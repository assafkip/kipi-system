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

PostToolUse on Edit/Write. Exits 2 ONCE per file per day, because the hook
contract is exit 2 = stderr fed to Claude, exit 0 = pass. An exit-0 hook writes
to a stderr nobody reads -- the first version of this file did exactly that and
was inert on arrival, which is the same defect the whole ledger suffered from.

The ask is NOT "fix this". Fixing an adjacent bug mid-task is scope creep and
the repo rules forbid it. The ask is "is this still true?" -- an agent with the
file already open is the cheapest verifier that will ever exist, and a confirm
or a void drains the pile one note at a time without a cleanup day.

Once per file per day, so a file with 17 notes interrupts once, not 17 times
and not on every edit. The marker is a date-stamped file; a new day re-asks,
which is correct for a note that was deferred rather than resolved.

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
ACK_DIR = Path.home() / ".config" / "kipi" / "spillover-ratchet-ack"


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
    # Stem matching only for DISTINCTIVE stems, i.e. ones carrying a separator
    # ("capability-gate", "linear_dor_drafter"). Caught 2026-08-03: matching any
    # stem over 4 chars made README.md fire, because "README" appears in dozens
    # of unrelated descriptions. A ratchet that cries wolf on README is a ratchet
    # someone switches off, and then it protects nothing.
    distinctive = ("-" in stem or "_" in stem) and len(stem) > 4
    spat = re.compile(r"(?<![\w.-])" + re.escape(stem) + r"(?![\w-])") if distinctive else None
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

    # One interruption per file per day. Without this, a file with 17 notes
    # would block every edit 17 times and the hook would be switched off within
    # the hour -- which is how a gate that protects nothing gets created.
    import datetime
    stamp = os.environ.get("KIPI_RATCHET_DATE") or datetime.date.today().isoformat()
    key = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{stamp}-{os.path.basename(target)}")
    ack = ACK_DIR / key
    if ack.exists():
        return 0
    try:
        ACK_DIR.mkdir(parents=True, exist_ok=True)
        ack.write_text("")
    except OSError:
        pass   # an unwritable marker must not turn one note into a loop

    print(f"\n[spillover] {len(hits)} open note(s) about {os.path.basename(target)}.",
          file=sys.stderr)
    print("These were left by whoever last worked here. You have the file open, "
          "so you are the cheapest person to check them.", file=sys.stderr)
    for r in hits[:MAX_SHOWN]:
        print(f"\n  {r['id']} (src {r.get('source')}):\n    "
              f"{(r.get('description') or '')[:260]}", file=sys.stderr)
    if len(hits) > MAX_SHOWN:
        print(f"\n  ...and {len(hits) - MAX_SHOWN} more "
              f"(`prd_runner.py spillover list --open`)", file=sys.stderr)
    print("\n  DO NOT fix them here -- that is scope creep. Decide, and give each "
          "an ADDRESS:\n"
          "    STALE     -> prd_runner.py spillover resolve <id> --void \"<reason>\"\n"
          "    STILL TRUE-> spillover-promote.py <id> --title \"...\" --dor-file <f>\n"
          "                 makes a Linear issue the worker can pick up. It REFUSES\n"
          "                 without allowed-files + acceptance, because an issue\n"
          "                 nothing can work is the queue this all started from.\n"
          "  A confirmed note with no address is just the pile, re-read.\n"
          "  Then continue your task. This fires once per file per day.\n",
          file=sys.stderr)
    return 2     # the ONLY exit code whose stderr reaches the agent


if __name__ == "__main__":
    sys.exit(main())
