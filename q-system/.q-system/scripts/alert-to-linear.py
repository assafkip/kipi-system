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
import shutil
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
    # PUNCTUATION IS RESIDUE, and it split tickets. Found by a live check, not by
    # the suite: with 2 files the separators survive as ", ", with 1 file they do
    # not, so two firings of ONE condition hashed differently and opened two
    # tickets. The suite missed it because every real #general fixture names
    # paths WITH slashes, and `\S*/\S*` is greedy enough to swallow the trailing
    # comma along with the token -- so the bug is invisible exactly where the
    # fixtures live and appears on any message naming a bare filename.
    # Word content decides the fingerprint; nothing else does.
    (re.compile(r"[^a-z0-9 ]+"), " "),
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


# The fleet convention for where the skeleton sits when nothing else can say.
# Same constant voice-dna-loader.py:63 already falls back to, deliberately: two
# scripts guessing the skeleton two different ways is a derivation split waiting
# to be found. LAST rung, never first -- see _registry_path.
CANONICAL_SKELETON = os.path.join(os.path.expanduser("~"), "projects",
                                  "kipi-system")


def _registry_path() -> str:
    """instance-registry.json. KIPI_INSTANCE_REGISTRY is the test seam.

    THE REGISTRY LIVES ONLY AT THE SKELETON ROOT, AND THIS SCRIPT SHIPS TO EVERY
    INSTANCE (ASK-839, PR #191 review round 4). The fleet updater copies
    `q-system/` and nothing at the repo root, so three-levels-up from an
    INSTANCE's scripts/ named a file that is not there. `_registry_rows()` then
    returned [] and rungs 2 (repo path), 3 (label vs registry name) and 5 (own
    checkout) were dead at once -- in the instances, which is where alerts are
    raised. Measured 2026-08-15 against the live registry: 24 of 25 instances
    ship this writer, 25 of 25 lack the registry, and 8 have a basename that is
    not their board alias (strategy/KTLYST_strategy, consulting/ASK Consulting,
    product/ktlyst, website/ktlyst-website, lawyer/ktlyst_lawyer,
    kipi-investigations/investigations, cole-gtm/cole-GTM, and one client
    engagement this public repo does not name).
    For those 8, rung 4 offers the bare directory name, no project carries it,
    and the alert files unset -- the defect this issue is about, still live in
    every instance after three rounds fixed it in the skeleton.

    A LADDER, and the first rung that EXISTS wins:

    1. The path beside this script. FIRST so a skeleton checkout always reads its
       own registry and can never be answered by a stale copy under the canonical
       home path -- including this repo's own worktrees and CI clones.
    2. The `kipi` CLI on PATH, resolved through its symlink. A derivation from
       how the CLI is actually installed, not a constant, so it is correct for a
       skeleton at any location. `shutil.which` reads PATH in-process: no
       subprocess on the never-raises alert path, the same rule
       `_common_repo_root()` follows.
    3. CANONICAL_SKELETON. This is what covers a launchd job, whose PATH carries
       no `/opt/homebrew` -- 3 of this repo's 5 plists set no PATH at all and
       inherit the minimal one, and those are alert producers.

    NO RUNG INVENTS A NAME. When every rung misses, this returns the in-place
    path so `_registry_rows()` reads nothing and the candidate list is whatever
    the caller's own label supplied. A ladder that ended in a guess would file
    every instance's alerts under one wrong project and look fixed
    (test_an_instance_with_no_registry_anywhere_invents_nothing).
    """
    env = os.environ.get("KIPI_INSTANCE_REGISTRY")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    in_place = os.path.join(here, "..", "..", "..", "instance-registry.json")
    candidates = [in_place]
    try:
        cli = shutil.which("kipi")
        if cli:
            candidates.append(os.path.join(
                os.path.dirname(os.path.realpath(cli)), "instance-registry.json"))
    except OSError:
        pass
    candidates.append(os.path.join(CANONICAL_SKELETON, "instance-registry.json"))
    for candidate in candidates:
        try:
            if os.path.isfile(candidate):
                return candidate
        except OSError:
            continue
    return in_place


def _registry_rows() -> list:
    """Every registry row, or [] when it cannot be read. Never raises.

    THE SKELETON IS A ROW TOO, and reading only `instances` dropped it (ASK-839,
    PR #191 review round 3). The skeleton is not an instance: it is the
    registry's own top-level `skeleton` key, and it is the checkout this script
    LIVES in and the fleet's single biggest alert producer. Both rungs that
    search these rows -- the repo path (2) and this script's own checkout (5) --
    were therefore dead for it, so an alert raised from kipi-system or any of its
    worktrees resolved to no project at all unless its bare `[label]` happened to
    name a board project.

    Measured on the live board 2026-08-15, 82 open alert tickets: 22 labelled `/`
    (a cwd with no repo, so nothing is exported and no label resolves -- rung 5
    is their only cover) and 18 labelled with a kipi-system worktree directory,
    whose --git-common-dir path is the skeleton -- rung 2. 40 of 82 had no live
    rung.

    `standalone` rows stay out on purpose rather than by oversight: they carry
    `has_skeleton: false`, so they ship no slack-notify.sh and cannot reach this
    code path at all. Adding them would lengthen the candidate list with names no
    alert can ever arrive under.
    """
    try:
        with open(_registry_path(), encoding="utf-8") as fh:
            reg = json.load(fh)
    except (OSError, ValueError):
        return []
    if not isinstance(reg, dict):
        entries = reg
        return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    entries = reg.get("instances", reg)
    rows = [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    skeleton = reg.get("skeleton")
    if isinstance(skeleton, dict) and skeleton.get("path"):
        # Tagged rather than positional so a caller can ask "which row is the
        # skeleton" without counting on it being first.
        rows = [dict(skeleton, is_skeleton=True)] + rows
    return rows


def _linear_project_of(entry: dict) -> str:
    """The name this row carries ON THE BOARD.

    THE ALIAS IS A FIELD, NOT A GUESS -- the same rule linear-worker.sh applies
    (ASK-840), and the same order: explicit `linear_project` first, `name`
    second. Deriving the board name from the directory is what produced that bug,
    and a smarter derivation would only move the day it breaks. Measured on the
    live board 2026-08-15: of the 81 unset alert tickets, only 33 carried a
    `[label]` prefix that is an exact project name.
    """
    return (entry.get("linear_project") or entry.get("name") or "").strip()


def project_candidates(message: str) -> list[str]:
    """Board-project names to try for this alert, best evidence FIRST.

    A LIST, not one answer, and that is the load-bearing part. The first cut
    returned a single name and the `[/]` case proved it wrong immediately: 22 of
    the 81 unset tickets carry the prefix `[/]` (a cwd of `/`), and another 16
    carry a worktree directory (`.wt-ask791`, `kipi-wt-ask729`, `cleanmain`).
    Each of those is a plausible-looking label that matches no project, so
    returning it as THE answer filed the ticket unset all over again while
    looking like a fix. Returning candidates lets an unresolvable label fall
    through to the fallback instead of consuming the decision.

    1. KIPI_ALERT_PROJECT -- an explicit statement by the caller.
    2. The repo PATH the alert was raised from, through the registry. This is the
       only rung that survives a worktree or a renamed directory, which is why
       slack-notify.sh resolves the path rather than passing its own label.
    3. The `[label]` prefix matched against a registry row's own name. Covers a
       caller that set KIPI_INSTANCE_NAME but no path.
    4. The `[label]` prefix taken at face value, resolved case-insensitively
       against the board later (`cole-gtm` is `cole-GTM` there).
    5. The checkout THIS SCRIPT runs from. 22 of the 81 unset tickets were raised
       from a cwd of `/` with no repo at all; the code that raised them still ran
       out of a registered checkout, so this is a derivation and not an invention.
    """
    out: list[str] = []

    def offer(name: str) -> None:
        name = (name or "").strip()
        if name and name not in out:
            out.append(name)

    offer(os.environ.get("KIPI_ALERT_PROJECT") or "")

    rows = _registry_rows()
    path = (os.environ.get("KIPI_ALERT_REPO_PATH") or "").strip()
    if path:
        try:
            want = os.path.realpath(path)
        except OSError:
            want = ""
        for row in rows:
            row_path = row.get("path")
            if not row_path:
                continue
            try:
                if want and os.path.realpath(row_path) == want:
                    offer(_linear_project_of(row))
            except OSError:
                continue

    match = re.match(r"^\[([^\]]+)\]", message.strip())
    label = (match.group(1).strip() if match else "")
    if label:
        for row in rows:
            if (row.get("name") or "").strip().lower() == label.lower():
                offer(_linear_project_of(row))
        offer(label)

    offer(os.environ.get("KIPI_ALERT_FALLBACK_PROJECT") or "")
    offer(_own_checkout_project(rows))
    return out


def _own_checkout_root() -> str:
    """The directory three levels up from this scripts/ dir. The test seam for
    the rung below, so a worktree layout can be exercised without one."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "..", "..")


def _common_repo_root(root: str) -> str:
    """`root`, or the repo it is a linked worktree OF.

    A worktree is never its own registry row, and the fleet's agents all run in
    one -- 18 of the 82 live alert tickets on 2026-08-15 were labelled with a
    worktree directory. Without this, rung 5 misses in exactly the checkouts that
    raise the most alerts.

    Read from the `.git` FILE rather than shelled out to `git rev-parse
    --git-common-dir`: this function is on the never-raises alert path, where a
    subprocess is a new way to lose the ticket, and the file is the same fact.
    slack-notify.sh does shell out, and that is not a second derivation of one
    value -- it answers a different question (the repo the CALLER was in) at a
    point where git is already required.
    """
    try:
        with open(os.path.join(root, ".git"), encoding="utf-8") as fh:
            head = fh.read(4096).strip()
    except (OSError, ValueError):
        return root
    if not head.startswith("gitdir:"):
        return root
    gitdir = head.split(":", 1)[1].strip()
    marker = os.path.join(".git", "worktrees")
    if marker not in gitdir:
        return root
    common = gitdir.split(marker)[0]
    return common or root


def _own_checkout_project(rows: list) -> str:
    """The board project of the checkout THIS SCRIPT lives in.

    The last rung, and a derivation rather than a guess: an alert raised from a
    cwd of `/` still came from code executing out of a registered checkout, and
    that checkout is the one honest thing left to say about its origin.

    It is also the ONLY rung covering the 22 `[/]` tickets, since no path is
    exported and no label resolves for them. KIPI_ALERT_FALLBACK_PROJECT is not
    that cover: nothing in this repo sets it (one reader, no writer), so a case
    that supplies it by hand is testing an invention.
    """
    try:
        root = os.path.realpath(_common_repo_root(_own_checkout_root()))
    except OSError:
        return ""
    for row in rows:
        row_path = row.get("path")
        if not row_path:
            continue
        try:
            if os.path.realpath(row_path) == root:
                return _linear_project_of(row)
        except OSError:
            continue
    return ""


# This file already keeps its own copies of TEAM_QUERY and LABELS_QUERY rather
# than reaching into linear-sync for them, and this follows that shape. Reaching
# for `ln.TEAM_PROJECTS_QUERY` was tried first and failed silently in exactly the
# way this path must never fail: the attribute read sits inside the never-raises
# try, so a stub without that constant returned "no project" instead of erroring,
# and the reproducer stayed red with the fix already in place.
PROJECTS_QUERY = """
query($teamId: String!) {
  team(id: $teamId) { projects(first: 250) { nodes { id name } } }
}
"""


def _project_id_for(ln, team_id: str, names: list) -> str | None:
    """First of `names` that resolves to a board project id, or None.

    Matched case-insensitively on purpose: registry names and board names differ
    only by case for real rows (`cole-gtm` vs `cole-GTM`), and a case-sensitive
    compare would file those tickets unset -- the exact defect being fixed.

    NEVER RAISES, for the same reason _owner_label_id does not: a ticket with no
    project is worth far more than a dropped alert. The alert path exists because
    a swallowed alert is the worst outcome available here.
    """
    if not names:
        return None
    try:
        team = (ln.graphql(PROJECTS_QUERY, {"teamId": team_id}) or {}).get("team") or {}
        nodes = ((team.get("projects") or {}).get("nodes")) or []
    except Exception:
        return None
    by_lower = {}
    for node in nodes:
        key = (node.get("name") or "").strip().lower()
        if key and key not in by_lower:
            by_lower[key] = node.get("id")
    for name in names:
        found = by_lower.get(name.strip().lower())
        if found:
            return found
    return None


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

        # A PROJECT IS ROUTING, NOT DECORATION (ASK-839). This payload carried
        # teamId + labelIds and nothing else, so every alert landed project-unset.
        # An unset project cannot route to any checkout: linear-worker.sh's
        # in_this_repo() is false for it in every repo at once, so no rotation, no
        # cursor and no clone reaches it. Measured on the live board 2026-08-15:
        # 81 open alert tickets, all unset, and the DoR drafter had already
        # promoted 19 of them into ready-shaped work that was therefore
        # permanently UNREACHABLE -- 43% of that whole bucket. The `[repo]` prefix
        # this file already writes into the TITLE was that same fact, sitting in a
        # field no query can filter on.
        project_id = _project_id_for(ln, team_id, project_candidates(message))
        if project_id:
            payload["projectId"] = project_id

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
