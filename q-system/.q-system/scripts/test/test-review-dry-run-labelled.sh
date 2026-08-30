#!/usr/bin/env bash
# ASK-758: a dry run must SAY it is a dry run, at the moment a reader forms a
# belief about the verdict.
#
# THE DEFECT. pr-review-agent.sh defaults to POST=0. Every side effect -- the PR
# comment, the `kipi/reviewer-approved` commit status, the Linear post -- lives
# inside `if [ "$POST" = "1" ]`. The verdict line and the closing `done` line
# live OUTSIDE it and print unconditionally. So a default invocation runs the
# whole reviewer, prints `verdict: APPROVE`, prints `done`, exits 0, and has
# moved no gate and written nothing any human or required check can see. The
# transcript of a dry run and the transcript of a real approving run are the
# same text; the difference is only discoverable by going and proving that zero
# commit statuses exist.
#
# NOT A CLAIM ABOUT THE FLAG. POST=0 as a default is right -- a reviewer that
# comments on a live PR every time anyone invokes it is worse. The bug is that
# the run does not say which mode it was in.
#
# WHY THIS TEST ASSERTS BOTH DIRECTIONS. A test that only checks "a no-post run
# says DRY RUN" is passed by a script that stamps DRY RUN on every run,
# including the ones that really did move the gate -- which is the same defect
# pointed the other way, and worse, because it would train a reader to ignore
# the marker. So the --post half is a required positive control, and it is only
# non-vacuous if that run really did post: case 2 asserts the commit status
# landed, not merely that the marker is absent.
#
# Isolation: HOME, KIPI_STATE_DIR, the git repo, `gh` and the engine are all
# fixtures under a mktemp dir. No live PR is read, no model is spent, no commit
# status is posted anywhere real.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SRC_DIR="$ROOT/q-system/.q-system/scripts"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

# The marker the fix must carry. Asserted as a substring, not a byte-exact line,
# so rewording the sentence around it does not turn this red for no reason.
MARKER="DRY RUN"

[ -f "$SRC_DIR/pr-review-agent.sh" ] || fail "pr-review-agent.sh missing at $SRC_DIR"
REAL_GIT="$(command -v git)" || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_TARGET_REPO KIPI_REVIEW_ENGINE 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB"

# --- the repo under review, with the control code 3 levels down -------------
# The script's own root guard refuses unless it lives at
# <repo>/q-system/.q-system/scripts/, so the copy has to sit there. It is a `cp`
# of the shipping file: this exercises the real script, not a rewrite of it.
mkdir -p "$WORK/skel/q-system/.q-system/scripts"
git init -q "$WORK/skel"
echo "code" > "$WORK/skel/FILE.txt"
cp "$SRC_DIR/pr-review-agent.sh" "$SRC_DIR/pr-verdict-lib.sh" "$SRC_DIR/repo-slug-lib.sh" \
   "$WORK/skel/q-system/.q-system/scripts/"
G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "control code"
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "https://github.com/assafkip/homerepo.git"
AGENT="$WORK/skel/q-system/.q-system/scripts/pr-review-agent.sh"
SHA="$(git -C "$WORK/skel" rev-parse HEAD)"

# --- fake gh: logs every call, so "did a status get posted" is observable ----
GH_LOG="$WORK/gh-calls.txt"; : > "$GH_LOG"
cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$GH_LOG"
case "\$*" in
  *"pr view"*"headRefOid"*) printf '%s\t%s\n' "$SHA" "a PR title" ;;
  *"pr diff"*)              echo "diff --git a/FILE.txt b/FILE.txt" ;;
  *"pr comment"*)           echo "https://github.com/assafkip/homerepo/pull/1#issuecomment-1" ;;
  *"api"*)                  echo '{}' ;;
esac
exit 0
EOF
chmod +x "$STUB/gh"

# --- fake engine: a REAL-SHAPED review that derives an approving verdict -----
# One nit row, so the severity ladder derives APPROVE WITH NITS -- the shape
# post_reviewer_status maps to state=success. A run that approves is the only
# run where the missing mode label actually costs something, so that is the run
# under test.
cat > "$STUB/codex" <<'EOF'
#!/usr/bin/env bash
cat <<'REVIEW'
VERDICT: APPROVE
FINDINGS:
severity|file|line|what
nit|FILE.txt|1|trailing whitespace
END FINDINGS
REVIEW
exit 0
EOF
chmod +x "$STUB/codex"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/claude"; chmod +x "$STUB/claude"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub"

run_reviewer() {  # run_reviewer <out-file> <home-suffix> [extra args...]
  local out="$1" tag="$2"; shift 2
  ( cd "$WORK/skel" \
    && HOME="$WORK/home-$tag" KIPI_STATE_DIR="$WORK/state-$tag" KIPI_NOTIFY="/usr/bin/true" \
       bash "$AGENT" 1 --engine codex "$@" ) >"$out" 2>&1
  return $?
}

# ===========================================================================
# CASE 0 -- NEGATIVE SELF-TEST: the fake gh really does record a status POST.
# Without this, case 1's "no status was posted" assertion could be passing
# because the log is broken rather than because nothing was posted.
# ===========================================================================
( cd "$WORK/skel" && gh api -X POST "repos/assafkip/homerepo/statuses/$SHA" -f state=success >/dev/null 2>&1 )
grep -q "statuses/$SHA" "$GH_LOG" \
  || fail "negative self-test: a real status POST was not recorded in the gh log; every absence assertion below would be vacuous"
ok "negative self-test: the gh log records a statuses POST when one happens"
: > "$GH_LOG"

# ===========================================================================
# CASE 1 -- the reproducer: default (no --post) invocation
# ===========================================================================
run_reviewer "$WORK/dry.out" dry
RC_DRY=$?

VERDICT_LINE="$(grep -m1 '^  verdict: ' "$WORK/dry.out" || true)"
DONE_LINE="$(grep -m1 ' done' "$WORK/dry.out" | tail -1 || true)"
STATUS_CALLS="$(grep -c "statuses/" "$GH_LOG" || true)"

echo "  [ctx] no-post run rc=$RC_DRY"
echo "  [ctx] verdict line: ${VERDICT_LINE:-<none>}"
echo "  [ctx] closing line: ${DONE_LINE:-<none>}"
echo "  [ctx] commit statuses posted: $STATUS_CALLS"

# The preconditions. If these go red the run never reached the verdict at all
# and every assertion under them would be testing nothing.
[ -n "$VERDICT_LINE" ] \
  || fail "the no-post run printed no verdict line; it never reached the code under test:
$(tail -25 "$WORK/dry.out")"
case "$VERDICT_LINE" in
  *APPROVE*) ok "precondition: the no-post run reached an APPROVING verdict" ;;
  *) fail "the fixture no longer derives an approving verdict (got '$VERDICT_LINE'); the defect is only costly on an approving run" ;;
esac

# THE DEFECT ITSELF: an approving verdict, and nothing posted outward. Scoped
# deliberately to the OUTWARD surfaces -- case 3 measures the verdict record,
# which a no-post run does write, so "no gate moved" would be false here.
[ "$STATUS_CALLS" = "0" ] \
  || fail "the no-post run posted a commit status; POST=0 is supposed to post nothing:
$(sed 's/^/        /' "$GH_LOG")"
ok "the no-post run posted nothing outward (0 commit statuses)"

# ...so the transcript MUST say so. This is the assertion that was red before
# the fix: the run said APPROVE and said nothing about having done nothing.
case "$VERDICT_LINE" in
  *"$MARKER"*) ok "the no-post verdict line is labelled '$MARKER'" ;;
  *) fail "SILENT DRY RUN at pr-review-agent.sh -- the run printed an approving verdict and posted NOTHING (0 commit statuses, no PR comment), but its verdict line is indistinguishable from a real approving review:
      $VERDICT_LINE
      A reader forms a belief about this PR here, and the transcript gives them no way to know the gate never moved." ;;
esac

case "$DONE_LINE" in
  *"$MARKER"*) ok "the no-post closing line is labelled '$MARKER'" ;;
  *) fail "the run's closing line carries no '$MARKER' marker: '${DONE_LINE:-<none>}'. A reader who skims to the last line still sees a clean finish." ;;
esac

# Exit code stays 0. This is a REPORTING defect; a non-zero exit would break
# every caller that legitimately surveys without posting.
[ "$RC_DRY" = "0" ] \
  || fail "the no-post run exited $RC_DRY; a dry run must still exit 0 (callers survey with it)"
ok "the no-post run still exits 0"

# ===========================================================================
# CASE 2 -- POSITIVE CONTROL: a --post run must NOT be labelled, and must
# really have posted. Without the second half, "label everything dry" and
# "label nothing" are both caught, but "post nothing and label nothing" would
# still slip through as a passing --post case.
# ===========================================================================
: > "$GH_LOG"
run_reviewer "$WORK/post.out" post --post
RC_POST=$?

POST_VERDICT="$(grep -m1 '^  verdict: ' "$WORK/post.out" || true)"
POST_DONE="$(grep -m1 ' done' "$WORK/post.out" | tail -1 || true)"
POST_STATUS_CALLS="$(grep -c "statuses/" "$GH_LOG" || true)"

echo "  [ctx] --post run rc=$RC_POST"
echo "  [ctx] verdict line: ${POST_VERDICT:-<none>}"
echo "  [ctx] commit statuses posted: $POST_STATUS_CALLS"

[ -n "$POST_VERDICT" ] \
  || fail "the --post run printed no verdict line:
$(tail -25 "$WORK/post.out")"

# The half that makes this control non-vacuous: the run really did move a gate.
[ "$POST_STATUS_CALLS" -ge 1 ] \
  || fail "the --post run posted NO commit status, so 'the marker is absent' proves nothing here:
$(sed 's/^/        /' "$GH_LOG")"
ok "the --post run really did post a commit status ($POST_STATUS_CALLS)"

case "$POST_VERDICT" in
  *"$MARKER"*) fail "the --post run's verdict line is labelled '$MARKER' even though it posted a commit status:
      $POST_VERDICT
      A marker that appears on every run tells a reader nothing and trains them to ignore it." ;;
  *) ok "the --post verdict line carries no dry-run marker" ;;
esac

case "$POST_DONE" in
  *"$MARKER"*) fail "the --post run's closing line is labelled '$MARKER': '$POST_DONE'" ;;
  *) ok "the --post closing line carries no dry-run marker" ;;
esac

# ===========================================================================
# CASE 3 -- THE LABEL MUST MATCH WHAT THE RUN ACTUALLY DID (ASK-758 round 2).
#
# The first version of the marker read "nothing posted, no gate moved". The
# second half was false. The verdict record `pr-<N>.verdict.json` is written at
# pr-review-agent.sh:876, and the `if [ "$POST" = "1" ]` guard does not open
# until :974 -- so the record is written on EVERY run, dry ones included. That
# record is exactly what the loop gates on: converge.sh:748 and
# linear-worker.sh:1054 both read it to decide whether a PR is approved or goes
# to rework. A dry run therefore moves the one gate that matters most, while the
# marker told the reader no gate had moved. A marker that is trusted and wrong
# is worse than no marker: it is the same silent-dry-run defect aimed at the
# reader who DID read the label.
#
# SO THIS CASE MEASURES FIRST AND ASSERTS AGAINST THE MEASUREMENT, rather than
# pinning one sentence. If the record write ever moves inside the POST guard,
# the else-branch turns red and forces the label to be corrected in the other
# direction too. The claim is coupled to the behaviour, not to a string.
# ===========================================================================

# Negative self-test for the finder itself. Without it, "0 records found" below
# could mean the find expression is broken rather than that nothing was written.
EMPTY_DIR="$WORK/no-records"; mkdir -p "$EMPTY_DIR"
[ "$(find "$EMPTY_DIR" -name '*.verdict.json' 2>/dev/null | wc -l | tr -d ' ')" = "0" ] \
  || fail "negative self-test: the record finder reported records in an empty directory"
# The record lands under $OUT_DIR, which pr-review-agent.sh:111 derives from
# HOME ("$HOME/.config/kipi/pr-reviews") -- NOT from KIPI_STATE_DIR. Reading the
# derivation rather than assuming it is the point: the first draft of this case
# looked in the state dir, found nothing, and would have concluded "no record is
# written" -- the exact false-green this self-test exists to refuse.
[ "$(find "$WORK/home-post" -name '*.verdict.json' 2>/dev/null | wc -l | tr -d ' ')" -ge 1 ] \
  || fail "negative self-test: the record finder found no record even after the --post run, so it cannot detect one"
ok "negative self-test: the verdict-record finder distinguishes present from absent"

DRY_RECORDS="$(find "$WORK/home-dry" -name '*.verdict.json' 2>/dev/null | wc -l | tr -d ' ')"
echo "  [ctx] verdict records written by the no-post run: $DRY_RECORDS"

if [ "$DRY_RECORDS" -ge 1 ]; then
  ok "measured: the no-post run DID write the gating verdict record ($DRY_RECORDS)"

  # The false claim, named exactly. This is the assertion that was red.
  case "$VERDICT_LINE" in
    *"no gate moved"*) fail "the dry-run label claims 'no gate moved', but the run wrote $DRY_RECORDS verdict record(s):
      $VERDICT_LINE
      $(find "$WORK/home-dry" -name '*.verdict.json')
      converge.sh:748 and linear-worker.sh:1054 gate on that record. The run moved the loop's gate and told the reader it had not." ;;
    *) ok "the dry-run label does not claim 'no gate moved'" ;;
  esac

  # Deleting the false clause is not enough -- silence about the write is the
  # original defect again. The label has to say what the run DID do.
  case "$VERDICT_LINE" in
    *"verdict record"*) ok "the dry-run label discloses that the verdict record was still written" ;;
    *) fail "the dry-run label says nothing about the verdict record, which this run wrote and the loop gates on:
      $VERDICT_LINE
      Dropping the false clause without disclosing the write leaves the reader with the same wrong belief." ;;
  esac
else
  # The other direction: if the record write is ever moved behind --post, a
  # label that still mentions it becomes the new false claim.
  case "$VERDICT_LINE" in
    *"verdict record"*) fail "the label mentions a verdict record, but the no-post run wrote none. The claim and the behaviour have drifted apart:
      $VERDICT_LINE" ;;
    *) ok "the no-post run wrote no verdict record and the label claims none" ;;
  esac
fi

echo "PASS ($PASS checks) test-review-dry-run-labelled.sh"
