#!/usr/bin/env python3
"""
Structural lint: check canonical files for markers, orphans, and staleness.

Checks (structural only, no semantic analysis):
1. Talk tracks containing {{UNVALIDATED}} or {{NEEDS_PROOF}} markers (ERROR)
2. Competitive landscape headers not matching any objections header (WARNING)
3. Changelog entries older than 60 days (WARNING, collapsed to single count)
4. Excessive unvalidated markers in non-discovery files (WARNING if >3)

NOT checked (v1.1 semantic lint):
- Talk tracks claiming capabilities not in current-state.md
- Objection responses referencing proof points that don't exist
- Cross-file claim contradictions

Usage:
    python3 content-lint.py [--json]

Exit 0 = clean
Exit 1 = warnings found
Exit 2 = errors found
"""

import json
import os
import re
import sys
from datetime import date, timedelta

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
# Subtree instances nest q-system/ inside q-system/
if not os.path.isdir(os.path.join(QROOT, "canonical")) and os.path.isdir(os.path.join(QROOT, "q-system", "canonical")):
    QROOT = os.path.join(QROOT, "q-system")

FILES = {
    "current_state": os.path.join(QROOT, "my-project", "current-state.md"),
    "talk_tracks": os.path.join(QROOT, "canonical", "talk-tracks.md"),
    "objections": os.path.join(QROOT, "canonical", "objections.md"),
    "competitive": os.path.join(QROOT, "my-project", "competitive-landscape.md"),
    "market_intel": os.path.join(QROOT, "canonical", "market-intelligence.md"),
    "discovery": os.path.join(QROOT, "canonical", "discovery.md"),
    "changelog": os.path.join(QROOT, "canonical", "changelog.md"),
    "proof_points": os.path.join(QROOT, "marketing", "assets", "proof-points.md"),
}


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def extract_headers(content, level="## "):
    return [
        line.lstrip("#").strip()
        for line in content.splitlines()
        if line.startswith(level)
    ]


def extract_unvalidated_markers(content):
    return re.findall(r"\{\{(UNVALIDATED|NEEDS_PROOF)\}\}", content)


def check_changelog_staleness(content):
    cutoff = date.today() - timedelta(days=60)
    stale_count = 0
    for match in re.finditer(r"### (\d{4}-\d{2}-\d{2})", content):
        try:
            entry_date = date.fromisoformat(match.group(1))
            if entry_date < cutoff:
                stale_count += 1
        except ValueError:
            pass
    if stale_count > 0:
        return [f"{stale_count} changelog entries older than 60 days. Run md-prune.py."]
    return []


def check_orphaned_competitors(competitive, objections):
    warnings = []
    comp_headers = extract_headers(competitive, "## ")
    obj_headers = {h.lower() for h in extract_headers(objections, "## ")}
    obj_headers.update({h.lower() for h in extract_headers(objections, "### ")})
    for header in comp_headers:
        name = header.strip().lower()
        if name and len(name) > 2 and name not in obj_headers:
            warnings.append(
                f"Competitor '{header}' in competitive-landscape.md "
                f"but no matching header in objections.md"
            )
    return warnings


def check_unvalidated_in_talk_tracks(talk_tracks):
    errors = []
    markers = extract_unvalidated_markers(talk_tracks)
    if markers:
        errors.append(
            f"talk-tracks.md contains {len(markers)} unvalidated marker(s). "
            f"Talk tracks must be proven language only."
        )
    return errors


def main():
    json_mode = "--json" in sys.argv
    files = {k: read(v) for k, v in FILES.items()}

    warnings = []
    errors = []

    errors.extend(check_unvalidated_in_talk_tracks(files["talk_tracks"]))

    warnings.extend(
        check_orphaned_competitors(files["competitive"], files["objections"])
    )

    warnings.extend(check_changelog_staleness(files["changelog"]))

    for name, content in files.items():
        if name in ("changelog", "discovery"):
            continue
        count = len(extract_unvalidated_markers(content))
        if count > 3:
            warnings.append(
                f"{name} has {count} unvalidated markers. Review and resolve."
            )

    if json_mode:
        print(
            json.dumps(
                {
                    "errors": errors,
                    "warnings": warnings,
                    "clean": len(errors) == 0 and len(warnings) == 0,
                },
                indent=2,
            )
        )
    else:
        if errors:
            print("ERRORS:")
            for e in errors:
                print(f"  x {e}")
        if warnings:
            print("WARNINGS:")
            for w in warnings:
                print(f"  ! {w}")
        if not errors and not warnings:
            print("Content lint: clean")

    if errors:
        sys.exit(2)
    elif warnings:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
