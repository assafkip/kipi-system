set -u
# Mutation harness for PR #42 round-2 rework (ASK-218). NOT committed: it exists
# to prove the new cases are falsifiable -- each mutant reintroduces one of the
# three review findings and must turn the suite RED.
SRC="/Users/assafkipnis/.config/kipi/worktrees/ask-218"
BASE="$(mktemp -d)"
echo "mutant tree: $BASE"

mk() {  # mk <name> <python-patch>
  local n="$1" patch="$2"
  local d="$BASE/$n"
  mkdir -p "$d/q-system/.q-system"
  cp -R "$SRC/q-system/.q-system/scripts" "$d/q-system/.q-system/scripts"
  python3 - "$d/q-system/.q-system/scripts/converge.sh" <<PY
import sys
p = sys.argv[1]
s = open(p).read()
$patch
open(p, "w").write(s)
PY
}

run() {
  local n="$1"
  echo "########## MUTANT $n ##########"
  bash "$BASE/$n/q-system/.q-system/scripts/test/test-severity-floor.sh" 2>&1 \
    | grep -E "^(FAIL|PASS)" | head -6
  echo
}

# M1 (finding 1): the page ignores the receipt miss again -- the shipped defect.
mk m1-page 'assert s.count("""if [ -n "$RECEIPT_MISS" ]; then""") == 1
s = s.replace("""if [ -n "$RECEIPT_MISS" ]; then""", "if false; then")'

# M2 (finding 3): the push guard reads a rev-list error as "nothing to push".
mk m2-push '''old_read = """  ahead=\"$(git -C \"$tree\" rev-list --count \"origin/$BRANCH..HEAD\" 2>>\"$LOG\")\" || ahead=\"\""""
assert s.count(old_read) == 1
s = s.replace(old_read, """  ahead=\"$(git -C \"$tree\" rev-list --count \"origin/$BRANCH..HEAD\" 2>/dev/null || echo 0)\"""")
old_if = """  if [ -z \"$ahead\" ] || [ \"$ahead\" != \"0\" ]; then"""
assert s.count(old_if) == 1
s = s.replace(old_if, """  if [ \"$ahead\" != \"0\" ]; then""")'''

# M3A (finding 2): a receipt is ALSO written from the stale-approval branch.
mk m3a-stale '''anchor = """    say \"round $ROUND: PR #$PR reads"""
assert s.count(anchor) == 1
s = s.replace(anchor, """    receipt_ensure \"$SHA\" \"$REVIEWS_DIR/pr-$PR.verdict.json\"\n""" + anchor)'''

# M3B (finding 2): a receipt is written for EVERY verdict, before the gate dispatch.
mk m3b-always '''anchor = """  [ -n \"$GATE_NOTE\" ] && say \"$GATE_NOTE\""""
assert s.count(anchor) == 1
s = s.replace(anchor, anchor + """\n  receipt_ensure \"$SHA\" \"$REVIEWS_DIR/pr-$PR.verdict.json\"""")'''

# M4 (finding 2, related): the writer never reads ts, so reviewed_at is never claimed.
mk m4-noreviewed '''old = """        reviewed_at = json.load(handle).get(\"ts\", \"\") or \"\""""
assert s.count(old) == 1
s = s.replace(old, """        reviewed_at = \"\"""")'''

for m in m1-page m2-push m3a-stale m3b-always m4-noreviewed; do run "$m"; done
