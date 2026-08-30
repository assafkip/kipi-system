#!/usr/bin/env python3
"""
Tests for memory compilation candidate finder.

Covers: cluster detection, frontmatter parsing, compilation plan generation.

Run: python3 tests/test_compile.py
"""

import os
import sys
import tempfile
from pathlib import Path

# Import the module
import importlib.util
hook_path = os.path.join(os.path.dirname(__file__), "..", "hooks", "compile-memories.py")
spec = importlib.util.spec_from_file_location("compile_memories", hook_path)
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)

PASS = 0
FAIL = 0


def check(label, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}")


def make_memory(directory, filename, frontmatter_dict, body="Content."):
    lines = ["---"]
    for k, v in frontmatter_dict.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    path = directory / filename
    path.write_text("\n".join(lines))
    return path


# --- Test: Cluster key extraction ---

def test_cluster_key():
    print("\n--- Cluster key extraction ---")

    key1 = compiler.extract_cluster_key("project_josh_demo", {"type": "project", "name": "Josh demo status"})
    check("extracts type and subject", key1.startswith("project/"))
    check("subject words present", "josh" in key1)

    key2 = compiler.extract_cluster_key("feedback_testing", {"type": "feedback", "name": "Testing approach"})
    check("feedback type", key2.startswith("feedback/"))

    key3 = compiler.extract_cluster_key("pitfall_update", {"type": "feedback", "name": "Pitfall - update corrected"})
    check("skips 'pitfall' and 'update' words", "pitfall" not in key3.split("/")[1])


# --- Test: Cluster finding ---

def test_find_clusters():
    print("\n--- Cluster finding ---")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # Create 3 related project memories about Josh
        make_memory(tmp_dir, "project_josh_1.md", {"name": "Josh demo v1", "type": "project", "decay": "fast"})
        make_memory(tmp_dir, "project_josh_2.md", {"name": "Josh demo v2", "type": "project", "decay": "fast"})
        make_memory(tmp_dir, "project_josh_3.md", {"name": "Josh demo v3", "type": "project", "decay": "medium"})

        # Create 2 unrelated feedback memories (not enough for cluster)
        make_memory(tmp_dir, "feedback_voice.md", {"name": "Voice rules", "type": "feedback"})
        make_memory(tmp_dir, "feedback_testing.md", {"name": "Testing approach", "type": "feedback"})

        make_memory(tmp_dir, "MEMORY.md", {}, "Index")

        clusters = compiler.find_clusters(tmp_dir)

        check("finds 1 cluster", len(clusters) == 1)
        cluster_key = list(clusters.keys())[0]
        check("cluster has 3 memories", len(clusters[cluster_key]) == 3)


def test_finds_archived():
    print("\n--- Includes archived memories ---")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        archive_dir = tmp_dir / "archived"
        archive_dir.mkdir()

        # 2 active + 1 archived = cluster of 3
        make_memory(tmp_dir, "project_josh_1.md", {"name": "Josh demo v1", "type": "project"})
        make_memory(tmp_dir, "project_josh_2.md", {"name": "Josh demo v2", "type": "project"})
        make_memory(archive_dir, "project_josh_old.md", {"name": "Josh demo old", "type": "project"})

        make_memory(tmp_dir, "MEMORY.md", {}, "Index")

        clusters = compiler.find_clusters(tmp_dir)
        check("finds cluster across active + archived", len(clusters) >= 1)

        if clusters:
            cluster = list(clusters.values())[0]
            locations = [m["location"] for m in cluster]
            check("includes archived memory", "archived" in locations)
            check("includes active memories", "active" in locations)


def test_no_small_clusters():
    print("\n--- No clusters under 3 ---")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        make_memory(tmp_dir, "project_alpha.md", {"name": "Alpha project", "type": "project"})
        make_memory(tmp_dir, "project_beta.md", {"name": "Beta project", "type": "project"})
        make_memory(tmp_dir, "MEMORY.md", {}, "Index")

        clusters = compiler.find_clusters(tmp_dir)
        check("no clusters from 2 memories", len(clusters) == 0)


# --- Test: Compilation prompt ---

def test_compilation_prompt():
    print("\n--- Compilation prompt ---")

    clusters = {
        "project/josh-demo": [
            {"path": Path("/tmp/a.md"), "filename": "a.md", "name": "Josh v1",
             "decay": "fast", "type": "project", "location": "active", "body_preview": "Demo active"},
            {"path": Path("/tmp/b.md"), "filename": "b.md", "name": "Josh v2",
             "decay": "fast", "type": "project", "location": "active", "body_preview": "Demo reviewed"},
            {"path": Path("/tmp/c.md"), "filename": "c.md", "name": "Josh v3",
             "decay": "medium", "type": "project", "location": "archived", "body_preview": "Demo ended"},
        ]
    }

    prompt = compiler.generate_compilation_prompt(clusters)
    check("prompt includes cluster name", "josh-demo" in prompt)
    check("prompt includes source files", "/tmp/a.md" in prompt)
    check("prompt specifies slow decay", "slow" in prompt.lower())
    check("prompt mentions keeping recent state", "most recent" in prompt.lower())

    empty = compiler.generate_compilation_prompt({})
    check("empty clusters produce empty prompt", empty == "")


# --- Run all ---

if __name__ == "__main__":
    test_cluster_key()
    test_find_clusters()
    test_finds_archived()
    test_no_small_clusters()
    test_compilation_prompt()

    print(f"\n{'=' * 50}")
    print(f"  PASS: {PASS}")
    print(f"  FAIL: {FAIL}")
    print(f"{'=' * 50}")

    if FAIL > 0:
        print(f"\n{FAIL} test(s) failed.")
        sys.exit(1)
    else:
        print("\nAll tests passed.")
        sys.exit(0)
