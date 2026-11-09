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
hook() {  # hook <floor-json-value> -> "DENY|ALLOW <rc> <deny text>" or "CRASH ..."
python3 - "$SCRIPTS/worktree-disk-floor.py" "$1" <<'PY'
import importlib.util, io, json, sys
spec = importlib.util.spec_from_file_location("floor", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class FakeReaper:
    DEFAULTS = {"refuse_worktree_below_gb": 5}
    @staticmethod
    def load_config():
        return {"refuse_worktree_below_gb": json.loads(sys.argv[2])}
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
d = json.loads(out)["hookSpecificOutput"] if out else {}
print("DENY" if d.get("permissionDecision") == "deny" else "ALLOW", rc, d.get("permissionDecisionReason", ""))
PY
}
for v in '"5 GB"' '"nan"' '-1' 'null'; do
  OUT="$(hook "$v")"
  case "$OUT" in
    "DENY 0 "*"not a usable number"*) ok "case 1 [$v]: the floor stays on at the default, and the refusal says the value was ignored" ;;
    *) bad "case 1 [$v]: the floor stays on at the default and says so" "got: ${OUT:0:160}" ;;
  esac
done
OUT="$(hook '0')"
case "$OUT" in "ALLOW 0"*) ok "case 1e: an explicit 0 is still the off switch" ;; *) bad "case 1e: 0 is the off switch" "got: ${OUT:0:120}" ;; esac

# --- 2: the worker's line on reviewer exit 9 -----------------------------------
BLOCK="$WORK/block.sh"
awk '/NAME THE CAUSE \(ASK-4039/{on=1} on{print} on && /^      fi$/{exit}' "$SCRIPTS/linear-worker.sh" > "$BLOCK"
run_block() {  # run_block <reviewer stderr line> -> the line the block says
  printf 'earlier run: ENV: disk-floor: from an older review\n' > "$WORK/worker.log"
  FROM=$(( $(wc -l < "$WORK/worker.log") + 1 ))
  printf '%s\n' "$1" >> "$WORK/worker.log"
  ( SCRIPT_DIR="$SCRIPTS"; LOG="$WORK/worker.log"; REVIEW_LOG_FROM=$FROM; ISSUE=ASK-1; PR_NUM=7
    say() { echo "$*"; }
    . "$BLOCK" )
}
if [ -s "$BLOCK" ] && grep -q "ENV: disk-floor" "$BLOCK"; then
  U="$(run_block '  ENV: disk-floor: 1.0 GB free, floor 5 GB -> UNDER; no review tree for PR #7')"
  O="$(run_block 'claude: usage limit reached')"
  X="$(run_block '  ENV: disk-floor: 1.0 GB free, floor 5 GB -> UNDER; no review tree for PR #71')"
  printf '%s' "$U" | grep -q "disk is under the worktree floor" \
    && ok "case 2a: the reviewer's own disk-floor line makes the worker name the disk floor" \
    || bad "case 2a: the reviewer's disk-floor line names the disk" "got: $U"
  printf '%s' "$O" | grep -q "runner is unavailable" \
    && ok "case 2b: a runner refusal (and an older run's disk line) names the runner" \
    || bad "case 2b: a runner refusal names the runner" "got: $O"
  printf '%s' "$X" | grep -q "runner is unavailable" \
    && ok "case 2c: another worker's disk line (PR #71, not #7) in the shared log does not count" \
    || bad "case 2c: another PR's disk line does not count" "got: $X"
else
  bad "case 2: the cause-naming block is not in linear-worker.sh (anchors moved, or the fix is missing)"
fi

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" = "0" ]
