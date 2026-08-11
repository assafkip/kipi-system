#!/bin/bash
# Send a Slack message via an Incoming Webhook. Reliable, reaches the phone, works
# headless (unlike osascript desktop notifications, which are permission-gated and
# silently dropped from a sandboxed process).
#
# Webhook URL is a SECRET -- never committed. Resolved from, in order:
#   1. $KIPI_SLACK_WEBHOOK
#   2. ~/.config/kipi/slack-webhook  (gitignored file, one line)
# No webhook configured -> silent no-op (exit 0), so callers never break.
#
# Usage:
#   slack-notify.sh --kind receipt "message"                        (never delivered)
#   slack-notify.sh --kind decision --class <allowlisted> "message" (delivered)
#   slack-notify.sh "message"                                       (legacy, fail-open)
set -uo pipefail

# === THE DECISION GATE (ASK-294) =============================================
# The founder, twice in one session: "why do I keep getting slack messages I
# can't do anything about that you should be seeing and dealing with", then
# "I don't want to get slack messages that are useless to me. they should go to
# you or sana."
#
# MEASURED: 48 messages reached #general in 24h from 11 producers, and NOTHING in
# the fleet reads the channel back -- no job, no hook, no agent. A write-only
# webhook means every message terminates at the founder by construction. Most of
# them said "nothing to do" in their own text, which is the cry-wolf failure
# loop-exits.md already documents: a channel of non-actionable lines trains him
# to skim, and the skim is how the one page that matters gets missed.
#
# AN ALERT IS A RECEIPT, NEVER A MECHANISM. The machine handles the condition;
# the message records that it did. A message asking the founder to perform a
# step is a defect in the PRODUCER, not a wording problem.
#
# WHY A CLOSED ENUM AND NOT A WORDING LINT. The obvious cheap gate is "refuse a
# message that reads non-actionable", and it fails immediately: a producer that
# wants through just rewords. The enum is the opposite shape -- a producer
# cannot argue its way past it, it has to add a case to ALLOWED_CLASSES in a
# reviewed diff, which is exactly the visibility that was missing while 11
# producers violated founder-notifications.md for weeks.
#
# THE ALLOWLIST IS NOT A STYLE CHOICE. It is feedback_founder_never_the_next_actor
# read literally: founder sign-off exists for irreversible acts and for writes
# outside the canonical tree, plus the two authorizations only he holds. Four
# cases, and every one of them is something a machine must NOT decide alone.
#
# `credential` is the fifth and it was NOT in the first cut. Dispatch pages once
# when the Linear token is dead: no issue can be picked, the loop is stopped not
# slow, and no agent can rotate a secret it cannot read. Refusing that page would
# have left the whole loop silently dark -- a gate that swallows a real alert is a
# worse outage than the noise it was built to stop, which outranks this issue.
# Adding a class is deliberately a diff someone reviews; that is the brake.
ALLOWED_CLASSES="irreversible-git out-of-tree-write spend publish credential"

# CLASSIFICATION COMES FROM THE ENVIRONMENT FIRST, argv SECOND. That order is a
# scar, not a preference. argv flags were tried first and broke suites that had
# nothing to do with this change, in BOTH possible arrangements:
#   flags BEFORE the message -> the message leaves $1, and notify stubs across
#     these suites record "$1". Three untouched suites went red at once.
#   flags AFTER the message  -> "$*" gains " --kind receipt", and a stub that
#     records "$*" feeds that into assertions about the page PROSE.
#     test-severity-floor: "the healthy page now carries receipt prose on a run
#     where the receipt LANDED" -- every converged PR would have paged about a
#     problem that was not there.
# Rewriting the four stubs was the wrong instinct: they are tests this change
# never touched, and editing them regressed three.
#
# A command-prefix env var is invisible to BOTH forms -- "$1" is still the
# message, "$*" is still exactly the message -- so no stub here or in any fleet
# instance has to know this feature exists. Written as a prefix and never
# exported, so it stays per-invocation. argv still wins when both are given:
# dispatch's page_ok() passes flags straight through, and the sink has to remain
# usable by hand.
KIND="${KIPI_NOTIFY_KIND:-}"; CLASS="${KIPI_NOTIFY_CLASS:-}"; MSG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --kind)  KIND="${2:-}"; shift 2 || break ;;
    --class) CLASS="${2:-}"; shift 2 || break ;;
    --)      shift; MSG="${1:-}"; break ;;
    *)       MSG="$1"; shift ;;
  esac
done
[ -n "$MSG" ] || exit 0

# REFUSE means "do not deliver", never "discard". Every outcome below is written
# to the ledger, including the refusals, because a silently swallowed alert is
# the precise failure founder-notifications.md exists to prevent. The refusal is
# a routing decision, not a censorship decision.
REFUSED=0; DELIVER=0; REASON=""
case "$KIND" in
  receipt)
    DELIVER=0; REASON="receipt: handled by the machine, recorded not delivered" ;;
  decision)
    if [ -z "$CLASS" ]; then
      REFUSED=1; REASON="--kind decision requires --class from: $ALLOWED_CLASSES"
    else
      case " $ALLOWED_CLASSES " in
        *" $CLASS "*) DELIVER=1; REASON="founder decision ($CLASS)" ;;
        *) REFUSED=1; REASON="unknown --class '$CLASS'; allowed: $ALLOWED_CLASSES" ;;
      esac
    fi ;;
  "")
    # FAIL OPEN, LOUDLY. kipi update ships this script fleet-wide, and instances
    # carry producers this repo has never seen (a cole-gtm voice-lint nudge posts
    # here today). Refusing an unmigrated caller would silence an instance-local
    # alert nobody has looked at yet -- the "gate that silences a real alert is a
    # worse outage than the noise" line, which outranks this whole issue. So it
    # goes through wearing a marker, and the ledger row is the migration list.
    KIND="unclassified"; DELIVER=1
    REASON="legacy one-arg caller: no --kind declared"
    MSG="[unclassified] $MSG" ;;
  *)
    REFUSED=1; REASON="unknown --kind '$KIND'; expected receipt or decision" ;;
esac
[ "$REFUSED" -eq 0 ] || DELIVER=0

# Project label so the founder always knows which instance pinged. Resolved in order:
#   KIPI_INSTANCE_NAME (set by the fleet heartbeat = exact registry name)
#   -> git repo root basename -> cwd basename. Every message is prefixed "[label] ".
LABEL="${KIPI_INSTANCE_NAME:-}"
if [ -z "$LABEL" ]; then
  LABEL="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")")"
fi
MSG="[$LABEL] $MSG"

# --- fixture-run guard: a test must never be able to page a human -------------
# SCAR 2026-08-01. Three tests were found paging the founder's real Slack and
# were fixed by stubbing KIPI_NOTIFY per test (PR #54). While that PR sat open
# and unmerged, an agent ran test-worker-project-scope.sh from a worktree cut
# off main -- which carries no stub -- and the founder was paged again, live.
# Per-test stubbing has three structural holes: it only protects branches that
# carry it, only tests someone remembered to fix, and its paired lint only fires
# at write-time on the edited file. A test written tomorrow still pages.
# This is the one chokepoint that needs none of those things to be remembered.
#
# THE SIGNAL. Every test in this repo points the worker at a fixture Linear on
# loopback (KIPI_LINEAR_API_URL=http://127.0.0.1:$PORT/graphql); production
# always points at the real Linear API. That asymmetry is total in both
# directions, which is what makes it safe to key a refusal on. This script is
# invoked as `bash "$NOTIFY" "msg"` from the worker, so it INHERITS the
# variable -- verified 2026-08-01 by running the same `env VAR=... bash parent`
# shape the tests use and reading the variable from the grandchild.
#
# DELIBERATELY NOT A SIGNAL: KIPI_STATE_DIR under a temp dir. A production job
# may legitimately keep state in a temp path (macOS $TMPDIR is exactly that), so
# keying on it would suppress real pages. A guard that swallows a genuine alert
# is worse than the bug it fixes, so the guard keys only on the one signal that
# cannot be true in production.
#
# The refused text goes to stderr rather than being dropped: a silently
# swallowed alert is the precise failure mode founder-notifications.md exists
# to prevent, and a fixture run still needs its diagnostic to be readable.
# Two review findings on PR #58 shaped this function, and they point in OPPOSITE
# directions -- which is why both halves are asserted in the paired suite:
#
#   1. A `127.*` shell pattern also matches non-loopback HOSTNAMES beginning
#      "127.", so `127.example.com` would have been read as a fixture and its
#      alert SILENTLY SUPPRESSED. That is the same failure class this guard
#      rejects KIPI_STATE_DIR-under-temp for. The real invariant is the
#      127.0.0.0/8 block -- four NUMERIC octets in range -- not a string prefix.
#   2. The comparison was case-sensitive, so `LOCALHOST` reached the webhook
#      from a fixture run. DNS hostnames are case-insensitive, so that was a
#      genuine bypass, not a theoretical one.
#
# Lowercasing uses tr, not ${var,,}: /bin/bash on macOS is 3.2, where ${var,,}
# is a syntax error. `[[ =~ ]]` + BASH_REMATCH do exist in 3.2, and the regex
# must stay in an UNQUOTED variable -- quoting it makes 3.2 match it literally.
_kipi_loopback_host() {
  local h re
  h="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
  case "$h" in
    localhost|*.localhost|::1|0.0.0.0|0) return 0 ;;
  esac
  re='^127\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$'
  if [[ "$h" =~ $re ]]; then
    [ "${BASH_REMATCH[1]}" -le 255 ] && [ "${BASH_REMATCH[2]}" -le 255 ] \
      && [ "${BASH_REMATCH[3]}" -le 255 ] && return 0
  fi
  return 1
}

if [ -n "${KIPI_LINEAR_API_URL:-}" ]; then
  _KHOST="${KIPI_LINEAR_API_URL#*://}"   # drop scheme
  _KHOST="${_KHOST%%/*}"                 # drop path
  _KHOST="${_KHOST##*@}"                 # drop userinfo
  case "$_KHOST" in
    \[*\]*) _KHOST="${_KHOST#\[}"; _KHOST="${_KHOST%%\]*}" ;;  # [::1]:8080 -> ::1
    *)      _KHOST="${_KHOST%%:*}" ;;                          # host:port  -> host
  esac
  if _kipi_loopback_host "$_KHOST"; then
    printf 'slack-notify: REFUSED to page a human -- fixture run (KIPI_LINEAR_API_URL host "%s" is loopback). Message NOT sent: %s\n' \
           "$_KHOST" "$MSG" >&2
    exit 0
  fi
fi

DELIVERED=0
if [ "$DELIVER" -eq 1 ]; then
  HOOK="${KIPI_SLACK_WEBHOOK:-}"
  if [ -z "$HOOK" ] && [ -f "$HOME/.config/kipi/slack-webhook" ]; then
    HOOK="$(tr -d '\n\r' < "$HOME/.config/kipi/slack-webhook")"
  fi
  if [ -n "$HOOK" ]; then   # unconfigured -> silent, so callers never break
    PAYLOAD="$(python3 -c "import json,sys; print(json.dumps({'text': sys.argv[1]}))" "$MSG" 2>/dev/null)"
    if [ -n "$PAYLOAD" ] \
       && curl -fsS -X POST -H 'Content-type: application/json' --data "$PAYLOAD" "$HOOK" >/dev/null 2>&1; then
      DELIVERED=1
    fi
  fi
fi

# --- THE MACHINE SINK --------------------------------------------------------
# The founder's actual requirement is not "fewer pings", it is "they should go to
# you or sana". So a receipt is not dropped, it is ROUTED: every outcome lands
# here as one JSON row, and notify-receipts-surface.py reads it at SessionStart
# so the agent sees overnight machine activity instead of the founder seeing it.
#
# THAT SENTENCE WAS A CLAIM BEFORE IT WAS A FACT, and PR #72 review caught it as
# a major. The surfacer did not exist; nothing in the repo opened this file. So
# "recorded, not delivered" meant three dispatch pages that say the Linear loop
# is DEAD reached no human AND no machine, while page_once wrote its dedupe
# marker because this script exits 0 for a receipt. A sink with no reader is a
# drop with extra steps. The reader ships alongside this file now, is wired into
# SessionStart in BOTH .claude/settings.json and settings-template.json, and
# test-notify-receipts-surface.sh fails loudly if it goes missing again.
#
# READ-STATE LIVES IN A CURSOR THE READER OWNS, NOT IN THE ROW. A `read` field
# here would have made the surfacer a second writer to a file whose entire
# design is that two dispatchers, a converge run and a heartbeat cannot corrupt
# it. One writer per file: this script owns the ledger, the surfacer owns
# <ledger>.cursor.
#
# AT THE SOURCE, NOT BY POLLING SLACK. ASK-294 forbids a Slack reader and it is
# right: the producer already knows the condition, so round-tripping it through a
# chat channel would add a failure mode and buy nothing. The producer writes the
# ledger directly; Slack stays a delivery endpoint with no read path.
#
# SINGLE WRITER VIA flock, not `>>`. Up to two dispatchers, a converge run and a
# heartbeat can call this in the same second, and an append is only atomic below
# the pipe buffer -- the voice-lint nudge already posts a ~700-byte multi-line
# body, and an interleaved write would corrupt two rows, not one.
RECEIPTS="${KIPI_NOTIFY_RECEIPTS:-$HOME/.config/kipi/notify-receipts.jsonl}"
python3 - "$RECEIPTS" "$KIND" "$CLASS" "$DELIVERED" "$REFUSED" "$REASON" "$LABEL" "$MSG" <<'PY' 2>/dev/null || true
import fcntl, json, os, sys, time
path, kind, klass, delivered, refused, reason, label, msg = sys.argv[1:9]
os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
row = {
    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "label": label,
    "kind": kind,
    "class": klass or None,
    "delivered": delivered == "1",
    "refused": refused == "1",
    "reason": reason,
    "message": msg,
}
with open(path, "a", encoding="utf-8") as fh:
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    fh.flush()
    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
PY

if [ "$REFUSED" -eq 1 ]; then
  # Loud, and on stderr rather than dropped: the producer is misconfigured and
  # somebody reading a run-log has to be able to see which call was turned away.
  printf 'slack-notify: REFUSED -- %s. Message recorded to %s, NOT delivered: %s\n' \
         "$REASON" "$RECEIPTS" "$MSG" >&2
  exit 2
fi
exit 0
