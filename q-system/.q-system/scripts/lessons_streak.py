#!/usr/bin/env python3
"""Single writer of the lessons-propagation streak file and escalations ledger.

Issue lr-propagation-streak-escalation (prd-lessons-rail-and-up-rail, plan 3b).
Measured 2026-09-01: `propagate FAILED` on six consecutive logged runs over five
weeks, six identical alarms filed to Sana's queue, no action. The line has to
read differently on night 3 than on night 1, and the escalation has to be a
logged action, not only a Slack.

Why a helper and not three lines of bash (Codex finding-9 on the PRD): the
scheduled run and a manual `kipi lessons-run` can overlap. A read-increment-write
in the shell loses an increment or leaves half a JSON file. Every write here is
a temp file renamed into place under one fcntl lock on a sibling `.lock`, so a
reader never sees a partial file and two writers never both start from the
same count.

Commands (paths through --file / --ledger, defaults are the skeleton's
q-system/output/ files, never touched under pytest without an explicit path):
  bump --outcome fail|ok      prints "<new streak>\t<previous streak>", both from one lock
  read                        current streak (0 when missing or corrupt)
  append-escalation --streak N --threshold T   one row, ledger kept to 200 rows
  summary [--json]            streak + escalation rows of the last 30 days
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent.parent / "output"
DEFAULT_FILE = OUT / "lessons-propagation-streak.json"
DEFAULT_LEDGER = OUT / "lessons-propagation-escalations.jsonl"
LEDGER_KEEP = 200
SUMMARY_DAYS = 30


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")


class _Locked:
    """One lock file per data file; held across read-modify-replace."""

    def __init__(self, path: Path):
        self.lock_path = path.with_name(path.name + ".lock")
        self.fh = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.lock_path, "a+")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def _replace(path: Path, text: str) -> None:
    """Write to a sibling temp file, fsync, rename. Never truncate in place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_streak(path: Path) -> int:
    try:
        return max(0, int(json.loads(path.read_text()).get("streak", 0)))
    except (OSError, ValueError, AttributeError, TypeError):
        return 0


def bump(path: Path, outcome: str) -> tuple[int, int]:
    """Returns (new streak, previous streak), both read inside the one lock.

    The previous value comes from the same locked operation on purpose (Codex
    standard review, issue lr-propagation-streak-escalation): a separate `read`
    before an `ok` bump lets a concurrent failure land in between, so the reset
    clears a newer streak while the log reports the stale number.
    """
    if outcome not in ("fail", "ok"):
        raise SystemExit(f"bump: outcome must be fail or ok, got {outcome!r}")
    with _Locked(path):
        prev = read_streak(path)
        streak = prev + 1 if outcome == "fail" else 0
        _replace(path, json.dumps({"streak": streak, "previous": prev, "updated": _now()}) + "\n")
    return streak, prev


def _rows(ledger: Path):
    good, bad = [], 0
    try:
        lines = ledger.read_text().splitlines()
    except OSError:
        return good, bad
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError
            good.append(row)
        except ValueError:
            bad += 1
    return good, bad


def append_escalation(ledger: Path, streak: int, threshold: int) -> dict:
    row = {"at": _now(), "streak": int(streak), "threshold": int(threshold),
           "action": "escalated: streak line alerted and this row recorded"}
    with _Locked(ledger):
        # Retention works on RAW lines, never on the parsed rows: rewriting only
        # the parseable rows silently deleted every malformed line, so `summary`
        # could never report the count it claims to (Codex standard review,
        # issue lr-escalations-ledger-reader). A bad line stays visible until it
        # ages out of the last LEDGER_KEEP lines.
        try:
            lines = [l for l in ledger.read_text().splitlines() if l.strip()]
        except OSError:
            lines = []
        lines.append(json.dumps(row))
        _replace(ledger, "".join(l + "\n" for l in lines[-LEDGER_KEEP:]))
    return row


def summary(path: Path, ledger: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=SUMMARY_DAYS)
    good, bad = _rows(ledger)
    recent = []
    for row in good:
        try:
            at = datetime.strptime(row["at"], "%Y-%m-%dT%H:%M:%S%z")
        except (KeyError, ValueError, TypeError):
            bad += 1
            continue
        if at >= since:
            recent.append(row)
    return {"streak": read_streak(path), "escalations_30d": len(recent),
            "recent": recent, "malformed_rows": bad}


def summary_line(s: dict) -> str:
    line = f"streak {s['streak']}, {s['escalations_30d']} escalations in {SUMMARY_DAYS}d"
    if s["malformed_rows"]:
        line += f" ({s['malformed_rows']} malformed ledger rows skipped)"
    return line


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bump"); b.add_argument("--outcome", required=True)
    sub.add_parser("read")
    e = sub.add_parser("append-escalation")
    e.add_argument("--streak", type=int, required=True); e.add_argument("--threshold", type=int, required=True)
    s = sub.add_parser("summary"); s.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "bump":
        streak, prev = bump(a.file, a.outcome)
        print(f"{streak}\t{prev}")
    elif a.cmd == "read":
        print(read_streak(a.file))
    elif a.cmd == "append-escalation":
        print(json.dumps(append_escalation(a.ledger, a.streak, a.threshold)))
    elif a.cmd == "summary":
        s_ = summary(a.file, a.ledger)
        print(json.dumps(s_) if a.json else summary_line(s_))
    return 0


if __name__ == "__main__":
    sys.exit(main())
