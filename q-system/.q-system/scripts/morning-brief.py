#!/usr/bin/env python3
"""One Slack message each morning: what the founder has going on today.

Founder-directed 2026-08-30: fully automated, no HTML, one Slack message telling
him what he has on. Plan: `q-system/output/plans/morning-brief-overhaul-2026-08-30.md`.

## What this replaces, and why it is not a revival

The 37-agent `/q-morning` pipeline produced its last artifact on 2026-04-04 and
then produced nothing for 148 days without anyone being told. Two measured
causes, both in `.q-system/preflight.md`: it probed
`Google_Calendar__gcal_list_events` and `Gmail__gmail_search_messages`, tool
names that no longer exist (they are `list_events` and `search_threads`), and the
fallback for both rows was "None. Halt." The same table listed Chrome MCP as
CRITICAL with fallback "None. Halt.", which makes a headless run impossible by
construction: a 7am launchd job has no browser.

It was also never automated. It required the founder to open a session and type
a command, and it answered with an HTML page. An output nobody opens is the same
as no output.

Most of what the nine phases did (LinkedIn posts, engagement hitlist, lead
sourcing, prospect pipeline, content intel) is covered TODAY by live `com.cole.*`
launchd jobs. Reviving the orchestrator would build a second copy of running
work. What is actually missing is only the briefing.

## Two rules inherited verbatim from daily-linear-digest.py

**An empty section and a broken section are different facts.** Every collector
returns `(rows, error)`. A section with an error prints COULD NOT READ. It never
prints "nothing", because a silent zero reading as a quiet day is the exact
defect that let this system die in April.

**The send is verified, not assumed.** Delivery goes through `slack_founder.py`,
which reads Slack's own answer out of the response body. Never `slack-notify.sh`:
that is the fleet ALERT path, it files a Linear ticket for Sana, it sends nothing
to Slack, and it exits 0 either way.

## Why two `claude -p` calls and not one

Calendar and Gmail live behind the `claude_ai_*` connectors, which are MCP
servers attached to the CLI, not an HTTP API a bare Python script can call.
Measured 2026-08-30 in a stripped environment: a headless `claude -p` DOES reach
them (`--allowedTools mcp__claude_ai_Google_Calendar__list_events` returned
`COUNT=0`), provided `USER`/`LOGNAME` are set so the keychain resolves, and
provided PATH carries `~/.local/bin` (a bare `bash -lc` does not).

One combined call would be cheaper and would collapse two independent failures
into one: a model that could reach Gmail but not Calendar would blank both
sections identically. Constraint 3 says each section reports FAILED on its own,
so each section gets its own call.

    python3 morning-brief.py            # build and send
    python3 morning-brief.py --dry-run  # build, print, send nothing
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
# scripts/ -> .q-system/ -> q-system/   (the folder-structure QROOT rule)
QROOT = HERE.parent.parent / "q-system" if (HERE.parent.parent / "q-system").is_dir() \
    else HERE.parent.parent
STATE_DIR = Path(os.environ.get("KIPI_STATE_DIR", os.path.expanduser("~/.config/kipi")))
RECEIPT_PATH = STATE_DIR / "morning-brief-last.json"

# Pinned. Scar: headless `claude -p` jobs without an explicit pin rode the
# default model and burned 3% of a weekly budget in one hour.
BRIEF_MODEL = os.environ.get("KIPI_BRIEF_MODEL", "claude-opus-5")
CLAUDE_TIMEOUT = int(os.environ.get("KIPI_BRIEF_CLAUDE_TIMEOUT", "180"))

CAL_TOOL = "mcp__claude_ai_Google_Calendar__list_events"
MAIL_TOOL = "mcp__claude_ai_Gmail__search_threads"

MAX_ROWS = 15


def _load_sibling(stem: str, filename: str):
    spec = importlib.util.spec_from_file_location(stem, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# The model seam
# ---------------------------------------------------------------------------

def run_claude(prompt: str, tools: list, timeout: int = CLAUDE_TIMEOUT):
    """(stdout, error). One bounded headless call.

    REFUSES UNDER PYTEST. Same chokepoint posture as slack_founder.deliver: the
    refusal lives at the destination, not in per-test stubs, because per-test
    stubbing only ever protects the tests somebody remembered to write.

    `</dev/null` equivalent (`stdin=DEVNULL`) is not optional: `claude -p` reads
    stdin, and a caller that leaves it inherited has its own input drained.
    See rca-heartbeat-tail-skip-2026-07-05.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None, "refused: running under pytest, no live model call"
    env = dict(os.environ)
    env["ANTHROPIC_MODEL"] = BRIEF_MODEL
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--allowedTools", *tools],
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL, env=env)
    except FileNotFoundError:
        return None, "claude CLI not on PATH (a bare launchd PATH omits ~/.local/bin)"
    except subprocess.TimeoutExpired:
        return None, f"claude timed out after {timeout}s"
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {str(exc)[:160]}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:200]
        return None, f"claude exited {proc.returncode}: {detail}"
    return proc.stdout, None


def _parse_json_block(text: str, key: str):
    """(list, error). The model is asked for one JSON object; this refuses
    anything else rather than guessing.

    Deliberately not a regex over prose. A model that answers "I could not reach
    the calendar" must land in the ERROR branch, not be read as zero events,
    which is the whole distinction this file exists to preserve.
    """
    if text is None:
        return None, "no output"
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None, f"no JSON object in the answer: {text.strip()[:160]!r}"
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as exc:
        return None, f"unparseable JSON: {exc}"
    if not isinstance(data, dict) or key not in data:
        return None, f"answer has no {key!r} key: {text.strip()[:160]!r}"
    value = data[key]
    if not isinstance(value, list):
        return None, f"{key!r} is not a list"
    return value, None


# ---------------------------------------------------------------------------
# Section 1: today's calendar
# ---------------------------------------------------------------------------

CAL_PROMPT = """Call {tool} for calendar "primary" restricted to {day} local time only.
Reply with ONE JSON object and nothing else, no prose, no code fence:
{{"events": [{{"start": "HH:MM", "title": "...", "who": ["name", ...]}}]}}
Use "all-day" as start for all-day events. "who" is the other attendees, may be [].
If the tool call fails, reply with exactly: {{"error": "<what failed>"}}"""


def collect_calendar(now: dt.datetime, runner=None):
    day = now.strftime("%Y-%m-%d")
    runner = runner or (lambda p, t: run_claude(p, t))
    text, error = runner(CAL_PROMPT.format(tool=CAL_TOOL, day=day), [CAL_TOOL])
    if error:
        return [], error
    events, parse_error = _parse_json_block(text, "events")
    if parse_error:
        return [], parse_error
    rows = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        who = ev.get("who") or []
        who_text = f"  ({', '.join(str(w) for w in who)})" if who else ""
        rows.append(f"{ev.get('start', '??:??')}  {str(ev.get('title', 'untitled'))[:80]}{who_text}")
    return rows, None


# ---------------------------------------------------------------------------
# Section 2: mail that needs an answer
# ---------------------------------------------------------------------------

class Row(str):
    """A rendered brief line that also carries the STABLE IDENTITY of the thing it
    describes.

    ## Why this exists, and it is the end of a four-round loop

    PR #296 rounds 1-4 are all one defect. The Notion board keys each row so a row he
    has dragged is never archived and re-created underneath him. Four of the five
    producers pass a real id (client `kind:name`, `gtm:<step id>`, literal error keys).
    The inbox rows had nothing but their own RENDERED TEXT, so the key was that text
    with volatile bits scrubbed by a regex -- and every round patched the regex for one
    more surface form: the health dot, then "2h ago", then a bare digit run that
    collapsed two different invoice numbers, then the `[2h]` the real producer emits.
    A fifth form was guaranteed, because rendering keeps changing and the regex can
    only ever chase it.

    A row is a `str`, so every existing renderer (`_section`, the f-strings, the
    slicing) is untouched and this needed no caller changes. What it adds is `.key`:
    the Gmail thread id, the GroupMe conversation id -- an identity the producer KNOWS
    and was throwing away at the moment it rendered.
    """
    __slots__ = ("key",)

    def __new__(cls, text: str, key: str):
        row = super().__new__(cls, text)
        row.key = key
        return row


#: How far back the mail sweep looks, and it is a CONSTANT because it was a hardcoded
#: "48 hours" inside the prompt for weeks and nobody could see it.
#:
#: THE BUG THIS FIXES, measured 2026-09-03. The brief printed "Mail needing an answer:
#: nothing" on 09-01, 09-02 and 09-03 while two client threads sat unanswered since
#: 2026-08-11 and 2026-08-13. Both are real, both are named by
#: `email-watch/ledger.py needs-reply`, and both are 3 weeks old, so a 48-hour window
#: could not see either one. The section was not empty; it was blind, and it reported
#: blindness as calm.
#:
#: 30 days because the oldest of the two is 23 days old and a window that only just
#: covers today's example is a window that will fail next month. The prompt still
#: excludes automated senders and still requires that HE has not replied, so widening
#: the window does not widen the noise; it only stops hiding the old ones.
#:
#: The deterministic answer is `ledger.py needs-reply`, which has no window at all and
#: knows which threads are clients. It is not wired here yet: it reads the Notion
#: ledger live, so it is a cross-repo runtime dependency and its own piece of work.
MAIL_WINDOW_DAYS = 30
#: MAIL_ROW_CAP LIVED HERE AND IS DELETED (claude review, 2026-09-04, major).
#: It trimmed the PRODUCER's rows to 15. Trimmed threads never entered
#: `buckets["inbox"]`, yet `inbox:Gmail` still reported healthy (every remaining key
#: was a real thread id), so the painter archived their board rows -- pins included --
#: inside a healthy scope. An unanswered client thread disappeared off his board, which
#: is the exact failure this board exists to prevent.
#:
#: The cap was also redundant. `_section` already trims DISPLAY to MAX_ROWS and prints
#: "...and N more", so the Slack message was never going to be 50 lines. One cap for
#: display, none for data: the brief stays short and the board sees every thread.
#:
#: Round 11 fixed this same class inside the painter with its `capped` set, on the
#: rule that a cap is a write budget and not a statement that the work is finished.
#: The rule is right; a second cap upstream of the producer routed around it.

MAIL_PROMPT = """Call {tool} to find email threads from the last {days} days where a
REAL PERSON wrote to the founder and the founder has not replied yet. Exclude
newsletters, notifications, receipts, calendar invites, automated senders and
no-reply addresses. Oldest first: a thread waiting three weeks matters more than
one waiting an hour.
Reply with ONE JSON object and nothing else, no prose, no code fence:
{{"threads": [{{"id": "<the thread id the tool returned>", "from": "their email ADDRESS, not their display name", "subject": "...", "age_hours": <int>}}]}}
`id` is the thread's own id from the tool result, copied verbatim. It is what keeps a
board row stable while its age changes, so never invent or shorten it.
If the tool call fails, reply with exactly: {{"error": "<what failed>"}}"""


def _chat_days():
    """{slug: [dates he spoke in that client's chat]}. Empty on any failure, which
    keeps every thread rather than dropping one on incomplete evidence.

    DAYS, not a last-seen stamp: one message does not show he dealt with what they
    mailed, and the filter needs to count distinct days to tell the two apart."""
    out = {}
    try:
        answered = _load_sibling("answered_elsewhere", "answered_elsewhere.py")
        gm = _load_sibling("groupme_inbox", "groupme_inbox.py")
        token = gm.load_token()
        if not token:
            return out
        for group_id, slug in answered.channel_slugs().items():
            page = gm._get(f"/groups/{group_id}/messages", token, limit=100) or {}
            me = str((gm._get("/users/me", token) or {}).get("user_id") or "")
            days = {dt.datetime.fromtimestamp(m["created_at"], dt.timezone.utc).date()
                    for m in (page.get("messages") or [])
                    if str(m.get("user_id")) == me and m.get("created_at")}
            if days:
                out[slug] = sorted(days)
    except Exception:  # noqa: BLE001
        return {}
    return out


def collect_mail(now: dt.datetime, runner=None):
    runner = runner or (lambda p, t: run_claude(p, t))
    text, error = runner(MAIL_PROMPT.format(tool=MAIL_TOOL, days=MAIL_WINDOW_DAYS),
                         [MAIL_TOOL])
    if error:
        return [], error
    threads, parse_error = _parse_json_block(text, "threads")
    if parse_error:
        return [], parse_error
    # ANSWERED SOMEWHERE ELSE. A model reading one thread can only tell you whether
    # he replied IN it, and he does not always. He answers by starting a new mail, and
    # for a client whose day happens in a group chat he answers there. Measured
    # 2026-09-04: one client emailed on 08-05 and he sent 36 chat messages to them
    # between 08-18 and 09-02; the board called it 717 hours owed. No prompt fixes
    # that -- the model cannot see the other threads or the chat -- so the decision is
    # a timestamp comparison over sources already on disk, which is code.
    try:
        answered = _load_sibling("answered_elsewhere", "answered_elsewhere.py")
        before = len(threads)
        threads, notes = answered.filter_answered(threads, chat_days=_chat_days())
        # The prefix is NOT "dropped": these notes also carry the keeps and the
        # "check was inert" lines, and at 3am the only record of this running is this
        # log. A line saying the check found nothing must not read as a removal.
        for note in notes:
            print(f"[mail] {note}")
        print(f"[mail] answered-elsewhere: {before} candidate(s), "
              f"{len(threads)} still owed")
    except Exception as exc:  # noqa: BLE001
        # Never fatal, and never a silent drop: failing here KEEPS every thread,
        # because a wrong removal hides work he owes and a wrong keep costs a glance.
        print(f"[mail] answered-elsewhere check skipped ({type(exc).__name__}); "
              "every thread kept")

    rows = []
    for th in threads:
        if not isinstance(th, dict):
            continue
        age = th.get("age_hours")
        age_text = f"  [{age}h]" if isinstance(age, int) else ""
        sender = str(th.get("from", "unknown"))[:40]
        subject = str(th.get("subject", ""))[:70]
        # The thread id when the model returned one, else sender+subject. Both are
        # stable while the AGE changes, which is what was minting new ids. Never the
        # rendered line: that is the defect rounds 1-4 kept patching.
        key = str(th.get("id") or "").strip() or f"{sender}|{subject}"
        rows.append(Row(f"{sender}  {subject}{age_text}", f"mail:{key}"))

    # A COLLAPSE IS NOT A DEDUPE. Codex, 2026-09-03: when the model omits thread ids,
    # two different threads from one person with one subject ("Re: invoice", twice)
    # produce one key, the board writes ONE row, and the second task is gone -- while
    # read-back still says ok, because it compares what was written to what was
    # wanted and both had already lost it. That is worse than the bug it replaced:
    # rounds 1-4 lost a DRAG, this loses WORK.
    #
    # Nothing stable distinguishes them, so the choice is between dropping a task and
    # keeping it under an id that may move. Keeping it wins, and it is not close: a
    # row he never sees cannot be acted on at all, while a row whose id shifts costs
    # him a position on the board. The suffix is ordinal and deliberately provisional.
    # THE ORDINAL SUFFIX WAS WITHDRAWN (round 10, major). It numbered duplicates by
    # POSITION, so when the first of two "Re: invoice" threads was answered and left
    # the list, the second was renumbered onto the first one's key -- and inherited its
    # board row, its Status and the bucket he had dragged it to. A thread wearing
    # another thread's identity is worse than either failure the note above weighed.
    #
    # With no thread id there is nothing that tells two identical rows apart, so this
    # stops pretending there is. The group becomes ONE row that SAYS it is a group.
    # No task is hidden (the count is on the row), no id is invented, and the key is
    # stable because it is the thing they have in common.
    groups = {}
    for row in rows:
        groups.setdefault(row.key, []).append(row)
    rows = []
    for key, members in groups.items():
        if len(members) == 1:
            rows.append(members[0])
            continue
        rows.append(Row(f"{members[0]} ({len(members)} threads, same sender and "
                        "subject)", key))
    return rows, None


# ---------------------------------------------------------------------------
# Section 3: owed today
# ---------------------------------------------------------------------------

ASSIGNED_Q = """
query {
  viewer {
    assignedIssues(first: 250, filter: {state: {type: {nin: ["completed", "canceled"]}}}) {
      nodes { identifier title dueDate state { name type } labels { nodes { name } } }
    }
  }
}
"""

# The label the fleet already uses to say whose work an issue is. Not invented
# here: 50 of the 72 open issues assigned to the founder carry it.
SANA_LABEL = "owner:sana"
FOUNDER_LABEL = "owner:assaf"


def collect_owed(now: dt.datetime, qroot=None, graphql=None):
    """(rows, error). Leads with what is HIS; counts the rest without hiding it.

    ## Why this is not a flat list of everything assigned to him

    Measured 2026-08-30 against the live board, before choosing the shape:

        72 open issues assigned to the founder
        50 carry owner:sana        <- his engineer's queue, mis-assigned to him
         1 carries owner:assaf
        21 carry no owner label, and ~19 of those are engineering too
         1 has a due date at all, overdue since 2026-08-10

    A flat list renders Sana's queue as the founder's morning. The first live
    run printed 15 engineering issues and "...and 57 more", which is a section
    that costs attention and returns nothing.

    ## Why not a due-date filter, which was the obvious pick

    One issue in seventy-two has a due date. A "due today" tier would render
    empty almost every morning: a guard that cannot fire reads as protection and
    is not. So due-date is ONE of three lead signals, never the only one.

    ## What the three tiers are

    LEAD (things only he can do): open loops flagged needs_founder, issues
    labelled owner:assaf, and issues due today or overdue.
    TAIL: one counted line per remaining group, split by owner label so the
    50-issue mis-assignment stays visible every morning instead of being
    silently dropped. Counted, never hidden -- dropping them would make this
    function lie by omission, which is the same defect as a silent zero.
    """
    items, tail, errors = owed_items(now, qroot=qroot, graphql=graphql)
    # LEAD_CAP is the Phase 2 narrowing (plan item 2e, decided by convergence:
    # Bloom reads one board of three, Carson's watchdog collapses to three).
    # The withheld line is NOT optional: a truncation that hides its own
    # truncation is the defect (finding-15 asked that the split be DERIVED from
    # the item tags rather than guessed from rendered strings).
    rows = [i["text"] for i in items[:LEAD_CAP]]
    withheld = items[LEAD_CAP:]
    if withheld:
        n_linear = sum(1 for i in withheld if i["source"] == "linear")
        n_loops = sum(1 for i in withheld if i["source"] == "loops")
        rows.append(f"withheld {len(withheld)} more: {n_linear} in Linear, "
                    f"{n_loops} in open-loops")
    # The tail goes LAST and reads as a count, never as a task. It stays because
    # 50 issues labelled owner:sana sitting on the founder's assignee is itself
    # the finding; deleting the line would hide it the morning after it is fixed
    # and every morning it is not.
    if tail["sana"]:
        rows.append(f"({tail['sana']} more assigned to you but labelled {SANA_LABEL} "
                    f"-- Sana's queue, not yours)")
    if tail["other"]:
        rows.append(f"({tail['other']} more assigned to you with no owner label)")
    return rows, ("; ".join(errors) if errors else None)


LEAD_CAP = 3


def owed_items(now: dt.datetime, qroot=None, graphql=None):
    """(items, tail, errors). Structured, provenance-tagged; rendering is
    collect_owed's job. Each item is {"source": "linear"|"loops", "text": str};
    tail counts the groups that are counted-not-listed."""
    qroot = Path(qroot) if qroot else QROOT
    lead, errors = [], []
    sana_count = other_count = 0
    today = now.strftime("%Y-%m-%d")

    if graphql is None:
        try:
            graphql = _load_sibling("linear_sync", "linear-sync.py").graphql
        except Exception as exc:  # noqa: BLE001
            graphql = None
            errors.append(f"linear client unavailable: {type(exc).__name__}: {str(exc)[:120]}")
    if graphql is not None:
        try:
            data = graphql(ASSIGNED_Q, {})
            nodes = ((data or {}).get("viewer") or {}).get("assignedIssues", {}).get("nodes") or []
            for n in nodes:
                labels = {l.get("name") for l in ((n.get("labels") or {}).get("nodes") or [])}
                due = n.get("dueDate")
                ident = n.get("identifier")
                title = str(n.get("title", ""))[:80]
                if due and due <= today:
                    lead.append({"source": "linear", "text": f"DUE {due}  {ident}  {title}"})
                elif FOUNDER_LABEL in labels:
                    lead.append({"source": "linear", "text": f"{ident}  {title}"})
                elif SANA_LABEL in labels:
                    sana_count += 1
                else:
                    other_count += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"linear: {type(exc).__name__}: {str(exc)[:140]}")

    # ONE resolver for the loop ledger, and MISSING IS NOT EMPTY -- both rules
    # belong to loops_path.py, which exists because four readers resolved three
    # different paths and a warm inbound sat unanswered for 46 days while every
    # one of them rendered "no open loops".
    try:
        loops_mod = _load_sibling("loops_path", "loops_path.py")
        loops, status = loops_mod.load(qroot)
        if status != loops_mod.FOUND:
            errors.append(f"open-loops ledger unreadable under {qroot}")
        else:
            for loop in loops:
                if loop.get("status") == "open" and loop.get("needs_founder"):
                    lead.append({"source": "loops",
                                 "text": f"loop {loop.get('id')}  {str(loop.get('title', ''))[:80]}"})
    except Exception as exc:  # noqa: BLE001
        errors.append(f"loops: {type(exc).__name__}: {str(exc)[:120]}")

    return lead, {"sana": sana_count, "other": other_count}, errors


# ---------------------------------------------------------------------------
# Section 4: what ran overnight
# ---------------------------------------------------------------------------

def _watched_labels():
    """Every launchd job the fleet watchdog already watches. Reused, not
    re-derived: a second discovery rule would drift from the first, and the
    watchdog's prefix set is the one that gets maintained."""
    health = _load_sibling("launchd_health", "launchd-health-check.py")
    labels, seen = [], set()
    for prefix in health.load_watched_prefixes():
        for plist in sorted(health.LAUNCH_AGENTS.glob(f"{prefix}*.plist")):
            if plist.stem in seen:
                continue
            seen.add(plist.stem)
            labels.append(plist.stem)
    return labels, health.job_status, health.load_paused_labels()


def collect_overnight(now: dt.datetime, status_fn=None, labels=None, paused=None):
    """(rows, error). Names the jobs that did NOT do their job.

    Reporting all ~70 healthy labels every morning is noise the founder would
    learn to skip, and a brief nobody reads is the failure mode one level up. So
    a clean night renders as one line saying how many jobs were checked, and the
    named rows are the failures.
    """
    if status_fn is None or labels is None:
        try:
            discovered, status_fn_disc, paused_disc = _watched_labels()
        except Exception as exc:  # noqa: BLE001
            return [], f"cannot read launchd jobs: {type(exc).__name__}: {str(exc)[:140]}"
        labels = discovered if labels is None else labels
        status_fn = status_fn_disc if status_fn is None else status_fn
        paused = paused_disc if paused is None else paused
    paused = paused or set()

    if not labels:
        # A discovery that finds nothing is broken discovery. On this machine the
        # watched prefixes match ~70 plists; zero means the glob, the prefix file
        # or LaunchAgents itself moved, and rendering that as a quiet night is
        # the 148-day silence in miniature.
        return [], "no watched launchd jobs found at all (discovery is broken, not the night quiet)"

    failed, stopped, paused_rows, unknown = [], [], [], 0
    for label in labels:
        kind, code = status_fn(label)
        if kind == "unknown":
            unknown += 1
        elif kind == "failing":
            failed.append(f"FAILED  {label}  (exit {code})")
        elif kind == "not_loaded":
            if label in paused:
                paused_rows.append(label)
            else:
                stopped.append(f"NOT RUNNING  {label}  (installed but not loaded)")
    # ORDER IS THE MESSAGE, and the 15-row cap makes it load-bearing. Measured on
    # the first live run: 26 jobs are paused on purpose and they sorted ahead of
    # the two that had actually failed, so the cap ate both real findings and the
    # section read as a wall of "paused". A brief whose signal is below the fold
    # is the "output nobody reads" failure wearing a different hat. Paused jobs
    # are still reported -- as one counted line, because a deliberate pause is a
    # fact about a decision, not about last night.
    rows = failed + stopped
    if paused_rows:
        rows.append(f"({len(paused_rows)} more paused on purpose)")
    if unknown:
        # launchctl unreadable for any job means this section cannot make its
        # claim. Partial silence here is indistinguishable from health.
        return rows, f"launchctl unreadable for {unknown} of {len(labels)} jobs"
    if not rows:
        return [f"all {len(labels)} scheduled jobs clean"], None
    return rows, None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _section(title, rows, error, cap=MAX_ROWS):
    """Lifted from daily-linear-digest.py deliberately. Same shape, same words,
    so a reader who knows one message knows the other."""
    if error:
        return [f"*{title}*", f"  COULD NOT READ: {error}"]
    if not rows:
        return [f"*{title}*", "  nothing"]
    out = [f"*{title}*"] + [f"  {r}" for r in rows[:cap]]
    if len(rows) > cap:
        out.append(f"  ...and {len(rows) - cap} more")
    return out


# THE FOUNDER'S SECTIONS. Consulting only, 2026-09-03, founder-directed:
# "I'm not looking for this to be a build dashboard, but a consulting dashboard."
#
# `owed` (Linear) and `overnight` (launchd) LEFT this tuple and did NOT stop being
# collected. They are engineering signal, and `founder-notifications.md` has said since
# 2026-08-10 that engineering signal goes to Sana's Linear triage and never to him:
# "I dont want to see any of these." They now render through ENGINEERING_SECTIONS into
# slack-notify.sh. Deleting the collectors instead would have been the wrong fix twice
# over -- it would drop the deadman's view of overnight jobs, and it would silently
# retire `notion_board`'s only input.
SECTIONS = (
    ("calendar", "Today"),
    # The window is INTERPOLATED, never typed. It read "(48h)" while the prompt also
    # said 48 hours, so when the window was wrong the label agreed with it and the
    # section looked correct. A number written twice is a number that will disagree.
    ("mail", f"Mail needing an answer ({MAIL_WINDOW_DAYS}d)"),
)

#: Collected, never rendered to him. One line each into Sana's queue, and only when the
#: section is degraded: a healthy overnight run is not news and a ticket per morning is
#: how an alert channel gets muted.
ENGINEERING_SECTIONS = (
    ("owed", "Owed today"),
    ("overnight", "Overnight jobs"),
)


# Optional sections live in their OWN sibling modules and register here, once.
# Each module exposes `collect(now, sources) -> (rows, error)` and receives the
# fixed four sections already collected. Why a registry and not more code in
# collect_all(): Codex finding-2 on prd-morning-brief-learns (2026-09-01) --
# four issues were about to edit this file, which is the serialization hazard
# the single-owner rule exists to remove. A module that is absent renders no
# section and logs ONE line; absent is not "nothing", and it is not an error.
# Entries name the FILE, not the stem. The capability gate finds a wired engine
# by its filename on a wiring surface (this file is one); a bare stem here left
# notion_board.py reported inert on CI while this registry was its real caller
# (PR #294, 2026-09-02). _optional_module accepts either spelling.
OPTIONAL_SECTIONS = (
    # consulting_board runs FIRST: board_rows reads its buckets, and the registry is
    # ordered, so a later entry sees the earlier one's result in `sources`.
    ("consulting_board.py", "consulting", "Your book"),
    ("groupme_inbox.py", "groupme", "GroupMe waiting on you"),
    ("unknown_terms.py", "unknown_terms", "Terms I do not know"),
    ("board_rows.py", "board_rows", "Notion board"),
    # notion_board.py is UNREGISTERED here, and the comment this replaces was wrong.
    # It claimed the module would fall quiet because `owed` had left the founder's
    # sections. It did not: `owed` is still COLLECTED in collect_all's fixed tuple, so
    # notion_board's guard never fired and the first live dry-run rendered its bullets
    # right underneath board_rows' rows. Two writers on one board, which is the exact
    # thing this work exists to stop. Its bullets were never visible in the board's own
    # views anyway: the three sections are FILTERED VIEWS of the Kipi backlog database
    # split by the Bucket select, measured 2026-09-03. The file and its tests stay on
    # disk; only its registration is removed, so the revert is one line.
)

ERROR_LOG = STATE_DIR / "logs" / "morning-brief-errors.log"
COLLECT_BUDGET_S = 20.0
# The fixed four are bounded too (PR #294 review, major: `fixed_budget_s=None`
# meant one hung calendar or mail call held the 07:00 brief, its Slack send and
# its receipt forever, and the 09:00 deadman was the first thing to notice).
# Calendar and mail shell `claude -p` under CLAUDE_TIMEOUT, so the thread bound
# sits one minute above it: the subprocess timeout fires first in the normal
# case and this is the backstop for a collector that hangs before or after it.
FIXED_BUDGET_S = float(CLAUDE_TIMEOUT + 60)


def _optional_module(stem: str):
    """The module for an optional section, or None when its file is absent.
    Separate from _load_sibling so a test can swap it without touching disk.
    `stem` may carry its .py suffix (the registry does, see OPTIONAL_SECTIONS)."""
    if stem.endswith(".py"):
        stem = stem[:-3]
    path = HERE / f"{stem}.py"
    if not path.is_file():
        return None
    return _load_sibling(stem, f"{stem}.py")


def _log_line(log_path, text: str) -> None:
    try:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{dt.datetime.now().isoformat(timespec='seconds')} {text}\n")
    except OSError:
        pass  # the log is diagnostic; losing it must not cost the brief


def _guarded(key: str, fn, budget_s: float, log_path) -> tuple:
    """Run one collector behind the boundary every section shares.

    Two rules, both from Codex findings on prd-morning-brief-learns:
    - finding-14: the exception MESSAGE never reaches the founder-facing brief.
      A mail/HTTP/parser error can carry a token, a URL or a payload fragment.
      The brief gets `<key> failed (<Type>)`; the message goes to the local log.
    - finding-4: a collector is bounded. The board writer runs here, before the
      Slack send, so a hung Notion call must cost at most `budget_s`, never the
      morning. The worker thread is abandoned on timeout; the brief moves on.

    THIS GUARD BOUNDS THE WAIT, NOT THE WORK. Codex round 4 on the consulting board
    (major): an abandoned worker that MUTATES (board_rows, the only one) kept writing
    Notion rows after this returned "timed out". A guard that cannot cancel what it
    abandons is the wrong place to fix that, so the rule is on the collector: a
    mutating collector owns a budget BELOW `budget_s`, checks it before every call
    and caps the call in flight to what is left (notion_board._Budget, shared). Then
    its own cancel fires first and this guard is only the backstop.
    test_consulting_board pins board_rows.BUDGET_S < COLLECT_BUDGET_S.
    """
    # A DAEMON thread, not a ThreadPoolExecutor. Codex review of this issue
    # (findings 1 and 2, 2026-09-01): pool workers are non-daemon and the
    # interpreter joins them at exit, so a collector that never returns would
    # keep the 07:00 process alive forever after the brief had "moved on". A
    # daemon thread is abandoned at exit; the brief, the send and the receipt
    # all complete on schedule.
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["exc"] = exc

    worker = threading.Thread(target=run, name=f"brief-{key}", daemon=True)
    worker.start()
    worker.join(timeout=budget_s)
    if worker.is_alive():
        _log_line(log_path, f"{key}: timed out after {budget_s}s")
        return [], f"{key} timed out ({budget_s}s)"
    if "exc" in box:
        exc = box["exc"]
        _log_line(log_path, f"{key}: {type(exc).__name__}: {exc}")
        return [], f"{key} failed ({type(exc).__name__})"
    return box["value"]


def build(now: dt.datetime, sources: dict):
    """(message, degraded). `sources` maps section key -> (rows, error).
    The fixed four always render; an optional section renders only when it
    was collected (an absent module produces no key, and no section)."""
    lines = [f"*Morning brief* {now.strftime('%A %Y-%m-%d')} "
             f"(built {now.strftime('%H:%M %Z')})", ""]
    degraded = False
    for key, title in SECTIONS:
        rows, error = sources.get(key, ([], f"section {key} was never collected"))
        if error:
            degraded = True
        lines += _section(title, rows, error)
        lines.append("")
    for _stem, key, title in OPTIONAL_SECTIONS:
        if key not in sources:
            continue
        rows, error = sources[key]
        if error:
            degraded = True
        lines += _section(title, rows, error)
        lines.append("")
    for key, _title in ENGINEERING_SECTIONS:
        # DEGRADED WITHOUT RENDERING. Found by its own test: moving these two out of
        # SECTIONS also moved them out of this flag, and the flag is what the deadman
        # and the receipt read. A section that stops being VISIBLE to him must not
        # quietly stop being MONITORED -- that is the failure deleting the collectors
        # would have caused, arriving by another door.
        _rows, error = sources.get(key, ([], None))
        if error:
            degraded = True
    return "\n".join(lines).rstrip(), degraded


def route_engineering(sources: dict, notify=None) -> list:
    """Engineering sections leave his brief for Sana. Delegates to engineering_route.

    The routing lives in a SIBLING module, not here, because
    `test_no_source_file_calls_slack_notify` greps this file for "slack-notify" and is
    right to: the founder's brief must never go out through the fleet alert path. That
    guard caught the first version of this function, which is the guard working.
    """
    mod = _load_sibling("engineering_route", "engineering_route.py")
    return mod.route(sources, ENGINEERING_SECTIONS, notify=notify)   # (filed, failed)


#: What the hourly run collects. Mail and GroupMe are the inbox; board_rows paints it.
#: consulting_board is here for the healthy-scope reason in main(), not for its rows.
#: Calendar, Linear and the launchd sweep are DELIBERATELY absent: none of them change
#: within an hour in a way he would act on, and each costs a model call or a sweep.
HOURLY_SECTIONS = ("consulting_board.py", "groupme_inbox.py", "board_rows.py")


def collect_hourly(now: dt.datetime, log_path=None, budget_s: float = COLLECT_BUDGET_S,
                   fixed_budget_s: float = None) -> dict:
    """Mail + GroupMe + the board paint. Same guards, same (rows, error) contract,
    same budgets as collect_all -- this is a narrower SELECTION, never a second
    implementation, because two collectors drift and one of them is the one nobody
    watches."""
    log_path = log_path or ERROR_LOG
    if fixed_budget_s is None:
        fixed_budget_s = FIXED_BUDGET_S
    sources = {"mail": _guarded("mail", lambda: collect_mail(now),
                                fixed_budget_s, log_path)}
    for stem, key, _title in OPTIONAL_SECTIONS:
        if stem not in HOURLY_SECTIONS:
            continue
        absent = object()

        def load_and_collect(stem=stem):
            mod = _optional_module(stem)
            if mod is None:
                return absent
            return mod.collect(now, dict(sources))

        result = _guarded(key, load_and_collect, budget_s, log_path)
        if result is absent:
            _log_line(log_path, f"hourly section {key}: module {stem} absent")
            continue
        if result is None:
            _log_line(log_path, f"hourly section {key}: module {stem} reports off")
            continue
        sources[key] = result
    return sources


def collect_all(now: dt.datetime, log_path=None, budget_s: float = COLLECT_BUDGET_S,
                fixed_budget_s: float = None) -> dict:
    """`budget_s` bounds the OPTIONAL sections (the board's Notion round trip,
    finding-4). The fixed four bound themselves: calendar and mail shell
    `claude -p` under CLAUDE_TIMEOUT, and the first live dry-run of this code
    (2026-09-01) showed mail alone needs more than 20s, so a shared 20s bound
    would have cost the founder his mail every morning. `fixed_budget_s` exists
    so a test can prove the timeout path without waiting on a real collector."""
    log_path = log_path or ERROR_LOG
    if fixed_budget_s is None:
        fixed_budget_s = FIXED_BUDGET_S  # read at call time so a test can lower it
    fixed = (
        ("calendar", lambda: collect_calendar(now)),
        ("mail", lambda: collect_mail(now)),
        ("owed", lambda: collect_owed(now)),
        ("overnight", lambda: collect_overnight(now)),
    )
    sources = {key: _guarded(key, fn, fixed_budget_s, log_path) for key, fn in fixed}
    for stem, key, _title in OPTIONAL_SECTIONS:
        # The import runs INSIDE the guard (Codex finding-3 on this issue): a
        # module that exists but raises or hangs at import time is a failing
        # section, never a failing brief. ABSENT is the one signal that escapes
        # the guard, because it is not an error.
        absent = object()

        def load_and_collect(stem=stem):
            mod = _optional_module(stem)
            if mod is None:
                return absent
            return mod.collect(now, dict(sources))

        result = _guarded(key, load_and_collect, budget_s, log_path)
        if result is absent:
            _log_line(log_path, f"optional section {key}: module {stem} absent, not rendered")
            continue
        if result is None:
            # The OFF signal (amendment on mbl-board-section-bounded): a present
            # module that returns None has decided it is switched off, e.g. the
            # board with no page-id file. Not an error, not "nothing": no section.
            _log_line(log_path, f"optional section {key}: module {stem} reports off, not rendered")
            continue
        sources[key] = result
    return sources


# ---------------------------------------------------------------------------
# The receipt the deadman reads
# ---------------------------------------------------------------------------

def write_receipt(result: dict, now: dt.datetime, receipt_path=None) -> Path:
    """Single writer of the freshness receipt.

    Written LAST and only after the send has answered, so the recorded state is
    what Slack said rather than what this script intended. `delivered` is copied
    straight off the send result; there is no separate "I tried" flag that could
    drift from it.
    """
    path = Path(receipt_path) if receipt_path else RECEIPT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": now.strftime("%Y-%m-%d"),
        "at": now.isoformat(timespec="seconds"),
        "delivered": bool(result.get("delivered")),
        "transport": result.get("transport"),
        "reason": result.get("reason") or result.get("error"),
        "degraded": result.get("degraded"),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic: the deadman may read while this writes
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="build and print; send nothing, write no receipt")
    ap.add_argument("--inbox-only", action="store_true",
                    help="mail + GroupMe + the Notion board, nothing else. The hourly "
                         "runner: no Slack message, no receipt, no calendar, no Linear, "
                         "no launchd sweep.")
    args = ap.parse_args(argv)

    now = dt.datetime.now().astimezone()

    if args.inbox_only:
        # Founder-directed 2026-09-03: *"the email and groupme should be once an
        # hour."* The board is where he looks; a once-a-day inbox means a client who
        # writes at 08:00 is invisible until tomorrow.
        #
        # NO SLACK SEND, on purpose. Twelve messages a day is how a channel gets
        # muted, and the 07:00 brief already carries the daily read. This run only
        # repaints the board.
        #
        # consulting_board IS collected even though nothing here changes its rows,
        # because board_rows archives only inside the scopes reported healthy. Skip it
        # and the client scope is absent, not healthy, so those rows are KEPT -- but
        # relying on that is relying on a safety net rather than on the design. Cheap
        # anyway: it is three file reads.
        if args.dry_run:
            os.environ["KIPI_BRIEF_DRY_RUN"] = "1"
        sources = collect_hourly(now)
        for key in ("mail", "groupme", "board_rows"):
            if key not in sources:
                # OFF IS NOT BROKEN, and this line said it was (Codex round 7, minor).
                # `collect_hourly` omits a module that reported itself off -- no
                # GroupMe token, no Notion token -- which is the default on any fleet
                # machine, so a healthy run printed two COULD NOT READ lines twelve
                # times a day. It inverted the empty-versus-broken rule the whole file
                # is built on, in the one surface an operator actually reads.
                print(f"[{key}] off (not configured on this machine)")
                continue
            rows, error = sources[key]
            if error:
                print(f"[{key}] COULD NOT READ: {error}")
            else:
                print(f"[{key}] {len(rows)} row(s)")
        # Exit 1 on a degraded run so launchd column 2 shows it and the fleet
        # watchdog can see a broken hour without a human reading a log. An OFF
        # section is not degraded: it is absent from `sources` and contributes
        # nothing here, which is why this reads the dict rather than a default.
        return 1 if any(sources[k][1] for k in ("mail", "groupme", "board_rows")
                        if k in sources) else 0

    if args.dry_run:
        # Reaches the optional sections, which can write to places the send flag never
        # covered. Set before collect_all, because collection IS when they write.
        os.environ["KIPI_BRIEF_DRY_RUN"] = "1"
    sources = collect_all(now)
    # Engineering leaves BEFORE the founder's message is built, so a routing failure
    # cannot silently become a section he reads.
    filed, failed = route_engineering(
        sources, notify=(lambda _m: None) if args.dry_run else None)
    for line in filed:
        # DRY RUN SAYS SO (round 11, minor). The notifier injected above sends
        # nothing, and this printed the same "[to sana]" either way, so a dry run
        # reported an alert that no one received. Every other refusal in this file
        # names itself; this one claimed a delivery.
        print(f"[to sana{' (dry run, not sent)' if args.dry_run else ''}] {line}")
    for line, why in failed:
        # Printed as NOT filed. An engineering problem that was detected and then lost
        # on the way to the queue is worse than one never detected: it looks handled.
        print(f"[to sana FAILED, not filed] {line} :: {why}")
    message, degraded = build(now, sources)
    print(message)
    if args.dry_run:
        print("\n[dry-run] nothing sent, no receipt written")
        return 0

    sender = _load_sibling("slack_founder", "slack_founder.py")
    result = sender.deliver(message)
    result["degraded"] = degraded
    print(f"\n[send] {json.dumps(result)}")
    receipt = write_receipt(result, now)
    print(f"[receipt] {receipt}")
    if not result.get("delivered"):
        return 1
    return 1 if degraded else 0


if __name__ == "__main__":
    raise SystemExit(main())
