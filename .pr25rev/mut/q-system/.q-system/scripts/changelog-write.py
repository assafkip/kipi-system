#!/usr/bin/env python3
"""
Append a changelog entry and return ripple targets.

Usage:
    python3 changelog-write.py <file> <workflow> <summary> [--source SOURCE]

Example:
    python3 changelog-write.py canonical/objections.md debrief \
        "Added CrowdStrike competitive objection with differentiation response" \
        --source "Josh Martinez - 2026-04-12 - conversation"

Output (stdout JSON):
    {"logged": true, "ripple_targets": ["canonical/talk-tracks.md", ...]}

Exit 0 = success
Exit 1 = invalid arguments
Exit 2 = ripple-graph.json missing or malformed
"""

import json
import os
import sys
from datetime import date

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
# Subtree instances nest q-system/ inside q-system/
if not os.path.isdir(os.path.join(QROOT, "canonical")) and os.path.isdir(os.path.join(QROOT, "q-system", "canonical")):
    QROOT = os.path.join(QROOT, "q-system")
CHANGELOG = os.path.join(QROOT, "canonical", "changelog.md")
RIPPLE_GRAPH = os.path.join(QROOT, ".q-system", "ripple-graph.json")


def load_ripple_graph():
    try:
        with open(RIPPLE_GRAPH) as f:
            return json.load(f)["graph"]
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        print(f"ERROR: ripple-graph.json: {e}", file=sys.stderr)
        sys.exit(2)


def get_ripple_targets(graph, file_key):
    targets = graph.get(file_key, [])
    return sorted(t for t in targets if t != file_key)


def append_changelog(file_key, workflow, summary, source):
    changelog_dir = os.path.dirname(CHANGELOG)
    if not os.path.isdir(changelog_dir):
        print(f"ERROR: directory {changelog_dir} does not exist", file=sys.stderr)
        sys.exit(2)
    today = date.today().isoformat()
    entry = f"\n### {today} | {workflow} | {file_key}\n{summary}\nSource: {source}\n"
    with open(CHANGELOG, "a") as f:
        f.write(entry)


def main():
    if len(sys.argv) < 4:
        print(
            "Usage: changelog-write.py <file> <workflow> <summary> [--source SOURCE]",
            file=sys.stderr,
        )
        sys.exit(1)

    file_key = sys.argv[1]
    workflow = sys.argv[2]
    summary = sys.argv[3]
    source = "founder directive"

    if "--source" in sys.argv:
        idx = sys.argv.index("--source")
        if idx + 1 < len(sys.argv):
            source = sys.argv[idx + 1]

    graph = load_ripple_graph()
    targets = get_ripple_targets(graph, file_key)
    append_changelog(file_key, workflow, summary, source)

    result = {"logged": True, "ripple_targets": targets}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
