#!/usr/bin/env python3
"""fleet_load: build a headless job's lean launch from fleet-load-allowlist.json (ASK-4747, ASK-4756).

RULE-2026-11-13-E decided WHAT each job class loads; this is the one reader that turns
that file into launch arguments, so the worker does not keep a second copy of the list.

  settings   --job J --tree T [--guard-json S]   settings JSON for `claude -p --settings`:
             the guard set S (may be empty) plus enabledPlugins=false for every plugin
             the machine knows about whose name the job's row does not list. Prints
             nothing when there is nothing to pass, so the caller adds no --settings.
  mcp-config --job J                             the strict MCP config for --mcp-config.
  startup    --session SID --ticket T --record OUT
             reads the run's own transcript, reports what loaded at start-up (skill
             count, deferred tool names, MCP servers) against the row's
             startup_ceiling, appends one row to OUT, and prints ONE alert line only
             when the run crosses the ceiling and the previous row did not.

Exit 0 on success; 1 on a file it cannot read or parse (the caller logs it and falls
back to the full launch, which costs tokens and loses no gate); 2 on a row this code
cannot serve (an MCP server list it has no definitions for).

Why disable-the-rest and never force-enable the row: the worker runs in client trees
whose project settings may turn a fleet plugin off on purpose. Forcing it on would add
hooks that tree never ran. Turning the rest off can only remove what the job's row
says it does not use. Measured 2026-11-12 in a kipi-system tree (ASK-4756): 117,872
first-request tokens with the full set, 76,036 with this launch (76,166 re-measured
after the 2026-11-13 account sync).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ALLOW = Path(__file__).resolve().parent.parent / "fleet-load-allowlist.json"
STRICT_EMPTY = '{"mcpServers":{}}'


class Unservable(Exception):
    """A row this code cannot turn into launch arguments (exit 2). Not a LookupError:
    KeyError is one, and a missing job would then read as an unservable row."""


def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def job_row(job: str, allow: Path = ALLOW) -> dict:
    return json.loads(allow.read_text())["jobs"][job]


def _load(p: Path) -> dict:
    # A missing file is "nothing installed there"; a present file that does not parse
    # is an error, never an empty set: an empty set would turn nothing off and pass.
    if not p.exists():
        return {}
    d = json.loads(p.read_text())
    if not isinstance(d, dict):
        raise ValueError(f"{p}: not a JSON object")
    return d


def known_plugins(tree: Path, cfg: Path) -> set[str]:
    """Every plugin id (name@marketplace) the CLI could load for a session in `tree`.

    Four sources, each seen in `claude plugin list --json` on 2026-11-12/13: the install
    records, the enabledPlugins keys of the user and tree settings, a skills-dir plugin
    (a ~/.claude/skills/<dir> holding .claude-plugin/plugin.json, listed as
    <name>@skills-dir), and an account-synced plugin (<name>@synced). The CLI itself is not called: the worker's test suites stub
    `claude` on PATH, and a stray stub call would record argv and commit.
    """
    ids = set(_load(cfg / "plugins" / "installed_plugins.json").get("plugins", {}))
    # Both user files and both tree files: the CLI reads all four (PR #792 review, minor).
    for s in (cfg / "settings.json", cfg / "settings.local.json",
              tree / ".claude" / "settings.json", tree / ".claude" / "settings.local.json"):
        ids |= set(_load(s).get("enabledPlugins", {}) or {})
    skills = cfg / "skills"
    if skills.is_dir():
        for pj in sorted(skills.glob("*/.claude-plugin/plugin.json")):
            name = _load(pj).get("name") or pj.parent.parent.name
            ids.add(f"{name}@skills-dir")
    # Account-synced plugins (<name>@synced, scope "synced"): pushed by an account sync
    # under plugins/synced/<account>/<dir>/. Four appeared on 2026-11-13 between two
    # measurements ten minutes apart and took the lean listing from 106 skills to 164;
    # the start-up ratchet is what caught it. A fifth source would show up the same way.
    synced = cfg / "plugins" / "synced"
    if synced.is_dir():
        for pj in sorted(synced.glob("*/*/.claude-plugin/plugin.json")):
            name = _load(pj).get("name") or pj.parent.parent.name
            ids.add(f"{name}@synced")
    return ids


def lean_settings(job: str, tree: Path, guard_json: str, cfg: Path, allow: Path = ALLOW) -> str:
    keep = set(job_row(job, allow)["plugins"])
    off = {i: False for i in sorted(known_plugins(tree, cfg)) if i.split("@", 1)[0] not in keep}
    doc = json.loads(guard_json) if guard_json.strip() else {}
    if off:
        doc["enabledPlugins"] = {**(doc.get("enabledPlugins") or {}), **off}
    return json.dumps(doc) if doc else ""


def mcp_config(job: str, allow: Path = ALLOW) -> str:
    row = job_row(job, allow)
    if not row.get("strict_mcp"):
        return ""
    if row.get("mcp_servers"):
        # The file names servers but holds no definitions; serving them needs code.
        raise Unservable(f"{job}: mcp_servers {row['mcp_servers']} named, but fleet_load has no definitions for them")
    return STRICT_EMPTY


def startup_counts(transcript: Path) -> dict:
    """What the session loaded before its first request, from its attachment records."""
    out = {"skills": None, "skill_listing_chars": None, "deferred_tools": None, "mcp_servers": 0}
    servers: set[str] = set()
    for line in transcript.read_text().splitlines():
        try:
            a = json.loads(line).get("attachment") or {}
        except (ValueError, AttributeError):
            continue
        t = a.get("type")
        if t == "skill_listing" and out["skills"] is None:
            out["skills"] = a.get("skillCount", len(a.get("names") or []))
            out["skill_listing_chars"] = len(a.get("content") or "")
        elif t == "deferred_tools_delta" and out["deferred_tools"] is None:
            out["deferred_tools"] = len(a.get("addedNames") or [])
            for k in ("pendingMcpServers", "needsAuthMcpServers", "failedMcpServers"):
                servers |= set(a.get(k) or [])
            servers |= {n.split("__")[1] for n in a.get("addedNames") or [] if n.startswith("mcp__") and n.count("__") >= 2}
        elif t == "mcp_instructions_delta":
            servers |= set(a.get("addedNames") or [])
    out["mcp_servers"] = len(servers)
    return out


def over_ceiling(counts: dict, ceiling: dict) -> list[str]:
    # A count the transcript did not carry is reported as unread, never as zero:
    # a zero would pass every ceiling (ASK-4756, "silence is not a clean zero").
    over = []
    for k in ("skills", "deferred_tools", "mcp_servers"):
        if k not in ceiling:
            continue
        v = counts.get(k)
        if v is None:
            over.append(f"{k} unread")
        elif v > ceiling[k]:
            over.append(f"{k} {v} > {ceiling[k]}")
    return over


def startup(session: str, ticket: str, record: Path, cfg: Path, job: str = "worker", allow: Path = ALLOW) -> str:
    hits = sorted((cfg / "projects").glob(f"*/{session}.jsonl"))
    if not hits:
        return ""  # no transcript, no row: same rule as run_tokens.py --record
    counts = startup_counts(hits[0])
    over = over_ceiling(counts, job_row(job, allow).get("startup_ceiling") or {})
    prev_over = False
    if record.exists():
        rows = [ln for ln in record.read_text().splitlines() if ln.strip()]
        if rows:
            try:
                prev_over = bool(json.loads(rows[-1]).get("over"))
            except ValueError:
                prev_over = False
    row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "job": job,
           "ticket": ticket, "session": session, **counts, "over": over}
    record.parent.mkdir(parents=True, exist_ok=True)
    with record.open("a") as f:
        f.write(json.dumps(row) + "\n")
    if over and not prev_over:  # alert on the state change, once (founder-notifications.md)
        return f"worker start-up grew past its ceiling on {ticket}: {'; '.join(over)} (fleet-load-allowlist.json worker.startup_ceiling, ASK-4756)"
    return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("settings"); s.add_argument("--job", required=True); s.add_argument("--tree", required=True)
    s.add_argument("--guard-json", default="")
    m = sub.add_parser("mcp-config"); m.add_argument("--job", required=True)
    u = sub.add_parser("startup"); u.add_argument("--session", required=True); u.add_argument("--ticket", default="")
    u.add_argument("--record", required=True); u.add_argument("--job", default="worker")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "settings":
            out = lean_settings(a.job, Path(a.tree), a.guard_json, config_dir())
        elif a.cmd == "mcp-config":
            out = mcp_config(a.job)
        else:
            out = startup(a.session, a.ticket, Path(a.record), config_dir(), a.job)
    except Unservable as e:
        print(f"fleet_load: {e}", file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"fleet_load: {a.cmd}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
