#!/usr/bin/env bash
# Reproducer for sp-8379cd52: the verdict record could not distinguish a review
# CODEX wrote from one the Opus fallback wrote during a codex outage.
#
# Pairs with: the reviewed_by + degraded fields written by pr-review-agent.sh.
#
# WHY THIS IS THE PROOF THAT MATTERS. The human-facing surfaces were already
# honest -- the commit-status description and the Linear comment both say
# "DEGRADED (codex down, Opus fallback)" out loud. The MACHINE-READABLE record is
# the one converge.sh:36 and linear-worker.sh:76 actually gate on, and it said
# `"engine": "codex"` for a review codex never produced. Measured 2026-08-02
# during a real out-of-credits outage: PR #66 and #67 both carried
# `engine: codex` on Opus-written reviews. Truthful prose over a lying record is
# worse than an obvious gap, because the wrong reader trusts it silently.
#
# THE TEST DRIVES THE SHIPPED BLOCK, NOT A COPY OF IT. A hand-rolled
# reimplementation of the record writer would assert my model of the code and
# stay green while the real script drifted -- the exact fixture defect this
# fleet's reviewer prompt is calibrated against. So the block is EXTRACTED from
# pr-review-agent.sh at run time and executed. If someone edits the writer, this
# test follows it.
#
# THE FAIL-SAFE DIRECTION. Every record written before this change lacks the key
# entirely, and a missing key is UNKNOWN, never "independent". Case 3 is that
# assertion and it is the one a careless consumer would break.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$(cd "$HERE/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

export KIPI_NOTIFY=/usr/bin/true

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

AGENT="$SCRIPTS/pr-review-agent.sh"
[ -f "$AGENT" ] || { echo "missing $AGENT"; exit 1; }

# ---------------------------------------------------------------------------
# Pull the shipped derivation + record writer out of the real script.
# ---------------------------------------------------------------------------
extract_writer() { awk '/^REVIEWED_BY="\$CODEX_MODEL"$/,/^PY$/' "$AGENT"; }

WRITER="$WORK/writer.sh"
extract_writer > "$WRITER"

# NEGATIVE SELF-TEST ON THE EXTRACTION. An awk range that silently matches
# nothing yields an empty file, every case below then "passes" against no code
# at all, and the suite reports green about a check it never ran. Prove the
# extraction landed BEFORE trusting anything it produces.
echo "== 0. the extraction actually captured the shipped writer =="
if [ ! -s "$WRITER" ]; then
  bad "extraction produced an EMPTY block -- the anchors in $AGENT moved; every case below would be vacuous"
  echo; echo "-------- $PASS passed, $FAIL failed --------"; exit 1
fi
if grep -q 'json.dump' "$WRITER" && grep -q 'REVIEWED_BY=' "$WRITER"; then
  ok "extracted $(wc -l < "$WRITER" | tr -d ' ') lines carrying both the derivation and the json writer"
else
  bad "extracted block is missing the derivation or the json writer -- anchors are wrong"
  echo; echo "-------- $PASS passed, $FAIL failed --------"; exit 1
fi

# ---------------------------------------------------------------------------
# Run the extracted writer with a controlled environment.
# ---------------------------------------------------------------------------
run_writer() {  # run_writer <engine> <degraded> <verdict-dir> [writer-file]
  local engine="$1" degraded="$2" vdir="$3" writer="${4:-$WRITER}"
  mkdir -p "$vdir"
  (
    set +u
    TS() { echo "2026-08-02T16:00:00Z"; }
    CODEX_MODEL="gpt-5.6-sol"; CLAUDE_MODEL="claude-opus-5"
    ENGINE="$engine"; DEGRADED="$degraded"
    PR=900; ISSUE="ASK-900"; VERDICT="REQUEST CHANGES"
    REVIEW="$vdir/pr-900-review.md"; STATED_VERDICT="REQUEST CHANGES"
    DERIVED_VERDICT="REQUEST CHANGES"; ROUND=1
    HEAD_SHA="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    VERDICT_DIR="$vdir"; INVOKER="worker"
    # Set by the `if review_is_usable` line that sits just ABOVE the extraction
    # anchor, so the extracted block reads it but never computes it. Supplied
    # here rather than left to `set +u`: an empty positional would still fill the
    # slot and keep the arg count right, so the writer would not fail -- it would
    # silently record `usable: false` for every case and nobody would notice the
    # test had stopped matching the shipped arg list.
    REVIEW_USABLE=1
    . "$writer"
  ) >/dev/null 2>&1
}

# THE CONSUMER. This is the point of the whole fix: something downstream reads
# the record and answers "is this a second lab's opinion?" Three-valued on
# purpose -- forcing a binary would make a legacy record lie in one direction or
# the other, and "I cannot tell" is the honest answer for a record written
# before the field existed.
consumer_says() {  # consumer_says <record.json> -> independent|degraded|unknown
  python3 - "$1" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
if "degraded" not in r:
    print("unknown")
else:
    print("degraded" if r["degraded"] else "independent")
PY
}

echo
echo "== 1. THE DEFECT: a fallback review must name Opus and mark degraded =="
D1="$WORK/case1"; run_writer codex 1 "$D1"
REC1="$D1/pr-900.verdict.json"
if [ ! -f "$REC1" ]; then
  bad "no record written at all for the degraded case"
else
  RB="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("reviewed_by",""))' "$REC1")"
  if [ "$RB" = "claude-opus-5" ]; then
    ok "the fallback record names the model that actually wrote it (reviewed_by=$RB)"
  else
    bad "THE DEFECT: fallback record says reviewed_by='$RB'; codex never saw this code"
  fi
  case "$(consumer_says "$REC1")" in
    degraded) ok "a consumer reads the fallback record as DEGRADED" ;;
    *)        bad "THE DEFECT: a consumer reads the Opus fallback as an independent codex review" ;;
  esac
fi

echo
echo "== 2. a real codex review does NOT carry the degraded flag =="
D2="$WORK/case2"; run_writer codex 0 "$D2"
REC2="$D2/pr-900.verdict.json"
if [ ! -f "$REC2" ]; then
  bad "no record written for the healthy codex case"
else
  RB2="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("reviewed_by",""))' "$REC2")"
  if [ "$RB2" = "gpt-5.6-sol" ]; then
    ok "a healthy codex review names the codex model (reviewed_by=$RB2)"
  else
    bad "a healthy codex review says reviewed_by='$RB2'"
  fi
  case "$(consumer_says "$REC2")" in
    independent) ok "a consumer reads a real codex review as INDEPENDENT" ;;
    *)           bad "a healthy codex review was not readable as independent" ;;
  esac
fi

echo
echo "== 2b. a DELIBERATE claude run names Opus (the ENGINE=claude branch) =="
# COVERAGE HOLE, found by the degraded reviewer's mutation campaign on PR #114.
# Cases 1 and 2 both drive ENGINE=codex (degraded=1 and degraded=0), so NOTHING
# exercised `[ "$ENGINE" = "claude" ] && REVIEWED_BY="$CLAUDE_MODEL"`. Deleting
# that line left this suite 8/8 green while it printed the message claiming the
# record distinguishes the two writers.
#
# It is a LIVE path, not a hypothetical: `--engine claude` is accepted at the
# arg parser, and with KIPI_REVIEW_PRIMARY_ENGINE=claude that engine writes the
# ROOT gating record. With the line gone, a deliberate Opus review would be
# recorded as authored by the codex model -- the exact defect this file exists
# to kill, surviving inside it.
D2B="$WORK/case2b"; run_writer claude 0 "$D2B"
REC2B="$D2B/pr-900.verdict.json"
if [ ! -f "$REC2B" ]; then
  bad "no record written for the deliberate claude-engine case"
else
  RB2B="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("reviewed_by",""))' "$REC2B")"
  if [ "$RB2B" = "claude-opus-5" ]; then
    ok "a deliberate --engine claude run names the claude model (reviewed_by=$RB2B)"
  else
    bad "THE DEFECT: --engine claude recorded reviewed_by='$RB2B'; codex never ran"
  fi
fi

echo
echo "== 3. THE FAIL-SAFE: a legacy record with no key is UNKNOWN, not independent =="
D3="$WORK/case3"; mkdir -p "$D3"
cat > "$D3/pr-900.verdict.json" <<'JSON'
{"pr":900,"issue":"ASK-900","verdict":"APPROVE","engine":"codex","invoker":"worker",
 "round":1,"head_sha":"cafebabecafebabe","ts":"2026-07-30T00:00:00Z"}
JSON
case "$(consumer_says "$D3/pr-900.verdict.json")" in
  unknown)     ok "a pre-change record reads as unknown, so it cannot pass as independence proof" ;;
  independent) bad "THE DEFECT: a legacy record with no degraded key was claimed as an independent review" ;;
  *)           bad "a legacy record was misread as degraded (wrong direction, but still wrong)" ;;
esac

echo
echo "== 4. MUTATION: drop the degraded key and case 1 must go RED =="
# A test that cannot fail is decoration. Break the field the fix added and prove
# the degraded case stops being detectable.
MUT="$WORK/writer-mutant.sh"
sed '/"degraded": degraded == "1",/d' "$WRITER" > "$MUT"
# VALIDATE THE MUTANT APPLIED. A sed that matched nothing leaves the file
# identical, the case below still passes, and the run reports a FALSE KILL --
# claiming mutation coverage it never had.
if ! diff -q "$WRITER" "$MUT" >/dev/null 2>&1 && [ -s "$MUT" ]; then
  ok "mutant differs from the shipped writer (the degraded key was actually removed)"
  D4="$WORK/case4"; run_writer codex 1 "$D4" "$MUT"
  REC4="$D4/pr-900.verdict.json"
  if [ ! -f "$REC4" ]; then
    bad "mutant wrote no record at all -- that is a syntax break, not a live mutation test"
  elif [ "$(consumer_says "$REC4")" = "degraded" ]; then
    bad "THE MUTANT SURVIVED: the consumer still reported degraded without the key, so case 1 proves nothing"
  else
    ok "mutant KILLED: without the degraded key the consumer can no longer see the outage"
  fi
else
  bad "mutation did not apply (sed matched nothing or emptied the file); case 1's coverage is UNPROVEN"
fi

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: the verdict record distinguishes an Opus fallback from a real codex review"
