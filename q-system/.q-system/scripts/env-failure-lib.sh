#!/usr/bin/env bash
# ONE ANSWER TO "WHOSE FAILURE IS THIS" (ASK-873, factored for ASK-869).
#
# An exhausted account, an expired credential or a logged-out CLI is a property
# of the MACHINE. It is identical for every issue or instance the caller has not
# reached yet, so charging it to the work item is a category error, and any
# ledger that records the charge makes the error permanent.
# `.claude/rules/self-healing-retry.md` step 5 already states the rule:
# environmental failures stop on attempt 1 and surface immediately, because
# retrying logic cannot fix an environment.
#
# WHY A SOURCED LIB AND NOT A SECOND COPY. ASK-869 (PR #198) landed this same
# detector inline in open-loops-heartbeat.sh, and ASK-873's DoR is explicit that
# two detectors with two patterns is the defect again: the day one pattern is
# widened and the other is not, the two halves of the fleet disagree about what
# an outage looks like. Same convention as pr-verdict-lib.sh and
# repo-slug-lib.sh -- one derivation, sourced by every consumer. ASK-869 can
# adopt it by replacing its inline block with a `.` of this file; nothing here
# depends on the worker.
#
# DERIVED FROM WHAT THE LOG ACTUALLY CARRIED, not from what an exhausted CLI
# might plausibly print. The observed line, 2026-08-15, once per failing run:
#   You've hit your weekly limit - resets Aug 18 at 2pm (America/Los_Angeles)
# The auth siblings are here because they are the same CLASS -- the runner
# cannot run at all, and no work item can fix that for another -- but the match
# stays narrow on purpose. A loose pattern silently converts an ordinary
# per-issue failure into a fleet-wide halt, which is worse than the noise it
# replaces: the loop would stop on one issue's ordinary bad day.
#
# ANCHORED AT THE START OF A LINE, NOT MATCHED ANYWHERE. The runner emits this
# as a line of its own; an AGENT that merely writes ABOUT limits emits it inside
# a sentence or a bullet. Matched as a bare substring, an agent working on this
# very issue and then producing no PR would halt the whole dispatcher and report
# the runner as dead -- a false halt is worse than the noise, because it stops
# work that could have run. Same shape as ASK-747, fixed the same way: content
# that MENTIONS a marker is not the marker being raised. Leading whitespace is
# tolerated (up to 3) because the CLI pads some of these; an indented quote
# inside agent prose does not reach that far left.
ENV_MARKERS="(you've |you have )?hit your (weekly|usage|session|[0-9]+-hour) limit|usage limit reached|credit balance is too low|invalid api key|authentication_error|please run /login"

is_environmental() {  # is_environmental <runner-output> -> 0 when the MACHINE refused
  printf '%s' "${1:-}" | grep -qiE "^[[:space:]]{0,3}($ENV_MARKERS)"
}

environmental_reason() {  # environmental_reason <runner-output> -> one line, <=120 chars
  printf '%s' "${1:-}" \
    | grep -iE "^[[:space:]]{0,3}($ENV_MARKERS)" \
    | head -1 | tr -d '\n' | cut -c1-120
}
