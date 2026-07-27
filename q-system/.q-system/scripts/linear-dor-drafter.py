#!/usr/bin/env python3
"""Draft a Definition of Ready onto Linear issues that lack one. Bounded, nightly.

WHY THIS IS THE GATE ON AUTONOMY

The autonomous worker (see q-system/output/plans/linear-autonomous-design-2026-07-26.md)
only picks up issues that satisfy the SDLC standard's Definition of Ready. That is
not bureaucracy, it is the line between "agents get things done in the background"
and "agents produce plausible garbage in the background". Measured 2026-07-26:
125 of 146 issues on the ASK board had no DoR, including all 48 in cole-GTM. Until
that is fixed the worker has almost nothing it can safely touch.

WHY A NIGHTLY DRIP AND NOT ONE BIG PASS

125 issues of LLM judgment in one run is a long unattended session with no
checkpoint, and `claude -p` runs on the founder's SUBSCRIPTION, so it competes with
interactive work. `--limit` keeps each night small and resumable; the backlog
drains over days without a babysitter. That is the same reasoning behind the
open-loops heartbeat's per-instance timeout.

WHY IT APPENDS AND NEVER OVERWRITES

The issue description is the founder's own words. This adds a `## Definition of
Ready` section beneath it and touches nothing else. An LLM rewriting a human's
issue text is not a trade worth making, and Linear issues cannot be deleted here.

AUDHD: every drafted DoR carries an Energy mode and a Time Est, per
`.claude/rules/audhd-interaction.md` — an issue the founder cannot pick up by
energy level is not actually ready for a human either.

Exit 0 always: this runs from launchd and must not mark its own job failed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
QROOT = HERE.parent.parent
STATE = Path.home() / ".config" / "kipi" / "linear-dor-state.json"
DOR_HEADING = "## Definition of Ready"
TEAM_KEY = "ASK"

# Statuses worth drafting for. A Done/Canceled issue needs no DoR, and drafting
# onto one would be pure noise on a permanent object.
DRAFTABLE_STATE_TYPES = ("backlog", "unstarted")

PROMPT = """You are writing a Definition of Ready for one Linear issue in a software fleet.

Repo/project: {project}
Title: {title}

Existing description:
---
{description}
---

Write ONLY the body of a "Definition of Ready" section. No preamble, no heading, no
code fences. Use exactly these five bullets, in this order:

- **Outcome:** one sentence, what is true when this is done, in plain terms.
- **Files:** the explicit paths you'd expect to touch. If genuinely unknown, say
  "unknown - needs a recon pass" rather than inventing paths.
- **Check:** the command that proves it works, or that currently fails. Runnable.
  If none exists, say what would have to be written.
- **Blast radius:** does this propagate to other repos via `kipi update`? Is it
  skeleton-only or fleet-wide? Does it touch always-on rules or settings?
- **Not doing:** the adjacent thing this issue explicitly does not cover.

Then one final line exactly like:
**Energy:** <Quick Win|Deep Focus|People|Admin> · **Time Est:** <e.g. 30 min, 2 h, half day>

Be concrete and short. If the issue is too vague to answer a bullet honestly, write
what is missing instead of guessing. Never invent a file path or a command that you
cannot see evidence for."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _linear():
    spec = importlib.util.spec_from_file_location("ls", HERE / "linear-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ISSUES_Q = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}}},first:250,after:$a){
  nodes{id identifier title description project{name} state{name type}}
  pageInfo{hasNextPage endCursor}}}"""

UPDATE_M = """mutation($id:String!,$input:IssueUpdateInput!){
  issueUpdate(id:$id,input:$input){success issue{identifier}}}"""


def needs_dor(issue: dict) -> bool:
    if (issue.get("state") or {}).get("type") not in DRAFTABLE_STATE_TYPES:
        return False
    desc = issue.get("description") or ""
    if DOR_HEADING in desc:
        return False
    # The generated capability issues already carry a DoR under their own wording.
    if "Definition of Ready" in desc:
        return False
    return True


def draft_one(issue: dict, timeout: int) -> str | None:
    """One `claude -p` call. Returns the DoR body, or None if it failed."""
    prompt = PROMPT.format(
        project=(issue.get("project") or {}).get("name") or "unassigned",
        title=issue.get("title") or "",
        description=(issue.get("description") or "(empty)")[:4000],
    )
    try:
        res = subprocess.run(
            ["claude", "-p", prompt, "--permission-mode", "acceptEdits"],
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"  {issue['identifier']}: claude failed ({type(exc).__name__})", file=sys.stderr)
        return None
    out = (res.stdout or "").strip()
    if res.returncode != 0 or len(out) < 60:
        print(f"  {issue['identifier']}: unusable output (rc={res.returncode}, {len(out)} chars)",
              file=sys.stderr)
        return None
    # Strip any stray fencing the model added despite instructions.
    out = re.sub(r"^```[a-z]*\n|\n```$", "", out).strip()
    if "**Energy:**" not in out:
        print(f"  {issue['identifier']}: no Energy/Time line, rejecting", file=sys.stderr)
        return None
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=5, help="issues per run (default 5)")
    ap.add_argument("--apply", action="store_true", help="write to Linear")
    ap.add_argument("--project", help="only this project")
    ap.add_argument("--timeout", type=int, default=300, help="seconds per claude call")
    args = ap.parse_args()

    ls = _linear()
    try:
        tid = ls.graphql('query{teams(filter:{key:{eq:"%s"}}){nodes{id}}}' % TEAM_KEY,
                         {})["teams"]["nodes"][0]["id"]
    except Exception as exc:  # noqa: BLE001
        print(f"linear unreachable: {exc}", file=sys.stderr)
        return 0

    issues, after = [], None
    while True:
        page = ls.graphql(ISSUES_Q, {"t": tid, "a": after})["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    todo = [i for i in issues if needs_dor(i)]
    if args.project:
        todo = [i for i in todo
                if ((i.get("project") or {}).get("name") or "") == args.project]

    print(f"dor-drafter {_now()}: {len(todo)} issue(s) lack a Definition of Ready")
    batch = todo[: args.limit]
    if not args.apply:
        for i in batch:
            print(f"  would draft {i['identifier']}  {i['title'][:66]}")
        print(f"dry run. {len(todo)} remaining; --apply to write {len(batch)}.")
        return 0

    drafted = 0
    for issue in batch:
        body = draft_one(issue, args.timeout)
        if not body:
            continue
        new_desc = (issue.get("description") or "").rstrip() + f"\n\n{DOR_HEADING}\n\n{body}\n"
        try:
            ls.graphql(UPDATE_M, {"id": issue["identifier"],
                                  "input": {"description": new_desc}})
        except Exception as exc:  # noqa: BLE001
            print(f"  {issue['identifier']}: update failed: {str(exc)[:120]}", file=sys.stderr)
            continue
        drafted += 1
        print(f"  drafted {issue['identifier']}  {issue['title'][:60]}")

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(
        {"ran_at": _now(), "drafted": drafted, "remaining": len(todo) - drafted}, indent=2))
    print(f"dor-drafter: drafted {drafted}, {len(todo) - drafted} still lack a DoR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
