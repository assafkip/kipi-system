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
# = 9 conditional lines. Credit is min(20, 9) = 9; the other 11 are a deletion,
# so the cap tightens by 11 to 22 and headroom is 22 - 13 = 9.
{ echo "---"; echo "paths:"; echo "  - \"q-system/output/**\""; echo "---"
  echo "# Beta Rule (ENFORCED)"; echo
  echo "The deterministic half is \`beta-lint.py\`."; echo
  echo "Beta line 1."; echo; echo "Beta line 2."; echo; echo "Beta line 3."
} > "$R7/.claude/rules/beta.md"
audit_rc "$R7"
check_num "cap tightened by the gutted half" 22 "$(cap_of "$R7")"
check "credit is only the surviving lines" 0 "scoped: beta.md (9)" "$AUDIT_RC" "$AUDIT_OUT"
check "headroom is the credited amount" 0 "headroom 9" "$AUDIT_RC" "$AUDIT_OUT"

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
needle = "        elif name in conditional:\n            after = min(before, conditional[name])\n"
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
out = re.sub(r'\n    \("instruction-budget",\n.*?\n.*?\n', "\n", src, count=1, flags=re.S)
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


echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ]
