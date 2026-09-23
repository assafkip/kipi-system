#!/usr/bin/env bash
# An outage is bounded, quiet after its first word, and blames nobody (ASK-2009).
#
# PR #421 round 1 found that the halt from ASK-873 stopped CHARGING issues for a
# dead account but still made noise per tick. Each case below is the reviewer's
# own reproducer, kept verbatim under env-halt-bounds/ (only its repo-root line
# moved with it), and this driver asserts the number each one prints. Every
# number was measured RED on the code before the fix:
#
#   comment-spam2   3 halted runs, 1 outage -> "Not attempted" Linear comments.
#                   Was 3 (one per tick). Must be 1.
#   codex-loop      a Codex outage over two ticks -> pages. Was 0 (silent, exit 0,
#                   re-dispatched forever). Must be 1.
#   codex-limit     a Codex outage with --limit 1 on a 3-issue board. Was: one run
#                   walked ASK-811, 812 and 813. Must stop at ASK-811.
#   converge-page   converge after the worker's env halt -> pages. Was 1 (an
#                   exit-7 "Sana could not open a PR" per issue per tick). Must be 0.
#   leak            orphan per-pid files left by dead runs, after one healthy run.
#                   Was 2. Must be 0.
#   unmute-on-skip  one outage, with a middle tick that skipped every issue and
#                   never ran the runner. Was 2 pages and 2 comments. Must be 1
#                   and 1, and a tick where the runner answers must still free
#                   the claim so the NEXT outage pages (2 pages across 2).
#   pickup-spam     "Picked up ... Attempt 1 of 3" notes over 5 ticks of one
#                   outage. Was 5 (unbounded once the charge was gone). Must be
#                   1, and a new attempt after the runner answers must post (2).
#   codex-pickup-spam  the same note over 3 ticks of one CODEX outage, where Sana
#                   answers every tick. Was 3. Must be 1.
#   codex-fixture   every real worker handoff to Codex (44), replayed through the
#                   worker's own decision. Was 0 of 17 outages read as one. Must
#                   be 17 of 17, with 0 of 27 answered runs misread.
#   codex-real-outage  a real Codex outage transcript through the real worker.
#                   Was: parked blocked:capability, no page. Must not park, page
#                   once; a 2-day-old claim must expire and page; a fresh claim
#                   must still dedupe the page but not the per-issue note.
#   codex-allcomments  paid Sana runs and "Worker run completed" notes over 5
#                   ticks of one Codex outage. Was 5 and 5. Must be 1 and 1, the
#                   held issue must carry the mark converge reads, and a sixth
#                   tick after the claim is a day old must run it once more.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
B="$HERE/env-halt-bounds"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

run() { bash "$B/$1.sh" 2>&1 | grep -v 'Terminated'; }

echo "== one outage, one Linear comment"
OUT="$(run repro-comment-spam2)"
N="$(printf '%s\n' "$OUT" | grep -A1 "commentCreate calls carrying 'Not attempted'" | tail -1 | tr -dc '0-9')"
P="$(printf '%s\n' "$OUT" | sed -n 's/.*pages fired across 3 halted runs (deduped): \([0-9]*\).*/\1/p')"
if [ "${P:-x}" = "1" ] && [ "${N:-x}" = "1" ]; then
  ok "3 halted runs in one outage: 1 page and 1 'Not attempted' comment"
else
  bad "one outage writes one comment and one page" "pages=${P:-?} comments=${N:-?}: $(printf '%s' "$OUT" | tail -4 | tr '\n' '|')"
fi

echo "== a Codex outage halts and pages once"
OUT="$(run repro-codex-loop)"
P="$(printf '%s\n' "$OUT" | sed -n 's/^  pages fired: *\([0-9]*\).*/\1/p' | tail -1)"
if [ "${P:-x}" = "1" ]; then
  ok "a Codex outage over two ticks pages exactly once"
else
  bad "a Codex outage pages once" "pages=${P:-?}: $(printf '%s' "$OUT" | tail -4 | tr '\n' '|')"
fi

echo "== converge stays quiet on a machine outage when the issue already has a PR"
# PR #421 round 15, major: converge read env_halt only in its no-PR branch, so
# a halted rework round on an open PR paged exit 7 ("review produced no
# verdict") every tick, blaming the review for a machine outage.
OUT="$(run repro-converge-page-with-pr)"
RC="$(printf '%s\n' "$OUT" | sed -n 's/^--- converge rc=\([0-9]*\).*/\1/p' | tail -1)"
P="$(printf '%s\n' "$OUT" | sed -n 's/^--- page count: \([0-9]*\).*/\1/p' | tail -1)"
if [ "${P:-x}" = "0" ] && [ "${RC:-x}" = "9" ]; then
  ok "a halted rework round on an open PR exits 9 with no page"
else
  bad "converge reads env_halt before the PR logic" "rc=${RC:-?} pages=${P:-?}"
fi

echo "== a Codex outage does not walk the queue past --limit"
OUT="$(run repro-codex-limit)"
if grep -q "ASK-811 the second runner is unavailable" <<<"$OUT" \
   && ! grep -qE "ASK-81[23] the second runner is unavailable" <<<"$OUT"; then
  ok "--limit 1 on a 3-issue board stops at ASK-811"
else
  bad "the run stops at the first Codex refusal" "$(grep -E 'second runner' <<<"$OUT" | tr '\n' '|' | cut -c1-400)"
fi

echo "== converge does not page for a machine outage"
OUT="$(run repro-converge-page)"
P="$(printf '%s\n' "$OUT" | sed -n 's/^--- page count: \([0-9]*\).*/\1/p' | tail -1)"
if [ "${P:-x}" = "0" ]; then
  ok "converge after an env halt files no exit-7 ticket"
else
  bad "converge stays quiet on an env halt" "page count=${P:-?}"
fi

echo "== a Codex outage after an honest Codex refusal still pages"
# PR #421 round 2: the claim was released only on a committing Codex run, so an
# honest refusal left it held and the NEXT Codex outage paged nobody.
OUT="$(run repro-codex-mute)"
P1="$(printf '%s\n' "$OUT" | sed -n 's/^run1-codex-outage .*PAGES SENT=\([0-9]*\).*/\1/p')"
P3="$(printf '%s\n' "$OUT" | sed -n 's/^run3-codex-outage-again .*PAGES SENT=\([0-9]*\).*/\1/p')"
if [ "${P1:-x}" = "1" ] && [ "${P3:-x}" = "1" ]; then
  ok "two Codex outages around an honest refusal page twice, once each"
else
  bad "every Codex outage pages once" "run1=${P1:-?} run3=${P3:-?}"
fi

echo "== one Codex outage, one 'Not parked' comment"
# PR #421 round 4: the Codex branch deduped its page but posted its
# "Not parked: the second runner was unavailable" note on every tick.
OUT="$(run repro-codex-comment-spam)"
N="$(printf '%s\n' "$OUT" | sed -n "s/.*commentCreate calls carrying 'Not parked: the second runner was unavailable': \([0-9]*\).*/\1/p" | tail -1)"
P="$(printf '%s\n' "$OUT" | sed -n 's/.*pages fired across 3 ticks of ONE Codex outage (deduped): \([0-9]*\).*/\1/p' | tail -1)"
if [ "${N:-x}" = "1" ] && [ "${P:-x}" = "1" ]; then
  ok "3 ticks of one Codex outage: 1 page and 1 'Not parked' comment"
else
  bad "one Codex outage writes one comment" "pages=${P:-?} comments=${N:-?}"
fi

echo "== the CLI's hook-teardown lines never sink a real outage"
# Every hook event the noise rule names, at column 0 and indented by 3 (PR #421
# rounds 3 and 4: the widening had no case of its own, and the rule was
# column-0 anchored while the marker rule tolerates 3 spaces).
LIB="$HERE/../env-failure-lib.sh"
LIMIT="You've hit your weekly limit · resets Sep 22 at 2pm (America/Los_Angeles)"
MISSED=""
for ev in SessionEnd SessionStart Stop SubagentStop PreCompact Notification UserPromptSubmit PreToolUse PostToolUse; do
  for pad in "" "   "; do
    payload="$(printf '%s\n%s%s hook [node "x.mjs"] failed: Hook cancelled' "$LIMIT" "$pad" "$ev")"
    ( . "$LIB"; is_environmental "$payload" ) || MISSED="$MISSED ${ev}(pad=${#pad})"
  done
done
if [ -z "$MISSED" ]; then
  ok "a limit line beside any of 9 hook-teardown lines, at column 0 or indented 3, is an outage"
else
  bad "hook teardown noise is ignored for every event" "charged anyway:$MISSED"
fi
OUT="$(run repro-indent-noise)"
if grep -q "^3-space indent *-> OUTAGE" <<<"$OUT"; then
  ok "the reviewer's indented-teardown reproducer reads as an outage"
else
  bad "an indented teardown line does not sink an outage" "$(grep -E 'indent' <<<"$OUT" | tr '\n' '|')"
fi
# and the negative: a hook-failure line ALONE is not an outage (a timeout kill)
if ( . "$LIB"; is_environmental 'Stop hook [node "x.mjs"] failed: Hook cancelled' ); then
  bad "hook noise alone is not an outage" "a lone teardown line was excused"
else
  ok "a lone teardown line (a timeout kill) is still the issue's"
fi

echo "== a tick that never reached the runner does not re-arm the page"
# PR #421 round 5, major: the release after the loop was unconditional, so a
# tick that skipped every issue (attempt cap, --issue onto a capped issue)
# re-armed the page mid-outage.
OUT="$(run repro-unmute-on-skip)"
P1="$(printf '%s\n' "$OUT" | sed -n 's/^=== PAGES for ONE continuous outage: \([0-9]*\).*/\1/p')"
C1="$(printf '%s\n' "$OUT" | sed -n "s/^=== permanent Linear comments carrying 'Not attempted': \([0-9]*\).*/\1/p")"
P2="$(printf '%s\n' "$OUT" | sed -n 's/^=== PAGES across two outages split by a healthy tick: \([0-9]*\).*/\1/p')"
if [ "${P1:-x}" = "1" ] && [ "${C1:-x}" = "1" ]; then
  ok "a skipped tick inside one outage: still 1 page and 1 'Not attempted' comment"
else
  bad "a tick that never ran the runner keeps the outage claim" "pages=${P1:-?} comments=${C1:-?}"
fi
if [ "${P2:-x}" = "2" ]; then
  ok "a tick where the runner answers frees the claim: the next outage pages again"
else
  bad "the claim is released once the runner answers" "pages across two outages=${P2:-?} (1 = a permanent mute)"
fi

echo "== one outage, one pickup note"
# PR #421 round 6, major: the pickup note is posted before the runner is
# reached, so every tick of an outage wrote another "Attempt 1 of 3".
OUT="$(run repro-pickup-spam)"
N1="$(printf '%s\n' "$OUT" | sed -n "s/^=== 'Picked up' notes across 5 ticks of ONE outage: \([0-9]*\).*/\1/p")"
N2="$(printf '%s\n' "$OUT" | sed -n "s/^=== 'Picked up' notes after the runner answered twice: \([0-9]*\).*/\1/p")"
if [ "${N1:-x}" = "1" ]; then
  ok "5 ticks of one outage write 1 'Picked up' note"
else
  bad "one outage writes one pickup note" "notes=${N1:-?}"
fi
if [ "${N2:-x}" = "2" ] && grep -q 'Attempt 2 of 3' <<<"$OUT"; then
  ok "once the runner answers, the next attempt posts its own note (Attempt 2 of 3)"
else
  bad "the pickup note comes back after the outage" "notes=${N2:-?} (1 = muted for good)"
fi

echo "== one Codex outage, one pickup note"
# PR #421 round 7, major: Sana's healthy run cleared the mark every tick and
# the Codex outage branch never set it, so the note repeated per tick.
OUT="$(run repro-codex-pickup-spam)"
N="$(printf '%s\n' "$OUT" | sed -n 's/^--- commentCreate calls carrying "Picked up by the autonomous worker": \([0-9]*\).*/\1/p')"
if [ "${N:-x}" = "1" ]; then
  ok "3 ticks of one Codex outage write 1 'Picked up' note"
else
  bad "one Codex outage writes one pickup note" "notes=${N:-?}"
fi

echo "== every real Codex handoff, replayed"
# PR #421 round 8, major: `codex exec` prints a transcript, so the every-line
# rule never matched a real Codex outage and 17 issues were parked for one.
OUT="$(bash "$B/replay-codex-fixture.sh" 2>&1)"
O="$(printf '%s\n' "$OUT" | sed -n 's/^=== real Codex outages read as an outage: \([0-9]*\) of \([0-9]*\).*/\1\/\2/p')"
A="$(printf '%s\n' "$OUT" | sed -n 's/^=== real answered Codex runs read as an outage: \([0-9]*\) of \([0-9]*\).*/\1\/\2/p')"
if [ "${O:-x}" = "17/17" ] && [ "${A:-x}" = "0/27" ] && grep -q '^decision: codex_env_reason' <<<"$OUT"; then
  ok "17 of 17 real Codex outages read as outages, 0 of 27 answered runs misread"
else
  bad "the worker's Codex decision reads the real fixture" "outages=${O:-?} answered-misread=${A:-?} $(grep -E '^decision|mismatches' <<<"$OUT" | tr '\n' '|' | cut -c1-300)"
fi
# Two cases built from REAL lines, for the two halves the fixture alone cannot
# reach: an outage line ABOVE the end (echoed in the prompt) with the run ending
# in a real answer, and a real non-outage ERROR line after a real outage line.
LIB="$HERE/../env-failure-lib.sh"
FIXC="$HERE/fixtures/worker-env-halt/codex-outages-2026-09-23.json"
ADV="$(python3 - "$FIXC" <<'PYA'
import json, sys
fx = json.load(open(sys.argv[1]))
out = next(r for r in fx["runs"] if r["issue"] == "ASK-1126")["tail"][-1]
ans = next(r for r in fx["runs"] if r["label"] == "answered" and r["rc"] == 0)["tail"]
nf = next(l for r in fx["runs"] for l in r["error_lines"] if l.startswith("ERROR: file or directory not found"))
print(json.dumps({"echoed": "\n".join(fx["banner"] + [out] + ans), "mixed": "\n".join(fx["banner"] + [out, nf]),
                  "quoted": "\n".join(fx["banner"] + ["You are Codex.", "codex", ans[-1], out, "tokens used", "17,704"])}))
PYA
)"
ECHOED="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["echoed"])' "$ADV" 2>/dev/null)"
MIXED="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["mixed"])' "$ADV" 2>/dev/null)"
QUOTED="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["quoted"])' "$ADV" 2>/dev/null)"
# An empty case reads as "not an outage" and would pass the two checks below
# without testing anything (it did, once, while this was being written).
if [ -z "$ECHOED" ] || [ -z "$MIXED" ] || [ -z "$QUOTED" ]; then
  bad "the adversarial Codex cases could be built from the fixture" "a case came back empty; the checks below would pass vacuously"
fi
if ( . "$LIB"; codex_env_reason "$ECHOED" 1 >/dev/null ); then
  bad "an outage line above a real answer is not an outage" "an echoed limit line was read as the machine's"
else
  ok "a real outage line above a real answer (the echoed prompt) is not an outage"
fi
if ( . "$LIB"; codex_env_reason "$MIXED" 1 >/dev/null ); then
  bad "a real non-outage ERROR line at the end is the issue's" "a mixed ERROR block was read as an outage"
else
  ok "a real outage line followed by a real non-outage ERROR line is not an outage"
fi
# PR #421 round 9, minor: the model's own message ending in a quoted limit line,
# then Codex's token trailer. Under a "codex" header it is the model talking.
if ( . "$LIB"; codex_env_reason "$QUOTED" 1 >/dev/null ); then
  bad "a limit line in the model's own message is not an outage" "a quoted ERROR line under 'codex' was read as the machine's"
else
  ok "a real outage line quoted as the model's last message line is not an outage"
fi
REAL_OUT="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["mixed"].rsplit(chr(10),1)[0])' "$ADV")"
if ( . "$LIB"; codex_env_reason "$REAL_OUT" 0 >/dev/null ); then
  bad "a Codex run that exited 0 is not an outage" "rc=0 was read as an outage"
else
  ok "the same outage transcript with rc=0 is not an outage (every real one exited 1)"
fi

echo "== a real Codex outage through the real worker"
OUT="$(run repro-codex-real-outage)"
line() { printf '%s\n' "$OUT" | grep "^$1 "; }
field() { line "$1" | sed -n "s/.* $2=\([0-9]*\).*/\1/p"; }
if [ "$(field A-real-transcript parked)" = "0" ] && [ "$(field A-real-transcript unavailable)" = "1" ] \
   && [ "$(field A-real-transcript pages)" = "1" ] && [ "$(field A-real-transcript not-parked-notes)" = "1" ]; then
  ok "a real Codex outage transcript: not parked, 1 page, 1 'Not parked' note"
else
  bad "a real Codex outage is not parked" "$(line A-real-transcript)"
fi
# PR #421 round 13, major: without env_halt converge read refused_no_pr alone,
# logged a label never applied and paged exit 7 per issue. converge's own
# env_halt branch (exit 9, no page) is pinned by repro-converge-page above.
if [ "$(printf '%s\n' "$OUT" | sed -n 's/^A-real-transcript env_halt=\(.*\)$/\1/p')" = "True" ]; then
  ok "a Codex outage leaves env_halt, the mark converge reads to charge and page nothing"
else
  bad "a Codex outage marks the issue for converge" "$(printf '%s\n' "$OUT" | grep 'env_halt=' | tr '\n' ' ')"
fi
if [ "$(field B-claim-two-days-old pages)" = "1" ]; then
  ok "a Codex claim two days old expires: the next outage pages"
else
  bad "an old Codex claim expires" "$(line B-claim-two-days-old)"
fi
if [ "$(field C-claim-fresh pages)" = "0" ] && [ "$(field C-claim-fresh not-parked-notes)" = "1" ]; then
  ok "a fresh Codex claim still dedupes the page, and the issue still gets its own note"
else
  bad "a fresh claim dedupes the page but not the per-issue note" "$(line C-claim-fresh)"
fi

echo "== a Codex outage holds the issue instead of re-running Sana"
# PR #421 round 9, major: every tick re-ran a paid Sana session on the same
# unlabelled issue and posted another "Worker run completed".
OUT="$(run repro-codex-allcomments)"
num() { printf '%s\n' "$OUT" | sed -n "s/^=== $1: \([0-9A-Za-z]*\).*/\1/p" | head -1; }
S5="$(num 'Sana runs across 5 ticks of ONE Codex outage')"
C5="$(num "'Worker run completed' notes across those 5 ticks")"
MK="$(num 'held issue carries the machine-outage mark converge reads')"
S6="$(num 'Sana runs after the claim is a day old (tick 6)')"
if [ "${S5:-x}" = "1" ] && [ "${C5:-x}" = "1" ]; then
  ok "5 ticks of one Codex outage: 1 paid Sana run and 1 'Worker run completed'"
else
  bad "a Codex outage does not re-run Sana every tick" "sana-runs=${S5:-?} completed-notes=${C5:-?}"
fi
if [ "${MK:-x}" = "True" ]; then
  ok "the held issue carries the env_halt mark, so converge charges and pages nothing"
else
  bad "a held issue is marked for converge" "env_halt=${MK:-none}"
fi
if [ "${S6:-x}" = "2" ]; then
  ok "once the Codex claim is a day old, the held issue runs once more"
else
  bad "the hold lifts when the claim expires" "sana-runs after a day=${S6:-?} (1 = held for good)"
fi

echo "== a Codex claim with no epoch still ages out"
# PR #421 round 10, minor: a holder with no epoch (a failed write, a run killed
# between the mkdir and the write) never expired, so no Codex outage could page
# again and every held issue stayed held. Its age now falls back to the claim
# directory's mtime; a FRESH epochless claim (the racer's view of another run's
# mkdir) must still dedupe.
EPO="$(mktemp -d)"
age_dir() { python3 -c 'import os,sys,time; t=time.time()-int(sys.argv[2]); os.utime(sys.argv[1],(t,t))' "$1" "$2"; }
mkdir -p "$EPO/old/env-alert.claim" "$EPO/fresh/env-alert.claim"
age_dir "$EPO/old/env-alert.claim" 172800
OH=$( ( . "$LIB"; env_alert_held "$EPO/old" 86400 ) && echo yes || echo no)
OP=$( ( . "$LIB"; env_alert_claim "$EPO/old" 86400 ) && echo yes || echo no)
FH=$( ( . "$LIB"; env_alert_held "$EPO/fresh" 86400 ) && echo yes || echo no)
FP=$( ( . "$LIB"; env_alert_claim "$EPO/fresh" 86400 ) && echo yes || echo no)
if [ "$OH" = no ] && [ "$OP" = yes ]; then
  ok "an epochless claim two days old is no longer held and may page again"
else
  bad "an epochless claim ages out" "held=$OH may-page=$OP (yes/no = held and muted for good)"
fi
if [ "$FH" = yes ] && [ "$FP" = no ]; then
  ok "a fresh epochless claim still holds and still dedupes the page"
else
  bad "a fresh epochless claim is not taken over" "held=$FH may-page=$FP"
fi

echo "== round 11: a stale Codex note, a quoted 529, a takeover that nests"
# Minor: a note from an outage that ended held the issue through a later,
# unrelated Codex outage.
OUT="$(run repro-stale-codex-note)"
N="$(printf '%s\n' "$OUT" | sed -n 's/^=== Sana runs across a healthy tick and a tick during an unrelated Codex outage: \([0-9]*\).*/\1/p')"
if [ "${N:-x}" = "2" ]; then
  ok "a note from an ended Codex outage does not hold the issue through the next one"
else
  bad "a stale Codex note is dropped" "sana-runs=${N:-?} (1 = held by an old outage's note)"
fi
# PR #421 round 14, minor: the hold wrote the ledger above the dry-run gate.
if printf '%s\n' "$OUT" | grep -q '^=== dry run under a live claim wrote env_halt: no' \
   && printf '%s\n' "$OUT" | grep -q '^=== dry run with no claim cleared the note: no'; then
  ok "a dry run neither records env_halt for a held issue nor clears a stale note"
else
  bad "a dry run writes nothing to the ledger" "$(printf '%s\n' "$OUT" | grep '^=== dry run' | tr '\n' '|')"
fi
# Minor: the 529 marker ended in `.*`. The real line is from the captured
# fixture (limit-charges-2026-09-23.json, ASK-353/355); the prose variant keeps
# its first sentence and replaces the CLI's tail with an agent's.
R529="$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
o = next(f["agent_output"] for f in d["payload"]["failures"] if "529" in str(f["agent_output"]))
print(o if isinstance(o, str) else "\n".join(o))' "$HERE/fixtures/worker-env-halt/limit-charges-2026-09-23.json" 2>/dev/null)"
P529="${R529%% —*}, and I have since fixed the flaky test and pushed."
if [ -z "$R529" ]; then
  bad "the real 529 line is read from the fixture" "empty: the checks below would pass vacuously"
elif ( . "$LIB"; is_environmental "$R529" ) && ! ( . "$LIB"; is_environmental "$P529" ); then
  ok "the real 529 line is an outage; the same status followed by agent prose is not"
else
  bad "the 529 marker admits only the CLI's sentence" "real=$( ( . "$LIB"; is_environmental "$R529" ) && echo outage || echo issue) prose=$( ( . "$LIB"; is_environmental "$P529" ) && echo outage || echo issue)"
fi
# Nit: mv onto an existing .expired dir nested the claim inside it.
NST="$(mktemp -d)"
mkdir -p "$NST/env-alert.claim"
printf 'pid=1 claimed_at=x epoch=%s\n' "$(( $(date +%s) - 172800 ))" > "$NST/env-alert.claim/holder"
mkdir -p "$NST/env-alert.claim.expired.$$"
if ( . "$LIB"; env_alert_claim "$NST" 86400 ) && [ ! -d "$NST/env-alert.claim.expired.$$/env-alert.claim" ] \
   && grep -q "epoch=" "$NST/env-alert.claim/holder" 2>/dev/null; then
  ok "an expired claim is taken over by rename, never nested in a stale directory"
else
  bad "the takeover renames rather than nests" "$(find "$NST" | sed "s#$NST##" | tr '\n' ' ')"
fi

echo "== the main outage claim ages out after a day"
# PR #421 round 12, minor: released only by a run that hears the runner, the
# main claim outlived an outage whenever the queue stayed empty after it, and
# the next outage paged nobody (no launchd label carries exit 9 either).
OUT="$(run repro-main-claim-ages)"
PA="$(printf '%s\n' "$OUT" | sed -n 's/^=== pages for a new outage under a claim two days old: \([0-9]*\).*/\1/p')"
PB="$(printf '%s\n' "$OUT" | sed -n 's/^=== pages for the same outage under a claim two minutes old: \([0-9]*\).*/\1/p')"
if [ "${PA:-x}" = "1" ] && [ "${PB:-x}" = "0" ]; then
  ok "a main claim two days old pages the new outage; one two minutes old still dedupes"
else
  bad "the main claim ages out but still dedupes" "two-days-old=${PA:-?} two-minutes-old=${PB:-?}"
fi

echo "== the loser of a takeover race stays quiet"
# PR #421 round 13, minor: two runs read the old claim as expired; the winner
# made a fresh claim and the loser's mv took it, so both paged. Replayed
# deterministically: the loser's first age read is the stale "expired".
RST="$(mktemp -d)"
mkdir -p "$RST/env-alert.claim"
printf 'pid=WINNER claimed_at=now epoch=%s\n' "$(date +%s)" > "$RST/env-alert.claim/holder"
(
  . "$LIB"
  eval "$(declare -f _env_claim_older_than | sed '1s/_env_claim_older_than/_real_older_than/')"
  _env_claim_older_than() { if [ ! -e "$RST/.stale" ]; then : > "$RST/.stale"; return 0; fi; _real_older_than "$@"; }
  env_alert_claim "$RST" 86400
) 2>"$RST/.err" && LOSER=paged || LOSER=quiet
HOLDER="$(cut -d' ' -f1 "$RST/env-alert.claim/holder" 2>/dev/null)"
if [ "$LOSER" = quiet ] && [ "$HOLDER" = "pid=WINNER" ] && [ ! -s "$RST/.err" ]; then
  ok "the race loser does not page, leaves the winner's claim in place and prints nothing"
else
  bad "a takeover race pages once" "loser=$LOSER holder=${HOLDER:-none} stderr=$(head -c 200 "$RST/.err" 2>/dev/null)"
fi

echo "== the requeue tool reads a large merged worker without SIGPIPE"
# Found live on 2026-09-23, the morning ASK-2009 merged: redrive-unattempted.sh
# refused with "the environmental halt is not on origin/main yet" while main held
# it. Its check was `printf "$MERGED_WORKER" | grep -q` under `set -euo
# pipefail`: grep -q exits at the first match, printf takes SIGPIPE on a file
# past the pipe buffer, and the pipe returns 141. The real merged worker is that
# large. Both directions, on a throwaway repo whose main holds the real worker:
RQ="$(mktemp -d)"; RQS="$HERE/../redrive-unattempted.sh"
rq_repo() {  # rq_repo <dir> <worker-file>
  git init -q --bare "$1/origin.git"; git init -q "$1/skel"
  git -C "$1/skel" config user.email t@t; git -C "$1/skel" config user.name t
  mkdir -p "$1/skel/q-system/.q-system/scripts"; cp "$2" "$1/skel/q-system/.q-system/scripts/linear-worker.sh"
  git -C "$1/skel" add -A; git -C "$1/skel" commit -qm seed
  git -C "$1/skel" remote add origin "$1/origin.git"; git -C "$1/skel" push -q origin HEAD:main 2>/dev/null
  git -C "$1/skel" fetch -q origin 2>/dev/null
}
mkdir -p "$RQ/with" "$RQ/without" "$RQ/state"
rq_repo "$RQ/with" "$HERE/../linear-worker.sh"
grep -v 'is_environmental' "$HERE/../linear-worker.sh" > "$RQ/worker-without.sh"
rq_repo "$RQ/without" "$RQ/worker-without.sh"
KIPI_SKEL="$RQ/with/skel" KIPI_STATE_DIR="$RQ/state" bash "$RQS" --dry ASK-1 > "$RQ/with.out" 2>&1; RQ_WITH=$?
KIPI_SKEL="$RQ/without/skel" KIPI_STATE_DIR="$RQ/state" bash "$RQS" --dry ASK-1 > "$RQ/without.out" 2>&1; RQ_WITHOUT=$?
# The premise, checked on its own (PR #423 review, minor): the worker must be
# past the pipe buffer or the case below cannot tell the fix from the bug.
if [ "$(wc -c < "$HERE/../linear-worker.sh")" -gt 65536 ]; then
  ok "the real worker is past the pipe buffer ($(wc -c < "$HERE/../linear-worker.sh" | tr -d ' ') bytes), so this case can see the SIGPIPE"
else
  bad "the real worker is past the pipe buffer" "only $(wc -c < "$HERE/../linear-worker.sh" | tr -d ' ') bytes: grow the fixture, the case below proves nothing"
fi
if [ "$RQ_WITH" = "0" ] && grep -q "halt is present" "$RQ/with.out"; then
  ok "the real merged worker (past the pipe buffer) reads as having the halt"
else
  bad "the requeue tool sees the halt in a large merged worker" "rc=$RQ_WITH: $(head -2 "$RQ/with.out" | tr '\n' '|')"
fi
if [ "$RQ_WITHOUT" = "2" ] && grep -q "^REFUSED" "$RQ/without.out"; then
  ok "a merged worker without the halt is still refused (exit 2)"
else
  bad "the requeue tool still refuses a worker without the halt" "rc=$RQ_WITHOUT"
fi

echo "== the CLI's trust warning never sinks a real outage"
# PR #421 round 16, minor. The CLI prints "Ignoring N permissions.allow entries
# ... this workspace has not been trusted" as its own line (22 times in the
# worker log; ASK-757's window in limit-charges-2026-09-23.json carries one).
# Beside a real limit line it made is_environmental false and charged the
# attempt. Both lines below are real, read from the fixture; their pairing is
# constructed, since the 64 real outage windows carry the limit line bare.
TW="$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
for f in d["payload"]["failures"]:
    o = f["agent_output"]; o = o if isinstance(o, list) else o.split("\n")
    for l in o:
        if l.startswith("Ignoring ") and "has not been trusted" in l:
            print(l); raise SystemExit' "$HERE/fixtures/worker-env-halt/limit-charges-2026-09-23.json" 2>/dev/null)"
if [ -z "$TW" ]; then
  bad "the real trust warning is read from the fixture" "empty: the checks below would pass vacuously"
elif ( . "$LIB"; is_environmental "$(printf '%s\n%s' "$TW" "$LIMIT")" ) \
     && ! ( . "$LIB"; is_environmental "$TW" ); then
  ok "a real limit line beside the CLI's trust warning is an outage; the warning alone is not"
else
  bad "the trust warning is noise, not speech" "limit+warning=$( ( . "$LIB"; is_environmental "$(printf '%s\n%s' "$TW" "$LIMIT")" ) && echo outage || echo charged) warning-alone=$( ( . "$LIB"; is_environmental "$TW" ) && echo outage || echo issue)"
fi

echo "== Opus stands in when Codex is down"
# Founder, 2026-09-23: "you dont need codex credits, you can use opus as a
# fallback". A real Codex outage transcript (fixture run ASK-1126) through the
# real worker, with the Opus stand-in stubbed in three modes.
OUT="$(run repro-opus-fallback)"
row() { printf '%s\n' "$OUT" | grep "^$1 "; }
if [ "$(row commit)" = "commit opus-calls=1 continued=1 parked=0 held=0" ]; then
  ok "Codex down, Opus does the work: the issue is continued, not held or parked"
else
  bad "Opus continues the work when Codex is down" "$(row commit)"
fi
if [ "$(row refuse)" = "refuse opus-calls=1 continued=0 parked=1 held=0" ]; then
  ok "Codex down, Opus refuses on capability: parked with both refusals"
else
  bad "an Opus capability refusal parks" "$(row refuse)"
fi
if [ "$(row limit)" = "limit opus-calls=1 continued=0 parked=0 held=1" ]; then
  ok "Codex down and Opus out of quota too: only then is the issue held"
else
  bad "both runners down is the only hold" "$(row limit)"
fi

echo "== a dead run's per-pid files are swept"
OUT="$(run repro-leak)"
A="$(printf '%s\n' "$OUT" | sed -n 's/^after: *\([0-9]*\) orphan.*/\1/p')"
BEF="$(printf '%s\n' "$OUT" | sed -n 's/^before: *\([0-9]*\) orphan.*/\1/p')"
if [ "${BEF:-x}" = "2" ] && [ "${A:-x}" = "0" ]; then
  ok "2 planted orphans from dead pids are gone after one healthy run"
else
  bad "orphans are swept" "before=${BEF:-?} after=${A:-?}"
fi

echo
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
