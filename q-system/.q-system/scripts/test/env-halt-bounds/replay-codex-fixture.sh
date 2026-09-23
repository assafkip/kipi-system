#!/usr/bin/env bash
# Every real worker handoff to Codex, replayed through the worker's own Codex
# outage decision (PR #421 round 8, ASK-2009).
#
# The fixture is 44 real blocks from the worker log: 17 where Codex was out of
# credits or at its usage limit (every one of them was parked blocked:capability
# for a condition of the machine) and 27 where Codex answered. Each replay is a
# whole transcript: the real banner, the worker's own opening prompt line, then
# the run's real last lines, fed with the rc the worker logged (1 when it logged
# none, which is the stricter test for an answered run).
#
# The decision under test is codex_env_reason, the function linear-worker.sh
# calls. Before it existed the worker called is_environmental directly, so that
# is what this falls back to: the red number is the real pre-fix behaviour, not
# a "command not found".
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HERE/../../env-failure-lib.sh"
FIX="$HERE/../fixtures/worker-env-halt/codex-outages-2026-09-23.json"
# shellcheck disable=SC1090
. "$LIB"
if declare -F codex_env_reason >/dev/null; then
  DECIDE=codex_env_reason; echo "decision: codex_env_reason"
else
  DECIDE=""; echo "decision: is_environmental (pre-fix)"
fi
decide() {
  if [ -n "$DECIDE" ]; then "$DECIDE" "$1" "$2" >/dev/null; else is_environmental "$1"; fi
}

WORK="$(mktemp -d)"
trap 'find "$WORK" -type f -delete 2>/dev/null; rmdir "$WORK" 2>/dev/null' EXIT
python3 - "$FIX" "$WORK" <<'PY'
import json, sys, os
fx = json.load(open(sys.argv[1])); out = sys.argv[2]
for i, r in enumerate(fx["runs"]):
    text = fx["banner"] + ["You are Codex, the SECOND runner on Linear issue %s." % r["issue"]] + r["tail"]
    open(os.path.join(out, "%02d.out" % i), "w").write("\n".join(text) + "\n")
    open(os.path.join(out, "%02d.meta" % i), "w").write("%s %s %s\n" % (r["label"], r["rc"] if r["rc"] is not None else 1, r["issue"]))
PY

OUT_HIT=0; OUT_N=0; ANS_HIT=0; ANS_N=0; MISS=""
for m in "$WORK"/*.meta; do
  read -r label rc issue < "$m"
  body="$(cat "${m%.meta}.out")"
  if decide "$body" "$rc"; then got=outage; else got=answered; fi
  if [ "$label" = outage ]; then
    OUT_N=$((OUT_N+1)); [ "$got" = outage ] && OUT_HIT=$((OUT_HIT+1))
  else
    ANS_N=$((ANS_N+1)); [ "$got" = outage ] && ANS_HIT=$((ANS_HIT+1))
  fi
  [ "$got" = "$label" ] || MISS="$MISS $issue($label->$got)"
done
echo "=== real Codex outages read as an outage: $OUT_HIT of $OUT_N"
echo "=== real answered Codex runs read as an outage: $ANS_HIT of $ANS_N"
echo "--- mismatches:${MISS:- none}"
