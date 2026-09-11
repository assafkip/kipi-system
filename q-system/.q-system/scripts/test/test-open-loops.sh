#!/usr/bin/env bash
# AUDHD anti-drop: open-loops.py surfaces every parked item. Pairs with open-loops.json registry.
# spillover-skip -- every "deferred" string in this file is a TEST FIXTURE fed to the
# surfacer, not a real parked item. Capturing them would put fake work in the ledger.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
S="$ROOT/q-system/.q-system/scripts/open-loops.py"
fail() { echo "FAIL: $1" >&2; exit 1; }

# No fixture in this file may reach the Linear API. The pointer cache refresh is
# report-mode-only and already opt-out; pinning it OFF here keeps the suite
# deterministic and free, and keeps a real API key out of a test's blast radius.
export KIPI_OPEN_LOOPS_OFFLINE=1

# Linear cache records carry an age, so fixtures date theirs explicitly rather
# than relying on whatever "no stamp" happens to mean (see sections 11/11c).
stamp() {  # $1 = days ago
  python3 -c 'import datetime,sys;print((datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=float(sys.argv[1]))).strftime("%Y-%m-%dT%H:%M:%SZ"))' "$1"
}
NOW="$(stamp 0)"; OLD="$(stamp 30)"

# 1. report mode runs clean against the live registry (STRUCTURAL check only).
# Was: grep for two hardcoded loop titles ("cc-spex closeout-gate PR", ...).
# That pinned live, legitimately-changing registry content into a test — the
# moment a loop closed, the test went red with nothing broken (caught on the
# suite's first-ever gated run, 2026-07-23, prd-silent-absence-capability-gate).
# Content assertions live in section 3 against a fixture registry.
OUT="$(CLAUDE_PROJECT_DIR="$ROOT" python3 "$S" --report 2>&1)" || fail "report mode exited non-zero: $OUT"

# 3. fixture: open surfaced, closed excluded
T="$(mktemp -d)"; mkdir -p "$T/q-system/memory" "$T/.prd-os/findings"
cat > "$T/q-system/memory/open-loops.json" <<'JSON'
{"loops":[
 {"id":"a","title":"OPEN LOOP A","next_action":"do A","needs_founder":true,"status":"open"},
 {"id":"b","title":"CLOSED LOOP B","next_action":"do B","status":"closed"}
]}
JSON

# 2. hook mode emits valid SessionStart additionalContext JSON — against the
# FIXTURE registry, not live state. With zero live open loops the script
# correctly emits nothing ("never blocks on empty", section 5), so the live
# version of this assertion failed in 9 fleet instances on the first full
# sweep (2026-07-23) while passing in the skeleton, which had 6 open loops.
# Same live-data disease as old section 1, second occurrence.
JOUT="$(CLAUDE_PROJECT_DIR="$T" python3 "$S" 2>&1)"
echo "$JOUT" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['hookSpecificOutput']['hookEventName']=='SessionStart'; assert 'Open loops' in d['hookSpecificOutput']['additionalContext']" \
  || fail "hook mode JSON invalid: $JOUT"
OUT3="$(CLAUDE_PROJECT_DIR="$T" python3 "$S" --report 2>&1)"
echo "$OUT3" | grep -q "OPEN LOOP A" || fail "open loop A not surfaced: $OUT3"
echo "$OUT3" | grep -q "CLOSED LOOP B" && fail "closed loop B wrongly surfaced: $OUT3" || true

# 4. deferred findings: genuine future-work surfaced, 'folded into' bookkeeping excluded
printf '%s\n' \
 '{"id":"f1","disposition":"deferred","body":"provenance ledger missing","rationale":"deferred to v2; documented residual risk"}' \
 '{"id":"f2","disposition":"deferred","body":"bookkeeping item","rationale":"Folded into issue X; refinement, not a standalone work item"}' \
 '{"id":"f3","disposition":"accepted","body":"not deferred","rationale":"fixed"}' \
 > "$T/.prd-os/findings/p.jsonl"
OUT4="$(CLAUDE_PROJECT_DIR="$T" python3 "$S" --report 2>&1)"
echo "$OUT4" | grep -qi "provenance ledger" || fail "genuine deferred (v2) not surfaced: $OUT4"
echo "$OUT4" | grep -qi "bookkeeping item" && fail "folded-into finding wrongly surfaced: $OUT4" || true

# 5. empty (no registry, no findings) -> never blocks, hook mode emits nothing, exit 0
T2="$(mktemp -d)"; mkdir -p "$T2/q-system"
CLAUDE_PROJECT_DIR="$T2" python3 "$S" >/dev/null 2>&1 && rc=0 || rc=$?
[ "${rc:-1}" -eq 0 ] || fail "empty case did not exit 0 (got ${rc:-1})"
EOUT="$(CLAUDE_PROJECT_DIR="$T2" python3 "$S" 2>&1)"
[ -z "$EOUT" ] || fail "empty case should emit nothing in hook mode, got: $EOUT"

# 6. zero silent-fall: a plainly-worded deferred finding (no future-work keyword,
#    not folded bookkeeping) must NOT vanish -> it lands in the catch-all line.
T3="$(mktemp -d)"; mkdir -p "$T3/q-system/memory" "$T3/.prd-os/findings"
echo '{"loops":[]}' > "$T3/q-system/memory/open-loops.json"
printf '%s\n' \
 '{"id":"g1","disposition":"deferred","body":"plainly parked","rationale":"park this for now, we still need to build it but not in this issue"}' \
 > "$T3/.prd-os/findings/q.jsonl"
OUT6="$(CLAUDE_PROJECT_DIR="$T3" python3 "$S" --report 2>&1)"
echo "$OUT6" | grep -qi "not auto-classified" || fail "plainly-worded deferred not caught by catch-all (silent fall): $OUT6"

# 7. already-captured: a plainly-worded deferred finding that the spillover ledger
#    ALREADY holds (auto-created id `defer-<prd>-<finding-id>`, no-orphan-findings)
#    is not in limbo -- the gate keeps it RED until resolved. Counting it in the
#    catch-all re-surfaced tracked work as untracked every session (2026-08-14:
#    3 deterministic-reading findings, 2 of them already RESOLVED, nagged forever).
T4="$(mktemp -d)"; mkdir -p "$T4/q-system/memory" "$T4/.prd-os/findings"
echo '{"loops":[]}' > "$T4/q-system/memory/open-loops.json"
printf '%s\n' \
 '{"id":"finding-3","disposition":"deferred","body":"captured already","rationale":"park this for now, real and out of scope here"}' \
 '{"id":"finding-9","disposition":"deferred","body":"not captured","rationale":"park this for now, real and out of scope here"}' \
 > "$T4/.prd-os/findings/prd-demo-2026-08-14-findings.jsonl"
printf '%s\n' \
 '{"id":"defer-prd-demo-2026-08-14-finding-3","source":"prd-demo-2026-08-14","description":"captured already","status":"open"}' \
 > "$T4/.prd-os/spillover.jsonl"
OUT7="$(CLAUDE_PROJECT_DIR="$T4" python3 "$S" --report 2>&1)"
echo "$OUT7" | grep -q "1 deferred prd-os finding(s) not auto-classified" \
  || fail "expected exactly 1 uncaptured finding in the catch-all (spillover-captured one must be excluded): $OUT7"

# 7b. mutation guard: with NO ledger the same fixture must count BOTH, so section 7
#     can fail for the reason it claims (a ledger-blind counter says 2).
rm "$T4/.prd-os/spillover.jsonl"
OUT7B="$(CLAUDE_PROJECT_DIR="$T4" python3 "$S" --report 2>&1)"
echo "$OUT7B" | grep -q "2 deferred prd-os finding(s) not auto-classified" \
  || fail "ledger-absent case must count both findings (check is decorative otherwise): $OUT7B"

# ---------------------------------------------------------------------------
# Pointer-style deferrals (ASK-759). A rationale that NAMES its owner is not a
# keyword guess: the named tracker row's state is the answer. Before this, such a
# rationale fell to FUTURE_WORK_RE keyword luck and usually landed in the
# uncountable "N not auto-classified" bucket that no action clears (sp-30a109ad,
# hit 2026-07-27 on findings 3/7/9).
# ---------------------------------------------------------------------------

mk_ptr_fixture() {  # $1=dir  $2=prd status line ('' = no spec file at all)
  mkdir -p "$1/q-system/memory" "$1/.prd-os/findings" "$1/.prd-os/prds"
  echo '{"loops":[]}' > "$1/q-system/memory/open-loops.json"
  printf '%s\n' \
   '{"id":"p1","disposition":"deferred","body":"pointer parked item","rationale":"owned by prd-pointer-demo-2026-08-14, not this issue"}' \
   > "$1/.prd-os/findings/r.jsonl"
  if [ -n "$2" ]; then
    printf -- '---\nid: prd-pointer-demo-2026-08-14\nstatus: %s\n---\n' "$2" \
      > "$1/.prd-os/prds/prd-pointer-demo-2026-08-14.md"
  fi
}

# 8. pointer target resolvable and CLOSED (archived PRD) -> dropped from the
#    count AND not surfaced. The work is done; re-reporting it is the nag.
T5="$(mktemp -d)"; mk_ptr_fixture "$T5" archived
OUT8="$(CLAUDE_PROJECT_DIR="$T5" python3 "$S" --report 2>&1)"
echo "$OUT8" | grep -qi "not auto-classified" && fail "closed pointer target still counted in catch-all: $OUT8" || true
echo "$OUT8" | grep -qi "pointer parked item" && fail "closed pointer target wrongly surfaced: $OUT8" || true

# 8b. mutation guard: same finding, NO spec on disk -> unresolvable -> it must
#     stay in the catch-all. Proves 8 drops on resolved state, not on the mere
#     presence of a pointer (a pointer-swallowing bug would pass 8 and fail here).
T5B="$(mktemp -d)"; mk_ptr_fixture "$T5B" ""
OUT8B="$(CLAUDE_PROJECT_DIR="$T5B" python3 "$S" --report 2>&1)"
echo "$OUT8B" | grep -q "1 deferred prd-os finding(s) not auto-classified" \
  || fail "unresolvable pointer must fail OPEN into the catch-all, never drop: $OUT8B"

# 9. pointer target resolvable and OPEN -> a real loop line carrying the id, not
#    a nameless number. The id is what makes the line actionable.
T6="$(mktemp -d)"; mk_ptr_fixture "$T6" approved
OUT9="$(CLAUDE_PROJECT_DIR="$T6" python3 "$S" --report 2>&1)"
echo "$OUT9" | grep -qi "pointer parked item" || fail "open pointer target not surfaced as a loop: $OUT9"
echo "$OUT9" | grep -q "prd-pointer-demo-2026-08-14" || fail "surfaced loop does not carry the pointer id: $OUT9"
echo "$OUT9" | grep -qi "not auto-classified" && fail "open pointer target also counted in catch-all: $OUT9" || true

# 9b. mutation guard: flip that same spec to archived -> the line disappears.
#     Proves 9 reads the target's STATE; a presence-only check stays green in 9
#     and goes red here.
printf -- '---\nid: prd-pointer-demo-2026-08-14\nstatus: archived\n---\n' \
  > "$T6/.prd-os/prds/prd-pointer-demo-2026-08-14.md"
OUT9B="$(CLAUDE_PROJECT_DIR="$T6" python3 "$S" --report 2>&1)"
echo "$OUT9B" | grep -qi "pointer parked item" && fail "archived target still surfaced (state ignored): $OUT9B" || true

# 10. Linear pointers resolve from the on-disk cache only -- SessionStart never
#     makes a network call. `folded into ASK-...` is deliberate: FOLDED_RE used to
#     silently drop it, so an OPEN owner vanished. Pointer resolution outranks it.
T7="$(mktemp -d)"; mkdir -p "$T7/q-system/memory" "$T7/q-system/output" "$T7/.prd-os/findings"
echo '{"loops":[]}' > "$T7/q-system/memory/open-loops.json"
printf '%s\n' \
 '{"id":"l1","disposition":"deferred","body":"linear open owner","rationale":"folded into ASK-419"}' \
 '{"id":"l2","disposition":"deferred","body":"linear closed owner","rationale":"owned by ASK-420"}' \
 > "$T7/.prd-os/findings/s.jsonl"
printf '%s' \
 "{\"issues\":{\"ASK-419\":{\"state\":\"open\",\"fetched_at\":\"$NOW\"},\"ASK-420\":{\"state\":\"closed\",\"fetched_at\":\"$NOW\"}}}" \
 > "$T7/q-system/output/linear-issue-cache.json"
OUT10="$(CLAUDE_PROJECT_DIR="$T7" python3 "$S" --report 2>&1)"
echo "$OUT10" | grep -q "ASK-419" || fail "open Linear pointer not surfaced with its id: $OUT10"
echo "$OUT10" | grep -qi "linear closed owner" && fail "closed Linear pointer wrongly surfaced: $OUT10" || true
echo "$OUT10" | grep -qi "not auto-classified" && fail "cached Linear pointers still counted in catch-all: $OUT10" || true

# 10b. mutation guard: delete the cache -> BOTH become unresolvable and must land
#      in the catch-all. A cache-blind resolver that guessed would stay green in
#      10 and go red here.
rm "$T7/q-system/output/linear-issue-cache.json"
OUT10B="$(CLAUDE_PROJECT_DIR="$T7" python3 "$S" --report 2>&1)"
echo "$OUT10B" | grep -q "2 deferred prd-os finding(s) not auto-classified" \
  || fail "cache-absent Linear pointers must both fail open into the catch-all: $OUT10B"

# ---------------------------------------------------------------------------
# Cache freshness (ASK-759 round-1 review finding). A cached Linear state is a
# SNAPSHOT, not a fact: an issue closes, or a closed one is REOPENED, and the
# cache still says whatever it said the first time. `refresh_linear_cache` used
# to skip every id already present, so an id's FIRST answer was also its LAST,
# forever. A stale "closed" is the dangerous half -- it silently DROPS a live
# parked item, the one outcome this whole script exists to prevent.
# ---------------------------------------------------------------------------

mk_linear_fixture() {  # $1=dir  $2=cache JSON body
  mkdir -p "$1/q-system/memory" "$1/q-system/output" "$1/.prd-os/findings"
  echo '{"loops":[]}' > "$1/q-system/memory/open-loops.json"
  printf '%s\n' \
   '{"id":"l1","disposition":"deferred","body":"linear open owner","rationale":"folded into ASK-419"}' \
   '{"id":"l2","disposition":"deferred","body":"linear closed owner","rationale":"owned by ASK-420"}' \
   > "$1/.prd-os/findings/s.jsonl"
  printf '%s' "$2" > "$1/q-system/output/linear-issue-cache.json"
}
# 11. STALE entries expire to unresolvable -> BOTH land in the catch-all. The
#     closed one must not be dropped: a month-old "closed" cannot outvote a
#     parked item that may have been reopened since.
T8="$(mktemp -d)"; mk_linear_fixture "$T8" \
  "{\"issues\":{\"ASK-419\":{\"state\":\"open\",\"fetched_at\":\"$OLD\"},\"ASK-420\":{\"state\":\"closed\",\"fetched_at\":\"$OLD\"}}}"
OUT11="$(CLAUDE_PROJECT_DIR="$T8" python3 "$S" --report 2>&1)"
echo "$OUT11" | grep -q "2 deferred prd-os finding(s) not auto-classified" \
  || fail "stale cache entries must expire to unresolvable and fail open into the catch-all: $OUT11"

# 11b. mutation guard: the SAME fixture with fresh timestamps resolves normally
#      (open surfaces with its id, closed drops). Proves 11 expires on the
#      TIMESTAMP; a resolver that had simply stopped reading the cache would pass
#      11 and go red here.
T9="$(mktemp -d)"; mk_linear_fixture "$T9" \
  "{\"issues\":{\"ASK-419\":{\"state\":\"open\",\"fetched_at\":\"$NOW\"},\"ASK-420\":{\"state\":\"closed\",\"fetched_at\":\"$NOW\"}}}"
OUT11B="$(CLAUDE_PROJECT_DIR="$T9" python3 "$S" --report 2>&1)"
echo "$OUT11B" | grep -q "ASK-419" || fail "fresh open pointer not surfaced with its id: $OUT11B"
echo "$OUT11B" | grep -qi "linear closed owner" && fail "fresh closed pointer wrongly surfaced: $OUT11B" || true
echo "$OUT11B" | grep -qi "not auto-classified" && fail "fresh pointers still counted in catch-all: $OUT11B" || true

# 11c. a legacy record (no `fetched_at` -- the shape written before this fix) has
#      no provable age, so it is stale. Fail open; the refresh below re-answers it.
T10="$(mktemp -d)"; mk_linear_fixture "$T10" \
  '{"issues":{"ASK-419":{"state":"open"},"ASK-420":{"state":"closed"}}}'
OUT11C="$(CLAUDE_PROJECT_DIR="$T10" python3 "$S" --report 2>&1)"
echo "$OUT11C" | grep -q "2 deferred prd-os finding(s) not auto-classified" \
  || fail "undated legacy cache records must be treated as stale, not trusted forever: $OUT11C"

# 12. the online half: refresh re-asks for a STALE id and does NOT re-ask for a
#     FRESH one. Expiring an entry offline is useless if nothing ever re-fetches
#     it, and re-fetching everything would put an API call in front of every
#     --report. The fetcher is STUBBED here, so no network is touched;
#     KIPI_OPEN_LOOPS_OFFLINE is dropped only for this block and only because the
#     stub has already replaced the call that switch guards.
T11="$(mktemp -d)"; mk_linear_fixture "$T11" \
  "{\"issues\":{\"ASK-419\":{\"state\":\"open\",\"fetched_at\":\"$OLD\"},\"ASK-420\":{\"state\":\"closed\",\"fetched_at\":\"$NOW\"}}}"
ASKED="$(env -u KIPI_OPEN_LOOPS_OFFLINE python3 - "$S" "$T11" <<'PY'
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("_ol_under_test", sys.argv[1])
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
asked = []
mod._fetch_linear_states = lambda ids: (asked.extend(ids) or {i: "open" for i in ids})
mod.refresh_linear_cache(Path(sys.argv[2]) / "q-system", {"ASK-419", "ASK-420"})
print(",".join(sorted(asked)))
PY
)"
[ "$ASKED" = "ASK-419" ] || fail "refresh must re-ask the stale id and only it (asked: '$ASKED')"

# 12b. and the refreshed answer must be usable offline on the next run, which is
#      only true if the write path stamps `fetched_at`. ASK-419 now resolves OPEN
#      (surfaced with its id) and ASK-420 is still fresh-closed (dropped), so the
#      catch-all is empty.
OUT12B="$(CLAUDE_PROJECT_DIR="$T11" python3 "$S" --report 2>&1)"
echo "$OUT12B" | grep -q "ASK-419" || fail "refreshed id unusable offline (write path must stamp fetched_at): $OUT12B"
echo "$OUT12B" | grep -qi "not auto-classified" && fail "refreshed id still in the catch-all: $OUT12B" || true

echo "PASS: surfaces registry loops (incl seeded OSS PRs) + genuine deferred findings, excludes closed + folded bookkeeping + spillover-captured, resolves pointer-style deferrals (closed drops, open surfaces with its id, unresolvable fails open), expires stale Linear cache entries and re-asks only those, catch-all guarantees zero silent-fall, valid SessionStart JSON, never blocks on empty"
