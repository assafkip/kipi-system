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
# `· Please run /login`) plus a bare final period. A separator alone does NOT
# make the tail the machine's -- prose uses a dash to continue a clause all the
# time, which is round 4 below; the tail body is what decides. Otherwise a tail
# that resumes with a word is prose. Same shape as ASK-747: content that MENTIONS a
# marker is not the marker being raised.
#
# AND THE MARKER MUST BE THE WHOLE OUTPUT, NOT MERELY A LINE OF IT. Whole-line
# anchoring was the second attempt and it was still wrong, for the same reason
# one layer up. An agent WORKING on auth quotes a marker on a line of its own --
# in a fenced block, a diff, a test name, a bullet -- inside an otherwise
# ordinary multi-line report:
#   Implemented auth handling and added this regression fixture:
#   ```text
#   Invalid API key
#   ```
#   All tests pass.
# Matching any ONE line of a long transcript reads that report as the machine
# being dead. Measured on PR #200's review round 2.
#
# The runner's whole utterance is the whole OUTPUT. The machine says its piece
# and stops: on 2026-08-15 `claude -p` printed the limit line and nothing else.
# An agent that produced a transcript is, by the existence of the transcript, a
# runner that ran -- whatever it quoted inside it. So EVERY non-blank line must
# be the machine's, not just one. Blank lines are formatting, not a second
# utterance, and are not counted on either side.
#
# THIS ERRS TOWARD MISSING AN OUTAGE, DELIBERATELY, at both layers. If the CLI
# someday pads a marker with an unseen word-led tail, or prints one ordinary
# line alongside it, the run degrades to the OLD behaviour -- one issue charged
# one attempt -- which is recoverable and visible. A false halt is not: it stops
# work that could have run, charges nobody, and because no attempt is recorded
# the redrive feeds the same issue back into the same false halt forever. Widen
# this only from output an actual log carried, and add that output to the
# fixture table in test-worker-env-halt.sh.
#
# Leading whitespace is tolerated (up to 3) because the CLI pads some of these;
# an indented quote inside agent prose does not reach that far left.
ENV_MARKERS="(you've |you have )?hit your (weekly|usage|session|[0-9]+-hour) limit|usage limit reached|credit balance is too low|invalid api key|authentication_error|please run /login|api error: 529 overloaded(\. this is a server-side issue, usually temporary[[:space:]]*(—|–|-{1,2})[[:space:]]*try again in a moment\. if it persists, check https://status\.claude\.com\.?)?"
# The 529 line, added 2026-09-23 (ASK-2009) from the real worker log: on
# 2026-08-18 three runs printed ONE line that begins
#   API Error: 529 Overloaded. This is a server-side issue, usually temporary
# and continues on the same line, after an em dash, with "try again in a
# moment" and a status-page link (the captured fixture carries it verbatim).
# Each was charged to its issue. The provider was overloaded; the issue was
# fine. Only the CLI's own sentence is admitted after the status, never prose:
# the round-8 version ended in `.*`, which let one line of agent prose that
# QUOTED the 529 read as the machine refusing and halt the dispatcher (PR #421
# round 11, minor). The sentence is now spelled out to its last character.

# THE CLI'S OWN HOOK NOISE IS NOT AN UTTERANCE (ASK-2009). On 2026-09-19 a run
# printed the limit line and then two lines the CLI writes when it tears a
# session down mid-refusal:
#   SessionEnd hook [python3 ".../session-end-llma.py"] failed: Hook cancelled
# Counted as spoken lines, they made a real outage read as an agent that ran,
# and ASK-535 was charged. The pattern is that exact shape and nothing looser:
# the same log also carries an agent sentence that STARTS "SessionStart hook
# path makes zero network calls", which is prose and must keep counting.
# Widened from SessionEnd alone to the CLI's hook EVENTS (PR #421 round 2): a
# limit line beside a Stop-hook cancellation is the same refusal. Still the
# exact line shape -- `<Event> hook [<cmd>] failed: Hook cancelled` -- so no
# sentence an agent writes can pass for it.
# Up to 3 leading spaces, the same tolerance ENV_LINE_RE gives the marker
# (PR #421 round 3): an indented teardown line must not sink a real outage.
ENV_NOISE_RE='^[[:space:]]{0,3}(SessionEnd|SessionStart|Stop|SubagentStop|PreCompact|Notification|UserPromptSubmit|PreToolUse|PostToolUse) hook \[.*\] failed: Hook cancelled[[:space:]]*$'

# AND THE SEPARATOR MUST LEAD SOMEWHERE THE MACHINE GOES. Allowing a separator
# plus ANYTHING was the third attempt and it was wrong for the same reason as the
# first two, one layer further out: the tail exemption that admits the machine's
# own line is also the commonest way English continues a clause. A dash after a
# noun phrase is an ordinary summary bullet:
#   Invalid API key - fixed by adding a retry with backoff.
#   usage limit reached - added a regression test for the reset path.
# Both are agent SUCCESS reports and both halted the fleet. Measured on PR #200's
# review round 4; four shapes, including a markdown table row, whose `|` is in
# the separator class.
#
# The exemption exists for exactly two tails an actual log carried, so it admits
# exactly those two shapes and no third:
#   - resets Aug 18 at 2pm (America/Los_Angeles)   -> a `resets ...` clause
#   · Please run /login                            -> a SECOND marker
# A tail that resumes with any other word is prose. `resets` is matched word-led
# rather than by date shape on purpose: the CLI has already varied the clause
# ("resets at 2pm", "resets in 3 hours") and pinning a format would break on the
# next wording, which is the missing-an-outage direction but needlessly.
#
# Kept as one string so is_environmental and environmental_reason cannot drift: a
# reason computed from a looser pattern than the decision would page with an
# empty "why", and a tighter one would page with none at all.
# `.*` and not `[^\n]*` inside the reset clause: in an ERE bracket `\n` is the
# two literal characters, so `[^\n]*` excludes every tail containing the LETTER
# n -- which silently un-matched "- resets Aug 18 ... (America/Los_Angeles)".
# grep is line-oriented, so `.` is already newline-safe here.
ENV_TAIL_BODY="resets[[:space:]].*|$ENV_MARKERS"
ENV_LINE_TAIL="([[:space:]]*([-|]|·|–|—)[[:space:]]*($ENV_TAIL_BODY))?[[:space:]]*[.!]?[[:space:]]*"

# ONE regex, built once, used by the counter and by the reason. Two spellings of
# "is this the machine's line" is the drift this whole file exists to prevent.
ENV_LINE_RE="^[[:space:]]{0,3}($ENV_MARKERS)$ENV_LINE_TAIL\$"

is_environmental() {  # is_environmental <runner-output> -> 0 when the MACHINE refused
  local payload="${1:-}" spoken machine
  # The CLI's own session-teardown lines are dropped first: they are neither the
  # agent speaking nor the machine refusing (see ENV_NOISE_RE).
  payload="$(printf '%s\n' "$payload" | grep -vE "$ENV_NOISE_RE" 2>/dev/null)" || true
  # Non-blank lines the runner emitted, and how many of them were the machine's.
  # Equality is the test: one ordinary line among them means an agent ran and
  # merely QUOTED a marker, which is not an outage.
  spoken="$(printf '%s' "$payload" | grep -c '[^[:space:]]' 2>/dev/null)" || true
  machine="$(printf '%s' "$payload" | grep -ciE "$ENV_LINE_RE" 2>/dev/null)" || true
  [ "${spoken:-0}" -ge 1 ] && [ "${machine:-0}" -eq "${spoken:-0}" ]
}

environmental_reason() {  # environmental_reason <runner-output> -> one line, <=120 chars
  printf '%s' "${1:-}" \
    | grep -iE "$ENV_LINE_RE" \
    | head -1 | tr -d '\n' | cut -c1-120
}

# ---------------------------------------------------------------------------
# CODEX PRINTS A TRANSCRIPT, NOT A REFUSAL (PR #421 round 8, major)
# ---------------------------------------------------------------------------
# `codex exec` never prints its outage alone. Every real one in the worker log
# is a banner, the echoed prompt and hook lines, then `ERROR: <reason>` and
# exit 1, sometimes followed by its own "tokens used" / "<count>" trailer when
# the credits ran out mid-run. The every-line rule above can never match that,
# so the Codex branch parked the issue blocked:capability for a condition of
# the machine: 17 of the 44 real worker handoffs to Codex (fixture
# codex-outages-2026-09-23.json), two outage wordings, one of which ("Your
# workspace is out of credits") no marker covered at all.
#
# So Codex gets its own rule, read from the END of the transcript, where only
# Codex itself writes: the run failed (rc != 0), and after dropping blank lines
# and the token trailer, the last lines are Codex's own `ERROR:` lines and every
# one of them names an outage. The echoed prompt and anything the model said sit
# ABOVE that block, so a quoted limit line there cannot pass; an `ERROR:` line
# that is not an outage (the real "file or directory not found" in the fixture)
# fails the every-line half. Anchored at column 0 because that is where Codex
# prints it.
CODEX_OUTAGE_MARKERS="$ENV_MARKERS|your workspace is out of credits"

codex_outage_reason() {  # codex_outage_reason <codex-output> <rc> -> the line; 0 when the MACHINE refused
  local out="${1:-}" rc="${2:-0}"
  [ "$rc" != "0" ] || return 1
  printf '%s\n' "$out" | CODEX_RE="^error: ($CODEX_OUTAGE_MARKERS)" awk '
    { line[NR] = $0 }
    END {
      re = ENVIRON["CODEX_RE"]; n = NR
      while (n > 0 && line[n] ~ /^[[:space:]]*$/) n--
      if (n > 1 && line[n] ~ /^[0-9][0-9,]*$/ && line[n-1] == "tokens used") n -= 2
      while (n > 0 && line[n] ~ /^[[:space:]]*$/) n--
      k = n; seen = 0
      while (k > 0 && line[k] ~ /^ERROR: /) {
        if (tolower(line[k]) !~ re) exit 1
        seen = 1; k--
      }
      if (!seen) exit 1
      # WHO WAS SPEAKING above the block (PR #421 round 9, minor). Codex marks
      # every event with a header line: "user" (the echoed prompt), "codex" (the
      # model), "thinking", "exec" (a command and its output), "hook: <Event>".
      # The nearest header above the ERROR block must be the prompt or a hook,
      # as in every real outage in the fixture. Under "codex" or "exec" the
      # ERROR lines are the model or a command talking, and a quoted limit line
      # there is not the machine refusing. No header at all is read as Codex.
      for (j = k; j > 0; j--) {
        if (line[j] ~ /^(user|codex|thinking|exec)$/ || line[j] ~ /^hook: [A-Za-z]+( Completed)?$/) {
          if (line[j] == "codex" || line[j] == "thinking" || line[j] == "exec") exit 1
          break
        }
      }
      print substr(line[n], 1, 120)
      exit 0
    }'
}

# THE ONE DECISION the Codex branch calls, so a replay of the fixture and the
# worker cannot disagree. A runner that prints a bare limit line (the shape
# the other runner uses) still reads as an outage through the first half.
codex_env_reason() {  # codex_env_reason <codex-output> <rc> -> the line; 0 when the MACHINE refused
  if is_environmental "${1:-}"; then
    environmental_reason "${1:-}"
    return 0
  fi
  codex_outage_reason "${1:-}" "${2:-0}"
}

# ---------------------------------------------------------------------------
# ONE PAGE PER CONDITION, NOT ONE PER PROCESS (Codex round 5 on PR #200, major)
# ---------------------------------------------------------------------------
# Everything above answers WHOSE failure it is. This answers HOW MANY TIMES the
# answer gets said out loud, and it belongs in the same file because it is the
# same category error one layer out.
#
# The caller already promised "one machine-wide condition, one ticket" and kept
# it PER RUN, which is the wrong unit for a fact that is a property of the
# machine. Every process on that machine meets the identical condition:
#   * concurrent workers are supported (that is what the per-worktree claim lock
#     exists for, and it is why the halt marker and the run-output file above had
#     to become per-pid in round 3) -- so two of them halt on one exhausted
#     account and file two identical tickets a human then diffs at 3am;
#   * and at a 15-minute launchd tick, the measured six-hour outage of 2026-08-15
#     was twenty-four halted runs, so "one per run" is twenty-four pages for one
#     fact. That is exactly the cry-wolf shape founder-notifications.md names as
#     the thing that teaches the reader to mute the channel.
#
# So the claim is deliberately NOT per-pid, unlike the two files above. Those had
# to be private because they carry THIS RUN's state; this one has to be shared
# because it carries the MACHINE's, and $STATE_DIR is the scope both halves of
# that sentence already agree on.
#
# `mkdir` IS the atomicity, and it is the whole reason this is not a plain file.
# It is one syscall that either creates the directory or fails because it exists,
# with no window in between. A `[ -f ] && : > file` claim has exactly that window,
# and two workers hitting the same outage inside it both read "unclaimed" and both
# page -- the defect, reproduced rather than fixed. Eight racing subshells in
# test-worker-env-halt.sh pin that exactly one wins.
#
# NO STATE DIR MEANS PAGE. A caller that passes nothing gets a claim, because the
# failure direction here matters: a missing page for a real outage is silence a
# human cannot detect, and a duplicate page is noise they can.
ENV_ALERT_CLAIM_NAME="env-alert.claim"

# AN OPTIONAL MAX AGE, for a claim its release may never reach (PR #421 rounds
# 8 and 12). The Codex claim is released only by a run that REACHES Codex, which
# happens only on a rare capability refusal. The main claim is released only by
# a run that hears the runner answer, and a queue that stays empty after an
# outage never does. Either way a claim from an outage long over stayed held and
# the next outage paged nobody. With a max age, a claim older than that is taken
# over; the worker passes a day for both.
# The takeover is a rename, which exactly one racer can win, then the same mkdir
# as a fresh claim. See _env_claim_older_than for a holder with no epoch.
#
# HOW OLD IS A CLAIM (PR #421 round 10, minor). The epoch in the holder, and
# when there is none -- a holder write that failed, or a run killed between the
# mkdir and the write -- the claim directory's own mtime, which is when it was
# made. Never "no epoch means forever" (the round-8 version): that failed
# CLOSED, a claim nobody could take over and a hold nobody could lift, against
# this file's own rule that a missing page is the worse failure. And never "no
# epoch means expired" either: a racer that reads the holder in the instant
# between another run's mkdir and its write would take over a fresh claim and
# page twice. `find -mmin` is the one age test BSD and GNU find agree on.
_env_claim_older_than() {  # _env_claim_older_than <claim-dir> <max-age-seconds> -> 0 when older
  local claim="$1" max_age="$2" held_at
  held_at="$(sed -n 's/.*epoch=\([0-9][0-9]*\).*/\1/p' "$claim/holder" 2>/dev/null | head -1)"
  if [ -n "$held_at" ]; then
    [ $(( $(date +%s) - held_at )) -gt "$max_age" ]
  else
    [ -n "$(find "$claim" -maxdepth 0 -mmin +$(( (max_age + 59) / 60 )) 2>/dev/null)" ]
  fi
}

env_alert_claim() {  # env_alert_claim <state-dir> [max-age-seconds] -> 0 when THIS process may page
  local state="${1:-}" max_age="${2:-}" claim dead
  [ -n "$state" ] || return 0
  mkdir -p "$state" 2>/dev/null || return 0
  claim="$state/$ENV_ALERT_CLAIM_NAME"
  if ! mkdir "$claim" 2>/dev/null; then
    [ -n "$max_age" ] || return 1
    _env_claim_older_than "$claim" "$max_age" || return 1
    # A name nothing holds (PR #421 round 11, nit): mv onto an EXISTING
    # directory moves the claim inside it, the cleanup below misses, and the
    # litter stays. mktemp -u picks a free name on BSD and GNU alike.
    dead="$(mktemp -u "$claim.expired.XXXXXX")" || return 1
    mv "$claim" "$dead" 2>/dev/null || return 1
    rm -f "$dead/holder" 2>/dev/null || true
    rmdir "$dead" 2>/dev/null || true
    mkdir "$claim" 2>/dev/null || return 1
  fi
  # For the human reading $STATE_DIR later. The directory's existence is still
  # the protocol; only a caller that passed a max age reads the epoch back
  # (env_alert_claim above, env_alert_held below).
  printf 'pid=%s claimed_at=%s epoch=%s\n' "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)" "$(date +%s)" \
    > "$claim/holder" 2>/dev/null || true
  return 0
}

# THE RE-ARM, AND WITHOUT IT THIS IS A PERMANENT MUTE -- a worse failure than the
# duplicate it prevents, because the next outage weeks later would page nobody.
#
# There is no "the outage ended" event to subscribe to, so the release stands in
# for one: a caller that finished its work WITHOUT hitting an environmental
# failure has observed a working runner, and that observation is the state change.
# The page therefore fires on the healthy->down EDGE and the edge re-arms on the
# way back up, which is founder-notifications.md's "alert on state change, once"
# rather than a TTL guessed against a reset time the machine never tells us.
#
# A run killed mid-outage leaves the claim held, and that is correct: the outage
# is still on, so the next run should stay quiet. The claim comes off at the first
# run that hears the runner answer after recovery. A claim that outlives its
# outage (no run reached the runner since) would be silent: nothing else sees a
# halt, because kipi-dispatch.sh detaches converge and exits 0, so no launchd
# label ever carries the halt's exit 9 (PR #421 round 12). That is why the worker
# passes env_alert_claim a max age: past a day the claim is taken over and pages.
# IS THE CONDITION STILL ANNOUNCED? (PR #421 round 9, major) The Codex branch
# returns a capability-refused issue to the pool unlabelled during an outage,
# so every tick re-ran a paid Sana session on it only to reach the same dead
# Codex. The worker holds such an issue while this answers yes. Same epoch rule
# as env_alert_claim: past the max age the claim no longer counts as held, so
# the issue runs once more and the takeover there pages again.
env_alert_held() {  # env_alert_held <state-dir> [max-age-seconds] -> 0 while a live claim stands
  local claim="${1:-}/$ENV_ALERT_CLAIM_NAME" max_age="${2:-}"
  [ -n "${1:-}" ] && [ -d "$claim" ] || return 1
  [ -n "$max_age" ] || return 0
  ! _env_claim_older_than "$claim" "$max_age"
}

env_alert_release() {  # env_alert_release <state-dir>
  local state="${1:-}"
  [ -n "$state" ] || return 0
  rm -f "$state/$ENV_ALERT_CLAIM_NAME/holder" 2>/dev/null || true
  rmdir "$state/$ENV_ALERT_CLAIM_NAME" 2>/dev/null || true
  return 0
}
