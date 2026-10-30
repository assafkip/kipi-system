#!/usr/bin/env python3
"""weekly-improve.py -- the weekly pass over the friction ledger and the
skill-proposals inbox. One Slack message to the founder, through
slack_founder.deliver, never through the fleet alert path (the shell notifier
that files a Linear ticket for Sana and sends nothing to Slack; Phase 1
learned that, and test_weekly_improve.py greps this file for its name).

Plan items 2b + 2l of prd-morning-brief-learns-2026-09-01. Its trigger is
weekly-improve.sh under com.kipi.weekly-improve.plist (issue
mbl-weekly-improve-runner); this file never schedules itself.

Three rules, each with a failing input in test_weekly_improve.py:

1. EMPTY IS NOT BROKEN, AND A MISSING INPUT IS NOT A QUIET WEEK (ASK-3402).
   An unreadable or malformed file renders COULD NOT READ. A file that does
   not exist renders "input missing, no <file> exists"; an empty one "input
   empty"; rows all older than the window name the last row's date. "nothing
   this week" is no longer printed for a starved input: on 2026-10-26 the only
   run said it while both producers had no caller.
2. THE ROADMAP BOUNDARY IS A GATE HERE TOO. Every line is re-classified at
   read time with roadmap_scope (Codex finding-1: a line that reached the file
   with a declared system target is not trusted). roadmap and unknown are
   refused and counted, never proposed. `is_refused()` is the contract the
   paraphrase suite (test_roadmap_scope_suite.py) holds every consumer to.
3. NEVER THE WHOLE LINE. A proposal cites the line's id and a 60-character
   excerpt with email addresses masked (Codex finding-18: friction can carry
   client data). The verbatim line stays in the instance-owned file.

Scope boundary: this pass may propose a fix to a stage, a skill for manual
work, a rule/lint/prompt change, or a context entry. It never proposes what to
build, sell or publish. That is the hard constraint of the plan's first
amendment, wired into the done gate rather than stated as intent.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
QROOT = HERE.parent.parent  # scripts -> .q-system -> q-system
FRICTION_FILE = Path(os.environ.get("KIPI_FRICTION_FILE", QROOT / "memory" / "friction.jsonl"))
INBOX_DIR = Path(os.environ.get("KIPI_PROPOSALS_INBOX", QROOT / "output" / "skill-proposals" / "_inbox"))
EXCERPT_CHARS = 60
WINDOW_DAYS = 7
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def in_window(row: dict, now: dt.datetime, days: int = WINDOW_DAYS) -> bool:
    """A row is proposed once, in the week it was written (Codex adversarial
    finding on this issue: an append-only ledger read whole re-delivers every
    old line every week, and can never render "nothing this week"). The writer
    always stamps `at`; a row with no parseable `at` is treated as in-window so
    a hand-edited line surfaces rather than vanishing."""
    raw = row.get("at")
    if not raw:
        return True
    try:
        when = dt.datetime.fromisoformat(str(raw))
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=now.tzinfo)
    return (now - when) <= dt.timedelta(days=days)


def _load_sibling(stem: str, filename: str):
    path = HERE / filename
    spec = importlib.util.spec_from_file_location(stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def is_refused(text: str, declared_target) -> bool:
    """The consumer contract: True unless roadmap_scope says `system`."""
    scope = _load_sibling("roadmap_scope", "roadmap_scope.py")
    return scope.classify(text, declared_target)["verdict"] != "system"


def read_friction(path=None):
    """(rows, error). Missing or empty is ([], None); unreadable or malformed
    is ([], "<why>"). Those are different facts and render differently."""
    path = Path(path) if path else FRICTION_FILE
    if not path.exists():
        return [], None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], f"{type(exc).__name__}: {exc}"
    rows = []
    for n, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            return [], f"line {n} is not JSON ({exc})"
        if not isinstance(row, dict) or "id" not in row or "text" not in row:
            return [], f"line {n} lacks id/text"
        rows.append(row)
    return rows, None


def mask(text: str) -> str:
    return _EMAIL.sub("[email]", text)


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    masked = mask(" ".join(text.split()))
    return masked if len(masked) <= limit else masked[: limit - 3].rstrip() + "..."


def propose(rows: list) -> tuple:
    """(proposal_lines, refused_ids). Each proposal cites id + excerpt only."""
    proposals, refused = [], []
    for row in rows:
        if is_refused(str(row.get("text", "")), row.get("target")):
            refused.append(str(row.get("id")))
            continue
        proposals.append(f"{row['id']} [{row.get('target', '?')}]: \"{excerpt(str(row['text']))}\"")
    return proposals, refused


def read_inbox(inbox=None):
    inbox = Path(inbox) if inbox else INBOX_DIR
    if not inbox.is_dir():
        return [], None
    try:
        files = sorted(p.name for p in inbox.iterdir() if p.suffix == ".md")
    except OSError as exc:
        return [], f"{type(exc).__name__}: {exc}"
    return files, None


def _day(raw) -> str:
    return str(raw)[:10]


def input_count(friction_path=None, inbox=None, now=None, days: int = WINDOW_DAYS) -> int:
    """In-window friction rows plus inbox files: the number loop_starvation.py
    records per run. An unreadable input counts 0 and is already degraded."""
    now = now or dt.datetime.now().astimezone()
    rows, _ = read_friction(friction_path)
    files, _ = read_inbox(inbox)
    return len([r for r in rows if in_window(r, now, days)]) + len(files)


def build(friction_path=None, inbox=None, now=None, days: int = WINDOW_DAYS) -> tuple:
    """(message, degraded)."""
    now = now or dt.datetime.now().astimezone()
    all_rows, error = read_friction(friction_path)
    lines = ["*Weekly improve*", ""]
    degraded = False
    if error:
        lines += ["*Friction*", f"  COULD NOT READ: {error}"]
        degraded = True
    else:
        rows = [r for r in all_rows if in_window(r, now, days)]
        older = len(all_rows) - len(rows)
        proposals, refused = propose(rows)
        lines.append("*Friction*")
        fpath = Path(friction_path) if friction_path else FRICTION_FILE
        if not fpath.exists():
            lines.append(f"  Friction: input missing, no {fpath.name} exists (nothing has ever written one)")
        elif not all_rows:
            lines.append(f"  Friction: input empty, {fpath.name} has no rows")
        elif not rows:
            last = max(_day(r.get("at", "")) for r in all_rows)
            lines.append(f"  Friction: no new rows in {days} days, last row {last}")
        else:
            lines += [f"  {p}" for p in proposals] or ["  nothing proposable this week"]
            if refused:
                lines.append(f"  refused {len(refused)} line(s) outside system scope: {', '.join(refused)}")
        if older:
            lines.append(f"  ({older} older line(s) not re-sent)")
    files, ierr = read_inbox(inbox)
    lines += ["", "*Skill proposals inbox*"]
    if ierr:
        lines.append(f"  COULD NOT READ: {ierr}")
        degraded = True
    elif not files:
        idir = Path(inbox) if inbox else INBOX_DIR
        if not idir.is_dir():
            lines.append("  Skill proposals inbox: input missing, no inbox directory exists")
        else:
            stamps = [p.stat().st_mtime for p in idir.iterdir() if p.is_file()]
            last = dt.datetime.fromtimestamp(max(stamps), dt.timezone.utc).strftime("%Y-%m-%d") if stamps else None
            lines.append(f"  Skill proposals inbox: input empty, last file {last}" if last
                         else "  Skill proposals inbox: input empty, no file has ever landed")
    else:
        lines += [f"  {f}" for f in files]
    return "\n".join(lines), degraded


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="weekly pass over friction + proposals inbox")
    ap.add_argument("--dry-run", action="store_true", help="print, send nothing")
    ap.add_argument("--friction", default=None, help="override the friction ledger path")
    ap.add_argument("--inbox", default=None, help="override the proposals inbox dir")
    ap.add_argument("--count-inputs", action="store_true", help="print the run's input count, send nothing")
    args = ap.parse_args(argv)
    if args.count_inputs:
        # An unreadable input is not starvation: exit 1 with no number so the
        # caller records nothing (PR #572 review, minor).
        _, ferr = read_friction(args.friction)
        _, ierr = read_inbox(args.inbox)
        if ferr or ierr:
            print(ferr or ierr, file=sys.stderr)
            return 1
        print(input_count(args.friction, args.inbox))
        return 0
    message, degraded = build(args.friction, args.inbox)
    print(message)
    if args.dry_run:
        print("\n[dry-run] nothing sent")
        return 1 if degraded else 0
    sender = _load_sibling("slack_founder", "slack_founder.py")
    result = sender.deliver(message)
    print(f"\n[send] {json.dumps(result)}")
    if not result.get("delivered"):
        return 1
    return 1 if degraded else 0


if __name__ == "__main__":
    raise SystemExit(main())
