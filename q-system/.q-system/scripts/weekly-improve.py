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

1. EMPTY IS NOT BROKEN. No friction file, or an empty one, renders
   "nothing this week". An unreadable or malformed one renders COULD NOT READ.
   The two strings differ (a-zero-result-must-prove-it-is-empty-not-broken).
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
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


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


def build(friction_path=None, inbox=None) -> tuple:
    """(message, degraded)."""
    rows, error = read_friction(friction_path)
    lines = ["*Weekly improve*", ""]
    degraded = False
    if error:
        lines += ["*Friction*", f"  COULD NOT READ: {error}"]
        degraded = True
    else:
        proposals, refused = propose(rows)
        lines.append("*Friction*")
        if not rows:
            lines.append("  nothing this week")
        else:
            lines += [f"  {p}" for p in proposals] or ["  nothing proposable this week"]
            if refused:
                lines.append(f"  refused {len(refused)} line(s) outside system scope: {', '.join(refused)}")
    files, ierr = read_inbox(inbox)
    lines += ["", "*Skill proposals inbox*"]
    if ierr:
        lines.append(f"  COULD NOT READ: {ierr}")
        degraded = True
    elif not files:
        lines.append("  nothing this week")
    else:
        lines += [f"  {f}" for f in files]
    return "\n".join(lines), degraded


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="weekly pass over friction + proposals inbox")
    ap.add_argument("--dry-run", action="store_true", help="print, send nothing")
    ap.add_argument("--friction", default=None, help="override the friction ledger path")
    ap.add_argument("--inbox", default=None, help="override the proposals inbox dir")
    args = ap.parse_args(argv)
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
