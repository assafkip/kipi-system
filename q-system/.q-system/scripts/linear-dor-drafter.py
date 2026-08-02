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
from typing import NamedTuple

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
# writes it only inside apply_write(), which is the one path to a description write.
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
# to run on. The IDs come with the names because the write needs the id of the one
# label it drops.
#
# These are SELECTION-time labels. The write re-reads them (ISSUE_WRITE_Q) rather
# than reusing what it found here -- see reread_before_write(). An earlier comment
# in this slot claimed Linear has no remove-one mutation and that the full labelIds
# set therefore had to be replaced. That was false; removedLabelIds exists and is
# what this script sends. See needs_scope_label_ids().
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

# Re-read one issue immediately before writing it. Same fields the redraft write
# depends on, and nothing else. See reread_before_write().
ISSUE_WRITE_Q = """query($id:String!){issue(id:$id){
  id identifier description state{name type} labels{nodes{id name}}}}"""

TEAM_STATES_Q = """query($t:String!){team(id:$t){
  states(first:50){nodes{id name type position}}}}"""

REOPEN_M = """mutation($id:String!,$s:String!){
  issueUpdate(id:$id,input:{stateId:$s}){success}}"""


def issue_labels(issue: dict) -> list:
    """[{id, name}] for one issue. [] when the caller's fixture omits labels."""
    return ((issue.get("labels") or {}).get("nodes")) or []


def label_names(issue: dict) -> set:
    return {(lab.get("name") or "") for lab in issue_labels(issue)}


# Any markdown ATX heading, captured so its LEVEL can be compared.
HEADING_RE = re.compile(r"(?m)^[ \t]{0,3}(?P<hashes>#{1,6})[ \t]+(?P<text>.*?)[ \t]*$")
# The DoR heading, as a STRUCTURE: a heading line whose text begins with the
# phrase. Trailing words are allowed so the generated capability issues, which
# title their section in their own wording, are still recognised.
DOR_HEADING_RE = re.compile(
    r"(?mi)^[ \t]{0,3}(?P<hashes>#{1,6})[ \t]+definition of ready\b.*$")


# An opening or closing code fence: up to 3 spaces, then 3+ backticks or tildes.
FENCE_RE = re.compile(r"(?m)^[ \t]{0,3}(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)$")


def fenced_spans(text: str) -> list:
    """Character spans of CLOSED fenced code blocks, so headings inside them can
    be ignored.

    An UNCLOSED fence is deliberately NOT a span, and that is the load-bearing
    choice here. Treating a stray ``` as opening a region that runs to the end of
    the description would hide every real heading below it: the refused DoR would
    never be located, so it would never be replaced, and a second section would be
    appended beneath it. Of the two ways to be wrong, ignoring a real-but-unclosed
    fence costs at most a mis-scoped section, while swallowing the remainder loses
    the section boundary entirely on a permanent object.

    Fence rules follow CommonMark closely enough for issue descriptions: a closing
    fence matches the opening CHARACTER, is at least as long, and carries no info
    string; a backtick opener may not have backticks in its info string.
    """
    spans, open_at, open_char, open_len = [], None, "", 0
    for m in FENCE_RE.finditer(text):
        marker = m.group("fence")
        char, length, info = marker[0], len(marker), m.group("info").strip()
        if open_at is None:
            if char == "`" and "`" in info:
                continue      # not a valid backtick opener
            open_at, open_char, open_len = m.start(), char, length
        elif char == open_char and length >= open_len and not info:
            spans.append((open_at, m.end()))
            open_at = None
    return spans


def _outside_fences(pattern, text: str, spans: list):
    """Matches of `pattern` in `text` that do not start inside a fenced block."""
    return (m for m in pattern.finditer(text)
            if not any(s <= m.start() < e for s, e in spans))


def find_dor_heading(desc: str, spans: list | None = None):
    """The ONE place this file decides where a Definition of Ready section is.

    STRUCTURE, not phrase -- and that distinction is the whole reason this
    function exists rather than three `in desc` tests. Matching the words
    "Definition of Ready" wherever they appear went wrong three separate times
    in this one file:

      1. needs_dor() excluded any description CONTAINING the phrase, so a
         needs-scope issue (which HAS a bad DoR) was never redrafted. That is
         the defect this whole branch exists to fix.
      2. selection_mode() excluded on the same phrase in ordinary prose, so a
         founder writing "this needs a Definition of Ready" hid their own issue
         from the drafter permanently (sp-b784a19a).
      3. split_dor_section() located the owned span with `desc.find()`, so an
         inline MENTION became the section start and everything from that
         sentence to the next heading was replaced on redraft (codex round 2).

      4. A heading line INSIDE A FENCED CODE BLOCK counted, so a founder quoting
         this repo's own DoR template -- which is routinely pasted into a fenced
         block -- had the QUOTE treated as the section start: their prose was
         deleted from the quote onward while the actually-refused DoR below it
         was left untouched (codex round 3).

    Same mistake four times, so the fix is one resolver every site calls, not a
    fifth correct comparison. A heading is a line that starts with #s, outside a
    fence. A sentence that happens to contain the words is not a section.

    `spans` is an optimisation only: split_dor_section already computes the fence
    spans for its end-boundary search and passes them back in. It must NOT resolve
    the heading itself -- when it did, this function covered only the selection
    path while the write path kept its own copy, and a mutation that broke fence
    skipping here left every write-side test green. Found by mutation, not review.

    Known limit, chosen deliberately: a DoR titled with bold text
    (`**Definition of Ready**`) rather than a heading reads as absent, so such an
    issue gets a second section appended. That is the tradeoff rebuild_description
    already makes explicit -- a duplicate section is recoverable, silently
    deleting or permanently hiding a human's text is not.
    """
    desc = desc or ""
    spans = fenced_spans(desc) if spans is None else spans
    return next(_outside_fences(DOR_HEADING_RE, desc, spans), None)


def has_dor_section(desc: str) -> bool:
    """Whether the issue already carries a DoR section. See find_dor_heading."""
    return find_dor_heading(desc) is not None


def split_dor_section(desc: str) -> tuple:
    """(before, heading, section, after) around the DoR section this job owns.

    The owned span runs from the DoR heading LINE to the next heading of the same
    or a higher level, or to the end when there is none. `after` is somebody
    else's text -- a `## Notes`, an operator record, a later human edit -- and the
    first cut of this function took everything from the heading onward as
    replaceable, which silently deleted all of it on every redraft (codex round 1,
    finding 1). Nothing outside `section` is ever rewritten.

    The heading LINE comes back as its own element so a redraft can put the
    founder's exact wording back rather than normalising it to DOR_HEADING.
    """
    desc = desc or ""
    spans = fenced_spans(desc)
    match = find_dor_heading(desc, spans)
    if not match:
        return desc, "", "", ""
    level = len(match.group("hashes"))
    heading = match.group(0).strip()
    # Searched over `desc`, not over a slice, so the fence spans stay in one
    # coordinate system. Same-or-higher level ends the section; a deeper `###`
    # inside it does not, and neither does a heading inside a fenced block --
    # a fenced `## Notes` would otherwise cut the section short and shunt the
    # rest of the DoR into `after`, where it is never rewritten again.
    nxt = next((m for m in _outside_fences(HEADING_RE, desc, spans)
                if m.start() >= match.end() and len(m.group("hashes")) <= level), None)
    if not nxt:
        return desc[:match.start()], heading, desc[match.end():], ""
    return (desc[:match.start()], heading,
            desc[match.end():nxt.start()], desc[nxt.start():])


def redraft_state(desc: str) -> tuple:
    """(redrafts_done, already_terminal) off the marker. (0, False) if absent.

    Read ONLY from the line directly above the DoR heading, which is the slot
    this job writes and owns. Scanning the whole description let founder text
    forge the counter: a pasted `<!-- kipi-dor: redrafts=3 -->` example made the
    first real redraft terminal, and a pasted `terminal` removed the issue from
    selection permanently (codex-adversarial finding-4).

    HONEST BOUNDARY: text a human puts in that exact slot is still indistinguishable
    from this job's own. The slot is narrow and machine-shaped, not immune.
    """
    before = split_dor_section(desc)[0]
    lines = before.rstrip().splitlines()
    match = REDRAFT_MARKER_RE.search(lines[-1]) if lines else None
    if not match:
        return 0, False
    return int(match.group(1)), bool(match.group(2))


def strip_owned_marker(before: str) -> str:
    """`before` with this job's counter marker removed from the ONE slot it owns.

    The slot is the last line above the DoR heading, and this is deliberately the
    same slot, same regex and same `search` semantics that redraft_state() reads.
    They have to agree: the previous cut read narrow (one line) but deleted wide
    (`REDRAFT_MARKER_RE.sub("", before)` over the whole prefix), so a marker a
    founder had written into their own prose -- documenting the mechanism, quoting
    a terminal note from another issue -- was silently deleted on every redraft
    while being ignored for counting (codex round 1, finding 1). Deleting a human's
    words off a permanent Linear object is the worst failure this script has, and
    an asymmetry between the read slot and the write slot is how it got there.

    Only the marker leaves; any other text sharing that last line is kept.
    """
    body = (before or "").rstrip()
    lines = body.splitlines()
    if not lines or not REDRAFT_MARKER_RE.search(lines[-1]):
        return body
    last = REDRAFT_MARKER_RE.sub("", lines[-1]).rstrip()
    return "\n".join(lines[:-1] + ([last] if last.strip() else [])).rstrip()


def selection_mode(issue: dict) -> str | None:
    """"redraft" | "terminal" | "draft" | None -- THE selection predicate.

    ORDER IS THE WHOLE FIX. The needs-scope branch sits ABOVE the has-a-DoR
    exclusions, because a refused issue always has a DoR and the old code read
    that as "nothing to do here". Moving the label check below them would restore
    the exact bug while looking like it had been fixed, which is why the paired
    test asserts on an issue carrying BOTH the heading and the label.
    """
    if (issue.get("state") or {}).get("type") not in DRAFTABLE_STATE_TYPES:
        return None
    desc = issue.get("description") or ""
    # This job's own failure record. Drafting onto it burns a bounded nightly
    # slot to write prose onto a machine-written log. See FAILURE_MARKER.
    if FAILURE_MARKER in desc:
        return None

    if NEEDS_SCOPE_LABEL in label_names(issue):
        done, terminal = redraft_state(desc)
        if terminal:
            return None       # already declared a dead end; costs nothing further
        if done >= REDRAFT_CAP:
            return "terminal"  # exhausted -- record the rationale, once
        return "redraft"

    # One resolver, so "already has a DoR" cannot drift from "where is the DoR".
    # This replaces two separate phrase tests: an exact-DOR_HEADING substring and
    # a bare "Definition of Ready" substring. The second matched ordinary prose,
    # so a founder writing "this needs a Definition of Ready" removed their own
    # issue from the drafter forever (sp-b784a19a). A heading is structure; a
    # sentence mentioning the words is not. See find_dor_heading.
    if has_dor_section(desc):
        return None
    return "draft"


def needs_dor(issue: dict) -> bool:
    """Kept as the boolean face of selection_mode: this job's other test file
    (test-linear-dor-failure-reporting.py) asserts on it directly."""
    return selection_mode(issue) is not None


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


def draft_one(issue: dict, timeout: int, prompt: str | None = None) -> tuple:
    """One `claude -p` call. Returns (dor_body, "") or (None, reason).

    `prompt` overrides the first-draft prompt (the redraft path passes
    REDRAFT_PROMPT). Optional rather than positional so the existing callers and
    the failure-reporting test keep working unchanged.

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
    if prompt is None:
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
    """Every issue on the team this job has something to do to."""
    issues, after = [], None
    while True:
        page = ls.graphql(ISSUES_Q, {"t": team_id, "a": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return [i for i in issues if needs_dor(i)]


# Redrafts and terminals sort ahead of first drafts. NOT cosmetic ordering: the
# batch is todo[:limit] with no cursor and no rotation, and on 2026-08-01 the live
# board held 93 issues lacking a DoR against a --limit of 8. A redraft appended to
# the tail of that list would be selected in name and never reached in practice,
# so the redrive would be as dead as the promise it replaces. Terminals go first
# of all because they cost no `claude` call at all -- they must not be crowded out
# by work that does.
MODE_RANK = {"terminal": 0, "redraft": 1, "draft": 2}
VERBS = {"terminal": "mark terminal", "redraft": "redraft", "draft": "draft"}


def prioritise(issues: list) -> list:
    """[(mode, issue)] with the redrive ahead of the backlog. Stable within a
    mode, so the API's own order still decides among equals.

    Classifies but does NOT re-filter: fetch_draftable already holds the
    selection authority, and a second filter here would silently drop issues
    handed in by a caller that replaced it (the failure-reporting test does
    exactly that). Anything unclassifiable is a first draft, the behaviour every
    issue in the batch had before modes existed.
    """
    paired = [(selection_mode(i) or "draft", i) for i in issues]
    return sorted(paired, key=lambda pair: MODE_RANK.get(pair[0], 9))


def refusal_reason(ls, issue: dict) -> str:
    """The worker's most recent written refusal, or a stated absence.

    Never raises: a redraft without the reason is worse than one with it, but far
    better than a night that dies reading a comment thread.
    """
    try:
        nodes = ((((ls.graphql(ISSUE_COMMENTS_Q, {"id": issue["identifier"]}) or {})
                   .get("issue") or {}).get("comments") or {}).get("nodes")) or []
    except Exception as exc:  # noqa: BLE001 - see the docstring
        print(f"  {issue['identifier']}: could not read comments: {str(exc)[:100]}",
              file=sys.stderr)
        return "(the refusal comment could not be read)"
    for node in reversed(nodes):
        body = node.get("body") or ""
        if "Refused as unexecutable" in body:
            return body[:2000]
    return "(no refusal comment found on the issue)"


# The redraft prompt's budget for quoting the old DoR. A PROMPT cap, never a
# storage cap -- see dor_section() for why the two may not share one function.
PROMPT_DOR_CHARS = 3000
NO_SECTION_NOTE = "(the section could not be located by its heading)"


def dor_section(desc: str) -> str:
    """The DoR section exactly as it stands, in full. NEVER truncated.

    This is what the terminal path writes BACK to the issue, so any cap here is a
    silent partial write to a permanent object: terminalising an issue whose DoR
    ran past 3000 characters deleted everything after it, with no error and no
    record (codex round 4). Measured as introduced by this branch -- main has no
    terminal path at all and its only description write is a pure append, which
    cannot truncate.

    The producer/consumer mismatch had two honest resolutions: cap the producer so
    the trim can never happen, or stop the consumer trimming. Capping the producer
    is wrong here -- the "producer" is a previous redraft's body and whatever a
    human wrote, and refusing to store a long DoR is worse than storing it. So the
    write path takes the section whole, and the prompt keeps its own budget below.
    """
    return split_dor_section(desc)[2].strip()


def existing_dor(desc: str) -> str:
    """The DoR section trimmed to the redraft PROMPT's budget. Model input ONLY.

    Safe to truncate because nothing here is written back: it is context for the
    model to argue with. Never call this on a write path -- that is exactly the
    confusion that cost the tail of a long DoR. Write paths call dor_section().
    """
    return dor_section(desc)[:PROMPT_DOR_CHARS] or NO_SECTION_NOTE


def rebuild_description(desc: str, body: str, count: int,
                        terminal: bool = False) -> str:
    """Founder text + counter marker + a fresh DoR section + whatever followed it.

    Only the DoR section itself is replaced. Text above it AND text below it are
    carried through byte for byte, which is what keeps the append-only promise
    true for the words a human wrote.

    When the heading is absent (a differently-worded DoR on a generated capability
    issue), the whole description is treated as prefix and the section is APPENDED.
    Guessing at the boundary of a section we did not write would risk deleting a
    human's text, and a duplicate section is a recoverable mistake where that is not.
    """
    before, heading, _old, after = split_dor_section(desc)
    prefix = strip_owned_marker(before)
    marker = f"<!-- kipi-dor: redrafts={count}{' terminal' if terminal else ''} -->"
    # The founder's own heading wording is theirs, not this job's. Reuse it when
    # there is one; DOR_HEADING is only the fallback for an appended section.
    out = f"{prefix}\n\n{marker}\n{heading or DOR_HEADING}\n\n{body.strip()}\n"
    if terminal:
        out += f"\n{TERMINAL_NOTE}\n"
    if after.strip():
        out += f"\n{after.lstrip()}"
    return out


def needs_scope_label_ids(issue: dict) -> list:
    """The needs-scope label id(s) to remove.

    Sent as `removedLabelIds`, NOT as a full `labelIds` replacement. The first cut
    replaced the whole set from labels read before the `claude` call, which can be
    300s earlier, so any label added in that window was deleted (codex-review
    finding-2). The claim in that version -- that Linear can only express removal
    as a full replacement -- was false: IssueUpdateInput carries addedLabelIds and
    removedLabelIds, confirmed by schema introspection against the live API on
    2026-08-01. removedLabelIds touches one label and cannot clobber a concurrent one.
    """
    return [lab["id"] for lab in issue_labels(issue)
            if lab.get("name") == NEEDS_SCOPE_LABEL and lab.get("id")]


def reread_before_write(ls, issue: dict) -> dict | None:
    """The issue as Linear holds it NOW. None when it could not be read.

    A redraft's description is read during selection and written up to --timeout
    (default 300s) later, with a `claude` call in between. Everything the write
    depends on can move inside that window, and the write was built entirely from
    the pre-call copy (codex round 1, finding 2).

    None is a refusal to write, not an empty issue: writing the stale copy because
    the freshness check itself failed is the exact overwrite the check exists to
    stop, and a skipped redraft costs one slot while a clobbered description is
    gone from a permanent object.
    """
    try:
        return (ls.graphql(ISSUE_WRITE_Q, {"id": issue["identifier"]}) or {}).get("issue")
    except Exception as exc:  # noqa: BLE001 - see the docstring
        print(f"  {issue['identifier']}: could not re-read before write: {str(exc)[:100]}",
              file=sys.stderr)
        return None


def moved_since_selection(selected_desc: str, fresh: dict) -> bool:
    """True when anything this write depends on changed since selection.

    Named for what it checks, not for one cause of it: it began as a
    rival-drafter test and a human editing the DoR by hand trips it too.

    The counter marker is this job's own single-writer token, so it doubles as a
    compare-and-swap version: this job is the only thing that writes it, therefore
    a changed count means a second drafter finished first. A missing needs-scope
    label says the same thing from the other side.

    Deliberately NOT a lock, and deliberately not a counter kept in a shared file.
    Nothing is claimed before the work; the write is simply abandoned if the state
    it was computed against is gone. That is why this does not recreate the
    read-then-write race attempts-ledger.py exists to prevent (sp-626e9452, out of
    scope): a lost update here loses one night's redraft of one issue, which the
    next run redoes, rather than losing an increment nothing will ever redo.

    A HUMAN edit is not a rival writer. It leaves the counter alone, so the redraft
    proceeds and rebuild_description carries the human's new text through -- which
    is the point of rebuilding from the fresh description rather than skipping on
    any change at all.

    HONEST BOUNDARY: this narrows the window from the whole `claude` call to the
    gap between this read and the mutation. It does not close it. Linear's
    issueUpdate takes no expected-version argument, so a true CAS is not available
    to ask for; two drafters colliding inside that gap still resolve last-write-wins.
    """
    fresh_desc = fresh.get("description") or ""
    if NEEDS_SCOPE_LABEL not in label_names(fresh):
        return True
    if redraft_state(fresh_desc) != redraft_state(selected_desc):
        return True
    # THIRD signal, and the one a person actually trips: the DoR section itself
    # changed. The counter and the label are both machine-written, so a human who
    # rewrote the scope by hand during the model call left both untouched and the
    # redraft wrote straight over their words (codex round 4). A hand edit is the
    # most likely edit there is -- someone reading the refusal and fixing it -- so
    # the section body is part of what "unchanged since selection" has to mean.
    return dor_section(fresh_desc) != dor_section(selected_desc)


def update_issue(ls, issue: dict, payload: dict) -> None:
    """The single write chokepoint. Raises when Linear reports success=false.

    Both write paths ignored the response before this (codex-review finding-3): a
    `{"success": false}` was counted as drafted and printed as "redrafted,
    needs-scope dropped" while neither the label removal nor the cap marker had
    landed -- a silent divergence between what the run reported and what the board
    holds. One chokepoint, so the check cannot exist on one path and not the other.
    """
    res = ls.graphql(UPDATE_M, {"id": issue["identifier"], "input": payload})
    if not (((res or {}).get("issueUpdate") or {}).get("success")):
        raise RuntimeError("Linear returned issueUpdate.success=false "
                           "(nothing was written)")


class Skipped(NamedTuple):
    """Why a write was not made, and whether the issue is still queued.

    `still_queued` is the part callers got wrong: a skip was read as "somebody
    else finished it", but a rival redraft the WORKER REFUSED AGAIN still carries
    needs-scope and is back in the queue, not done. Reporting it as completed
    deletes real remaining work from the count (codex round 4).
    """
    reason: str
    still_queued: bool


def apply_write(ls, issue: dict, mode: str, body: str,
                attempt: int = 0) -> Skipped | None:
    """THE path from a drafted body to a description write. Every mode goes here.

    Returns None when the write landed, or a short reason when it was deliberately
    skipped. Raises only on a real transport/refusal failure.

    One function rather than one per mode, because the freshness guard was written
    for the redraft path and the other two paths silently did not have it (codex
    round 2): `terminal` and first-`draft` both built their payload from the
    description read at SELECTION, so an edit made after selection was overwritten
    by text that predated it -- the exact defect just fixed one branch over. Three
    call sites cannot drift apart if there is only one.

    Every mode re-reads first and builds from the CURRENT description. What differs
    per mode is only the applicability check and the payload shape, so those sit
    here side by side where a missing one is visible.
    """
    selected = issue.get("description") or ""
    fresh = reread_before_write(ls, issue)
    if fresh is None:
        raise RuntimeError("could not re-read the issue before writing")
    fresh_desc = fresh.get("description") or ""

    if mode == "redraft":
        if moved_since_selection(selected, fresh):
            return Skipped(
                "it changed while this attempt was drafting "
                "(rival redraft, label change, or a hand edit)",
                selection_mode(fresh) is not None)
        # Description and label drop go in ONE mutation on purpose. As two calls,
        # a failure between them leaves a rewritten DoR still wearing needs-scope:
        # the picker keeps ignoring it and the next night spends another capped
        # attempt rewriting work already done.
        #
        # removedLabelIds, not a full labelIds replacement: Linear applies it as a
        # delta against the label set as it stands at write time, so a label added
        # while this redraft was drafting survives. That is the label half of
        # round 1 finding 2, and it needs no version check because the server-side
        # semantics already give the atomicity.
        payload = {"description": rebuild_description(fresh_desc, body, attempt),
                   "removedLabelIds": needs_scope_label_ids(fresh)}
    elif mode == "terminal":
        # The needs-scope label is deliberately NOT removed: the issue really is
        # unscoped, and dropping it would feed the issue back to a picker that has
        # already refused it REDRAFT_CAP times.
        if moved_since_selection(selected, fresh):
            return Skipped("it changed while this run was working",
                           selection_mode(fresh) is not None)
        # dor_section, NOT existing_dor: this value is WRITTEN BACK, so the
        # prompt's character budget must not touch it.
        payload = {"description": rebuild_description(
            fresh_desc, dor_section(fresh_desc) or NO_SECTION_NOTE,
            REDRAFT_CAP, terminal=True)}
    else:
        # A first draft appends. If the issue gained a DoR since selection then
        # somebody else drafted it, and appending now would give it two.
        if has_dor_section(fresh_desc):
            return Skipped("it gained a Definition of Ready while this "
                           "attempt was drafting",
                           selection_mode(fresh) is not None)
        payload = {"description": fresh_desc.rstrip() + f"\n\n{DOR_HEADING}\n\n{body}\n"}

    update_issue(ls, issue, payload)
    return None


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


def queue_breakdown(total: int, redrives: int) -> str:
    """The ONE phrasing of the lacks-a-DoR / has-a-bad-one split.

    Both status lines call this. They used to phrase the same split themselves,
    and the opening line was corrected while the closing line kept saying the
    remainder "still lack a DoR" (codex round 2, twin of round 1 finding 3).
    Every redrive candidate HAS a Definition of Ready -- having one the worker
    refused is the entire reason it is queued -- so counting it as lacking one
    reports the opposite of the state the run is acting on. A shared formatter
    is what stops one caller from being fixed and the other from drifting.
    """
    return (f"{total - redrives} lacking a Definition of Ready, "
            f"{redrives} {NEEDS_SCOPE_LABEL} redrive (DoR present, being rewritten)")


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

    plan = prioritise(todo)
    redrives = sum(1 for mode, _ in plan if mode in ("redraft", "terminal"))
    print(f"dor-drafter {_now()}: {len(todo)} issue(s) queued: "
          f"{queue_breakdown(len(todo), redrives)}")
    batch = plan[: args.limit]
    if not args.apply:
        for mode, i in batch:
            print(f"  would {VERBS[mode]} {i['identifier']}  {i['title'][:66]}")
        print(f"dry run. {len(todo)} remaining; --apply to write {len(batch)}.")
        return 0

    # Collected, not just printed, and each one carries its own cause. draft_one()
    # still writes the reason to stderr; this list is what leaves the machine.
    # done_redrives feeds the CLOSING status line: without it the closing count
    # cannot tell a redrive apart from a first draft and reports the same wrong
    # thing the opening line used to (codex round 2, twin of round 1 finding 3).
    # `elsewhere` is issues a concurrent writer finished first. They are neither
    # drafted by this run nor still queued, and counting them as remaining
    # reported work that no longer exists (codex round 3).
    drafted, failed, done_redrives = 0, [], 0
    elsewhere, elsewhere_redrives = 0, 0
    for mode, issue in batch:
        desc = issue.get("description") or ""
        attempt = 0  # bound for every mode; only a redraft carries a real number

        # The cap is spent. One write, no model call, and the label stays on.
        if mode == "terminal":
            try:
                skipped = apply_write(ls, issue, "terminal", "")
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{issue['identifier']}: terminal write failed: {str(exc)[:120]}")
                continue
            if skipped:
                if not skipped.still_queued:
                    elsewhere += 1
                    elsewhere_redrives += 1
                print(f"  skipped {issue['identifier']}: {skipped.reason}")
                continue
            drafted += 1
            done_redrives += 1
            print(f"  marked terminal {issue['identifier']}  redraft cap "
                  f"{REDRAFT_CAP}/{REDRAFT_CAP} spent")
            continue

        # Two call shapes, not one with a None default. draft_one is a monkeypatch
        # seam for test-linear-dor-failure-reporting.py, which replaces it with a
        # TWO-argument lambda; passing a third positional on the first-draft path
        # breaks that suite with a TypeError. The first-draft call stays exactly
        # the arity it has always been.
        if mode == "redraft":
            attempt = redraft_state(desc)[0] + 1
            body, reason = draft_one(issue, args.timeout, REDRAFT_PROMPT.format(
                attempt=attempt, cap=REDRAFT_CAP,
                project=(issue.get("project") or {}).get("name") or "unassigned",
                title=issue.get("title") or "",
                old_dor=existing_dor(desc),
                reason=refusal_reason(ls, issue),
            ))
        else:
            body, reason = draft_one(issue, args.timeout)
        if not body:
            failed.append(f"{issue['identifier']}: {reason}")
            continue

        try:
            skipped = apply_write(ls, issue, mode, body, attempt)
        except Exception as exc:  # noqa: BLE001
            print(f"  {issue['identifier']}: update failed: {str(exc)[:120]}", file=sys.stderr)
            failed.append(f"{issue['identifier']}: Linear update failed: {str(exc)[:120]}")
            continue
        if skipped:
            # Not a failure: the issue got what it needed, or somebody is working
            # on it. Counting it as drafted would overstate the run, and reporting
            # it as failed would file a noise issue about work that got done.
            # It only leaves the queue if it is actually FINISHED -- a rival
            # redraft the worker refused again still wears needs-scope and is
            # still real remaining work.
            if not skipped.still_queued:
                elsewhere += 1
                if mode == "redraft":
                    elsewhere_redrives += 1
            print(f"  skipped {issue['identifier']}: {skipped.reason}")
            continue
        drafted += 1
        if mode == "redraft":
            done_redrives += 1
            print(f"  redrafted {issue['identifier']} (attempt {attempt}/{REDRAFT_CAP}, "
                  f"{NEEDS_SCOPE_LABEL} dropped)  {issue['title'][:44]}")
        else:
            print(f"  drafted {issue['identifier']}  {issue['title'][:60]}")

    # Anything an earlier night could not file rides along with tonight's, so a
    # clean night still flushes the backlog. `held` was read at the top of the
    # run; read_state()/read_pending() are what give the state file a reader.
    pending = held
    to_report = pending + failed
    reported = report_failures(ls, to_report, carried=len(pending))
    unfiled = to_report if reported == "unreachable" else []

    # One arithmetic for the queue, used by the state file and the status line, so
    # the two cannot disagree about what is left.
    remaining = len(todo) - drafted - elsewhere
    remaining_redrives = redrives - done_redrives - elsewhere_redrives
    write_state(ran_at=_now(), drafted=drafted, failed=len(failed),
                carried_in=len(pending), failures_reported=reported,
                pending_failures=unfiled[-PENDING_CAP:],
                remaining=remaining)
    carried_note = f", {len(pending)} carried in" if pending else ""
    held_note = f", {len(unfiled)} STILL UNFILED" if unfiled else ""
    elsewhere_note = (f", {elsewhere} completed by another writer"
                      if elsewhere else "")
    print(f"dor-drafter: drafted {drafted}, {len(failed)} failed ({reported})"
          f"{carried_note}{held_note}{elsewhere_note}, {remaining} still queued: "
          f"{queue_breakdown(remaining, remaining_redrives)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
