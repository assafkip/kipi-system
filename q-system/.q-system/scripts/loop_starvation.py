#!/usr/bin/env python3
"""loop_starvation.py -- one alarm for a loop that runs, exits 0 and has no input.

ASK-3402. The weekly learning pass logged "nothing this week" while both of its
producers had no caller, and lessons-daily would print scanned 0 forever the
same way. A starved loop exits 0, so no failure detector sees it.

Usage:  loop_starvation.py record <loop> <input_count> [--threshold N]

Each call appends ONE row {loop, at, inputs, alerted} to an append-only jsonl.
When the trailing run of rows for that loop with inputs == 0 reaches the
threshold (default 3, env KIPI_STARVATION_THRESHOLD or --threshold) and no row
of that run has alerted, ONE alert goes out through slack-notify.sh (the fleet
alert path: it files a Linear ticket for Sana and pages nobody). The row is
stamped alerted=true only when the notifier exited 0, so a failed filing is
retried on the next zero run instead of being lost. A non-zero run ends the
streak, so the next starvation alerts again: state change only, once.

Emitter named (named-emitter.md): this script is the emitter of the
"starved" alert text, through q-system/.q-system/scripts/slack-notify.sh.

Single writer: the append and the streak read happen under one flock, so two
loops recording at once cannot interleave a row or both claim the alert.

Env (tests set all three; none may point at a live path under pytest):
  KIPI_STARVATION_LEDGER  jsonl path (default q-system/output/loop-starvation.jsonl)
  KIPI_STARVATION_NOTIFY  notifier command (default slack-notify.sh beside this file)
  KIPI_STARVATION_THRESHOLD  default 3
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
QROOT = HERE.parent.parent
DEFAULT_THRESHOLD = 3


def ledger_path() -> Path:
    return Path(os.environ.get("KIPI_STARVATION_LEDGER", QROOT / "output" / "loop-starvation.jsonl"))


def notifier() -> list:
    raw = os.environ.get("KIPI_STARVATION_NOTIFY")
    return ["bash", "-c", raw + ' "$1"', "notify"] if raw else ["bash", str(HERE / "slack-notify.sh")]


def _rows(path: Path, loop: str) -> list:
    out = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a torn line must not stop the alarm
            if isinstance(row, dict) and row.get("loop") == loop:
                out.append(row)
    return out


def _streak(rows: list) -> list:
    """The trailing run of zero-input rows (empty when the last run had input)."""
    run = []
    for row in reversed(rows):
        if row.get("inputs") != 0:
            break
        run.append(row)
    return run


def record(loop: str, inputs: int, threshold: int, path: Path = None, now: dt.datetime = None) -> dict:
    path = path or ledger_path()
    now = now or dt.datetime.now().astimezone()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            row = {"loop": loop, "at": now.isoformat(timespec="seconds"), "inputs": int(inputs), "alerted": False}
            run = _streak(_rows(path, loop) + [row])
            fire = len(run) >= threshold and not any(r.get("alerted") for r in run[1:])  # run is newest first
            if fire:
                msg = (f"loop starved: {loop} had zero input for {len(run)} runs in a row "
                       f"(since {run[-1]['at']}). It exits 0, so nothing else flags it. "
                       f"Emitter: loop_starvation.py via slack-notify.sh")
                p = subprocess.run(notifier() + [msg], capture_output=True, text=True)
                row["alerted"] = p.returncode == 0
                if p.returncode != 0:
                    print(f"loop_starvation: notifier rc={p.returncode}: {p.stderr[-200:]}", file=sys.stderr)
            fh.write(json.dumps(row) + "\n")
            fh.flush()
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    return {"loop": loop, "streak": len(run), "alerted": row["alerted"], "fired": fire}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("loop")
    r.add_argument("inputs", type=int)
    r.add_argument("--threshold", type=int, default=None)
    a = ap.parse_args(argv)
    thr = a.threshold or int(os.environ.get("KIPI_STARVATION_THRESHOLD", DEFAULT_THRESHOLD))
    print(json.dumps(record(a.loop, a.inputs, thr)))
    return 0  # an alarm helper never fails the job it watches


if __name__ == "__main__":
    raise SystemExit(main())
