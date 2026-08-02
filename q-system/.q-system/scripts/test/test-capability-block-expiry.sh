#!/usr/bin/env bash
# Reproducer + guard for capability_block_expiry.py (ASK-288).
#
# THE DEFECT, STATED AS A TEST: a `blocked:capability` label is a point-in-time
# verdict about the environment that nothing re-tests, so an issue whose blocker
# was fixed stays parked forever. ASK-140 is the live instance -- blocked on "no
# safe write route into .claude/", which shipped on 2026-08-01.
#
# The fixture is CAPTURED FROM THE PRODUCER (the live Linear API, 2026-08-02),
# not hand-authored. A hand-written idea of what a blocked issue looks like tests
# my assumption about the shape, not the shape. That has shipped two green-but-
# wrong tests here before.
#
# Nothing in this file touches Linear or the real .claude/. Probes resolve
# against a temp root via --root, and issues come from --fixture; both are the
# test-isolation seams the engine exposes for exactly this reason.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$HERE/../capability_block_expiry.py"
FIXTURE="$HERE/fixtures/blocked-capability-live-2026-08-02.json"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf 'PASS  %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf 'FAIL  %s\n    %s\n' "$1" "${2:-}"; }

# Assert a verdict line for one issue. Uses grep on a captured file rather than a
# pipeline: `| grep -q` under pipefail returns 141 (SIGPIPE) and reads as a
# production failure, which has cost real debugging time in this repo before.
expect() { # <label> <fixture> <root> <issue> <verdict>
  local out="$TMP/out.$$"
  python3 "$ENGINE" --fixture "$2" --root "$3" --repo-project kipi-system >"$out" 2>&1
  if grep -Eq "^$5 +$4:" "$out"; then ok "$1"; else
    bad "$1" "wanted '$5 $4', got: $(grep -E "$4" "$out" || echo '(no line for it)')"; fi
}

# A root WITHOUT the capability, and one WITH it. The probe under test names the
# apply route that unstuck ASK-140 in real life.
CAP_REL="q-system/.q-system/scripts/apply-claude-changes.sh"
mkdir -p "$TMP/absent" "$TMP/present/$(dirname "$CAP_REL")"
: >"$TMP/present/$CAP_REL"

# --- derive the probed variants FROM the real fixture -----------------------
python3 - "$FIXTURE" "$TMP" <<'PY'
import json, sys, copy
src, tmp = sys.argv[1], sys.argv[2]
data = json.load(open(src))
by = {i["identifier"]: i for i in data["issues"]}

_clock = [0]


def with_comment(issue, body):
    # STRICTLY INCREASING TIMESTAMPS. The first version stamped every synthetic
    # comment with one fixed time, so "is this fence older than that refusal?"
    # compared equal and the staleness check could never fire -- a fixture that
    # made the test unable to see the bug it was written for.
    _clock[0] += 1
    c = copy.deepcopy(issue)
    c["comments"]["nodes"].append(
        {"body": body, "createdAt": "2026-08-02T12:%02d:00Z" % _clock[0]})
    return c


def with_label(issue, name):
    c = copy.deepcopy(issue)
    c["labels"]["nodes"].append({"name": name})
    return c

probe = "```kipi-capability-probe\nfile:q-system/.q-system/scripts/apply-claude-changes.sh\n```"
spent = "```kipi-capability-probe\nlegacy-reoffer-consumed\n```"
bogus = "```kipi-capability-probe\nfile:q-system/.q-system/scripts/does-not-exist.sh\n```"
# A kind the vocabulary does not define. Distinct from `bogus` above, which is a
# KNOWN kind pointing at a missing target -- an earlier version of this file
# conflated the two, so the unknown-kind branch was never exercised and a mutant
# that made it fail OPEN survived. Two different failures need two fixtures.
unknown = "```kipi-capability-probe\nsomeday:a-kind-nobody-defined\n```"

json.dump({"issues": [with_comment(by["ASK-140"], probe)]}, open(tmp + "/probed.json", "w"))
json.dump({"issues": [with_comment(by["ASK-140"], spent)]}, open(tmp + "/spent.json", "w"))
json.dump({"issues": [with_comment(by["ASK-140"], bogus)]}, open(tmp + "/bogus.json", "w"))
json.dump({"issues": [with_comment(by["ASK-140"], unknown)]}, open(tmp + "/unknown.json", "w"))

# --- the codex-found MAJOR (PR #69 review, 2026-08-02) --------------------
# An issue that once recorded a PASSING probe, then was re-blocked by a refusal
# that recorded NO probe. The old fence must not answer for the new block: the
# capability that is missing NOW is what decides workability. Getting this wrong
# re-expires a real block on every worker tick, burning one runner dispatch per
# cycle forever -- the exact opposite of the anti-thrash property this file
# claims. Both comment shapes below come from the real producers (the worker's
# refusal note and cbe.expire_note), not from my idea of them.
noprobe_fence = "```kipi-capability-probe\nno-probe\n```"
reblock = ("**Blocked on a missing capability, not on scope.**\n\n"
           "**No probe was recorded**, so this block cannot be re-tested mechanically.")

# (a) the new worker always emits a fence, so the newest fence says `no-probe`.
# The re-offer is ALREADY SPENT here, which is what makes this discriminating:
# under the old code the spent marker only gated the no-tokens path, so the stale
# passing fence supplied tokens and it expired anyway -- forever.
stale_fenced = with_label(
    with_comment(with_comment(by["ASK-140"], probe), reblock + "\n\n" + noprobe_fence),
    "capability:reoffered")
json.dump({"issues": [stale_fenced]}, open(tmp + "/stale-fenced.json", "w"))

# (b) the backstop: a refusal that emitted NO fence at all (old data, or any
# producer that forgets). The newest FENCE is still the old passing one, so
# fence-ordering alone cannot see this. Recency of the refusal is what does.
stale_unfenced = with_label(with_comment(with_comment(by["ASK-140"], probe), reblock),
                            "capability:reoffered")
json.dump({"issues": [stale_unfenced]}, open(tmp + "/stale-unfenced.json", "w"))

# (d) THE SUPERSESSION DEFECT IN ISOLATION, no unknown-token luck involved.
# Newest fence carries only the consumed marker, so it filters to zero tokens.
# The old engine treated "this fence has no tokens" as "keep looking backwards"
# and reached the older PASSING probe -> EXPIRE. The newest fence is the only one
# entitled to answer, and here it says "nothing recorded".
json.dump({"issues": [with_comment(with_comment(by["ASK-140"], probe), spent)]},
          open(tmp + "/marker-over-passing.json", "w"))

# (c) the bound itself: an unverifiable block that has NOT spent its re-offer
# gets exactly one, and the same issue with the marker gets none. This is the
# guarantee stated in the module docstring, asserted in both directions.
json.dump({"issues": [with_comment(by["ASK-140"], reblock + "\n\n" + noprobe_fence)]},
          open(tmp + "/noprobe-fresh.json", "w"))
json.dump({"issues": [with_label(with_comment(by["ASK-140"], reblock + "\n\n" + noprobe_fence),
                                 "capability:reoffered")]},
          open(tmp + "/noprobe-spent.json", "w"))
PY

# --- 1. the defect is real: ASK-140 is not pickable as it stands -------------
python3 - "$FIXTURE" "$HERE/.." <<'PY'
import json, sys, importlib.util, pathlib
spec = importlib.util.spec_from_file_location("lp", pathlib.Path(sys.argv[2]) / "linear_pick.py")
lp = importlib.util.module_from_spec(spec); spec.loader.exec_module(lp)
i = {x["identifier"]: x for x in json.load(open(sys.argv[1]))["issues"]}["ASK-140"]
assert not lp.ready(i, "kipi-system"), "ASK-140 should NOT be pickable while blocked"

# BOTH conditions are load-bearing. Dropping only the label leaves it at
# `started`, which ready() also refuses -- an expiry that stopped at the label
# would report success and change nothing observable.
no_label = json.loads(json.dumps(i))
no_label["labels"]["nodes"] = [l for l in no_label["labels"]["nodes"]
                               if l["name"] != "blocked:capability"]
assert not lp.ready(no_label, "kipi-system"), \
    "label-only removal must NOT be enough: ASK-140 is 'started'"

unblocked = json.loads(json.dumps(no_label))
unblocked["state"] = {"name": "Todo", "type": "unstarted"}
assert lp.ready(unblocked, "kipi-system"), "label removed + state restored must be pickable"
print("PASS  picker: blocked -> not ready; label-only -> still not ready; both -> ready")
PY
[ $? -eq 0 ] && PASS=$((PASS+1)) || bad "picker predicate contract" "see above"

# --- 2. the expiry verdicts --------------------------------------------------
expect "legacy block (no probe) spends its one re-offer"   "$FIXTURE"      "$TMP/absent"  ASK-140 EXPIRE
expect "closed issue keeps its label but is skipped"       "$FIXTURE"      "$TMP/absent"  ASK-281 SKIP
expect "probe still absent -> HOLD, no pick burned"        "$TMP/probed.json" "$TMP/absent"  ASK-140 HOLD
expect "probe now present -> EXPIRE"                       "$TMP/probed.json" "$TMP/present" ASK-140 EXPIRE
expect "spent re-offer is never re-spent"                  "$TMP/spent.json"  "$TMP/absent"  ASK-140 HOLD
expect "known kind, target absent -> HOLD"                 "$TMP/bogus.json"  "$TMP/present" ASK-140 HOLD
expect "UNKNOWN probe kind fails CLOSED"                   "$TMP/unknown.json" "$TMP/present" ASK-140 HOLD
expect "a newer no-probe fence supersedes an older PASSING probe" "$TMP/stale-fenced.json"   "$TMP/present" ASK-140 HOLD
expect "a newer refusal with NO fence supersedes it too"          "$TMP/stale-unfenced.json" "$TMP/present" ASK-140 HOLD
expect "marker-only newest fence never defers to an older passing one" "$TMP/marker-over-passing.json" "$TMP/present" ASK-140 HOLD
expect "unverifiable + re-offer unspent -> exactly one"           "$TMP/noprobe-fresh.json"  "$TMP/present" ASK-140 EXPIRE
expect "unverifiable + re-offer spent -> never again"             "$TMP/noprobe-spent.json"  "$TMP/present" ASK-140 HOLD

# --- 3. a probe is never executed -------------------------------------------
# The refusal text is agent-authored. If a probe were shelled out, this would
# create the file. Persisting agent-authored shell for later unattended
# execution is the path ASK-282 closed; this asserts it stayed closed.
python3 - "$FIXTURE" "$TMP" <<'PY'
import json, sys, copy
data = json.load(open(sys.argv[1]))
i = copy.deepcopy({x["identifier"]: x for x in data["issues"]}["ASK-140"])
i["comments"]["nodes"].append({
    "body": "```kipi-capability-probe\nfile:x; touch " + sys.argv[2] + "/PWNED\n```",
    "createdAt": "2026-08-02T12:00:00Z"})
json.dump({"issues": [i]}, open(sys.argv[2] + "/inject.json", "w"))
PY
python3 "$ENGINE" --fixture "$TMP/inject.json" --root "$TMP/present" --repo-project kipi-system >/dev/null 2>&1
if [ -e "$TMP/PWNED" ]; then bad "probe must never execute" "the injected command RAN"
else ok "probe text is never executed"; fi

# --- 5. producer and consumer agree on the no-probe token --------------------
# The whole supersession fix rests on the WORKER emitting a fence the ENGINE
# recognises. Asserting the engine's constant alone would pass while the worker
# emitted something else entirely -- two halves of one contract, tested apart.
# This reads the literal out of linear-worker.sh and runs it through the engine.
python3 - "$HERE/../linear-worker.sh" "$HERE/.." <<'PY'
import importlib.util, pathlib, re, sys
worker = open(sys.argv[1]).read()
spec = importlib.util.spec_from_file_location(
    "cbe", pathlib.Path(sys.argv[2]) / "capability_block_expiry.py")
cbe = importlib.util.module_from_spec(spec); spec.loader.exec_module(cbe)

# The worker writes the fence inside a double-quoted bash string, so each
# backtick is BACKSLASH-ESCAPED on disk (`\`\`\``). Matching a bare ``` finds
# nothing and the assert below would report "emits no fence" for a worker that
# emits one correctly -- a false alarm about the producer, from the consumer.
fences = re.findall(r"(?:\\?`){3}kipi-capability-probe[ \t]*\n(.*?)(?:\\?`){3}",
                    worker, re.DOTALL)
emitted = [f.strip() for f in fences if "$" not in f]
assert emitted, "linear-worker.sh emits no literal probe fence for the no-probe case"
assert cbe.NO_PROBE in emitted, (
    "worker emits %r but the engine's NO_PROBE is %r" % (emitted, cbe.NO_PROBE))

body = "Blocked on a missing capability\n\n```kipi-capability-probe\n%s\n```" % cbe.NO_PROBE
tokens, _ = cbe.parse_probes([{"body": body, "createdAt": "2026-08-02T12:00:00Z"}])
assert tokens == [], "engine must read the worker's no-probe fence as unverifiable, got %r" % tokens
print("PASS  worker's no-probe fence round-trips into the engine as unverifiable")

# THE EXPIRY MUST NOT MANUFACTURE A PASSING FENCE. The first version re-posted
# the probes it had just re-run, putting a PASSING fence at the top of history --
# so the next real block inherited it and re-expired forever. The expiry was
# building the stale fence that broke it. Probes are recorded by REFUSALS only.
note = cbe.expire_note("every recorded probe now passes: file:x", ["file:x"])
tokens, _ = cbe.parse_probes([{"body": note, "createdAt": "2026-08-02T13:00:00Z"}])
assert tokens == [], "expire_note must not emit a re-readable probe fence, got %r" % tokens
print("PASS  an expiry note never re-posts a passing probe fence")
PY
[ $? -eq 0 ] && PASS=$((PASS+1)) || bad "producer/consumer agree on no-probe" "see above"

# --- 4. --apply is required before anything writes ---------------------------
OUT="$TMP/dry.txt"
python3 "$ENGINE" --fixture "$FIXTURE" --root "$TMP/absent" --repo-project kipi-system >"$OUT" 2>&1
if grep -q "would expire" "$OUT"; then ok "default run is report-only"
else bad "default run is report-only" "$(cat "$OUT")"; fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
