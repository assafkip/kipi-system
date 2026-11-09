#!/usr/bin/env bash
# reviewer-resolve.sh -- THE ONE reviewer resolver (ASK-3831).
#
# Sourced, never executed. Pairs with test/test-reviewer-resolve.sh.
#
# WHY THIS FILE EXISTS. The reviewer fallback was implemented FOUR times and not
# one of them ever reached a second Codex account:
#
#   pr-review-agent.sh    codex exec, then the Opus fallback, marked degraded
#   linear-worker.sh      CODEX_CMD, then SECOND_RUNNER_FALLBACK
#   plugins/kipi-dsse/commands/issue-review.md   prose: "use another row and stamp what ran"
#   plugins/prd-os/commands/prd-review.md        prose
#
# Codex went out of credits on 2026-09-16. Each site recorded that outage PER PR
# -- 24 cap tickets, and every round labelled "Codex" since that date was in fact
# a degraded Opus stand-in -- while NO health event ever said the fleet had been
# running on one reviewer for seven weeks. Four implementations of one decision
# is four places for it to drift, and a per-PR record of a fleet-wide outage is
# noise that hides the one fact an operator needed.
#
# WHAT IT OWNS, and the reason each belongs here and not at a call site:
#
#   1. THE CHAIN ORDER. codex(primary) -> codex(other account) -> claude. One
#      list, so a new rung reaches every call site in one edit.
#   2. THE ONLY `codex exec` CONSTRUCTION in this directory. A second place that
#      knows how to invoke codex is a second place the sandbox flag, the
#      --ignore-user-config flag or the account can be forgotten.
#   3. THE STAMPS. codex-review / codex-adversarial / claude-review /
#      claude-adversarial, so "which engine actually ran" is one vocabulary.
#   4. THE OUTAGE LEDGER. At most ONE event per account per UTC day, which is
#      what turns 24 per-PR tickets into one health line.
#
# WHAT IT DELIBERATELY DOES NOT OWN. It does not decide whether an answer is a
# usable review -- `review_is_usable` in pr-verdict-lib.sh is the single reader
# of that question and stays there. The resolver names candidates; the call site
# runs them and judges the answer. Collapsing the two would give this file a
# second definition of "complete", which is the sp-c0a9dac3 defect class.
#
# HOW THE SECOND ACCOUNT IS SELECTED IS A FOUNDER DECISION STILL OPEN (asked on
# ASK-3831). Until it is answered the slot is a CODEX_HOME path, because that is
# the variable codex itself reads for its auth and config, so a second logged-in
# account is a second directory and needs no codex feature we have not probed.
# If the founder picks a `codex login` profile or a different config path
# instead, THIS FILE is the only place that changes.

# Guard against double-sourcing: several call sites source both this and
# pr-verdict-lib.sh, and pr-verdict-lib.sh may come to source this.
[ -n "${KIPI_REVIEWER_RESOLVE_LOADED:-}" ] && return 0
KIPI_REVIEWER_RESOLVE_LOADED=1

REVIEWER_RESOLVE_STATE_DIR="${KIPI_STATE_DIR:-$HOME/.config/kipi}"

# The account name recorded on a verdict record for the primary login. Not a
# path: the primary account is whatever `codex exec` resolves by itself, which is
# the behaviour every review before this change had.
REVIEWER_PRIMARY_ACCOUNT="primary"

# ---------------------------------------------------------------------------
# The second Codex account
# ---------------------------------------------------------------------------

# reviewer_secondary_home -> prints the second account's CODEX_HOME, or nothing.
#
# AN ABSENT DIRECTORY IS NOT A CONFIGURED ACCOUNT. A CODEX_HOME pointing at
# nothing makes `codex exec` fail with an auth error, which `is_environmental`
# reads as "the runner is unavailable" -- so a typo in this variable would look
# like a fleet-wide Codex outage on every PR. Absent means not configured.
reviewer_secondary_home() {
  local home="${KIPI_CODEX_SECONDARY_HOME:-}"
  [ -n "$home" ] || return 0
  [ -d "$home" ] || return 0
  printf '%s' "$home"
}

# reviewer_secondary_account -> the NAME recorded for the second account.
# Overridable because the basename of a config directory is an implementation
# detail and the founder may call the account something else.
reviewer_secondary_account() {
  local home
  home="$(reviewer_secondary_home)" || return 0
  [ -n "$home" ] || return 0
  printf '%s' "${KIPI_CODEX_SECONDARY_LABEL:-$(basename "$home")}"
}

# ---------------------------------------------------------------------------
# The stamps
# ---------------------------------------------------------------------------

# reviewer_stamp <codex|claude> <review|adversarial>
#
# REFUSES an unknown role rather than defaulting. A silent default would stamp an
# adversarial round as an ordinary review, and the stamp is what tells a later
# reader which bar the code was held to.
reviewer_stamp() {
  local engine="${1:-}" role="${2:-}"
  case "$engine" in codex|claude) ;; *) return 2 ;; esac
  case "$role" in review|adversarial) ;; *) return 2 ;; esac
  printf '%s-%s' "$engine" "$role"
}

# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------

# reviewer_candidates <review|adversarial>
#
# Prints the ordered chain, one candidate per line, TAB separated:
#     <engine>\t<account>\t<stamp>
#
# The caller walks it top to bottom and stops at the first candidate whose
# answer is a usable review. Opus is always last and always present: if nothing
# filled a required `kipi/reviewer-approved`, every PR in the repo would wedge
# forever, which is the hazard the degraded fallback was built for in July.
reviewer_candidates() {
  local role="${1:-review}" stamp second
  stamp="$(reviewer_stamp codex "$role")" || return 2
  printf '%s\t%s\t%s\n' codex "$REVIEWER_PRIMARY_ACCOUNT" "$stamp"
  second="$(reviewer_secondary_account)"
  [ -n "$second" ] && printf '%s\t%s\t%s\n' codex "$second" "$stamp"
  printf '%s\t%s\t%s\n' claude "-" "$(reviewer_stamp claude "$role")"
}

# ---------------------------------------------------------------------------
# The one codex exec construction
# ---------------------------------------------------------------------------

# reviewer_codex_cmd <account> -> the command prefix that runs codex for it.
#
# Caller appends its own flags (the sandbox, --model, -C, the prompt). This
# function owns only the part that differs per account, plus the base command,
# so no call site can invent a second way to reach codex.
#
# INJECTABLE, for the same reason KIPI_PR_REVIEWER is (linear-worker.sh:102):
# otherwise every "both Codex accounts are out" test case bills two real model
# runs, so the branch stays untested -- which is exactly how one account's worth
# of fallback shipped four separate times.
#
# `--ignore-user-config` is NOT set here: it is a reviewer-specific choice
# (pr-review-agent.sh explains why the reviewer must not load this fleet's own
# agent config) and the worker's second runner deliberately does not want it.
reviewer_codex_cmd() {
  local account="${1:-}" home
  if [ "$account" = "$REVIEWER_PRIMARY_ACCOUNT" ]; then
    printf '%s' "${KIPI_CODEX_RUNNER:-codex exec}"
    return 0
  fi
  home="$(reviewer_secondary_home)"
  if [ -n "$home" ] && [ "$account" = "$(reviewer_secondary_account)" ]; then
    if [ -n "${KIPI_CODEX_RUNNER_2:-}" ]; then
      printf '%s' "$KIPI_CODEX_RUNNER_2"
    else
      # %q, NOT %s (PR #701 review, minor 2). What this returns is spliced into a
      # `bash -c "<string>"` that bash RE-PARSES -- pr-review-agent.sh run_engine
      # and linear-worker.sh's CODEX_CMD_2 both do that. A home with a space in it
      # split there: bash read `CODEX_HOME=/Users/x/codex` and then tried to run
      # `home`, exit 127. `is_environmental` reads 127 as the machine refusing, so
      # a correctly configured second account was recorded as that account's
      # OUTAGE and the chain fell to Opus. %q is quoting for exactly that reuse.
      printf 'CODEX_HOME=%q %s' "$home" "${KIPI_CODEX_RUNNER:-codex exec}"
    fi
    return 0
  fi
  # NEVER FALL BACK TO THE PRIMARY. An unrecognised account silently running on
  # the primary login would record a review as coming from an account that never
  # saw the code, which is the false-provenance shape sp-8379cd52 already cost
  # this fleet once.
  return 2
}

# ---------------------------------------------------------------------------
# The outage ledger: one event per account per UTC day
# ---------------------------------------------------------------------------
#
# WHY A DAY AND NOT A TRANSITION. `note_degraded_transition` in pr-review-agent.sh
# already pages on the edges, and it still produced 24 cap tickets, because the
# edge it watches is per-repo state while the outage is fleet-wide and lasted
# seven weeks. A day stamp is the unit an operator actually reads: "Codex has
# been out since the 16th" is one fact, not 24.
#
# WHY A FILE AND NOT A LINEAR CALL FROM HERE. This runs inside every review, on
# every PR, in a sandbox that may have no network. The consumer is
# fleet-health-daily.py, which already owns the "file one deduped issue for
# Sana" mechanism and the `needs-triage` posture. One producer, one consumer.
# linear-filer: human-in-the-loop -- this file never creates a Linear issue; it
# appends a local JSONL row that fleet-health-daily.py reads.

reviewer_outage_events_path() {
  printf '%s/codex-outage-events.jsonl' "$REVIEWER_RESOLVE_STATE_DIR"
}

reviewer_outage_state_path() {
  printf '%s/codex-account-health.json' "$REVIEWER_RESOLVE_STATE_DIR"
}

reviewer_outage_lock_path() {
  printf '%s.lock' "$(reviewer_outage_state_path)"
}

_reviewer_day() { date -u +%Y-%m-%d; }
_reviewer_ts()  { date -u +%Y-%m-%dT%H:%M:%SZ; }

# ---------------------------------------------------------------------------
# WHAT THE LEDGER MAY CARRY: a code, never the line Codex printed
# ---------------------------------------------------------------------------
#
# A FINDING CARRIES A REFERENCE, NEVER UNTRUSTED TEXT (ASK-204, and ASK-3988 /
# sp-762d494b already decided this exact question one layer over). The reason
# written here is read by fleet-health-daily.py and published VERBATIM in a
# Linear issue body, and a Linear issue filed by that script is PERMANENT. The
# PR #701 review found the hole in the prose half: issue-review.md and
# prd-review.md told the model to pass "the refusal line Codex printed", which
# is model-adjacent output of unbounded length and arbitrary syntax -- the
# denylist-against-shell-syntax shape whose nine consecutive bypasses are what
# ASK-204 exists to end.
#
# So the ledger carries a CODE out of a closed vocabulary, coerced HERE rather
# than trusted from the caller. A caller cannot opt out: prose, a shell call
# site and a future one all land on the same coercion.
#
# WHAT IS LOST, AND WHERE IT STILL LIVES. The PR number, the issue id and
# Codex's own wording drop out of the ledger. Each already goes to its caller's
# own log, which is ASK-3988's rule in one line -- the marker to the ticket, the
# whole line to the log: pr-review-agent.sh prints it to stderr, linear-worker.sh
# to the worker log. Nothing an operator needs is only here.
REVIEWER_OUTAGE_CODES="usage-limit out-of-credits auth overloaded exec-failure unclassified"

# reviewer_outage_code <text> -> exactly one code from REVIEWER_OUTAGE_CODES.
#
# COARSE ON PURPOSE, AND IT DEGRADES TOWARD `unclassified`, never toward
# publishing the input. These patterns are a bucketing of the markers
# env-failure-lib.sh already owns in ENV_MARKERS / CODEX_OUTAGE_MARKERS; that
# file stays the single reader of "is this the machine refusing". A marker added
# there that is not bucketed here falls to `unclassified`, which costs one grain
# of detail in the health line and never leaks a byte.
reviewer_outage_code() {
  local t
  t="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
  case "$t" in
    *"out of credits"*|*"credit balance is too low"*) printf 'out-of-credits' ;;
    *"usage limit"*|*"hit your weekly limit"*|*"hit your usage limit"*|\
    *"hit your session limit"*|*"hour limit"*)        printf 'usage-limit' ;;
    *"invalid api key"*|*authentication_error*|*"please run /login"*) printf 'auth' ;;
    *overloaded*|*529*)                              printf 'overloaded' ;;
    # BOTH SPELLINGS OF "the process died". This fleet writes the exit status
    # two ways and the bucket missed one until a test caught it: pr-review-agent.sh
    # passes `exit $rc on PR #N`, while the worker's and the suite's wording is
    # `rc=N`. A bucket that knows one spelling reports the other as
    # `unclassified`, which loses the one distinction the health line is for.
    *exit\ [0-9]*|*rc=[0-9]*|*rc\ [0-9]*|*timed\ out*|*timeout*) printf 'exec-failure' ;;
    *)                                               printf 'unclassified' ;;
  esac
}

# _reviewer_code_or_unclassified <text> -> the text when it is ALREADY a code,
# else the bucketed code. Both shapes reach the writer: linear-worker.sh hands
# it a marker line, and a caller that resolved the code itself hands the code.
# Membership is checked against the list rather than assumed, so a caller cannot
# smuggle free text through by making it look code-shaped.
_reviewer_code_or_unclassified() {
  local want="${1:-}" c
  for c in $REVIEWER_OUTAGE_CODES; do
    [ "$want" = "$c" ] && { printf '%s' "$c"; return 0; }
  done
  reviewer_outage_code "$want"
}

# _reviewer_write_health <fail|ok> <account> [reason]
#
# THE ONE WRITER of both the state file and the event log, and the only holder of
# the lock. Both public notes below delegate here.
#
# IT USED TO BE TWO WRITERS, EACH UNLOCKED (PR #701 review, minor 3). A
# fleet-wide credit outage fails every live review in the same instant -- the
# worker's second runner plus every open PR's reviewer -- and each process read
# "no event filed today" before any of them wrote one, so the file whose header
# promises ONE event per account per UTC day held N, and the health finding's
# "first seen" line came from whichever row landed first. Two writers of one file
# is also two chances for the next change to serialise only one of them.
#
# Always exits 0: a reviewer must never die because its own bookkeeping failed.
_reviewer_write_health() {
  local mode="${1:-fail}" account="${2:-unknown}" reason="${3:-}"
  # THE COERCION IS HERE AND NOWHERE ELSE (PR #701 review round 2, major). This
  # is the single writer of both files, so it is the only place a caller's text
  # can be stopped before it becomes a permanent Linear issue body. Doing it at
  # the two public notes below would leave a third caller free to bypass it, and
  # doing it in the detector would leave the untrusted bytes on disk for anything
  # else that reads the ledger later.
  reason="$(_reviewer_code_or_unclassified "$reason")"
  mkdir -p "$REVIEWER_RESOLVE_STATE_DIR" 2>/dev/null || return 0
  python3 - "$(reviewer_outage_state_path)" "$(reviewer_outage_events_path)" \
           "$(reviewer_outage_lock_path)" "$mode" "$account" "$reason" \
           "$(_reviewer_day)" "$(_reviewer_ts)" <<'PY' 2>/dev/null || true
import fcntl, json, os, sys, time
(state_path, events_path, lock_path, mode, account, reason,
 day, ts) = sys.argv[1:9]

# flock, not a lock FILE. The kernel releases it when the holder dies, so a
# reviewer killed by its own timeout mid-write cannot wedge the next one -- which
# a pid-file or an O_EXCL marker would. Non-blocking with a deadline rather than a
# plain blocking acquire: past 5s of contention this files the event UNSERIALISED,
# because a duplicate health line is recoverable and a lost outage is not.
lock = None
try:
    lock = open(lock_path, "a+")
    deadline = time.time() + 5
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() >= deadline:
                break
            time.sleep(0.02)
except Exception:
    lock = None   # no locking available on this filesystem: proceed unserialised

# A CORRUPT LEDGER MUST NOT SILENCE THE EVENT. Read failure is treated as "no
# event filed yet today", which errs toward one extra health line rather than
# toward an outage nobody hears about.
try:
    with open(state_path) as fh:
        state = json.load(fh)
    if not isinstance(state, dict):
        state = {}
except Exception:
    state = {}

row = state.get(account) if isinstance(state.get(account), dict) else {}
append = False
if mode == "ok":
    # The day stamp comes OFF, so the next outage earns its own event and the
    # health consumer can tell a recovered transient from a live outage. The
    # event already on disk is never rewritten: the log is append-only, and
    # `last_ok` is what says the account answered after it.
    row.pop("outage_day", None)
    row["last_ok"] = ts
    row["fails"] = 0
else:
    append = row.get("outage_day") != day
    # `last_reason_code`, not `last_reason`: the key name says what the value is
    # allowed to be, so a later reader cannot mistake it for the line Codex
    # printed and publish it (ASK-204).
    row.update({"outage_day": day, "last_fail": ts, "last_reason_code": reason})
    row["fails"] = int(row.get("fails") or 0) + 1
state[account] = row

# A PID-UNIQUE TEMP. One shared `.tmp` name is safe under the lock and collides
# on the degraded unserialised path above, which would publish a half-written
# state file through os.replace.
tmp = "%s.tmp.%d" % (state_path, os.getpid())
try:
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, state_path)
except Exception:
    try:
        os.unlink(tmp)
    except OSError:
        pass

if append:
    with open(events_path, "a") as fh:
        fh.write(json.dumps({"kind": "codex-outage", "account": account,
                             "day": day, "ts": ts, "reason_code": reason},
                            sort_keys=True) + "\n")
PY
  return 0
}

# reviewer_note_codex_outage <account> <code-or-marker>
#
# Records that this account could not produce a review. Appends ONE event per
# account per UTC day; later calls the same day update nothing and print nothing.
#
# THE SECOND ARGUMENT IS NOT FREE TEXT and a caller cannot make it so: whatever
# arrives is coerced to one of REVIEWER_OUTAGE_CODES before it is written,
# because what is written lands verbatim in a permanent Linear issue. Pass a
# code, or pass `codex_env_marker`'s closed-vocabulary output and let the
# coercion bucket it. Codex's own line belongs in your log, never here.
reviewer_note_codex_outage() {
  _reviewer_write_health fail "${1:-unknown}" "${2:-}"
}

# reviewer_note_codex_ok <account>
#
# This account answered. Clears its day stamp so the NEXT outage earns its own
# event: an operator who hears nothing after a recovery cannot tell a live
# second opinion from a stand-in wearing its context.
#
# THIS IS THE HALF THE HEALTH CONSUMER READS. fleet-health-daily.py reads the
# append-only event log AND this state, because the log alone cannot say that an
# account which failed at 03:00 answered at 03:01 (PR #701 review, major).
# Every call site that gets a usable answer out of codex calls this.
reviewer_note_codex_ok() {
  _reviewer_write_health ok "${1:-unknown}" ""
}

# reviewer_outage_events_today -> today's RAW event rows, one JSON object per line.
#
# RAW, AND NOT A LIST OF WHO IS DOWN. The log is append-only, so a row here only
# says an account failed at some point today; whether it is still down is the
# state file's answer. The health consumer joins the two
# (fleet-health-daily.py `codex_outage_findings`); this accessor deliberately
# does not, so there is one place that decides "down" and one that reports events.
reviewer_outage_events_today() {
  local ev day
  ev="$(reviewer_outage_events_path)"
  day="$(_reviewer_day)"
  [ -f "$ev" ] || return 0
  python3 - "$ev" "$day" <<'PY' 2>/dev/null || true
import json, sys
path, day = sys.argv[1], sys.argv[2]
with open(path) as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get("day") == day:
            print(json.dumps(row, sort_keys=True))
PY
}
