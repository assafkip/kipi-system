#!/usr/bin/env bash
# A reviewer run that writes no verdict does not spend a review round (ASK-5847).
#
# WHY THIS EXISTS. Measured 2026-11-27 on ASK-5802: the reviewer's claude call was
# refused with rc=5 ("every known key's cycle credit is spent"), wrote no verdict
# record, and still left its partial review .md beside the real ones. review_round
# counts those .md files, so a credit outage walked the PR toward the 3-round cap
# with nothing reviewed.
#
# WHAT IS PINNED, through the real pr-review-agent.sh with a stubbed claude:
#   1. a refused run (claude exits 5) writes no verdict record and leaves no
#      round-counted .md (its output is kept as .no-verdict);
#   2. the next, real review is still round 1 and writes the verdict;
#   3. a real review after that is round 2 (a verdict does advance the count).
# No network, no real claude, no live state: HOME and KIPI_STATE_DIR are temp dirs.
set -uo pipefail
export KIPI_FLEET_API_KEYS=0

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SRC_DIR="$ROOT/q-system/.q-system/scripts"
PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$SRC_DIR/pr-review-agent.sh" ] || fail "pr-review-agent.sh missing at $SRC_DIR"
REAL_GIT="$(command -v git)" || fail "git not on PATH"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
unset KIPI_TARGET_REPO KIPI_REVIEW_ENGINE KIPI_REVIEW_PRIMARY_ENGINE KIPI_REVIEW_MAX_ROUNDS 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB"
mkdir -p "$WORK/skel/q-system/.q-system/scripts"
git init -q "$WORK/skel"
echo "base" > "$WORK/skel/FILE.txt"
cp "$SRC_DIR/pr-review-agent.sh" "$SRC_DIR/pr-verdict-lib.sh" "$SRC_DIR/repo-slug-lib.sh" \
   "$SRC_DIR/env-failure-lib.sh" "$SRC_DIR/reviewer-token-lib.sh" "$SRC_DIR/review-lean-lib.sh" \
   "$WORK/skel/q-system/.q-system/scripts/"
G -C "$WORK/skel" add -A; G -C "$WORK/skel" commit -q -m "control code"
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "https://github.com/example-owner/example-repo.git"
git -C "$WORK/skel" checkout -q -b pr-branch
AGENT="$WORK/skel/q-system/.q-system/scripts/pr-review-agent.sh"
echo "WORK_LINE" >> "$WORK/skel/FILE.txt"
G -C "$WORK/skel" commit -q -am "the work"
git -C "$WORK/skel" rev-parse HEAD > "$WORK/head"

cat > "$STUB/gh" <<EOF
case "\$*" in
  *"pr view"*"headRefOid"*) printf '%s\t%s\n' "\$(cat "$WORK/head")" "a PR title" ;;
  *"pr view"*"baseRefName"*) echo main ;;
  *"pr diff"*)              echo "+WORK_LINE" ;;
  *"pr comment"*)           echo "https://github.com/example-owner/example-repo/pull/1#issuecomment-1" ;;
  *"api"*)                  echo '{}' ;;
esac
exit 0
EOF
chmod +x "$STUB/gh"
# MODE file: "refuse" makes claude exit 5 the way fleet-claude.sh does on spent credit.
MODE="$WORK/mode"
cat > "$STUB/claude" <<EOF
if [ "\$(cat "$MODE")" = "refuse" ]; then
  echo "fleet-claude: every known key's cycle credit is spent" >&2
  exit 5
fi
cat <<'REVIEW'
VERDICT: APPROVE
FINDINGS:
END FINDINGS
REVIEW
exit 0
EOF
chmod +x "$STUB/claude"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/codex"; chmod +x "$STUB/codex"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/notify"; chmod +x "$STUB/notify"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub"

run_reviewer() {  # run_reviewer <out-file>
  ( cd "$WORK/skel" \
    && HOME="$WORK/home" KIPI_STATE_DIR="$WORK/state" KIPI_NOTIFY="$STUB/notify" \
       KIPI_REVIEW_MAX_ROUNDS=20 bash "$AGENT" 1 --engine claude --post ) >"$1" 2>&1
  echo $? > "$1.rc"
}
REVIEWS="$WORK/home/.config/kipi/pr-reviews"
REC="$REVIEWS/example-owner_example-repo__pr-1.verdict.json"
counted_md() { find "$REVIEWS" -maxdepth 1 -type f -name '*pr-1-*.md' 2>/dev/null | grep -c . ; }

echo refuse > "$MODE"
run_reviewer "$WORK/r0.out"
[ "$(cat "$WORK/r0.out.rc")" != "0" ] || fail "the refused run exited 0; the stub did not refuse:
$(tail -15 "$WORK/r0.out")"
grep -q "round: 1" "$WORK/r0.out" || fail "the refused run never reached the round line, so the case is vacuous:
$(tail -15 "$WORK/r0.out")"
[ -e "$REC" ] && fail "the refused run wrote a verdict record"
[ "$(counted_md)" = "0" ] || fail "THE DEFECT: the refused run left $(counted_md) round-counted review file(s):
$(ls -la "$REVIEWS")"
ls "$REVIEWS" | grep -q 'no-verdict$' || fail "the refused run's output was not kept as .no-verdict:
$(ls -la "$REVIEWS")"
ok "a refused reviewer (rc=$(cat "$WORK/r0.out.rc")) wrote no verdict and spent no round"
sleep 1

echo approve > "$MODE"
run_reviewer "$WORK/r1.out"
[ "$(cat "$WORK/r1.out.rc")" = "0" ] || fail "the real review exited $(cat "$WORK/r1.out.rc"):
$(tail -15 "$WORK/r1.out")"
grep -q "round: 1" "$WORK/r1.out" || fail "the first real review is not round 1:
$(grep 'round:' "$WORK/r1.out")"
[ -s "$REC" ] || fail "the real review wrote no verdict record"
ok "the first real review after a refusal is round 1 and writes the verdict"
sleep 1

run_reviewer "$WORK/r2.out"
grep -q "round: 2" "$WORK/r2.out" || fail "a review after a verdict did not advance to round 2:
$(grep 'round:' "$WORK/r2.out")"
ok "a written verdict advances the round"

echo "PASS: $PASS cases"
