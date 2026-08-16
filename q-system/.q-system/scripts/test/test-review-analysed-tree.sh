#!/usr/bin/env bash
# Reproducer for the analysed-tree guard in pr-review-agent.sh (ASK-830).
# Pairs with analysed_tree_conflict() and the REFUSING branch it feeds.
#
# THE DEFECT IT PINS. pr-review-agent.sh posts kipi/reviewer-approved -- a
# REQUIRED check on main with enforce_admins -- against the head sha it was
# invoked for, regardless of which tree the model actually read. Measured on
# PR #165 round 2, 2026-08-14 PT: the wrapper detached a review tree at c87245b0
# and logged `commit status posted: kipi/reviewer-approved=failure on c87245b0`,
# while the review body says "GitHub was also unreachable, so the review used the
# locally available PR tip `0880859e`" and every reproducer in it runs
# `git show 0880859e:fleet-unblock.py`. 0880859e is the merge-base from before
# the fixes under review. Attempt 2 of the same command, same head, read the
# right tree and returned two entirely different findings.
#
# WHY IT IS NOT THE ASK-221 GUARD. test-review-tree-guard.sh covers the
# head-moved-between-reads race: two reads of the PR head disagree because
# something is pushing. Here NOTHING moves -- the two reads agree perfectly and
# the model still read another commit. A two-read comparison structurally cannot
# see it. Case 4 below asserts that older guard still fires, because this issue
# adds a check and must not replace one.
#
# NEGATIVE SELF-TEST (case 2). A guard that refuses everything would pass case 1
# while wedging every correct PR in the fleet behind a required check whose only
# documented escape disables branch protection fleet-wide. Case 2 drives the SAME
# harness with the round-3 review of the same PR at the same head and asserts the
# status IS posted. Case 1 without case 2 is not evidence.
#
# Point it at an older copy to watch case 1 fail:
#   KIPI_TEST_REVIEWER_REF=85f556dc bash test-review-analysed-tree.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_SCRIPTS="$SCRIPT_DIR/.."
ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
FIX="$SCRIPT_DIR/fixtures/review-analysed-tree"
REF="${KIPI_TEST_REVIEWER_REF:-}"

PASS=0
ok()   { PASS=$((PASS+1)); echo "  ok: $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }

command -v git >/dev/null 2>&1 || fail "git not on PATH"
command -v python3 >/dev/null 2>&1 || fail "python3 not on PATH (the record writer is a real python3 heredoc)"

# The head sha PR #165 round 2 was actually posted against. Both fixtures below
# were produced by runs invoked for THIS commit; only one of them read it.
HEAD_SHA="c87245b06e0f2c9e0c4b7a1d3f5e8a2b9c6d4e10"
WRONG_TREE="0880859e"

WRONG_FIX="$FIX/pr-165-round2-wrong-tree.md"
RIGHT_FIX="$FIX/pr-165-round3-right-tree.md"
for f in "$WRONG_FIX" "$RIGHT_FIX"; do
  [ -s "$f" ] || fail "missing fixture: $f (see $FIX/PROVENANCE.md)"
done

# THE FIXTURES ARE ASSERTED, NOT ASSUMED. A fixture that quietly lost the line
# the guard keys on would make case 1 pass for the wrong reason -- the failure
# mode this repo keeps finding. These two greps are what make the cases mean
# something, so they run before either case does.
grep -q "$WRONG_TREE" "$WRONG_FIX" \
  || fail "premise broken: the wrong-tree fixture no longer cites $WRONG_TREE, so case 1 would pass
      because the fixture is empty of the defect, not because the guard works"
grep -q "$WRONG_TREE" "$RIGHT_FIX" \
  && fail "premise broken: the right-tree fixture cites $WRONG_TREE, so case 2 cannot distinguish
      a working guard from one that refuses everything"
ok "premises: the wrong-tree fixture cites $WRONG_TREE and the right-tree one does not"

W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
REPO="$W/repo"
S="$REPO/q-system/.q-system/scripts"
mkdir -p "$S/test" "$W/bin"

# The scripts under test, all from ONE source: the reviewer sources the lib, and
# mixing an old reviewer with a new lib tests a combination that never shipped.
for f in pr-review-agent.sh pr-verdict-lib.sh repo-slug-lib.sh; do
  if [ -n "$REF" ]; then
    git -C "$ROOT" show "$REF:q-system/.q-system/scripts/$f" > "$S/$f" 2>/dev/null \
      || cp "$SRC_SCRIPTS/$f" "$S/$f" \
      || fail "cannot read $f at ref $REF or from the working tree"
  else
    cp "$SRC_SCRIPTS/$f" "$S/$f" || fail "cannot copy $f from the working tree"
  fi
done
REVIEWER="$S/pr-review-agent.sh"
echo "reviewer under test: ${REF:-working tree} ($(wc -l < "$REVIEWER" | tr -d ' ') lines)"

git -C "$REPO" init -q 2>/dev/null || fail "git init failed"
printf 'sandbox\n' > "$REPO/marker.txt"
git -C "$REPO" add -A >/dev/null 2>&1
git -C "$REPO" -c user.name=treetest -c user.email=tree@test \
  commit -q -m "sandbox base" --no-verify >/dev/null 2>&1 || fail "sandbox commit failed"

cat > "$W/notify.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$W/notify.sh"

# $1 = case name, $2 = review body the codex stub emits, $3.. = the shas `gh pr
# view` reports, in order (one value = both reads agree; two = the head moved).
#
# The gh stub LOGS EVERY CALL. "Was a status posted?" has to be answered by the
# side effect the real run performs -- a POST to repos/<slug>/statuses/<sha> --
# and never by stdout prose, because prose is exactly what the live failure got
# right while doing the wrong thing.
run_case() {
  local name="$1" body="$2"; shift 2
  local d="$W/$name"; mkdir -p "$d/bin" "$d/home"
  printf '%s\n' "$@" > "$d/oids"
  cat > "$d/bin/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$d/gh-calls.log"
case "\$1 \$2" in
  "pr view")
    n=0
    [ -f "$d/view-count" ] && n=\$(cat "$d/view-count")
    n=\$((n+1)); printf '%s' "\$n" > "$d/view-count"
    oid="\$(sed -n "\${n}p" "$d/oids")"
    [ -n "\$oid" ] || oid="\$(tail -n1 "$d/oids")"
    printf '%s\tanalysed tree case $name\n' "\$oid" ;;
  "pr diff")    printf 'diff --git a/marker.txt b/marker.txt\n' ;;
  "pr comment") printf 'https://github.com/o/r/pull/901#issuecomment-1\n' ;;
esac
exit 0
EOF
  cat > "$d/bin/codex" <<EOF
#!/usr/bin/env bash
: > "$d/codex-ran"
cat "$body"
EOF
  cat > "$d/bin/claude" <<EOF
#!/usr/bin/env bash
: > "$d/claude-ran"
cat "$body"
EOF
  chmod +x "$d/bin/gh" "$d/bin/codex" "$d/bin/claude"
  ( PATH="$d/bin:$PATH" HOME="$d/home" KIPI_NOTIFY="$W/notify.sh" \
      bash "$REVIEWER" 901 --post ) >"$d/out.txt" 2>"$d/err.txt"
  RC=$?
  CASE_DIR="$d"
}

status_posted() { grep -qE 'statuses/' "$1/gh-calls.log" 2>/dev/null; }

# --- case 1: the defect. A review that read another tree must not post. -------
run_case wrong "$WRONG_FIX" "$HEAD_SHA"
[ "$RC" -ne 0 ] \
  || fail "THE DEFECT IS LIVE: the reviewer exited 0 on a review whose own commands read $WRONG_TREE
      while the status names ${HEAD_SHA:0:8}. A caller cannot tell this from a real review. stdout:
$(sed 's/^/        /' "$CASE_DIR/out.txt")"
ok "a wrong-tree review exits non-zero (rc=$RC)"

status_posted "$CASE_DIR" \
  && fail "A REQUIRED CHECK WAS SET FROM A REVIEW OF ANOTHER COMMIT. gh was asked to POST a commit
      status even though the review read $WRONG_TREE. That is the ASK-830 defect verbatim:
$(grep 'statuses/' "$CASE_DIR/gh-calls.log" | sed 's/^/        /')"
ok "no commit status is posted for a wrong-tree review"

grep -qE 'pr comment' "$CASE_DIR/gh-calls.log" \
  && fail "the wrong-tree findings were posted to the PR. They cite line numbers from another commit,
      so the author's next round is spent on lines that do not exist in their diff"
ok "no PR comment either (the findings are of another commit)"

grep -q "REFUSING" "$CASE_DIR/err.txt" \
  || fail "it declined SILENTLY. An absent status cannot tell the operator 'not reviewed yet' from
      'reviewed the wrong thing'. stderr was:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
grep -q "$WRONG_TREE" "$CASE_DIR/err.txt" \
  || fail "the refusal does not name the tree that was actually read ($WRONG_TREE)"
grep -q "${HEAD_SHA:0:8}" "$CASE_DIR/err.txt" \
  || fail "the refusal does not name the sha the status would have carried (${HEAD_SHA:0:8})"
ok "the refusal is loud and names both shas"

# --- case 2: the negative self-test. A correct review must still post. --------
run_case right "$RIGHT_FIX" "$HEAD_SHA"
[ "$RC" -eq 0 ] \
  || fail "THE GUARD REFUSES EVERYTHING. Round 3 of the SAME PR at the SAME head -- the run that read
      the right tree -- exited $RC, so case 1 proves nothing and every correct PR in the fleet
      wedges behind a required check. stderr was:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
ok "a right-tree review exits 0 (the guard can pass, so case 1 is meaningful)"

status_posted "$CASE_DIR" \
  || fail "no commit status posted for a review that read the correct tree. gh calls were:
$(sed 's/^/        /' "$CASE_DIR/gh-calls.log")"
ok "the commit status IS posted for a right-tree review"

grep -q "REFUSING" "$CASE_DIR/err.txt" && fail "it refused a review of its own head sha"
ok "no refusal on the healthy path"

# --- case 3: silence is not a refusal ----------------------------------------
# A review that declares no tree at all is not refused. Under-refusal costs one
# wrong review; a false refusal costs every correct PR at once, escapable only
# through break-glass-main-protection.sh, which disables protection fleet-wide.
cat > "$W/silent.md" <<'EOF'
## VERDICT: APPROVE

Nothing survived reproduction.

FINDINGS:
END FINDINGS
EOF
run_case silent "$W/silent.md" "$HEAD_SHA"
[ "$RC" -eq 0 ] || fail "a review that names no tree was refused; the guard detects a contradiction,
      and there is nothing here to contradict. stderr:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
status_posted "$CASE_DIR" || fail "a review that names no tree posted no status"
ok "a review that declares no tree is not refused (contradiction, not proof-of-match)"

# --- case 4: the ASK-221 head-moved refusal is untouched ---------------------
# This is a DIFFERENT check and this issue must not replace it. Two reads of the
# PR head that disagree still refuse, before the reviewer is ever dispatched.
MOVED="f380d11b7c2a4e6b8d0f1a3c5e7b9d2f4a6c8e01"
run_case moved "$RIGHT_FIX" "$HEAD_SHA" "$MOVED"
[ "$RC" -ne 0 ] || fail "REGRESSION: the head moved between two reads and the reviewer proceeded.
      That is the ASK-221 guard, which this issue must not replace"
grep -q "head moved between two reads" "$CASE_DIR/err.txt" \
  || fail "REGRESSION: the head-moved refusal no longer names itself. stderr was:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
status_posted "$CASE_DIR" && fail "REGRESSION: a status was posted after the head moved mid-review"
ok "the ASK-221 head-moved refusal still fires (both guards live, neither replaced)"

echo "PASS ($PASS checks)"
