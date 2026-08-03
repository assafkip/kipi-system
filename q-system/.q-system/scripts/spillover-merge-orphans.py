#!/usr/bin/env python3
"""Fold pre-fix worktree ledgers back into the one shared ledger (ASK-340).

why: `.prd-os/spillover.jsonl` is gitignored (`*.jsonl`), so before
`_ledger_root()` started resolving through `git rev-parse --git-common-dir`,
EVERY worktree wrote its own private ledger. `gates run` from the main checkout
was green about work it structurally could not see.

That fix is in and verified (a capture from a worktree now lands in the main
ledger). But it only stops NEW splits. Ledgers written before it are still
sitting in worktree directories holding real findings nobody can see.

This merges them. Append-only and id-keyed, so:
  - an id already in main is left alone; main is authoritative because it is
    where every post-fix write lands
  - an id only in a worktree is appended with its original record, tagged with
    the worktree it came from so its provenance survives
  - a RESOLVED orphan is never re-opened

Dry run by default.

Usage:
  spillover-merge-orphans.py                # report what would move
  spillover-merge-orphans.py --apply
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
SKELETON = HERE.parents[3]


def read_ledger(path: Path) -> dict:
    rows = {}
    if not path.is_file():
        return rows
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in r:
                rows[r["id"]] = r     # append-only: last state wins
    except OSError:
        pass
    return rows


def worktrees(root: Path) -> list:
    try:
        out = subprocess.run(["git", "worktree", "list", "--porcelain"],
                             cwd=str(root), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    return [Path(l.split(" ", 1)[1].strip())
            for l in out.stdout.splitlines() if l.startswith("worktree ")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=str(SKELETON))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    root = Path(args.repo_root).resolve()
    main_ledger = root / ".prd-os" / "spillover.jsonl"
    main_rows = read_ledger(main_ledger)
    print(f"main ledger: {main_ledger}")
    print(f"  ids present: {len(main_rows)}")

    incoming, sources = {}, {}
    for wt in worktrees(root):
        if wt.resolve() == root:
            continue
        rows = read_ledger(wt / ".prd-os" / "spillover.jsonl")
        for rid, rec in rows.items():
            if rid in main_rows or rid in incoming:
                continue
            incoming[rid] = rec
            sources[rid] = wt.name

    openable = [r for r in incoming.values() if r.get("status") == "open"]
    print(f"\norphan ids not in main: {len(incoming)}  (open: {len(openable)})")
    for rid, rec in list(incoming.items())[:15]:
        print(f"  {rid} [{rec.get('status')}] from {sources[rid]}: "
              f"{(rec.get('description') or '')[:70]}")
    if len(incoming) > 15:
        print(f"  ...and {len(incoming) - 15} more")

    if not incoming:
        print("\nnothing to merge")
        return 0
    if not args.apply:
        print(f"\nDRY RUN. {main_ledger} unchanged "
              f"({main_ledger.stat().st_size if main_ledger.is_file() else 0} bytes).")
        return 0

    main_ledger.parent.mkdir(parents=True, exist_ok=True)
    with main_ledger.open("a") as fh:
        for rid, rec in incoming.items():
            rec = dict(rec)
            # Provenance survives the move. Without it a merged finding looks
            # like it was always here, and the next person cannot tell which
            # ledger it came from or why it was invisible for a month.
            rec["merged_from_worktree"] = sources[rid]
            fh.write(json.dumps(rec) + "\n")
        fh.flush()
    print(f"\nmerged {len(incoming)} record(s) into {main_ledger}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
