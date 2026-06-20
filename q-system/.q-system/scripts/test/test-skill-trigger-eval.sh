#!/usr/bin/env bash
# H1: skill-trigger eval harness, OFFLINE (mocks claude -p). Pairs with issue skill-trigger-eval.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
H="$ROOT/q-system/.q-system/scripts/skill-trigger-eval.py"
fail() { echo "FAIL: $1" >&2; exit 1; }

# mock claude: prints the FIRED marker when the prompt contains 'yes', else not
MOCK="$(mktemp -d)/mockclaude"
printf '%s\n' '#!/usr/bin/env bash' 'case "$2" in *yes*) echo "skill FIRED here";; *) echo "nothing happened";; esac' > "$MOCK"
chmod +x "$MOCK"
FX="$(mktemp -d)"

# 1. all cases match should_trigger -> rate 1.00
cat > "$FX/testskill.json" <<'J'
{"skill":"testskill","fired_marker":"FIRED","cases":[
 {"prompt":"yes do it","should_trigger":true},
 {"prompt":"no thanks","should_trigger":false},
 {"prompt":"yes please","should_trigger":true}
]}
J
OUT="$(SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$MOCK" python3 "$H" testskill 2>&1)" || fail "harness errored: $OUT"
echo "$OUT" | grep -q "trigger_rate=1.00" || fail "expected trigger_rate=1.00, got: $OUT"
echo "$OUT" | grep -qi "ADVISORY" || fail "missing advisory note"

# 2. a should_trigger=false case that fires -> rate drops to 0.50
cat > "$FX/testskill.json" <<'J'
{"skill":"testskill","fired_marker":"FIRED","cases":[
 {"prompt":"yes a","should_trigger":true},
 {"prompt":"yes b","should_trigger":false}
]}
J
OUT2="$(SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$MOCK" python3 "$H" testskill 2>&1)" || fail "harness errored (case2)"
echo "$OUT2" | grep -q "trigger_rate=0.50" || fail "expected 0.50 (one false-positive), got: $OUT2"

# 3. malformed fixture -> non-zero exit
printf '{"skill":"bad"}\n' > "$FX/bad.json"
SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$MOCK" python3 "$H" bad >/dev/null 2>&1 && fail "malformed fixture did not error" || true

# 4. the 4 real fixtures parse + run with a no-op mock (no live claude call)
NOOP="$(mktemp -d)/noop"; printf '%s\n' '#!/usr/bin/env bash' 'echo ""' > "$NOOP"; chmod +x "$NOOP"
for sk in founder-voice audhd-executive-function rca fable-discipline; do
  SKILL_EVAL_CLAUDE_CMD="$NOOP" python3 "$H" "$sk" >/dev/null 2>&1 || fail "real fixture $sk failed to parse/run"
done

# 5. broken/missing claude command -> clear error (exit 3), NOT a misleading low rate
printf '{"skill":"t","fired_marker":"FIRED","cases":[{"prompt":"yes","should_trigger":true}]}\n' > "$FX/t.json"
SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="/nonexistent/claude-xyz" python3 "$H" t >/dev/null 2>&1 && fail "broken claude binary did not error" || true

echo "PASS: trigger_rate computed, false-positive penalized, malformed rejected, all 4 real fixtures parse; broken-claude errors clearly (offline)"
