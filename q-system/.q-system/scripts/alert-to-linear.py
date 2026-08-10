#!/usr/bin/env python3
"""File a fleet alert as a Linear issue for Sana. The founder is never paged.

FOUNDER-DIRECTED 2026-08-10, verbatim: "I dont want to see any of these. Any of
the ones that need attention should go to Sana - not me." and then, on being
offered one carve-out for the fable-escalation cap: "the fable escalation should
be gone. I gave it clear instructions."

So there is no founder path here, and no flag that re-opens one. Every alert in
the fleet becomes a Linear ticket on team ASK labelled `owner:sana`, which is the
queue `kipi-dispatch.sh` already drains into agent sessions. That loop exists and
runs; this is a new producer for it, not a new consumer to build.

THE SCAR THIS REPLACES. #general on 2026-08-10 carried 100 messages between 09:35
and 14:06 PDT. 51 were auto-commit naming a file set that changed every turn; 35
were one cole-gtm carve-out notice re-announcing a CONFIG STATE once per run, in
duplicate pairs. The 6 that mattered -- four security reverts of unsanctioned
.claude/ changes, a Notion job dead since 13:00 -- were unreadable underneath.
A channel that reports an unchanged condition on every turn stops being read, and
then the one real alert arrives somewhere nobody looks.

DEDUP IS THE WHOLE POINT. Moving a flood from Slack to Linear would be the same
defect with a new surface, except worse: a Slack message scrolls away and a Linear
ticket has to be closed by hand. So a repeating alert is ONE issue with a comment
counter, keyed on a fingerprint that deliberately ignores the volatile parts (how
many files, which files, what time). "auto-commit left 3 file(s) ... a.py, b.py"
and "auto-commit left 9 file(s) ... c.py" are the same alert and get one ticket.

EXIT CONTRACT, mirroring slack-notify.sh so existing callers are unchanged:
  0  filed (created a ticket, or recorded a repeat on the open one)
  1  attempted and FAILED (reason on stderr, message text preserved there)
  3  no Linear API key configured -- a setup state, not an error
  4  refused: running under pytest (see the fixture guard)

Never raises. This is called from Stop hooks and launchd jobs; an alerting path
that can crash its caller is worse than the alert being lost.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import time

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NO_KEY = 3
EXIT_REFUSED_FIXTURE = 4

TEAM_KEY = os.environ.get("KIPI_LINEAR_TEAM", "ASK")
OWNER_LABEL = "owner:sana"

# A repeat inside this window updates the counter silently. Past it, the ticket
# gets a comment so a condition that is STILL true a day later is visible as
# still-true rather than as one stale ticket nobody has touched.
REPEAT_COMMENT_AFTER_HOURS = 12


def _state_dir() -> str:
    """Fingerprint -> ticket map, OUTSIDE any repo.

    why (carried from auto-commit.py's ASK-603 fix): state written inside a
    project becomes an uncommitted file, which is a thing the fleet alerts ON,
    which would rewrite the state, which alerts again. The cache would be its
    own alarm.
    """
    return os.path.join(
        os.path.expanduser("~"), ".cache", "kipi", "alert-to-linear")


# Volatile spans, stripped before fingerprinting. Order matters: paths before
# bare numbers, or the digits inside a path are gone before the path matches.
#
# THE PATH RULE IS "CONTAINS A SLASH", not "starts with one. First attempt used
# `(?:/[\w.@+-]+){2,}` and the suite caught it immediately: every real
# auto-commit line names RELATIVE paths (`.prd-os/issues/lane-h.md`), so the
# anchored pattern matched nothing, the trailing filename was stripped by the
# extension rule, and the surviving `.prd-os/issues/` residue differed per
# message. Four identical alerts produced four fingerprints -- the exact flood
# this file exists to stop, reproduced inside the fix.
_VOLATILE = [
    (re.compile(r"\[\d{4}-\d{2}-\d{2}[^\]]*\]"), " "),      # trailing timestamps
    (re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.+Z-]+"), " "),     # iso stamps
    (re.compile(r"\d{4}-\d{2}-\d{2}"), " "),                # bare dates
    (re.compile(r"\S*/\S*"), " "),                          # any path-shaped token
    (re.compile(r"[\w.-]+\.(?:py|json|md|sh|yaml|yml|jsonl|html|txt|lock)\b"), " "),
    (re.compile(r"\(\+\d+ more\)"), " "),
    (re.compile(r"\b[0-9a-f]{7,40}\b"), " "),               # sha / run ids
    (re.compile(r"\d+"), " "),                              # every remaining count
    (re.compile(r"\s+"), " "),
]


def fingerprint(message: str) -> str:
    """Stable id for 'the same alert, said again'.

    Everything that varies between two firings of one condition is removed, so
    the dedup key is the SHAPE of the alert. This is what turns 51 auto-commit
    messages into one ticket. Tested directly: test_alert_to_linear.py pins the
    real 2026-08-10 #general strings as same-fingerprint pairs.
    """
    norm = message.strip().lower()
    for pattern, repl in _VOLATILE:
        norm = pattern.sub(repl, norm)
    return hashlib.sha256(norm.strip().encode("utf-8")).hexdigest()[:16]


def title_for(message: str) -> str:
    """A ticket title a human can scan in a list. One line, bounded."""
    line = " ".join(message.strip().split())
    return line[:110] + ("..." if len(line) > 110 else "")


def _load_linear():
    """Import linear-sync.py for its auth + graphql. Hyphen forces importlib.

    SINGLE WRITER for how this fleet talks to Linear. Reimplementing the key
    lookup or the errors-array handling here would be a second place to fix when
    Linear changes, and linear-sync.py's graphql() already knows that Linear
    returns HTTP 200 with an `errors` key on application failures.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "linear-sync.py")
    spec = importlib.util.spec_from_file_location("kipi_linear_sync", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TEAM_QUERY = """
query($key: String!) {
  teams(filter: { key: { eq: $key } }) { nodes { id key } }
}
"""

LABELS_QUERY = """
query($teamId: String!) {
  team(id: $teamId) { labels(first: 250) { nodes { id name } } }
}
"""

LABEL_CREATE = """
mutation($input: IssueLabelCreateInput!) {
  issueLabelCreate(input: $input) { success issueLabel { id name } }
}
"""

ISSUE_CREATE = """
mutation($input: IssueCreateInput!) {
  issueCreate(input: $input) { success issue { id identifier url } }
}
"""

ISSUE_STATE_QUERY = """
query($id: String!) {
  issue(id: $id) { id identifier url state { type } }
}
"""

COMMENT_CREATE = """
mutation($input: CommentCreateInput!) {
  commentCreate(input: $input) { success }
}
"""


def _read_state(fp: str) -> dict:
    try:
        with open(os.path.join(_state_dir(), f"{fp}.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _write_state(fp: str, data: dict) -> None:
    """Remember which ticket owns this fingerprint. Never raises."""
    try:
        os.makedirs(_state_dir(), exist_ok=True)
        with open(os.path.join(_state_dir(), f"{fp}.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(data, fh)
    except OSError:
        pass


def _owner_label_id(ln, team_id: str) -> str | None:
    """The owner:sana label id, created once if the team lacks it.

    A missing label must never cost the ticket: an alert filed with no label is
    still an alert Sana can find, whereas raising here would drop it entirely.
    """
    try:
        team = (ln.graphql(LABELS_QUERY, {"teamId": team_id}) or {}).get("team") or {}
        for node in ((team.get("labels") or {}).get("nodes") or []):
            if (node.get("name") or "").lower() == OWNER_LABEL:
                return node.get("id")
        made = ln.graphql(LABEL_CREATE,
                          {"input": {"name": OWNER_LABEL, "teamId": team_id}})
        return (((made or {}).get("issueLabelCreate") or {})
                .get("issueLabel") or {}).get("id")
    except Exception:
        return None


def file_alert(message: str, now: float | None = None) -> tuple[int, str]:
    """(exit_code, human line). The whole job, in one place."""
    now = time.time() if now is None else now
    fp = fingerprint(message)
    ln = _load_linear()

    try:
        ln.linear_api_key()
    except Exception as exc:
        return EXIT_NO_KEY, f"no Linear key configured ({exc}); NOT filed: {message}"

    prior = _read_state(fp)

    # A ticket already exists for this shape. Is it still open?
    if prior.get("issue_id"):
        try:
            issue = (ln.graphql(ISSUE_STATE_QUERY,
                                {"id": prior["issue_id"]}) or {}).get("issue") or {}
        except Exception:
            issue = {}
        state_type = ((issue.get("state") or {}).get("type") or "").lower()
        still_open = bool(issue.get("id")) and state_type not in ("completed", "canceled")
        if still_open:
            count = int(prior.get("count", 1)) + 1
            last_comment = float(prior.get("last_comment_at", prior.get("first_at", 0)))
            said = False
            if (now - last_comment) >= REPEAT_COMMENT_AFTER_HOURS * 3600:
                try:
                    ln.graphql(COMMENT_CREATE, {"input": {
                        "issueId": prior["issue_id"],
                        "body": (f"Still firing. {count} occurrence(s) since this "
                                 f"ticket opened.\n\nMost recent:\n```\n{message}\n```"),
                    }})
                    said = True
                except Exception:
                    pass
            _write_state(fp, {**prior, "count": count,
                              "last_at": now,
                              "last_comment_at": now if said else last_comment})
            return EXIT_OK, (f"repeat #{count} on {prior.get('identifier', '?')}"
                             f"{' (commented)' if said else ' (counted)'}")
        # Closed or gone: Sana dealt with it and it came back. That is a NEW
        # ticket on purpose -- reopening a closed one hides the recurrence,
        # which is the signal worth having.

    try:
        teams = (ln.graphql(TEAM_QUERY, {"key": TEAM_KEY}) or {}).get("teams") or {}
        nodes = teams.get("nodes") or []
        if not nodes:
            return EXIT_FAILED, f"no Linear team {TEAM_KEY!r}; NOT filed: {message}"
        team_id = nodes[0]["id"]

        payload = {
            "title": title_for(message),
            "teamId": team_id,
            "description": (
                f"Filed automatically by the fleet alert path. The founder is not "
                f"paged for these.\n\n```\n{message}\n```\n\n"
                f"Repeats of this same alert will be counted on THIS ticket rather "
                f"than opening new ones. If it recurs after you close it, that is a "
                f"fresh ticket and a real recurrence.\n\n"
                f"<!-- kipi-alert-fingerprint: {fp} -->"
            ),
        }
        label_id = _owner_label_id(ln, team_id)
        if label_id:
            payload["labelIds"] = [label_id]

        data = ln.graphql(ISSUE_CREATE, {"input": payload})
        issue = ((data or {}).get("issueCreate") or {}).get("issue") or {}
        if not issue.get("id"):
            return EXIT_FAILED, f"issueCreate returned no issue; NOT filed: {message}"
    except Exception as exc:
        return EXIT_FAILED, f"Linear create failed ({exc}); NOT filed: {message}"

    _write_state(fp, {"issue_id": issue["id"],
                      "identifier": issue.get("identifier"),
                      "count": 1, "first_at": now, "last_at": now,
                      "last_comment_at": now})
    return EXIT_OK, f"filed {issue.get('identifier')} {issue.get('url', '')}".strip()


def main(argv: list[str]) -> int:
    message = (argv[1] if len(argv) > 1 else "").strip()
    if not message:
        return EXIT_OK

    # CAPTURE HATCH -- the isolation seam bash suites need, and the reason this
    # block exists at all.
    #
    # SCAR, 2026-08-10, ten minutes old when this was written. The bash guard
    # suite isolates itself by pointing KIPI_SLACK_WEBHOOK at a local capture
    # server, then asserts on what arrived. The moment the destination became
    # Linear that stub addressed nothing, so the suite's deliberate "a
    # production run still alerts" cases filed a REAL ticket (ASK-635, canceled).
    # Switching a chokepoint's destination silently invalidates every test stub
    # aimed at the old one, and the tests keep passing their own assertions right
    # up until they write to production.
    #
    # So the capture seam is part of the destination, not part of the caller: any
    # runner that can set an env var can redirect the write. Nothing is dropped
    # -- the message is appended to the file -- and it announces itself on
    # stderr, so this can never be mistaken for a delivered alert in a job log.
    capture = os.environ.get("KIPI_ALERT_CAPTURE")
    if capture:
        try:
            with open(capture, "a", encoding="utf-8") as fh:
                fh.write(message + "\n")
        except OSError as exc:
            print(f"alert-to-linear: capture to {capture} failed ({exc}); "
                  f"NOT filed: {message}", file=sys.stderr)
            return EXIT_FAILED
        print(f"alert-to-linear: CAPTURED to {capture} (not filed to Linear): "
              f"{message}", file=sys.stderr)
        return EXIT_OK

    # FIXTURE GUARD (the same chokepoint fable-escalate.py uses for model calls).
    # SCAR 2026-08-01: three tests were found paging the founder's real Slack,
    # and while the fix sat unmerged an agent ran one from a worktree without it
    # and paged again. Per-test stubbing only protects tests someone remembered
    # to fix. A test written tomorrow must not be able to open a real ticket, so
    # the refusal lives here rather than in each suite.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        print(f"alert-to-linear: REFUSED under pytest. NOT filed: {message}",
              file=sys.stderr)
        return EXIT_REFUSED_FIXTURE

    try:
        code, line = file_alert(message)
    except Exception as exc:                       # never crash a Stop hook
        print(f"alert-to-linear: unexpected {exc!r}; NOT filed: {message}",
              file=sys.stderr)
        return EXIT_FAILED

    # A failed alert stays readable in the job log. A silently swallowed alert is
    # the exact failure mode this whole path exists to prevent.
    print(f"alert-to-linear: {line}", file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
