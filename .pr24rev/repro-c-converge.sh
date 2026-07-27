#!/usr/bin/env bash
# REPRO C: the new exit 9 has a consumer that ignores it. converge.sh captures
# the worker's rc into WRC and never branches on it. So after this PR, a dead
# network makes converge page the founder with a diagnosis that blames Sana.
#
# Uses converge.sh's OWN documented test seams (KIPI_CONVERGE_WORKER, KIPI_NOTIFY,
# KIPI_STATE_DIR) plus a gh stub, so nothing here is invented shape: the fake
# worker returns exactly what the real worker on this branch returns when
# `git fetch` fails -- rc 9, no commit, no new PR.
set -uo pipefail
REPO="/Users/assafkipnis/projects/kipi-system/.pr24rev/repo"
CONV="$REPO/q-system/.q-system/scripts/converge.sh"
W="$(mktemp -d)"
STUB="$W/bin"; mkdir -p "$STUB" "$W/state/pr-reviews"

# Exactly the real worker's fetch-failure behaviour on this branch: page, exit 9.
cat > "$W/fake-worker.sh" <<EOF
#!/usr/bin/env bash
bash "$W/notify.sh" "worker: git fetch failed -- the run did NO work. Check credentials/network."
exit 9
EOF
chmod +x "$W/fake-worker.sh"
cat > "$W/notify.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$W/pages.txt"
EOF
chmod +x "$W/notify.sh"

# --- scenario 1: a PR already exists (the rework case: this is how the worker
#     gets re-dispatched at all, per the severity-floor gate) -----------------
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"pr list"*)  echo 77 ;;
  *"pr view"*)  echo deadbeefdeadbeefdeadbeefdeadbeefdeadbeef ;;
esac
exit 0
EOF
chmod +x "$STUB/gh"
export PATH="$STUB:$PATH"
printf '{"verdict":"REQUEST CHANGES"}\n' > "$W/state/pr-reviews/pr-77.verdict.json"
: > "$W/pages.txt"

KIPI_STATE_DIR="$W/state" KIPI_NOTIFY="$W/notify.sh" \
  KIPI_CONVERGE_WORKER="bash $W/fake-worker.sh" \
  bash "$CONV" --issue ASK-AAA --max-rounds 4 > "$W/out1" 2>&1
RC1=$?
echo "SCENARIO 1 (PR exists, worker exits 9 on a dead network)"
echo "  converge rc = $RC1"
echo "  rounds it burned: $(grep -c 'dispatching Sana' "$W/out1")"
echo "  pages the founder got:"
sed 's/^/    - /' "$W/pages.txt"
echo "  converge's own last line:"
tail -1 "$W/out1" | sed 's/^/    /'

# --- scenario 2: no PR yet (the first-round case) --------------------------
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$STUB/gh"
: > "$W/pages.txt"
KIPI_STATE_DIR="$W/state" KIPI_NOTIFY="$W/notify.sh" \
  KIPI_CONVERGE_WORKER="bash $W/fake-worker.sh" \
  bash "$CONV" --issue ASK-BBB --max-rounds 4 > "$W/out2" 2>&1
RC2=$?
echo
echo "SCENARIO 2 (no PR yet, worker exits 9 on a dead network)"
echo "  converge rc = $RC2"
echo "  pages the founder got:"
sed 's/^/    - /' "$W/pages.txt"
echo "  converge's own last line:"
tail -1 "$W/out2" | sed 's/^/    /'

echo
echo "converge.sh's handling of the worker rc:"
grep -n 'WRC' "$CONV" | sed 's/^/  /'
