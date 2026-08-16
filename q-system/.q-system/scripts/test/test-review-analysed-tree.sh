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
# NEGATIVE SELF-TEST (case 5, and why case 2 is NOT it). A guard that refuses
# everything would pass case 1 while wedging every correct PR in the fleet behind
# a required check whose only documented escape disables branch protection
# fleet-wide. Case 2 was written as that self-test and does not do the job: the
# round-3 fixture declares NO tree at all, so for this guard it is byte-equivalent
# to case 3's silence. Measured on PR #197 round 2 -- with the head-sha exemption
# deleted, so the guard refuses EVERY review that names a tree, the suite still
# reported PASS (10 checks). Case 5 is the real one: a review that runs
# `git show <head>:<path>` and must still post. Case 5m re-runs it against a
# mutant with that exemption removed and requires it to go RED, so the suite
# cannot report a passing guard it never exercised.
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
  # CHANGED_LIST is the PR's changed-file set (round 5, major 2). Set by a case
  # that needs it; empty means the reviewer resolves it itself, which under this
  # gh stub yields a malformed answer and therefore no exemption.
  ( PATH="$d/bin:$PATH" HOME="$d/home" KIPI_NOTIFY="$W/notify.sh" \
      KIPI_PR_CHANGED_FILES="${CHANGED_LIST:-}" \
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

# mkbody <outfile>; stdin is the review body, @HEAD@/@WRONG@ substituted. Bodies
# are written here rather than added as fixtures because these are SHAPES, not
# payloads -- the two real payloads are the .md fixtures, and inventing a fixture
# to stand in for a real one is the failure this repo keeps finding.
mkbody() {
  local out="$1" raw
  raw="$(cat)"
  raw="${raw//@HEAD@/$HEAD_SHA}"
  raw="${raw//@WRONG@/$WRONG_TREE}"
  printf '%s\n' "$raw" > "$out"
}

# --- case 5: THE negative self-test -- a review that opens the head must post --
# The one case 2 cannot be. This body declares a tree, and it declares the RIGHT
# one, so it drives the head-sha exemption that case 2 never reaches.
mkbody "$W/declares-head.md" <<'EOF'
## VERDICT: APPROVE

Reproduced against the PR tip `@HEAD@`.

```
git show @HEAD@:fleet-unblock.py > "$tmp/fleet-unblock.py"
python3 -m pytest -q "$tmp/fleet-unblock.py" || true
```

FINDINGS:
END FINDINGS
EOF
run_case declares_head "$W/declares-head.md" "$HEAD_SHA"
[ "$RC" -eq 0 ] \
  || fail "THE GUARD REFUSES A REVIEW OF ITS OWN HEAD. The body runs
      \`git show ${HEAD_SHA:0:8}:fleet-unblock.py\` and nothing else, so there is nothing to
      contradict. Every correct PR in the fleet wedges behind a required check. stderr:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
status_posted "$CASE_DIR" \
  || fail "no commit status posted for a review that opened the head. gh calls were:
$(sed 's/^/        /' "$CASE_DIR/gh-calls.log")"
ok "a review that opens the HEAD tree posts its status (the exemption is exercised)"

# --- case 5m: and that case can actually go RED --------------------------------
# Delete the head-sha exemption on a copy and case 5 must fail. Without this the
# suite cannot distinguish the shipped guard from one that refuses everything --
# which is exactly how the fleet-wedging version shipped green.
MUT="$W/mutant"
mkdir -p "$MUT"
cp "$S"/pr-review-agent.sh "$S"/pr-verdict-lib.sh "$S"/repo-slug-lib.sh "$MUT/" \
  || fail "cannot stage the mutant copy"
python3 - "$MUT/pr-review-agent.sh" <<'PY'
import sys
path = sys.argv[1]
with open(path) as fh:
    src = fh.read()
target = "    if any(is_head(sha) for sha in shas):"
if target not in src:
    sys.exit(3)
with open(path, "w") as fh:
    fh.write(src.replace(target, "    if False:  # MUTANT: head-sha exemption removed", 1))
PY
MUT_RC=$?
# A mutation that silently no-ops turns this case into decoration that always
# passes, so a missing target is fatal -- EXCEPT under an explicit historical ref,
# where the reviewer under test predates the line and legitimately does not carry
# it. That exemption is keyed on $REF and nothing else: on the working tree a
# missing target is still a hard failure.
if [ "$MUT_RC" -eq 3 ] && [ -n "$REF" ]; then
  echo "  skip: mutation target absent in $REF (the exemption postdates it); working-tree runs still enforce it"
elif [ "$MUT_RC" -ne 0 ]; then
  fail "the mutation did not apply (rc=$MUT_RC). Its target line is gone from the guard, so this
      case would report green while exercising nothing"
else
  REVIEWER_REAL="$REVIEWER"
  REVIEWER="$MUT/pr-review-agent.sh"
  run_case mutant "$W/declares-head.md" "$HEAD_SHA"
  REVIEWER="$REVIEWER_REAL"
  [ "$RC" -ne 0 ] \
    || fail "MUTATION SURVIVED: with the head-sha exemption deleted -- a guard that refuses every
      review naming any tree -- case 5 still passed. The suite cannot see the difference, so its
      green says nothing about the guard"
  ok "case 5 goes RED against a mutant with the head-sha exemption removed"
fi

# --- case 6: before/after verification is a comparison, not a conflict ---------
# Showing the pre-fix line from the merge base to prove the fix landed is ordinary
# reviewer behaviour. The first version of this guard refused it (PR #197 round 2,
# major 1): first-off-head-sha-wins, no status, no comment, PR wedged.
mkbody "$W/before-after.md" <<'EOF'
## VERDICT: APPROVE

The fix landed. Before, at the merge base:

```
git show 4a1b2c3d4e5f6071:fleet-unblock.py | sed -n 138p
```

After, at the tip under review:

```
git show @HEAD@:fleet-unblock.py | sed -n 138p
```

FINDINGS:
END FINDINGS
EOF
run_case before_after "$W/before-after.md" "$HEAD_SHA"
[ "$RC" -eq 0 ] \
  || fail "a before/after comparison was refused. Both commands open fleet-unblock.py and one of
      them opens it at the head, so the review read the tree the status names. stderr:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
status_posted "$CASE_DIR" || fail "no status posted for a before/after review"
ok "a path opened at the head AND at a base is a comparison, not a conflict"

# --- case 7: the flag window -- `git show --stat <sha>` is still a declaration --
# The first version anchored on `show[^0-9a-fA-F]{1,6}`. `--stat ` contains a, t
# and c, so it is not spannable by a non-hex window at any width: the declaration
# walked past the detector and the review posted success on an unread tree
# (PR #197 round 2, minor 3).
mkbody "$W/stat-flag.md" <<'EOF'
## VERDICT: APPROVE

GitHub was unreachable, so I used the locally available checkout.

```
git show --stat @WRONG@
git show --format=%H @WRONG@
```

FINDINGS:
END FINDINGS
EOF
run_case stat_flag "$W/stat-flag.md" "$HEAD_SHA"
[ "$RC" -ne 0 ] \
  || fail "A FLAGGED DECLARATION WALKED PAST THE DETECTOR. \`git show --stat $WRONG_TREE\` is the
      reviewer saying it opened $WRONG_TREE, and the status would have gone on ${HEAD_SHA:0:8}.
      That is the ASK-830 symptom verbatim, one flag away from the fixture's shape"
status_posted "$CASE_DIR" \
  && fail "a commit status was posted from a review whose only declared tree was $WRONG_TREE:
$(grep 'statuses/' "$CASE_DIR/gh-calls.log" | sed 's/^/        /')"
ok "\`git show --stat <sha>\` and \`--format=\` are declarations too"

# --- case 8: `git checkout <sha>` has no colon and no path --------------------
mkbody "$W/checkout.md" <<'EOF'
## VERDICT: APPROVE

```
git checkout @WRONG@
python3 -m pytest -q
```

FINDINGS:
END FINDINGS
EOF
run_case checkout "$W/checkout.md" "$HEAD_SHA"
[ "$RC" -ne 0 ] || fail "\`git checkout $WRONG_TREE\` is a whole-tree declaration and was not caught"
status_posted "$CASE_DIR" && fail "a status was posted after the review checked out $WRONG_TREE"
ok "a bare \`git checkout <sha>\` is a whole-tree declaration"

# --- case 9: one right path does not excuse another read off-head -------------
# THE TRAP. The obvious repair for case 6 is "pass if the head appears in any
# show position". It is wrong on the measured payload and this case is the pin.
# Round 2 runs `git show c87245b0:test_fleet_unblock.py` -- it fetched the TEST
# from the right tree while reading fleet-unblock.py, the file its findings are
# about, from 0880859e. Under any-match the live defect passes.
mkbody "$W/mixed.md" <<'EOF'
## VERDICT: REQUEST CHANGES

```
git show @WRONG@:fleet-unblock.py > "$tmp/fleet-unblock.py"
git show @HEAD@:test_fleet_unblock.py > "$tmp/test_fleet_unblock.py"
```

FINDINGS:
major|something about fleet-unblock.py|fleet-unblock.py:138
END FINDINGS
EOF
run_case mixed "$W/mixed.md" "$HEAD_SHA"
[ "$RC" -ne 0 ] \
  || fail "ANY-MATCH REGRESSION: the review opened test_fleet_unblock.py at the head but read
      fleet-unblock.py -- the file it reports a finding against -- from $WRONG_TREE, and it was
      allowed to post. That is PR #165 round 2's exact shape"
status_posted "$CASE_DIR" && fail "a status was posted from a mixed-tree review"
grep -q "$WRONG_TREE" "$CASE_DIR/err.txt" || fail "the refusal does not name $WRONG_TREE"
ok "a head read of one path does not excuse another path read off-head"

# --- case 10: the ASYMMETRIC before/after (PR #197 round 3, major) ------------
# The reviewer is dispatched inside a detached worktree ALREADY at the head, so
# the head side of a comparison is the working tree -- read with sed/cat, never
# with `git show <head>:path`. Case 6 only covered the symmetric form, so this
# shape (one base show + a plain read) was still refused and wedged the check.
mkbody "$W/asymmetric.md" <<'EOF'
## VERDICT: APPROVE WITH NITS

Before, at the merge base:

```
git show 4a1b2c3d4e5f6071:fleet-unblock.py | sed -n 138p
```

After, in the checkout under review:

```
sed -n '138p' fleet-unblock.py
```

FINDINGS:
END FINDINGS
EOF
run_case asymmetric "$W/asymmetric.md" "$HEAD_SHA"
[ "$RC" -eq 0 ] \
  || fail "AN ASYMMETRIC BEFORE/AFTER WAS REFUSED. The reviewer runs in a worktree at the head, so
      \`sed -n 138p fleet-unblock.py\` IS the head read; only the base side needs a sha. Refusing
      this wedges every correct comparison behind a required check. stderr:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
status_posted "$CASE_DIR" || fail "no status posted for an asymmetric before/after review"
ok "a worktree read is a head read: the asymmetric comparison posts"

# --- case 11: the symbolic ref (PR #197 round 3, major) -----------------------
mkbody "$W/symhead.md" <<'EOF'
## VERDICT: APPROVE

```
git show HEAD:fleet-unblock.py | sed -n 138p
git show 4a1b2c3d4e5f6071:fleet-unblock.py | sed -n 138p
```

FINDINGS:
END FINDINGS
EOF
run_case symhead "$W/symhead.md" "$HEAD_SHA"
[ "$RC" -eq 0 ] \
  || fail "\`git show HEAD:path\` is the same claim as naming the head sha, and the comparison was
      refused anyway. stderr:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
status_posted "$CASE_DIR" || fail "no status posted for a symbolic-HEAD comparison"
ok "\`git show HEAD:<path>\` counts as reading the head"

# --- case 12: `git -C <dir> show` (PR #197 round 3, minor 2) ------------------
# UNDER-refusal, the opposite direction from case 10: this shape was invisible to
# the detector, so the measured ASK-830 payload rewritten with -C posts a green
# required check on a tree nobody read. The fleet's own rule prefers `git -C`.
mkbody "$W/dashc.md" <<'EOF'
## VERDICT: APPROVE

GitHub was unreachable, so I used a local checkout.

```
git -C /tmp/wt show @WRONG@:fleet-unblock.py | sed -n 138p
```

FINDINGS:
major|something about fleet-unblock.py|fleet-unblock.py:138
END FINDINGS
EOF
run_case dashc "$W/dashc.md" "$HEAD_SHA"
[ "$RC" -ne 0 ] \
  || fail "\`git -C <dir> show $WRONG_TREE:<path>\` WALKED PAST THE DETECTOR. It is the ASK-830
      payload with the fleet's preferred git invocation, and it posted a green required check"
status_posted "$CASE_DIR" \
  && fail "a status was posted from a \`git -C\` review of $WRONG_TREE:
$(grep 'statuses/' "$CASE_DIR/gh-calls.log" | sed 's/^/        /')"
ok "\`git -C <dir> show <sha>:<path>\` is a declaration too"

# --- case 13: path normalization (PR #197 round 3, minor 3) -------------------
mkbody "$W/dotslash.md" <<'EOF'
## VERDICT: APPROVE

```
git show @HEAD@:./fleet-unblock.py | sed -n 138p
git show 4a1b2c3d4e5f6071:fleet-unblock.py | sed -n 138p
```

FINDINGS:
END FINDINGS
EOF
run_case dotslash "$W/dotslash.md" "$HEAD_SHA"
[ "$RC" -eq 0 ] \
  || fail "\`./fleet-unblock.py\` and \`fleet-unblock.py\` were bucketed as two paths, so a
      comparison that opened the head copy was refused. stderr:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
status_posted "$CASE_DIR" || fail "no status posted for a ./-prefixed comparison"
ok "a leading ./ does not split one path into two buckets"

# --- case 14: THE TRAP for case 10's repair -----------------------------------
# Case 10 says "a plain read of the path is a head read". The measured defect is
# written as a python-quoted git show -- `python3 -c '...["git","show",
# "0880859e:fleet-unblock.py"]...'` -- which a naive read-verb scan sees as a
# python3 command mentioning the path, i.e. as a head read. That would let PR
# #165 round 2 through the guard built to catch it. Case 1 cannot pin this: the
# real fixture ALSO carries a prose tip declaration, so it refuses either way.
# This body has no tip line, so the python-quoted show is the only signal.
#
# THE BODY FOLLOWS THE MEASURED PAYLOAD'S PUNCTUATION -- `\n` escapes, commas,
# and NO literal `;`. A `;` truncates the read window before the path and defuses
# this case into passing for the wrong reason: mutating the declaration scrub
# away left the `;` version still refusing (survived) while this version goes RED
# (killed).
#
# IT IS NOT BYTE-COPIED, and the earlier claim here that it was is corrected
# (PR #197 round 4, major 2). Round 2 writes this construct TWO ways in the same
# file -- `"git","show"` and the re-escaped `\",\"` -- and this case only ever
# carried the first. The second is case 16, because a 4-char window could not
# span it and it was the form covering the fixture's finding-bearing path.
mkbody "$W/pyquoted.md" <<'EOF'
## VERDICT: REQUEST CHANGES

```
python3 -c 'import subprocess,types,ast\nsrc=subprocess.run(["git","show","@WRONG@:fleet-unblock.py"],capture_output=True).stdout'
```

FINDINGS:
major|something about fleet-unblock.py|fleet-unblock.py:138
END FINDINGS
EOF
run_case pyquoted "$W/pyquoted.md" "$HEAD_SHA"
[ "$RC" -ne 0 ] \
  || fail "WORKTREE-READ REGRESSION: a python-quoted \`git show $WRONG_TREE:fleet-unblock.py\` was
      read as a plain python3 read of that path, so the off-head bucket was cleared and the review
      posted. That is PR #165 round 2's exact shape passing the guard written to refuse it"
status_posted "$CASE_DIR" && fail "a status was posted from a python-quoted off-head read"
ok "a python-quoted \`git show\` is a declaration, not a worktree read"

# --- case 15: the EXTRACTION trap (PR #197 round 4, major 1) ------------------
# Case 10's escape ("a plain read of the path is a head read") was a SUBSTRING
# test, and the canonical off-head idiom defeats it in one line: extract the file
# from the base tree into $tmp, then read the extraction. `"$tmp/fleet-unblock.py"`
# contains `fleet-unblock.py`, so the read cleared the bucket the extraction had
# just created and the review posted kipi/reviewer-approved on a tree it never
# opened. The redirect half is fixture line 459 verbatim, not invented.
mkbody "$W/tmpread.md" <<'EOF'
## VERDICT: APPROVE

```
review_tmp=$(mktemp -d)
git show @WRONG@:fleet-unblock.py > "$review_tmp/fleet-unblock.py"
sed -n '138p' "$review_tmp/fleet-unblock.py"
```

FINDINGS:
END FINDINGS
EOF
run_case tmpread "$W/tmpread.md" "$HEAD_SHA"
[ "$RC" -ne 0 ] \
  || fail "THE EXTRACTION TRAP IS LIVE: the review extracted fleet-unblock.py from $WRONG_TREE into
      \$tmp and then read the extraction, and that read was accepted as a head read. One \`sed\` line
      turns a refusal into an approved required check on a tree nobody opened"
status_posted "$CASE_DIR" && fail "a status was posted from a review that only read an off-head copy"
ok "reading an extracted \"\$tmp/<path>\" copy does not excuse the off-head read"

# --- case 16: the payload's OTHER quoting (PR #197 round 4, major 2) ----------
# Round 2 writes its python-quoted show twice over, and the two forms are not the
# same string: `"git","show"` puts 3 characters between the tokens, `\",\"` puts
# 5. The window was 1-4, so the second form yielded ZERO declarations -- the real
# ASK-830 shape, fed to the guard alone, posted. This body carries ONLY that form.
mkbody "$W/escquoted.md" <<'EOF'
## VERDICT: REQUEST CHANGES

```
/bin/zsh -lc 'python3 -c $'"'import subprocess,types\nsrc=subprocess.run([\"git\",\"show\",\"@WRONG@:fleet-unblock.py\"],capture_output=True,text=True,check=True).stdout'
```

FINDINGS:
major|something about fleet-unblock.py|fleet-unblock.py:138
END FINDINGS
EOF
run_case escquoted "$W/escquoted.md" "$HEAD_SHA"
[ "$RC" -ne 0 ] \
  || fail "THE RE-ESCAPED DECLARATION WALKED PAST THE DETECTOR. \`\\\",\\\"\` is 5 characters between
      \`git\` and \`show\`; a 1-4 window cannot span it, so the guard saw no declaration at all and
      approved. This is the measured ASK-830 payload's own second form"
status_posted "$CASE_DIR" && fail "a status was posted from a re-escaped off-head show"
ok "the re-escaped \`\\\",\\\"git show\` form is a declaration too"

# --- case 17: a QUOTE is not a RUN (PR #197 round 4, major 3) -----------------
# THE GUARD ATE THE REVIEW OF ITS OWN PR. The fixture is that review, verbatim:
# it critiques this change, so it cites the `git show 0880859e:...` lines the
# change adds, and the guard read the citations as commands it had run. Refused
# with no status and no comment -- which wedges the required check on every later
# round of any PR that touches these files.
#
# This case is the one that must NOT refuse, so it is the negative self-test for
# the quote rule the same way case 5 is for the head-sha exemption.
run_case quotesdiff "$FIX/pr-197-round4-quotes-the-diff.md" "$HEAD_SHA"
[ "$RC" -eq 0 ] \
  || fail "A REVIEW WAS REFUSED FOR QUOTING THE CODE UNDER REVIEW. This body is PR #197's own round-4
      review; every sha in it sits in markdown inline code inside a sentence, not at a command
      position. Refusing it means the guard wedges the required check on its own PR. stderr:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
status_posted "$CASE_DIR" || fail "no status posted for a review that only QUOTED a sha-qualified show"
ok "a sha-qualified show cited in prose is a quote, not a run"

# --- case 18: prose about a tip is not a declaration (round 4, minor) ---------
# `\btip\b` plus a sha within 4 non-word characters turned an ordinary sentence
# into a whole-tree claim -- and the whole-tree bucket is deliberately unclearable
# by a worktree read, so nothing rescued it. A review that ran no git command at
# all was refused, with no escape but break-glass-main-protection.sh.
mkbody "$W/prosetip.md" <<'EOF'
## VERDICT: APPROVE

Baseline for the comparison below is main's tip (`85f556dc6e0f2c9e0c4b7a1d3f5e8a2b9c6d4e11`),
which is where the regression was introduced.

```
$ sed -n '138p' fleet-unblock.py
```

FINDINGS:
END FINDINGS
EOF
run_case prosetip "$W/prosetip.md" "$HEAD_SHA"
[ "$RC" -eq 0 ] \
  || fail "A REVIEW THAT RAN NO GIT COMMAND WAS REFUSED. Naming a baseline's tip in a sentence is
      prose, not a declaration that a tree was opened. stderr:
$(sed 's/^/        /' "$CASE_DIR/err.txt")"
status_posted "$CASE_DIR" || fail "no status posted for a review whose only sha was prose about a tip"
ok "prose naming a tip is not a whole-tree declaration"


# --- case 19: a path OUTSIDE the diff is a citation, not a finding ------------
# PR #197 round 5, major 2. The reviewer quoted `git show 0880859e:fleet-unblock.py`
# out of the fixtures this PR ships and was refused, with the wedge becoming
# permanent at merge. fleet-unblock.py is not a file PR #197 changes, so no
# finding can be about it. Measured on 111 real review bodies: this is what
# turned pr197-c1 and pr197-c5 from refusals into posts.
cat > "$W/outside.md" <<EOF
## Verdict: REQUEST CHANGES

The fixture this PR adds contains the defect's own command:

\`\`\`
git show ${WRONG_TREE}:fleet-unblock.py
\`\`\`

FINDINGS:
major|the guard eats its own PR|q-system/.q-system/scripts/pr-review-agent.sh:1
END FINDINGS
EOF
printf '%s\n' "q-system/.q-system/scripts/pr-review-agent.sh" > "$W/changed-outside.txt"
CHANGED_LIST="$W/changed-outside.txt" run_case outside "$W/outside.md" "$HEAD_SHA"
CHANGED_LIST=""
[ "$RC" -eq 0 ] \
  || fail "THE GUARD STILL EATS ITS OWN PR: a review quoting a path the PR does not
      change (fleet-unblock.py) was refused. At merge the fixtures ship that string, so
      every future review of this guard wedges the required check. rc=$RC"
ok "a path the PR never changed is a citation, not a finding"
status_posted "$CASE_DIR" \
  || fail "case 19 exited 0 but posted no status"
ok "and its status is posted"

# --- case 20: the negative self-test for case 19 ------------------------------
# THE SAME BODY, with fleet-unblock.py IN the changed set, must still refuse.
# Without this, case 19 would pass just as well if the exemption were a blanket
# "never refuse" -- which is exactly how a guard goes silently off.
printf '%s\n' "fleet-unblock.py" > "$W/changed-inside.txt"
CHANGED_LIST="$W/changed-inside.txt" run_case inside "$W/outside.md" "$HEAD_SHA"
CHANGED_LIST=""
[ "$RC" -ne 0 ] \
  || fail "THE EXEMPTION IS A BLANKET PASS: the same body was accepted with
      fleet-unblock.py IN the PR's changed set, where the off-head read really could
      carry a finding. Case 19 proves nothing if this posts."
status_posted "$CASE_DIR" \
  && fail "case 20 refused but posted a status anyway"
ok "the same body still refuses when the PR does change that path"

# --- case 21: a malformed changed-file list must not exempt anything ----------
# Caught by case 1 going red mid-round-5: a `gh` that answers anything other than
# a path list produced a NON-EMPTY set containing none of the review's paths,
# which reads as "every path is outside the diff" and exempts everything. The
# guard looked healthy and was off.
printf '%s\n' '{"errors":[{"message":"not found"}]}' > "$W/changed-junk.txt"
CHANGED_LIST="$W/changed-junk.txt" run_case junklist "$WRONG_FIX" "$HEAD_SHA"
CHANGED_LIST=""
[ "$RC" -ne 0 ] \
  || fail "SILENT-OFF: a malformed changed-file list exempted every path and the
      live defect fixture posted. Unknown must mean no exemption, never a free pass."
ok "a malformed changed-file list means unknown, not a free pass"

# --- case 22: the head read codex actually writes ------------------------------
# PR #197 round 5, major 1. Every codex command is `/bin/zsh -lc "<cmd>"`, so the
# read verb sits after a quote. That was not a command start, so the head-side
# read was invisible and one `git show <base>:...` refused a correct before/after
# review. Measured: this is the shape that refused pr188-c1 against every
# candidate head of its own PR.
cat > "$W/zshlc.md" <<EOF
## Verdict: APPROVE

I read the head side:

\`\`\`
/bin/zsh -lc "sed -n '1,40p' fleet-unblock.py"
\`\`\`

and the base side to compare:

\`\`\`
git show ${WRONG_TREE}:fleet-unblock.py
\`\`\`

FINDINGS:
END FINDINGS
EOF
printf '%s\n' "fleet-unblock.py" > "$W/changed-zshlc.txt"
CHANGED_LIST="$W/changed-zshlc.txt" run_case zshlc "$W/zshlc.md" "$HEAD_SHA"
CHANGED_LIST=""
[ "$RC" -eq 0 ] \
  || fail "A CORRECT BEFORE/AFTER REVIEW IS REFUSED: the head-side read is written
      /bin/zsh -lc \"sed ...\", which is how codex writes every command. rc=$RC"
ok "a read after \`-lc \"\` is a head read (the shape codex actually emits)"

# --- case 23: the declaration regex may not backtrack exponentially -----------
# PR #197 round 5, minor 1. `git show --a=` + `-b`*n doubled per segment (1.9s at
# 22) because a `-b` could be eaten by the flag body OR by another turn of the
# outer loop. There is no portable `timeout` binary on this fleet's runners, so
# the cure is the regex, and this is its clock.
DET="$W/detector.py"
awk "/<<'ANALYSED_TREE_PY'/{f=1;next} /^ANALYSED_TREE_PY/{f=0} f" "$REVIEWER" > "$DET"
python3 - "$DET" <<'PYEOF' || fail "the DECLARATION regex still backtracks: a 40-segment
      flag run did not finish in 5s. A review body can hang the unattended job."
import subprocess, sys, tempfile, time, os
det = sys.argv[1]
body = "git show --a=" + "-b" * 40 + "!"
with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
    fh.write(body); p = fh.name
start = time.time()
subprocess.run([sys.executable, det, p, "c87245b0", ""], capture_output=True, timeout=60)
os.unlink(p)
sys.exit(0 if time.time() - start < 5 else 1)
PYEOF
ok "a 40-segment flag run is linear, not exponential"

echo "PASS ($PASS checks)"
