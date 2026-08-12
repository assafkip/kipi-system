#!/usr/bin/env bash
# Pairs with q-system/.q-system/scripts/will-it-run.py (ASK-292).
#
# HERMETIC BY CONSTRUCTION. Nothing here reaches Linear, launchd, or the live
# ~/.config/kipi counter files. The fable-discipline lint blocks a test that
# touches a live data path, and this script is the one that would be tempted to:
# its subject reads six live sources. So the decision layer is tested through the
# script's own hermetic --self-test, and the CLI contract is tested with argv
# only. A test that dispatched a real issue to prove the checker works would be
# the worst possible way to verify a tool built to stop false dispatch claims.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/../will-it-run.py"
PASS=0; FAIL=0

ok() { PASS=$((PASS+1)); printf 'PASS: %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf 'FAIL: %s\n' "$1"; }
expect_rc() { # expect_rc <want> <name> -- reads rc from $?
  local want="$1" name="$2" got="$3"
  [ "$got" = "$want" ] && ok "$name" || bad "$name (want rc=$want, got rc=$got)"
}

[ -f "$TARGET" ] || { echo "FAIL: $TARGET missing"; exit 1; }

# 1. The decision layer. Delegates to the script's own hermetic suite so the
#    assertions live next to the code they cover and cannot drift from it.
OUT="$(python3 "$TARGET" --self-test 2>&1)"; RC=$?
expect_rc 0 "will-it-run --self-test passes" "$RC"
printf '%s\n' "$OUT" | grep -qE '^[0-9]+/[0-9]+ passed' \
  && ok "self-test printed a case tally" \
  || bad "self-test printed no tally (did it run?)"
printf '%s\n' "$OUT" | grep -q 'NEGATIVE self-test' \
  && ok "the suite contains a negative case" \
  || bad "no negative case: a suite that cannot fail is not a suite"

# 2. THE ANTI-DEFAULT ASSERTION, stated as its own case because it is the whole
#    point of the file. kipi-dispatch.sh:557 defaults DAILY_MAX to 4 and the
#    RUNNING value is 3. A checker that reads the default and reports it commits
#    the exact substitution it was built to prevent, so the literal must not be
#    reachable as a fallback anywhere in the source.
#    SCAN CODE, NOT PROSE. The first version of this check grepped the raw file
#    and went red on the DOCSTRING, which quotes `${KIPI_DISPATCH_DAILY_MAX:-4}`
#    to explain the hazard. A detector that cannot tell a description of a defect
#    from the defect is a detector that trains you to ignore it, so the source is
#    tokenised and comments plus string literals are dropped first.
if python3 - "$TARGET" <<'PY'
import io, re, sys, tokenize
src = open(sys.argv[1], "rb")
code = []
for tok in tokenize.tokenize(src.readline):
    if tok.type in (tokenize.COMMENT, tokenize.STRING, tokenize.NL):
        continue
    code.append(tok.string)
joined = " ".join(code)
# a literal 4 used as a cap fallback: `cap or 4`, `get(..., 4)`, `= 4` near cap
sys.exit(1 if re.search(r"(cap|DAILY_MAX|daily_max)[^;]{0,40}\b4\b", joined) else 0)
PY
then
  ok "no hardcoded cap default in CODE: the cap is observed or UNKNOWN"
else
  bad "a hardcoded cap fallback of 4 is reachable in code"
fi

# 3. Pickability is IMPORTED, never restated (ASK-288's scar, one copy of the rule).
grep -q 'linear_pick' "$TARGET" \
  && ok "imports linear_pick rather than restating pickability" \
  || bad "does not reference linear_pick: the pick rule has been copied"
if grep -qE '^\s*(PICKABLE_STATE_TYPES|HOLD_LABELS)\s*=' "$TARGET"; then
  bad "redefines a linear_pick constant locally (second copy of one truth)"
else
  ok "defines no local copy of linear_pick's constants"
fi

# 4. Liveness must come from process/state reads, not artifact mtimes. Four of the
#    nine RCA errors were artifact-read-as-behaviour, so the tool that exists to
#    prevent that class must not commit it.
# The binary name is held in a variable so it is a GREP PATTERN and never an
# invocation. The subject DOES invoke it and is macOS-scoped on purpose (the
# dispatcher is a launchd job); on Linux the subject's _run() returns 127 and the
# job reads NOT loaded, which is the honest answer there rather than a crash.
JOB_STATE_BIN='launchctl'   # portability-lint-skip
grep -q "$JOB_STATE_BIN" "$TARGET" && ok "reads job state from the job, not a log" \
  || bad "no job-state read: liveness would be inferred from an artifact"
grep -q 'pgrep' "$TARGET" && ok "reads running processes via pgrep" \
  || bad "no pgrep read: concurrency would be inferred"
if grep -qE 'st_mtime' "$TARGET" && ! grep -q 'FETCH_HEAD' "$TARGET"; then
  bad "uses an mtime for something other than reporting fetch age"
else
  ok "mtime is used only to report fetch age, never as evidence of behaviour"
fi

# 5. CLI contract, argv only.
python3 "$TARGET" >/dev/null 2>&1; RC=$?
expect_rc 2 "no argument is a usage error, not a silent success" "$RC"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
