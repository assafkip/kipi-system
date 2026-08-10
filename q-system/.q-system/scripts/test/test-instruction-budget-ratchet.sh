#!/usr/bin/env bash
# Tests for the instruction-budget ratchet and its pairing with the sanctioned
# .claude/ write path (ASK-285).
#
# THE DEADLOCK THESE PIN OPEN. Two gates were individually correct and jointly
# impossible: the ratchet allowed zero net growth of always-on instruction lines,
# and apply_claude_changes.py -- the only sanctioned write path into .claude/ --
# is additive-only and refuses every frontmatter change, so through that route the
# always-on total can never drop. Every rule-file append it could express was
# therefore uncommittable, and the only escape was to find unrelated dead weight
# somewhere else and delete it (PR #48 did, by luck).
#
# The fix is in the ratchet's ACCOUNTING, never in the write path's vocabulary:
# a drop is classified as scoping (cap holds, headroom banked) or deletion (cap
# follows down, permanently). Sections 6-9 are the negative controls that hold
# that line -- if any of them goes green-when-it-should-fail, the fix has turned
# into a loosening.
#
# Every case builds a THROWAWAY fixture root under mktemp and points both scripts
# at it with --root. No case reads or writes the repo's real .claude/ or its real
# instruction-budget-baseline.json.
#
# Ref hatch: point either script at a pre-fix copy to watch a case fail.
#   git show HEAD~1:q-system/.q-system/scripts/instruction-budget-audit.py > /tmp/old-audit.py
#   BUDGET_AUDIT=/tmp/old-audit.py bash <this script>
#   git show HEAD~1:q-system/.q-system/scripts/apply_claude_changes.py > /tmp/old-engine.py
#   APPLY_ENGINE=/tmp/old-engine.py bash <this script>
# A regression case never watched fail is not known to catch anything.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
AUDIT="${BUDGET_AUDIT:-$SCRIPT_DIR/../instruction-budget-audit.py}"
WRAPPER="$SCRIPT_DIR/../apply-claude-changes.sh"
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

# check_num <name> <expected> <actual>
check_num() {
  if [ "$2" = "$3" ]; then ok "$1 == $2"; else bad "$1 (got $3, wanted $2)"; fi
}

audit() {  # audit <root> [extra args...]
  local r="$1"; shift
  python3 "$AUDIT" --ratchet --root "$r" "$@" 2>&1 || true
}

audit_rc() {  # audit_rc <root>; sets AUDIT_OUT / AUDIT_RC
  local r="$1"; shift
  set +e
  AUDIT_OUT=$(python3 "$AUDIT" --ratchet --root "$r" "$@" 2>&1)
  AUDIT_RC=$?
  set -e
}

# The DoR words the check as "applies cleanly through apply-claude-changes.sh",
# so the default path is the wrapper. APPLY_ENGINE swaps in a bare engine copy
# for the ref hatch and the mutation cases; the wrapper hardcodes its own engine
# and cannot be redirected.
apply() {  # apply <proposal> <root>; sets APPLY_OUT / APPLY_RC
  set +e
  if [ -n "${APPLY_ENGINE:-}" ]; then
    APPLY_OUT=$(KIPI_NOTIFY=/usr/bin/true python3 "$APPLY_ENGINE" "$1" --root "$2" 2>&1)
  else
    APPLY_OUT=$(bash "$WRAPPER" "$1" --root "$2" 2>&1)
  fi
  APPLY_RC=$?
  set -e
}

cap_of()      { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["cap"])' "$1/q-system/.q-system/instruction-budget-baseline.json"; }
total_of()    { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["total_always_on"])' "$1/q-system/.q-system/instruction-budget-baseline.json"; }

# ---------------------------------------------------------------- fixtures
#
# Line arithmetic is fixed and small on purpose, so every expected number below
# is checkable by hand:
#   CLAUDE.md          3 substantive lines
#   rules/alpha.md    10 substantive lines, no frontmatter -> always-on
#   rules/beta.md     20 substantive lines, no frontmatter -> always-on
#   always-on total = 3 + 10 + 20 = 33
mk_fixture() {  # mk_fixture <root>
  local r="$1" i
  mkdir -p "$r/.claude/rules" "$r/q-system/.q-system/scripts" "$r/q-system/output"
  printf '# Fixture root\n\nOne behavioural line.\n\nAnother behavioural line.\n' > "$r/CLAUDE.md"

  { echo "# Alpha Rule (ENFORCED)"; echo
    echo "The deterministic half is \`alpha-lint.py\`."; echo
    for i in $(seq 1 8); do echo "Alpha line $i."; echo; done
  } > "$r/.claude/rules/alpha.md"

  { echo "# Beta Rule (ENFORCED)"; echo
    echo "The deterministic half is \`beta-lint.py\`."; echo
    for i in $(seq 1 18); do echo "Beta line $i."; echo; done
  } > "$r/.claude/rules/beta.md"

  cat > "$r/.claude/settings.json" <<'JSON'
{
  "permissions": {
    "allow": [],
    "deny": [
      "Read(.env)"
    ],
    "defaultMode": "acceptEdits"
  },
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/bin/true"
          }
        ]
      }
    ]
  }
}
JSON
  cp "$r/.claude/settings.json" "$r/settings-template.json"
  # The engine runs this as a gate against --root, so the fixture needs its own
  # copy. Copying the script UNDER TEST is what makes the mutation cases work.
  cp "$AUDIT" "$r/q-system/.q-system/scripts/instruction-budget-audit.py"
}

# Verify the hand-checked arithmetic before anything depends on it.
assert_fixture_counts() {  # assert_fixture_counts <root>
  local r="$1" a b c
  a=$(grep -c '[^[:space:]]' "$r/CLAUDE.md" || true)
  b=$(grep -c '[^[:space:]]' "$r/.claude/rules/alpha.md" || true)
  c=$(grep -c '[^[:space:]]' "$r/.claude/rules/beta.md" || true)
  check_num "fixture CLAUDE.md lines" 3 "$a"
  check_num "fixture alpha.md lines" 10 "$b"
  check_num "fixture beta.md lines" 20 "$c"
}

# Scope a rule the way the founder does it: frontmatter, added by an ordinary
# edit. Deliberately NOT through apply-claude-changes.sh -- that route refuses
# frontmatter changes on every op, which is the property under test.
scope_rule() {  # scope_rule <root> <rule.md> <glob>
  local r="$1" f="$2" g="$3" tmp
  tmp=$(mktemp)
  { echo "---"; echo "paths:"; echo "  - \"$g\""; echo "---"; cat "$r/.claude/rules/$f"; } > "$tmp"
  mv "$tmp" "$r/.claude/rules/$f"
}

append_proposal() {  # append_proposal <path> <rule.md> <text>
  cat > "$1" <<JSON
{
  "schema_version": 1,
  "slug": "append-one-line",
  "reason": "ASK-285 reproducer: one appended line, nothing deleted anywhere",
  "edits": [
    {
      "file": ".claude/rules/$2",
      "op": "append",
      "insert": "\n$3\n",
      "reason": "the append the two gates jointly refused"
    }
  ]
}
JSON
}

echo "== 1. bootstrap: first ratchet run records cap, total and the snapshot"
R1=$(mktemp -d); mk_fixture "$R1"
assert_fixture_counts "$R1"
audit_rc "$R1"
check "bootstrap exits 0" 0 "baseline created at 33" "$AUDIT_RC" "$AUDIT_OUT"
check_num "bootstrap cap" 33 "$(cap_of "$R1")"
check_num "bootstrap total" 33 "$(total_of "$R1")"

echo "== 2. scoping banks headroom: the cap does NOT follow the total down"
# beta.md (20 always-on lines) becomes paths-scoped. Its lines stop loading every
# turn, so the total drops to 13 -- but nothing was DELETED, so the cap holds at
# 33 and those 20 lines are headroom. Pre-fix this auto-tightened the cap to 13,
# which is precisely what made section 3 impossible.
scope_rule "$R1" beta.md "q-system/output/**"
audit_rc "$R1"
check "scoping run exits 0" 0 "scoped: beta.md (20)" "$AUDIT_RC" "$AUDIT_OUT"
check_num "cap held after scoping" 33 "$(cap_of "$R1")"
check_num "total after scoping" 13 "$(total_of "$R1")"
check "headroom reported" 0 "headroom 20" "$AUDIT_RC" "$AUDIT_OUT"

echo "== 3. THE DoR CHECK: one appended line lands through BOTH gates, no deletion"
append_proposal "$R1/prop.json" alpha.md "Alpha line 8, appended by the sanctioned route."
apply "$R1/prop.json" "$R1"
check "append applies through apply-claude-changes.sh" 0 "OK applied append-one-line" "$APPLY_RC" "$APPLY_OUT"
audit_rc "$R1"
check "instruction-budget passes in the same commit" 0 "RATCHET PASS" "$AUDIT_RC" "$AUDIT_OUT"
check_num "cap unmoved by the append" 33 "$(cap_of "$R1")"
check_num "total after the append" 14 "$(total_of "$R1")"
if grep -q "appended by the sanctioned route" "$R1/.claude/rules/alpha.md"; then
  ok "appended line is on disk"
else
  bad "appended line missing from alpha.md"
fi
# "no manual deletion elsewhere": every other always-on line is still there.
if [ "$(grep -c '[^[:space:]]' "$R1/CLAUDE.md")" = "3" ]; then
  ok "CLAUDE.md untouched (nothing traded away to pay for the append)"
else
  bad "CLAUDE.md changed; the append was paid for by a deletion"
fi

echo "== 4. negative control: no headroom -> the engine auto-reverts, not 'OK applied'"
# Without this gate the engine printed OK applied and the founder discovered the
# refusal at `git commit`. A landed change that cannot be committed is worse than
# a refusal, because everything downstream believes it shipped.
R2=$(mktemp -d); mk_fixture "$R2"
audit_rc "$R2"   # bootstrap: cap 33, total 33, headroom 0
append_proposal "$R2/prop.json" alpha.md "One line too many."
apply "$R2/prop.json" "$R2"
check "over-budget append reverts" 3 "gate 'instruction-budget' regressed pass->fail" "$APPLY_RC" "$APPLY_OUT"
if grep -q "One line too many" "$R2/.claude/rules/alpha.md"; then
  bad "reverted apply left its line on disk"
else
  ok "reverted apply restored alpha.md"
fi
audit_rc "$R2"
check "ratchet still refuses growth past the cap" 0 "RATCHET PASS" "$AUDIT_RC" "$AUDIT_OUT"

echo "== 5. the refusal names a move the reader can actually make"
R3=$(mktemp -d); mk_fixture "$R3"
audit_rc "$R3"
printf '\nAn eleventh always-on line.\n' >> "$R3/.claude/rules/alpha.md"
audit_rc "$R3"
check "over-cap exits 1" 1 "RATCHET FAIL: always-on total 33 -> 34" "$AUDIT_RC" "$AUDIT_OUT"
check "names the reachable move" 1 "paths-scoped rule costs 0 always-on lines" "$AUDIT_RC" "$AUDIT_OUT"
check "names scoping candidates by size" 1 "beta.md (20)" "$AUDIT_RC" "$AUDIT_OUT"
check "says who can scope" 1 "refuses frontmatter changes on every op" "$AUDIT_RC" "$AUDIT_OUT"
check_num "a failing run does not move the cap" 33 "$(cap_of "$R3")"

echo "== 6. negative control: removing a hook entry is STILL refused"
# The fix must not widen the write path's vocabulary. Neutering a hook with
# '|| true' deletes nothing textually and is the canonical additive-looking
# removal; the enforcement census has to keep catching it.
R4=$(mktemp -d); mk_fixture "$R4"
audit_rc "$R4"
cat > "$R4/prop.json" <<'JSON'
{
  "schema_version": 1,
  "slug": "neuter-hook",
  "reason": "negative control: this must never land",
  "edits": [
    {
      "file": ".claude/settings.json",
      "op": "insert_after",
      "anchor": "\"command\": \"/usr/bin/true",
      "insert": " || true",
      "reason": "makes the old exact command string vanish from the census"
    },
    {
      "file": "settings-template.json",
      "op": "insert_after",
      "anchor": "\"command\": \"/usr/bin/true",
      "insert": " || true",
      "reason": "kept in lockstep so the pairing check is not what refuses it"
    }
  ]
}
JSON
apply "$R4/prop.json" "$R4"
check "hook removal refused" 2 "enforcement ratchet" "$APPLY_RC" "$APPLY_OUT"
if grep -q '|| true' "$R4/.claude/settings.json"; then
  bad "refused proposal still wrote settings.json"
else
  ok "refused proposal wrote nothing"
fi

echo "== 7. negative control: deletion tightens the cap, it does not bank headroom"
R5=$(mktemp -d); mk_fixture "$R5"
audit_rc "$R5"
scope_rule "$R5" beta.md "q-system/output/**"
audit_rc "$R5"   # cap 33, total 13, headroom 20
# Remove 3 substantive lines from alpha.md. Deletion is permanent: the cap must
# follow the total down by exactly 3, leaving headroom unchanged at 20.
python3 - "$R5/.claude/rules/alpha.md" <<'PY'
import sys
p = sys.argv[1]
lines = open(p).read().splitlines(True)
kept, dropped = [], 0
for line in lines:
    if line.strip() and dropped < 3 and line.startswith("Alpha line"):
        dropped += 1
        continue
    kept.append(line)
open(p, "w").write("".join(kept))
PY
audit_rc "$R5"
check "deletion run exits 0" 0 "tightened cap 33 -> 30" "$AUDIT_RC" "$AUDIT_OUT"
check_num "cap tightened by the deleted lines" 30 "$(cap_of "$R5")"
check_num "total after deletion" 10 "$(total_of "$R5")"
check "headroom unchanged by a deletion" 0 "headroom 20" "$AUDIT_RC" "$AUDIT_OUT"

echo "== 8. negative control: a NEW paths-scoped rule mints no headroom"
# Only a rule that WAS always-on can free always-on lines. Crediting a brand-new
# scoped rule would let an agent mint budget out of nothing, one create_file at
# a time -- the exact loosening this design must not become.
R6=$(mktemp -d); mk_fixture "$R6"
audit_rc "$R6"   # cap 33, total 33
{ echo "---"; echo "paths:"; echo "  - \"q-system/output/**\""; echo "---"; echo
  echo "# Gamma Rule"; echo; for i in $(seq 1 10); do echo "Gamma line $i."; echo; done
} > "$R6/.claude/rules/gamma.md"
audit_rc "$R6"
check_num "cap unmoved by a new scoped rule" 33 "$(cap_of "$R6")"
check "no headroom minted" 0 "headroom 0" "$AUDIT_RC" "$AUDIT_OUT"
append_proposal "$R6/prop.json" alpha.md "Still one line too many."
apply "$R6/prop.json" "$R6"
check "append still reverts with no real headroom" 3 "instruction-budget" "$APPLY_RC" "$APPLY_OUT"

echo "== 9. negative control: scoped-and-gutted credits only the surviving lines"
R7=$(mktemp -d); mk_fixture "$R7"
audit_rc "$R7"   # cap 33, total 33, beta 20 lines
# beta.md is scoped AND cut to 5 body lines in one step: 4 frontmatter + 5 body
# = 9 conditional lines. Only the 5 body lines survive, so the credit is 5 and the
# other 15 are a deletion: the cap tightens by 15 to 18 and headroom is 18 - 13 = 5.
# These numbers were 9 / 11 / 22 until PR #88 round 7, which is section 33's defect
# showing up here at four times the size -- the old reading credited beta's four
# NEW frontmatter lines as surviving instruction lines. Strictly tighter now.
{ echo "---"; echo "paths:"; echo "  - \"q-system/output/**\""; echo "---"
  echo "# Beta Rule (ENFORCED)"; echo
  echo "The deterministic half is \`beta-lint.py\`."; echo
  echo "Beta line 1."; echo; echo "Beta line 2."; echo; echo "Beta line 3."
} > "$R7/.claude/rules/beta.md"
audit_rc "$R7"
check_num "cap tightened by the gutted half" 18 "$(cap_of "$R7")"
check "credit is only the surviving body lines" 0 "scoped: beta.md (5)" "$AUDIT_RC" "$AUDIT_OUT"
check "headroom is the credited amount" 0 "headroom 5" "$AUDIT_RC" "$AUDIT_OUT"

echo "== 10. a pre-ASK-285 baseline upgrades without moving the gate"
R8=$(mktemp -d); mk_fixture "$R8"
printf '{\n  "total_always_on": 33\n}\n' > "$R8/q-system/.q-system/instruction-budget-baseline.json"
audit_rc "$R8"
check "old-shape baseline still passes" 0 "RATCHET PASS" "$AUDIT_RC" "$AUDIT_OUT"
check_num "cap read from the single old number" 33 "$(cap_of "$R8")"
check "snapshot recorded for the next run" 0 "stage " "$AUDIT_RC" "$AUDIT_OUT"

echo "== 11. --no-write leaves the baseline alone (a gate must not mutate it)"
R9=$(mktemp -d); mk_fixture "$R9"
audit_rc "$R9"
scope_rule "$R9" beta.md "q-system/output/**"
BEFORE=$(cat "$R9/q-system/.q-system/instruction-budget-baseline.json")
audit_rc "$R9" --no-write
AFTER=$(cat "$R9/q-system/.q-system/instruction-budget-baseline.json")
if [ "$BEFORE" = "$AFTER" ]; then ok "--no-write did not touch the baseline"; else bad "--no-write rewrote the baseline"; fi

echo "== 12. mutation: blind the scoping/deletion classifier -> section 3 goes RED"
# A guard never seen to fail is not a guard. Blind the one arm that classifies a
# scoped rule's surviving lines as NOT deleted and every drop reads as a deletion:
# the cap auto-tightens exactly as it did before ASK-285 and the appended line is
# refused again. The mutation targets deleted_lines because that is what decides
# the cap now -- scoping_freed only writes the note (PR #88 round 2, minor).
MUT=$(mktemp -d)/mutant-audit.py
mkdir -p "$(dirname "$MUT")"
python3 - "$AUDIT" "$MUT" <<'PY'
import sys
src = open(sys.argv[1]).read()
needle = ("        elif name in conditional:\n"
          "            after = scoped_credit(before, prev_body.get(name, before),\n"
          "                                  body.get(name, 0))\n")
assert needle in src, "deleted_lines classifier moved; update the mutation"
open(sys.argv[2], "w").write(src.replace(
    needle, "        elif name in conditional:\n            after = 0\n", 1))
PY
RM=$(mktemp -d); AUDIT_SAVE="$AUDIT"; AUDIT="$MUT"; mk_fixture "$RM"
audit_rc "$RM"
scope_rule "$RM" beta.md "q-system/output/**"
audit_rc "$RM"
check_num "mutant auto-tightens the cap (pre-ASK-285 behaviour)" 13 "$(cap_of "$RM")"
append_proposal "$RM/prop.json" alpha.md "Alpha line 8, appended by the sanctioned route."
apply "$RM/prop.json" "$RM"
check "mutant refuses the DoR append" 3 "instruction-budget" "$APPLY_RC" "$APPLY_OUT"
AUDIT="$AUDIT_SAVE"

echo "== 13. mutation: drop the instruction-budget gate -> section 4 goes RED"
# Proves the gate wiring in apply_claude_changes.py is load-bearing, not decoration.
MUTE=$(mktemp -d)/mutant-engine.py
mkdir -p "$(dirname "$MUTE")"
python3 - "$SCRIPT_DIR/../apply_claude_changes.py" "$MUTE" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
out = re.sub(r'\n    \("instruction-budget", gate_instruction_budget\),\n', "\n", src, count=1)
assert out != src, "instruction-budget gate entry not found; update the mutation"
open(sys.argv[2], "w").write(out)
PY
RE1=$(mktemp -d); mk_fixture "$RE1"
audit_rc "$RE1"
append_proposal "$RE1/prop.json" alpha.md "One line too many."
APPLY_ENGINE="$MUTE" apply "$RE1/prop.json" "$RE1"
check "mutant engine applies an uncommittable change" 0 "OK applied" "$APPLY_RC" "$APPLY_OUT"
audit_rc "$RE1"
check "and the commit gate is the one that finds out" 1 "RATCHET FAIL" "$AUDIT_RC" "$AUDIT_OUT"

echo "== 14. a rule in a rules/ SUBDIRECTORY is counted, not invisible"
# apply_claude_changes.py is depth-permissive for rule text (is_rule_text) and its
# own content census walks the whole rules/ tree, so the sanctioned route can
# create .claude/rules/team/nested.md and Claude loads it always-on like any other
# unscoped rule. A one-level os.listdir here left those lines uncounted: the engine
# printed "gates held" on instructions the ratchet could not see (PR #88, major).
# nested.md is 1 heading + 4 body = 5 substantive lines, so total 33 -> 38.
R10=$(mktemp -d); mk_fixture "$R10"
audit_rc "$R10"                      # cap 33, total 33
mkdir -p "$R10/.claude/rules/team"
{ echo "# Nested Rule"; echo
  for i in $(seq 1 4); do echo "Nested line $i."; echo; done
} > "$R10/.claude/rules/team/nested.md"
check_num "fixture nested.md lines" 5 "$(grep -c '[^[:space:]]' "$R10/.claude/rules/team/nested.md" || true)"
audit_rc "$R10"
check "nested always-on lines hit the cap" 1 "RATCHET FAIL: always-on total 33 -> 38" "$AUDIT_RC" "$AUDIT_OUT"
LISTING=$(python3 "$AUDIT" --root "$R10" 2>&1 || true)
case "$LISTING" in
  *"team/nested.md: 5"*) ok "listing names the nested rule by its path under rules/" ;;
  *) bad "listing hides the nested rule :: $LISTING" ;;
esac

echo "== 15. the sanctioned route cannot land an uncounted nested rule either"
# Same hole seen from the write path: create_file at depth is permitted, so the
# gate has to grade it. Pre-fix the engine reported OK applied and the always-on
# total it printed was unchanged.
R11=$(mktemp -d); mk_fixture "$R11"
audit_rc "$R11"                      # cap 33, total 33, headroom 0
cat > "$R11/prop.json" <<'JSON'
{
  "schema_version": 1,
  "slug": "nested-always-on",
  "reason": "PR #88 reproducer: an always-on rule created at depth under rules/",
  "edits": [
    {
      "file": ".claude/rules/team/nested.md",
      "op": "create_file",
      "insert": "# Nested Rule\n\nNested line 1.\n\nNested line 2.\n",
      "reason": "five always-on lines the one-level scanner never saw"
    }
  ]
}
JSON
apply "$R11/prop.json" "$R11"
check "nested create_file reverts with no headroom" 3 "gate 'instruction-budget' regressed pass->fail" "$APPLY_RC" "$APPLY_OUT"
if [ -f "$R11/.claude/rules/team/nested.md" ]; then
  bad "reverted apply left the nested rule on disk"
else
  ok "reverted apply removed the nested rule"
fi

echo "== 16. the ratchet stages the baseline it rewrote, so the commit records it"
# The pre-commit hook rewrites the baseline in the WORKING TREE. Unstaged, the
# commit that caused the accounting transition does not carry it: a tightened cap
# is one `git checkout` from gone, and the committed baseline disagrees with the
# tree every gate reads (PR #88, major).
R12=$(mktemp -d); mk_fixture "$R12"
audit_rc "$R12"                      # bootstrap writes the baseline
git -C "$R12" init -q
git -C "$R12" add -A
BASE_REL="q-system/.q-system/instruction-budget-baseline.json"
scope_rule "$R12" beta.md "q-system/output/**"
git -C "$R12" add -A                 # section 20: a run only records a tree the commit carries
audit_rc "$R12"                      # rewrites the baseline: total 33 -> 13
check "staging run exits 0" 0 "RATCHET PASS" "$AUDIT_RC" "$AUDIT_OUT"
STAGED=$(git -C "$R12" show ":$BASE_REL")
ONDISK=$(cat "$R12/$BASE_REL")
if [ "$STAGED" = "$ONDISK" ]; then
  ok "rewritten baseline is in the index"
else
  bad "baseline rewritten in the tree only; the commit would not carry it"
fi
check "the run says it staged, not that the reader should" 0 "staged $BASE_REL" "$AUDIT_RC" "$AUDIT_OUT"

echo "== 17. --no-stage and a non-git tree: staging is never load-bearing"
# The audit runs against throwaway fixtures and inside apply_claude_changes.py's
# gate suite, neither of which is a git work tree. Failing to stage must never be
# what fails a run.
R13=$(mktemp -d); mk_fixture "$R13"
audit_rc "$R13"
scope_rule "$R13" beta.md "q-system/output/**"
audit_rc "$R13"
check "non-git tree still passes" 0 "RATCHET PASS" "$AUDIT_RC" "$AUDIT_OUT"
case "$AUDIT_OUT" in
  *"staged "*) bad "claimed to stage in a tree with no git index" ;;
  *) ok "no staging claim outside a git work tree" ;;
esac
R14=$(mktemp -d); mk_fixture "$R14"
audit_rc "$R14"
git -C "$R14" init -q
git -C "$R14" add -A
scope_rule "$R14" beta.md "q-system/output/**"
git -C "$R14" add -A
audit_rc "$R14" --no-stage
STAGED=$(git -C "$R14" show ":$BASE_REL")
ONDISK=$(cat "$R14/$BASE_REL")
if [ "$STAGED" = "$ONDISK" ]; then
  bad "--no-stage staged the baseline anyway"
else
  ok "--no-stage left the index alone"
fi

echo "== 18. mutation: blind the walk to subdirectories -> section 14 goes RED"
MUTW=$(mktemp -d)/mutant-walk.py
mkdir -p "$(dirname "$MUTW")"
python3 - "$AUDIT" "$MUTW" <<'PY'
import sys
src = open(sys.argv[1]).read()
needle = "    for dirpath, dirnames, filenames in os.walk(rules_dir):\n"
assert needle in src, "scan_rules walk moved; update the mutation"
open(sys.argv[2], "w").write(src.replace(
    needle, needle + "        dirnames[:] = []\n", 1))
PY
RM2=$(mktemp -d); AUDIT_SAVE="$AUDIT"; AUDIT="$MUTW"; mk_fixture "$RM2"
audit_rc "$RM2"
mkdir -p "$RM2/.claude/rules/team"
{ echo "# Nested Rule"; echo
  for i in $(seq 1 4); do echo "Nested line $i."; echo; done
} > "$RM2/.claude/rules/team/nested.md"
audit_rc "$RM2"
check "mutant reports the nested rule as free" 0 "RATCHET PASS" "$AUDIT_RC" "$AUDIT_OUT"
AUDIT="$AUDIT_SAVE"

echo "== 19. mixed scoping + deletion + addition: the deletion still tightens the cap"
# PR #88 round 2, minor. The cap moved on the NET drop, so a step that scopes 20
# lines, deletes 3 and adds 3 elsewhere netted to "scoping only" and the 3 deleted
# lines silently became permanent extra headroom. Deletion is now counted per file
# against the snapshot, so an addition somewhere else cannot pay for it.
R15=$(mktemp -d); mk_fixture "$R15"
audit_rc "$R15"                       # cap 33, total 33, snapshot alpha 10 / beta 20
scope_rule "$R15" beta.md "q-system/output/**"   # frees 20
python3 - "$R15/.claude/rules/alpha.md" <<'PY'
import sys
p = sys.argv[1]
kept, dropped = [], 0
for line in open(p).read().splitlines(True):
    if line.strip() and dropped < 3 and line.startswith("Alpha line"):
        dropped += 1
        continue
    kept.append(line)
open(p, "w").write("".join(kept))
PY
printf '\nA third behavioural line.\n\nA fourth behavioural line.\n\nA fifth behavioural line.\n' >> "$R15/CLAUDE.md"
# CLAUDE.md 3 -> 6, alpha 10 -> 7, beta scoped: total = 6 + 7 = 13.
audit_rc "$R15"
check "mixed step exits 0" 0 "tightened cap 33 -> 30" "$AUDIT_RC" "$AUDIT_OUT"
check_num "cap tightened by the deleted lines only" 30 "$(cap_of "$R15")"
check_num "total after the mixed step" 13 "$(total_of "$R15")"
check "headroom is the scoping credit minus the addition" 0 "headroom 17" "$AUDIT_RC" "$AUDIT_OUT"
check "the scoping credit is still reported in full" 0 "scoped: beta.md (20)" "$AUDIT_RC" "$AUDIT_OUT"

echo "== 20. an unstaged rule deletion records nothing, so a fresh checkout stays green"
# PR #88 round 2, major. The ratchet reads the WORKING TREE and stages what it
# wrote. Under a partial `git add`, a tree-only deletion tightened the cap and that
# cap was committed while the rules it was computed from were not -- so a fresh
# clone audited RED and needed a hand repair. Recording now waits for a tree that
# matches the index.
R16=$(mktemp -d); mk_fixture "$R16"
audit_rc "$R16"                       # bootstrap: cap 33, total 33
git -C "$R16" init -q
git -C "$R16" add -A
python3 - "$R16/.claude/rules/alpha.md" <<'PY'
import sys
p = sys.argv[1]
kept, dropped = [], 0
for line in open(p).read().splitlines(True):
    if line.strip() and dropped < 3 and line.startswith("Alpha line"):
        dropped += 1
        continue
    kept.append(line)
open(p, "w").write("".join(kept))
PY
audit_rc "$R16"                       # the deletion is in the tree, NOT in the index
check "dirty run still exits 0" 0 "RATCHET PASS" "$AUDIT_RC" "$AUDIT_OUT"
check "it says why it recorded nothing" 0 "not recording" "$AUDIT_RC" "$AUDIT_OUT"
check "it names the diverging path" 0 "alpha.md" "$AUDIT_RC" "$AUDIT_OUT"
check_num "cap not tightened from an unstaged deletion" 33 "$(cap_of "$R16")"
git -C "$R16" -c user.email=t@t -c user.name=t commit -qm "commit the index, not the tree"
R17=$(mktemp -d); rmdir "$R17"
git clone -q "$R16" "$R17"
cp "$AUDIT" "$R17/q-system/.q-system/scripts/instruction-budget-audit.py"
audit_rc "$R17" --no-write --no-stage
check "a fresh checkout of that commit audits green" 0 "RATCHET PASS: total 33, cap 33" "$AUDIT_RC" "$AUDIT_OUT"
# Staging the same deletion is what makes the accounting land.
git -C "$R16" add -A
audit_rc "$R16"
check "staged, the deletion tightens the cap" 0 "tightened cap 33 -> 30" "$AUDIT_RC" "$AUDIT_OUT"
check_num "cap follows a staged deletion down" 30 "$(cap_of "$R16")"

echo "== 21. renaming an unchanged always-on rule spends no headroom"
# PR #88 round 3, major. deleted_lines diffs each snapshot entry against a file of
# the SAME NAME, so `git mv alpha.md gamma.md` read as "all 10 of alpha.md's lines
# are gone" and charged the cap for every one of them. Headroom the founder banked
# by scoping was consumed by a step that moved no instruction line anywhere, and
# only a hand edit of the baseline got it back. The rename git already recorded is
# now what rekeys the snapshot, before anything is diffed against it.
R18=$(mktemp -d); mk_fixture "$R18"
audit_rc "$R18"                       # bootstrap: cap 33, total 33
git -C "$R18" init -q
git -C "$R18" add -A
git -C "$R18" -c user.email=t@t -c user.name=t commit -qm "fixture (ASK-285)"
scope_rule "$R18" beta.md "q-system/output/**"    # banks 20 lines of headroom
git -C "$R18" add -A
audit_rc "$R18"
check "scoping banks the headroom" 0 "headroom 20" "$AUDIT_RC" "$AUDIT_OUT"
check_num "cap holds while the total drops" 33 "$(cap_of "$R18")"
git -C "$R18" -c user.email=t@t -c user.name=t commit -qm "scope beta (ASK-285)"
git -C "$R18" mv .claude/rules/alpha.md .claude/rules/gamma.md
audit_rc "$R18"
check "the rename run exits 0" 0 "RATCHET PASS" "$AUDIT_RC" "$AUDIT_OUT"
check_num "cap survives a pure rename" 33 "$(cap_of "$R18")"
check_num "total is unmoved by a rename" 13 "$(total_of "$R18")"
check "headroom survives a pure rename" 0 "headroom 20" "$AUDIT_RC" "$AUDIT_OUT"
snap_keys() { python3 -c 'import json,sys; print(",".join(sorted(json.load(open(sys.argv[1]))["always_on_files"])))' "$1/q-system/.q-system/instruction-budget-baseline.json"; }
check_num "the snapshot follows the rename" "gamma.md" "$(snap_keys "$R18")"
# The load-bearing half: git reports the rename only in the commit that makes it.
# If the snapshot kept the old key, the NEXT run would see alpha.md gone with no
# rename record to explain it and charge the 10 lines one commit late.
git -C "$R18" -c user.email=t@t -c user.name=t commit -qm "rename alpha (ASK-285)"
audit_rc "$R18"
check "the run after the rename commit still holds" 0 "headroom 20" "$AUDIT_RC" "$AUDIT_OUT"
check_num "cap held once the rename is history" 33 "$(cap_of "$R18")"

echo "== 22. rename + shortening: the shortening half still tightens the cap"
# The negative control on section 21. Carrying the snapshot entry across the
# rename is exactly what lets max(0, before - after) see a shrink at all, so a
# rename must never launder a deletion: gutting 3 lines in the same step as the
# rename charges the cap 3, no more and no less.
git -C "$R18" mv .claude/rules/gamma.md .claude/rules/delta.md
python3 - "$R18/.claude/rules/delta.md" <<'PY'
import sys
p = sys.argv[1]
kept, dropped = [], 0
for line in open(p).read().splitlines(True):
    if line.strip() and dropped < 3 and line.startswith("Alpha line"):
        dropped += 1
        continue
    kept.append(line)
open(p, "w").write("".join(kept))
PY
git -C "$R18" add -A                  # section 20: record only a tree the commit carries
audit_rc "$R18"                       # CLAUDE.md 3 + delta 7 = 10
check "rename+shortening charges the shortening" 0 "tightened cap 33 -> 30" "$AUDIT_RC" "$AUDIT_OUT"
check_num "cap follows the deleted lines down" 30 "$(cap_of "$R18")"
check_num "total after rename+shortening" 10 "$(total_of "$R18")"
check_num "the snapshot follows this rename too" "delta.md" "$(snap_keys "$R18")"

echo "== 23. mutation: drop the rename lookup -> section 21 goes RED"
# A regression case never watched fail is not known to catch anything, and the
# ref hatch only reaches the previous commit. This blinds the rekey in place.
MUTR=$(mktemp -d)/mutant-rename.py
mkdir -p "$(dirname "$MUTR")"
python3 - "$AUDIT" "$MUTR" <<'PY'
import sys
src = open(sys.argv[1]).read()
needle = "        key = renames.get(name, name)\n"
assert needle in src, "apply_renames moved; update the mutation"
open(sys.argv[2], "w").write(src.replace(needle, "        key = name\n", 1))
PY
RM3=$(mktemp -d); AUDIT_SAVE="$AUDIT"; AUDIT="$MUTR"; mk_fixture "$RM3"
audit_rc "$RM3"
git -C "$RM3" init -q
git -C "$RM3" add -A
git -C "$RM3" -c user.email=t@t -c user.name=t commit -qm "fixture (ASK-285)"
scope_rule "$RM3" beta.md "q-system/output/**"
git -C "$RM3" add -A
audit_rc "$RM3"
git -C "$RM3" -c user.email=t@t -c user.name=t commit -qm "scope beta (ASK-285)"
git -C "$RM3" mv .claude/rules/alpha.md .claude/rules/gamma.md
audit_rc "$RM3"
check "mutant charges the rename as a deletion" 0 "tightened cap 33 -> 23" "$AUDIT_RC" "$AUDIT_OUT"
AUDIT="$AUDIT_SAVE"

echo "== 24. a FAILED git status records nothing; it does not read as a clean tree"
# PR #88 round 4, major. git_status() returned None both when there is no index to
# read (a --root'ed fixture -- ordinary) and when git was there and could not be
# read (index.lock contention, a corrupt index, a permission fault -- never
# ordinary). index_divergence(None) is falsy, so the second case walked straight
# past the guard section 20 built and committed a cap computed from an UNSTAGED
# deletion. The discriminator is `git rev-parse --is-inside-work-tree`, which reads
# no index and so still answers when `git status` cannot.
#
# The shim is how a status failure is made deterministic: `git -C <root> <cmd>` is
# the shape every call in the audit uses, so $3 is always the subcommand.
REAL_GIT=$(command -v git)
mk_git_shim() {  # mk_git_shim <dir> <subcommand-to-fail>
  mkdir -p "$1"
  cat > "$1/git" <<SH
#!/usr/bin/env bash
if [ "\${3:-}" = "$2" ]; then echo "fatal: simulated $2 failure" >&2; exit 128; fi
exec "$REAL_GIT" "\$@"
SH
  chmod +x "$1/git"
}
audit_with_path() {  # audit_with_path <PATH-prefix-dir> <root> [args...]
  local shim="$1" r="$2"; shift 2
  set +e
  AUDIT_OUT=$(PATH="$shim:$PATH" python3 "$AUDIT" --ratchet --root "$r" "$@" 2>&1)
  AUDIT_RC=$?
  set -e
}

SHIM_STATUS=$(mktemp -d)/bin; mk_git_shim "$SHIM_STATUS" status
R19=$(mktemp -d); mk_fixture "$R19"
audit_rc "$R19"                       # bootstrap: cap 33, total 33
git -C "$R19" init -q
git -C "$R19" add -A
git -C "$R19" -c user.email=t@t -c user.name=t commit -qm "fixture (ASK-285)"
python3 - "$R19/.claude/rules/alpha.md" <<'PY'
import sys
p = sys.argv[1]
kept, dropped = [], 0
for line in open(p).read().splitlines(True):
    if line.strip() and dropped < 3 and line.startswith("Alpha line"):
        dropped += 1
        continue
    kept.append(line)
open(p, "w").write("".join(kept))
PY
audit_with_path "$SHIM_STATUS" "$R19"   # deletion in the tree only, and status is broken
check "a broken git status still exits 0" 0 "RATCHET PASS" "$AUDIT_RC" "$AUDIT_OUT"
check "it says why it recorded nothing" 0 "not recording" "$AUDIT_RC" "$AUDIT_OUT"
check "it names git status, not a diverging path" 0 "git status failed" "$AUDIT_RC" "$AUDIT_OUT"
check_num "cap not tightened behind a broken git status" 33 "$(cap_of "$R19")"
# Fail-closed is the whole point, so it costs a recording even when the tree is in
# fact clean. Stated as a boundary in the docstring; pinned here so it stays a
# choice rather than a surprise.
git -C "$R19" add -A
audit_with_path "$SHIM_STATUS" "$R19"
check "still recording nothing while git status is broken" 0 "not recording" "$AUDIT_RC" "$AUDIT_OUT"
check_num "cap still held" 33 "$(cap_of "$R19")"
audit_rc "$R19"                       # real git back on PATH: the accounting lands
check "with git working the staged deletion lands" 0 "tightened cap 33 -> 30" "$AUDIT_RC" "$AUDIT_OUT"
check_num "cap follows the deletion once git answers" 30 "$(cap_of "$R19")"

echo "== 25. a FAILED baseline git add fails the run, it does not exit 0"
# PR #88 round 4, major. stage_baseline() swallowed a failed `git add` and printed
# "stage <path> with this commit" -- the same instruction-to-an-absent-reader that
# section 16 already replaced once. The commit then carried the rules WITHOUT the
# accounting they moved. A rename is the sharp case: git reports it only in the
# commit that makes it, so a baseline left behind charges the whole rule as a
# deletion on the very next run and eats banked headroom.
SHIM_ADD=$(mktemp -d)/bin; mk_git_shim "$SHIM_ADD" add
R20=$(mktemp -d); mk_fixture "$R20"
audit_rc "$R20"                       # bootstrap: cap 33, total 33
git -C "$R20" init -q
git -C "$R20" add -A
git -C "$R20" -c user.email=t@t -c user.name=t commit -qm "fixture (ASK-285)"
BEFORE_BASE=$(git -C "$R20" show ":$BASE_REL")
scope_rule "$R20" beta.md "q-system/output/**"
git -C "$R20" add -A                  # tree matches the index, so recording is allowed
audit_with_path "$SHIM_ADD" "$R20"
check "an unstageable baseline fails the run" 1 "RATCHET FAIL" "$AUDIT_RC" "$AUDIT_OUT"
check "the failure names the staging problem" 1 "could not stage" "$AUDIT_RC" "$AUDIT_OUT"
if [ "$(git -C "$R20" show ":$BASE_REL")" = "$BEFORE_BASE" ]; then
  ok "the index really did not get the new baseline"
else
  bad "shim did not block the add; the case proves nothing"
fi
# The new failure is gated on being in a work tree, so fixtures and the engine's
# gate suite (section 17) keep passing with the same broken `git add`.
R21=$(mktemp -d); mk_fixture "$R21"
audit_rc "$R21"
scope_rule "$R21" beta.md "q-system/output/**"
audit_with_path "$SHIM_ADD" "$R21"
check "a non-git tree is untouched by the add failure" 0 "RATCHET PASS" "$AUDIT_RC" "$AUDIT_OUT"
check_num "cap held in the non-git tree" 33 "$(cap_of "$R21")"

echo "== 26. mutation: blind the work-tree probe -> sections 24 and 25 go RED"
# A regression case never watched fail is not known to catch anything. This makes
# inside_work_tree() answer False everywhere, which is exactly the pre-fix reading:
# every git failure looks like "no index here, carry on".
MUTG=$(mktemp -d)/mutant-worktree.py
mkdir -p "$(dirname "$MUTG")"
python3 - "$AUDIT" "$MUTG" <<'PY'
import sys
src = open(sys.argv[1]).read()
needle = '    return proc.stdout.decode("utf-8", "replace").strip() == "true"\n'
assert needle in src, "inside_work_tree moved; update the mutation"
open(sys.argv[2], "w").write(src.replace(needle, "    return False\n", 1))
PY
RM4=$(mktemp -d); AUDIT_SAVE="$AUDIT"; AUDIT="$MUTG"; mk_fixture "$RM4"
audit_rc "$RM4"
git -C "$RM4" init -q
git -C "$RM4" add -A
git -C "$RM4" -c user.email=t@t -c user.name=t commit -qm "fixture (ASK-285)"
python3 - "$RM4/.claude/rules/alpha.md" <<'PY'
import sys
p = sys.argv[1]
kept, dropped = [], 0
for line in open(p).read().splitlines(True):
    if line.strip() and dropped < 3 and line.startswith("Alpha line"):
        dropped += 1
        continue
    kept.append(line)
open(p, "w").write("".join(kept))
PY
audit_with_path "$SHIM_STATUS" "$RM4"
check "mutant commits a cap from an unstaged deletion" 0 "tightened cap 33 -> 30" "$AUDIT_RC" "$AUDIT_OUT"
AUDIT="$AUDIT_SAVE"

echo "== 27. bootstrap obeys the same recording guard every later run does"
# PR #88 round 5, minor. Sections 20 and 24 made a RUN refuse to record accounting
# it could not prove the commit would carry -- but both guards sat AFTER the
# `baseline is None` arm, which writes and stages a fresh baseline of its own. So
# the very first ratchet run in a repo, behind an unstaged rule deletion, minted a
# cap from the tree and staged it into a commit carrying the longer rules: the next
# fresh clone audits RED with only a hand edit of the baseline to get back. That is
# section 20's defect verbatim, on the one path that had no guard.
R22=$(mktemp -d); mk_fixture "$R22"     # deliberately NO bootstrap audit yet
git -C "$R22" init -q
git -C "$R22" add -A
git -C "$R22" -c user.email=t@t -c user.name=t commit -qm "fixture, no baseline (ASK-285)"
python3 - "$R22/.claude/rules/alpha.md" <<'PY'
import sys
p = sys.argv[1]
kept, dropped = [], 0
for line in open(p).read().splitlines(True):
    if line.strip() and dropped < 3 and line.startswith("Alpha line"):
        dropped += 1
        continue
    kept.append(line)
open(p, "w").write("".join(kept))
PY
audit_rc "$R22"                         # first run ever, deletion in the tree only
check "the bootstrap run still exits 0" 0 "RATCHET" "$AUDIT_RC" "$AUDIT_OUT"
check "it says why it recorded nothing" 0 "not recording" "$AUDIT_RC" "$AUDIT_OUT"
check "it names the diverging path" 0 "alpha.md" "$AUDIT_RC" "$AUDIT_OUT"
if [ -f "$R22/$BASE_REL" ]; then
  bad "bootstrap wrote a baseline from a tree the commit does not carry"
else
  ok "no baseline is minted from an unstaged deletion"
fi
if git -C "$R22" show ":$BASE_REL" >/dev/null 2>&1; then
  bad "bootstrap staged that baseline into the commit"
else
  ok "nothing was staged either"
fi
# The disaster this prevents, proved end to end: commit RIGHT HERE, with the
# deletion still unstaged. Pre-fix that commit carries a cap of 30 alongside rules
# that still total 33, and the clone below is where a human first finds out.
# --allow-empty because the two behaviours differ in exactly what is staged: the
# pre-fix run staged the baseline it minted, the fixed run staged nothing at all.
git -C "$R22" -c user.email=t@t -c user.name=t commit -q --allow-empty \
  -m "commit the index, not the tree (ASK-285)"
R23=$(mktemp -d); rmdir "$R23"
git clone -q "$R22" "$R23"
cp "$AUDIT" "$R23/q-system/.q-system/scripts/instruction-budget-audit.py"
audit_rc "$R23" --no-write --no-stage
check "a fresh clone of that commit is not born RED" 0 "RATCHET" "$AUDIT_RC" "$AUDIT_OUT"
case "$AUDIT_OUT" in
  *"RATCHET FAIL"*) bad "the clone inherited a cap its own rules already violate" ;;
  *) ok "the clone bootstraps against its own committed tree" ;;
esac
# The commit that carries the rules is the one allowed to bootstrap.
git -C "$R22" add -A
audit_rc "$R22"
check "staged, the bootstrap lands" 0 "baseline created at 30" "$AUDIT_RC" "$AUDIT_OUT"
check_num "the bootstrapped cap is the staged total" 30 "$(cap_of "$R22")"
# Negative control: a clean tree with no baseline must still bootstrap. The guard
# is "the commit does not carry this", never "there is a git repo here".
R24=$(mktemp -d); mk_fixture "$R24"
git -C "$R24" init -q
git -C "$R24" add -A
audit_rc "$R24"
check "a clean tree bootstraps as before" 0 "baseline created at 33" "$AUDIT_RC" "$AUDIT_OUT"
check_num "clean bootstrap records the full total" 33 "$(cap_of "$R24")"

echo "== 28. mutation: put the bootstrap back ahead of the guard -> section 27 goes RED"
# A regression case never watched fail is not known to catch anything, and the ref
# hatch only reaches the previous commit. This drops the guard from the bootstrap
# arm in place, which is exactly the pre-fix ordering.
MUTB=$(mktemp -d)/mutant-bootstrap.py
mkdir -p "$(dirname "$MUTB")"
python3 - "$AUDIT" "$MUTB" <<'PY'
import sys
src = open(sys.argv[1]).read()
needle = "    if baseline is None:\n        if blocked:\n"
assert needle in src, "the bootstrap guard moved; update the mutation"
open(sys.argv[2], "w").write(
    src.replace(needle, "    if baseline is None:\n        if False:\n", 1))
PY
RM5=$(mktemp -d); AUDIT_SAVE="$AUDIT"; AUDIT="$MUTB"; mk_fixture "$RM5"
git -C "$RM5" init -q
git -C "$RM5" add -A
git -C "$RM5" -c user.email=t@t -c user.name=t commit -qm "fixture, no baseline (ASK-285)"
python3 - "$RM5/.claude/rules/alpha.md" <<'PY'
import sys
p = sys.argv[1]
kept, dropped = [], 0
for line in open(p).read().splitlines(True):
    if line.strip() and dropped < 3 and line.startswith("Alpha line"):
        dropped += 1
        continue
    kept.append(line)
open(p, "w").write("".join(kept))
PY
audit_rc "$RM5"
check "mutant mints a cap from an unstaged deletion" 0 "baseline created at 30" "$AUDIT_RC" "$AUDIT_OUT"
AUDIT="$AUDIT_SAVE"

echo "== 29. a baseline the index does not carry is staged on the NEXT run too"
# PR #88 round 5, major. Section 25 made the first attempt fail, and stopped there.
# The rewrite had already landed in the WORKING TREE, so the retry read its own
# advanced baseline, computed `changed` = False, and exited 0 having staged
# nothing: the commit went out carrying the rules without the accounting they
# moved, which is section 25's defect surviving one `git commit` later. Staging is
# now decided by what the INDEX holds, not by whether this particular run rewrote
# the file, so every run after the failure keeps trying until the index agrees.
R23=$(mktemp -d); mk_fixture "$R23"
audit_rc "$R23"                       # bootstrap: cap 33, total 33
git -C "$R23" init -q
git -C "$R23" add -A
git -C "$R23" -c user.email=t@t -c user.name=t commit -qm "fixture (ASK-285)"
STALE_BASE=$(git -C "$R23" show ":$BASE_REL")
scope_rule "$R23" beta.md "q-system/output/**"
git -C "$R23" add -A                  # tree matches the index, so recording is allowed
audit_with_path "$SHIM_ADD" "$R23"    # attempt 1: rewritten, unstageable, run fails
check "attempt 1 still fails the run" 1 "could not stage" "$AUDIT_RC" "$AUDIT_OUT"
audit_rc "$R23"                       # attempt 2, git working again, nothing left to rewrite
check "the retry stages the baseline it did not rewrite" 0 "staged $BASE_REL" "$AUDIT_RC" "$AUDIT_OUT"
if [ "$(git -C "$R23" show ":$BASE_REL")" = "$(cat "$R23/$BASE_REL")" ]; then
  ok "the index carries the accounting after the retry"
else
  bad "the retry exited 0 with the index still holding the pre-failure baseline"
fi
if [ "$(git -C "$R23" show ":$BASE_REL")" = "$STALE_BASE" ]; then
  bad "the index baseline never moved off the pre-failure copy"
else
  ok "the staged baseline is the rewritten one, not the stale one"
fi
# The consequence the founder feels: the COMMIT carries the accounting, so a fresh
# clone reads it instead of re-deriving one. Cap 33 held through the scoping.
git -C "$R23" -c user.email=t@t -c user.name=t commit -qm "scoping (ASK-285)"
if [ "$(git -C "$R23" show "HEAD:$BASE_REL")" = "$(cat "$R23/$BASE_REL")" ]; then
  ok "the commit carries the rewritten baseline"
else
  bad "the commit went out with the pre-failure baseline"
fi
R23C=$(mktemp -d)/clone
git clone -q "$R23" "$R23C"
audit_rc "$R23C"
check "the clone of that commit audits green" 0 "RATCHET PASS" "$AUDIT_RC" "$AUDIT_OUT"
check_num "the clone reads the banked cap" 33 "$(cap_of "$R23C")"
# Negative controls. A run with the baseline already in the index must not claim a
# staging it did not do, and --no-stage keeps addressing the reader who asked for it.
audit_rc "$R23"
case "$AUDIT_OUT" in
  *staged*) bad "a settled baseline still reported a staging" ;;
  *) ok "a baseline already in the index is left alone" ;;
esac
scope_rule "$R23" alpha.md "q-system/output/**"
git -C "$R23" add -A
audit_rc "$R23" --no-stage
check "--no-stage still asks the reader, it does not stage" 0 "stage $R23/$BASE_REL" "$AUDIT_RC" "$AUDIT_OUT"
if [ "$(git -C "$R23" show ":$BASE_REL")" = "$(cat "$R23/$BASE_REL")" ]; then
  bad "--no-stage staged the baseline anyway"
else
  ok "--no-stage left the index alone"
fi

# The expensive shape, end to end: a rename behind a failed `git add`. Git reports
# a rename only in the commit that makes it, so a baseline left behind charges the
# whole rule as a deletion on the next run -- and here that run is a FRESH CLONE,
# where no hand edit is available and the founder's banked headroom is simply gone.
R24=$(mktemp -d); mk_fixture "$R24"
audit_rc "$R24"                       # bootstrap: cap 33, total 33
git -C "$R24" init -q
git -C "$R24" add -A
git -C "$R24" -c user.email=t@t -c user.name=t commit -qm "fixture (ASK-285)"
scope_rule "$R24" beta.md "q-system/output/**"
git -C "$R24" add -A
audit_rc "$R24"                       # the founder banks 20 lines of headroom
check_num "headroom banked before the rename" 33 "$(cap_of "$R24")"
git -C "$R24" -c user.email=t@t -c user.name=t commit -qm "scoping (ASK-285)"
git -C "$R24" mv .claude/rules/alpha.md .claude/rules/gamma.md
audit_with_path "$SHIM_ADD" "$R24"    # attempt 1: rewritten, unstageable, run fails
check "the rename attempt fails on the unstageable baseline" 1 "could not stage" "$AUDIT_RC" "$AUDIT_OUT"
audit_rc "$R24"                       # attempt 2 must still get it into the commit
git -C "$R24" -c user.email=t@t -c user.name=t commit -qm "rename (ASK-285)"
R24C=$(mktemp -d)/clone
git clone -q "$R24" "$R24C"
audit_rc "$R24C"
check_num "the clone keeps the banked cap through the rename" 33 "$(cap_of "$R24C")"
check "the clone still has its headroom" 0 "headroom 20" "$AUDIT_RC" "$AUDIT_OUT"

echo '== 30. mutation: decide staging from "changed" alone -> section 29 goes RED'
# A regression case never watched fail is not known to catch anything, and the ref
# hatch only reaches the previous commit. This restores the pre-fix condition in
# place: stage only when THIS run rewrote the file.
MUTS=$(mktemp -d)/mutant-staging.py
mkdir -p "$(dirname "$MUTS")"
python3 - "$AUDIT" "$MUTS" <<'PY'
import sys
src = open(sys.argv[1]).read()
needle = "    if write and (changed or baseline_unstaged(project_root)):\n"
assert needle in src, "the staging condition moved; update the mutation"
open(sys.argv[2], "w").write(src.replace(needle, "    if write and changed:\n", 1))
PY
RM6=$(mktemp -d); AUDIT_SAVE="$AUDIT"; AUDIT="$MUTS"; mk_fixture "$RM6"
audit_rc "$RM6"
git -C "$RM6" init -q
git -C "$RM6" add -A
git -C "$RM6" -c user.email=t@t -c user.name=t commit -qm "fixture (ASK-285)"
scope_rule "$RM6" beta.md "q-system/output/**"
git -C "$RM6" add -A
audit_with_path "$SHIM_ADD" "$RM6"
audit_rc "$RM6"
if [ "$(git -C "$RM6" show ":$BASE_REL")" = "$(cat "$RM6/$BASE_REL")" ]; then
  bad "mutant staged the baseline; the mutation does not reach the fix"
else
  ok "mutant retry exits $AUDIT_RC with the index still stale"
fi
AUDIT="$AUDIT_SAVE"

echo "== 31. the over-cap refusal names the total the tree actually had"
# PR #88 round 6, minor. The refusal printed the CAP as the left-hand number of
# "always-on total X -> Y". Before any headroom is banked cap == prev_total and the
# two readings coincide, which is why section 5 never caught it. After scoping,
# they come apart: the tree last recorded 13 always-on lines under a cap of 33, so
# "33 -> 34" states a growth that never happened and hides both the real +21 and
# the fact that 20 banked lines were spent getting there. An agent reading it looks
# for one line to trim.
R25=$(mktemp -d); mk_fixture "$R25"
audit_rc "$R25"                                   # bootstrap: cap 33, total 33
scope_rule "$R25" beta.md "q-system/output/**"
audit_rc "$R25"                                   # cap 33, total 13, headroom 20
check "headroom banked before the over-cap append" 0 "headroom 20" "$AUDIT_RC" "$AUDIT_OUT"
for i in $(seq 1 21); do printf '\nAlpha overflow line %s.\n' "$i" >> "$R25/.claude/rules/alpha.md"; done
audit_rc "$R25"                                   # total 13 + 21 = 34, cap 33
check "over-cap exits 1 behind banked headroom" 1 "RATCHET FAIL" "$AUDIT_RC" "$AUDIT_OUT"
check "names the total the tree actually had" 1 "always-on total 13 -> 34" "$AUDIT_RC" "$AUDIT_OUT"
check "names the cap it broke" 1 "cap 33 exceeded by 1" "$AUDIT_RC" "$AUDIT_OUT"
check "names the headroom that got spent" 1 "banked headroom was 20" "$AUDIT_RC" "$AUDIT_OUT"
case "$AUDIT_OUT" in
  *"total 33 -> 34"*) bad "the refusal still reports the cap as the previous total" ;;
  *) ok "the cap is not passed off as a total the tree ever had" ;;
esac
check_num "a failing run still does not move the cap" 33 "$(cap_of "$R25")"
# Negative control: with nothing banked, cap == prev_total and the sentence is the
# one section 5 pins. The fix must read the baseline, not rename the numbers.
R26=$(mktemp -d); mk_fixture "$R26"
audit_rc "$R26"                                   # cap 33, total 33, nothing banked
printf '\nAn eleventh always-on line.\n' >> "$R26/.claude/rules/alpha.md"
audit_rc "$R26"
check "no headroom banked: the transition is unchanged" 1 "always-on total 33 -> 34" "$AUDIT_RC" "$AUDIT_OUT"
check "and it says the headroom was zero" 1 "banked headroom was 0" "$AUDIT_RC" "$AUDIT_OUT"

echo "== 32. mutation: report the cap as the previous total -> section 31 goes RED"
# A regression case never watched fail is not known to catch anything, and the ref
# hatch only reaches the previous commit. This puts the pre-fix reading back in
# place: the left-hand number is the cap again.
MUTT=$(mktemp -d)/mutant-failtext.py
mkdir -p "$(dirname "$MUTT")"
python3 - "$AUDIT" "$MUTT" <<'PY'
import sys
src = open(sys.argv[1]).read()
needle = "    ).format(cap=cap, total=total, over=total - cap, prev=prev_total,\n"
assert needle in src, "the fail-text format call moved; update the mutation"
open(sys.argv[2], "w").write(src.replace(
    needle,
    "    ).format(cap=cap, total=total, over=total - cap, prev=cap,\n", 1))
PY
RM7=$(mktemp -d); AUDIT_SAVE="$AUDIT"; AUDIT="$MUTT"; mk_fixture "$RM7"
audit_rc "$RM7"
scope_rule "$RM7" beta.md "q-system/output/**"
audit_rc "$RM7"
for i in $(seq 1 21); do printf '\nAlpha overflow line %s.\n' "$i" >> "$RM7/.claude/rules/alpha.md"; done
audit_rc "$RM7"
case "$AUDIT_OUT" in
  *"always-on total 13 -> 34"*) bad "mutant still names the real total; the mutation does not reach the fix" ;;
  *) ok "mutant reports the cap as the previous total" ;;
esac
AUDIT="$AUDIT_SAVE"

echo "== 33. scoping frontmatter cannot hide deleted body lines"
# PR #88 round 7, minor. Every count here is substantive-lines-of-the-file, and a
# scoping block is four substantive lines of its own ("---", "paths:", the glob,
# "---"). So scoping INFLATES the file's count by four at the same moment the rule
# leaves the always-on set. The scoped credit was min(before, after), and `after`
# carried that inflation, so up to four deleted BODY lines fitted underneath it:
# they never tightened the cap and became permanent headroom instead. Headroom is
# the one thing this accounting must never mint.
R27=$(mktemp -d); mk_fixture "$R27"
audit_rc "$R27"                                   # bootstrap: cap 33, total 33
check_num "cap before the scoping step" 33 "$(cap_of "$R27")"
# Scope beta AND gut four of its body lines in one step. 4 frontmatter + 1 heading
# + 1 lint line + 14 body = 20 counted lines, exactly the 20 it was counted for
# while always-on, so a whole-file compare sees nothing gone at all.
{ echo "---"; echo "paths:"; echo "  - \"q-system/output/**\""; echo "---"
  echo "# Beta Rule (ENFORCED)"; echo
  echo "The deterministic half is \`beta-lint.py\`."; echo
  for i in $(seq 1 14); do echo "Beta line $i."; echo; done
} > "$R27/.claude/rules/beta.md"
audit_rc "$R27"
check_num "the four gutted body lines tighten the cap" 29 "$(cap_of "$R27")"
check "headroom is only what actually survived" 0 "headroom 16" "$AUDIT_RC" "$AUDIT_OUT"
case "$AUDIT_OUT" in
  *"headroom 20"*) bad "scoping frontmatter minted headroom for four deleted lines" ;;
  *) ok "the scoping block is not credited as surviving instruction lines" ;;
esac
# The consequence, end to end: with 4 minted lines the tree can spend headroom it
# never had. Under the honest cap of 29 a 17-line append is over budget and the
# commit-time gate has to refuse it.
for i in $(seq 1 17); do printf '\nAlpha overflow line %s.\n' "$i" >> "$R27/.claude/rules/alpha.md"; done
audit_rc "$R27"                                   # total 3 + 27 = 30 vs cap 29
check "an append past the surviving headroom is refused" 1 "RATCHET FAIL" "$AUDIT_RC" "$AUDIT_OUT"
check "and it names the cap the deletion set" 1 "cap 29 exceeded by 1" "$AUDIT_RC" "$AUDIT_OUT"

# Negative control 1: scoping with the body INTACT still banks the whole rule. The
# fix must charge the missing body, not the frontmatter it grew.
R28=$(mktemp -d); mk_fixture "$R28"
audit_rc "$R28"
scope_rule "$R28" beta.md "q-system/output/**"
audit_rc "$R28"
check_num "a clean scoping still holds the cap" 33 "$(cap_of "$R28")"
check "a clean scoping still banks every line" 0 "headroom 20" "$AUDIT_RC" "$AUDIT_OUT"

# Negative control 2: a baseline recorded BEFORE this fix carries no body counts.
# The fallback reads the whole recorded count as body, which can over-charge a rule
# that already had frontmatter -- it never mints. Here it lands on the same 29.
R29=$(mktemp -d); mk_fixture "$R29"
audit_rc "$R29"
python3 - "$R29/$BASE_REL" <<'PY'
import json, sys
b = json.load(open(sys.argv[1]))
b.pop("always_on_body", None)
json.dump(b, open(sys.argv[1], "w"), indent=2)
PY
{ echo "---"; echo "paths:"; echo "  - \"q-system/output/**\""; echo "---"
  echo "# Beta Rule (ENFORCED)"; echo
  echo "The deterministic half is \`beta-lint.py\`."; echo
  for i in $(seq 1 14); do echo "Beta line $i."; echo; done
} > "$R29/.claude/rules/beta.md"
audit_rc "$R29"
check_num "a pre-fix baseline still charges the deletion" 29 "$(cap_of "$R29")"

echo "== 34. mutation: credit the scoped rule its whole new count -> section 33 goes RED"
# A regression case never watched fail is not known to catch anything, and the ref
# hatch only reaches the previous commit. This puts the pre-fix compare back in
# place: the scoped credit is the whole file again, frontmatter included.
MUTB=$(mktemp -d)/mutant-scopedbody.py
mkdir -p "$(dirname "$MUTB")"
python3 - "$AUDIT" "$MUTB" <<'PY'
import sys
src = open(sys.argv[1]).read()
needle = "    return max(0, before - max(0, body_before - body_after))\n"
assert needle in src, "scoped_credit moved; update the mutation"
open(sys.argv[2], "w").write(src.replace(needle, "    return before\n", 1))
PY
RM8=$(mktemp -d); AUDIT_SAVE="$AUDIT"; AUDIT="$MUTB"; mk_fixture "$RM8"
audit_rc "$RM8"
{ echo "---"; echo "paths:"; echo "  - \"q-system/output/**\""; echo "---"
  echo "# Beta Rule (ENFORCED)"; echo
  echo "The deterministic half is \`beta-lint.py\`."; echo
  for i in $(seq 1 14); do echo "Beta line $i."; echo; done
} > "$RM8/.claude/rules/beta.md"
audit_rc "$RM8"
if [ "$(cap_of "$RM8")" = "29" ]; then
  bad "mutant still charges the deletion; the mutation does not reach the fix"
else
  ok "mutant banks the four deleted lines as headroom (cap $(cap_of "$RM8"))"
fi
AUDIT="$AUDIT_SAVE"

echo "== 35. an ALREADY over-cap tree does not license another over-cap edit"
# gate_regression asked one question of every gate: was it passing before and not
# passing after. That is right for a parse gate -- a settings.json that was already
# broken is not this tool's doing -- and wrong for a BUDGET. A tree the founder had
# already pushed past the cap made the gate FAIL before AND after, which is not
# pass -> fail, so the engine grew it further and printed "gates held". That is
# section 4's defect exactly, reached through the one door section 4 left open
# (PR #88 round 10).
R30=$(mktemp -d); mk_fixture "$R30"
audit_rc "$R30"                      # bootstrap: cap 33, total 33, headroom 0
# Straight into the tree, not through the engine: this is the founder hand-editing
# a rule, which is how a tree gets over its cap in the first place.
printf '\nA founder edit, one line past the cap.\n' >> "$R30/.claude/rules/alpha.md"
audit_rc "$R30"
check "the tree is already red before the engine runs" 1 "cap 33 exceeded by 1" "$AUDIT_RC" "$AUDIT_OUT"
append_proposal "$R30/prop.json" alpha.md "And one more on top of that."
apply "$R30/prop.json" "$R30"
check "the engine refuses to make a red tree redder" 3 "gate 'instruction-budget'" "$APPLY_RC" "$APPLY_OUT"
check "and names how much worse it got" 3 "always-on overage 1 -> 2" "$APPLY_RC" "$APPLY_OUT"
if grep -q "And one more on top of that" "$R30/.claude/rules/alpha.md"; then
  bad "reverted apply left its line on disk"
else
  ok "reverted apply restored alpha.md"
fi
audit_rc "$R30"
check "the tree is no worse than the engine found it" 1 "cap 33 exceeded by 1" "$AUDIT_RC" "$AUDIT_OUT"
# NEGATIVE CONTROL, and the reason the fix is "not worse" rather than "must be
# green": a paths-scoped rule costs 0 always-on lines. The overage is unchanged, so
# this still lands. A blanket refusal on a red tree would wall off every edit that
# does not touch the budget at all, including the ones that walk it back.
cat > "$R30/prop2.json" <<'JSON'
{
  "schema_version": 1,
  "slug": "scoped-rule-on-a-red-tree",
  "reason": "PR #88 round 10 control: costs 0 always-on lines, so the overage holds",
  "edits": [
    {
      "file": ".claude/rules/delta.md",
      "op": "create_file",
      "insert": "---\npaths:\n  - \"q-system/output/**\"\n---\n\n# Delta Rule\n\nDelta line 1.\n",
      "reason": "scoped, so it never enters the always-on total"
    }
  ]
}
JSON
apply "$R30/prop2.json" "$R30"
check "an edit that costs no always-on lines still lands on a red tree" 0 "OK applied scoped-rule-on-a-red-tree" "$APPLY_RC" "$APPLY_OUT"

echo "== 36. mutation: ask the gate only 'was it passing' -> section 35 goes RED"
# The ref hatch reaches the previous commit; this puts the boolean-only comparison
# back in place, so the case is watched failing for the reason it exists.
MUTC=$(mktemp -d)/mutant-boolgate.py
mkdir -p "$(dirname "$MUTC")"
python3 - "$SCRIPT_DIR/../apply_claude_changes.py" "$MUTC" <<'PY'
import sys
src = open(sys.argv[1]).read()
needle = "        if isinstance(b, tuple):\n"
assert needle in src, "the overage compare moved; update the mutation"
head, sep, tail = src.partition(needle)
# Everything from the tuple arm to the end of gate_regression becomes dead.
end = tail.index("    return None\n")
open(sys.argv[2], "w").write(head + "        if False:\n            pass\n" + tail[end:])
PY
RM9=$(mktemp -d); mk_fixture "$RM9"
audit_rc "$RM9"
printf '\nA founder edit, one line past the cap.\n' >> "$RM9/.claude/rules/alpha.md"
append_proposal "$RM9/prop.json" alpha.md "And one more on top of that."
APPLY_ENGINE="$MUTC" apply "$RM9/prop.json" "$RM9"
check "mutant grows a tree that was already over its cap" 0 "OK applied" "$APPLY_RC" "$APPLY_OUT"

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ]
