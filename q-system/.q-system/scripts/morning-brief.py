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
import concurrent.futures
import datetime as dt
import importlib.util
import json
import os
import re
import subprocess
import sys
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

MAIL_PROMPT = """Call {tool} to find email threads from the last 48 hours where a
REAL PERSON wrote to the founder and the founder has not replied yet. Exclude
newsletters, notifications, receipts, calendar invites, automated senders and
no-reply addresses.
Reply with ONE JSON object and nothing else, no prose, no code fence:
{{"threads": [{{"from": "email or name", "subject": "...", "age_hours": <int>}}]}}
If the tool call fails, reply with exactly: {{"error": "<what failed>"}}"""


def collect_mail(now: dt.datetime, runner=None):
    runner = runner or (lambda p, t: run_claude(p, t))
    text, error = runner(MAIL_PROMPT.format(tool=MAIL_TOOL), [MAIL_TOOL])
    if error:
        return [], error
    threads, parse_error = _parse_json_block(text, "threads")
    if parse_error:
        return [], parse_error
    rows = []
    for th in threads:
        if not isinstance(th, dict):
            continue
        age = th.get("age_hours")
        age_text = f"  [{age}h]" if isinstance(age, int) else ""
        rows.append(f"{str(th.get('from', 'unknown'))[:40]}  {str(th.get('subject', ''))[:70]}{age_text}")
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


SECTIONS = (
    ("calendar", "Today"),
    ("mail", "Mail needing an answer (48h)"),
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
OPTIONAL_SECTIONS = (
    ("unknown_terms", "unknown_terms", "Terms I do not know"),
    ("notion_board", "board", "Notion board"),
)

ERROR_LOG = STATE_DIR / "logs" / "morning-brief-errors.log"
COLLECT_BUDGET_S = 20.0


def _optional_module(stem: str):
    """The module for an optional section, or None when its file is absent.
    Separate from _load_sibling so a test can swap it without touching disk."""
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
    """
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(fn)
        try:
            return future.result(timeout=budget_s)
        except concurrent.futures.TimeoutError:
            _log_line(log_path, f"{key}: timed out after {budget_s}s")
            return [], f"{key} timed out ({budget_s}s)"
        except Exception as exc:  # noqa: BLE001
            _log_line(log_path, f"{key}: {type(exc).__name__}: {exc}")
            return [], f"{key} failed ({type(exc).__name__})"
    finally:
        pool.shutdown(wait=False)


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
    return "\n".join(lines).rstrip(), degraded


def collect_all(now: dt.datetime, log_path=None, budget_s: float = COLLECT_BUDGET_S,
                fixed_budget_s=None) -> dict:
    """`budget_s` bounds the OPTIONAL sections (the board's Notion round trip,
    finding-4). The fixed four bound themselves: calendar and mail shell
    `claude -p` under CLAUDE_TIMEOUT, and the first live dry-run of this code
    (2026-09-01) showed mail alone needs more than 20s, so a shared 20s bound
    would have cost the founder his mail every morning. `fixed_budget_s` exists
    so a test can prove the timeout path without waiting on a real collector."""
    log_path = log_path or ERROR_LOG
    fixed = (
        ("calendar", lambda: collect_calendar(now)),
        ("mail", lambda: collect_mail(now)),
        ("owed", lambda: collect_owed(now)),
        ("overnight", lambda: collect_overnight(now)),
    )
    sources = {key: _guarded(key, fn, fixed_budget_s, log_path) for key, fn in fixed}
    for stem, key, _title in OPTIONAL_SECTIONS:
        mod = _optional_module(stem)
        if mod is None:
            _log_line(log_path, f"optional section {key}: module {stem} absent, not rendered")
            continue
        sources[key] = _guarded(key, lambda m=mod: m.collect(now, dict(sources)),
                                budget_s, log_path)
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
    args = ap.parse_args(argv)

    now = dt.datetime.now().astimezone()
    message, degraded = build(now, collect_all(now))
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
