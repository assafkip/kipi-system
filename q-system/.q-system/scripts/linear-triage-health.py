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
  needs-triage    open issues carrying the mark an automated filer left AND
                  still holding no project. Depth of the queue nobody has routed
                  yet. Both halves are required: nothing removes the label when
                  an issue is routed, so counting the label alone counted routed
                  work as untriaged forever.
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
A dormant issue gets ONE COMMENT. Closing stays a judgment call.

The comment is the ONLY mutation this script makes -- it writes no label. This
line used to promise "a comment and a label" while no label mutation existed
anywhere in the file (Codex minor round 2, PR #204). The promise was corrected
rather than implemented, because the comment already carries the whole message
and a second write would double the ways a flag can half-land: nothing here
needs to query BY the flag, which is the only thing a label would buy.

The `dormant` LABEL is still READ, and that asymmetry is deliberate. A human who
disagrees with a flag can apply the label by hand to suppress future sweeps, so
the label is a human-owned override this script honours and never sets.

WHY IT EXCLUDES ITS OWN TICKETS

`slack-notify.sh` no longer sends to Slack -- it files a Linear ticket (founder-
directed 2026-08-10, "I dont want to see any of these"). So this script's own
alert becomes an issue on the board this script counts. Left alone, a backlog
monitor would inflate the backlog it reports and then report the inflation. The
exclusion is by title marker and is tested; see SELF_MARKER.

EXIT CODES -- this script never lies about failure
  0  measured cleanly, and any alert it owed was delivered
  1  usage error
  3  no Linear API key configured -- a setup state, not an error
  4  refused: running under pytest
  5  a threshold was breached and the alert did NOT send. The numbers are good;
     nobody was told. Printing the failure and exiting 0 made launchd record a
     silent 3am success, so the delivery result reaches the exit code.
  6  --apply ran and at least one dormancy write did not land. Same rule as 5,
     one layer down: the per-issue outcome decides the code, never the print.
  7  --apply refused because another --apply run holds the lock. Nothing was
     written and nothing was corrupted; re-run when the other finishes.
  9  the run could not complete its measurement (API failure mid-walk). Partial
     numbers are still printed, but the exit code says they are partial.

Precedence when several apply: 9 (the measurement is untrustworthy) then 5 then
6. A run reports its worst outcome, and stderr names every one of them.

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
import fcntl
import hashlib
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
EXIT_ALERT_FAILED = 5
EXIT_WRITE_FAILED = 6
EXIT_LOCKED = 7
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
query($id: String!, $after: String) {
  issue(id: $id) {
    comments(first: 100, after: $after) {
      nodes { body createdAt }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

# Runaway-loop stop for the marker walk, NOT a search bound. Exceeding it raises
# rather than answering "no marker" -- see already_flagged(). 50 pages is 5000
# comments on one issue; the board's busiest issue is nowhere near that, so this
# firing at all means something is wrong with the cursor, not with the issue.
COMMENT_PAGE_CAP = 50


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


def is_awaiting_triage(issue: dict) -> bool:
    """Carrying the filer's mark AND still unrouted.

    BOTH halves, and the second one is a fix, not a refinement. `alert-to-linear
    .py` sets `projectId` and the `needs-triage` label in the SAME issueCreate
    payload, and NOTHING anywhere removes that label once a human routes the
    issue. So a label-only count reported every routed alert ticket as still
    awaiting triage, forever -- a queue that can only grow, reported by the
    script whose whole job is noticing a queue that only grows (Codex major on
    PR #204, reproduced: one routed ticket, needs_triage=1).

    Routing is the event that ends the wait, so routing is what the measurement
    reads. The alternative was a label-removal writer, which needs a mutation,
    a second write path, and something to run it; a predicate needs neither and
    cannot drift out of sync with the board.
    """
    return TRIAGE_LABEL in label_names(issue) and is_unrouted(issue)


def measure(issues: list, now: datetime) -> dict:
    """The three numbers, over already-filtered open non-self issues.

    Pure: takes the list, returns the dict, touches no network. That is what
    lets the test drive it with fixtures and assert literal numbers rather than
    asserting a value it computed the same way the code did.
    """
    unrouted = [i for i in issues if is_unrouted(i)]
    triage = [i for i in issues if is_awaiting_triage(i)]

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

    Also skips anything still AWAITING TRIAGE (it is inflow that has not been
    decided yet, not work that stalled) and anything already labelled dormant
    (the flag is not re-applied).

    THE TRIAGE SKIP CALLS `is_awaiting_triage()` RATHER THAN RE-TESTING THE
    LABEL, and that is the fix for a hole this function opened by disagreeing
    with the count beside it. `is_awaiting_triage()` was narrowed to "label AND
    unrouted" because nothing removes the label when a human routes an issue.
    This skip kept the OLD, label-only definition, so a routed issue carrying a
    stale `needs-triage` label matched NEITHER predicate: not awaiting triage
    (it has a project), not dormancy-eligible (it has the label). It fell out of
    both readings of the same page and was invisible at any age. Reproduced on
    the PR head: a 100-day-old routed issue gave awaiting_triage=False and
    dormant_matches=0 (Codex major round 2, PR #204).

    Two predicates deciding one question is how they drift apart, so there is
    now one definition and this is a caller of it, not a copy.
    """
    out = []
    for issue in issues:
        if is_unrouted(issue):
            continue
        labels = label_names(issue)
        if is_awaiting_triage(issue) or DORMANT_LABEL in labels:
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


class FlagCheckFailed(Exception):
    """The already-flagged READ failed, so the flagged state is UNKNOWN.

    A distinct type, and not a bool, because the two safe answers to "is this
    already flagged" are yes and no -- and "I could not find out" is neither.
    Raising makes the unknown state impossible to ignore: a caller that forgets
    it gets a traceback, where a sentinel return value would be silently
    truthy-or-falsy and pick one of the two wrong answers by accident.
    """


def already_flagged(ln, issue_id: str, issue_updated_at: str | None = None) -> bool:
    """True when a CURRENT dormancy comment is already on the issue.

    CURRENT is the round-5 word. A marker is not a permanent silencer; it stops
    applying once the issue is touched after it was posted, which is exactly
    what `dormancy_comment()` promises the operator in writing. See
    `marker_superseded()` for that comparison and the measurement behind it.

    `issue_updated_at` defaults to None, and None means "no clock available, so
    the marker stands". That keeps every existing caller and any future one safe
    by default: forgetting the argument can only cause silence, never a
    duplicate permanent comment.

    Checked per issue rather than trusting the label alone: the label can be
    removed by a human who disagrees, and re-adding a comment they already read
    is the comment-stack failure this marker exists to prevent.

    RAISES `FlagCheckFailed` WHEN THE READ ITSELF FAILS, and does not answer
    True. Returning True on an API error meant a Linear timeout was reported to
    the operator as `already-flagged` -- a sentence about work someone else had
    already done, produced by a run that in fact learned nothing and wrote
    nothing. The run then looked complete. Reproduced on the PR head: a raising
    comments-read returned `already-flagged` with zero mutations attempted
    (Codex major round 2, PR #204).

    Erring toward silence is still right -- the caller must NOT write on an
    unknown -- but silence has to be reported as a failure rather than as a
    skip. A missed flag costs one issue staying quiet; a missed flag the run
    calls "already handled" costs the operator the ability to notice.

    WALKS EVERY COMMENT PAGE, AND THAT IS THE CORRECTNESS GUARANTEE FOR
    FLAG-ONCE. This read used to ask for `comments(first: 100)` and stop, so a
    marker sitting at comment 101 was invisible and the sweep wrote a SECOND
    permanent dormancy comment on an issue it had already flagged -- on one
    host, with no concurrency involved at all. Reproduced on the PR head: a
    marker at index 100 returned `flagged` and landed 1 duplicate mutation
    (Codex major round 4, PR #204).

    A bound would have rebuilt the same defect one page further out, so there
    is no bound: `False` is returned ONLY after Linear reports
    `hasNextPage: false`. `COMMENT_PAGE_CAP` and the stalled-cursor branch both
    RAISE instead of returning False, because a read that did not finish must
    never be reported as "no marker" -- the same lesson the FlagCheckFailed
    branch above already paid for, applied to a second way of not finishing.
    """
    latest = latest_marker_at(ln, issue_id)
    if latest is None:
        return False
    return not marker_superseded(latest, issue_updated_at)


def latest_marker_at(ln, issue_id: str) -> str | None:
    """The NEWEST dormancy marker's `createdAt`, or None if there is no marker.

    NEWEST, so every page is walked even after a marker is found. Returning on
    the first hit was correct while the only question was "is there a marker",
    and it becomes wrong the moment the answer is compared against a clock: an
    issue that was flagged, revived, went quiet and was flagged AGAIN carries
    two markers, and the older one is the one that reads as superseded. Judging
    by the first marker would re-flag an issue that already holds a current
    flag, which is the duplicate-comment failure this whole read exists to
    prevent, rebuilt from the other end.

    Raises `FlagCheckFailed` for every way of not finishing, for the reason
    already_flagged() documents: a read that did not complete must never be
    answered as "no marker".
    """
    after, newest = None, None
    for _ in range(COMMENT_PAGE_CAP):
        try:
            issue = (ln.graphql(ISSUE_COMMENTS_QUERY,
                                {"id": issue_id, "after": after})
                     or {}).get("issue") or {}
        except Exception as exc:
            raise FlagCheckFailed(str(exc)) from exc
        comments = issue.get("comments") or {}
        for node in (comments.get("nodes") or []):
            if DORMANT_MARKER not in (node.get("body") or ""):
                continue
            stamp = node.get("createdAt") or ""
            # A marker with no readable stamp is still a marker. It sorts as
            # the newest so it can never be judged superseded: silence beats a
            # duplicate permanent comment when the timestamp is unusable.
            if not stamp or _parse_iso(stamp) is None:
                return ""
            if newest is None or stamp > newest:
                newest = stamp
        page = comments.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            return newest
        cursor = page.get("endCursor")
        if not cursor or cursor == after:
            raise FlagCheckFailed(
                f"comment paging stalled on {issue_id} at cursor {cursor!r}")
        after = cursor
    raise FlagCheckFailed(
        f"more than {COMMENT_PAGE_CAP} comment pages on {issue_id}; "
        f"the already-flagged check did not complete")


def marker_superseded(marker_at: str, issue_updated_at: str | None) -> bool:
    """Did the issue get touched AFTER this marker was posted?

    This is the sentence `dormancy_comment()` prints to the operator -- "still
    wanted -> comment or update it and this clears" -- expressed as code. It was
    a promise nothing implemented: `already_flagged()` found the marker forever,
    so an issue that was flagged, revived by a real human, and then went quiet a
    SECOND time could never be flagged again. Reproduced on the PR head:
    second_sweep_outcome=already-flagged, new_comment_writes=0, on an issue
    whose updatedAt was three months newer than its marker (Codex blocker round
    5, PR #204). A monitor that goes permanently silent on exactly the issues it
    already identified once is worse than one that never ran.

    MEASURED, not assumed, because the answer decides whether this is safe:
    Linear DOES bump an issue's `updatedAt` when a comment is created. Sampled
    2026-08-17 across 14 ASK issues -- in 7 the issue's `updatedAt` equals the
    newest comment's own `updatedAt` to the exact millisecond, and Linear stamps
    a comment's `updatedAt` 15-200ms BEFORE its `createdAt`. So the bot's own
    dormancy comment lands with `issue.updatedAt` fractionally EARLIER than
    `marker.createdAt` and does not supersede itself.

    That ordering is a nicety, not the safety argument, and this does not lean
    on it. Even if a bump did land after the marker, `find_dormant()` still
    requires a FULL fresh threshold of silence measured from that same
    `updatedAt` before the issue is eligible again. The worst case is therefore
    one comment per threshold period of continuous silence -- a bounded drip
    that keeps saying something true -- never the comment stack the marker was
    introduced to prevent.

    An unreadable or absent `updatedAt` answers False: the marker stands, and
    the issue stays quiet. Erring toward silence is the standing posture here,
    because a comment is permanent and has no undo.
    """
    if not marker_at:
        return False
    marker = _parse_iso(marker_at)
    updated = _parse_iso(issue_updated_at or "")
    if marker is None or updated is None:
        return False
    return updated > marker


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
        f"<sub>`linear-triage-health.py`. A re-run finds this comment and "
        f"skips, until the issue is updated after it -- then the flag above "
        f"stops applying and a later silence can be flagged again.</sub>"
    )


def apply_lock_path() -> str:
    """One lock per MACHINE per Linear team. Still not the flag-once guarantee.

    Read this before reasoning about duplicate dormancy comments. The guarantee
    that an issue is flagged once lives in `already_flagged()`, which walks
    every comment page. This lock removes the window between that read and the
    write for every sweep that CAN share a filesystem.

    KEYED ON THE TEAM BEING SWEPT, NOT ON THE INSTALL PATH, and that is the
    round-5 fix. The old key was `sha256(HERE)`, the directory the running copy
    lives in, chosen so a tmpdir copy could not contend with the real
    installation. The cost of that convenience was the thing the lock is for:
    two checkouts of this repo on ONE machine -- a worktree and the installed
    copy, or `/opt/kipi-a` and `/opt/kipi-b` -- hashed to two different paths,
    never contended, and both left a permanent dormancy comment on the same
    issue. Reproduced on the PR head: outcomes=['flagged','flagged'],
    permanent_comment_writes=2 (Codex major round 5, PR #204). The install path
    is an accident of deployment; the Linear team is what two sweeps actually
    collide over, so that is what the key is made of.

    Lives in `~/.cache/kipi/`, the same place and for the same stated reason as
    `alert-to-linear.py`'s `_state_dir()`: OUTSIDE any repo checkout. A lock
    inside this tree would be rsynced as fleet cargo by `kipi update`, and would
    also be per-checkout again, which is the defect above wearing a new path.
    The system temp dir would work for the lock alone, but splitting kipi's
    machine-local state across two roots is how the next reader misses one.

    Isolation for the suite is now EXPLICIT, via `KIPI_TRIAGE_HEALTH_LOCK`,
    rather than a side effect of where a staged copy happened to sit. A test
    that forgets to pin it would contend with the real launchd job, so the
    suite's `_health_env()` sets it by default rather than per test.
    """
    override = os.environ.get("KIPI_TRIAGE_HEALTH_LOCK")
    if override:
        return override
    # The team key reaches a filesystem path, and it comes from an env var, so
    # it is constrained here rather than trusted. Anything outside the safe set
    # collapses to a hash of the raw value: still one stable path per team, with
    # no way to climb out of the directory.
    safe = "".join(c for c in TEAM_KEY if c.isalnum() or c in "-_")
    if not safe or safe != TEAM_KEY:
        safe = "team-" + hashlib.sha256(TEAM_KEY.encode("utf-8")).hexdigest()[:16]
    return os.path.join(os.path.expanduser("~"), ".cache", "kipi",
                        "linear-triage-health", f"{safe}.lock")


def acquire_apply_lock():
    """Take the exclusive --apply lock, or return None if another run holds it.

    BEST-EFFORT, AND DELIBERATELY NOT THE CORRECTNESS STORY. A future reader
    who finds a duplicate comment must not reach for a bigger lock. What makes
    flag-once hold across anything that does NOT share this filesystem is
    `already_flagged()` reading every comment page before the write.

    WHAT THIS LOCK NOW COVERS, AND WHAT IT STILL DOES NOT. Since the key moved
    from the install path to the team (see `apply_lock_path`), every sweep on
    ONE machine serialises no matter which checkout, worktree or install
    directory it runs from. That is the whole realistic population for this
    fleet: a launchd job plus a founder's manual run plus an agent worktree,
    all on the same laptop.

    Two different PHYSICAL HOSTS sweeping one Linear team still race, and that
    is an accepted, documented limitation rather than something this change
    quietly closed. No filesystem lock can span hosts. Closing it needs
    idempotency on Linear's side with no read/write gap, and `commentCreate`
    exposes no idempotency key, so there is nowhere to put the guarantee. If a
    duplicate ever shows up, check whether two hosts ran before reaching for a
    wider lock here; a bigger filesystem lock cannot fix a cross-host race and
    will only make the same window harder to see.

    What this DOES buy: the check and the write are not one operation --
    `already_flagged()` reads Linear, then `flag_dormant()` writes, and nothing
    links them -- so two overlapping runs of the SAME installation would both
    read "no marker" and both leave a permanent dormancy comment. Permanent is
    the operative word; there is no undo on a comment. Serialising same-host
    runs removes that window and saves the loser the whole sweep. Reproduced on
    the PR head: two overlapping --apply processes landed 2 comment mutations
    on one issue (Codex major round 2, PR #204).

    NON-BLOCKING ON PURPOSE. The loser refuses and says so rather than queueing:
    this runs daily against a 75-day threshold, so skipping one sweep costs
    nothing, while a launchd job silently waiting on a founder's interactive run
    is a job that looks hung.

    `fcntl.flock` and not a pid/token file, following `attempts-ledger.py`,
    which paid for that lesson: liveness-by-pid asks whether SOME process has
    that number, not whether it holds this lock, and pids wrap. The kernel
    releases this on process exit however the process dies, so there is no
    corpse to break. This lock file is never unlinked, so unlike the ledger's it
    also needs no inode re-check -- nothing can swap the path underneath it.

    HONEST BOUNDARY. Two different HOSTS still race inside the window between a
    completed read and the write, because the only authority that could close
    that is Linear and `commentCreate` has no idempotency key. Two installs on
    one host no longer do -- that was the round-5 finding and the team-keyed
    path above closes it. What the paginated read removed is the LARGE case: an
    unbounded, permanent blind spot that fired on any issue past 100 comments,
    on one host, with nothing concurrent about it. What is left needs two
    sweeps on two machines to overlap on the same issue on the same day. It
    gets closed at Linear or it stays documented.
    """
    path = apply_lock_path()
    try:
        # The cache root is created on demand: this is the first run's path on
        # any new machine, and a missing parent would otherwise surface as
        # "cannot open the --apply lock" and skip the sweep forever.
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        handle = open(path, "a")
    except OSError as exc:
        print(f"WARN: cannot open the --apply lock at {path} ({exc})",
              file=sys.stderr)
        return None
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def flag_dormant(ln, issue: dict, days: float, threshold: int) -> str:
    """Write one dormancy comment. Returns a short outcome for the report.

    THE MUTATION'S OWN `success` FIELD IS THE EVIDENCE, not the absence of an
    exception. `COMMENT_CREATE` selects `success` and this used to discard it,
    so a `commentCreate: {success: false}` reply came back through a clean call
    and was reported as "flagged" -- the run counted a write that never landed
    and the summary line said flagged=N (Codex major on PR #204, reproduced).
    A monitoring script that overstates its own writes is the failure it was
    built to catch, one layer up.

    `graphql()` already raises on Linear's `errors` array, so the two paths are
    different animals: the exception is a call that failed, this is a call that
    succeeded and declined.
    """
    try:
        if already_flagged(ln, issue["id"], issue.get("updatedAt")):
            return "already-flagged"
    except FlagCheckFailed as exc:
        # UNKNOWN is not "no", so nothing is written; and it is not
        # "already-flagged" either, so the run does not claim this issue was
        # handled. It lands in `failed=` and reaches the exit code.
        return f"FAILED (already-flagged check did not complete: {exc})"
    try:
        res = ln.graphql(COMMENT_CREATE, {"input": {
            "issueId": issue["id"],
            "body": dormancy_comment(days, threshold),
        }})
    except Exception as exc:
        return f"FAILED ({exc})"
    if not (((res or {}).get("commentCreate") or {}).get("success")):
        return "FAILED (commentCreate returned success=false)"
    return "flagged"


def select_to_flag(dormant: list, limit: int) -> list:
    """Which dormant issues this run may WRITE to. Never a display concern.

    Split out of main() so it is testable, because the defect it replaces was
    invisible exactly where it lived. The write and the print used to share one
    loop over `dormant[:20]`, so --apply flagged 20 and skipped the rest while
    printing "... and N more" -- a display sentence that read as a work report.
    Measured 2026-08-16: 193 dormant at a 7-day threshold, 173 silently skipped.

    limit 0 means no cap: every dormant issue is eligible. A caller that wants a
    bounded first run passes --limit N explicitly rather than inheriting a
    number that happened to be a print width.
    """
    if limit < 0:
        raise ValueError("limit must be >= 0")
    return dormant[:limit] if limit else list(dormant)


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
    ap.add_argument("--limit", type=int, default=0, metavar="N",
                    help="write at most N dormancy comments this run (0 = no cap). "
                         "Bounds the blast radius of a first live --apply.")
    args = ap.parse_args(argv[1:])

    if args.dormant_days < 1:
        print("--dormant-days must be >= 1", file=sys.stderr)
        return EXIT_USAGE

    if args.limit < 0:
        print("--limit must be >= 0", file=sys.stderr)
        return EXIT_USAGE

    # FIXTURE GUARD, the same chokepoint alert-to-linear.py uses. A suite written
    # tomorrow must not be able to comment on a real issue or file a real ticket,
    # so the refusal lives here rather than in each test.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        print("linear-triage-health: REFUSED under pytest.", file=sys.stderr)
        return EXIT_REFUSED_FIXTURE

    # Taken BEFORE the key lookup and the paginated walk: a run that cannot
    # write should not spend the API calls to work out what it would have
    # written. Report-only runs never take it -- they mutate nothing, so two of
    # them are harmless and serialising them would be a cost with no buyer.
    lock = None
    if args.apply:
        lock = acquire_apply_lock()
        if lock is None:
            print(f"REFUSED: another --apply run holds {apply_lock_path()}. "
                  f"Nothing was written; re-run when it finishes.",
                  file=sys.stderr)
            return EXIT_LOCKED
    try:
        return _run(args, lock is not None)
    finally:
        if lock is not None:
            lock.close()  # the kernel drops the flock with the last fd


def _run(args, holding_lock: bool) -> int:
    """The measurement and the writes, inside the lock when --apply is set."""
    # Fail closed. The lock is acquired by the caller, so this function could be
    # reached by a future caller that forgot it; the write path must refuse
    # rather than proceed unguarded.
    if args.apply and not holding_lock:
        raise RuntimeError("refusing to write dormancy comments without the "
                           "--apply lock")
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

    # Declared out here, not inside `if dormant:`, because the exit code below
    # reads it. A per-issue result that only the display loop can see is exactly
    # how a refused write reached the operator as a printed line and reached
    # launchd as success.
    outcomes = {}

    if dormant:
        # The WRITE loop is separate from the DISPLAY loop on purpose, and this
        # separation is the fix for a real defect, not a style preference. Both
        # used to be one loop over `dormant[:20]`, so --apply silently flagged
        # only the first 20 and skipped the rest while printing "... and N more"
        # -- a line about DISPLAY that read as a line about work done. Measured
        # 2026-08-16: 193 dormant at a 7-day threshold, so 173 would have been
        # silently skipped. A display bound must never decide what gets written.
        to_flag = select_to_flag(dormant, args.limit)
        if args.apply:
            for issue, days in to_flag:
                outcomes[issue["identifier"]] = flag_dormant(
                    ln, issue, days, args.dormant_days)

        if args.apply:
            capped = f", capped at {args.limit}" if args.limit else ""
            header = f"APPLY: wrote to {len(to_flag)} of {len(dormant)}{capped}"
        else:
            header = "report only, writes nothing"
        print(f"\nDORMANT ({header}):")

        for issue, days in dormant[:20]:
            line = f"  {issue['identifier']:<10} {days:6.0f}d  {issue['title'][:58]}"
            outcome = outcomes.get(issue["identifier"])
            if args.apply:
                # "not-attempted" is said out loud rather than left blank: a blank
                # next to a listed issue is what made the old cap invisible.
                line += "  [" + (outcome or "not-attempted (over --limit)") + "]"
            print(line)
        if len(dormant) > 20:
            print(f"  ... and {len(dormant) - 20} more (display cap, not a write cap)")

        if args.apply:
            wrote = sum(1 for v in outcomes.values() if v == "flagged")
            print(f"  flagged={wrote} already-flagged="
                  f"{sum(1 for v in outcomes.values() if v == 'already-flagged')} "
                  f"failed={sum(1 for v in outcomes.values() if v.startswith('FAILED'))} "
                  f"not-attempted={len(dormant) - len(to_flag)}")

    hits = breaches(m)
    alert_failed = False
    if hits and not args.no_notify:
        line = (f"{SELF_MARKER} " + "; ".join(hits) +
                f". {m['dormant']} dormant >={args.dormant_days}d. "
                f"Drain is owner:sana -> kipi-dispatch.sh.")
        rc = notify(line)
        # A NONZERO HERE IS A DELIVERY FAILURE AND MUST REACH THE EXIT CODE.
        # This printed `alerted (exit 1)` and then returned 0, so a 3am launchd
        # run recorded success for a breach nobody was told about -- the one
        # state this script exists to make impossible (Codex major, PR #204).
        # `notify()` never raises by design, which is exactly why its return
        # value is the only signal there is.
        alert_failed = rc != 0
        verb = "alert FAILED" if alert_failed else "alerted"
        print(f"\n{verb} (exit {rc}): {line}")
    elif hits:
        print(f"\nwould alert (suppressed by --no-notify): {'; '.join(hits)}")
    else:
        print("\nno threshold breached; staying quiet")

    # A REFUSED WRITE IS A FAILED RUN, and the per-issue result is the only
    # place that fact exists. `flag_dormant()` was fixed to stop reporting a
    # declined mutation as "flagged", and then main() threw that answer away
    # when it chose its exit code: a run where EVERY commentCreate came back
    # success=false still returned 0, so launchd recorded a clean sweep that
    # wrote nothing. Reproduced on the PR head: failed=3, RETURN_CODE 0 (Codex
    # major round 2, PR #204). The same shape as the alert bug beside it, one
    # layer down, which is why both now terminate in a code and not a print.
    failed_writes = sorted(k for k, v in outcomes.items() if v.startswith("FAILED"))

    # Precedence is worst-measurement-first: a partial walk means the dormancy
    # set itself is untrustworthy, so it outranks what happened to the writes.
    if not complete:
        print("INCOMPLETE: the issue walk did not finish; numbers are partial.",
              file=sys.stderr)
        return EXIT_INCOMPLETE
    if alert_failed:
        print("ALERT FAILED: a threshold was breached and the alert did not send.",
              file=sys.stderr)
        return EXIT_ALERT_FAILED
    if failed_writes:
        print(f"WRITE FAILED: {len(failed_writes)} of {len(outcomes)} dormancy "
              f"write(s) did not land: {', '.join(failed_writes)}", file=sys.stderr)
        return EXIT_WRITE_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv))
