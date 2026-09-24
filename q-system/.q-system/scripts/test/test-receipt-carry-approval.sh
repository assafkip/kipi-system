#!/usr/bin/env bash
# An approval survives the receipt commit, and ONLY the receipt commit (ASK-1888).
#
# WHY THIS EXISTS. converge writes the prd-os receipt as a commit ON the approved
# branch, 4 to 11 seconds after the reviewer posts `kipi/reviewer-approved=success`.
# A commit status is per-sha, so the approval stayed on the old head and the new
# head had none. Measured 2026-09-19: 31 approved PRs red on their current head,
# 25 of them behind exactly that commit, 1 merge in 9 days of 10 dispatches a day.
#
# THE FIXTURES ARE REAL API PAYLOADS, captured 2026-09-19 from GitHub's plural
# statuses endpoint (trimmed to the five fields the script reads):
#
#   reviewed-approved.json        <- PR #370 reviewed sha 45e0445f: floor, then APPROVE WITH NITS
#   head-floor-only.json          <- PR #370 receipt head 96778488: the floor's red and nothing else
#   reviewed-request-changes.json <- PR #372 reviewed sha: a real REQUEST CHANGES
#   head-absent.json              <- a head nobody has posted on
#
# Isolation: `gh` is a recording stub via RECEIPT_CARRY_GH and the repos are
# throwaway `git init` trees under mktemp. No network, no status posted, no live
# data path.

set -uo pipefail

# THE NOTIFIER IS STUBBED FOR EVERY CHILD OF THIS FILE. The mutation harness at
# the bottom re-invokes this file with a MUTATED converge.sh, and a mutant is by
# construction a path nobody reasoned about. converge resolves its pager through
# KIPI_NOTIFY, so binding it here once means no mutant can reach the real one.
# Scar: 2026-08-01, a suite reporting 14/14 green paged the founder twice.
export KIPI_NOTIFY=/usr/bin/true

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FX="$HERE/fixtures/receipt-carry"
# REF HATCH: the mutation harness at the bottom re-invokes this file at a mutant.
SCRIPT="${RECEIPT_CARRY_SCRIPT:-$HERE/../receipt-carry-approval.sh}"

PASS=0; FAIL=0
pass() { PASS=$((PASS + 1)); echo "  ok   $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; }
check_eq() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (want '$2', got '$3')"; fi; }

# shellcheck source=/dev/null
. "$SCRIPT"

echo "decision (pure, real payloads) -- script under test: $SCRIPT"

check_eq "an approval buried under the floor is still the live verdict" \
  "success APPROVE WITH NITS" "$(live_verdict < "$FX/reviewed-approved.json")"
check_eq "a real REQUEST CHANGES is not an approval" \
  "failure REQUEST CHANGES" "$(live_verdict < "$FX/reviewed-request-changes.json")"
check_eq "the floor's own red is not a verdict" \
  "none" "$(live_verdict < "$FX/head-floor-only.json" | cut -d' ' -f1)"
check_eq "an empty list is not a verdict" \
  "none" "$(live_verdict < "$FX/head-absent.json" | cut -d' ' -f1)"
# Derived from the two real payloads: a later refusal stacked on an earlier approval.
check_eq "an approval the reviewer later withdrew does not carry" \
  "failure REQUEST CHANGES" \
  "$(jq -s '.[0] + .[1]' "$FX/reviewed-request-changes.json" "$FX/reviewed-approved.json" | live_verdict)"

# ------------------------------------------------- what the header may claim
# ASK-1905 nit 3. The ORDER guarantees exactly one thing: nothing on the NEW sha
# can predate the copy. It does NOT close the window on the REVIEWED sha -- a
# REQUEST CHANGES landing there between guard 1's read and converge's branch move
# is buried by the move, not by this script. The header claimed the gap was gone
# entirely, which is a wider claim than the code keeps. Prose is all there is to
# check here, so this greps the shipped header rather than pretending otherwise.
echo "header (the claim the order actually earns)"
HDR="$(sed -n '1,60p' "$SCRIPT")"
check_eq "the header does not claim the copy can never bury a verdict" "0" \
  "$(printf '%s' "$HDR" | grep -c 'cannot bury a verdict' || true)"
check_eq "it names what the order guarantees: no verdict on the NEW sha predates the copy" "yes" \
  "$(printf '%s' "$HDR" | grep -q 'predate the copy' && echo yes || echo no)"
check_eq "and it names the window that stays open: a refusal on the reviewed sha" "yes" \
  "$(printf '%s' "$HDR" | grep -q 'refusal landing on the reviewed sha' && echo yes || echo no)"

# ------------------------------------------------------------------ git half
TMP="$(mktemp -d "${TMPDIR:-/tmp}/receipt-carry.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
REPO="$TMP/repo"
git init -q "$REPO"
g() { git -C "$REPO" -c user.name=t -c user.email=t@t.invalid "$@"; }
mkdir -p "$REPO/.prd-os"; echo code > "$REPO/src.sh"; : > "$REPO/.prd-os/receipts.jsonl"
g add -A; g commit -q -m reviewed; REVIEWED="$(g rev-parse HEAD)"
echo '{"r":1}' >> "$REPO/.prd-os/receipts.jsonl"; g commit -q -am "chore(receipt)"; RECEIPT="$(g rev-parse HEAD)"
echo more >> "$REPO/src.sh"; g commit -q -am "code after review"; CODE="$(g rev-parse HEAD)"
g checkout -q -b side "$REVIEWED~0" 2>/dev/null; g checkout -q --orphan other; g rm -rq --cached . ; echo x > "$REPO/o"; g add o; g commit -q -m other; OTHER="$(g rev-parse HEAD)"

echo "delta (what the new head adds beyond the reviewed sha)"
check_eq "receipt-only delta is carriable"            "receipt-only" "$(delta_kind "$REPO" "$REVIEWED" "$RECEIPT")"
check_eq "code after the review is NOT carriable"     "other"        "$(delta_kind "$REPO" "$REVIEWED" "$CODE")"
check_eq "the same sha is nothing to carry"           "same"         "$(delta_kind "$REPO" "$REVIEWED" "$REVIEWED")"
check_eq "an unrelated line of history is NOT carriable" "other"     "$(delta_kind "$REPO" "$REVIEWED" "$OTHER")"
check_eq "a sha git cannot resolve is NOT carriable"  "other"        "$(delta_kind "$REPO" "$REVIEWED" "0000000000000000000000000000000000000000")"

# ------------------------------------------------------------------ end to end
# The stub serves a payload per sha and records every POST.
STUB="$TMP/gh"; CALLS="$TMP/calls"
cat > "$STUB" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "$CALLS"
case "\$*" in
  *"-X POST"*)
    # WHERE WAS THE BRANCH WHEN THE GREEN WAS WRITTEN? The whole safety of the
    # carry is its order, so the stub records what origin's branch pointed at, and
    # whether the staging ref existed, at the instant of the POST.
    if [ -n "\${STUB_ORIGIN:-}" ]; then
      echo "AT-POST branch=\$(git -C "\$STUB_ORIGIN" rev-parse -q --verify "refs/heads/\$STUB_BRANCH" 2>/dev/null)" >> "$CALLS"
      echo "AT-POST staging=\$(git -C "\$STUB_ORIGIN" for-each-ref --format='%(objectname)' refs/kipi/receipt-staging | tr '\n' ' ')" >> "$CALLS"
    fi
    exit "\${STUB_POST_RC:-0}" ;;
  *"/commits/\$STUB_REVIEWED/statuses"*) cat "\$STUB_REVIEWED_PAYLOAD" ;;
  *"/commits/"*"/statuses"*) cat "\$STUB_HEAD_PAYLOAD" ;;
esac
EOF
chmod +x "$STUB"
run() {  # run <reviewed-payload> <head-payload> <head-sha>
  : > "$CALLS"
  STUB_REVIEWED="$REVIEWED" STUB_REVIEWED_PAYLOAD="$1" STUB_HEAD_PAYLOAD="$2" \
    RECEIPT_CARRY_GH="$STUB" bash "$SCRIPT" "$REPO" "$REVIEWED" "$3" "o/r" >/dev/null 2>&1
  grep -c -- "-X POST" "$CALLS" || true
}
echo "end to end (stubbed gh, throwaway repo)"
check_eq "THE REPRODUCER: approved + receipt-only + floor-only head posts once" \
  "1" "$(run "$FX/reviewed-approved.json" "$FX/head-floor-only.json" "$RECEIPT")"
check_eq "the post is a success on the NEW head, in the reviewer's context" \
  "1" "$(grep -c -- "-X POST repos/o/r/statuses/$RECEIPT -f state=success -f context=kipi/reviewer-approved" "$CALLS")"
check_eq "the description names the sha the approval came from" \
  "1" "$(grep -c "carried from $(printf '%.12s' "$REVIEWED")" "$CALLS")"
check_eq "approved + receipt-only + absent head posts once" \
  "1" "$(run "$FX/reviewed-approved.json" "$FX/head-absent.json" "$RECEIPT")"
check_eq "code after the review posts NOTHING" \
  "0" "$(run "$FX/reviewed-approved.json" "$FX/head-floor-only.json" "$CODE")"
check_eq "a REQUEST CHANGES posts NOTHING" \
  "0" "$(run "$FX/reviewed-request-changes.json" "$FX/head-floor-only.json" "$RECEIPT")"
check_eq "a head the reviewer already judged is never overwritten" \
  "0" "$(run "$FX/reviewed-approved.json" "$FX/reviewed-request-changes.json" "$RECEIPT")"
check_eq "an unreadable reviewed payload posts NOTHING" \
  "0" "$(run "$TMP/does-not-exist.json" "$FX/head-absent.json" "$RECEIPT")"

check_eq "a guard saying no exits 10, so the caller can tell it from a failure" "10" \
  "$(STUB_REVIEWED="$REVIEWED" STUB_REVIEWED_PAYLOAD="$FX/reviewed-request-changes.json" STUB_HEAD_PAYLOAD="$FX/head-absent.json" \
     RECEIPT_CARRY_GH="$STUB" bash "$SCRIPT" "$REPO" "$REVIEWED" "$RECEIPT" "o/r" >/dev/null 2>&1; echo $?)"
check_eq "a post GitHub refuses exits 1, not 0" "1" \
  "$(STUB_POST_RC=1 STUB_REVIEWED="$REVIEWED" STUB_REVIEWED_PAYLOAD="$FX/reviewed-approved.json" STUB_HEAD_PAYLOAD="$FX/head-absent.json" \
     RECEIPT_CARRY_GH="$STUB" bash "$SCRIPT" "$REPO" "$REVIEWED" "$RECEIPT" "o/r" >/dev/null 2>&1; echo $?)"

# ------------------------------------------------------------------ wiring
# A script nothing calls fixes nothing, and THIS one is only safe in one order.
# approval_carry is CUT FROM THE SHIPPED converge.sh (same move as
# test-converge-crossrepo-receipt.sh) and driven against a real bare origin, so
# "the branch had not moved yet" is read from git, not asserted in a comment.
CONVERGE="${RECEIPT_CARRY_CONVERGE:-$HERE/../converge.sh}"
echo "wiring (approval_carry cut from the shipped converge.sh)"
FN="$TMP/fn.sh"
sed -n '/^approval_carry() {/,/^}$/p' "$CONVERGE" > "$FN"
check_eq "converge.sh defines approval_carry" "1" "$(grep -c '^approval_carry() {' "$FN")"

# THE ORDER, read from the shipped function body: the carry call sits ABOVE the
# line that moves the branch, inside receipt_transaction, and nowhere else.
TX="$(sed -n '/^receipt_transaction() {/,/^}$/p' "$CONVERGE")"
CALL_LINE="$(printf '%s\n' "$TX" | grep -n '^  approval_carry "\$tree" "\$sha"$' | cut -d: -f1 | head -1)"
MOVE_LINE="$(printf '%s\n' "$TX" | grep -n 'HEAD:refs/heads/\$BRANCH' | cut -d: -f1 | head -1)"
check_eq "receipt_transaction calls the carry" "yes" "$([ -n "$CALL_LINE" ] && echo yes || echo no)"
check_eq "and calls it BEFORE the line that moves the branch" "yes" \
  "$([ -n "$CALL_LINE" ] && [ -n "$MOVE_LINE" ] && [ "$CALL_LINE" -lt "$MOVE_LINE" ] && echo yes || echo no)"
check_eq "nothing carries onto a head that is already live (receipt_confirm_origin)" "0" \
  "$(sed -n '/^receipt_confirm_origin() {/,/^}$/p' "$CONVERGE" | grep -c 'approval_carry')"
check_eq "a missed carry reaches the terminal page, not just the log" "1" \
  "$(grep -c 'if \[ -z "\$RECEIPT_MISS" \] && \[ -n "\$CARRY_MISS" \]; then' "$CONVERGE")"

ORIGIN="$TMP/origin.git"; CLONE="$TMP/clone"
git init -q --bare "$ORIGIN"
g push -q "$ORIGIN" "$REVIEWED:refs/heads/sana/ask-1"
git clone -q -b sana/ask-1 "$ORIGIN" "$CLONE" 2>/dev/null
# The clone now stands where converge's tree stands: the receipt is committed
# locally and origin's branch is still at the reviewed sha.
git -C "$CLONE" -c user.name=t -c user.email=t@t.invalid pull -q "$REPO" "$RECEIPT" 2>/dev/null \
  || git -C "$CLONE" fetch -q "$REPO" "$RECEIPT" && git -C "$CLONE" reset -q --hard "$RECEIPT"
wire() {  # wire <slug> <reviewed-payload>  -> prints CARRY_MISS (empty when carried)
  : > "$CALLS"
  STUB_ORIGIN="$ORIGIN" STUB_BRANCH="sana/ask-1" \
  STUB_REVIEWED="$REVIEWED" STUB_REVIEWED_PAYLOAD="$2" \
  STUB_HEAD_PAYLOAD="$FX/head-absent.json" RECEIPT_CARRY_GH="$STUB" \
  SCRIPT_DIR="$(dirname "$SCRIPT")" LOG="$TMP/converge.log" \
  TARGET_SLUG="$1" TARGET_REPO="$CLONE" BRANCH="sana/ask-1" \
    bash -c "say() { :; }; CARRY_STAGING_PREFIX=refs/kipi/receipt-staging; . '$FN'; approval_carry '$CLONE' '$REVIEWED'; printf '%s' \"\$CARRY_MISS\"" 2>/dev/null
}
# SCRIPT_DIR is the real scripts dir, so this runs the shipped carry script. Under
# the script-mutation harness SCRIPT is a mutant in $TMP with no sibling: skip.
if [ -z "${RECEIPT_CARRY_SCRIPT:-}" ]; then
  MISS="$(wire o/r "$FX/reviewed-approved.json")"
  check_eq "converge carries the approval, and reports no miss" "" "$MISS"
  check_eq "onto the receipt commit" "1" "$(grep -c -- "-X POST repos/o/r/statuses/$RECEIPT " "$CALLS")"
  check_eq "WHILE origin's branch still pointed at the reviewed sha" \
    "AT-POST branch=$REVIEWED" "$(grep '^AT-POST branch=' "$CALLS")"
  check_eq "and the receipt commit was already on GitHub, under its staging ref" \
    "AT-POST staging=$RECEIPT " "$(grep '^AT-POST staging=' "$CALLS")"
  check_eq "the staging ref is tidied afterwards" "" \
    "$(git -C "$ORIGIN" for-each-ref --format='%(refname)' refs/kipi/receipt-staging)"
  check_eq "a declined carry is a MISS the page will carry" "yes" \
    "$(wire o/r "$FX/reviewed-request-changes.json" | grep -q 'NOT carried' && echo yes || echo no)"
  check_eq "with no owner/repo slug: NOTHING posted, and not a miss (there is no status API to miss)" " 0" \
    "$(wire "" "$FX/reviewed-approved.json") $(grep -c -- "-X POST" "$CALLS" || true)"

  # ORIGIN HAS THE LAST WORD (codex, PR #376 round 3). On a retry the receipt is
  # already on origin, approval_carry never runs, and the page went back to "no
  # human merge needed" over a red head. approval_confirm asks GitHub what the
  # head origin has actually carries, every run, and never posts.
  echo "confirm (approval_confirm cut from the shipped converge.sh)"
  FN2="$TMP/fn2.sh"
  sed -n '/^approval_confirm() {/,/^}$/p' "$CONVERGE" > "$FN2"
  check_eq "converge.sh defines approval_confirm" "1" "$(grep -c '^approval_confirm() {' "$FN2")"
  check_eq "the receipt-confirmed branch calls it, with the PR number threaded in" "1" \
    "$(sed -n '/^receipt_confirm_origin() {/,/^}$/p' "$CONVERGE" | grep -c '^    approval_confirm "\$tree" "\$sha" "\$pr"$')"
  check_eq "and receipt_ensure is where that PR number comes from" "1" \
    "$(sed -n '/^receipt_ensure() {/,/^}$/p' "$CONVERGE" | grep -c '^  receipt_confirm_origin "\$tree" "\$sha" "\$record" "\$pr"$')"
  # Origin's branch now IS the receipt commit, which is the retry's world.
  g push -q "$ORIGIN" "$RECEIPT:refs/heads/sana/ask-1"
  git -C "$CLONE" fetch -q origin sana/ask-1
  CARRIED="$TMP/head-carried.json"
  jq '[{"context":"kipi/reviewer-approved","state":"success","description":"carried from 45e0445f5656 (receipt-only delta): APPROVE","target_url":null,"created_at":"2026-09-19T00:00:00Z"}] + .' \
    "$FX/head-floor-only.json" > "$CARRIED"
  confirm() {  # confirm <slug> <head-payload> <starting CARRY_MISS>  -> prints CARRY_MISS afterwards
    : > "$CALLS"
    STUB_REVIEWED="$REVIEWED" STUB_REVIEWED_PAYLOAD="$FX/reviewed-approved.json" STUB_HEAD_PAYLOAD="$2" \
    RECEIPT_CARRY_GH="$STUB" SCRIPT_DIR="$(dirname "$SCRIPT")" LOG="$TMP/converge.log" \
    TARGET_SLUG="$1" TARGET_REPO="$CLONE" BRANCH="sana/ask-1" ISSUE="ASK-1" START_MISS="$3" \
      bash -c "say() { :; }; CARRY_MISS=\"\$START_MISS\"; CARRY_FIX=''; . '$FN2'; approval_confirm '$CLONE' '$REVIEWED'; printf '%s' \"\$CARRY_MISS\"" 2>/dev/null
  }
  check_eq "THE ROUND-3 REPRODUCER: a retry over a red head is a MISS, though this run carried nothing" "yes" \
    "$(confirm o/r "$FX/head-floor-only.json" "" | grep -q 'carries no live reviewer approval (state: none)' && echo yes || echo no)"
  check_eq "a head GitHub shows as approved clears a stale miss" "" "$(confirm o/r "$CARRIED" "stale miss from an earlier step")"
  check_eq "a head the reviewer REFUSED is a miss too" "yes" \
    "$(confirm o/r "$FX/reviewed-request-changes.json" "" | grep -q '(state: failure)' && echo yes || echo no)"
  check_eq "GitHub unreadable is a miss, never a silent pass" "yes" \
    "$(confirm o/r "$TMP/does-not-exist.json" "" | grep -q '(state: unreadable)' && echo yes || echo no)"
  check_eq "confirming never posts" "0" "$(grep -c -- "-X POST" "$CALLS" || true)"

  # ASK-1905 nits 1 and 2, both about the PAGE rather than the decision. A page
  # the operator has to edit before running, or one that prescribes a re-review
  # for an expired token, spends the 3am it just bought. Same helper as confirm,
  # reading CARRY_FIX instead of CARRY_MISS.
  confirm_fix() {  # confirm_fix <slug> <head-payload> <pr>  -> prints CARRY_FIX
    : > "$CALLS"
    STUB_REVIEWED="$REVIEWED" STUB_REVIEWED_PAYLOAD="$FX/reviewed-approved.json" STUB_HEAD_PAYLOAD="$2" \
    RECEIPT_CARRY_GH="$STUB" SCRIPT_DIR="$(dirname "$SCRIPT")" LOG="$TMP/converge.log" \
    TARGET_SLUG="$1" TARGET_REPO="$CLONE" BRANCH="sana/ask-1" ISSUE="ASK-1" PRNUM="$3" \
      bash -c "say() { :; }; CARRY_MISS=''; CARRY_FIX=''; . '$FN2'; approval_confirm '$CLONE' '$REVIEWED' \"\$PRNUM\"; printf '%s' \"\$CARRY_FIX\"" 2>/dev/null
  }
  # nit 1: $PR is in scope at the page, so the remedy is pasteable or it is not a remedy.
  check_eq "the red-head remedy names the PR number, so it can be pasted" "yes" \
    "$(confirm_fix o/r "$FX/head-floor-only.json" 376 | grep -q 'pr-review-agent.sh 376 --issue ASK-1 --post' && echo yes || echo no)"
  check_eq "and carries no literal <pr> placeholder" "0" \
    "$(confirm_fix o/r "$FX/head-floor-only.json" 376 | grep -c '<pr>' || true)"
  # nit 2: `unreadable` means converge could not ASK. It is not "the head is red",
  # and no amount of re-reviewing fixes an expired token or a dead network.
  check_eq "an unreadable GitHub is NOT paged as a head carrying no approval" "0" \
    "$(confirm o/r "$TMP/does-not-exist.json" "" | grep -c 'carries no live reviewer approval' || true)"
  check_eq "it says converge could not read the verdict, which is a different claim" "yes" \
    "$(confirm o/r "$TMP/does-not-exist.json" "" | grep -q 'could not read' && echo yes || echo no)"
  check_eq "and its remedy is auth plus network, never a re-review" "yes" \
    "$(confirm_fix o/r "$TMP/does-not-exist.json" 376 | grep -q 'gh auth status' && echo yes || echo no)"
  check_eq "a genuinely red head still gets the re-review remedy" "yes" \
    "$(confirm_fix o/r "$FX/head-floor-only.json" 376 | grep -q 'pr-review-agent.sh' && echo yes || echo no)"
  check_eq "--head-state is read-only and says what GitHub shows" "success 0" \
    "$(STUB_REVIEWED=x STUB_REVIEWED_PAYLOAD=/dev/null STUB_HEAD_PAYLOAD="$CARRIED" RECEIPT_CARRY_GH="$STUB" bash "$SCRIPT" --head-state o/r "$RECEIPT") $(grep -c -- "-X POST" "$CALLS" || true)"
fi

# ------------------------------------------------------------------ mutation
# One mutant per decision point. Each must turn this file RED, or the check it
# targets is decoration. Skipped when already running against a mutant.
if [ -z "${RECEIPT_CARRY_SCRIPT:-}" ] && [ -z "${RECEIPT_CARRY_CONVERGE:-}" ]; then
  echo "mutation (each mutant must fail this file)"
  cmutate() {  # cmutate <label> <python-expr over s>
    local cm="$TMP/converge-mutant.sh"
    python3 - "$CONVERGE" "$cm" "$2" <<'PY'
import sys
src, dst, expr = sys.argv[1:4]
s = open(src).read()
CALL = '  approval_carry "$tree" "$sha"\n'
open(dst, "w").write(eval(expr))
PY
    if cmp -s "$cm" "$CONVERGE"; then fail "converge mutant '$1' changed nothing"
    elif RECEIPT_CARRY_CONVERGE="$cm" bash "${BASH_SOURCE[0]}" >/dev/null 2>&1; then fail "mutant '$1' SURVIVED"
    else pass "mutant '$1' killed"; fi
  }
  # The shipped defect: a receipt lands and nobody carries the approval.
  cmutate "converge never calls the carry" 's.replace(CALL, "", 1)'
  # Round 3's defect: nobody asks origin, so a retry reports a red head as landing.
  cmutate "converge never confirms the head with origin" 's.replace("    approval_confirm \"$tree\" \"$sha\" \"$pr\"\n", "", 1)'
  # ASK-1905 nit 1: drop the PR number on the way down and the page goes back to
  # a command the operator cannot paste.
  cmutate "the PR number never reaches the page" \
    's.replace("  receipt_confirm_origin \"$tree\" \"$sha\" \"$record\" \"$pr\"\n", "  receipt_confirm_origin \"$tree\" \"$sha\" \"$record\"\n", 1)'
  # ASK-1905 nit 2: collapse unreadable back into the red-head sentence.
  cmutate "an unreadable GitHub is paged as a red head again" \
    's.replace("  if [ \"$state\" = \"unreadable\" ]; then\n", "  if false; then\n", 1)'
  # The defect two review rounds were about: the carry runs AFTER the branch moved.
  cmutate "converge carries after the branch moved" \
    's.replace(CALL, "", 1).replace("    say \"receipt: pushed --", "    approval_carry \"$tree\" \"$sha\"\n    say \"receipt: pushed --", 1)'
  mutate() {  # mutate <label> <sed-expr>
    local m="$TMP/mutant.sh"
    sed "$2" "$SCRIPT" > "$m"
    if cmp -s "$m" "$SCRIPT"; then fail "mutant '$1' changed nothing -- the sed no longer matches"; return; fi
    if RECEIPT_CARRY_SCRIPT="$m" bash "${BASH_SOURCE[0]}" >/dev/null 2>&1; then
      fail "mutant '$1' SURVIVED"
    else
      pass "mutant '$1' killed"
    fi
  }
  mutate "delta guard removed"        's/\[ "\$kind" = "receipt-only" \]/true/'
  mutate "approval guard removed"     's/\[ "\$state" = "success" \]/true/'
  mutate "no-overwrite guard removed" 's/\[ "\$head_state" = "none" \]/true/'
fi

echo
echo "passed $PASS, failed $FAIL"
[ "$FAIL" = "0" ]
