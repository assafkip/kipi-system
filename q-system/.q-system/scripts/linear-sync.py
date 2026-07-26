#!/usr/bin/env python3
"""Idempotent planner for Linear project/issue creation across the kipi fleet.

Pairs with q-system/output/plans/linear-sdlc-standard-2026-07-26.md (Part 2) and
its reproducer q-system/.q-system/scripts/test/test-linear-sync-idempotent.sh.

WHY A PLANNER AND NOT A CREATOR (ASK-113): this script cannot reach Linear. There
is no Linear API key in ~/.config/kipi/ and no LINEAR_* env var, so Linear is
reachable only through the MCP server, which is available to the agent and not to
a subprocess. The split is deliberate:

    plan   -> (agent creates via MCP) -> record

The deterministic half is the part that decides WHAT to create and the part that
remembers what was created. The network call happens where credentials exist.

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
    body = [
        f"<!-- kipi-key: {key} -->",
        "",
        f"`capability-map-gen.py` found **{len(rolled)} Python engines** in `{repo}` "
        "with neither a paired test nor any reference on a wiring surface "
        "(settings.json, lefthook.yml, a hook, a command, the kipi CLI, or another script).",
        "",
        "That does not prove they are dead. It proves nothing in the repo *says* "
        "they are alive, which is the same position a future reader is in.",
        "",
        "## The list",
        "",
        *rows,
        "",
        "## Definition of Ready",
        "",
        "- **Outcome:** every script below is either wired (and the wiring is visible), "
        "tested, or deleted. None are left in the ambiguous middle.",
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
        "",
        "## Why this is one issue and not "
        f"{len(rolled)}",
        "",
        "Wiring-or-deleting a repo's dead scripts is a single decision made once with "
        "the whole list in view. Split across "
        f"{len(rolled)} issues it becomes {len(rolled)} groomings for one call, and "
        "Linear issues cannot be deleted here, so each one is permanent.",
        "",
        "Filed under ASK-113.",
    ]
    return {
        "key": key,
        "title": f"Audit {len(rolled)} unwired engines in {repo}",
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
    nodes { id identifier description }
    pageInfo { hasNextPage endCursor }
  }
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
                    keys[found.group(1)] = {
                        "linear_id": node["id"],
                        "identifier": node["identifier"],
                    }
            info = page.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                break
            after = info.get("endCursor")
    return team_id, project, keys


def cmd_create(args) -> int:
    """Apply a plan against live Linear. Dry by default; --apply to write."""
    with open(args.plan, "r", encoding="utf-8") as fh:
        plan = json.load(fh)
    repo = plan.get("repo")
    if not repo:
        print("BLOCK: plan has no 'repo'", file=sys.stderr)
        return EXIT_USAGE

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
