#!/usr/bin/env python3
"""Surface a minor spillover finding at the moment someone edits its file (ASK-343).

why: 510 of 532 open findings are `minor`. They are real, but they are not a
queue -- nobody will ever sit down and work a 510-item list, and after ASK-341
they no longer block the gate. So they had no delivery mechanism at all, which
makes keeping them identical to deleting them.

This gives them one. A minor finding is a note left for THE NEXT PERSON TO TOUCH
THIS FILE. So it fires then, and only then.

Same shape as portability-lint.sh, which sp-db43af2f documents: wired as a
RATCHET on the file being edited, so pre-existing findings surface when a file
is next touched rather than turning a gate red on items nobody is working on
today.

Consequence, deliberately: a finding about a file nobody ever touches again
never fires. That is correct. If the file is dead, the finding was too.

PostToolUse on Edit/Write. Advisory only -- exit 0 always. A note is not a
blocker; it is context delivered at the one moment it is useful.

Usage (hook): reads the tool payload on stdin.
Usage (manual): spillover-ratchet.py <path>
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
SKELETON = HERE.parents[3]
MAX_SHOWN = 3


def ledger_rows(root: Path) -> list:
    """Open MINOR findings only. Blocking ones go through the gate, not here."""
    p = root / ".prd-os" / "spillover.jsonl"
    if not p.is_file():
        return []
    rows = {}
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "id" in r:
                    rows[r["id"]] = r
    except OSError:
        return []
    return [r for r in rows.values()
            if r.get("status") == "open"
            and (r.get("severity") or "minor").lower() == "minor"]


def repo_root_for(path: Path) -> Path:
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             cwd=str(path.parent if path.is_file() else path),
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return SKELETON


def findings_for(filename: str, rows: list) -> list:
    """Findings whose text names this file.

    Matches the BASENAME, not the full path: a finding written from another
    checkout names `capability-gate.py`, not the path you happen to be editing
    it through. Word-boundary anchored so `gate.py` does not match
    `capability-gate.py`.
    """
    base = os.path.basename(filename)
    if not base or len(base) < 4:
        return []
    pat = re.compile(r"(?<![\w/-])" + re.escape(base) + r"(?![\w])")
    stem = os.path.splitext(base)[0]
    spat = re.compile(r"(?<![\w.-])" + re.escape(stem) + r"(?![\w-])") if len(stem) > 4 else None
    hits = []
    for r in rows:
        d = r.get("description", "") or ""
        if pat.search(d) or (spat and spat.search(d)):
            hits.append(r)
    return hits


def main() -> int:
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        try:
            payload = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            return 0
        target = (payload.get("tool_input") or {}).get("file_path") or ""
    if not target:
        return 0

    p = Path(target)
    rows = ledger_rows(repo_root_for(p))
    hits = findings_for(target, rows)
    if not hits:
        return 0

    print(f"\n[spillover] {len(hits)} open note(s) about {os.path.basename(target)}:",
          file=sys.stderr)
    for r in hits[:MAX_SHOWN]:
        print(f"  {r['id']} (src {r.get('source')}): "
              f"{(r.get('description') or '')[:200]}", file=sys.stderr)
    if len(hits) > MAX_SHOWN:
        print(f"  ...and {len(hits) - MAX_SHOWN} more", file=sys.stderr)
    print("  Fix it now, or `prd_runner.py spillover resolve <id> --void \"<reason>\"` "
          "if it is stale.\n", file=sys.stderr)
    return 0     # advisory, never blocks


if __name__ == "__main__":
    sys.exit(main())
