#!/usr/bin/env bash
# ASK-2541: every claude review run writes ONE usage-ledger row.
#
# THE DEFECT. On 2026-10-06 the fleet ran 35 PR reviews and the usage ledger held
# zero rows for any of them, so the founder's usage view could not see review
# spend at all. pr-review-agent.sh called `claude -p` with plain text output and
# nothing parsed the usage the CLI reports.
#
# WHAT THIS PINS, against the shipping script (copied, not rewritten):
#   1. a claude review run appends one row: bot pr-review, item <slug>#<pr>,
#      the model, the tokens and the cost from the CLI's own json document;
#   2. the verdict is still read correctly from the json output (the meter
#      must hand the FINDINGS reader the same text a plain -p call printed);
#   3. fail-open: with the meter module missing the review still lands, and
#      the named meter log says why there is no row.
#
# Isolation: HOME, KIPI_STATE_DIR, the ledger, the meter log, the git repo, `gh`
# and `claude` are fixtures under a mktemp dir. No model is spent.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SRC_DIR="$ROOT/q-system/.q-system/scripts"
PLUG_DIR="$ROOT/plugins/kipi-core/voiceloop"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$SRC_DIR/pr-review-agent.sh" ] || fail "pr-review-agent.sh missing at $SRC_DIR"
REAL_GIT="$(command -v git)" || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_TARGET_REPO KIPI_REVIEW_ENGINE KIPI_USAGE_LEDGER KIPI_USAGE_METER_LOG KIPI_USAGE_METER_PY 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB"

mkdir -p "$WORK/skel/q-system/.q-system/scripts" "$WORK/skel/plugins/kipi-core/voiceloop"
git init -q "$WORK/skel"
echo "code" > "$WORK/skel/FILE.txt"
cp "$SRC_DIR/pr-review-agent.sh" "$SRC_DIR/pr-verdict-lib.sh" "$SRC_DIR/repo-slug-lib.sh" \
   "$SRC_DIR/env-failure-lib.sh" "$SRC_DIR/reviewer-token-lib.sh" \
   "$WORK/skel/q-system/.q-system/scripts/"
cp "$PLUG_DIR/usage_meter.py" "$PLUG_DIR/usage_ledger.py" "$PLUG_DIR/model_prices.py" \
   "$WORK/skel/plugins/kipi-core/voiceloop/"
G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "control code"
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "https://github.com/example-org/example-repo.git"
AGENT="$WORK/skel/q-system/.q-system/scripts/pr-review-agent.sh"
SHA="$(git -C "$WORK/skel" rev-parse HEAD)"

cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
case "\$*" in
  *"pr view"*"headRefOid"*) printf '%s\t%s\n' "$SHA" "a PR title" ;;
  *"pr diff"*)              echo "diff --git a/FILE.txt b/FILE.txt" ;;
  *"pr comment"*)           echo "https://github.com/example-org/example-repo/pull/7#issuecomment-1" ;;
  *"api"*)                  echo '{}' ;;
esac
exit 0
EOF
chmod +x "$STUB/gh"

# The claude stub answers the way the real CLI does under --output-format json
# (one result document), and as plain text otherwise, so a script that stops
# asking for json is caught by the row assertion, not hidden by the stub.
cat > "$STUB/claude" <<'EOF'
#!/usr/bin/env bash
REVIEW=$'VERDICT: APPROVE\nFINDINGS:\nseverity|file|line|what\nnit|FILE.txt|1|trailing whitespace\nEND FINDINGS'
case " $* " in
  *" --output-format json "*)
    python3 -c 'import json,sys; print(json.dumps({"type":"result","subtype":"success","is_error":False,"result":sys.argv[1],"num_turns":3,"total_cost_usd":0.4321,"duration_ms":1200,"session_id":"s-1","modelUsage":{"claude-opus-5":{"inputTokens":11,"outputTokens":222,"cacheReadInputTokens":3333,"cacheCreationInputTokens":444,"costUSD":0.4321}}}))' "$REVIEW" ;;
  *) printf '%s\n' "$REVIEW" ;;
esac
exit 0
EOF
chmod +x "$STUB/claude"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub"

run_reviewer() {  # run_reviewer <out-file> <tag>
  local out="$1" tag="$2"
  ( cd "$WORK/skel" \
    && HOME="$WORK/home-$tag" KIPI_STATE_DIR="$WORK/state-$tag" KIPI_NOTIFY="/usr/bin/true" \
       KIPI_USAGE_LEDGER="$WORK/ledger-$tag.jsonl" KIPI_USAGE_METER_LOG="$WORK/meter-$tag.log" \
       bash "$AGENT" 7 ) >"$out" 2>&1
}

# --- CASE 1: a claude review run writes exactly one row ---------------------
run_reviewer "$WORK/run.out" a
grep -q '^  verdict: APPROVE' "$WORK/run.out" \
  || { cat "$WORK/run.out" >&2; fail "the review never reached an APPROVE verdict (json output broke the FINDINGS reader?)"; }
ok "verdict still extracted from json-mode output"

[ -f "$WORK/ledger-a.jsonl" ] || { cat "$WORK/run.out" >&2; fail "no usage-ledger row after a claude review run"; }
python3 - "$WORK/ledger-a.jsonl" <<'PY' || fail "ledger row has the wrong shape"
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
assert len(rows) == 1, f"expected 1 row, got {len(rows)}"
r = rows[0]
assert r["bot"] == "pr-review" and r["job"] == "pr-review", r
assert r["item"] == "example-org/example-repo#7", r["item"]
assert r["kind"] == "run" and r["rc"] == 0, r
assert r["total_cost_usd"] == 0.4321, r
assert r["tokens_out"] == 222 and r["tokens_cache_read"] == 3333 and r["tokens_in"] == 11 + 3333 + 444, r
assert r["model"], r
PY
ok "one row: bot pr-review, item slug#pr, tokens and cost from the CLI document"

RF="$(sed -n 's/.*review written: //p' "$WORK/run.out" | head -1)"
[ -n "$RF" ] && [ -s "$RF" ] || fail "control: the run did not report a review file"
ls "$RF".json "$RF".stderr >/dev/null 2>&1 \
  && fail "the raw json / stderr side files were left beside the review"
ok "no side files left in the review dir"

# --- CASE 2: fail-open with the meter missing -------------------------------
rm -f "$WORK/skel/plugins/kipi-core/voiceloop/usage_meter.py"
run_reviewer "$WORK/run-b.out" b
grep -q '^  verdict: APPROVE' "$WORK/run-b.out" \
  || { cat "$WORK/run-b.out" >&2; fail "a missing meter cost the review its verdict"; }
[ -s "$WORK/ledger-b.jsonl" ] && fail "a row appeared with the meter missing; this case is not exercising the fallback"
grep -q 'meter unavailable' "$WORK/meter-b.log" 2>/dev/null \
  || fail "meter missing but the named meter log does not say so"
ok "fail-open: meter missing, review verdict intact, reason in the meter log"

echo "PASS ($PASS checks)"
