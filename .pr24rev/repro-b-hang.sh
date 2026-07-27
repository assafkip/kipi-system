#!/usr/bin/env bash
# REPRO B: the new fetch is the worker's only unbounded network call. Every other
# long operation in this script runs under run_bounded() (defined 10 lines above
# the fetch). A remote that ACCEPTS the connection and never answers -- a captive
# portal, a hung proxy, a firewall that blackholes an established session -- makes
# `git fetch` block forever. The worker then never picks an issue, never pages,
# and never exits: the exact "goes dark and nobody finds out" failure this PR
# exists to eliminate, relocated into the fix.
set -uo pipefail
REPO="/Users/assafkipnis/projects/kipi-system/.pr24rev/repo"
WORKER="$REPO/q-system/.q-system/scripts/linear-worker.sh"
REAL_PY="$(command -v python3)"
W="$(mktemp -d)"
G() { git -c user.email=t@t.t -c user.name=t "$@"; }

STUB="$W/bin"; mkdir -p "$STUB" "$W/home"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/gh"; chmod +x "$STUB/gh"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/claude"; chmod +x "$STUB/claude"
cat > "$W/notify.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$W/pages.txt"
EOF
chmod +x "$W/notify.sh"
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null; printf '%s\n' '{"ready":[{"id":"ASK-AAA","title":"t","project":"p"}],"total_open":1}'; exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
chmod +x "$STUB/python3"
export PATH="$STUB:$PATH"

# A listener that ACCEPTS and never speaks. This is a blackholing middlebox, not
# an unreachable host: git connects fine and then waits on a read that never comes.
"$REAL_PY" - "$W" <<'PY' &
import socket, sys, time
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", 0)); s.listen(8)
open(sys.argv[1] + "/port", "w").write(str(s.getsockname()[1]))
conns = []
t0 = time.time()
while time.time() - t0 < 120:
    s.settimeout(1)
    try: conns.append(s.accept()[0])   # accept, then say nothing at all
    except Exception: pass
PY
SRV=$!
while [ ! -s "$W/port" ]; do sleep 0.2; done
PORT="$(cat "$W/port")"

git init -q "$W/skel"
G -C "$W/skel" commit -q --allow-empty -m c1
git -C "$W/skel" branch -M main
git -C "$W/skel" remote add origin "git://127.0.0.1:$PORT/repo.git"
: > "$W/pages.txt"

echo "starting the worker against a blackholing origin on port $PORT ..."
( cd "$W/skel" && HOME="$W/home" KIPI_SKEL="$W/skel" KIPI_STATE_DIR="$W/state" \
  KIPI_NOTIFY="$W/notify.sh" bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) > "$W/out" 2>&1 &
JOB=$!

for i in 1 2 3 4 5 6; do
  sleep 5
  if ! kill -0 "$JOB" 2>/dev/null; then
    wait "$JOB"; echo "worker EXITED after ~$((i*5))s with rc=$?"; break
  fi
  echo "  t=$((i*5))s: worker still alive; pages so far=$(wc -l < "$W/pages.txt" | tr -d ' '); log=$(cat "$W/out" 2>/dev/null | tail -1)"
done

if kill -0 "$JOB" 2>/dev/null; then
  echo "RESULT: after 30s the worker is STILL BLOCKED in git fetch."
  echo "        pages sent: $(wc -l < "$W/pages.txt" | tr -d ' ')   (nobody has been told)"
  echo "        worktrees cut: $(ls "$W/state/worktrees" 2>/dev/null | wc -l | tr -d ' ')"
  echo "        run_bounded() is defined at line $(grep -n '^run_bounded' "$WORKER" | cut -d: -f1) and is NOT applied to the fetch at line $(grep -n 'SKEL\" fetch' "$WORKER" | cut -d: -f1)"
  kill -9 "$JOB" 2>/dev/null
fi
kill -9 "$SRV" 2>/dev/null
wait 2>/dev/null
