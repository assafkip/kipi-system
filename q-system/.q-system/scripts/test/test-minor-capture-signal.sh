#!/usr/bin/env bash
# Pairs with the follow-ups half of pr-review-agent.sh (ASK-1921, ASK-2422).
#
# THE DEFECT THIS NOW PINS, PART 1 (ASK-1921). The block used to call
# `prd_runner.py spillover add` with no --severity. That defaults to `minor`,
# which sits in SPILLOVER_REFUSED_SEVERITIES ("a minor is fixed in this change or
# rejected with a reason; it is never queued", founder 2026-09-12), so the call
# returned 2 on EVERY run. The captured count was 0 by construction, and the alarm
# built on that zero paged Sana on every approved PR carrying a nit -- an alert
# with nothing down and nothing to act on (claude review of PR #392, finding 1).
#
# THE DEFECT THIS NOW PINS, PART 2 (ASK-2422, round 1 finding 2). The mark that
# releases a major from the gate sent that major down the MINORS path: named as a
# minor, and filed nowhere, under a log line explaining that minors are refused by
# policy. `major` is NOT refused by that policy, and no-orphan-findings.md requires
# medium-and-up to be captured, so the one severity that had to reach the ledger
# was the one that reached nobody.
#
# WHY AN rc KNOB IS BACK, NARROWLY. An earlier version of this file drove a
# severity-less call through a stub returning 0 -- an exit code the real producer
# cannot return for those arguments (same review, finding 2) -- and the knob was
# removed with the call. The block now makes a call for which rc=0 IS reachable:
# `--severity major` is outside SPILLOVER_REFUSED_SEVERITIES, so prd_runner writes
# the row and returns 0 (prd_runner.py cmd_spillover, the `add` branch). So the
# stub below is not a knob at all by default: it DERIVES the refused set from the
# real prd_runner source and applies the real rule to whatever the block passed.
# RUNNER_FORCE_RC exists only to drive the outage case -- a capture that genuinely
# failed -- which is a state the real producer can reach and must be paged.
#
# IT DRIVES THE SHIPPED BLOCK, NOT A COPY. The follow-ups half is inline in
# pr-review-agent.sh, so this extracts it by awk range (anchored on the `if` line
# and the first `^fi$` after it) and executes it in a bare subshell. Its outside
# edges: the findings extractor and the notifier are stubbed; pr-verdict-lib.sh is
# SOURCED FOR REAL, because findings_row_parts is the row parse under test here
# and a stub for it would test this file's idea of the row shape.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$SCRIPTS/../../.." && pwd)"
REVIEWER="$SCRIPTS/pr-review-agent.sh"
LIB="$SCRIPTS/pr-verdict-lib.sh"
RUNNER_SRC="$REPO/plugins/prd-os/scripts/prd_runner.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
FAILED=0

fail() { echo "FAIL: $*" >&2; FAILED=1; }
ok()   { echo "PASS: $*"; }

[ -f "$REVIEWER" ] || { echo "FAIL: $REVIEWER is missing"; exit 1; }
[ -f "$LIB" ]      || { echo "FAIL: $LIB is missing"; exit 1; }
[ -f "$RUNNER_SRC" ] || { echo "FAIL: $RUNNER_SRC is missing"; exit 1; }

# --- the refused severities, DERIVED from the code that owns them --------------
# Restating ("minor low nit") here would agree on the day it is written and keep
# agreeing after the real tuple moves, which is how a green test stops describing
# the system. The floor below is the other half: an empty parse would make every
# refusal check a no-op that still reads green.
REFUSED="$(sed -n 's/^SPILLOVER_REFUSED_SEVERITIES *= *(\(.*\)).*/\1/p' "$RUNNER_SRC" \
  | head -1 | tr -d '"'"'" | tr ',' ' ')"
REFUSED="$(printf '%s' "$REFUSED" | tr -s ' ')"
case " $REFUSED " in
  *" minor "*) ok "derived the refused severities from prd_runner.py: [$REFUSED]" ;;
  *) fail "could not derive SPILLOVER_REFUSED_SEVERITIES from $RUNNER_SRC (got '[$REFUSED]'); every refusal check below would be a no-op" ;;
esac
case " $REFUSED " in
  *" major "*) fail "prd_runner now REFUSES --severity major, so the capture call in the block cannot succeed and this whole route is dead" ;;
esac

# --- extract the shipped block ----------------------------------------------
extract_block() {
  awk '/^if \[ "\$VERDICT" = "APPROVE WITH NITS" \] && \[ -n "\$ISSUE" \]; then$/,/^fi$/' \
    "$1"
}
extract_block "$REVIEWER" > "$WORK/block.sh"
[ -s "$WORK/block.sh" ] || fail "could not extract the follow-ups block -- its anchors moved"
grep -q 'extract_followup_findings' "$WORK/block.sh" \
  || fail "the extracted range is not the follow-ups block (no 'extract_followup_findings' in it)"

# --- the harness the block runs inside ---------------------------------------
# $1 = the follow-up rows the extractor yields. $2 = an alternate block (mutants).
# Env knobs read from the caller: POST_MODE, RUNNER_FORCE_RC.
run_block() {
  local rows="$1" block="${2:-$WORK/block.sh}"
  local sandbox="$WORK/run"
  rm -rf "$sandbox"; mkdir -p "$sandbox/plugins/prd-os/scripts"
  # A prd_runner stub that applies the REAL refusal rule to the arguments it was
  # handed: refused severity (or none) -> rc 2 with the real refusal on stderr;
  # anything else -> the row is written, rc 0. So a severity-less call still fails
  # loudly here, exactly as it does in production.
  cat > "$sandbox/plugins/prd-os/scripts/prd_runner.py" <<RUNNER
#!/usr/bin/env bash
printf 'prd_runner was called: %s\n' "\$*" >> "$sandbox/runner-calls.txt"
if [ -n "\${RUNNER_FORCE_RC:-}" ]; then
  echo "forced failure" >&2
  exit "\$RUNNER_FORCE_RC"
fi
sev=""; prev=""
for a in "\$@"; do [ "\$prev" = "--severity" ] && sev="\$a"; prev="\$a"; done
for r in $REFUSED; do
  if [ "\${sev:-minor}" = "\$r" ]; then
    echo "refused: a \$r is fixed in this change or rejected with a reason" >&2
    exit 2
  fi
done
printf '{"id": "sp-stub", "status": "open", "linear": {"state": "filed"}}\n'
exit 0
RUNNER
  chmod +x "$sandbox/plugins/prd-os/scripts/prd_runner.py"
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$1" >> "%s/notified.txt"\n' "$sandbox" > "$sandbox/notify.sh"
  chmod +x "$sandbox/notify.sh"
  : > "$sandbox/notified.txt"
  : > "$sandbox/runner-calls.txt"

  {
    echo ". \"$LIB\""                     # findings_row_parts, for real
    echo 'python3() { "$1" "${@:2}"; }'   # route the block's python3 at the stub runner
    echo "extract_followup_findings() { printf '%s' \"\$ROWS_FIXTURE\"; }"
    cat "$block"
  } > "$sandbox/harness.sh"

  # The page and the runner calls both land in FILES, never in shell variables:
  # every caller below reads run_block through a command substitution, which is a
  # subshell, so an assignment made in here would be discarded and every "paged
  # nobody" assertion would pass without measuring anything.
  VERDICT="APPROVE WITH NITS" ISSUE="ASK-9999" PR="392" REVIEW="$WORK/review.md" \
  MINOR_TAG="" SKEL="$sandbox" NOTIFY="$sandbox/notify.sh" ROWS_FIXTURE="$rows" \
  POST="${POST_MODE:-1}" RUNNER_FORCE_RC="${RUNNER_FORCE_RC:-}" \
    bash "$sandbox/harness.sh" 2>&1
}

notified()     { cat "$WORK/run/notified.txt" 2>/dev/null; }
runner_calls() { cat "$WORK/run/runner-calls.txt" 2>/dev/null; }

TWO_MINORS='minor|the help text omits --repo-root|a.py:10
minor|the comment misstates the code|b.yml:72'
# A pipe inside the claim is the round-1 defect of ASK-2422 in its other half:
# a positional read would log the location as ` rc=3 and reports green`.
NB_MAJOR='major|the fallback swallows rc=2 | rc=3 and reports green|a.sh:40|nonblocking'

# --- the minors door is still not knocked on ----------------------------------
# Structural, read off the SHIPPED source. The assertion is NARROWER than the
# ASK-1921 version: a `spillover add` is legal now, but only carrying an explicit
# non-refused severity. A severity-less add is the exact call that returned 2 on
# every run, and it must never come back.
ADDS="$(grep -c 'spillover add' "$WORK/block.sh")"
if [ "$ADDS" = "0" ]; then
  fail "the block calls no 'spillover add' at all, so a nonblocking major is captured nowhere (no-orphan-findings.md)"
else
  # PER LINE, deliberately. A joined-text fallback ("the severity appears
  # somewhere after an add") would let one compliant call vouch for a second
  # severity-less one, which is exactly how mutant 1 below would survive. The
  # shipped call keeps `spillover add` and `--severity major` on one physical
  # line so this check needs no fallback; if a future edit wraps them, this goes
  # red and the fix is to unwrap the line, not to loosen the check.
  BAD=0
  while IFS= read -r line; do
    case "$line" in *"--severity major"*) : ;; *) BAD=1 ;; esac
  done <<ADDLINES
$(grep -n 'spillover add' "$WORK/block.sh")
ADDLINES
  [ "$BAD" = "0" ] \
    && ok "every 'spillover add' in the block carries an explicit --severity major (never the defaulted minor that prd_runner refuses)" \
    || fail "the block calls 'spillover add' without --severity major. prd_runner refuses a $REFUSED by policy (rc=2), so the capture cannot succeed and any count built on it reads as an outage."
fi

# --- two minors: named, counted, nobody paged, nothing filed -------------------
OUT="$(run_block "$TWO_MINORS")"
case "$OUT" in
  *"review minors on a terminal verdict: 2"*) ok "the minor count is printed (2)" ;;
  *) fail "expected a minor count of 2 in the output, got: $OUT" ;;
esac
MISSING=""
for claim in "the help text omits --repo-root" "a.py:10" "the comment misstates the code" "b.yml:72"; do
  case "$OUT" in *"$claim"*) : ;; *) MISSING="$MISSING [$claim]" ;; esac
done
[ -z "$MISSING" ] \
  && ok "each minor is NAMED with its location, not only tallied" \
  || fail "the output tallies the minors without naming them; absent:$MISSING"
case "$OUT" in
  *UNROUTED*) ok "a terminal verdict with minors says so out loud (UNROUTED)" ;;
  *) fail "2 minors on a terminal APPROVE WITH NITS produced no loud signal. Output was: $OUT" ;;
esac
[ -z "$(runner_calls)" ] \
  && ok "minors invoke no external producer at all" \
  || fail "the block filed a minor: $(runner_calls)"
[ -z "$(notified)" ] \
  && ok "a policy refusal pages nobody (no 100%-rate alert)" \
  || fail "an ordinary APPROVE WITH NITS with minors paged the alert path: $(notified)"

# --- a nonblocking major: captured at its real severity (ASK-2422) -------------
OUT="$(run_block "$NB_MAJOR")"
case "$OUT" in
  *"nonblocking major 1:"*) ok "a nonblocking major is labelled a major, not a minor" ;;
  *) fail "the nonblocking major was not named as one. Output was: $OUT" ;;
esac
case "$OUT" in
  *"the fallback swallows rc=2 | rc=3 and reports green (a.sh:40)"*)
    ok "the claim keeps its literal pipe and the location is the file:line, not a fragment of the claim" ;;
  *) fail "the row was split positionally, so the logged claim or location is wrong. Output was: $OUT" ;;
esac
case "$OUT" in
  *"review minors on a terminal verdict: 0"*) ok "a nonblocking major does not inflate the minor count" ;;
  *) fail "the major was counted as a minor. Output was: $OUT" ;;
esac
case "$OUT" in
  *"nonblocking majors on a terminal verdict: 1 (captured: 1)"*)
    ok "the major is counted and reported captured" ;;
  *) fail "no captured count for the nonblocking major. Output was: $OUT" ;;
esac
case "$(runner_calls)" in
  *"spillover add"*"--severity major"*) ok "the capture reached prd_runner with --severity major" ;;
  *) fail "the nonblocking major was never filed: [$(runner_calls)]" ;;
esac
[ -z "$(notified)" ] \
  && ok "a SUCCESSFUL capture pages nobody" \
  || fail "a successful capture paged the alert path: $(notified)"

# --- the capture fails: loud, and paged ----------------------------------------
# The real producer can fail here (no .prd-os in the repo, a broken runner), and a
# released major that reached no ledger and no issue is the orphan the rule forbids.
OUT="$(RUNNER_FORCE_RC=2 run_block "$NB_MAJOR")"
case "$OUT" in
  *"UNCAPTURED major"*) ok "a failed capture says UNCAPTURED out loud" ;;
  *) fail "a failed capture was silent. Output was: $OUT" ;;
esac
case "$OUT" in
  *"(captured: 0)"*) ok "a failed capture is not counted as captured" ;;
  *) fail "a failed capture was still counted. Output was: $OUT" ;;
esac
case "$(notified)" in
  *"capture FAILED"*) ok "a failed capture pages the alert path once" ;;
  *) fail "a failed capture paged nobody: [$(notified)]" ;;
esac

# --- a dry run files nothing (sp-8424aa32) -------------------------------------
# Everything else in this block only writes to the log, so it was safe above the
# POST guard. A capture call is not: it files a real Linear issue.
OUT="$(POST_MODE=0 run_block "$NB_MAJOR")"
case "$OUT" in
  *"WOULD CAPTURE"*) ok "a dry run says what it would file" ;;
  *) fail "a dry run gave no sign of the capture it skipped. Output was: $OUT" ;;
esac
[ -z "$(runner_calls)" ] \
  && ok "a dry run calls no producer and mutates no ledger" \
  || fail "a dry run filed to the ledger: $(runner_calls)"

# --- the negative: zero follow-ups is quiet ------------------------------------
# An LLM that drifts from the FINDINGS format yields zero lines, and zero follow-ups
# is a review with no nits -- the ordinary healthy case.
OUT="$(run_block "")"
case "$OUT" in
  *UNROUTED*) fail "zero follow-ups extracted was reported as unrouted: $OUT" ;;
  *) ok "zero follow-ups raises nothing" ;;
esac
[ -z "$(notified)" ] || fail "zero follow-ups paged the alert path: $(notified)"
[ -z "$(runner_calls)" ] || fail "zero follow-ups filed something: $(runner_calls)"

# --- mutant 1: the severity-less call cannot come back -------------------------
# A check that cannot be made to fail is decoration. Re-add the ASK-1921 call to a
# COPY and confirm the structural assertion above goes red on it.
sed 's#^  done <<EOF#    python3 "$SKEL/plugins/prd-os/scripts/prd_runner.py" spillover add --source "$ISSUE" --desc "x"\n  done <<EOF#' \
  "$WORK/block.sh" > "$WORK/mutant1.sh"
M1JOINED="$(tr '\n' ' ' < "$WORK/mutant1.sh")"
case "$M1JOINED" in
  *'spillover add --source "$ISSUE" --desc'*)
    ok "mutant 1 built (severity-less capture call re-added to a copy)"
    M1BAD=0
    while IFS= read -r line; do
      case "$line" in *"--severity major"*) : ;; *) M1BAD=1 ;; esac
    done <<M1LINES
$(grep -n 'spillover add' "$WORK/mutant1.sh")
M1LINES
    [ "$M1BAD" = "1" ] \
      && ok "mutant 1 killed: the per-line severity check sees the severity-less add" \
      || fail "mutant 1 SURVIVED: a severity-less 'spillover add' passed the structural check"
    # ...and it also fails at runtime, through the real refusal rule.
    run_block "$TWO_MINORS" "$WORK/mutant1.sh" >/dev/null
    case "$(runner_calls)" in
      *"spillover add"*) ok "mutant 1 killed at runtime too: the minors path knocked on the refusing door" ;;
      *) fail "mutant 1 SURVIVED at runtime: the re-added capture call was never observed" ;;
    esac ;;
  *) fail "could not build mutant 1 -- the block's shape moved, so the check above is unproven" ;;
esac

# --- mutant 2: the POST guard is what holds the dry run ------------------------
sed 's#^      if \[ "\$POST" != "1" \]; then#      if false; then#' \
  "$WORK/block.sh" > "$WORK/mutant2.sh"
if ! cmp -s "$WORK/block.sh" "$WORK/mutant2.sh"; then
  ok "mutant 2 built (POST guard disabled on a copy)"
  POST_MODE=0 run_block "$NB_MAJOR" "$WORK/mutant2.sh" >/dev/null
  [ -n "$(runner_calls)" ] \
    && ok "mutant 2 killed: the dry-run check sees a ledger write once the guard is gone" \
    || fail "mutant 2 SURVIVED: the POST guard was removed and the dry-run check noticed nothing"
else
  fail "could not build mutant 2 -- the POST guard's shape moved, so the dry-run check is unproven"
fi

[ "$FAILED" = "0" ] && echo "ALL PASS" || echo "SOME FAILED"
exit "$FAILED"
