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


def _labels_for(cap: dict) -> list:
    labels = ["kind:capability"]
    layer = str(cap.get("layer") or "").strip()
    if layer:
        # "L1 Propagation and fleet control" -> "layer:L1"
        token = layer.split()[0]
        if re.fullmatch(r"L\d+", token):
            labels.append(f"layer:{token}")
    if not (cap.get("evidence") or "").strip():
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
    for i, cap in enumerate(caps):
        if not cap.get("track", True):
            continue
        if args.filter == "actionable" and _state_for(cap) == "Done":
            continue
        issue = build_issue(repo, cap, i)
        if issue["key"] in known:
            continue
        create_issues.append(issue)

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
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("record", help="append created objects to the ledger")
    p.add_argument("--results", required=True)
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("key", help="print the dedup key for a repo/capability pair")
    p.add_argument("--repo", required=True)
    p.add_argument("--capability", required=True)
    p.set_defaults(func=cmd_key)

    p = sub.add_parser("status", help="which repos are rolled out")
    p.set_defaults(func=cmd_status)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
