#!/usr/bin/env python3
"""Would this spillover row have qualified as a small adjacent fix? (ASK-2014)

WHY THIS EXISTS. `no-orphan-findings.md` says a medium-and-up finding is CAPTURED,
never fixed in passing, and `prd_runner.py` enforces it at the door
(SPILLOVER_REFUSED_SEVERITIES refuses minor/low/nit, founder-approved
RULE-2026-09-12-A). The open question is whether some of what the workers file
would have been cheaper fixed in place. That is a founder decision about the rule,
and it was blocked on having no number under it. This script is the number.

IT CHANGES NOTHING. No hook, no settings entry, no schedule. It reads the ledger
and git history and prints. The worker keeps filing exactly as it does now.

THREE GATES, each decided and reported separately:

  G1 severity   row severity at or below `medium`, ranked by prd-os's own
                SPILLOVER_SEVERITY_ORDER (derived, never restated here)
  G2 adjacency  a path named in the row's description is in the changed-file set
                of the issue named in the row's `source`
  G3 size       the resolution commit's changed-line count is under --max-lines

VERDICTS ARE THREE-WAY ON PURPOSE. A row nobody has fixed carries no patch, so its
size is not a small number and not a large one -- it is unmeasured. Measured
2026-09-29 against the founder's live ledger: 1,780 rows after last-write-wins,
of which 20 carry a `resolution_commit`. Folding "unmeasured" into either answer
would invent the number this script exists to produce, so UNDECIDABLE is a
first-class verdict and the funnel below TOTAL reports each gate's own pass count.

THE CAP IS A PARAMETER, NOT A POLICY. --max-lines defaults to 20 and is printed in
the header. Nothing in the repo blesses 20; re-run with another number and the
split moves. Picking the number is the founder's call, which is exactly what this
script is meant to inform.
"""

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNNER = ROOT / "plugins/prd-os/scripts/prd_runner.py"
DEFAULT_LEDGER = ".prd-os/spillover.jsonl"

# An extension list, not a heuristic: a token only counts as a path if it ends in
# one of the suffixes this repo actually contains. "the worker filed a ticket" has
# no filename in it and must yield nothing.
PATH_RE = re.compile(
    r"[A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:py|sh|md|json|jsonl|yml|yaml|html|js|txt|plist)\b"
)
ISSUE_RE = re.compile(r"\b([A-Z]{2,5}-\d+)\b")


def severity_order(runner_path=None):
    """Read SPILLOVER_SEVERITY_ORDER out of prd_runner.py without executing it.

    DERIVED, NOT RESTATED (lessons: derive-a-value-from-its-owner). A copy of the
    tuple typed here would agree on the day it was written and keep agreeing after
    prd-os changed it, so the severity gate would go on enforcing the old contract
    while reading as green. Parsed with `ast` rather than imported because
    prd_runner.py is a 3,000-line module and this script needs one constant.

    prd_runner.py currently assigns the name TWICE with identical values (lines
    2813 and 2817). Python's last assignment wins, so this takes the last one
    rather than the first, which is the only reading that cannot disagree with the
    module it is deriving from.
    """
    path = Path(runner_path) if runner_path else DEFAULT_RUNNER
    if not path.is_file():
        raise SystemExit(
            f"cannot derive the severity order: {path} is absent. This script "
            "refuses to fall back on a hand-typed copy, because a copy is how the "
            "gate silently starts enforcing an old contract."
        )
    found = None
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id == "SPILLOVER_SEVERITY_ORDER":
                found = tuple(ast.literal_eval(node.value))
    if not found:
        raise SystemExit(
            f"SPILLOVER_SEVERITY_ORDER not found in {path}; the derivation has "
            "broken and an empty order would make the severity gate a no-op."
        )
    return found


def collapse_rows(lines):
    """Last-write-wins per id: the append-only ledger's own read semantics
    (prd_runner.py `_read_spillover`). Without it a resolved row is counted twice,
    once in each of its states."""
    by = {}
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        rid = rec.get("id")
        if rid:
            by[rid] = rec
    return list(by.values())


def extract_paths(text):
    """Every path-like token in a description, plus the tail of a slash-joined
    list. Descriptions are prose, so this is best-effort by construction -- a row
    naming no file yields nothing and is reported UNDECIDABLE rather than guessed.
    """
    out = set()
    for m in PATH_RE.finditer(text or ""):
        tok = m.group(0)
        out.add(tok)
        # "say.md/say-play.sh/say-last-response.py" is a list, not a path; the
        # segments are what a reader means. Keep the whole token too, since a real
        # path is also a slash-joined string.
        for seg in tok.split("/"):
            if PATH_RE.fullmatch(seg):
                out.add(seg)
    return out


def changed_files_by_issue(repo_root):
    """issue id -> set of files its commits touched, from git history.

    ONE git pass over --all, not one per row: 1,289 distinct sources would
    otherwise be 1,289 subprocesses. Records are \\x1e-separated, fields
    \\x1f-separated, so a commit body containing blank lines cannot desync the
    parse the way a newline-delimited format does.
    """
    p = subprocess.run(
        ["git", "log", "--all", "--name-only",
         "--pretty=format:%x1e%H%x1f%B%x1f"],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    if p.returncode != 0:
        return {}
    out = {}
    for rec in p.stdout.split("\x1e"):
        if not rec.strip():
            continue
        parts = rec.split("\x1f")
        if len(parts) < 3:
            continue
        body, files_block = parts[1], parts[2]
        files = {ln.strip() for ln in files_block.splitlines() if ln.strip()}
        if not files:
            continue
        for iid in set(ISSUE_RE.findall(body)):
            out.setdefault(iid, set()).update(files)
    return out


def commit_line_count(repo_root, sha):
    """Added + deleted lines for one commit, or None when the sha is not here.

    None is not zero. A sha from another checkout must read as unmeasured, because
    treating an unresolvable commit as a 0-line patch would classify it as the
    smallest possible fix -- the exact wrong direction for a gate that decides
    whether something was small enough to do in passing.
    """
    p = subprocess.run(
        ["git", "show", "--numstat", "--format=", sha],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    if p.returncode != 0:
        return None
    total = 0
    for ln in p.stdout.splitlines():
        cols = ln.split("\t")
        if len(cols) != 3:
            continue
        for c in cols[:2]:
            if c.isdigit():
                total += int(c)
    return total


def _adjacency(row, changed_map):
    """(state, detail). state is 'path', 'basename', 'outside' or 'unknown'."""
    paths = extract_paths(row.get("description") or "")
    if not paths:
        return "unknown", "no path named in the description"
    changed = changed_map.get((row.get("source") or "").strip())
    if not changed:
        return "unknown", f"no commits found for source {row.get('source')!r}"
    for cand in sorted(paths):
        if cand in changed or any(c.endswith("/" + cand) for c in changed):
            return "path", cand
    bases = {c.rsplit("/", 1)[-1] for c in changed}
    for cand in sorted(paths):
        if cand.rsplit("/", 1)[-1] in bases:
            return "basename", cand.rsplit("/", 1)[-1]
    return "outside", sorted(paths)[0]


def classify(row, changed_map, max_lines, size_lookup, order):
    """(verdict, reason). FILE_TICKET beats UNDECIDABLE: a gate that DECIDED no is
    an answer, and an unmeasured later gate cannot take it back."""
    rank = {s: i for i, s in enumerate(order)}
    sev = (row.get("severity") or "minor").strip().lower()
    if sev not in rank:
        return "UNDECIDABLE", f"severity {sev!r} is not in prd-os's severity order"
    if rank[sev] > rank["medium"]:
        return "FILE_TICKET", f"severity {sev} is above medium"

    state, detail = _adjacency(row, changed_map)
    if state == "outside":
        return "FILE_TICKET", f"not adjacent: {detail} is outside the changed files"
    if state == "unknown":
        return "UNDECIDABLE", f"adjacency undecidable: {detail}"

    sha = row.get("resolution_commit")
    if not sha:
        return "UNDECIDABLE", (
            f"adjacent:{state} ({detail}) but size unmeasured: the row carries no "
            "resolution_commit, so there is no patch to count")
    n = size_lookup.get(sha) if isinstance(size_lookup, dict) else None
    if n is None:
        return "UNDECIDABLE", (
            f"adjacent:{state} ({detail}) but size unmeasured: commit {sha} does "
            "not resolve here")
    if n > max_lines:
        return "FILE_TICKET", f"size {n} lines is over the cap of {max_lines}"
    return "FIX_IN_PLACE", f"severity {sev}, adjacent:{state} ({detail}), {n} lines"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", default=DEFAULT_LEDGER,
                    help=f"spillover ledger to read (default: {DEFAULT_LEDGER})")
    ap.add_argument("--repo-root", default=str(Path.cwd()),
                    help="repo whose history supplies the changed-file sets")
    ap.add_argument("--max-lines", type=int, default=20,
                    help="the line cap a patch must be under (default: 20)")
    ap.add_argument("--limit", type=int, default=0,
                    help="print at most N rows (0 = all); the TOTAL covers the "
                         "rows printed, so a limited run says so")
    args = ap.parse_args(argv)

    ledger = Path(args.ledger)
    if not ledger.is_file():
        # Absent is not empty. Printing a 0/0 split here would read as "nothing
        # qualifies" when the truth is "nothing was read" -- the silent-absence
        # class the capability gate exists to make loud.
        print(f"NO LEDGER: {ledger} does not exist. This worktree has no "
              "spillover ledger to replay (.prd-os/spillover.jsonl is gitignored, "
              "so it is never in a fresh checkout). Point --ledger at a checkout "
              "that has one.", file=sys.stderr)
        return 2

    repo_root = Path(args.repo_root).resolve()
    order = severity_order()
    rows = collapse_rows(ledger.read_text().splitlines())
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    if args.limit:
        rows = rows[: args.limit]

    changed_map = changed_files_by_issue(repo_root)
    sizes = {}
    for r in rows:
        sha = r.get("resolution_commit")
        if sha and sha not in sizes:
            sizes[sha] = commit_line_count(repo_root, sha)

    print(f"LEDGER {ledger} rows={len(rows)} (last-write-wins) "
          f"cap={args.max_lines} lines repo={repo_root}")
    print(f"HISTORY {len(changed_map)} issue ids carry changed files")

    counts = {"FIX_IN_PLACE": 0, "FILE_TICKET": 0, "UNDECIDABLE": 0}
    sev_pass = adj_pass = size_measured = 0
    rank = {s: i for i, s in enumerate(order)}
    for r in rows:
        v, why = classify(r, changed_map, args.max_lines, sizes, order)
        counts[v] = counts.get(v, 0) + 1
        sev = (r.get("severity") or "minor").strip().lower()
        if sev in rank and rank[sev] <= rank["medium"]:
            sev_pass += 1
            if _adjacency(r, changed_map)[0] in ("path", "basename"):
                adj_pass += 1
                if sizes.get(r.get("resolution_commit")) is not None:
                    size_measured += 1
        # The "ROW " prefix is load-bearing, not decoration. Real ids are not all
        # `sp-`-shaped: 5 of the 13 committed fixtures start with `defer-`, written
        # by the deferred-finding auto-capture path. A reader keying off the id
        # prefix silently drops those, which is how the first run of this replay
        # counted 8 rows out of 13 and still exited 0.
        print(f"ROW {r.get('id')} {v} [{r.get('severity')}] {r.get('source')}: {why}")

    print(f"TOTAL rows={len(rows)} "
          f"FIX_IN_PLACE={counts['FIX_IN_PLACE']} "
          f"FILE_TICKET={counts['FILE_TICKET']} "
          f"UNDECIDABLE={counts['UNDECIDABLE']}")
    # The funnel is the founder-facing number: a ceiling, then what is measurable
    # inside it. Read the last figure narrowly -- it is the measured subset, not an
    # estimate of the rest.
    print(f"FUNNEL severity<=medium={sev_pass} "
          f"of-those-adjacent={adj_pass} "
          f"of-those-with-a-measurable-patch={size_measured} "
          f"of-those-under-{args.max_lines}-lines={counts['FIX_IN_PLACE']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
