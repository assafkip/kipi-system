#!/usr/bin/env python3
"""Did the lessons corpus actually reach every live instance? (ASK-3574)

The check the DoR of ASK-3574 names, as ONE command instead of a 20-minute
hand probe. Run it after any lessons-daily / kipi-update fan-out:

    python3 q-system/.q-system/scripts/lessons-fanout-check.py

Exit 0 = green. Exit 2 = red. Exit 1 = the check itself could not run.

WHAT IS RED, AND WHY IT IS NOT "any difference"
-----------------------------------------------
Red on a live instance MISSING lessons the skeleton has, which is the fan-out
property this check exists to hold. A SURPLUS is reported on its own labelled
line and is NOT red by default: measured 2026-10-31, one instance carried 213
against the skeleton's 205, so a strict-equality default would have been red on
its own population the day it landed, and a gate red on its own population gets
switched off. `--strict` makes a surplus red too, for a caller that wants the
literal equality the DoR wrote.

Red also on `propagate FAILED` in the newest lessons-daily.log run block, and on
a log or streak file that could not be read. A check whose inputs are absent
reports COULD NOT READ, never "green": the 2026-10-22 miss below was invisible
for nine days precisely because nothing counted.

DEAD REGISTRY PATHS ARE REPORTED, NOT RED. Measured 2026-10-31: 8 of 21
registry rows point at directories that no longer exist. They belong to
ASK-3404; failing this check on them would bury the fan-out signal under a
registry-hygiene problem that is somebody else's issue.

THE SCAR
--------
2026-10-22: the fleet fan-out reached 12 instances and missed exactly one. That
instance stayed at 176 lessons while the skeleton moved to 205, and the 29
missing files were only found by counting them by hand nine days later. Branch
was NOT the cause, which is worth recording because it was the first guess:
three instances that took that same sync were sitting on feature branches of
their own. Nothing in the fleet compared a count, so the miss was silent.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
LESSONS_REL = pathlib.Path("q-system") / "lessons"
# The newest run block in the log is what a post-run verification is asking
# about; an older failure already had its own alert and its own streak row.
RUN_MARKER = "lessons publish:"
FAIL_MARKER = "propagate FAILED"


def count_lessons(root: pathlib.Path) -> int:
    """Lesson files under <root>/q-system/lessons. -1 when there is no dir."""
    lessons = root / LESSONS_REL
    if not lessons.is_dir():
        return -1
    return len(list(lessons.glob("*.md")))


def load_registry(path: pathlib.Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"COULD NOT READ the registry {path}: {exc}")
    rows = data.get("instances")
    if not isinstance(rows, list):
        raise SystemExit(f"registry {path} declares no 'instances' list")
    return rows


def classify(skeleton_count: int, rows: list[dict]) -> dict:
    """Split the registry into short / surplus / level / dead / no-corpus."""
    out = {"short": [], "surplus": [], "level": [], "dead": [], "no_corpus": []}
    for row in rows:
        name = row.get("name") or "<unnamed>"
        path = pathlib.Path(str(row.get("path") or "")).expanduser()
        if not path.is_dir():
            out["dead"].append((name, str(path)))
            continue
        found = count_lessons(path)
        if found < 0:
            out["no_corpus"].append((name, str(path)))
        elif found < skeleton_count:
            out["short"].append((name, found, skeleton_count - found))
        elif found > skeleton_count:
            out["surplus"].append((name, found, found - skeleton_count))
        else:
            out["level"].append((name, found))
    return out


def read_log_verdict(log: pathlib.Path) -> tuple[bool, str]:
    """(ok, line) for the newest run block of lessons-daily.log."""
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, f"COULD NOT READ {log}: {exc}"
    if not text.strip():
        return False, f"COULD NOT READ {log}: file is empty"
    blocks = text.split(RUN_MARKER)
    newest = blocks[-1]
    hits = [ln for ln in newest.splitlines() if FAIL_MARKER in ln]
    if hits:
        return False, f"{FAIL_MARKER} in the newest run block: {hits[-1].strip()}"
    return True, f"no '{FAIL_MARKER}' in the newest run block of {log.name}"


def read_streak(streak: pathlib.Path) -> tuple[bool, str]:
    try:
        data = json.loads(streak.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"COULD NOT READ {streak}: {exc}"
    return True, f"streak file present: {json.dumps(data, sort_keys=True)[:200]}"


def print_report(skeleton_count: int, groups: dict, log_msg: str, streak_msg: str):
    print(f"skeleton lessons: {skeleton_count}")
    print(f"level with skeleton: {len(groups['level'])} instance(s)")
    for name, found, gap in groups["short"]:
        print(f"  SHORT   {name}: {found} lessons, {gap} missing")
    for name, found, extra in groups["surplus"]:
        print(f"  surplus {name}: {found} lessons, {extra} the skeleton lacks")
    for name, path in groups["no_corpus"]:
        print(f"  NO CORPUS {name}: no q-system/lessons dir at {path}")
    for name, path in groups["dead"]:
        print(f"  dead path (ASK-3404, not red) {name}: {path}")
    print(f"log:    {log_msg}")
    print(f"streak: {streak_msg}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skeleton", default=str(REPO_ROOT),
                    help="skeleton repo root (default: this script's repo)")
    ap.add_argument("--registry", default=None,
                    help="instance-registry.json (default: <skeleton>/instance-registry.json)")
    ap.add_argument("--log", default=None,
                    help="lessons-daily.log (default: <skeleton>/q-system/output/lessons-daily.log)")
    ap.add_argument("--streak", default=None,
                    help="streak json (default: <skeleton>/q-system/output/lessons-propagation-streak.json)")
    ap.add_argument("--strict", action="store_true",
                    help="a surplus is red too (the DoR's literal 'red if they differ')")
    return ap


def resolve_paths(args) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]:
    skel = pathlib.Path(args.skeleton).expanduser().resolve()
    registry = pathlib.Path(args.registry) if args.registry else skel / "instance-registry.json"
    out = skel / "q-system" / "output"
    log = pathlib.Path(args.log) if args.log else out / "lessons-daily.log"
    streak = (pathlib.Path(args.streak) if args.streak
              else out / "lessons-propagation-streak.json")
    return skel, registry, log, streak


def main() -> int:
    args = build_parser().parse_args()
    skel, registry, log, streak = resolve_paths(args)

    skeleton_count = count_lessons(skel)
    if skeleton_count < 0:
        print(f"COULD NOT READ the skeleton corpus at {skel / LESSONS_REL}")
        return 1

    groups = classify(skeleton_count, load_registry(registry))
    log_ok, log_msg = read_log_verdict(log)
    streak_ok, streak_msg = read_streak(streak)
    print_report(skeleton_count, groups, log_msg, streak_msg)

    reasons = []
    if groups["short"]:
        reasons.append(f"{len(groups['short'])} instance(s) short of the skeleton")
    if groups["no_corpus"]:
        reasons.append(f"{len(groups['no_corpus'])} live instance(s) with no lessons dir")
    if args.strict and groups["surplus"]:
        reasons.append(f"{len(groups['surplus'])} instance(s) above the skeleton (--strict)")
    if not log_ok:
        reasons.append("the lessons-daily log did not read clean")
    if not streak_ok:
        reasons.append("the propagation streak file did not read")

    if reasons:
        print("\nRED: " + "; ".join(reasons))
        return 2
    print("\nGREEN: every live instance is level with the skeleton corpus")
    return 0


if __name__ == "__main__":
    sys.exit(main())
