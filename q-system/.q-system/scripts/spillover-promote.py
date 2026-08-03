#!/usr/bin/env python3
"""Turn a confirmed spillover finding into a fully-scoped Linear issue (ASK-344).

why: the ratchet delivers a note to the agent editing its file, and the agent
confirms it is still true. Then what? Before this, nothing -- a confirmed note
stayed a note. Triage with no address is just re-reading the pile.

This is the address. A confirmed finding becomes a Linear issue the autonomous
worker can actually pick up, and the ledger row stops firing.

THE BAR: no Definition of Ready, no issue. `linear-worker.sh` refuses any issue
without one, so promoting without a DoR would file something nothing can work --
the 137-issue queue that started this whole PRD. Refusing here is the only place
that cannot be forgotten later.

The DoR is written by the agent that CONFIRMED the finding, because it has the
file open and the context loaded. Nobody will ever be cheaper.

The row moves to `promoted`, not `resolved`. Resolution still requires the
Linear issue to actually close -- promoting is not fixing, and a status that
claimed otherwise would let the pile launder itself clean.

Usage:
  spillover-promote.py <id> --title "..." --dor-file dor.md
  spillover-promote.py <id> --title "..." --dor "..." --dry-run
"""
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
SKELETON = HERE.parents[3]
TEAM_KEY = os.environ.get("KIPI_LINEAR_TEAM", "ASK")

# The sections a DoR must carry for linear-worker to have anything to act on.
# Not cosmetic: an issue missing "what files" or "how do I know it is done" is
# one the worker either refuses or guesses at, and guessing is worse.
REQUIRED_DOR = ("allowed files", "acceptance")


def linear_module():
    spec = importlib.util.spec_from_file_location("ls", HERE.parent / "linear-sync.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_rows(ledger: Path) -> dict:
    rows = {}
    if not ledger.is_file():
        return rows
    for line in ledger.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in r:
                rows[r["id"]] = r
    return rows


def validate_dor(text: str) -> list:
    """Missing required sections. Empty list means the DoR is workable."""
    low = (text or "").lower()
    missing = [s for s in REQUIRED_DOR if s not in low]
    if len((text or "").strip()) < 120:
        missing.append("substance (under 120 chars is not a scope)")
    return missing


def build_body(rec: dict, dor: str, repo: str) -> str:
    return (
        f"Promoted from spillover `{rec['id']}` (severity: {rec.get('severity')}, "
        f"source: `{rec.get('source')}`, repo: `{repo}`).\n\n"
        f"## The finding\n\n{rec.get('description', '')}\n\n"
        f"## Definition of Ready\n\n{dor}\n\n"
        f"---\n*Confirmed still-true at the moment its file was edited, then "
        f"promoted. Resolve the ledger row with "
        f"`prd_runner.py spillover resolve {rec['id']} --resolution-ref <this issue>` "
        f"once this closes.*"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("finding_id")
    ap.add_argument("--title", required=True)
    ap.add_argument("--dor", help="Definition of Ready, inline")
    ap.add_argument("--dor-file", help="Definition of Ready, from a file")
    ap.add_argument("--repo-root", default=str(SKELETON))
    ap.add_argument("--priority", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(args.repo_root).resolve()
    ledger = root / ".prd-os" / "spillover.jsonl"
    rows = load_rows(ledger)
    rec = rows.get(args.finding_id)
    if not rec:
        sys.stderr.write(f"unknown finding: {args.finding_id}\n")
        return 2
    if rec.get("status") != "open":
        sys.stderr.write(f"{args.finding_id} is '{rec.get('status')}', not open\n")
        return 2

    dor = args.dor or ""
    if args.dor_file:
        dor = Path(args.dor_file).read_text()
    missing = validate_dor(dor)
    if missing:
        sys.stderr.write(
            f"refused: the Definition of Ready is missing {', '.join(missing)}.\n\n"
            "linear-worker.sh will not touch an issue without a workable DoR, so\n"
            "promoting without one files something nothing can work. That is the\n"
            "137-issue queue this whole effort started from.\n\n"
            "A DoR needs at least:\n"
            "  **Allowed files** -- explicit paths the fix may touch\n"
            "  **Acceptance**    -- checkboxes, including how a failure would show\n"
            "You have the file open. You are the cheapest person to write this.\n")
        return 2

    body = build_body(rec, dor, root.name)
    if args.dry_run:
        print(f"WOULD CREATE in team {TEAM_KEY}: {args.title}\n")
        print(body[:900])
        print(f"\nDRY RUN. {ledger} unchanged.")
        return 0

    ls = linear_module()
    tid = ls.graphql('query{teams(filter:{key:{eq:"%s"}}){nodes{id}}}' % TEAM_KEY,
                     {})["teams"]["nodes"][0]["id"]
    res = ls.graphql(ls.ISSUE_CREATE, {"input": {
        "teamId": tid, "title": args.title, "description": body,
        "priority": args.priority}})
    issue = (res.get("issueCreate") or {}).get("issue") or {}
    ident = issue.get("identifier")
    if not ident:
        sys.stderr.write(f"Linear create failed: {json.dumps(res)[:300]}\n")
        return 1

    # `promoted`, never `resolved`. Promoting is not fixing; a status claiming
    # otherwise would let the pile launder itself clean without a single fix.
    promoted = dict(rec)
    promoted.update({"status": "promoted", "linear_ref": ident,
                     "promoted_from_ratchet": True})
    with ledger.open("a") as fh:
        fh.write(json.dumps(promoted) + "\n")
        fh.flush()
    print(json.dumps({"finding": rec["id"], "linear": ident, "status": "promoted"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
