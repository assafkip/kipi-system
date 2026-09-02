#!/usr/bin/env python3
"""What a declared hub instance has that the skeleton lacks, once a week.

Issues lr-drift-reporter and lr-drift-trigger-proof (prd-lessons-rail-and-up-rail,
plan 4c). Measured 2026-09-01: eight lessons existed only in consulting for
three weeks and nothing said so. This says so, every Monday 06:45, through
slack_founder.deliver (founder-facing), never the fleet alert path.

Resolution (Codex finding-13 on the PRD): the skeleton is the registry's
`skeleton` entry and it MUST be this file's own repo root, otherwise the
report says `skeleton: COULD NOT READ` (a worktree never reports as the
skeleton). Hubs are the registry NAMES in q-system/.q-system/drift-hubs.json;
a name the registry does not hold renders COULD NOT READ for that hub. launchd
passes nothing; the plist template sets KIPI_TRIGGER=launchd.

Delivery (Codex finding-7): the report is delivered only under
KIPI_TRIGGER=launchd, which only the plist sets. Run by hand it prints and
sends nothing, so removing the plist provably stops delivery; --dry-run
prints only, whatever the trigger.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.realpath(os.path.join(HERE, "..", "..", ".."))
HUBS_REL = "q-system/.q-system/drift-hubs.json"
LESSONS_REL = "q-system/lessons"
SCRIPTS_REL = "q-system/.q-system/scripts"
COULD_NOT_READ = "COULD NOT READ"


def _load(name, filename):
    # no bytecode: a __pycache__/lessons_streak.*.pyc beside the helper would
    # match the single-writer grep in test_lessons_daily_streak.py
    # (restored afterwards: the flag is process-global and an embedding caller,
    # pytest included, keeps its own setting; Codex adversarial, issue 13)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = previous
    return mod


def _digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _files(root, rel, pattern):
    base = os.path.join(root, rel)
    if not os.path.isdir(base):
        raise OSError(f"{base} is not a directory")
    out = {}
    for p in glob.glob(os.path.join(base, pattern)):
        if os.path.isfile(p) and os.path.basename(p) != "README.md":
            out[rel + "/" + os.path.basename(p)] = _digest(p)
    return out


def resolve(root):
    """(skeleton_ok, hubs) where hubs is [(name, path or None)]."""
    root = os.path.realpath(root)
    registry_path = os.path.join(root, "instance-registry.json")
    try:
        registry = json.loads(open(registry_path, encoding="utf-8").read())
    except (OSError, ValueError):
        return False, []
    raw = (registry.get("skeleton") or {}).get("path")
    # the RAW value is checked before realpath: realpath("") is the cwd, which
    # would pass whenever the reporter runs from its own root (Codex, issue 13)
    skeleton_ok = isinstance(raw, str) and bool(raw.strip()) and os.path.realpath(raw) == root
    try:
        names = json.loads(open(os.path.join(root, HUBS_REL), encoding="utf-8").read()).get("hubs", [])
    except (OSError, ValueError):
        names = []
    by_name = {e.get("name"): e.get("path") for e in registry.get("instances", [])}
    return skeleton_ok, [(n, by_name.get(n)) for n in names]


def drift(hub_root, skel_root):
    """Paths present in the hub and absent from or different in the skeleton."""
    hub = {}
    hub.update(_files(hub_root, LESSONS_REL, "*.md"))
    hub.update(_files(hub_root, SCRIPTS_REL, "*"))
    skel = {}
    skel.update(_files(skel_root, LESSONS_REL, "*.md"))
    skel.update(_files(skel_root, SCRIPTS_REL, "*"))
    absent = sorted(p for p in hub if p not in skel)
    changed = sorted(p for p in hub if p in skel and hub[p] != skel[p])
    return absent, changed


def build(root, now=None):
    now = now or datetime.now(timezone.utc)
    root = os.path.realpath(root)
    lines = [f"Lessons drift ({now.strftime('%Y-%m-%d')})"]
    skeleton_ok, hubs = resolve(root)
    if not skeleton_ok:
        lines.append(f"skeleton: {COULD_NOT_READ} (the registry's skeleton entry is not this checkout: {root})")
    for name, path in hubs:
        if not skeleton_ok:
            break
        if not path or not os.path.isdir(path):
            lines.append(f"{name}: {COULD_NOT_READ} (not in the registry or its path is missing)")
            continue
        try:
            absent, changed = drift(path, root)
        except OSError as exc:
            lines.append(f"{name}: {COULD_NOT_READ} ({exc})")
            continue
        if not absent and not changed:
            lines.append(f"{name}: no drift")
            continue
        lines.append(f"{name} has {len(absent)} the skeleton lacks and {len(changed)} that differ:")
        lines += [f"  absent   {p}" for p in absent]
        lines += [f"  differs  {p}" for p in changed]
    if skeleton_ok and not hubs:
        lines.append(f"no hubs declared in {HUBS_REL}")
    try:
        from pathlib import Path
        streak = _load("lessons_streak", "lessons_streak.py")
        # the file names come from the single writer's own constants: this is a
        # READER, and test_only_lessons_streak_writes_the_streak_file pins that
        # nothing but the job and the helper spells the streak file's name
        out_dir = Path(root) / "q-system" / "output"
        s = streak.summary(out_dir / streak.DEFAULT_FILE.name, out_dir / streak.DEFAULT_LEDGER.name, now=now)
        lines.append("propagation: " + streak.summary_line(s))
    except Exception as exc:  # the drift report still ships without the streak line
        lines.append(f"propagation: {COULD_NOT_READ} ({type(exc).__name__})")
    return "\n".join(lines)


def run(root, deliver=None, dry_run=False, trigger=None, now=None):
    """Build, then deliver only when launched by the plist (KIPI_TRIGGER=launchd).
    `deliver` is injectable for tests; None means slack_founder.deliver."""
    message = build(root, now=now)
    result = {"message": message, "delivery": {"delivered": False, "refused": False, "skipped": True}}
    if dry_run:
        return result
    if trigger != "launchd":
        result["delivery"]["reason"] = "not launched by the plist (KIPI_TRIGGER != launchd): printed, not sent"
        return result
    if deliver is None:
        deliver = _load("slack_founder", "slack_founder.py").deliver
    out = deliver(message) or {}
    result["delivery"] = {"delivered": bool(out.get("delivered")), "refused": bool(out.get("refused")), "skipped": False}
    return result


def main(argv=None, deliver=None):
    """Exit 0 when nothing was owed or the owed message landed; exit 2 when the
    plist launched this and delivery did not happen (PR #294 review, major: a
    refused Slack send returned 0, so the reporter's ONLY alert vanished behind
    a success exit that launchd, the deadman and run-step-audit all read as
    fine). Printed-not-sent (no plist marker) and --dry-run owe nothing."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--dry-run", action="store_true", help="print, send nothing")
    a = ap.parse_args(argv)
    trigger = os.environ.get("KIPI_TRIGGER")
    result = run(a.root, deliver=deliver, dry_run=a.dry_run, trigger=trigger)
    print(result["message"])
    d = result["delivery"]
    if a.dry_run:
        return 0
    print("delivery: " + ("sent" if d["delivered"] else "refused" if d["refused"] else d.get("reason", "not sent")))
    if trigger == "launchd" and not d["delivered"]:
        print("delivery: FAILED, the plist launched this and nothing landed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
