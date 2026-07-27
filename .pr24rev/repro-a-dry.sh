#!/usr/bin/env bash
# REPRO A: `kipi work` with NO --apply is documented "Dry by default: prints what
# it would pick and stops." After this PR a dry run performs a network fetch and,
# when that fetch fails, PAGES SLACK and exits 9 -- a preview command that alarms.
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

git init -q "$W/skel"
G -C "$W/skel" commit -q --allow-empty -m c1
git -C "$W/skel" branch -M main
git -C "$W/skel" remote add origin "$W/nowhere.git"   # unreachable, e.g. laptop offline
: > "$W/pages.txt"

# NO --apply. This is the preview a human types.
( cd "$W/skel" && HOME="$W/home" KIPI_SKEL="$W/skel" KIPI_STATE_DIR="$W/state" \
  KIPI_NOTIFY="$W/notify.sh" bash "$WORKER" ) > "$W/out" 2>&1
RC=$?

echo "dry-run rc = $RC   (documented dry contract: print what it would pick, stop)"
echo "pages sent from a DRY run: $(wc -l < "$W/pages.txt" | tr -d ' ')"
echo "page text: $(cat "$W/pages.txt")"
echo "stdout: $(cat "$W/out")"
