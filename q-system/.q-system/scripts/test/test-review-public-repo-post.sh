#!/usr/bin/env bash
# ASK-2893: on a PUBLIC repo, `pr-review-agent.sh --post` must set the commit
# status and post at most a counts-only summary. Never the review text, never a
# finding's text, never the diff. Private repos keep the full rendered review.
#
# THE DEFECT. The --post path rendered the whole review into a PR comment, and a
# claude or codex review replays the diff it read. On public assafkip/kipi-system
# that put 188 term-carrying comments on public PRs (scan of 2026-10-22, up to
# 55 KB each). A scrub PR leaked the very terms it removed: they are in its diff.
#
# WHAT EACH CASE PROVES
#   0  negative self-tests: the fake gh really captures a posted body, and the
#      guard really finds the synthetic term under the fixture HOME. Without
#      them every "the term is absent" assertion below could pass on a broken
#      capture or an empty term list.
#   1  public repo, review and diff carry the term: summary only, status set.
#   2  the visibility lookup FAILS: treated as public (fail closed).
#   3  public repo whose slug collides with a term: the guard catches the path in
#      the summary and the post drops to the counts-only line.
#   4  public repo, approving review: status success, so a gate can go green
#      without any review text on the PR (the PR #551 shape).
#   5  private repo: the posted body is byte-identical to review_comment_body,
#      i.e. today's behaviour, diff and all.
#   6  round 2 on a public repo: the earlier round's findings reach the reviewer
#      from disk, since they are no longer in the PR comments. Round 2 on a
#      private repo gets no such section (unchanged).
#   7  the counts-only floor still says DEGRADED on an Opus-fallback run.
#   8  round 2 after an unusable round 1: no earlier-rounds header over nothing.
#   9  a major the reviewer marked nonblocking is named as such in the summary.
#
# Isolation: HOME, KIPI_STATE_DIR, the git repo, `gh`, the engines and the term
# list are all fixtures under a mktemp dir. No live PR is read, no model runs,
# nothing is posted anywhere real. The term is synthetic.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SRC_DIR="$ROOT/q-system/.q-system/scripts"

PASS=0; BAD=0
fail() { echo "FAIL: $1" >&2; exit 1; }   # fixture broken: nothing below means anything
bad()  { BAD=$((BAD + 1)); echo "  BAD: $1" >&2; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$SRC_DIR/pr-review-agent.sh" ] || fail "pr-review-agent.sh missing at $SRC_DIR"
[ -f "$SRC_DIR/client-name-guard.py" ] || fail "client-name-guard.py missing at $SRC_DIR"
REAL_GIT="$(command -v git)" || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_TARGET_REPO KIPI_REVIEW_ENGINE PRIVATE_TERMS GH_REPO 2>/dev/null || true

TERM_X="zorblaxquux"   # synthetic private term; never a real one
G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB"

mkdir -p "$WORK/skel/q-system/.q-system/scripts"
git init -q "$WORK/skel"
echo "code" > "$WORK/skel/FILE.txt"
cp "$SRC_DIR/pr-review-agent.sh" "$SRC_DIR/pr-verdict-lib.sh" "$SRC_DIR/repo-slug-lib.sh" \
   "$SRC_DIR/env-failure-lib.sh" "$SRC_DIR/reviewer-token-lib.sh" "$SRC_DIR/client-name-guard.py" \
   "$WORK/skel/q-system/.q-system/scripts/"
G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "control code"
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "https://github.com/assafkip/homerepo.git"
AGENT="$WORK/skel/q-system/.q-system/scripts/pr-review-agent.sh"
SHA="$(git -C "$WORK/skel" rev-parse HEAD)"

# --- fake gh -----------------------------------------------------------------
# Visibility is read from a file per call, so one stub serves every case.
# Every `pr comment` body is captured verbatim, whichever flag carried it.
GH_LOG="$WORK/gh-calls.txt"; : > "$GH_LOG"
POSTED="$WORK/posted"; mkdir -p "$POSTED"
echo PUBLIC > "$WORK/visibility"
cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$GH_LOG"
case "\$*" in
  *"repo view"*)
    v="\$(cat "$WORK/visibility")"
    [ "\$v" = FAIL ] && { echo "error connecting to api.github.com" >&2; exit 1; }
    echo "\$v"; exit 0 ;;
  *"pr view"*"headRefOid"*) printf '%s\t%s\n' "$SHA" "a PR title" ;;
  *"pr view"*"--comments"*) echo "EARLIER-ROUND-COMMENT-MARKER" ;;
  *"pr view"*)              echo "title: a PR title" ;;
  *"pr diff"*)              printf 'diff --git a/FILE.txt b/FILE.txt\n+$TERM_X onboarding notes\n' ;;
  *"pr comment"*)
    n=\$(( \$(ls "$POSTED" | wc -l) + 1 )); prev=""
    for a in "\$@"; do
      case "\$prev" in
        --body-file) cat "\$a" > "$POSTED/\$n.txt" ;;
        --body|-b)   printf '%s' "\$a" > "$POSTED/\$n.txt" ;;
      esac
      prev="\$a"
    done
    echo "https://github.com/assafkip/homerepo/pull/1#issuecomment-\$n" ;;
  *"api"*)                  echo '{}' ;;
esac
exit 0
EOF
chmod +x "$STUB/gh"

# --- fake engine ---------------------------------------------------------------
# Prints whatever review the case put in review.txt, and keeps a copy of the
# earlier-rounds file the prompt points at, so case 6 can read what it was given.
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
for a in "\$@"; do
  p="\$(printf '%s' "\$a" | grep -oE '/[^ ]*comments\.txt' | head -1)"
  [ -n "\$p" ] && [ -f "\$p" ] && cp "\$p" "$WORK/ctx-comments.txt"
done
cat "$WORK/review.txt"
exit 0
EOF
chmod +x "$STUB/claude"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/codex"; chmod +x "$STUB/codex"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub"

REVIEW_TERM="$WORK/review-term.txt"
cat > "$REVIEW_TERM" <<EOF
I read the diff:
diff --git a/FILE.txt b/FILE.txt
+$TERM_X onboarding notes
VERDICT: REQUEST CHANGES
FINDINGS:
major|the $TERM_X loader swallows errors|FILE.txt:1
minor|rename the $TERM_X helper|FILE.txt:2
END FINDINGS
EOF
REVIEW_OK="$WORK/review-ok.txt"
cat > "$REVIEW_OK" <<'EOF'
I read the diff and found nothing.
VERDICT: APPROVE
FINDINGS:
END FINDINGS
EOF

mkhome() {  # mkhome <tag>: a HOME whose term list holds only the synthetic term
  mkdir -p "$WORK/home-$1/.config/kipi"
  printf '%s\n' "$TERM_X" > "$WORK/home-$1/.config/kipi/client-tokens"
}

run_post() {  # run_post <tag> <visibility> <review-file>
  local tag="$1"; echo "$2" > "$WORK/visibility"; cp "$3" "$WORK/review.txt"
  [ -d "$WORK/home-$tag" ] || mkhome "$tag"
  rm -f "$POSTED"/*.txt "$WORK/ctx-comments.txt"; : > "$GH_LOG"
  ( cd "$WORK/skel" \
    && HOME="$WORK/home-$tag" KIPI_STATE_DIR="$WORK/state-$tag" KIPI_NOTIFY="/usr/bin/true" \
       KIPI_REVIEW_SCRATCH_BASE="$WORK/scratch-$tag" \
       bash "$AGENT" 1 --engine claude --post ) >"$WORK/run-$tag.out" 2>&1
}

body_of() { cat "$POSTED"/*.txt 2>/dev/null; }
n_posted() { ls "$POSTED" | grep -c '\.txt$'; }
status_line() { grep -E "api -X POST repos/[^ ]*/statuses/$SHA" "$GH_LOG" | tail -1; }

# Shared assertions for every public case: no diff, no term, no finding text,
# and the gate still moved.
assert_public_safe() {  # assert_public_safe <case-label> <expected-state>
  local label="$1" want="$2" body st
  body="$(body_of)"
  [ "$(n_posted)" -le 1 ] && ok "$label: at most one comment posted ($(n_posted))" \
    || bad "$label: $(n_posted) comments posted"
  if [ -n "$body" ]; then
    case "$body" in *"diff --git"*|*"+$TERM_X"*) bad "$label: THE DEFECT: the posted body carries the diff" ;;
      *) ok "$label: no diff in the posted body" ;; esac
    if printf '%s' "$body" | grep -qi "$TERM_X"; then
      bad "$label: THE DEFECT: the posted body carries the private term"
    else ok "$label: no private term in the posted body"; fi
    if printf '%s' "$body" | grep -qE 'swallows errors|rename the|I read the diff'; then
      bad "$label: THE DEFECT: the posted body carries review or finding text"
    else ok "$label: no review or finding text in the posted body"; fi
    [ "$(printf '%s' "$body" | wc -c | tr -d ' ')" -lt 600 ] \
      && ok "$label: the body is short ($(printf '%s' "$body" | wc -c | tr -d ' ') bytes)" \
      || bad "$label: the body is $(printf '%s' "$body" | wc -c | tr -d ' ') bytes, not a summary"
  fi
  st="$(status_line)"
  case "$st" in
    *"context=kipi/reviewer-approved"*"state=$want"*|*"state=$want"*"context=kipi/reviewer-approved"*)
      ok "$label: commit status still set (kipi/reviewer-approved=$want)" ;;
    *) bad "$label: no kipi/reviewer-approved=$want status was posted. gh log:
$(sed 's/^/        /' "$GH_LOG" | grep -v 'pr view\|pr diff' | head -8)" ;;
  esac
}

# ===========================================================================
echo "== 0. negative self-tests =="
printf 'marker-body' > "$WORK/probe.txt"
( cd "$WORK/skel" && gh pr comment 1 --body-file "$WORK/probe.txt" >/dev/null )
[ "$(body_of)" = "marker-body" ] || fail "the fake gh did not capture a --body-file body"
rm -f "$POSTED"/*.txt
( cd "$WORK/skel" && gh pr comment 1 --body "marker-two" >/dev/null )
[ "$(body_of)" = "marker-two" ] || fail "the fake gh did not capture a --body body"
rm -f "$POSTED"/*.txt
ok "the fake gh captures a posted body from either flag"

mkhome probe
GUARD_PROBE='
import importlib.util, sys
s = importlib.util.spec_from_file_location("g", sys.argv[1]); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
t = m.load_terms(warn=lambda _m: None) if hasattr(m, "load_terms") else m.load_tokens()
sys.exit(1 if t and m.hits(sys.stdin.read(), t) else 0)'
printf 'x %s y' "$TERM_X" | HOME="$WORK/home-probe" python3 -I -c "$GUARD_PROBE" "$SRC_DIR/client-name-guard.py"
[ $? = 1 ] || fail "the guard does not find the synthetic term under the fixture HOME; the term assertions would be vacuous"
printf 'nothing private here' | HOME="$WORK/home-probe" python3 -I -c "$GUARD_PROBE" "$SRC_DIR/client-name-guard.py"
[ $? = 0 ] || fail "the guard flags clean text under the fixture HOME"
ok "the guard finds the synthetic term and passes clean text"

# ===========================================================================
echo "== 1. public repo, the review and the diff carry the term =="
run_post pub PUBLIC "$REVIEW_TERM"
grep -q '^  verdict: ' "$WORK/run-pub.out" || fail "case 1 never reached a verdict:
$(tail -20 "$WORK/run-pub.out")"
assert_public_safe "case 1" failure
B1="$(body_of)"
case "$B1" in *"Verdict: REQUEST CHANGES"*) ok "case 1: the verdict is in the summary" ;;
  *) bad "case 1: the summary does not state the verdict" ;; esac
case "$B1" in *"Findings: 2"*) ok "case 1: the finding count is in the summary" ;;
  *) bad "case 1: the summary does not carry the finding count (2)" ;; esac
case "$B1" in *"pr-reviews/"*".md"*) ok "case 1: the summary names the review file on the reviewer machine" ;;
  *) bad "case 1: the summary does not name the review file" ;; esac

# ===========================================================================
echo "== 2. the visibility lookup fails: fail closed =="
run_post fail FAIL "$REVIEW_TERM"
grep -q 'repo view' "$GH_LOG" && ok "case 2: the reviewer asked GitHub for the visibility" \
  || bad "case 2: the reviewer never asked GitHub for the repo visibility"
assert_public_safe "case 2" failure

# ===========================================================================
echo "== 3. public repo whose slug collides with a term: counts-only line =="
git -C "$WORK/skel" remote set-url origin "https://github.com/assafkip/$TERM_X.git"
run_post slug PUBLIC "$REVIEW_TERM"
git -C "$WORK/skel" remote set-url origin "https://github.com/assafkip/homerepo.git"
assert_public_safe "case 3" failure
B3="$(body_of)"
[ "$B3" = "Verdict: REQUEST CHANGES. Findings: 2. Review withheld: this repository is public." ] \
  && ok "case 3: the guard hit dropped the post to the counts-only line" \
  || bad "case 3: expected the counts-only line, got: $(printf '%s' "$B3" | head -c 200 | sed "s/$TERM_X/<term>/g")"

# ===========================================================================
echo "== 4. public repo, approving review: the gate goes green with no review text =="
run_post okpub PUBLIC "$REVIEW_OK"
assert_public_safe "case 4" success
case "$(body_of)" in *"Verdict: APPROVE"*"Findings: 0"*) ok "case 4: summary says APPROVE with 0 findings" ;;
  *) bad "case 4: summary does not say APPROVE / Findings: 0" ;; esac

# ===========================================================================
echo "== 5. private repo: today's behaviour, byte for byte =="
run_post priv PRIVATE "$REVIEW_TERM"
REV5="$(ls -t "$WORK/home-priv/.config/kipi/pr-reviews/"*.md 2>/dev/null | head -1)"
[ -n "$REV5" ] || fail "case 5: no review file was written:
$(tail -20 "$WORK/run-priv.out")"
EXPECT5="$( . "$SRC_DIR/pr-verdict-lib.sh"; review_comment_body "$REV5" "REQUEST CHANGES" claude 0 )"
[ "$(n_posted)" = 1 ] && ok "case 5: one comment posted" || bad "case 5: $(n_posted) comments posted"
[ "$(body_of)" = "$EXPECT5" ] \
  && ok "case 5: the posted body is byte-identical to review_comment_body (unchanged)" \
  || bad "case 5: the private-repo body differs from review_comment_body"
case "$(body_of)" in *"diff --git"*) ok "case 5: the private comment still carries the full review" ;;
  *) bad "case 5: the private comment lost the review narrative" ;; esac
case "$(status_line)" in *"context=kipi/reviewer-approved"*) ok "case 5: commit status set" ;;
  *) bad "case 5: no commit status" ;; esac

# ===========================================================================
echo "== 6. round 2: earlier findings reach the reviewer from disk on a public repo =="
run_post pub PUBLIC "$REVIEW_TERM"      # same HOME as case 1, so round 1 is on disk
grep -q 'round: 2' "$WORK/run-pub.out" || fail "case 6 is not a round-2 run:
$(grep 'round' "$WORK/run-pub.out" | head -3)"
if [ -f "$WORK/ctx-comments.txt" ] && grep -q "^major|the $TERM_X loader swallows errors|FILE.txt:1" "$WORK/ctx-comments.txt"; then
  ok "case 6: the round-1 findings are in the file the round-2 prompt points at"
else
  bad "case 6: the round-2 reviewer was not given the round-1 findings"
fi
assert_public_safe "case 6" failure
run_post priv PRIVATE "$REVIEW_TERM"    # same HOME as case 5
grep -q 'round: 2' "$WORK/run-priv.out" || fail "case 6b is not a round-2 run"
# Both halves (PR #557 round 2, minor): the PR comments DO arrive, and nothing
# else is appended. The marker comes from the fake gh's `--comments` answer.
if [ -f "$WORK/ctx-comments.txt" ] && grep -q 'EARLIER-ROUND-COMMENT-MARKER' "$WORK/ctx-comments.txt" \
   && ! grep -q 'Earlier rounds of this review' "$WORK/ctx-comments.txt"; then
  ok "case 6b: a private round 2 gets the PR comments, and only them (unchanged)"
else
  bad "case 6b: the private round-2 context lost the PR comments or gained a section"
fi

# ===========================================================================
echo "== 7. the counts-only floor keeps the DEGRADED words (PR #557 round 1) =="
L7="$( . "$SRC_DIR/pr-verdict-lib.sh"; review_public_counts_line "$REVIEW_TERM" "APPROVE" 1 )"
case "$L7" in DEGRADED*"Verdict: APPROVE. Findings: 2."*) ok "case 7: a degraded counts-only line says DEGRADED" ;;
  *) bad "case 7: the degraded counts-only line does not say DEGRADED" ;; esac
L7B="$( . "$SRC_DIR/pr-verdict-lib.sh"; review_public_counts_line "$REVIEW_TERM" "APPROVE" 0 )"
case "$L7B" in DEGRADED*) bad "case 7: a normal counts-only line claims DEGRADED" ;;
  *) ok "case 7: a normal counts-only line does not say DEGRADED" ;; esac

# ===========================================================================
echo "== 8. round 2 after an UNUSABLE round 1: no empty earlier-rounds header (PR #557 round 1) =="
REVIEW_CUT="$WORK/review-cut.txt"
printf 'VERDICT: APPROVE\nFINDINGS:\nmajor|cut off mid|FILE.txt:1\n' > "$REVIEW_CUT"
run_post cut PUBLIC "$REVIEW_CUT"       # round 1: truncated block, unusable, verdict UNSTATED
assert_public_safe "case 8 round 1" failure
case "$(body_of)" in *"Verdict: unstated"*"Findings: not parsed"*) ok "case 8: an unusable round says unstated / not parsed" ;;
  *) bad "case 8: an unusable round's summary does not say unstated / not parsed" ;; esac
run_post cut PUBLIC "$REVIEW_OK"        # round 2 on the same HOME
grep -q 'round: 2' "$WORK/run-cut.out" || fail "case 8 is not a round-2 run:
$(grep 'round' "$WORK/run-cut.out" | head -3)"
if [ -f "$WORK/ctx-comments.txt" ] && ! grep -q 'Earlier rounds of this review' "$WORK/ctx-comments.txt"; then
  ok "case 8: no earlier-rounds header when no earlier round is usable"
else
  bad "case 8: the round-2 context carries an earlier-rounds header over no usable round"
fi

# ===========================================================================
echo "== 9. a nonblocking major is named as such in the summary (PR #557 round 2) =="
REVIEW_NB="$WORK/review-nb.txt"
printf 'VERDICT: APPROVE WITH NITS\nFINDINGS:\nmajor|safe to fix after merge|FILE.txt:1|nonblocking\nminor|a nit|FILE.txt:2\nEND FINDINGS\n' > "$REVIEW_NB"
B9="$( HOME="$WORK/home-probe"; . "$SRC_DIR/pr-verdict-lib.sh"
       review_public_body "$REVIEW_NB" "APPROVE WITH NITS" claude 0 "$SRC_DIR/client-name-guard.py" 2>/dev/null )"
case "$B9" in *"major 1, 1 of them marked nonblocking by the reviewer"*) ok "case 9: the released major is named nonblocking" ;;
  *) bad "case 9: the summary does not say the major is nonblocking" ;; esac
case "$B9" in *"safe to fix"*|*"a nit"*) bad "case 9: finding text leaked into the summary" ;;
  *) ok "case 9: no finding text in the summary" ;; esac

echo
if [ "$BAD" -gt 0 ]; then
  echo "test-review-public-repo-post: $BAD BAD, $PASS ok"
  exit 1
fi
echo "test-review-public-repo-post: all $PASS checks passed"
