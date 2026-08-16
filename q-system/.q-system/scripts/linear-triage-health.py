#!/usr/bin/env python3
"""Is the triage queue draining, and what has gone quiet? (ASK-882)

WHY THIS EXISTS

Measured on the live board 2026-08-16: 873 issues on team ASK, 229 of them with
no project at all -- created, never routed. That is not a discipline failure. It
is arithmetic: inflow is automated (scanners, alert filers, the DoR drafter) and
outflow is manual, so the board can only grow. `owner:sana` -> `kipi-dispatch.sh`
is the intended drain, and NOTHING measured whether it was keeping pace. A drain
nobody meters is indistinguishable from a drain that stopped.

WHAT IT MEASURES (the three numbers, and why these three)

  unrouted        open issues with no project. This is the 229. An unset project
                  is not cosmetic: linear-worker.sh `in_this_repo()` reads unset
                  as "not this repo", so an unrouted issue is unreachable by every
                  checkout at once. It is the count that best predicts work that
                  can never be picked up.
  needs-triage    open issues carrying the mark an automated filer left. Depth of
                  the queue nobody has routed yet.
  oldest          age in days of the oldest untouched issue in that queue. A
                  count alone hides the shape: 40 issues filed this morning and
                  40 filed in June are the same number and different problems.

DORMANCY LIVES HERE TOO, ON PURPOSE

The dormancy sweep needs exactly the same page of open issues this already
fetches. Splitting it into a second script would mean two paginated walks of the
same board and two places to fix when the query changes. So one fetch, two
readings of it.

IT FLAGS, IT NEVER CLOSES. GitHub's stale-bot pattern is the reference and the
warning: a bot that silently closes real work teaches people the tracker lies.
A dormant issue gets ONE comment and a label. Closing stays a judgment call.

WHY IT EXCLUDES ITS OWN TICKETS

`slack-notify.sh` no longer sends to Slack -- it files a Linear ticket (founder-
directed 2026-08-10, "I dont want to see any of these"). So this script's own
alert becomes an issue on the board this script counts. Left alone, a backlog
monitor would inflate the backlog it reports and then report the inflation. The
exclusion is by title marker and is tested; see SELF_MARKER.

EXIT CODES -- this script never lies about failure
  0  measured cleanly (whether or not it alerted)
  1  usage error
  3  no Linear API key configured -- a setup state, not an error
  4  refused: running under pytest
  9  the run could not complete its measurement (API failure mid-walk). Partial
     numbers are still printed, but the exit code says they are partial.

Deliberately not `exit 0 always`: that shape is its own defect class in this repo
(ASK-213, three silent-success bugs shipped in one day).

Usage:
  linear-triage-health.py                       # measure, print, alert if breached
  linear-triage-health.py --dormant-days 90     # different dormancy threshold
  linear-triage-health.py --apply               # also write dormancy comments
  linear-triage-health.py --no-notify           # never call the alert path
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_NO_KEY = 3
EXIT_REFUSED_FIXTURE = 4
EXIT_INCOMPLETE = 9

HERE = os.path.dirname(os.path.abspath(__file__))

TEAM_KEY = os.environ.get("KIPI_LINEAR_TEAM", "ASK")
TRIAGE_LABEL = "needs-triage"
DORMANT_LABEL = "dormant"

# Default dormancy threshold. 75 days sits inside the 60-90 band the stale-bot
# research describes, and is deliberately NOT 90: the board itself is 22 days old
# as of 2026-08-16, so a 90-day threshold could not fire at all for another two
# months and would read as protection while doing nothing. A guard that cannot
# fire on the population it runs against is decoration.
DEFAULT_DORMANT_DAYS = 75

# Thresholds that make the run worth an alert. Below these the run says nothing:
# "still fine" every day is how a channel stops being read, which is the exact
# scar `slack-notify.sh` was rewritten for.
UNROUTED_ALERT_AT = 50
TRIAGE_ALERT_AT = 40
OLDEST_ALERT_DAYS = 30

# Every alert line this script emits opens with this. It is how the script
# recognises and excludes its OWN tickets from its OWN counts -- see the module
# docstring. Changing it silently re-includes every past self-ticket, so it is
# pinned by test_self_tickets_are_excluded.
SELF_MARKER = "linear-triage-health:"

# Written into every dormancy comment. A re-run finds it and skips, so a nightly
# sweep cannot grow a comment stack on a permanent object. Same device as
# linear-triage.py's MARKER, and for the same reason.
DORMANT_MARKER = "<!-- kipi-dormancy-flag -->"

OPEN_ISSUES_QUERY = """
query($teamId: ID!, $after: String) {
  issues(filter: {team: {id: {eq: $teamId}}}, first: 250, after: $after) {
    nodes {
      id identifier title createdAt updatedAt
      state { name type }
      project { id name }
      labels { nodes { name } }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

COMMENT_CREATE = """
mutation($input: CommentCreateInput!) {
  commentCreate(input: $input) { success }
}
"""

ISSUE_COMMENTS_QUERY = """
query($id: String!) {
  issue(id: $id) { comments(first: 100) { nodes { body } } }
}
"""


def _load_linear():
    """Import linear-sync.py for its auth + graphql. Hyphen forces importlib.

    SINGLE WRITER for how this fleet talks to Linear, the same rule
    alert-to-linear.py follows. Reimplementing the key lookup or the errors-array
    handling here would be a second place to fix when Linear changes, and
    linear-sync.py's graphql() already knows Linear returns HTTP 200 with an
    `errors` key on application failures.
    """
    path = os.path.join(HERE, "linear-sync.py")
    spec = importlib.util.spec_from_file_location("kipi_linear_sync", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parse_iso(stamp: str) -> datetime | None:
    """Linear's ISO-8601 into an aware datetime, or None.

    Linear sends a trailing `Z`, which `fromisoformat` rejected before 3.11. The
    replace keeps this working on whatever python3 a launchd job happens to get,
    rather than on the one this was written against.
    """
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def age_days(stamp: str, now: datetime) -> float | None:
    """Days between `stamp` and `now`, or None when unparseable."""
    when = _parse_iso(stamp)
    if when is None:
        return None
    return (now - when).total_seconds() / 86400.0


def is_open(issue: dict) -> bool:
    """Open means not completed and not canceled.

    Read off `state.type`, never `state.name`: the names are per-team strings a
    human can rename, the types are Linear's own closed set. This team also
    carries a `Duplicate` state whose type is `duplicate`, which is neither open
    work nor a completion -- treating it as open would keep dead issues in the
    count forever.
    """
    state_type = ((issue.get("state") or {}).get("type") or "").lower()
    return state_type not in ("completed", "canceled", "duplicate")


def label_names(issue: dict) -> set:
    """Lowercased label names on an issue."""
    nodes = ((issue.get("labels") or {}).get("nodes")) or []
    return {(n.get("name") or "").lower() for n in nodes}


def is_self_ticket(issue: dict) -> bool:
    """A ticket THIS script's own alert path filed.

    Excluded from every count. `slack-notify.sh` files a Linear ticket rather
    than sending to Slack, so without this a backlog monitor reports its own
    output as backlog and then alerts about the number it just caused.
    """
    return SELF_MARKER in (issue.get("title") or "")


def is_unrouted(issue: dict) -> bool:
    """Open, and carrying no project.

    An unset project is what makes an issue unreachable rather than merely
    untidy: linear-worker.sh `in_this_repo()` reads unset as "not this repo", so
    no checkout claims it.
    """
    return not ((issue.get("project") or {}).get("id"))


def measure(issues: list, now: datetime) -> dict:
    """The three numbers, over already-filtered open non-self issues.

    Pure: takes the list, returns the dict, touches no network. That is what
    lets the test drive it with fixtures and assert literal numbers rather than
    asserting a value it computed the same way the code did.
    """
    unrouted = [i for i in issues if is_unrouted(i)]
    triage = [i for i in issues if TRIAGE_LABEL in label_names(i)]

    oldest_days, oldest_id = 0.0, ""
    for issue in triage:
        days = age_days(issue.get("updatedAt") or "", now)
        if days is not None and days > oldest_days:
            oldest_days, oldest_id = days, issue.get("identifier") or ""

    return {
        "open": len(issues),
        "unrouted": len(unrouted),
        "needs_triage": len(triage),
        "oldest_triage_days": round(oldest_days, 1),
        "oldest_triage_id": oldest_id,
    }


def find_dormant(issues: list, now: datetime, threshold_days: int) -> list:
    """Real work that has gone quiet past the threshold.

    REAL, meaning it has a project. An unrouted issue is already counted as
    unrouted; flagging it dormant as well would double-report one problem and
    put a dormancy comment on the noise this system is trying to stop filing in
    the first place. Dormancy is a question about work someone routed and then
    nobody touched.

    Also skips anything already carrying `needs-triage` (it is inflow that has
    not been decided yet, not work that stalled) and anything already labelled
    dormant (the flag is not re-applied).
    """
    out = []
    for issue in issues:
        if is_unrouted(issue):
            continue
        labels = label_names(issue)
        if TRIAGE_LABEL in labels or DORMANT_LABEL in labels:
            continue
        days = age_days(issue.get("updatedAt") or "", now)
        if days is not None and days >= threshold_days:
            out.append((issue, round(days, 1)))
    out.sort(key=lambda pair: pair[1], reverse=True)
    return out


def fetch_open_issues(ln, team_id: str) -> tuple:
    """(issues, complete). One paginated walk, shared by both readings.

    `complete` is False when the walk broke partway. The caller PRINTS the
    partial numbers and exits 9 rather than presenting a short count as the
    answer -- an undercount here reads as "the queue is draining", which is the
    one wrong conclusion this script exists to prevent.
    """
    issues, after = [], None
    while True:
        try:
            page = (ln.graphql(OPEN_ISSUES_QUERY,
                               {"teamId": team_id, "after": after}) or {})
            data = page.get("issues") or {}
        except Exception as exc:
            print(f"WARN: issue walk failed after {len(issues)} issue(s): {exc}",
                  file=sys.stderr)
            return issues, False
        issues.extend(data.get("nodes") or [])
        info = data.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return issues, True
        after = info.get("endCursor")
        if not after:
            # hasNextPage true with no cursor would spin forever on the same
            # page. Stop and say the walk is partial.
            print("WARN: pagination reported more pages but gave no cursor",
                  file=sys.stderr)
            return issues, False


def already_flagged(ln, issue_id: str) -> bool:
    """True when a dormancy comment is already on the issue.

    Checked per issue rather than trusting the label alone: the label can be
    removed by a human who disagrees, and re-adding a comment they already read
    is the comment-stack failure this marker exists to prevent.

    On an API failure this returns True -- skip rather than risk a duplicate.
    Erring toward silence is right here: a missed flag costs one issue staying
    quiet, a duplicated flag costs trust in every flag.
    """
    try:
        issue = (ln.graphql(ISSUE_COMMENTS_QUERY, {"id": issue_id}) or {}).get("issue") or {}
    except Exception:
        return True
    for node in ((issue.get("comments") or {}).get("nodes") or []):
        if DORMANT_MARKER in (node.get("body") or ""):
            return True
    return False


def dormancy_comment(days: float, threshold: int) -> str:
    """The body written onto a dormant issue. Flags, never closes."""
    return (
        f"{DORMANT_MARKER}\n"
        f"**Dormant: no activity in {days:.0f} days** (threshold {threshold}).\n\n"
        f"This is a flag, not a verdict, and nothing was closed. It means nobody "
        f"has touched this since it was routed, which is worth a decision one way "
        f"or the other:\n\n"
        f"- still wanted -> comment or update it and this clears\n"
        f"- superseded or done -> close it with the reason\n"
        f"- real but not now -> say so here, so the next sweep reads an answer "
        f"instead of silence\n\n"
        f"<sub>`linear-triage-health.py`. Flagged once; a re-run finds this "
        f"comment and skips.</sub>"
    )


def flag_dormant(ln, issue: dict, days: float, threshold: int) -> str:
    """Write one dormancy comment. Returns a short outcome for the report."""
    if already_flagged(ln, issue["id"]):
        return "already-flagged"
    try:
        ln.graphql(COMMENT_CREATE, {"input": {
            "issueId": issue["id"],
            "body": dormancy_comment(days, threshold),
        }})
    except Exception as exc:
        return f"FAILED ({exc})"
    return "flagged"


def breaches(m: dict) -> list:
    """Which thresholds this measurement crosses. Empty means stay quiet."""
    out = []
    if m["unrouted"] >= UNROUTED_ALERT_AT:
        out.append(f"{m['unrouted']} unrouted (no project)")
    if m["needs_triage"] >= TRIAGE_ALERT_AT:
        out.append(f"{m['needs_triage']} awaiting triage")
    if m["oldest_triage_days"] >= OLDEST_ALERT_DAYS:
        out.append(f"oldest untriaged {m['oldest_triage_id']} "
                   f"at {m['oldest_triage_days']:.0f}d")
    return out


def notify(line: str) -> int:
    """Send one line through the fleet's single alert path.

    `slack-notify.sh` is the only sanctioned sink (founder-notifications.md), and
    it dedupes by alert SHAPE -- every digit is stripped before fingerprinting --
    so a daily run of this script collapses onto ONE ticket with a counter rather
    than one ticket a day. That property is why a daily cadence is safe here.

    Never raises: a monitoring script that can crash on its own alert is worse
    than the alert being lost.
    """
    script = os.path.join(HERE, "slack-notify.sh")
    if not os.path.isfile(script):
        print(f"WARN: no slack-notify.sh at {script}; not alerting", file=sys.stderr)
        return 1
    try:
        res = subprocess.run(["bash", script, line], capture_output=True,
                             text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"WARN: alert path failed ({exc})", file=sys.stderr)
        return 1
    return res.returncode


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dormant-days", type=int, default=DEFAULT_DORMANT_DAYS,
                    help=f"dormancy threshold in days (default {DEFAULT_DORMANT_DAYS})")
    ap.add_argument("--apply", action="store_true",
                    help="write dormancy comments (default: report only)")
    ap.add_argument("--no-notify", action="store_true",
                    help="never call the alert path")
    ap.add_argument("--json", action="store_true", help="print the measurement as JSON")
    args = ap.parse_args(argv[1:])

    if args.dormant_days < 1:
        print("--dormant-days must be >= 1", file=sys.stderr)
        return EXIT_USAGE

    # FIXTURE GUARD, the same chokepoint alert-to-linear.py uses. A suite written
    # tomorrow must not be able to comment on a real issue or file a real ticket,
    # so the refusal lives here rather than in each test.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        print("linear-triage-health: REFUSED under pytest.", file=sys.stderr)
        return EXIT_REFUSED_FIXTURE

    ln = _load_linear()
    try:
        ln.linear_api_key()
    except Exception as exc:
        print(f"no Linear key configured ({exc})", file=sys.stderr)
        return EXIT_NO_KEY

    try:
        teams = (ln.graphql(ln.TEAM_QUERY, {"key": TEAM_KEY}) or {}).get("teams") or {}
        nodes = teams.get("nodes") or []
    except Exception as exc:
        print(f"team lookup failed ({exc})", file=sys.stderr)
        return EXIT_INCOMPLETE
    if not nodes:
        print(f"no Linear team {TEAM_KEY!r}", file=sys.stderr)
        return EXIT_INCOMPLETE
    team_id = nodes[0]["id"]

    raw, complete = fetch_open_issues(ln, team_id)
    # Filter ONCE, here, so measure() and find_dormant() cannot disagree about
    # which population they describe.
    issues = [i for i in raw if is_open(i) and not is_self_ticket(i)]
    now = datetime.now(timezone.utc)

    m = measure(issues, now)
    dormant = find_dormant(issues, now, args.dormant_days)
    m["dormant"] = len(dormant)
    m["dormant_threshold_days"] = args.dormant_days
    m["complete"] = complete

    if args.json:
        print(json.dumps(m, indent=2))
    else:
        print(f"team {TEAM_KEY}: {m['open']} open "
              f"({len(raw)} fetched, {len(raw) - len(issues)} closed/self)")
        print(f"  unrouted (no project) : {m['unrouted']}")
        print(f"  needs-triage          : {m['needs_triage']}")
        print(f"  oldest untriaged      : {m['oldest_triage_days']:.0f}d "
              f"{m['oldest_triage_id']}")
        print(f"  dormant (>={args.dormant_days}d)      : {m['dormant']}")

    if dormant:
        print(f"\nDORMANT ({'APPLY' if args.apply else 'report only, writes nothing'}):")
        for issue, days in dormant[:20]:
            line = f"  {issue['identifier']:<10} {days:6.0f}d  {issue['title'][:58]}"
            if args.apply:
                line += "  [" + flag_dormant(ln, issue, days, args.dormant_days) + "]"
            print(line)
        if len(dormant) > 20:
            print(f"  ... and {len(dormant) - 20} more")

    hits = breaches(m)
    if hits and not args.no_notify:
        line = (f"{SELF_MARKER} " + "; ".join(hits) +
                f". {m['dormant']} dormant >={args.dormant_days}d. "
                f"Drain is owner:sana -> kipi-dispatch.sh.")
        rc = notify(line)
        print(f"\nalerted (exit {rc}): {line}")
    elif hits:
        print(f"\nwould alert (suppressed by --no-notify): {'; '.join(hits)}")
    else:
        print("\nno threshold breached; staying quiet")

    if not complete:
        print("INCOMPLETE: the issue walk did not finish; numbers are partial.",
              file=sys.stderr)
        return EXIT_INCOMPLETE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv))
