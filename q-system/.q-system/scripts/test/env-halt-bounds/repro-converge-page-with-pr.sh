#!/usr/bin/env bash
# PR #421 round 15, major: the same halt on an issue that ALREADY HAS AN OPEN PR
# (a rework round). converge read env_halt only in its no-PR branch, so with a
# PR it went on to the verdict logic and paged exit 7 or exit 5 every tick,
# blaming the review or the agent for a machine outage. Copy of
# repro-converge-page.sh with a gh that reports PR #77 for the branch.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd)"
CONV="$ROOT/q-system/.q-system/scripts/converge.sh"
LEDGER="$ROOT/q-system/.q-system/scripts/attempts-ledger.py"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/state/pr-reviews"

# fake gh: the branch already has open PR #77 (a rework round)
cat > "$WORK/bin/gh" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "pr" ] && [ "${2:-}" = "list" ]; then echo 77; fi
exit 0
EOF
chmod +x "$WORK/bin/gh"

# fake worker: EXACTLY what linear-worker.sh does on an environmental halt --
# claim the env_halt flag in the shared ledger, open no PR, exit 9.
cat > "$WORK/bin/halted-worker" <<EOF
#!/usr/bin/env bash
python3 "$LEDGER" "\$KIPI_STATE_DIR/linear-worker-attempts.json" claim-flag ASK-999 env_halt >/dev/null 2>&1
echo "ASK-999: NOT ATTEMPTED -- the runner itself is unavailable"
exit 9
EOF
chmod +x "$WORK/bin/halted-worker"

# recording notify sink
cat > "$WORK/bin/notify" <<'EOF'
#!/usr/bin/env bash
printf 'NOTIFY %s\n' "$*" >> "$NOTIFY_LOG"
exit 0
EOF
chmod +x "$WORK/bin/notify"

export PATH="$WORK/bin:$PATH"
export KIPI_STATE_DIR="$WORK/state"
export KIPI_CONVERGE_WORKER="$WORK/bin/halted-worker"
export KIPI_NOTIFY="$WORK/bin/notify"
export NOTIFY_LOG="$WORK/notify.log"
: > "$NOTIFY_LOG"

bash "$CONV" --issue ASK-999 --max-rounds 3 > "$WORK/out" 2>&1
RC=$?

echo "--- converge rc=$RC"
echo "--- converge said:"
grep -i 'NOT ATTEMPTED\|STOP exit' "$WORK/out" || true
echo "--- attempts ledger:"
cat "$WORK/state/linear-worker-attempts.json" 2>/dev/null || echo "(none)"
echo "--- pages fired for this machine-wide outage:"
cat "$NOTIFY_LOG"
N="$(grep -c '^NOTIFY ' "$NOTIFY_LOG" 2>/dev/null || echo 0)"
echo "--- page count: $N (expected 0 for a machine condition the worker already deduped)"
