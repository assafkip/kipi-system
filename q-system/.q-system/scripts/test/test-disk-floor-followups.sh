#!/usr/bin/env bash
# Disk-floor follow-ups from PR #656 review round 3 (ASK-4039).
#
#   1. The PreToolUse hook path of worktree-disk-floor.py with a malformed floor
#      value ("5 GB") keeps the floor on at the default. Before, the comparison sat
#      outside the try, so it raised and exited 1 with no deny: it failed OPEN.
#   2. When the reviewer exits 9, the worker's line names the disk floor when that
#      is the cause, and the runner otherwise. Before, it always blamed the runner.
#
# Both cases drive the shipped code: case 1 loads the real script and replaces only
# its measurement; case 2 lifts the real block out of linear-worker.sh by its own
# markers and runs it.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SCRIPTS="$ROOT/q-system/.q-system/scripts"
PASS=0; FAIL=0
ok()  { PASS=$((PASS + 1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; [ -n "${2:-}" ] && printf '       %s\n' "$2"; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "== disk-floor follow-ups (ASK-4039)"

# --- 1: the hook path with a malformed floor -----------------------------------
OUT="$(python3 - "$SCRIPTS/worktree-disk-floor.py" <<'PY'
import importlib.util, io, json, sys
spec = importlib.util.spec_from_file_location("floor", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class FakeReaper:
    DEFAULTS = {"refuse_worktree_below_gb": 5}
    @staticmethod
    def load_config():
        return {"refuse_worktree_below_gb": "5 GB"}   # the hand-edit a person makes
    @staticmethod
    def free_gb():
        return 1.0                                  # under the default floor
m._reaper = lambda: FakeReaper
sys.stdin = io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "git worktree add /x"}}))
buf = io.StringIO(); real = sys.stdout; sys.stdout = buf
try:
    rc = m.main()
except Exception as exc:
    sys.stdout = real; print("CRASH", repr(exc)); sys.exit(0)
sys.stdout = real
out = buf.getvalue().strip()
print("DENY" if out and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny" else "ALLOW", rc)
PY
)"
case "$OUT" in
  "DENY 0") ok "case 1: a malformed floor keeps the floor on; 1 GB free under the 5 GB default is refused" ;;
  *) bad "case 1: a malformed floor keeps the floor on" "got: $OUT" ;;
esac

# --- 2: the worker's line on reviewer exit 9 -----------------------------------
BLOCK="$WORK/block.sh"
awk '/NAME THE CAUSE \(ASK-4039/{on=1} on{print} on && /^      fi$/{exit}' "$SCRIPTS/linear-worker.sh" > "$BLOCK"
cfg() { printf '{"roots": [], "min_idle_hours": 6, "alarm_below_gb": 0, "refuse_worktree_below_gb": %s}' "$1" > "$WORK/floor.json"; }
run_block() {  # run_block <floor-gb> -> the line the block says
  cfg "$1"
  ( SCRIPT_DIR="$SCRIPTS"; LOG=/dev/null; ISSUE=ASK-1; PR_NUM=7
    say() { echo "$*"; }
    export KIPI_WORKTREE_REAPER_CONFIG="$WORK/floor.json"
    . "$BLOCK" )
}
if [ -s "$BLOCK" ] && grep -q "worktree-disk-floor.py" "$BLOCK"; then
  U="$(run_block 1000000)"; O="$(run_block 0)"
  printf '%s' "$U" | grep -q "disk is under the worktree floor" \
    && ok "case 2a: under the floor, the line names the disk floor" \
    || bad "case 2a: under the floor, the line names the disk floor" "got: $U"
  printf '%s' "$O" | grep -q "runner is unavailable" \
    && ok "case 2b: over the floor, the line names the runner" \
    || bad "case 2b: over the floor, the line names the runner" "got: $O"
else
  bad "case 2: the cause-naming block is not in linear-worker.sh (anchors moved, or the fix is missing)"
fi

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" = "0" ]
