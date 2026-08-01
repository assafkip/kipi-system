#!/usr/bin/env python3
"""Draft a Definition of Ready onto Linear issues that lack one. Bounded, nightly.

WHY THIS IS THE GATE ON AUTONOMY

The autonomous worker (see q-system/output/plans/linear-autonomous-design-2026-07-26.md)
only picks up issues that satisfy the SDLC standard's Definition of Ready. That is
not bureaucracy, it is the line between "agents get things done in the background"
and "agents produce plausible garbage in the background". Measured 2026-07-26:
125 of 146 issues on the ASK board had no DoR, including all 48 in cole-GTM. Until
that is fixed the worker has almost nothing it can safely touch.

WHY A NIGHTLY DRIP AND NOT ONE BIG PASS

125 issues of LLM judgment in one run is a long unattended session with no
checkpoint, and `claude -p` runs on the founder's SUBSCRIPTION, so it competes with
interactive work. `--limit` keeps each night small and resumable; the backlog
drains over days without a babysitter. That is the same reasoning behind the
open-loops heartbeat's per-instance timeout.

WHY IT APPENDS AND NEVER OVERWRITES

The issue description is the founder's own words. This adds a `## Definition of
Ready` section beneath it and touches nothing else. An LLM rewriting a human's
issue text is not a trade worth making, and Linear issues cannot be deleted here.

THE ONE EXCEPTION: REDRAFT (needs-scope-redrive, 2026-08-01)

There is a second selection mode. `linear-worker.sh` refuses an issue whose DoR
is unexecutable, labels it `needs-scope`, and tells the operator in writing that
"linear-dor-drafter.py re-scopes this ... no action is needed from the founder."
That was FALSE for as long as it had been printed: needs_dor() returned False on
any description containing "Definition of Ready", and a needs-scope issue HAS a
DoR -- having a bad one is exactly why it was refused. So every refusal was
parked permanently behind a message promising the opposite (ASK-148).

A redraft therefore DOES overwrite, but only the `## Definition of Ready` section
and never a byte above it: that section is this job's own prior output, not the
founder's words, so the append-only rule is not in tension with rewriting it.
The bounded-loop rules apply (REDRAFT_CAP, TERMINAL_NOTE) because a redraft loop
that keeps producing unexecutable specs would cycle an issue between the worker
and this job forever.

AUDHD: every drafted DoR carries an Energy mode and a Time Est, per
`.claude/rules/audhd-interaction.md` — an issue the founder cannot pick up by
energy level is not actually ready for a human either.

Exit 0 always: this runs from launchd and must not mark its own job failed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
QROOT = HERE.parent.parent
STATE = Path.home() / ".config" / "kipi" / "linear-dor-state.json"
DOR_HEADING = "## Definition of Ready"
TEAM_KEY = "ASK"

# Where this job's own failures go. Exit 0 keeps launchd calm, which also means
# launchd-health-check.py (it keys on a non-zero LastExitStatus) never sees a bad
# night here. So the run reports itself instead. ONE permanent issue, deduped by
# the kipi-key marker exactly like fleet-health-daily.py, with a comment per
# failing run -- a new issue every night would be its own kind of silence.
FAILURE_REPO = "kipi-system"
FAILURE_KEY = "linear-dor/run-failure"
FAILURE_TITLE = "linear-dor: nightly DoR drafter reported failures"

# ONE definition, used by the writer (the create payload) and by the selector
# (needs_dor). The job's own failure record has no explicit state, so it lands in
# `backlog` and passed the job's own selector -- tomorrow night it would spend one
# of the plist's bounded `claude -p` slots writing LLM prose onto the operator's
# failure log. Matched narrowly on THIS job's key rather than on any kipi-key
# marker: other machine-filed issues (fleet-health-daily's findings) are real work
# items and a DoR helps them. (PR #12 round-2 review, nit.)
FAILURE_MARKER = f"<!-- kipi-key: {FAILURE_KEY} -->"

# The single founder-ping channel (.claude/rules/founder-notifications.md).
# Used ONLY when the report itself could not reach the board -- an open Linear
# issue is the signal on a normal failing night, and a nightly Slack line on top
# of it would train the founder to ignore the channel.
NOTIFY_SCRIPT = HERE / "slack-notify.sh"

# A closed permanent issue must be REOPENED, never quietly commented on. The
# dedup key outlives the issue's state and fetch_remote_state cannot see state
# (its query filters on project and does not select it), so the first time the
# operator did the right thing -- fix the cause, close the issue -- every later
# failing night became a comment on a Done issue with nothing open on the board.
# The detector switched itself off at exactly the moment it was working.
# (PR #12 review, major 1.)
CLOSED_STATE_TYPES = ("completed", "canceled")
REOPEN_TARGET_TYPES = ("unstarted", "backlog")  # prefer Todo, settle for Backlog

# Failures a run could not file (Linear down at 03:00 is the routine unattended
# case) are held in the state file and flushed by the next run. Before this the
# list was dropped to stderr and the state file had no reader anywhere in the
# repo -- a write-only artifact is not a record. (PR #12 review, major 2.)
PENDING_CAP = 50

# Linear can also be down BEFORE anything is attempted (the team lookup at the
# top of main()). That path used to return immediately: no state write, so ran_at
# froze and the file could not serve as a freshness deadman, the held backlog
# silently stopped draining, and launchd saw exit 0. Now the night still leaves a
# heartbeat, and the founder gets ONE ping per outage rather than one per night --
# a nightly line for the whole duration of an outage is how a channel becomes one
# nobody reads (founder-notifications.md: unchanged status is noise, not a ping).
# Edge-triggered off this verdict: any successful run overwrites it, so the next
# outage is a new event and pings again. (PR #12 round-2 review, minor.)
START_UNREACHABLE = "unreachable-at-start"

# ...but edge-triggered alone buys UNBOUNDED silence: miss the one ping and a
# three-week outage is three weeks of nothing. launchd-health-check.py solves the
# same problem with FAIL_PING_TTL_SECONDS = 6h, which for a job that runs once a
# night degenerates to a ping every night. So the cadence is counted in nights
# instead: night 1, then every 7th. Once a week says "still dark" without
# training the founder to swipe the channel away.
START_UNREACHABLE_REPING_NIGHTS = 7

# Linear does NOT answer {"issue": null} for an id it does not have. It answers
# HTTP 200 with an `errors` array, and linear-sync.graphql raises on any errors
# array (linear-sync.py:381). Captured live 2026-07-27 against both a well-formed
# uuid with nothing behind it and a non-uuid string -- identical payload:
#   [{"message": "Entity not found: Issue", ..., "code": "INPUT_ERROR",
#     "statusCode": 400, "userError": true, ...}]
# So "this issue is gone" arrives as an exception indistinguishable from "Linear
# is down" unless something reads the message. Untreated, the operator deleting
# the bot-filed issue meant nothing was ever filed again plus a nightly false
# "Linear unreachable" ping while Linear was fine. (PR #12 round-2 review, major.)
#
# Matched on the message and deliberately NOT on INPUT_ERROR alone: a malformed
# query is also INPUT_ERROR, and reading that as "gone" would fork a new permanent
# issue every night. Linear issues cannot be deleted here (destructive-op-deny.sh
# blocks *delete* and archive), so an over-match is unrecoverable while an
# under-match only holds the failures for the next run.
MISSING_ISSUE_MARKER = "entity not found"

# Escape hatch for a claude installed somewhere CLAUDE_FALLBACKS never heard of
# (nvm, volta, asdf all put it under a versioned dir). A hardcoded list cannot be
# exhaustive; this makes it not the last word.
CLAUDE_BIN_ENV = "KIPI_CLAUDE_BIN"

# Where `claude` lives when PATH does not say. The plist runs `/bin/bash -lc`,
# and `-l` sources BASH login files -- the founder's shell is zsh, so the PATH
# entry for ~/.local/bin never loads under launchd. Interactively it works
# because PATH is inherited from the parent shell, which is why this was invisible
# until the job was actually kickstarted (2026-07-27: 8 of 8 drafts died on
# FileNotFoundError while launchd recorded LastExitStatus=0). Resolving the binary
# here rather than trusting the scheduler's environment fixes it for every caller.
CLAUDE_FALLBACKS = (
    Path.home() / ".local" / "bin" / "claude",
    Path.home() / ".claude" / "local" / "claude",
    Path("/opt/homebrew/bin/claude"),
    Path("/usr/local/bin/claude"),
)

# Statuses worth drafting for. A Done/Canceled issue needs no DoR, and drafting
# onto one would be pure noise on a permanent object.
DRAFTABLE_STATE_TYPES = ("backlog", "unstarted")

# The worker's refusal label. This is the redrive input: the issue is selected
# BECAUSE it carries this, not excluded because it already has a DoR.
NEEDS_SCOPE_LABEL = "needs-scope"

# How many times this job may rewrite one issue's DoR before it stops.
# Three, matching self-healing-retry.md's attempt cap: the same reasoning applies
# (a fourth identical-quality attempt is not new information, it is a slot spent).
REDRAFT_CAP = 3

# The redraft counter lives in the ISSUE DESCRIPTION, not in the state file and
# not in attempts-ledger.py.
#   - not the ledger: out of scope by founder deferral (sp-626e9452), and a
#     read-then-write from a second process is the race that file exists to stop.
#   - not ~/.config/kipi/linear-dor-state.json: that is one machine's scratch. A
#     cap whose count evaporates on a new laptop is not a cap, and the terminal
#     rationale has to be READABLE on the issue by whoever opens it anyway. If
#     the rationale must live on the issue, so must the number behind it.
# Single writer: this job is the only thing that writes this marker, and it
# writes it only inside the one issueUpdate call in apply_redraft/apply_terminal.
REDRAFT_MARKER_RE = re.compile(r"<!--\s*kipi-dor:\s*redrafts=(\d+)(\s+terminal)?\s*-->")

# What goes on the issue when the cap is spent. Deliberately NOT a new escalation
# tier -- the PRD rejects manufactured tiers (codex finding 5). It is an honest
# terminal: a written statement that the machine is out of moves, kept reversible
# by naming the one edit that puts the issue back in the loop.
TERMINAL_NOTE = f"""> **Redraft cap reached ({REDRAFT_CAP} of {REDRAFT_CAP}). This is an honest terminal, not a queue.**
>
> `linear-dor-drafter.py` rewrote this Definition of Ready {REDRAFT_CAP} times and the
> autonomous worker refused it as unexecutable each time. There is no further machine
> move here: a {REDRAFT_CAP + 1}th rewrite would produce a spec of the same quality and
> spend another night's slot. The `needs-scope` label stays ON deliberately, so the
> picker keeps this out of the loop instead of cycling it.
>
> What is missing is a scope decision: what bounded outcome this issue is actually
> asking for. That is a real dead end for this job, recorded here rather than left
> looking like pending work.
>
> To put it back in the loop: delete the `<!-- kipi-dor: ... -->` line above. The
> counter resets and the next nightly run redrafts it again."""

PROMPT = """You are writing a Definition of Ready for one Linear issue in a software fleet.

Repo/project: {project}
Title: {title}

Existing description:
---
{description}
---

Write ONLY the body of a "Definition of Ready" section. No preamble, no heading, no
code fences. Use exactly these five bullets, in this order:

- **Outcome:** one sentence, what is true when this is done, in plain terms.
- **Files:** the explicit paths you'd expect to touch. If genuinely unknown, say
  "unknown - needs a recon pass" rather than inventing paths.
- **Check:** the command that proves it works, or that currently fails. Runnable.
  If none exists, say what would have to be written.
- **Blast radius:** does this propagate to other repos via `kipi update`? Is it
  skeleton-only or fleet-wide? Does it touch always-on rules or settings?
- **Not doing:** the adjacent thing this issue explicitly does not cover.

Then one final line exactly like:
**Energy:** <Quick Win|Deep Focus|People|Admin> · **Time Est:** <e.g. 30 min, 2 h, half day>

Be concrete and short. If the issue is too vague to answer a bullet honestly, write
what is missing instead of guessing. Never invent a file path or a command that you
cannot see evidence for."""


REDRAFT_PROMPT = """You are REWRITING a Definition of Ready that an autonomous coding agent
already refused as unexecutable. Attempt {attempt} of {cap}.

Repo/project: {project}
Title: {title}

The Definition of Ready it refused:
---
{old_dor}
---

Why it refused it:
---
{reason}
---

Rewrite the DoR so THAT refusal no longer applies. The usual cause is scope: the
spec asked for an unbounded amount of work, or asked for a judgment call the agent
cannot make from a non-interactive session. Cut it down to ONE bounded change that
a single agent session can finish and prove. Narrowing the outcome is correct and
expected; do not preserve ambition you cannot bound.

Write ONLY the body of the section. No preamble, no heading, no code fences. Use
exactly these five bullets, in this order:

- **Outcome:** one sentence, what is true when this is done, in plain terms.
- **Files:** the explicit paths you'd expect to touch. If genuinely unknown, say
  "unknown - needs a recon pass" rather than inventing paths.
- **Check:** the command that proves it works, or that currently fails. Runnable.
  If none exists, say what would have to be written.
- **Blast radius:** does this propagate to other repos via `kipi update`? Is it
  skeleton-only or fleet-wide? Does it touch always-on rules or settings?
- **Not doing:** the adjacent thing this issue explicitly does not cover. Name here
  whatever you cut out of the old scope.

Then one final line exactly like:
**Energy:** <Quick Win|Deep Focus|People|Admin> · **Time Est:** <e.g. 30 min, 2 h, half day>

Be concrete and short. Never invent a file path or a command you cannot see evidence for."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _linear():
    spec = importlib.util.spec_from_file_location("ls", HERE / "linear-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# `labels` is new (needs-scope-redrive). Before it this query selected no labels
# at all, so a label-driven selection was not merely unimplemented, it had no data
# to run on. The IDs come with the names because dropping the label is an
# issueUpdate with the FULL replacement labelIds set -- Linear has no remove-one
# mutation, so the survivors have to be known at write time.
ISSUES_Q = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}}},first:250,after:$a){
  nodes{id identifier title description project{name} state{name type}
        labels{nodes{id name}}}
  pageInfo{hasNextPage endCursor}}}"""

# The worker writes WHY it refused as a comment, not into the description. A
# redraft that cannot see that reason is a coin flip that spends one of three
# capped attempts, so it is fetched per candidate rather than skipped. Bounded by
# --limit (8 a night), which is why this is a per-issue query and not another
# field on the 250-issue page.
ISSUE_COMMENTS_Q = """query($id:String!){issue(id:$id){comments(last:15){nodes{body}}}}"""

UPDATE_M = """mutation($id:String!,$input:IssueUpdateInput!){
  issueUpdate(id:$id,input:$input){success issue{identifier}}}"""

ISSUE_STATE_Q = """query($id:String!){issue(id:$id){id identifier state{name type}}}"""

TEAM_STATES_Q = """query($t:String!){team(id:$t){
  states(first:50){nodes{id name type position}}}}"""

REOPEN_M = """mutation($id:String!,$s:String!){
  issueUpdate(id:$id,input:{stateId:$s}){success}}"""


def needs_dor(issue: dict) -> bool:
    if (issue.get("state") or {}).get("type") not in DRAFTABLE_STATE_TYPES:
        return False
    desc = issue.get("description") or ""
    # This job's own failure record. Drafting onto it burns a bounded nightly
    # slot to write prose onto a machine-written log. See FAILURE_MARKER.
    if FAILURE_MARKER in desc:
        return False
    if DOR_HEADING in desc:
        return False
    # The generated capability issues already carry a DoR under their own wording.
    if "Definition of Ready" in desc:
        return False
    return True


def notify(message: str) -> bool:
    """Ping the founder through the one channel. Never raises, never blocks long.

    Reserved for the case where this reporter could NOT put the failure on the
    board. A ping for something already filed as a Linear issue is noise, and a
    noisy channel is a channel nobody reads at 03:00.
    """
    if not NOTIFY_SCRIPT.exists():
        return False
    try:
        subprocess.run(["bash", str(NOTIFY_SCRIPT), message], timeout=20)
        return True
    except Exception:  # noqa: BLE001 - a failed ping must not fail the run
        return False


def read_state() -> dict:
    """Last run's state file. {} when missing or corrupt -- never raises, because
    a job that dies reading its own bookkeeping is worse than one that starts
    fresh. The state file's only reader lives here and in read_pending()."""
    try:
        data = json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def read_pending(state: dict | None = None) -> list:
    """Failures an earlier run could not file."""
    items = (read_state() if state is None else state).get("pending_failures")
    if not isinstance(items, list):
        return []
    return [str(i) for i in items][-PENDING_CAP:]


def write_state(**fields) -> None:
    """The single writer. Every exit path from main() goes through it, including
    the ones that did no work, so `ran_at` is a real heartbeat rather than a
    'the last time this job got all the way to the end' timestamp."""
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(fields, indent=2))


def claude_binary() -> str | None:
    """Absolute path to the `claude` CLI, or None.

    KIPI_CLAUDE_BIN first, then PATH, then the known install locations.
    """
    override = os.environ.get(CLAUDE_BIN_ENV)
    if override:
        path = Path(override).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        print(f"  {CLAUDE_BIN_ENV}={override} is not an executable file, ignoring it",
              file=sys.stderr)
    found = shutil.which("claude")
    if found:
        return found
    for candidate in CLAUDE_FALLBACKS:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def draft_one(issue: dict, timeout: int) -> tuple:
    """One `claude -p` call. Returns (dor_body, "") or (None, reason).

    The reason travels with the failure: it is the line report_failures puts on
    the Linear issue. Collapsing every cause into one string told the operator a
    count and never a cause -- a missing binary read exactly like a timeout, and
    the missing binary is the bug this whole job-migration exists because of.
    (PR #12 review, minor 4.)
    """
    binary = claude_binary()
    if not binary:
        reason = (f"no claude binary (${CLAUDE_BIN_ENV} unset or bad, not on PATH, "
                  f"not in {len(CLAUDE_FALLBACKS)} known install locations)")
        print(f"  {issue['identifier']}: {reason}", file=sys.stderr)
        return None, reason
    prompt = PROMPT.format(
        project=(issue.get("project") or {}).get("name") or "unassigned",
        title=issue.get("title") or "",
        description=(issue.get("description") or "(empty)")[:4000],
    )
    try:
        res = subprocess.run(
            [binary, "-p", prompt, "--permission-mode", "acceptEdits"],
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        reason = f"claude call failed ({type(exc).__name__} after {timeout}s)"
        print(f"  {issue['identifier']}: {reason}", file=sys.stderr)
        return None, reason
    out = (res.stdout or "").strip()
    if res.returncode != 0 or len(out) < 60:
        reason = f"claude exited rc={res.returncode} with {len(out)} chars of output"
        print(f"  {issue['identifier']}: {reason}", file=sys.stderr)
        return None, reason
    # Strip any stray fencing the model added despite instructions.
    out = re.sub(r"^```[a-z]*\n|\n```$", "", out).strip()
    # ...and any narration before the first bullet. Observed on the first live run
    # (ASK-149): the model prefixed "Both paths verified: ... Re-emitting the DoR
    # unchanged:" before the content. The prompt says no preamble; a prompt is not
    # enforcement, so cut deterministically at the first Outcome bullet.
    start = re.search(r"(?m)^[-*]\s+\*\*Outcome:\*\*", out)
    if start:
        out = out[start.start():].strip()
    if "**Energy:**" not in out:
        reason = f"draft had no Energy/Time line ({len(out)} chars), not written"
        print(f"  {issue['identifier']}: {reason}", file=sys.stderr)
        return None, reason
    return out, ""


def fetch_draftable(ls, team_id: str) -> list:
    """Every issue on the team that still lacks a Definition of Ready."""
    issues, after = [], None
    while True:
        page = ls.graphql(ISSUES_Q, {"t": team_id, "a": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return [i for i in issues if needs_dor(i)]


def _is_missing_issue(exc: Exception) -> bool:
    """True when Linear said the issue does not exist, as opposed to being down.
    See MISSING_ISSUE_MARKER for why this is matched on the message."""
    return MISSING_ISSUE_MARKER in str(exc).lower()


def _live_issue(ls, linear_id: str):
    """The permanent failure issue as Linear has it right now, or None if it is
    gone. fetch_remote_state cannot answer this: its query filters on project and
    never selects state, so the dedup key alone says "exists", not "is open".

    A deleted issue and a down Linear both arrive here as an exception; only the
    first returns None. The second is re-raised so the caller holds the failures
    for the next run instead of forking a permanent issue it cannot delete.
    """
    try:
        return (ls.graphql(ISSUE_STATE_Q, {"id": linear_id}) or {}).get("issue")
    except Exception as exc:  # noqa: BLE001 - re-raised unless it is a deletion
        if not _is_missing_issue(exc):
            raise
        print(f"  the recorded failure issue {linear_id} is gone from Linear; "
              f"filing a fresh one", file=sys.stderr)
        return None


def _reopen(ls, team_id: str, linear_id: str) -> bool:
    """Move a closed failure issue back to an open state. False if that failed.

    Swallows its own errors on purpose: a reopen that Linear refuses must still
    leave the failure detail ON the issue and tell the founder the board has
    nothing open, which is strictly more than raising here would achieve.
    """
    try:
        nodes = (((ls.graphql(TEAM_STATES_Q, {"t": team_id}) or {}).get("team") or {})
                 .get("states") or {}).get("nodes") or []
        open_states = [s for s in nodes if s.get("type") in REOPEN_TARGET_TYPES]
        open_states.sort(key=lambda s: (REOPEN_TARGET_TYPES.index(s["type"]),
                                        s.get("position") or 0))
        if not open_states:
            print("  no open workflow state to reopen into", file=sys.stderr)
            return False
        res = ls.graphql(REOPEN_M, {"id": linear_id, "s": open_states[0]["id"]})
        return bool((res.get("issueUpdate") or {}).get("success"))
    except Exception as exc:  # noqa: BLE001 - see the docstring
        print(f"  reopen failed: {str(exc)[:120]}", file=sys.stderr)
        return False


def report_failures(ls, failures: list, carried: int = 0) -> str:
    """Put the failures onto ONE permanent Linear issue, and keep it OPEN.

    Returns "none" | "created" | "commented" | "reopened" | "reopen-failed"
    | "unreachable". `carried` is how many of `failures` came from an earlier run
    that could not file them, so the report can say when they actually happened.

    Never raises. This runs in the last breath of a launchd job; a reporter that
    throws would replace a silent failure with a louder one and still tell the
    founder nothing. Every exit path here is a return.
    """
    if not failures:
        return "none"

    detail = "\n".join(f"- {f}" for f in failures)
    header = f"Run {_now()} — {len(failures)} failure(s)"
    if carried:
        header += (f" ({carried} carried from an earlier run that could not reach "
                   f"Linear)")
    try:
        team_id, project, remote_keys = ls.fetch_remote_state(TEAM_KEY, FAILURE_REPO)
        existing = dict(remote_keys).get(FAILURE_KEY) or ls.read_ledger().get(FAILURE_KEY)
        live = _live_issue(ls, existing["linear_id"]) if (
            existing and existing.get("linear_id")) else None

        if live:
            verdict = "commented"
            if (live.get("state") or {}).get("type") in CLOSED_STATE_TYPES:
                verdict = "reopened" if _reopen(ls, team_id, live["id"]) else "reopen-failed"
            ls.graphql(ls.COMMENT_CREATE, {"input": {
                "issueId": live["id"], "body": f"{header}:\n\n{detail}",
            }})
            ident = live.get("identifier") or FAILURE_KEY
            print(f"  reported {len(failures)} failure(s) on {ident} ({verdict})")
            if verdict == "reopen-failed":
                notify(f"linear-dor: {len(failures)} failure(s) noted on {ident}, but it "
                       f"is CLOSED and would not reopen. Nothing is open on the board.")
            return verdict

        payload = {
            "title": FAILURE_TITLE[:250],
            "description": (
                f"{FAILURE_MARKER}\n\n"
                f"`com.kipi.linear-dor` had failures it cannot signal through its exit "
                f"code (it exits 0 by design so launchd does not restart-loop it).\n\n"
                f"{header}:\n\n{detail}\n\n"
                f"Full stderr: `~/.config/kipi/linear-dor.err`. "
                f"Filed by `linear-dor-drafter.py`."
            ),
            "teamId": team_id,
        }
        if project:
            payload["projectId"] = project["id"]
        node = (ls.graphql(ls.ISSUE_CREATE, {"input": payload})
                .get("issueCreate") or {}).get("issue") or {}
        if not node.get("id"):
            print("  failure report refused by Linear", file=sys.stderr)
            notify(f"linear-dor: Linear refused the failure report; "
                   f"{len(failures)} failure(s) held for the next run.")
            return "unreachable"
        ls.append_ledger([{
            "key": FAILURE_KEY, "kind": "issue", "linear_id": node["id"],
            "identifier": node.get("identifier"), "source": "linear-dor",
        }])
        print(f"  filed {node.get('identifier')} with {len(failures)} failure(s)")
        return "created"
    except Exception as exc:  # noqa: BLE001 - see the never-raise note above
        print(f"  linear unreachable, {len(failures)} failure(s) NOT filed: "
              f"{str(exc)[:120]}", file=sys.stderr)
        notify(f"linear-dor: Linear unreachable, {len(failures)} failure(s) could not "
               f"be filed ({str(exc)[:80]}). Held for the next run.")
        return "unreachable"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=5, help="issues per run (default 5)")
    ap.add_argument("--apply", action="store_true", help="write to Linear")
    ap.add_argument("--project", help="only this project")
    ap.add_argument("--timeout", type=int, default=300, help="seconds per claude call")
    args = ap.parse_args()

    ls = _linear()
    prior = read_state()
    held = read_pending(prior)
    try:
        tid = ls.graphql('query{teams(filter:{key:{eq:"%s"}}){nodes{id}}}' % TEAM_KEY,
                         {})["teams"]["nodes"][0]["id"]
    except Exception as exc:  # noqa: BLE001
        # Nothing has been attempted, so nothing new is lost -- but the backlog
        # stops draining and the night is a no-op. Leave a heartbeat, keep the
        # held failures, and ping once per outage. See START_UNREACHABLE.
        print(f"linear unreachable: {exc}", file=sys.stderr)
        nights = (prior.get("down_nights") or 0) + 1 if (
            prior.get("failures_reported") == START_UNREACHABLE) else 1
        write_state(ran_at=_now(), drafted=0, failed=0, carried_in=0,
                    failures_reported=START_UNREACHABLE, down_nights=nights,
                    pending_failures=held, remaining=None)
        if nights == 1 or nights % START_UNREACHABLE_REPING_NIGHTS == 0:
            note = f" {len(held)} earlier failure(s) still unfiled." if held else ""
            notify(f"linear-dor: Linear unreachable at start for {nights} night(s), "
                   f"the DoR drip is not running.{note} Next ping in "
                   f"{START_UNREACHABLE_REPING_NIGHTS} nights if it stays down.")
        print(f"dor-drafter: SKIPPED, Linear unreachable at start "
              f"(night {nights}); {len(held)} failure(s) still held")
        return 0

    todo = fetch_draftable(ls, tid)
    if args.project:
        todo = [i for i in todo
                if ((i.get("project") or {}).get("name") or "") == args.project]

    print(f"dor-drafter {_now()}: {len(todo)} issue(s) lack a Definition of Ready")
    batch = todo[: args.limit]
    if not args.apply:
        for i in batch:
            print(f"  would draft {i['identifier']}  {i['title'][:66]}")
        print(f"dry run. {len(todo)} remaining; --apply to write {len(batch)}.")
        return 0

    # Collected, not just printed, and each one carries its own cause. draft_one()
    # still writes the reason to stderr; this list is what leaves the machine.
    drafted, failed = 0, []
    for issue in batch:
        body, reason = draft_one(issue, args.timeout)
        if not body:
            failed.append(f"{issue['identifier']}: {reason}")
            continue
        new_desc = (issue.get("description") or "").rstrip() + f"\n\n{DOR_HEADING}\n\n{body}\n"
        try:
            ls.graphql(UPDATE_M, {"id": issue["identifier"],
                                  "input": {"description": new_desc}})
        except Exception as exc:  # noqa: BLE001
            print(f"  {issue['identifier']}: update failed: {str(exc)[:120]}", file=sys.stderr)
            failed.append(f"{issue['identifier']}: Linear update failed: {str(exc)[:120]}")
            continue
        drafted += 1
        print(f"  drafted {issue['identifier']}  {issue['title'][:60]}")

    # Anything an earlier night could not file rides along with tonight's, so a
    # clean night still flushes the backlog. `held` was read at the top of the
    # run; read_state()/read_pending() are what give the state file a reader.
    pending = held
    to_report = pending + failed
    reported = report_failures(ls, to_report, carried=len(pending))
    unfiled = to_report if reported == "unreachable" else []

    write_state(ran_at=_now(), drafted=drafted, failed=len(failed),
                carried_in=len(pending), failures_reported=reported,
                pending_failures=unfiled[-PENDING_CAP:],
                remaining=len(todo) - drafted)
    carried_note = f", {len(pending)} carried in" if pending else ""
    held_note = f", {len(unfiled)} STILL UNFILED" if unfiled else ""
    print(f"dor-drafter: drafted {drafted}, {len(failed)} failed ({reported})"
          f"{carried_note}{held_note}, {len(todo) - drafted} still lack a DoR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
