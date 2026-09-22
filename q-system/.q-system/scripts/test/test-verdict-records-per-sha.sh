#!/usr/bin/env bash
# Reproducer + acceptance criteria: verdict records are per-sha and append-only
# (ASK-1956, from the fleet-sync RCA row T4).
#
# THE DEFECT. `verdict_record_write_path` returns ONE path per (repo, PR) and the
# reviewer writes it with `open(out, "w")`, which truncates. So the second review
# of a PR destroys the first, and the only surviving statement about that PR is
# the last one written. A BLOCK recorded in round 1 is gone the moment round 2
# runs; an approval pinned to sha A is replaced by one pinned to sha B with
# nothing left to compare it against.
#
# THE FIX under test (pr-verdict-lib.sh + its three consumers):
#   - verdict_record_reserve  <dir> <slug> <pr> <sha>  -- creates a NEW file under
#     bash `noclobber`. The create IS the check (the validate-then-copy-is-a-race
#     lesson): two runs on one sha get two paths, and a second run can never land
#     on the first's path.
#   - verdict_record_for_head <dir> <slug> <pr> <sha>  -- the ONE reader-side
#     resolver: the record matching the PR's current head, else the newest record
#     at any sha, else the pre-change repo-keyed / legacy path.
#
# WHY TIER 2 OF THE RESOLVER IS TESTED. Returning nothing when no record matches
# the head would flip every pushed-past-approval PR from rework_gate exit 40
# (stale, re-review) to exit 20 (unreviewed) fleet-wide. P6 below pins that.
#
# Isolation: everything runs in a mktemp dir. Never touches the live
# ~/.config/kipi/pr-reviews.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
LIB="$ROOT/q-system/.q-system/scripts/pr-verdict-lib.sh"
SLUGLIB="$ROOT/q-system/.q-system/scripts/repo-slug-lib.sh"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$LIB" ]     || fail "pr-verdict-lib.sh does not exist at $LIB"
[ -f "$SLUGLIB" ] || fail "repo-slug-lib.sh does not exist at $SLUGLIB"
. "$SLUGLIB"
. "$LIB"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
DIR="$WORK/pr-reviews"; mkdir -p "$DIR"

SLUG="assafkip/kipi-system"
PR=901
SHA_A="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
SHA_B="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

# The expected basename stem is DERIVED from the owner of the naming rule, never
# typed here -- restating it would make this test a second source of truth for a
# value repo-slug-lib.sh owns (derive-a-value-from-its-owner lesson).
KEY="$(artifact_key "$SLUG" "$PR")"

write_record() {   # write_record <path> <verdict> <sha> <round>
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import json, sys
p, verdict, sha, rnd = sys.argv[1:5]
json.dump({"pr": 901, "verdict": verdict, "head_sha": sha,
           "round": int(rnd), "engine": "claude", "usable": True,
           "ts": "2026-09-22T0%s:00:00Z" % rnd}, open(p, "w"), indent=2)
PY
}

# --- the functions must exist before anything below means anything ------------
type verdict_record_reserve  >/dev/null 2>&1 \
  || fail "verdict_record_reserve is not defined in pr-verdict-lib.sh (the writer still cannot avoid clobbering)"
type verdict_record_for_head >/dev/null 2>&1 \
  || fail "verdict_record_for_head is not defined in pr-verdict-lib.sh (nothing resolves a record by the PR's current head)"
ok "both new resolvers are defined"

# --- P1: two runs on ONE sha produce TWO records ------------------------------
P1A="$(verdict_record_reserve "$DIR" "$SLUG" "$PR" "$SHA_A")" \
  || fail "P1: first reservation failed"
P1B="$(verdict_record_reserve "$DIR" "$SLUG" "$PR" "$SHA_A")" \
  || fail "P1: second reservation failed"
[ -n "$P1A" ] && [ -n "$P1B" ] || fail "P1: a reservation returned an empty path"
[ "$P1A" != "$P1B" ] \
  || fail "P1: two runs on one sha returned the SAME path ($P1A) -- the second would overwrite the first"
[ -f "$P1A" ] && [ -f "$P1B" ] \
  || fail "P1: a reserved path does not exist on disk (reservation must create it, or a concurrent run can take it)"
case "$(basename "$P1A")" in
  "$KEY"*) : ;;
  *) fail "P1: reserved basename $(basename "$P1A") does not start with the key $KEY that repo-slug-lib.sh owns" ;;
esac
case "$(basename "$P1A")" in
  *.verdict.json) : ;;
  *) fail "P1: reserved basename $(basename "$P1A") does not end in .verdict.json -- the out-of-scope globbers (review-redrive.py, verify-codex-review-live.sh) would stop seeing records" ;;
esac
ok "P1: two runs on one sha produce two distinct records, both created, both keyed and globbable"

# --- P2: the second write cannot overwrite the first --------------------------
write_record "$P1A" "BLOCK" "$SHA_A" 1
FIRST_BYTES="$(cat "$P1A")"
write_record "$P1B" "APPROVE" "$SHA_A" 2
[ "$(cat "$P1A")" = "$FIRST_BYTES" ] \
  || fail "P2: writing the second record changed the first record's bytes"
[ "$(verdict_from_record "$P1A")" = "BLOCK" ] \
  || fail "P2: the first record no longer reads BLOCK after the second landed (got '$(verdict_from_record "$P1A")')"
ok "P2: the second run left the first record byte-identical and still readable"

# --- P3: an OLDER record stays readable after a newer one lands ---------------
[ "$(head_sha_from_record "$P1A")" = "$SHA_A" ] \
  || fail "P3: the older record's head_sha is not readable after a newer record landed"
[ "$(verdict_from_record "$P1B")" = "APPROVE" ] \
  || fail "P3: the newer record does not read back its own verdict"
ok "P3: both the older and the newer record read back their own values"

# --- P4: the resolver returns the record matching the PR's CURRENT head -------
# The record for SHA_B is written LAST, so a newest-wins resolver would return it
# for a head of SHA_A. That is the mutation this case exists to kill.
P4B="$(verdict_record_reserve "$DIR" "$SLUG" "$PR" "$SHA_B")" || fail "P4: reservation failed"
write_record "$P4B" "REQUEST CHANGES" "$SHA_B" 3
RESOLVED="$(verdict_record_for_head "$DIR" "$SLUG" "$PR" "$SHA_A")"
[ -n "$RESOLVED" ] || fail "P4: the resolver returned nothing for a head that HAS a record"
[ "$(head_sha_from_record "$RESOLVED")" = "$SHA_A" ] \
  || fail "P4: resolving head $SHA_A returned a record pinned to $(head_sha_from_record "$RESOLVED") -- a newer record for a different sha won"
ok "P4: the resolver picks the record matching the current head, not merely the newest"

RESOLVED_B="$(verdict_record_for_head "$DIR" "$SLUG" "$PR" "$SHA_B")"
[ "$(verdict_from_record "$RESOLVED_B")" = "REQUEST CHANGES" ] \
  || fail "P4b: resolving head $SHA_B did not return the record written for it"
ok "P4b: the other head resolves to its own record"

# --- P5: no per-sha record at all -> the pre-change paths still resolve -------
# Pre-ASK-1956 records (~90 legacy un-slugged, plus every repo-keyed one) must
# keep resolving, or every open PR reads as unreviewed and re-review rounds fire
# across the whole board at once.
OLD="$WORK/old"; mkdir -p "$OLD"
write_record "$OLD/$KEY.verdict.json" "APPROVE WITH NITS" "$SHA_A" 1
R5="$(verdict_record_for_head "$OLD" "$SLUG" "$PR" "$SHA_A")"
[ "$(verdict_from_record "$R5")" = "APPROVE WITH NITS" ] \
  || fail "P5: a pre-change repo-keyed record no longer resolves"
LEG="$WORK/legacy"; mkdir -p "$LEG"
write_record "$LEG/pr-$PR.verdict.json" "BLOCK" "$SHA_B" 1
R5L="$(verdict_record_for_head "$LEG" "$SLUG" "$PR" "$SHA_A")"
[ "$(verdict_from_record "$R5L")" = "BLOCK" ] \
  || fail "P5: a legacy un-slugged record no longer resolves"
ok "P5: repo-keyed and legacy pre-change records still resolve"

# --- P6: a record exists, but for a DIFFERENT sha -> still returned -----------
# This is the drift path ASK-216/ASK-219 built. Returning nothing here would send
# rework_gate to exit 20 (unreviewed) instead of exit 40 (stale), which is a
# different terminal branch on every pushed-past-approval PR in the fleet.
ONLY_B="$WORK/onlyb"; mkdir -p "$ONLY_B"
P6="$(verdict_record_reserve "$ONLY_B" "$SLUG" "$PR" "$SHA_B")" || fail "P6: reservation failed"
write_record "$P6" "APPROVE" "$SHA_B" 1
R6="$(verdict_record_for_head "$ONLY_B" "$SLUG" "$PR" "$SHA_A")"
[ -n "$R6" ] || fail "P6: no record returned when one exists at another sha"
V6="$(verdict_from_record "$R6")"; S6="$(head_sha_from_record "$R6")"
[ "$V6" = "APPROVE" ] && [ "$S6" = "$SHA_B" ] \
  || fail "P6: expected the other-sha record (APPROVE @ $SHA_B), got '$V6' @ '$S6'"
rework_gate "$V6" "" "$S6" "$SHA_A"; G6=$?
[ "$G6" -eq 40 ] \
  || fail "P6: rework_gate returned $G6, not 40 -- the ASK-216 drift exit no longer fires through the new resolver"
ok "P6: an other-sha record is still returned and still reaches rework_gate exit 40"

# --- P7: an empty current sha falls back rather than inventing ----------------
R7="$(verdict_record_for_head "$ONLY_B" "$SLUG" "$PR" "")"
[ "$(head_sha_from_record "$R7")" = "$SHA_B" ] \
  || fail "P7: an unreadable current head did not fall back to the newest record"
ok "P7: an empty current head falls back to the newest record, never to nothing"

# --- P8: the shipped writer reserves instead of clobbering --------------------
# Reads the SHIPPED pr-review-agent.sh rather than a copy: the write call site
# must go through the reservation, or every property above is true of a function
# nothing calls.
AGENT="$ROOT/q-system/.q-system/scripts/pr-review-agent.sh"
# THE CALL FORM, NOT THE NAME. Both files carry why-comments that NAME the old
# resolver, and a bare name match reported the shipped writer as unfixed while
# it was already reserving (observed RED here, pass 2). `$(fn ` is what an
# invocation looks like in these scripts.
grep -q '\$(verdict_record_reserve ' "$AGENT" \
  || fail "P8: pr-review-agent.sh does not CALL verdict_record_reserve -- the new writer is not wired"
grep -q '\$(verdict_record_write_path ' "$AGENT" \
  && fail "P8: pr-review-agent.sh still calls verdict_record_write_path, the clobbering path"
ok "P8: the shipped reviewer writes through the reservation"

# --- P9: both readers resolve by the current head ----------------------------
for f in converge.sh linear-worker.sh; do
  S="$ROOT/q-system/.q-system/scripts/$f"
  grep -q '\$(verdict_record_for_head ' "$S" \
    || fail "P9: $f does not CALL verdict_record_for_head -- it still reads one path per PR"
  grep -q '\$(verdict_record_path "\$REVIEWS_DIR"' "$S" \
    && fail "P9: $f still resolves through verdict_record_path directly; the head-aware resolver must be the one reader"
done
ok "P9: converge.sh and linear-worker.sh both resolve through the head-aware reader"

echo "PASS: $PASS checks"
