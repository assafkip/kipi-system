#!/bin/bash
# Pairs with: human-handoff-audit.py (ASK-310).
#
# WHY THIS EXISTS AT ALL. The audit was written, used by hand to take the repo
# from 46 unexplained handoffs to 0, and then wired to nothing and never tested --
# on the same day, in the same session, whose entire subject was "built but not
# wired". A sweep run once by hand is a cleanup, not a gate: nothing stops the
# 47th handoff landing tomorrow.
#
# The negative half is the load-bearing half. Four exclusion rules were added
# because the detector kept flagging its own cure: a comment that NEGATES a
# handoff, a comment QUOTING one it removed, a test fixture, and generated
# report prose. Each is pinned here, because loosening any of them silently is
# how the audit starts reporting 40 again and gets ignored.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUDIT="$(cd "$HERE/.." && pwd)/human-handoff-audit.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0
ok()  { printf '  \033[0;32mPASS\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad() { printf '  \033[0;31mFAIL\033[0m %s\n     %s\n' "$1" "${2:-}"; FAIL=$((FAIL+1)); }

mkdir -p "$WORK/q-system/.q-system/scripts/test" "$WORK/q-system/output"
cd "$WORK" && git init -q .

cat > q-system/.q-system/scripts/planted.sh <<'FIXTURE'
#!/bin/bash
# CAUGHT: names a human as the actor
echo "this run needs a human to finish it"
# CAUGHT: names the founder as the actor
echo "the founder must approve the next step"
# CAUGHT: defers to an unnamed someone
echo "it sits there until someone runs the job"
# CAUGHT: hands over a command
echo "Do: git merge --ff-only origin/main"
# NOT CAUGHT: negated -- this is the cure, not the defect
echo "Sana is a robot. She does not need a human to keep going."
# NOT CAUGHT: historical -- a comment quoting wording that was removed
# This block used to end here with a page carrying
#   "Do: cd $REPO && git merge --ff-only origin/main"
# NOT CAUGHT: declared with the class that makes it human-only
# human-required: irreversible-git -- resolving a conflict picks which side wins
echo "this one needs a human"
FIXTURE

# NOT CAUGHT: a test fixture quoting a handoff is exercising the detector
cat > q-system/.q-system/scripts/test/test-fixture.sh <<'FIXTURE'
echo "needs a human to look at this"
FIXTURE

# NOT CAUGHT: generated report prose argues ABOUT the system
cat > q-system/output/report.py <<'FIXTURE'
TEXT = "the founder must manually copy it across, which is the limitation"
FIXTURE

git add -A >/dev/null 2>&1
git -c user.email=t@t -c user.name=t commit -qm fixture >/dev/null 2>&1

OUT="$(python3 "$AUDIT" --repo "$WORK" 2>&1)"

echo "== real handoffs are caught =="
for phrase in "needs a human to finish" "founder must approve" "until someone runs" "Do: git merge"; do
  printf '%s' "$OUT" | grep -qi "$phrase" \
    && ok "catches: $phrase" \
    || bad "MISSED: $phrase" "$OUT"
done

echo
echo "== the four exclusions hold =="
printf '%s' "$OUT" | grep -q "does not need a human" \
  && bad "flags a NEGATED handoff -- the detector is reporting its own cure" "$OUT" \
  || ok "negated handoff not flagged"
printf '%s' "$OUT" | grep -q "used to end here" \
  && bad "flags HISTORICAL text quoting removed wording" "$OUT" \
  || ok "historical quote not flagged"
printf '%s' "$OUT" | grep -q "test-fixture.sh" \
  && bad "flags a TEST FIXTURE that quotes a handoff" "$OUT" \
  || ok "test fixture not flagged"
printf '%s' "$OUT" | grep -q "output/report.py" \
  && bad "flags GENERATED report prose" "$OUT" \
  || ok "generated output not flagged"
# Match the declared SITE's own text, not the string "human-required" -- the
# audit prints that word in its own fix instructions, so grepping the whole
# output matched the help text and failed a correct implementation.
printf '%s' "$OUT" | grep -q "this one needs a human" \
  && bad "flags a site that DECLARED its class" "$OUT" \
  || ok "a declared human-required site is accepted"

echo
echo "== a clean tree is reported clean =="
mkdir -p "$WORK/clean/q-system/.q-system/scripts" && cd "$WORK/clean" && git init -q .
printf '#!/bin/bash\necho "the loop retries on the next dispatch"\n' \
  > q-system/.q-system/scripts/good.sh
git add -A >/dev/null 2>&1
git -c user.email=t@t -c user.name=t commit -qm clean >/dev/null 2>&1
python3 "$AUDIT" --repo "$WORK/clean" >/dev/null 2>&1 \
  && ok "exit 0 on a tree with no handoffs" \
  || bad "a clean tree was reported as violating"

echo
echo "  passed: $PASS   failed: $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
