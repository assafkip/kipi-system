#!/usr/bin/env python3
"""budget_check: output tokens per merged PR, with caps (ASK-4649).

Reads transcripts through run_tokens.report (one dedup rule, one place) and
divides output tokens by merged PRs. Nothing calls this yet: no hook, nothing
blocking. Exit 2 when --cap-per-pr or --cap-total is crossed, 0 when not, 1 when
it cannot answer. A cap that cannot be evaluated (no PRs to divide by, zero
requests read) is 1, never 0: a budget check that passes because it saw nothing
is the failure this ticket exists to remove.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_tokens  # noqa: E402


def merged_prs(repo: str, since: str) -> int:
    out = subprocess.run(
        ["gh", "pr", "list", "--repo", repo, "--state", "merged", "--search", f"merged:>={since}",
         "--json", "number", "--limit", "1000"],
        capture_output=True, text=True, check=True).stdout
    return len(json.loads(out))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--subagents", action="store_true")
    ap.add_argument("--prs", type=int, help="merged PR count")
    ap.add_argument("--repo")
    ap.add_argument("--since", help="YYYY-MM-DD, with --repo")
    ap.add_argument("--cap-per-pr", type=int)
    ap.add_argument("--cap-total", type=int)
    a = ap.parse_args(argv)
    if a.prs is None and not (a.repo and a.since):
        ap.error("give --prs, or --repo with --since")
    prs = a.prs if a.prs is not None else merged_prs(a.repo, a.since)
    rep = run_tokens.report(a.paths, subagents=a.subagents)
    out = rep["output_tokens"]
    per_pr = out / prs if prs > 0 else None
    result = {"output_tokens": out, "requests": rep["requests"], "merged_prs": prs,
              "output_tokens_per_pr": per_pr, "cap_per_pr": a.cap_per_pr, "cap_total": a.cap_total,
              "unreadable": rep["unreadable"], "over": []}
    rc = 0
    if rep["requests"] == 0 or rep["unreadable"]:
        rc = 1
    if a.cap_per_pr is not None:
        if per_pr is None:
            rc = 1
        elif per_pr > a.cap_per_pr:
            result["over"].append("per_pr")
    if a.cap_total is not None and out > a.cap_total:
        result["over"].append("total")
    if result["over"] and rc == 0:
        rc = 2
    print(json.dumps(result))
    return rc


if __name__ == "__main__":
    sys.exit(main())
