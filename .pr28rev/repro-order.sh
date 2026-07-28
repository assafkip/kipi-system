#!/usr/bin/env bash
# Does the PR's ordering guard actually catch the regression it names?
# Test lines under review (test-severity-floor.sh, ASK-216 section M):
#   SHA_LINE="$(grep -n 'headRefOid' "$REVIEWER" | head -1 | cut -d: -f1)"
#   RUN_LINE="$(grep -n 'run_bounded "\$TIMEOUT_SECONDS"' "$REVIEWER" | head -1 | cut -d: -f1)"
#   [ "$SHA_LINE" -lt "$RUN_LINE" ] || fail "captured AFTER the reviewer runs"
set -uo pipefail
SRC="/Users/assafkipnis/projects/kipi-system/.pr28rev/scripts/pr-review-agent.sh"
W="$(mktemp -d)"; BAD="$W/pr-review-agent.sh"

# THE REGRESSION: move the real read to AFTER the reviewer dispatch, i.e. the
# record now claims a commit the reviewer may never have seen. Leave behind the
# kind of comment this repo writes on every line it touches.
python3 - "$SRC" "$BAD" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
L = open(src).read().split("\n")
read_i = next(i for i,l in enumerate(L) if l.startswith("PR_META="))
block = L[read_i:read_i+4]                      # PR_META=, ||, HEAD_SHA=, PR_TITLE=
del L[read_i:read_i+4]
L.insert(read_i, '# headRefOid is captured further down, after the reviewer returns.')
L.insert(read_i+1, 'PR_TITLE="$(gh pr view "$PR" --json title -q .title 2>/dev/null)"')
run_i = next(i for i,l in enumerate(L) if 'run_bounded "$TIMEOUT_SECONDS"' in l)
end = next(i for i,l in enumerate(L) if i > run_i and l == "fi")
L[end+1:end+1] = block                          # sha read now happens AFTER the review
open(dst,"w").write("\n".join(L))
PY

REVIEWER="$BAD"
SHA_LINE="$(grep -n 'headRefOid' "$REVIEWER" | head -1 | cut -d: -f1)"
RUN_LINE="$(grep -n 'run_bounded "\$TIMEOUT_SECONDS"' "$REVIEWER" | head -1 | cut -d: -f1)"
echo "grep 'headRefOid' first hit  -> line $SHA_LINE : $(sed -n "${SHA_LINE}p" "$REVIEWER")"
echo "real PR_META= read is now at -> line $(grep -n '^PR_META=' "$REVIEWER" | cut -d: -f1)"
echo "run_bounded dispatch         -> line $RUN_LINE"
if [ "$SHA_LINE" -lt "$RUN_LINE" ]; then
  echo "GUARD SAYS: ok  (the PR's assertion PASSES)"
else
  echo "GUARD SAYS: fail"
fi
echo
echo "REPRO HIT: the sha is now read AFTER the reviewer ran, which is exactly the"
echo "           regression the assertion names -- and the assertion is green."
rm -rf "$W"
