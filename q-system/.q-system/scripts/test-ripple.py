#!/usr/bin/env python3
"""
Ripple system regression tests. Run automatically via `kipi check`.

Tests:
1. ripple-graph.json is valid JSON with "graph" key
2. All source files in graph exist on disk
3. All target files in graph exist on disk
4. No file lists itself as a ripple target
5. changelog-write.py runs without import errors
6. content-lint.py runs without import errors
7. ripple-verify.py runs without import errors

Exit 0 = all pass
Exit 1 = failures (printed to stdout)
"""

import json
import os
import subprocess
import sys

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
# Subtree instances nest q-system/ inside q-system/
if not os.path.isdir(os.path.join(QROOT, "canonical")) and os.path.isdir(os.path.join(QROOT, "q-system", "canonical")):
    QROOT = os.path.join(QROOT, "q-system")
SCRIPTS = os.path.dirname(__file__)
RIPPLE_GRAPH = os.path.join(QROOT, ".q-system", "ripple-graph.json")

failures = []


def test(name, condition, detail=""):
    if condition:
        print(f"  PASS: {name}")
    else:
        msg = f"  FAIL: {name}" + (f" ({detail})" if detail else "")
        print(msg)
        failures.append(msg)


def test_graph_valid():
    try:
        with open(RIPPLE_GRAPH) as f:
            data = json.load(f)
        test("graph is valid JSON", True)
        test("graph has 'graph' key", "graph" in data, "missing top-level 'graph' key")
        return data.get("graph", {})
    except (FileNotFoundError, json.JSONDecodeError) as e:
        test("graph is valid JSON", False, str(e))
        return {}


# Dirs kipi-update deliberately does NOT sync (kipi-update.sh rsync
# --exclude list): instances OWN these and may trim or rename their canon
# (q-client_b keeps 3 canon files, not the skeleton's 14). The skeleton-authored
# ripple graph still ships via sync, so demanding skeleton canon exist in an
# instance failed 6/22 instances on the capability gate's first full fleet
# sweep (sp-07c9dad8, 2026-07-23). Skeleton stays strict; instances exempt
# refs under instance-owned prefixes, LOUDLY.
INSTANCE_OWNED_PREFIXES = ("canonical/", "my-project/", "memory/", "output/")
REPO_ROOT = os.path.normpath(os.path.join(QROOT, ".."))
IS_SKELETON = os.path.isfile(os.path.join(REPO_ROOT, "instance-registry.json"))


def _kept_out_of_repo(ref):
    """True when .gitignore deliberately keeps this instance-owned file out of git.

    ASK-2058 (2026-10-22): the scrub of this public skeleton untracks
    my-project/relationships.md, a list of real people, and ignores it so an
    auto-commit cannot add it back. Instances still own that file and the graph
    edge from it, so the skeleton check skips it, but only when an explicit
    ignore rule names it: a typo or a deleted file is not ignored and still fails.
    While the file is still tracked, the existence check passes first and this
    never runs.

    A LITERAL RULE FOR THAT EXACT PATH, NOT ANY RULE (PR #552 review round 1).
    A glob such as `output/**` also ignores a typo under output/, so "ignored"
    alone would skip the very mistake this check exists to catch. The deciding
    rule must be a non-negated pattern with no wildcard, in a .gitignore inside
    this repo, that spells out this file's path.
    """
    full = os.path.join(QROOT, ref)
    r = subprocess.run(["git", "-C", REPO_ROOT, "check-ignore", "-v", "--no-index", full],
                       capture_output=True, text=True)
    if r.returncode != 0 or "\t" not in r.stdout:
        return False
    source, _, pattern = r.stdout.split("\t", 1)[0].split(":", 2)
    if os.path.isabs(source) or pattern.startswith("!") or any(c in pattern for c in "*?[\\"):
        return False
    rule_dir = os.path.join(REPO_ROOT, os.path.dirname(source))
    return pattern.strip("/") == os.path.relpath(full, rule_dir)


def test_files_exist(graph):
    missing, instance_owned_absent, kept_out = [], [], []
    for src, targets in graph.items():
        for ref in [src] + list(targets):
            if os.path.exists(os.path.join(QROOT, ref)):
                continue
            if not IS_SKELETON and ref.startswith(INSTANCE_OWNED_PREFIXES):
                instance_owned_absent.append(ref)
            elif ref.startswith(INSTANCE_OWNED_PREFIXES) and _kept_out_of_repo(ref):
                kept_out.append(ref)
            else:
                missing.append(ref)
    if instance_owned_absent:
        skipped = sorted(set(instance_owned_absent))
        print(f"  SKIP: {len(skipped)} graph ref(s) under instance-owned dirs "
              f"absent here (canon is instance-owned, not synced): {skipped[:4]}...")
    if kept_out:
        print(f"  SKIP: {len(set(kept_out))} instance-owned graph ref(s) that "
              f".gitignore keeps out of this public repo: {sorted(set(kept_out))}")
    test("all referenced files exist", len(missing) == 0, f"missing: {missing}")


def test_no_self_reference(graph):
    self_refs = []
    for src, targets in graph.items():
        if src in targets:
            self_refs.append(src)
    test("no self-references", len(self_refs) == 0, f"self-referencing: {self_refs}")


def test_script_runs(name, script_path):
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Scripts with no args should exit 1 (usage) or 0, not crash
        test(
            f"{name} runs without crash",
            result.returncode in (0, 1, 2),
            f"exit {result.returncode}: {result.stderr[:200]}",
        )
    except Exception as e:
        test(f"{name} runs without crash", False, str(e))


def main():
    print("Ripple system regression tests:\n")

    graph = test_graph_valid()
    if graph:
        test_files_exist(graph)
        test_no_self_reference(graph)

    test_script_runs(
        "changelog-write.py", os.path.join(SCRIPTS, "changelog-write.py")
    )
    test_script_runs("content-lint.py", os.path.join(SCRIPTS, "content-lint.py"))
    test_script_runs("ripple-verify.py", os.path.join(SCRIPTS, "ripple-verify.py"))

    print(f"\n{7 - len(failures)}/7 passed, {len(failures)} failed.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
