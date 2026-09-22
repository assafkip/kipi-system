#!/usr/bin/env python3
"""One Slack message a day: what closed, what opened, what could not be worked.

Founder-directed 2026-08-13: "I want to create a mechanism that pings me once a day
on slack with which linear issues were closed today -- what they are about / New
linear issues opened today -- what they are about / Linear issues that you tried and
could not be worked - why. I want it every day at 4pm PST."

## The three sections and where each comes from

- CLOSED / OPENED: Linear itself, via `linear-sync.graphql`. One client, reused, not
  a second one -- two readers of one API is the derivation split this fleet keeps
  paying for.
- COULD NOT BE WORKED: `~/.config/kipi/linear-worker.log`, which ALREADY records it:
  "held at needs-scope (refused as unexecutable)", "held at blocked:capability",
  "skipped as out-of-repo". That log existed before this digest; nothing was
  invented to feed it.

## Two rules this thing must never break

**An empty section and a broken section are different facts.** If the Linear query
fails, this says FAILED. It never prints "0 closed today", because a silent zero
reading as a quiet day is the exact defect the 2026-07-21 silent-delivery RCA is
about, and shipping it inside a status digest would be absurd.

**The send is verified, not assumed.** `slack-notify.sh` is a silent no-op that
still exits 0 when no webhook resolves. So delivery is recorded separately from the
attempt, and a run that could not deliver says so on stdout where launchd logs it.

## Its own deadman is the founder

A daily message that stops arriving is visible to a human on day one, which is more
than most of this fleet's watchdogs manage. It still stamps its own run in the
message so a stale pin is obvious.

    python3 daily-linear-digest.py            # send
    python3 daily-linear-digest.py --dry-run  # print, send nothing
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
from pathlib import Path

HERE = Path(__file__).resolve().parent
_STATE = Path(os.environ.get("KIPI_STATE_DIR", os.path.expanduser("~/.config/kipi")))
WORKER_LOG = _STATE / "linear-worker.log"
# ASK-729: the second producer. "Could not be worked" is written in two places --
# the worker says what it refused to pick, the dispatcher says which repos it
# refused to ENTER. Reading only the worker made the entire cross-repo hold
# invisible for 13 days, which is the failure this section exists to prevent.
DISPATCH_LOG = _STATE / "dispatch.log"
NOTIFY = HERE / "slack-notify.sh"


def _linear():
    """The existing client. One reader of the Linear API, never a second."""
    spec = importlib.util.spec_from_file_location("linear_sync", HERE / "linear-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# PAGINATED. `first: 100` with no cursor silently dropped everything past the
# hundredth updated issue, so a busy day reported a short list as if it were the
# whole day -- a silent cap inside the tool whose job is saying what happened.
ISSUES_Q = """
query($after: DateTimeOrDuration!, $cursor: String) {
  issues(filter: {updatedAt: {gte: $after}}, first: 100, after: $cursor) {
    nodes { identifier title url createdAt completedAt canceledAt
            state { name type } }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def fetch(since_iso: str):
    """(closed, opened, error). `error` is a string when the API could not answer.

    Returning an error rather than an empty list is the whole contract: a caller
    that cannot tell "nothing happened" from "I could not look" will report the
    first when it means the second.
    """
    nodes, cursor, pages = [], None, 0
    try:
        ls = _linear()
        while True:
            data = ls.graphql(ISSUES_Q, {"after": since_iso, "cursor": cursor})
            block = (data or {}).get("issues") or {}
            nodes.extend(block.get("nodes") or [])
            info = block.get("pageInfo") or {}
            pages += 1
            # A bound, because an unbounded loop against a paging API is its own
            # outage. 20 pages is 2000 issues; past that the digest says so rather
            # than truncating quietly.
            if not info.get("hasNextPage") or pages >= 20:
                if info.get("hasNextPage"):
                    return [], [], f"more than {len(nodes)} issues updated today; digest would be partial"
                break
            cursor = info.get("endCursor")
    except Exception as exc:  # noqa: BLE001
        return [], [], f"{type(exc).__name__}: {str(exc)[:180]}"
    closed = [n for n in nodes if n.get("completedAt", "") and n["completedAt"] >= since_iso]
    opened = [n for n in nodes if n.get("createdAt", "") and n["createdAt"] >= since_iso]
    return closed, opened, None


# Lines the worker writes when it looked at an issue and could not take it. Kept as
# data so a change in the worker's wording shows up as a diff here rather than as a
# silently empty section.
# The COUNT is part of the fact. An earlier version matched from "held at" onward
# and dropped the leading "2 issue(s)", which turned a number into a vibe.
BLOCKED_PATTERNS = (
    re.compile(r"\d+ issue\(s\) held at needs-scope[^\n]*"),
    re.compile(r"\d+ issue\(s\) held at blocked:[^\n]*"),
    re.compile(r"\d+ ready-shaped issue\(s\) skipped as out-of-repo[^\n]*"),
    # ASK-729. These two are the "whether or not it is fully fixed" half: while
    # cross-repo dispatch stays held, the digest still has to say how much work is
    # stranded and why, every day, instead of the gap living in one log line
    # nobody reads.
    re.compile(r"\d+ ready-shaped issue\(s\) UNREACHABLE: no local checkout[^\n]*"),
    # ASK-840. The third bucket: the checkout exists, and repo-preflight refuses
    # entry anyway. It needs its own line here because the response differs from
    # both neighbours -- a routine skip resolves on a later rotation turn, an
    # unreachable repo needs a clone, and this one needs a cure or is permanent
    # (a client engagement repo is refused forever, whatever its name resolves to).
    re.compile(r"\d+ ready-shaped issue\(s\) REFUSED by preflight[^\n]*"),
    re.compile(r"\d+ repo\(s\) HELD \(cross-repo gh scoping[^\n]*"),
)

# Which producer each pattern reads. Kept explicit so a pattern cannot silently
# scan a log that never emits it and read as a healthy "nothing".
BLOCKED_SOURCES = (WORKER_LOG, DISPATCH_LOG)


def blocked_today(window: tuple):
    """(lines, error). Reads the producers own logs; invents no state of its own."""
    # The WORKER log staying required is deliberate: it is the one that always
    # exists on a healthy machine, so its absence is a real fault worth shouting
    # about. A missing dispatch.log only means the dispatcher has not run yet,
    # which is not an error and must not blank the whole section.
    if not WORKER_LOG.exists():
        return [], f"no worker log at {WORKER_LOG}"
    chunks = []
    for src in BLOCKED_SOURCES:
        if not src.exists():
            continue
        try:
            chunks.append(src.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            return [], f"unreadable log {src}: {exc}"
    text = "\n".join(chunks)
    # LAST occurrence per pattern, not every one. The worker runs several times a
    # day and each run logs its own counts, so listing them all showed "44 skipped"
    # and "45 skipped" as if they were two facts. They are one fact, measured twice.
    latest = {}
    for line in text.splitlines():
        # A TIME RANGE, not a date prefix. Two clocks were in play and neither was
        # wrong alone: the logs stamp UTC, the reader lives in local time. Matching a
        # UTC prefix while labelling the message with the local date reported a
        # window spanning two local days under one local heading. Matching a local
        # prefix found nothing at all, because the log never writes that string.
        # One definition wins: the reader's own day, expressed as UTC bounds.
        stamp = line[:20]
        try:
            ts = dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        if not (window[0] <= ts <= window[1]):
            continue
        for i, pat in enumerate(BLOCKED_PATTERNS):
            m = pat.search(line)
            if m:
                latest[i] = m.group(0)
    return [latest[i] for i in sorted(latest)], None


def _section(title, rows, error, fmt):
    if error:
        # Loud, and never mistakable for a quiet day.
        return [f"*{title}*", f"  COULD NOT READ: {error}"]
    if not rows:
        return [f"*{title}*", "  nothing"]
    return [f"*{title}*"] + [f"  {fmt(r)}" for r in rows[:15]] + (
        [f"  ...and {len(rows) - 15} more"] if len(rows) > 15 else [])


def build(now: dt.datetime):
    # MATCH THE LOG'S OWN CLOCK. `linear-worker.log` and `dispatch.log` prefix every
    # line with a UTC stamp (`date -u`), and this compared them against the LOCAL
    # date. Measured 2026-08-13 21:5x PDT: local said 2026-08-13 while the logs were
    # already writing 2026-08-14, so the "could not be worked" section matched zero
    # lines and printed "nothing" on a day full of them. A silent empty, inside the
    # tool built to stop silent empties. The header keeps the LOCAL date because that
    # is the day the reader is having.
    local_day = now.strftime("%Y-%m-%d")
    since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # The reader's day, in UTC bounds, so the filter and the heading describe the
    # same span of time.
    window = (since.astimezone(dt.timezone.utc), now.astimezone(dt.timezone.utc))
    since_iso = since.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    closed, opened, api_err = fetch(since_iso)
    blocked, log_err = blocked_today(window)

    lines = [f"*Linear daily* {local_day} (as of {now.strftime('%H:%M %Z')})", ""]
    lines += _section("Closed today", closed, api_err,
                      lambda n: f"{n['identifier']} {n['title'][:90]}")
    lines.append("")
    lines += _section("Opened today", opened, api_err,
                      lambda n: f"{n['identifier']} {n['title'][:90]}")
    lines.append("")
    lines += _section("Tried, could not be worked", blocked, log_err, lambda s: s)
    return "\n".join(lines), (api_err or log_err)


def send(message: str):
    """Delegate to slack_founder.deliver(). Verified by Slack's answer, as before.

    ## Why this changed (2026-08-30, ASK-1178)

    This function used to read `~/.config/kipi/slack-webhook` itself and POST to
    it. That file was RETIRED on 2026-08-19 (`slack-webhook.retired-2026-08-19`
    is still on disk beside an older `.old-workspace`) and nothing repointed
    this job. Measured in its own log, `~/.config/kipi/logs/linear-daily-digest.out.log`:
    11 `delivered: False` against 5 `delivered: True`, every recent one reading
    `no webhook`. Eleven days of a correct 4pm digest going nowhere.

    The job was never broken. Its only transport was decommissioned underneath
    it, and a single-transport sender has no way to survive that. So delivery
    moves to the shared chokepoint, which tries the webhook FIRST (unchanged
    behaviour the day a webhook exists again) and falls back to the bot token.

    ## What did NOT change

    Still not `slack-notify.sh`. That is the fleet ALERT path; it files a Linear
    ticket for Sana and sends nothing to Slack. The first version of this digest
    called it, got exit 0, and recorded `delivered_claim: True` having filed
    ASK-724 -- a status digest as a Linear ticket. Do not "fix" this back.

    Still verified rather than assumed: `deliver()` returns Slack's own verdict,
    read out of the response body, because Slack answers HTTP 200 both for a
    delivered webhook (body `ok`) and for a refused chat.postMessage
    (`{"ok": false, ...}`).
    """
    spec = importlib.util.spec_from_file_location("slack_founder", HERE / "slack_founder.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.deliver(message)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    now = dt.datetime.now().astimezone()
    message, degraded = build(now)
    print(message)
    if args.dry_run:
        print("\n[dry-run] nothing sent")
        return 0
    result = send(message)
    print(f"\n[send] {result}")
    if not result.get("delivered"):
        # Never exit 0 on an undelivered digest. That is the whole defect this
        # script was built in the middle of.
        return 1
    # Non-zero when a section could not be read, so launchd's log and any future
    # watchdog can tell a degraded digest from a clean one.
    return 1 if degraded else 0


if __name__ == "__main__":
    raise SystemExit(main())
