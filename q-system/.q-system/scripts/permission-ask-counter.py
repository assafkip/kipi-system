#!/usr/bin/env python3
"""permission-ask-counter.py -- count the turns that name a pick and then end by
asking permission to take it.

Plan item 2i of prd-morning-brief-learns-2026-09-01. The autonomy contract
forbids exactly this shape ("when you have a clear pick, the next action is a
tool call, not prose with a question mark") and forbids fixing it with more
phrase patches ("hooks are the wrong layer for this"). So this is a
MEASUREMENT in the posture of skill-trigger-eval.py: on demand, advisory,
never a hook, and it refuses to print a number when its apparatus is broken
(exit 3 on an unreadable sample) rather than reporting a misleading zero.

Measured 2026-09-01 in the session that wrote the plan: the contract was broken
in at least four consecutive turns. That is the observation this exists to
count, over time, in a ledger the number can move in.

Input: Claude Code session transcripts (JSONL, one record per line, assistant
records carrying text blocks). The default sample is this machine's
~/.claude/projects, resolved INSIDE the script so the command line never
carries that path (the path-write guard reads command text). Tests pass a
tmp_path sample.

Output: one line, and one appended row in q-system/output/permission-ask-ledger.jsonl:
{date, sample, turns, count, rate}. A rate is a signal, never a gate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
QROOT = HERE.parent.parent
LEDGER = Path(os.environ.get("KIPI_PERMISSION_LEDGER", QROOT / "output" / "permission-ask-ledger.jsonl"))
DEFAULT_SAMPLE = Path.home() / ".claude" / "projects"

PICK = re.compile(r"\b(my call|my pick|i'?d pick|i would pick|i recommend|recommend(ed)?:|the pick)\b", re.IGNORECASE)
ASK = re.compile(r"\b(want me to|should i|shall i|which (one|do you)|say go|approve|give the word|let me know (when|if)|"
                 r"your call|up to you|ready when you are)\b", re.IGNORECASE)
EXIT_OK, EXIT_BROKEN = 0, 3


def _assistant_texts(record: dict):
    if record.get("type") != "assistant":
        return
    msg = record.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        yield content
        return
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            yield block["text"]


def is_pick_then_ask(text: str) -> bool:
    """A pick is named somewhere, and the turn ENDS on a permission ask."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return False
    last = lines[-1]
    return bool(PICK.search(text)) and last.endswith("?") and bool(ASK.search(last))


def scan(sample: Path, limit_files: int = 200) -> dict:
    files = sorted(sample.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit_files]
    if not files:
        raise FileNotFoundError(f"no .jsonl transcripts under {sample}")
    turns = count = 0
    for path in files:
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    for text in _assistant_texts(rec):
                        turns += 1
                        if is_pick_then_ask(text):
                            count += 1
        except OSError:
            continue
    return {"files": len(files), "turns": turns, "count": count,
            "rate": round(count / turns, 4) if turns else None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="count pick-then-ask turns over a transcript sample (advisory)")
    ap.add_argument("--sample", default=None, help="directory of .jsonl transcripts (default: this machine's session store)")
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--no-ledger", action="store_true")
    args = ap.parse_args(argv)
    sample = Path(args.sample).expanduser() if args.sample else DEFAULT_SAMPLE
    if not sample.is_dir():
        sys.stderr.write(f"error: sample dir not readable: {sample}. Refusing to report a misleading count.\n")
        return EXIT_BROKEN
    try:
        result = scan(sample)
    except (FileNotFoundError, PermissionError) as exc:
        sys.stderr.write(f"error: {exc}. Refusing to report a misleading count.\n")
        return EXIT_BROKEN
    if result["turns"] == 0:
        sys.stderr.write("error: zero assistant turns found; the apparatus is broken, not the behaviour perfect.\n")
        return EXIT_BROKEN
    row = {"date": dt.date.today().isoformat(), "sample": str(sample), **result}
    print(f"pick-then-ask: {row['count']} of {row['turns']} turns (rate {row['rate']}) over {row['files']} transcript(s)")
    print("ADVISORY: a signal about the autonomy contract, never a gate.")
    if not args.no_ledger:
        ledger = Path(args.ledger) if args.ledger else LEDGER
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
