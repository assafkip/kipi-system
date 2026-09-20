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
  *"-X POST"*) exit 0 ;;
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

# ------------------------------------------------------------------ wiring
# A script nothing calls fixes nothing. approval_carry is CUT FROM THE SHIPPED
# converge.sh (same move as test-converge-crossrepo-receipt.sh), and driven
# against a real origin + clone so FETCH_HEAD is what git actually wrote.
CONVERGE="${RECEIPT_CARRY_CONVERGE:-$HERE/../converge.sh}"
echo "wiring (approval_carry cut from the shipped converge.sh)"
FN="$TMP/fn.sh"
sed -n '/^approval_carry() {/,/^}$/p' "$CONVERGE" > "$FN"
check_eq "converge.sh defines approval_carry" "1" "$(grep -c '^approval_carry() {' "$FN")"
check_eq "the receipt-confirmed branch calls it with the reviewed sha" "1" \
  "$(sed -n '/^receipt_confirm_origin() {/,/^}$/p' "$CONVERGE" | grep -c '^    approval_carry "\$tree" "\$sha"$')"

ORIGIN="$TMP/origin.git"; CLONE="$TMP/clone"
git init -q --bare "$ORIGIN"
g push -q "$ORIGIN" "$RECEIPT:refs/heads/sana/ask-1"
git clone -q "$ORIGIN" "$CLONE" 2>/dev/null
git -C "$CLONE" fetch -q origin sana/ask-1
wire() {  # wire <slug>  -> number of POSTs
  : > "$CALLS"
  STUB_REVIEWED="$REVIEWED" STUB_REVIEWED_PAYLOAD="$FX/reviewed-approved.json" \
  STUB_HEAD_PAYLOAD="$FX/head-floor-only.json" RECEIPT_CARRY_GH="$STUB" \
  SCRIPT_DIR="$(dirname "$SCRIPT")" CARRY_UNDER_TEST="$SCRIPT" \
  TARGET_SLUG="$1" TARGET_REPO="$CLONE" BRANCH="sana/ask-1" \
    bash -c "say() { :; }; . '$FN'; approval_carry '$CLONE' '$REVIEWED'" >/dev/null 2>&1
  grep -c -- "-X POST" "$CALLS" || true
}
# SCRIPT_DIR is the real scripts dir, so this runs the shipped carry script. Under
# the mutation harness SCRIPT is a mutant in $TMP with no sibling, so skip there.
if [ -z "${RECEIPT_CARRY_SCRIPT:-}" ]; then
  check_eq "converge carries the approval onto origin's receipt head" "1" "$(wire o/r)"
  check_eq "and it lands on the sha origin has" "1" "$(grep -c -- "statuses/$RECEIPT " "$CALLS")"
  check_eq "with no owner/repo slug it posts NOTHING (ASK-738: gh api resolves from cwd)" "0" "$(wire "")"
fi

# ------------------------------------------------------------------ mutation
# One mutant per decision point. Each must turn this file RED, or the check it
# targets is decoration. Skipped when already running against a mutant.
if [ -z "${RECEIPT_CARRY_SCRIPT:-}" ] && [ -z "${RECEIPT_CARRY_CONVERGE:-}" ]; then
  echo "mutation (each mutant must fail this file)"
  # The wiring mutant: converge.sh with the call deleted. This is the shipped
  # defect -- a receipt confirmed on origin and nobody carrying the approval.
  CM="$TMP/converge-mutant.sh"
  grep -v '^    approval_carry "\$tree" "\$sha"$' "$CONVERGE" > "$CM"
  if cmp -s "$CM" "$CONVERGE"; then fail "the converge mutant changed nothing"
  elif RECEIPT_CARRY_CONVERGE="$CM" bash "${BASH_SOURCE[0]}" >/dev/null 2>&1; then fail "mutant 'converge never calls the carry' SURVIVED"
  else pass "mutant 'converge never calls the carry' killed"; fi
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
