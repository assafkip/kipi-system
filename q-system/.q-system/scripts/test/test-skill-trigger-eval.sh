#!/usr/bin/env bash
# H1: skill-trigger eval harness, OFFLINE (mocks claude -p). Pairs with issue skill-trigger-eval.
# Mocks speak stream-json, the format the harness reads tool calls from: argv is
# `-p <prompt> --output-format stream-json --verbose`, so the prompt is "$2".
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
H="$ROOT/q-system/.q-system/scripts/skill-trigger-eval.py"
fail() { echo "FAIL: $1" >&2; exit 1; }

# mock claude: calls the Skill tool with "FIRED" when the prompt contains 'yes'
MOCK="$(mktemp -d)/mockclaude"
cat > "$MOCK" <<'M'
#!/usr/bin/env bash
case "$2" in
  *yes*) echo '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"FIRED"}}]}}';;
esac
echo '{"type":"result","subtype":"success","result":"done"}'
M
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

# 4. the real fixtures parse + run with a no-op mock (no live claude call).
#    The no-op is a successful run that called no tool: one result event.
NOOP="$(mktemp -d)/noop"
cat > "$NOOP" <<'M'
#!/usr/bin/env bash
echo '{"type":"result","subtype":"success","result":""}'
M
chmod +x "$NOOP"
for sk in founder-voice audhd-executive-function rca fable-discipline dev-skills-auto-invoke; do
  SKILL_EVAL_CLAUDE_CMD="$NOOP" python3 "$H" "$sk" >/dev/null 2>&1 || fail "real fixture $sk failed to parse/run"
done

# 6. A rule naming SEVERAL skills needs several markers (Codex PR #238, major).
#    A list is any-of. Before this, a fixture expressed the alternatives as one
#    "a|b|c" string, `marker in output` matched it literally, and every correct
#    invocation scored as a miss -- an advisory eval reporting 0.00 forever.
#    The mock calls a plugin-namespaced skill: the namespace is stripped.
MULTI="$(mktemp -d)/multi"
cat > "$MULTI" <<'M'
#!/usr/bin/env bash
case "$2" in
  *yes*) echo '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"plugin-dev:mcp-builder"}}]}}';;
esac
echo '{"type":"result","subtype":"success","result":"done"}'
M
chmod +x "$MULTI"
cat > "$FX/multi.json" <<'J'
{"skill":"multi","fired_marker":["skill-creator","mcp-builder","claude-api"],"cases":[
 {"prompt":"yes do it","should_trigger":true},
 {"prompt":"no thanks","should_trigger":false}
]}
J
OUT6="$(SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$MULTI" python3 "$H" multi 2>&1)" || fail "list marker errored: $OUT6"
echo "$OUT6" | grep -q "trigger_rate=1.00" || fail "expected 1.00 for any-of list marker, got: $OUT6"

# 7. A per-case marker narrows the any-of list, so invoking the WRONG skill of
#    the set scores as a miss. Without this, a 6-skill rule cannot tell "fired"
#    from "fired the right one" and the eval measures almost nothing.
cat > "$FX/percase.json" <<'J'
{"skill":"percase","fired_marker":["skill-creator","mcp-builder"],"cases":[
 {"prompt":"yes build a skill","should_trigger":true,"fired_marker":"skill-creator"}
]}
J
OUT7="$(SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$MULTI" python3 "$H" percase 2>&1)" || fail "per-case marker errored: $OUT7"
echo "$OUT7" | grep -q "trigger_rate=0.00" || fail "expected 0.00 (mcp-builder fired, skill-creator expected), got: $OUT7"

# 8. The bug itself is refused rather than silently mismeasured: a marker
#    carrying '|' looks like alternation and is not, so no future fixture can
#    smuggle a fake regex past a literal match.
printf '{"skill":"p","fired_marker":"a|b","cases":[{"prompt":"yes","should_trigger":true}]}\n' > "$FX/p.json"
SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$MULTI" python3 "$H" p >/dev/null 2>&1 && fail "pipe-separated marker was accepted as a literal" || true

# 9. Negative self-test for 8: an empty marker list is refused too, otherwise
#    `any([])` is False and every case silently scores as "did not fire".
printf '{"skill":"e","fired_marker":[],"cases":[{"prompt":"yes","should_trigger":true}]}\n' > "$FX/e.json"
SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$MULTI" python3 "$H" e >/dev/null 2>&1 && fail "empty marker list was accepted" || true

# 5. broken/missing claude command -> clear error (exit 3), NOT a misleading low rate
printf '{"skill":"t","fired_marker":"FIRED","cases":[{"prompt":"yes","should_trigger":true}]}\n' > "$FX/t.json"
SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="/nonexistent/claude-xyz" python3 "$H" t >/dev/null 2>&1 && fail "broken claude binary did not error" || true

# 10. A claude that EXISTS and is executable but fails every call is the same
#     class as case 5, and case 5 could not see it: claude_runnable() passes on
#     /usr/bin/false, then every invocation exits nonzero with no output and the
#     old run_case returned "" for each. Three negative cases scored as correct
#     and the harness published trigger_rate=0.38 -- total infrastructure
#     failure wearing the shape of a model measurement (Codex PR #238 round 3).
BROKEN="$(mktemp -d)/broken"
printf '%s\n' '#!/usr/bin/env bash' 'echo "auth error" >&2' 'exit 1' > "$BROKEN"
chmod +x "$BROKEN"
OUT10="$(SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$BROKEN" python3 "$H" t 2>&1 || true)"
echo "$OUT10" | grep -q "trigger_rate=" && fail "a failing claude still published a trigger_rate: $OUT10"
SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$BROKEN" python3 "$H" t >/dev/null 2>&1 && fail "a claude that fails every call did not error" || true

# 11. Negative self-test for 10: a successful run that called no Skill tool is a
#     real measurement ("the skill did not fire"), not an infrastructure error.
#     A fix that treated a quiet run as failure would refuse every honest
#     negative case and the eval could never score should_trigger=false again.
printf '{"skill":"n","fired_marker":"FIRED","cases":[{"prompt":"no","should_trigger":false}]}\n' > "$FX/n.json"
OUT11="$(SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$NOOP" python3 "$H" n 2>&1)" || fail "quiet-but-successful claude errored: $OUT11"
echo "$OUT11" | grep -q "trigger_rate=1.00" || fail "expected 1.00 (no Skill call is a valid non-trigger), got: $OUT11"

# 12. A skill NAMED in the final text is not a skill INVOKED (Codex PR #238
#     round 4, major). The model said "I did not invoke skill-creator." and the
#     substring engine scored it as fired: trigger_rate=1.00 for work that never
#     happened. Only a tool call in the event stream counts.
PROSE="$(mktemp -d)/prose"
printf '%s\n' '#!/usr/bin/env bash' 'echo "{\"type\":\"result\",\"subtype\":\"success\",\"result\":\"I did not invoke skill-creator.\"}"' > "$PROSE"
chmod +x "$PROSE"
printf '{"skill":"sc","fired_marker":"skill-creator","cases":[{"prompt":"yes","should_trigger":true}]}\n' > "$FX/sc.json"
OUT12="$(SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$PROSE" python3 "$H" sc 2>&1)" || fail "prose-only claude errored: $OUT12"
echo "$OUT12" | grep -q "trigger_rate=0.00" || fail "a skill named only in prose scored as invoked: $OUT12"

# 13. Negative self-test for 12: a Read of <skill>/SKILL.md IS a load, the path
#     fable-discipline's fixture relies on. A fix that counted only the Skill
#     tool would score every such case as a miss.
READER="$(mktemp -d)/reader"
cat > "$READER" <<'M'
#!/usr/bin/env bash
echo '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{"file_path":"/x/plugins/p/skills/skill-creator/SKILL.md"}}]}}'
echo '{"type":"result","subtype":"success","result":"done"}'
M
chmod +x "$READER"
OUT13="$(SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$READER" python3 "$H" sc 2>&1)" || fail "SKILL.md reader errored: $OUT13"
echo "$OUT13" | grep -q "trigger_rate=1.00" || fail "a Read of SKILL.md did not count as a load: $OUT13"

# 14. rc 0 with NO stream events cannot be observed, so it is refused (exit 3)
#     rather than scored: counting it as "did not fire" would credit every
#     should_trigger=false case for a run whose tool calls nobody saw.
EMPTY="$(mktemp -d)/empty"
printf '%s\n' '#!/usr/bin/env bash' 'echo ""' > "$EMPTY"
chmod +x "$EMPTY"
RC14=0; OUT14="$(SKILL_EVAL_DIR="$FX" SKILL_EVAL_CLAUDE_CMD="$EMPTY" python3 "$H" n 2>&1)" || RC14=$?
[ "$RC14" = 3 ] || fail "an unobservable run did not exit 3 (rc=$RC14): $OUT14"
echo "$OUT14" | grep -q "trigger_rate=" && fail "an unobservable run published a trigger_rate: $OUT14"

echo "PASS: trigger_rate computed, false-positive penalized, malformed rejected, all 5 real fixtures parse; any-of marker list + per-case narrowing work; pipe-separated and empty markers refused; broken-claude and failing-claude error clearly, quiet-but-successful still measures; prose mentions do not count, Skill and SKILL.md-Read calls do, an event-less run is refused (offline)"
