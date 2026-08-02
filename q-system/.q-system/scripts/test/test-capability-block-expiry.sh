#!/usr/bin/env bash
# Reproducer + guard for capability_block_expiry.py (ASK-284).
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

def with_comment(issue, body):
    c = copy.deepcopy(issue)
    c["comments"]["nodes"].append({"body": body, "createdAt": "2026-08-02T12:00:00Z"})
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

# --- 4. --apply is required before anything writes ---------------------------
OUT="$TMP/dry.txt"
python3 "$ENGINE" --fixture "$FIXTURE" --root "$TMP/absent" --repo-project kipi-system >"$OUT" 2>&1
if grep -q "would expire" "$OUT"; then ok "default run is report-only"
else bad "default run is report-only" "$(cat "$OUT")"; fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
