#!/usr/bin/env python3
"""Idempotent planner for Linear project/issue creation across the kipi fleet.

Pairs with q-system/output/plans/linear-sdlc-standard-2026-07-26.md (Part 2) and
its reproducer q-system/.q-system/scripts/test/test-linear-sync-idempotent.sh.

PLANNER *AND* CREATOR (ASK-113, updated 2026-07-26). This file used to say it
could not reach Linear: there was no API key, so Linear was reachable only
through the MCP server, which the agent has and a subprocess does not. That was
true of the credentials, never of the design -- verified while reading two other
Linear agent orchestrators, both of which simply use an API key. A key now lives
at ~/.config/kipi/linear-api-key (0600), so the whole flow runs headless:

    remote -> plan -> create --apply   (and `record` for the MCP path)

The MCP path still works and is still correct when an agent is already in
session. `create` is what makes the rollout a script instead of one repo per
agent session.

The deterministic half is still the part that decides WHAT to create and the part
that remembers what was created; `create` adds the network call under the same
two guards.

WHY THE DEDUP KEY IS LOAD-BEARING: mcp__linear__*delete* and archive are both
blocked by ~/.claude/hooks/destructive-op-deny.sh, and an agent cannot set
ALLOW_DESTRUCTIVE=1 for itself. A duplicate issue is permanent. So there are two
independent guards, and the remote one is the truth:

    1. ledger guard  - fast, local, q-system/output/linear-ledger.jsonl
    2. remote guard  - authoritative, parses <!-- kipi-key: ... --> markers out of
                       the descriptions of issues that already exist in Linear

The ledger is a cache. It is *.jsonl, which lefthook's blocked-paths rule refuses
to commit, so it cannot travel with the repo. That is exactly why the remote guard
exists: a fresh clone, a wiped ledger, or a parallel session must not produce
duplicates.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

QROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Exit codes are distinct so a test can tell a refusal from a crash.
EXIT_OK = 0
EXIT_USAGE = 1
EXIT_COLLISION = 3

MARKER_RE = re.compile(r"<!--\s*kipi-key:\s*([^\s>]+)\s*-->")
PROJECT_SUFFIX = "__project__"


def ledger_path() -> str:
    """Single source for the ledger location. KIPI_LINEAR_LEDGER exists so the
    test suite never opens the live file (fable-discipline test isolation)."""
    return os.environ.get(
        "KIPI_LINEAR_LEDGER", os.path.join(QROOT, "output", "linear-ledger.jsonl")
    )


def slugify(text: str) -> str:
    """Lowercase, collapse every non-alphanumeric run to a single hyphen, trim.

    A '/' inside a capability name becomes '-', so a name can never forge the
    repo/capability separator and collide with a different repo's key.
    """
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def make_key(repo: str, capability: str) -> str:
    return f"{slugify(repo)}/{slugify(capability)}"


def project_key(repo: str) -> str:
    return f"{slugify(repo)}/{PROJECT_SUFFIX}"


# --- ledger: one reader, one writer ------------------------------------------


def read_ledger() -> dict:
    """Return {key: record}. A malformed line is skipped, not fatal: the remote
    guard is the authority, so a corrupt cache degrades to 'slower', not 'wrong'."""
    path = ledger_path()
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and rec.get("key"):
                out[rec["key"]] = rec
    return out


def append_ledger(records: list) -> int:
    """The ONLY writer. Append-only by construction: opened 'a', never 're-written'.
    Re-appending a known key is harmless (read_ledger dedups by last-wins), which
    is why `record` is safe to re-run after a partial failure."""
    if not records:
        return 0
    path = ledger_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "a", encoding="utf-8") as fh:
        for rec in records:
            rec.setdefault("created_at", now)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return len(records)


# --- planning -----------------------------------------------------------------


def parse_remote(remote: dict) -> tuple:
    """Pull kipi-key markers out of the remote snapshot.

    Only a marker counts. Matching on title was considered and rejected: a title
    match would SKIP a create that is genuinely needed the moment a human edits a
    title, silently losing work. A false dedup is worse than a missed one, because
    the missed one is visible and the false one is not.
    """
    found = {}
    for issue in remote.get("issues") or []:
        m = MARKER_RE.search(issue.get("description") or "")
        if not m:
            continue
        found[m.group(1)] = {
            "linear_id": issue.get("id"),
            "identifier": issue.get("identifier"),
        }
    proj = remote.get("project")
    return found, proj


def build_issue(repo: str, cap: dict, index: int) -> dict:
    key = make_key(repo, cap["name"])
    cap_id = f"CAP-{index + 1:02d}"
    summary = (cap.get("summary") or "").strip()
    title = f"{cap_id} {cap['name']}"
    if summary:
        title = f"{title}: {summary}"
    if len(title) > 120:
        title = title[:117].rstrip() + "..."

    lines = [
        f"<!-- kipi-key: {key} -->",
        "",
        summary or "_No summary in the capability map._",
        "",
        "| Field | Value |",
        "| -- | -- |",
        f"| Repo | `{repo}` |",
        f"| Layer | {cap.get('layer', 'unclassified')} |",
        f"| Status claimed | {cap.get('status', 'UNKNOWN')} |",
        f"| Entry point | {cap.get('entry') or '_not recorded_'} |",
        f"| Trigger | {cap.get('trigger') or '_not recorded_'} |",
        f"| Depends on | {cap.get('depends') or '_nothing recorded_'} |",
        f"| Feeds | {cap.get('feeds') or '_nothing recorded_'} |",
        "",
        "## Evidence",
        "",
        cap.get("evidence") or "_No command proves this yet. That is the gap._",
        "",
        "## Definition of Done",
        "",
        "Per the fleet SDLC standard: the command and its real output pasted here,",
        "the reproducer green after being observed red, wiring proven end to end,",
        "and a commit naming this issue id.",
    ]
    return {
        "key": key,
        "title": title,
        "description": "\n".join(lines),
        "labels": _labels_for(cap),
        "state": _state_for(cap),
        "capability": cap.get("name"),
    }


def build_rollup(repo: str, rolled: list) -> dict:
    """One issue per repo carrying every UNWIRED engine, with the full list.

    Nothing is dropped: each script is named in the table with its line count and
    why it was flagged, so the rollup is a work-list rather than a summary that
    loses the detail.
    """
    key = f"{slugify(repo)}/unwired-engine-audit"
    rows = ["| Script | Lines | Why flagged |", "| -- | -- | -- |"]
    for cap in sorted(rolled, key=lambda c: c.get("entry") or ""):
        ev = cap.get("evidence") or ""
        lines = re.search(r"(\d+) lines", ev)
        rows.append(
            f"| `{cap.get('entry')}` | {lines.group(1) if lines else '?'} | "
            f"{'no test, no wiring reference' if 'NO test and NO wiring' in ev else ev[:60]} |"
        )
    # Pluralization is not cosmetic here: 10 of the 15 repos with work roll up to
    # exactly ONE engine, and a Linear issue cannot be deleted, so "found 1 Python
    # engines / 1 groomings for one call" would be permanent in most of the fleet.
    # Caught on the first live create (ASK-118), spillover sp-77c8f0e9.
    count = len(rolled)
    one = count == 1
    engines = "engine" if one else "engines"
    they_are = "it is" if one else "they are"
    the_scripts = "the script below is" if one else "every script below is"

    body = [
        f"<!-- kipi-key: {key} -->",
        "",
        f"`capability-map-gen.py` found **{count} Python {engines}** in `{repo}` "
        "with neither a paired test nor any reference on a wiring surface "
        "(settings.json, lefthook.yml, a hook, a command, the kipi CLI, or another script).",
        "",
        f"That does not prove {'it is' if one else 'they are'} dead. It proves nothing "
        f"in the repo *says* {they_are} alive, which is the same position a future "
        "reader is in.",
        "",
        "## The list",
        "",
        *rows,
        "",
        "## Definition of Ready",
        "",
        f"- **Outcome:** {the_scripts} either wired (and the wiring is visible), "
        "tested, or deleted. Nothing is left in the ambiguous middle.",
        "- **Check:** re-run the generator and confirm the UNWIRED count for this repo "
        "drops to 0:",
        "",
        "```bash",
        "python3 q-system/.q-system/scripts/capability-map-gen.py \\",
        f"  --root <repo> --repo {repo} --out /tmp/{slugify(repo)}.json",
        "```",
        "",
        "- **Not doing:** engines that ARE referenced but lack a test. That is a "
        "test-coverage issue, not a liveness one.",
    ]

    # The "why one issue and not N" rationale only means anything when N > 1.
    # At N=1 it read "Why this is one issue and not 1", which is nonsense.
    if not one:
        body += [
            "",
            f"## Why this is one issue and not {count}",
            "",
            "Wiring-or-deleting a repo's dead scripts is a single decision made once "
            "with the whole list in view. Split across "
            f"{count} issues it becomes {count} groomings for one call, and Linear "
            "issues cannot be deleted here, so each one is permanent.",
        ]

    body += ["", "Filed under ASK-113."]

    return {
        "key": key,
        "title": f"Audit {count} unwired {engines} in {repo}",
        "description": "\n".join(body),
        "labels": ["kind:capability", "unwired", "needs-evidence"],
        "state": "Backlog",
        "capability": "unwired engine audit",
    }


def _labels_for(cap: dict) -> list:
    """Only labels that actually exist in the workspace.

    Linear refuses an unresolved label name outright (it will not auto-create),
    and every label is another permanent object. `layer:*` was dropped on purpose:
    the layer is already in the issue's own field table AND in the capability map,
    which is what the overlap join reads. Seven more labels bought nothing.
    """
    labels = ["kind:capability"]
    status = str(cap.get("status") or "").upper()
    if status == "UNWIRED":
        labels.append("unwired")
    if status in ("NEEDS_WORK", "UNWIRED", "BROKEN"):
        labels.append("needs-evidence")
    return labels


def _state_for(cap: dict) -> str:
    """Map a claimed capability status onto a Linear workflow state.

    LIVE lands in Done ONLY when the map carries evidence. A LIVE claim with no
    command behind it is exactly the thing the triage pass is supposed to catch,
    so it lands in Todo with a needs-evidence label instead of being rubber-stamped.
    """
    status = str(cap.get("status") or "").upper()
    has_evidence = bool((cap.get("evidence") or "").strip())
    if status in ("LIVE", "DONE", "SHIPPED"):
        return "Done" if has_evidence else "Todo"
    if status in ("NEEDS_WORK", "DEGRADED", "PARTIAL", "BROKEN"):
        return "Todo"
    if status in ("PLANNED", "IDEA", "PROPOSED"):
        return "Backlog"
    return "Backlog"


# ---------------------------------------------------------------------------
# Direct creation over the Linear API
#
# Why this exists: queue-and-drain was built because a shell had no way to reach
# Linear, so capture was local and an agent session drained it. That constraint
# was a missing credential, not a law -- verified 2026-07-26 while reading two
# other Linear agent orchestrators, both of which simply use an API key. With a
# key, `create` closes the loop and the drain round trip is optional.
#
# The permanence rule still dominates every design choice below: Linear delete
# and archive are blocked by the destructive-op hook and an agent cannot
# self-authorize them, so a duplicate is FOREVER. Hence: refetch the remote
# guard immediately before writing, append the ledger after EVERY single create
# rather than at the end, and require --apply.

LINEAR_API_URL = os.environ.get("KIPI_LINEAR_API_URL", "https://api.linear.app/graphql")


class LinearAPIError(Exception):
    """A GraphQL call failed. Never swallowed: a failed create must stop the run."""


def linear_api_key() -> str:
    """The key, from env or the gitignored secret file.

    Same convention as the Slack webhook and cockpit-token: a 0600 file under
    ~/.config/kipi/, never in the repo, never in a committed config.
    """
    env = os.environ.get("KIPI_LINEAR_API_KEY")
    if env:
        return env.strip()
    path = os.path.expanduser("~/.config/kipi/linear-api-key")
    if not os.path.isfile(path):
        raise LinearAPIError(
            f"no Linear API key. Create one at https://linear.app/settings/api "
            f"then:\n  umask 077 && printf '%%s' '<key>' > {path}\n"
            "or export KIPI_LINEAR_API_KEY."
        )
    with open(path, encoding="utf-8") as fh:
        key = fh.read().strip()
    if not key:
        raise LinearAPIError(f"{path} is empty")
    return key


def graphql(query: str, variables: dict) -> dict:
    """One GraphQL call. Raises on transport OR on a GraphQL `errors` array.

    Linear returns HTTP 200 with an `errors` key for application-level failures,
    so checking the status code alone would read a failed create as a success and
    then append a ledger record for an object that does not exist.
    """
    import urllib.error
    import urllib.request

    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        LINEAR_API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": linear_api_key(),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise LinearAPIError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LinearAPIError(f"network: {exc.reason}") from exc
    if payload.get("errors"):
        raise LinearAPIError(json.dumps(payload["errors"])[:500])
    return payload.get("data") or {}


TEAM_QUERY = """
query($key: String!) {
  teams(filter: { key: { eq: $key } }) { nodes { id key name } }
}
"""

PROJECT_ISSUES_QUERY = """
query($projectId: ID!, $after: String) {
  issues(filter: { project: { id: { eq: $projectId } } }, first: 100, after: $after) {
    nodes { id identifier description state { id name type } team { id } }
    pageInfo { hasNextPage endCursor }
  }
}
"""

# One issue by its Linear id, INDEPENDENT of what project it currently sits in.
# A project-scoped listing is the wrong sole lookup for a standing rollup issue:
# moving it to another project is ordinary triage, and after the move the owning
# job could no longer find it, so it stopped updating it and reported an
# all-clear instead (PR #11 fourth review, finding 2). The ledger already holds
# the linear_id; this is how a caller uses it.
ISSUE_BY_ID_QUERY = """
query($id: String!) {
  issue(id: $id) { id identifier description state { id name type } team { id } }
}
"""

TEAM_PROJECTS_QUERY = """
query($teamId: String!) {
  team(id: $teamId) { projects(first: 250) { nodes { id name description } } }
}
"""

PROJECT_CREATE = """
mutation($input: ProjectCreateInput!) {
  projectCreate(input: $input) { success project { id name } }
}
"""

ISSUE_CREATE = """
mutation($input: IssueCreateInput!) {
  issueCreate(input: $input) { success issue { id identifier } }
}
"""

# Rewrites an EXISTING issue rather than creating a second one. Needed by any
# caller whose issue is a standing rollup (fleet-health's cron/spillover
# findings): the dedup key is stable on purpose, so without an update the body
# freezes at the truth of the day it was filed and every later occurrence is
# swallowed by the "already exists" guard. Never used to change a kipi-key
# marker -- that would fork the identity the whole ledger is built on.
ISSUE_UPDATE = """
mutation($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) { success issue { id identifier } }
}
"""

# Removes ONE label, server-side. The alternative -- reading labelIds and
# sending the survivors back through issueUpdate -- is a full-set overwrite that
# drops whatever another actor added between the read and the write. See
# cmd_unblock for why that window is routine on this board rather than rare.
ISSUE_REMOVE_LABEL = """
mutation($id: String!, $labelId: String!) {
  issueRemoveLabel(id: $id, labelId: $labelId) { success }
}
"""

TEAM_STATES_QUERY = """
query($teamId: String!) {
  team(id: $teamId) { states(first: 100) { nodes { id name type position } } }
}
"""

# Linear WorkflowState.type values that mean "this issue is off the board".
CLOSED_STATE_TYPES = ("completed", "canceled")

# Where a reopen lands, best first. `unstarted` is the team's Todo column: the
# issue is back on the board without falsely claiming someone is on it.
_REOPEN_TYPE_PREFERENCE = ("unstarted", "backlog", "triage")

_REOPEN_STATE_CACHE: dict = {}


def reopen_state_id(team_id: str) -> str:
    """The workflow state a CLOSED issue should be moved back to, or "".

    Needed because a standing rollup issue's identity is its kipi-key, so there
    is exactly one of them forever. Rewriting a Done issue's body leaves the
    finding invisible on the board while the run reports it as handled. State is
    what carries visibility; the body does not.

    Returns "" when the team exposes no reopenable state, so the caller can
    still write the body rather than failing the whole run over a missing column.
    """
    if team_id in _REOPEN_STATE_CACHE:
        return _REOPEN_STATE_CACHE[team_id]
    nodes = (
        ((graphql(TEAM_STATES_QUERY, {"teamId": team_id}).get("team") or {}).get("states") or {})
        .get("nodes")
        or []
    )
    chosen = ""
    for wanted in _REOPEN_TYPE_PREFERENCE:
        matches = [n for n in nodes if n.get("type") == wanted]
        if matches:
            chosen = sorted(matches, key=lambda n: n.get("position") or 0)[0]["id"]
            break
    _REOPEN_STATE_CACHE[team_id] = chosen
    return chosen


def fetch_remote_state(team_key: str, repo: str) -> tuple:
    """(team_id, project_or_None, {kipi-key: {...}}) straight from Linear.

    This is the AUTHORITATIVE duplicate guard, refetched at create time rather
    than trusted from the plan's `--remote` snapshot. A plan written an hour ago
    and applied now would otherwise recreate anything added in between, and
    those duplicates cannot be deleted.
    """
    teams = (graphql(TEAM_QUERY, {"key": team_key}).get("teams") or {}).get("nodes") or []
    if not teams:
        raise LinearAPIError(f"no team with key {team_key!r}")
    team_id = teams[0]["id"]

    projects = (
        ((graphql(TEAM_PROJECTS_QUERY, {"teamId": team_id}).get("team") or {}).get("projects") or {})
        .get("nodes")
        or []
    )
    pkey = project_key(repo)
    project = None
    for proj in projects:
        if MARKER_RE.search(proj.get("description") or "") and pkey in (
            MARKER_RE.findall(proj.get("description") or "")
        ):
            project = proj
            break
        if (proj.get("name") or "").strip() == repo:
            project = proj
            break

    keys: dict = {}
    if project:
        after = None
        while True:
            page = (
                graphql(PROJECT_ISSUES_QUERY, {"projectId": project["id"], "after": after}).get(
                    "issues"
                )
                or {}
            )
            for node in page.get("nodes") or []:
                found = MARKER_RE.search(node.get("description") or "")
                if found:
                    state = node.get("state") or {}
                    keys[found.group(1)] = {
                        "linear_id": node["id"],
                        "identifier": node["identifier"],
                        # The live body, so a caller holding a standing rollup
                        # issue can tell "unchanged" from "needs a rewrite"
                        # without a second fetch. cmd_remote does not carry this
                        # into its snapshot; the snapshot is a dedup guard only.
                        "description": node.get("description") or "",
                        # STATE, for the same reason. A standing rollup issue the
                        # operator closed is the correct end state of the fix;
                        # rewriting its body afterwards puts the finding somewhere
                        # nobody looks. A caller cannot tell without this field.
                        "state_type": state.get("type") or "",
                        "state_name": state.get("name") or "",
                        # The issue's OWN team. A project can span teams, and a
                        # workflow state id belongs to one team, so a caller
                        # moving an issue back onto the board must ask that
                        # issue's team for the state rather than assume the
                        # team it started the lookup from.
                        "team_id": (node.get("team") or {}).get("id") or "",
                    }
            info = page.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                break
            after = info.get("endCursor")
    return team_id, project, keys


# What Linear's "that id is not an issue" reads like on the wire. Matched on the
# message rather than the status code because the call returns HTTP 200 with an
# `errors` array (see graphql's docstring).
_ENTITY_NOT_FOUND_RE = re.compile(r"Entity not found|Could not find referenced", re.I)


def fetch_issue(linear_id: str) -> dict:
    """One issue by id, in the same record shape `fetch_remote_state` returns.

    Same shape ON PURPOSE: a caller that already handles a tracked issue must not
    need a second code path for "the same issue, found a different way". Two
    readers of one input with different semantics is the defect this avoids.

    Returns {} when the issue is gone, so the caller can tell "moved" (a record)
    from "not there any more" (empty) and report the second rather than silently
    treating a key it can no longer maintain as handled.
    """
    try:
        node = (graphql(ISSUE_BY_ID_QUERY, {"id": linear_id}) or {}).get("issue") or {}
    except LinearAPIError as exc:
        # Linear answers an unknown id with a GraphQL ERROR, not a null issue.
        # Verified live 2026-07-27: `Entity not found: Issue ... code
        # INPUT_ERROR`. The first cut of this function checked for a null node
        # and never saw that, so a deleted issue would have surfaced to the
        # operator as "Linear rejected the write" instead of "this key has no
        # issue any more" -- right ping, wrong sentence.
        if not _ENTITY_NOT_FOUND_RE.search(str(exc)):
            raise  # a 429 or a dropped connection is NOT "gone"
        return {}
    if not node.get("id"):
        return {}
    state = node.get("state") or {}
    return {
        "linear_id": node["id"],
        "identifier": node.get("identifier") or "",
        "description": node.get("description") or "",
        "state_type": state.get("type") or "",
        "state_name": state.get("name") or "",
        "team_id": (node.get("team") or {}).get("id") or "",
    }


COMMENT_CREATE = """
mutation($input: CommentCreateInput!) {
  commentCreate(input: $input) { success comment { id } }
}
"""

ISSUE_BY_ID = """
query($id: String!) { issue(id: $id) { id identifier title state { name type } } }
"""

# THE READ HALF OF THE REVIEW CONVERSATION (ASK-221). `progress` could already
# WRITE a comment onto an issue, so the trail was one-way: codex posted its review
# and Sana never saw it, because the worker reads PR comments and the review
# conversation the founder asked for lives on the Linear issue. Without a read verb
# "they can talk to each other" is one agent talking.
#
# `botActor` is the FALLBACK, not the usual case: verified against ASK-221's live
# thread 2026-07-29, `user.name` comes back as the token owner ("Assaf Kipnis") for
# agent-written comments, because these go through the founder's API token. So the
# API author identifies the TOKEN, never the agent -- which is exactly why the
# agent name is carried in the BODY by `progress` and why --agent below filters on
# text rather than on this field. botActor only covers a genuine bot integration.
ISSUE_COMMENTS = """
query($id: String!) {
  issue(id: $id) {
    id identifier title
    comments(first: 100) {
      nodes { id createdAt body user { name } botActor { name } }
    }
  }
}
"""


def cmd_progress(args) -> int:
    """Post a progress note onto an issue, and optionally move its state.

    Why this exists: measured 2026-07-26, ONE issue out of 146 carried any
    progress comments (ASK-113, where sessions had been reporting by hand). An
    issue that says only "In Progress" with no trail is indistinguishable from an
    abandoned one -- which is exactly the "left hanging" state the founder is
    trying to eliminate. The trail belongs ON the issue, not in a chat log or a
    Slack message, because those cannot be read later by whoever picks it up.

    Agents call this as they work. The founder reads the issue, not the agent.
    """
    try:
        issue = graphql(ISSUE_BY_ID, {"id": args.issue}).get("issue")
    except LinearAPIError as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not issue:
        print(f"BLOCK: no issue {args.issue}", file=sys.stderr)
        return EXIT_USAGE

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    who = args.agent or os.environ.get("KIPI_AGENT") or "sana"
    body = f"**{who}** · {stamp}\n\n{args.note}"
    if args.evidence:
        # "I ran X and got Y" beats "should work" -- the repo's own bar.
        body += f"\n\n```\n{args.evidence}\n```"

    # CHECK THE MUTATION RESULT. Codex found this on 2026-07-29 (major,
    # linear-sync.py:663): the return value was discarded, so a rejected
    # commentCreate still printed "progress noted" and exited 0. That is the
    # slack-notify.sh always-exits-0 defect again (sp-8f879dc5) on the channel the
    # review CONVERSATION now depends on -- the reviewer would report that its
    # findings reached the issue when no comment exists, and Sana would be told to
    # reply to a thread that is not there.
    result = graphql(COMMENT_CREATE, {"input": {"issueId": issue["id"], "body": body}})
    created = (result or {}).get("commentCreate") or {}
    if not created.get("success") or not (created.get("comment") or {}).get("id"):
        print(f"BLOCK: Linear accepted the request but did not create the comment on "
              f"{issue['identifier']}. Nothing was posted. Raw: {created}", file=sys.stderr)
        return EXIT_USAGE
    print(f"{issue['identifier']}: progress noted by {who} (state: {issue['state']['name']})")
    # Deliberately does NOT change state. A progress note and a state transition
    # are different claims: "here is what happened" vs "this is now done". Moving
    # state belongs to the closeout gates (/issue-verify, /issue-closeout), which
    # refuse without receipts. Letting a comment also flip state would route
    # around them.
    return EXIT_OK


ISSUE_LABELS = """query($id:String!){
  issue(id: $id) {
    id identifier
    team { id }
    labels { nodes { id name } }
  }
}"""

TEAM_LABELS = """query($t:String!){
  team(id: $t) { labels(first: 250) { nodes { id name } } }
}"""

LABEL_CREATE = """mutation($input: IssueLabelCreateInput!){
  issueLabelCreate(input: $input) { success issueLabel { id name } }
}"""


def cmd_label(args) -> int:
    """Add a label to an issue, without disturbing the labels already on it.

    WHY THIS EXISTS (ASK-275). linear-triage.py has classified issues as
    `needs-scope` since 2026-07-27, and its verdict has always been a COMMENT.
    Grepping that file for a label mutation returns zero. So the classifier was a
    producer with no machine-readable output: a human could read the verdict, and
    nothing in the loop could. The worker picker cannot filter on prose.

    Adding the label is what turns a refusal into something ready() can exclude.
    Before this, the only way to get a correctly-refused issue out of the queue
    was to relabel it `owner:assaf` -- the FOUNDER queue -- which is how ASK-149
    ended up there on 2026-07-30. A re-scope is engineering work, so it must not
    land on the founder.

    READ-MODIFY-WRITE, deliberately: Linear's issueUpdate takes labelIds as the
    COMPLETE set, so sending only the new id would silently strip every existing
    label, including owner:sana -- which would drop the issue out of the queue for
    the wrong reason and make it un-findable. The union is computed here and the
    result is verified below rather than assumed.
    """
    try:
        issue = graphql(ISSUE_LABELS, {"id": args.issue}).get("issue")
    except LinearAPIError as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not issue:
        print(f"BLOCK: no issue {args.issue}", file=sys.stderr)
        return EXIT_USAGE

    current = {n["name"]: n["id"] for n in (issue.get("labels") or {}).get("nodes", [])}
    if args.name in current:
        # Idempotent on purpose: the worker may refuse the same issue twice before
        # the picker next runs, and a second call must not be an error.
        print(f"{issue['identifier']}: already labelled {args.name}")
        return EXIT_OK

    team_id = (issue.get("team") or {}).get("id")
    known = {n["name"]: n["id"]
             for n in ((graphql(TEAM_LABELS, {"t": team_id}).get("team") or {})
                       .get("labels") or {}).get("nodes", [])}
    label_id = known.get(args.name)
    if not label_id:
        made = graphql(LABEL_CREATE, {"input": {"name": args.name, "teamId": team_id}})
        created = (made or {}).get("issueLabelCreate") or {}
        if not created.get("success"):
            print(f"BLOCK: could not create label {args.name}: {created}", file=sys.stderr)
            return EXIT_USAGE
        label_id = created["issueLabel"]["id"]

    result = graphql(ISSUE_UPDATE, {
        "id": issue["id"],
        "input": {"labelIds": sorted(set(current.values()) | {label_id})},
    })
    updated = (result or {}).get("issueUpdate") or {}
    # CHECK THE MUTATION RESULT, same reason cmd_progress does (codex 2026-07-29):
    # a discarded return value turns a rejected write into a reported success, and
    # here that would mean the worker believes an issue is out of the queue while
    # the picker keeps handing it back -- an infinite, silent redispatch loop.
    if not updated.get("success"):
        print(f"BLOCK: Linear did not apply {args.name} to {issue['identifier']}. "
              f"Raw: {updated}", file=sys.stderr)
        return EXIT_USAGE
    print(f"{issue['identifier']}: labelled {args.name}")
    return EXIT_OK


def cmd_unblock(args) -> int:
    """Remove ONE label from an issue, keeping every other label on it.

    THE INVERSE OF cmd_label, AND IT DID NOT EXIST (ASK-288). The worker could
    apply `blocked:capability` and nothing in the fleet could take it off, so a
    park was permanent: the label removes the issue from the picker, and the
    Linear comment's "once it exists, remove this label" named a human as the
    only actor who could. Ten issues sat at that state on 2026-08-01 while the
    loop reported a healthy empty queue every 15 minutes.

    A block worth applying automatically is a block worth clearing
    automatically. capability_block_expiry.py is the caller: it re-tests the
    recorded probe and calls this only on an affirmative pass.

    NOT READ-MODIFY-WRITE (codex, PR #77). The first cut mirrored cmd_label:
    read every label, drop one, send the rest back through issueUpdate, which
    takes labelIds as the COMPLETE set. That makes the write a full-set
    overwrite carrying a snapshot taken seconds earlier -- so any label another
    actor added in between is silently deleted. This fleet runs a picker, a
    worker and this expiry sweep against ONE board, so a concurrent labeller is
    the normal case rather than a rare interleaving, and the label most likely
    to be added in that window is the one a second worker uses to claim the
    issue. Losing it would double-dispatch the issue that was just recovered.

    issueRemoveLabel names the single label and lets the server do the set
    arithmetic under its own lock. The read below is only to resolve the label
    NAME to an id and to answer "was it even applied"; nothing read there is
    written back.
    """
    try:
        issue = graphql(ISSUE_LABELS, {"id": args.issue}).get("issue")
    except LinearAPIError as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not issue:
        print(f"BLOCK: no issue {args.issue}", file=sys.stderr)
        return EXIT_USAGE

    current = {n["name"]: n["id"] for n in (issue.get("labels") or {}).get("nodes", [])}
    if args.name not in current:
        # Idempotent, matching cmd_label: two expiry sweeps can overlap, and the
        # second must not be an error just because the first won.
        print(f"{issue['identifier']}: not labelled {args.name}, nothing to remove")
        return EXIT_OK

    result = graphql(ISSUE_REMOVE_LABEL,
                     {"id": issue["id"], "labelId": current[args.name]})
    updated = (result or {}).get("issueRemoveLabel") or {}
    # CHECK THE MUTATION RESULT (codex 2026-07-29, the same defect twice above):
    # a discarded return value here reports an un-parked issue that is still
    # parked, so the caller logs a recovery the picker will never see.
    if not updated.get("success"):
        print(f"BLOCK: Linear did not remove {args.name} from {issue['identifier']}. "
              f"Raw: {updated}", file=sys.stderr)
        return EXIT_USAGE
    print(f"{issue['identifier']}: removed {args.name}")
    return EXIT_OK


def cmd_comments(args) -> int:
    """Print an issue's comment thread so an agent can READ what the other said.

    Why this exists: the review conversation between Sana and the codex reviewer
    is supposed to happen on the Linear issue (founder directive 2026-07-29), and
    an issue is the only place both agents can see. Before this, `progress` could
    write a comment but nothing could read one back, so each agent was posting
    into a channel it could not hear.

    Prints plain text, not JSON, on purpose: the consumer is an LLM reading its
    own prompt context, and a JSON blob costs tokens to restate as prose.
    """
    try:
        issue = graphql(ISSUE_COMMENTS, {"id": args.issue}).get("issue")
    except LinearAPIError as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not issue:
        print(f"BLOCK: no issue {args.issue}", file=sys.stderr)
        return EXIT_USAGE

    nodes = (issue.get("comments") or {}).get("nodes") or []
    # SORT EXPLICITLY. Do not trust the API's order. Verified live on ASK-221
    # 2026-07-29: Linear returns this connection NEWEST-FIRST, and the first cut of
    # this verb documented and assumed oldest-first -- so `--last N` sliced the tail
    # of a descending list and returned the OLDEST N. It hid the Codex reply that
    # arrived 4 seconds after the request, through two turns of looking straight at
    # it. My own test passed because its fixture was hand-written ascending: the
    # exact defect Codex flagged in this same session (a fixture built from the
    # author's mental model rather than from what the producer emits), committed
    # twice in one day. Sorting here makes the order a property of this function
    # instead of an assumption about a remote API.
    nodes.sort(key=lambda n: n.get("createdAt") or "")
    if args.agent:
        # MATCH THE ATTRIBUTION MARKER, NOT ANY MENTION. `progress` writes the
        # author as the literal first line "**<who>** · <stamp>", so `**sana**` is
        # the author and a bare "sana" anywhere else is just prose ABOUT Sana.
        #
        # Codex found the bare-substring version on 2026-07-29 (minor,
        # linear-sync.py:699) and it was a live bug, not a hypothetical: the
        # reviewer's own comment body contains the sentence "Sana: reply to this
        # comment on THIS issue", so `--agent sana` returned the REVIEWER's comment
        # as if Sana had written it. My own test passed because its fixture never
        # put the word "sana" inside the reviewer's comment. The real prompt does.
        # ANCHOR TO THE FIRST LINE, not anywhere in the body. `progress` writes the
        # author as the literal first line "**<who>** · <stamp>", so that line IS the
        # attribution and everything after it is prose.
        #
        # Codex found the whole-body version on 2026-07-30 (minor, reproducer with
        # real output): a comment authored by codex-reviewer whose prose contains the
        # markdown `**sana**` was attributed to Sana. Third time in one session that
        # my fixture missed the shape that breaks it -- the earlier regression case
        # covered the bare text "Sana:" and not the marker token itself, so the suite
        # stayed green over a live bug. See feedback-fixtures-from-producers.
        # MATCH THE COMPLETE PRODUCER-OWNED PREFIX, delimiter included. `progress`
        # emits exactly "**<who>** · <stamp>", so the attribution is the marker AND
        # the " · " that follows it. Without the delimiter, prose that merely OPENS
        # with a bold mention -- "**sana** please review this note" -- is read as
        # authorship.
        #
        # THIRD NARROWING OF THE SAME BUG, all three found by codex, each time
        # because I removed the case in front of me instead of the ambiguity:
        # bare substring -> marker anywhere in body -> marker at start of line ->
        # (now) the full attribution prefix. The delimiter is what makes this a
        # producer contract rather than a guess about prose.
        prefix = f"**{args.agent.lower()}** · "
        nodes = [n for n in nodes
                 if (n.get("body") or "").lstrip().split("\n", 1)[0].lower().startswith(prefix)]
    if args.last and args.last > 0:
        nodes = nodes[-args.last:]

    if not nodes:
        print(f"{issue['identifier']}: no comments match")
        return EXIT_OK

    print(f"{issue['identifier']}: {issue['title']}  ({len(nodes)} comment(s))")
    for n in nodes:
        who = (n.get("user") or {}).get("name") \
            or (n.get("botActor") or {}).get("name") or "unknown"
        print(f"\n--- {n.get('createdAt', '?')} · via {who} ---")
        print((n.get("body") or "").strip())
    return EXIT_OK


def cmd_remote(args) -> int:
    """Write the snapshot `plan --remote` expects, straight from the API.

    Before the API key existed this snapshot had to be hand-fetched in an agent
    session over MCP, which is why the rollout stalled at one repo per session.
    Reusing fetch_remote_state means the snapshot and the create-time guard read
    the SAME markers through the same code -- a second fetcher would be a second
    definition of "already exists", and the two would drift.
    """
    try:
        _team_id, project, keys = fetch_remote_state(args.team, args.repo)
    except LinearAPIError as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return EXIT_USAGE
    issues = [
        {"id": v["linear_id"], "identifier": v["identifier"],
         "description": f"<!-- kipi-key: {k} -->"}
        for k, v in keys.items()
    ]
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"project": project, "issues": issues}, fh, indent=2, ensure_ascii=False)
    print(
        f"{args.repo}: project={'found' if project else 'MISSING'}, "
        f"{len(issues)} existing keyed issue(s) -> {args.out}"
    )
    return EXIT_OK


def cmd_create(args) -> int:
    """Apply a plan against live Linear. Dry by default; --apply to write."""
    try:
        with open(args.plan, "r", encoding="utf-8") as fh:
            plan = json.load(fh)
    except OSError as exc:
        print(f"BLOCK: cannot read plan {args.plan}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except json.JSONDecodeError as exc:
        # An empty or malformed plan must be a clean refusal, not a traceback:
        # this is the first thing a new operator hits, and a stack trace reads as
        # "the tool is broken" rather than "point me at a real plan file".
        print(
            f"BLOCK: plan {args.plan} is not valid JSON ({exc}). Generate one with "
            "`kipi linear plan --map <capability-map> --remote <snapshot> --out <plan>`.",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if not isinstance(plan, dict) or not plan.get("repo"):
        print(f"BLOCK: plan {args.plan} has no 'repo' field", file=sys.stderr)
        return EXIT_USAGE
    repo = plan["repo"]

    try:
        team_id, project, remote_keys = fetch_remote_state(args.team, repo)
    except LinearAPIError as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return EXIT_USAGE

    ledger = read_ledger()
    known = set(ledger) | set(remote_keys)

    want_project = plan.get("create_project")
    if project:
        want_project = None  # already exists remotely; never make a second one
    issues = [i for i in (plan.get("create_issues") or []) if i["key"] not in known]
    skipped = len(plan.get("create_issues") or []) - len(issues)

    print(
        f"{repo}: would create project={'yes' if want_project else 'exists'}, "
        f"{len(issues)} issue(s), skipping {skipped} already known"
    )
    if not args.apply:
        print("dry run. re-run with --apply to write to Linear.")
        return EXIT_OK

    if want_project:
        data = graphql(
            PROJECT_CREATE,
            {
                "input": {
                    "name": want_project["name"],
                    "description": (
                        f"{want_project.get('summary', '')}\n\n"
                        f"<!-- kipi-key: {want_project['key']} -->"
                    ).strip(),
                    "teamIds": [team_id],
                }
            },
        )
        created = (data.get("projectCreate") or {}).get("project") or {}
        if not created.get("id"):
            print("BLOCK: projectCreate returned no project", file=sys.stderr)
            return EXIT_USAGE
        project = created
        # Append IMMEDIATELY. A crash before the next write must not lose the
        # record of a permanent object.
        append_ledger([{
            "key": want_project["key"], "kind": "project",
            "linear_id": created["id"], "identifier": created.get("name"),
            "source": "api-create",
        }])
        print(f"  created project {created.get('name')} ({created['id']})")

    made = 0
    for issue in issues:
        payload = {
            "title": issue["title"],
            "description": issue["description"],
            "teamId": team_id,
        }
        if project:
            payload["projectId"] = project["id"]
        try:
            data = graphql(ISSUE_CREATE, {"input": payload})
        except LinearAPIError as exc:
            # Stop on the first failure. Continuing would keep spending against a
            # broken condition (bad auth, rate limit) and the ledger's account of
            # what exists would drift from Linear.
            print(f"BLOCK after {made} create(s): {exc}", file=sys.stderr)
            return EXIT_USAGE
        node = (data.get("issueCreate") or {}).get("issue") or {}
        if not node.get("id"):
            print(f"BLOCK: issueCreate returned no issue for {issue['key']}", file=sys.stderr)
            return EXIT_USAGE
        append_ledger([{
            "key": issue["key"], "kind": "issue",
            "linear_id": node["id"], "identifier": node.get("identifier"),
            "source": "api-create",
        }])
        made += 1
        print(f"  {node.get('identifier')}  {issue['title'][:70]}")

    print(f"{repo}: created {made} issue(s). Ledger updated per create.")
    return EXIT_OK


def cmd_plan(args) -> int:
    with open(args.map, "r", encoding="utf-8") as fh:
        cmap = json.load(fh)
    repo = cmap.get("repo")
    if not repo:
        print("BLOCK: capability map has no 'repo' field", file=sys.stderr)
        return EXIT_USAGE
    caps = cmap.get("capabilities") or []

    # Collision check BEFORE anything else. Two capabilities that slugify to the
    # same key would silently become one issue, and the second would look "already
    # created" forever. Refuse the map instead of guessing which one wins.
    seen = {}
    for cap in caps:
        k = make_key(repo, cap.get("name", ""))
        if k in seen:
            print(
                f"BLOCK: '{cap.get('name')}' and '{seen[k]}' both slugify to {k}.\n"
                f"       Rename one in the capability map. Two capabilities sharing a\n"
                f"       dedup key would collapse into one permanent issue.",
                file=sys.stderr,
            )
            return EXIT_COLLISION
        seen[k] = cap.get("name")

    with open(args.remote, "r", encoding="utf-8") as fh:
        remote = json.load(fh)
    remote_keys, remote_project = parse_remote(remote)

    ledger = read_ledger()

    # Rehydrate: anything Linear knows about that the ledger does not. This is what
    # makes a lost ledger a no-op instead of 400 duplicates.
    rehydrate = [
        {"key": k, "kind": "issue", "linear_id": v["linear_id"],
         "identifier": v["identifier"], "source": "remote-rehydrate"}
        for k, v in remote_keys.items()
        if k not in ledger
    ]
    pkey = project_key(repo)
    if remote_project and pkey not in ledger:
        rehydrate.append({
            "key": pkey, "kind": "project",
            "linear_id": remote_project.get("id"),
            "identifier": remote_project.get("name"),
            "source": "remote-rehydrate",
        })
    if rehydrate:
        append_ledger(rehydrate)
        ledger = read_ledger()

    known = set(ledger) | set(remote_keys)

    create_issues = []
    rolled = []
    for i, cap in enumerate(caps):
        if not cap.get("track", True):
            continue
        if args.filter == "actionable" and _state_for(cap) == "Done":
            continue
        # UNWIRED is a survey finding, not a defect: "this script has no test and
        # no caller" is ONE decision for the repo (audit them, wire them, or delete
        # them), not N decisions. Filing it per script would make the founder groom
        # 25 items to make 1 call, and every one of those issues is permanent.
        # NEEDS_WORK and BROKEN stay individual: each is a distinct defect.
        if args.rollup and str(cap.get("status", "")).upper() == "UNWIRED":
            rolled.append(cap)
            continue
        issue = build_issue(repo, cap, i)
        if issue["key"] in known:
            continue
        create_issues.append(issue)

    if rolled:
        rollup = build_rollup(repo, rolled)
        if rollup["key"] not in known:
            create_issues.append(rollup)

    create_project = None
    if pkey not in known:
        create_project = {
            "key": pkey,
            "name": repo,
            "summary": (cmap.get("summary") or f"Capabilities of the {repo} repo.")[:255],
            "description": cmap.get("description") or "",
        }

    plan = {
        "repo": repo,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "create_project": create_project,
        "create_issues": create_issues,
        "skipped_known": len(caps) - len(create_issues),
        "rehydrated": len(rehydrate),
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2, ensure_ascii=False)

    print(
        f"{repo}: plan {len(create_issues)} issue(s), "
        f"project={'yes' if create_project else 'exists'}, "
        f"skipped {plan['skipped_known']} known, rehydrated {len(rehydrate)}"
    )
    return EXIT_OK


def cmd_record(args) -> int:
    with open(args.results, "r", encoding="utf-8") as fh:
        results = json.load(fh)
    records = []
    proj = results.get("project")
    if proj and proj.get("key"):
        records.append({"key": proj["key"], "kind": "project",
                        "linear_id": proj.get("linear_id"),
                        "identifier": proj.get("identifier")})
    for issue in results.get("issues") or []:
        if issue.get("key"):
            records.append({"key": issue["key"], "kind": "issue",
                            "linear_id": issue.get("linear_id"),
                            "identifier": issue.get("identifier")})
    n = append_ledger(records)
    print(f"recorded {n} object(s) to {ledger_path()}")
    return EXIT_OK


def cmd_key(args) -> int:
    print(make_key(args.repo, args.capability))
    return EXIT_OK


def cmd_status(args) -> int:
    """Answer 'which repos are done' without re-querying Linear."""
    ledger = read_ledger()
    repos = {}
    for key, rec in ledger.items():
        repo = key.split("/", 1)[0]
        bucket = repos.setdefault(repo, {"project": False, "issues": 0})
        if rec.get("kind") == "project" or key.endswith(PROJECT_SUFFIX):
            bucket["project"] = True
        else:
            bucket["issues"] += 1
    if not repos:
        print("ledger empty: no repos rolled out yet")
        return EXIT_OK
    print(f"{'repo':32} {'project':8} issues")
    for repo in sorted(repos):
        b = repos[repo]
        print(f"{repo:32} {'yes' if b['project'] else 'NO':8} {b['issues']}")
    print(f"\n{len(repos)} repo(s) in the ledger at {ledger_path()}")
    return EXIT_OK


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="decide what to create; writes a plan JSON")
    p.add_argument("--map", required=True, help="path to a CAPABILITY-MAP.json")
    p.add_argument("--remote", required=True, help="snapshot of what Linear already has")
    p.add_argument("--out", required=True, help="where to write the plan")
    p.add_argument("--filter", choices=["all", "actionable"], default="all")
    p.add_argument("--rollup", action="store_true",
                   help="collapse UNWIRED engines into one audit issue per repo")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("record", help="append created objects to the ledger")
    p.add_argument("--results", required=True)
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("key", help="print the dedup key for a repo/capability pair")
    p.add_argument("--repo", required=True)
    p.add_argument("--capability", required=True)
    p.set_defaults(func=cmd_key)

    p = sub.add_parser("progress", help="post a progress note onto an issue")
    p.add_argument("issue", help="issue identifier, e.g. ASK-113")
    p.add_argument("note", help="what happened, in one or two sentences")
    p.add_argument("--agent", help="who is reporting (default: $KIPI_AGENT or sana)")
    p.add_argument("--evidence", help="the command and its real output")
    p.set_defaults(func=cmd_progress)

    p = sub.add_parser("label", help="add one label to an issue, keeping the rest")
    p.add_argument("issue", help="issue identifier, e.g. ASK-148")
    p.add_argument("name", help="label to add, e.g. needs-scope")
    p.set_defaults(func=cmd_label)

    p = sub.add_parser("unblock", help="remove one label from an issue, keeping the rest")
    p.add_argument("issue", help="issue identifier, e.g. ASK-288")
    p.add_argument("name", help="label to remove, e.g. blocked:capability")
    p.set_defaults(func=cmd_unblock)

    p = sub.add_parser("comments", help="read an issue's comment thread")
    p.add_argument("issue", help="issue identifier, e.g. ASK-221")
    p.add_argument("--agent", help="only comments whose body names this agent")
    p.add_argument("--last", type=int, default=0, help="only the N most recent")
    p.set_defaults(func=cmd_comments)

    p = sub.add_parser("remote", help="fetch the remote snapshot plan --remote wants")
    p.add_argument("--repo", required=True)
    p.add_argument("--team", default="ASK")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_remote)

    p = sub.add_parser("create", help="apply a plan to live Linear (dry unless --apply)")
    p.add_argument("--plan", required=True, help="plan JSON from `plan`")
    p.add_argument("--team", default="ASK", help="Linear team KEY (default ASK)")
    # Dry by default and --apply to write, because Linear objects are permanent:
    # delete and archive are hook-blocked and an agent cannot self-authorize them,
    # so an accidental run cannot be undone.
    p.add_argument("--apply", action="store_true", help="actually write to Linear")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("status", help="which repos are rolled out")
    p.set_defaults(func=cmd_status)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
