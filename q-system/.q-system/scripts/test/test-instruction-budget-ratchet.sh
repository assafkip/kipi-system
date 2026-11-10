#!/usr/bin/env bash
# Tests for the instruction-budget ratchet (ASK-285).
#
# THE DEADLOCK THIS SUITE EXISTS FOR. Two gates were mutually exclusive:
#   Gate A  instruction-budget --ratchet (lefthook pre-commit) allowed ZERO net
#           growth in always-on instruction lines.
#   Gate B  apply_claude_changes.py, the only sanctioned write path into
#           .claude/, cannot express a removal -- and its line census refuses to
#           let a `replace` SHORTEN a rule, and _guard_frontmatter refuses a
#           frontmatter change by ANY op, so it cannot scope a rule either.
# So every non-empty append to a .claude/rules/*.md file added at least one
# always-on line, Gate A demanded an offsetting removal, and Gate B could
# perform neither a removal nor a scope. Every rule append was unlandable.
#
# The fix is in the ACCOUNTING, not in the write path's vocabulary (DoR option
# b). The baseline's one number became two: `cap` (the gate) and
# `total_always_on` (last observed total). A drop is classified:
#   scoping  -- a rule moved from always-on to paths-scoped. Its text is still
#               on disk, so the cap HOLDS and the freed lines become headroom.
#   deletion -- lines left the tree. The cap follows down, permanently.
# cap only ever moves by -deletion_delta, so it is monotone non-increasing by
# construction: the floor may tighten, never loosen.
#
# Every case builds a THROWAWAY fixture root under mktemp and runs a COPY of the
# audit script from inside it, so the script's own __file__-derived root resolves
# to the fixture. No case reads or writes the repo's real .claude/ or baseline
# (fable-discipline test isolation).
#
# REF HATCH: point the suite at a pre-fix audit to watch a case fail.
#   git show <ref>:q-system/.q-system/scripts/instruction-budget-audit.py > /tmp/old-audit.py
#   BUDGET_AUDIT=/tmp/old-audit.py bash <this script>
# Sections 3, 6 and 7 were each observed RED against origin/main this way.
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
AUDIT="${BUDGET_AUDIT:-$SCRIPT_DIR/../instruction-budget-audit.py}"
ENGINE="${APPLY_ENGINE:-$SCRIPT_DIR/../apply_claude_changes.py}"
PASS=0
FAIL=0

ok()  { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

# check <name> <expected-exit> <expected-substring> <actual-exit> <actual-output>
check() {
  local name="$1" want_rc="$2" want_sub="$3" got_rc="$4" got_out="$5"
  if [ "$got_rc" != "$want_rc" ]; then
    bad "$name (exit $got_rc, wanted $want_rc) :: $got_out"; return
  fi
  case "$got_out" in
    *"$want_sub"*) ok "$name" ;;
    *) bad "$name (missing '$want_sub') :: $got_out" ;;
  esac
}

# A rule body of exactly N substantive lines, no frontmatter => always-on.
rule_body() {  # rule_body <n> <tag>
  local n="$1" tag="$2" i
  echo "# Rule $tag"
  for ((i = 2; i <= n; i++)); do echo "line $i of $tag"; done
}

mk_fixture() {  # mk_fixture <root>
  local r="$1"
  mkdir -p "$r/.claude/rules" "$r/q-system/.q-system/scripts" "$r/q-system/output"
  cp "$AUDIT" "$r/q-system/.q-system/scripts/instruction-budget-audit.py"
  printf '# Project\nOne instruction line.\n' > "$r/CLAUDE.md"
  rule_body 10 alpha > "$r/.claude/rules/alpha.md"
  rule_body 6  beta  > "$r/.claude/rules/beta.md"
  # Already paths-scoped: costs zero always-on lines from the start.
  { echo "---"; echo "paths:"; echo '  - "**/*.html"'; echo "---";
    rule_body 20 gamma; } > "$r/.claude/rules/gamma.md"
}

audit() {  # audit <root> [args...]
  local r="$1"; shift
  python3 "$r/q-system/.q-system/scripts/instruction-budget-audit.py" "$@" 2>&1
}

baseline_of() {  # baseline_of <root>
  cat "$1/q-system/.q-system/instruction-budget-baseline.json"
}

jq_num() {  # jq_num <root> <key>
  python3 - "$1" "$2" <<'PY'
import json, sys
with open(sys.argv[1] + "/q-system/.q-system/instruction-budget-baseline.json") as fh:
    print(json.load(fh).get(sys.argv[2], "MISSING"))
PY
}

# ---------------------------------------------------------------------------
echo "== 1. a fresh tree creates its own baseline"
R=$(mktemp -d); mk_fixture "$R"
OUT=$(audit "$R" --ratchet); RC=$?
# CLAUDE.md 2 + alpha 10 + beta 6 = 18 always-on; gamma is scoped.
check "baseline created at the observed total" 0 "18" "$RC" "$OUT"
check "cap recorded" 0 "18" "0" "$(jq_num "$R" cap)"
rm -rf "$R"

# ---------------------------------------------------------------------------
echo "== 2. a bare append with no headroom is refused"
R=$(mktemp -d); mk_fixture "$R"
audit "$R" --ratchet >/dev/null
echo "one more always-on line" >> "$R/.claude/rules/beta.md"
OUT=$(audit "$R" --ratchet); RC=$?
check "append over the cap fails" 1 "RATCHET FAIL" "$RC" "$OUT"
check "cap unchanged by a refused commit" 0 "18" "0" "$(jq_num "$R" cap)"
rm -rf "$R"

# ---------------------------------------------------------------------------
echo "== 3. THE DoR CHECK: scoping banks headroom, an append then lands"
R=$(mktemp -d); mk_fixture "$R"
audit "$R" --ratchet >/dev/null
# Move alpha (10 lines) from always-on to paths-scoped. Nothing is deleted:
# every line of alpha.md is still on disk.
{ echo "---"; echo "paths:"; echo '  - "**/*.py"'; echo "---";
  rule_body 10 alpha; } > "$R/.claude/rules/alpha.md"
OUT=$(audit "$R" --ratchet); RC=$?
check "scoping holds the cap" 0 "cap 18" "$RC" "$OUT"
check "cap did NOT follow the total down" 0 "18" "0" "$(jq_num "$R" cap)"
check "headroom is reported" 0 "headroom 10" "$RC" "$OUT"
# Now the append the deadlock made impossible: one line, no deletion anywhere.
echo "one more always-on line" >> "$R/.claude/rules/beta.md"
OUT=$(audit "$R" --ratchet); RC=$?
check "an append inside banked headroom passes" 0 "RATCHET PASS" "$RC" "$OUT"
check "spending headroom does not move the cap" 0 "18" "0" "$(jq_num "$R" cap)"
rm -rf "$R"

# ---------------------------------------------------------------------------
echo "== 4. a deletion lowers the cap permanently"
R=$(mktemp -d); mk_fixture "$R"
audit "$R" --ratchet >/dev/null
rule_body 6 alpha > "$R/.claude/rules/alpha.md"   # 10 -> 6 lines: 4 deleted
OUT=$(audit "$R" --ratchet); RC=$?
check "deletion tightens the cap" 0 "tightened" "$RC" "$OUT"
check "cap followed the deletion down" 0 "14" "0" "$(jq_num "$R" cap)"
# Putting those 4 lines back is now a regression against the tightened cap.
rule_body 10 alpha > "$R/.claude/rules/alpha.md"
OUT=$(audit "$R" --ratchet); RC=$?
check "re-adding deleted lines is refused" 1 "RATCHET FAIL" "$RC" "$OUT"
rm -rf "$R"

# ---------------------------------------------------------------------------
echo "== 5. a deleted rule FILE is a deletion, not a scoping"
R=$(mktemp -d); mk_fixture "$R"
audit "$R" --ratchet >/dev/null
rm "$R/.claude/rules/beta.md"                      # 6 always-on lines gone
OUT=$(audit "$R" --ratchet); RC=$?
check "a vanished rule tightens the cap" 0 "tightened" "$RC" "$OUT"
check "cap followed it down" 0 "12" "0" "$(jq_num "$R" cap)"
rm -rf "$R"

# ---------------------------------------------------------------------------
echo "== 6. CLAUDE.md shrinking is a deletion too"
R=$(mktemp -d); mk_fixture "$R"
audit "$R" --ratchet >/dev/null
printf '# Project\n' > "$R/CLAUDE.md"              # 2 -> 1
OUT=$(audit "$R" --ratchet); RC=$?
check "CLAUDE.md deletion tightens the cap" 0 "tightened" "$RC" "$OUT"
check "cap followed it down" 0 "17" "0" "$(jq_num "$R" cap)"
rm -rf "$R"

# ---------------------------------------------------------------------------
echo "== 7. a legacy single-number baseline migrates without loosening"
R=$(mktemp -d); mk_fixture "$R"
printf '{\n  "total_always_on": 18\n}\n' > "$R/q-system/.q-system/instruction-budget-baseline.json"
OUT=$(audit "$R" --ratchet); RC=$?
check "legacy baseline is read as its own cap" 0 "cap 18" "$RC" "$OUT"
check "cap adopted from total_always_on" 0 "18" "0" "$(jq_num "$R" cap)"
rm -rf "$R"

# ---------------------------------------------------------------------------
echo "== 8. --root points the audit at another tree"
R=$(mktemp -d); mk_fixture "$R"
OUT=$(python3 "$AUDIT" --root "$R" --rules-total); RC=$?
check "rules-only always-on total for a foreign root" 0 "16" "$RC" "$OUT"
OUT=$(python3 "$AUDIT" --root "$R" --rules-cap); RC=$?
check "no baseline yet prints none" 0 "none" "$RC" "$OUT"
audit "$R" --ratchet >/dev/null
# cap 18 minus the fixture's 2 CLAUDE.md lines: the same unit as --rules-total.
OUT=$(python3 "$AUDIT" --root "$R" --rules-cap); RC=$?
check "rules-only cap from the foreign baseline" 0 "16" "$RC" "$OUT"
rm -rf "$R"

# ---------------------------------------------------------------------------
echo "== 9. the sanctioned route refuses an append it cannot pay for"
R=$(mktemp -d); mk_fixture "$R"
mkdir -p "$R/.claude"
printf '{"hooks":{}}\n' > "$R/.claude/settings.json"
audit "$R" --ratchet >/dev/null
cat > "$R/prop.json" <<'JSON'
{
  "schema_version": 1,
  "slug": "append-one-always-on-line",
  "reason": "ASK-285 reproducer: one appended line into an always-on rule",
  "edits": [
    {"file": ".claude/rules/beta.md", "op": "append",
     "insert": "one more always-on line\n", "reason": "the append the deadlock blocked"}
  ]
}
JSON
OUT=$(python3 "$ENGINE" "$R/prop.json" --root "$R" 2>&1); RC=$?
check "over-cap append is refused up front" 2 "instruction budget" "$RC" "$OUT"
if grep -q "one more always-on line" "$R/.claude/rules/beta.md"; then
  bad "refused append left its line on disk"
else
  ok "refused append wrote nothing"
fi
rm -rf "$R"

# ---------------------------------------------------------------------------
echo "== 10. the route still applies an append that costs no always-on lines"
R=$(mktemp -d); mk_fixture "$R"
printf '{"hooks":{}}\n' > "$R/.claude/settings.json"
audit "$R" --ratchet >/dev/null
cat > "$R/prop.json" <<'JSON'
{
  "schema_version": 1,
  "slug": "append-to-a-scoped-rule",
  "reason": "ASK-285: a paths-scoped rule costs zero always-on lines",
  "edits": [
    {"file": ".claude/rules/gamma.md", "op": "append",
     "insert": "one more scoped line\n", "reason": "scoped rules stay editable"}
  ]
}
JSON
OUT=$(python3 "$ENGINE" "$R/prop.json" --root "$R" 2>&1); RC=$?
check "scoped-rule append still applies" 0 "OK applied" "$RC" "$OUT"
rm -rf "$R"

# ---------------------------------------------------------------------------
echo "== 11. the route applies an append that FITS the banked headroom"
R=$(mktemp -d); mk_fixture "$R"
printf '{"hooks":{}}\n' > "$R/.claude/settings.json"
audit "$R" --ratchet >/dev/null
{ echo "---"; echo "paths:"; echo '  - "**/*.py"'; echo "---";
  rule_body 10 alpha; } > "$R/.claude/rules/alpha.md"
audit "$R" --ratchet >/dev/null                     # banks 10 lines of headroom
cat > "$R/prop.json" <<'JSON'
{
  "schema_version": 1,
  "slug": "append-inside-headroom",
  "reason": "ASK-285: the append the two gates together made impossible",
  "edits": [
    {"file": ".claude/rules/beta.md", "op": "append",
     "insert": "one more always-on line\n", "reason": "paid for by banked headroom"}
  ]
}
JSON
OUT=$(python3 "$ENGINE" "$R/prop.json" --root "$R" 2>&1); RC=$?
check "append inside headroom applies" 0 "OK applied" "$RC" "$OUT"
OUT=$(audit "$R" --ratchet); RC=$?
check "and the same tree passes the ratchet" 0 "RATCHET PASS" "$RC" "$OUT"
rm -rf "$R"

# ---------------------------------------------------------------------------
echo "== 12. NEGATIVE CONTROL: removing a hook entry is still refused"
R=$(mktemp -d); mk_fixture "$R"
cat > "$R/.claude/settings.json" <<'JSON'
{
  "hooks": {
    "PostToolUse": [
      {"matcher": "Edit|Write",
       "hooks": [{"type": "command", "command": "python3 q-system/.q-system/scripts/existing-lint.py"}]}
    ]
  }
}
JSON
cp "$R/.claude/settings.json" "$R/settings-template.json"
echo "print('lint')" > "$R/q-system/.q-system/scripts/existing-lint.py"
audit "$R" --ratchet >/dev/null
# A `replace` aimed at the config surface: the only op that could rewrite a hook
# command. rule_text_only pins replace to .claude/rules/*.md, so this is refused
# before the budget is ever consulted -- the fix must not widen that.
cat > "$R/prop.json" <<'JSON'
{
  "schema_version": 1,
  "slug": "drop-a-hook-entry",
  "reason": "negative control: this must never be expressible",
  "requires": {"template_pairs": true},
  "edits": [
    {"file": ".claude/settings.json", "op": "replace",
     "anchor": "python3 q-system/.q-system/scripts/existing-lint.py",
     "insert": "true", "reason": "neuter the lint"}
  ]
}
JSON
OUT=$(python3 "$ENGINE" "$R/prop.json" --root "$R" 2>&1); RC=$?
check "hook removal is still refused" 2 "REFUSED" "$RC" "$OUT"
rm -rf "$R"

# ---------------------------------------------------------------------------
echo "== 13. MUTANT: cap that follows a scoping down puts section 3 back in the hole"
R=$(mktemp -d); mk_fixture "$R"
MUT="$R/q-system/.q-system/scripts/instruction-budget-audit.py"
# The whole fix is that a SCOPING does not move the cap. Cut that out: make
# every drop a deletion, which is exactly origin/main's behaviour.
python3 - "$MUT" <<'PY'
import re, sys
p = sys.argv[1]
src = open(p).read()
new = src.replace("cap_new = cap - deletion_delta", "cap_new = min(cap, total)")
assert new != src, "mutation point not found: the cap arithmetic moved"
open(p, "w").write(new)
PY
audit "$R" --ratchet >/dev/null
{ echo "---"; echo "paths:"; echo '  - "**/*.py"'; echo "---";
  rule_body 10 alpha; } > "$R/.claude/rules/alpha.md"
audit "$R" --ratchet >/dev/null
echo "one more always-on line" >> "$R/.claude/rules/beta.md"
OUT=$(audit "$R" --ratchet); RC=$?
check "mutant re-closes the door on the append" 1 "RATCHET FAIL" "$RC" "$OUT"
rm -rf "$R"

# ---------------------------------------------------------------------------
echo "== 14. MUTANT: engine without the budget precondition applies the unlandable append"
R=$(mktemp -d); mk_fixture "$R"
printf '{"hooks":{}}\n' > "$R/.claude/settings.json"
audit "$R" --ratchet >/dev/null
MUTE="$R/mutant-engine.py"
python3 - "$ENGINE" "$MUTE" <<'PY'
import sys
src = open(sys.argv[1]).read()
call = "\n        check_instruction_budget(root, copy_root, log)\n"
assert src.count(call) == 1, "mutation point not found: the budget precondition moved"
new = src.replace(call, "\n        pass\n")
open(sys.argv[2], "w").write(new)
PY
cat > "$R/prop.json" <<'JSON'
{
  "schema_version": 1,
  "slug": "append-one-always-on-line",
  "reason": "ASK-285 reproducer against a mutated engine",
  "edits": [
    {"file": ".claude/rules/beta.md", "op": "append",
     "insert": "one more always-on line\n", "reason": "the append the deadlock blocked"}
  ]
}
JSON
OUT=$(python3 "$MUTE" "$R/prop.json" --root "$R" 2>&1); RC=$?
check "mutant engine applies it" 0 "OK applied" "$RC" "$OUT"
OUT=$(audit "$R" --ratchet); RC=$?
check "and the commit is then impossible: the deadlock" 1 "RATCHET FAIL" "$RC" "$OUT"
rm -rf "$R"

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ]
