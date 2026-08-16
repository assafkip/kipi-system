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
# THE MARKER MUST BE THE WHOLE LINE, NOT MERELY ITS START. Start-anchoring alone
# was the first attempt and it was wrong, because every marker below is also a
# legal opening for an ordinary English sentence. An agent that FIXES auth
# handling writes, at the left margin of its summary:
#   Invalid API key handling is now covered by regression tests.
# A start-anchored detector reads that success report as the machine being dead.
# That is the worst failure this file can have: a false halt stops the whole
# dispatcher on a HEALTHY runner, charges nobody, and -- because no attempt is
# recorded -- the redrive feeds the same issue back into the same false halt
# forever. Measured on PR #200's review: three ordinary sentences halted.
#
# The discriminator is not WHERE the marker sits but whether the line is the
# runner's ENTIRE utterance. The machine says its piece and stops; agent prose
# continues past the marker into more sentence. So the line must END at the
# marker, allowing only a SEPARATOR-LED tail (`- resets Aug 18 ...`,
# `· Please run /login`) -- machine formatting, which prose does not use to
# continue a clause -- plus a bare final period. A tail that resumes with a word
# is prose and is not a halt. Same shape as ASK-747: content that MENTIONS a
# marker is not the marker being raised.
#
# THIS ERRS TOWARD MISSING AN OUTAGE, DELIBERATELY. If the CLI someday pads a
# marker with an unseen word-led tail, the run degrades to the OLD behaviour --
# one issue charged one attempt -- which is recoverable and visible. A false halt
# is not: it stops work that could have run and it is self-perpetuating. Widen
# this only from a line an actual log carried, and add that line to the fixture
# table in test-worker-env-halt.sh.
#
# Leading whitespace is tolerated (up to 3) because the CLI pads some of these;
# an indented quote inside agent prose does not reach that far left.
ENV_MARKERS="(you've |you have )?hit your (weekly|usage|session|[0-9]+-hour) limit|usage limit reached|credit balance is too low|invalid api key|authentication_error|please run /login"

# Separator-led remainder of the machine's own line, or nothing. Kept as one
# string so is_environmental and environmental_reason cannot drift: a reason
# computed from a looser pattern than the decision would page with an empty
# "why", and a tighter one would page with none at all.
# `.*` and not `[^\n]*`: in an ERE bracket `\n` is the two literal characters,
# so `[^\n]*` excludes every tail containing the LETTER n -- which silently
# un-matched "- resets Aug 18 ... (America/Los_Angeles)" and "· Please run
# /login", i.e. both observed machine lines. grep is line-oriented, so `.` is
# already newline-safe here.
ENV_LINE_TAIL="([[:space:]]*([-|]|·|–|—).*)?[[:space:]]*[.!]?[[:space:]]*"

is_environmental() {  # is_environmental <runner-output> -> 0 when the MACHINE refused
  printf '%s' "${1:-}" | grep -qiE "^[[:space:]]{0,3}($ENV_MARKERS)$ENV_LINE_TAIL\$"
}

environmental_reason() {  # environmental_reason <runner-output> -> one line, <=120 chars
  printf '%s' "${1:-}" \
    | grep -iE "^[[:space:]]{0,3}($ENV_MARKERS)$ENV_LINE_TAIL\$" \
    | head -1 | tr -d '\n' | cut -c1-120
}
