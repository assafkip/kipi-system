#!/usr/bin/env python3
"""
Tests for memory lifecycle hook.

Covers: frontmatter parsing, freshness detection, auto-archive,
decay promotion, MEMORY.md index updates.

Run: python3 tests/test_lifecycle.py
"""

import json
import os
import sys
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# Add parent to path so we can import the hook
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hooks"))

from importlib import import_module

# Import session-start.py (hyphenated filename)
import importlib.util
hook_path = os.path.join(os.path.dirname(__file__), "..", "hooks", "session-start.py")
spec = importlib.util.spec_from_file_location("session_start", hook_path)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


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


def make_memory(tmp_dir, filename, frontmatter_dict, body="Memory content."):
    """Create a memory file with frontmatter."""
    lines = ["---"]
    for k, v in frontmatter_dict.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append(body)

    path = tmp_dir / filename
    path.write_text("\n".join(lines))
    return path


def set_file_age(path, days):
    """Set file mtime to N days ago."""
    import time
    old_time = time.time() - (days * 86400)
    os.utime(path, (old_time, old_time))


# --- Test: Frontmatter parsing ---

def test_parse_frontmatter():
    print("\n--- Frontmatter parsing ---")

    content = "---\nname: test\ndecay: fast\nverify_count: 3\n---\nBody."
    fm = hook.parse_frontmatter(content)
    check("parses name", fm.get("name") == "test")
    check("parses decay", fm.get("decay") == "fast")
    check("parses verify_count", fm.get("verify_count") == "3")

    fm_empty = hook.parse_frontmatter("No frontmatter here.")
    check("returns empty dict for no frontmatter", fm_empty == {})

    fm_partial = hook.parse_frontmatter("---\nname: only\n---\n")
    check("handles partial frontmatter", fm_partial.get("name") == "only")


# --- Test: Update frontmatter ---

def test_update_frontmatter():
    print("\n--- Frontmatter update ---")

    content = "---\nname: test\ndecay: fast\n---\nBody text."
    updated = hook.update_frontmatter(content, {"decay": "medium"})
    fm = hook.parse_frontmatter(updated)
    check("updates existing field", fm.get("decay") == "medium")
    check("preserves other fields", fm.get("name") == "test")
    check("preserves body", "Body text." in updated)

    added = hook.update_frontmatter(content, {"last_verified": "2026-04-11"})
    fm2 = hook.parse_frontmatter(added)
    check("adds new field", fm2.get("last_verified") == "2026-04-11")


# --- Test: Freshness detection ---

def test_freshness():
    print("\n--- Freshness detection ---")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        make_memory(tmp_dir, "fast_mem.md", {"name": "Fast thing", "decay": "fast"})
        make_memory(tmp_dir, "slow_mem.md", {"name": "Slow thing", "decay": "slow"})
        make_memory(tmp_dir, "no_decay.md", {"name": "No decay"})
        make_memory(tmp_dir, "MEMORY.md", {}, "Index file")

        fast = hook.check_freshness(tmp_dir)
        check("finds fast-decay memory", len(fast) == 1)
        check("correct name", fast[0][0] == "Fast thing")
        check("correct filename", fast[0][1] == "fast_mem.md")


# --- Test: Auto-archive ---

def test_archive():
    print("\n--- Auto-archive ---")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        state = {"archived": []}

        # Fast-decay, 20 days old, no verification -> should archive
        p1 = make_memory(tmp_dir, "stale_fast.md", {"name": "Stale", "decay": "fast"})
        set_file_age(p1, 20)

        # Fast-decay, 5 days old -> should NOT archive
        p2 = make_memory(tmp_dir, "fresh_fast.md", {"name": "Fresh", "decay": "fast"})
        set_file_age(p2, 5)

        # Slow-decay, 100 days old -> should NOT archive (slow never archives)
        p3 = make_memory(tmp_dir, "old_slow.md", {"name": "Old slow", "decay": "slow"})
        set_file_age(p3, 100)

        # Medium-decay, 70 days old -> should archive
        p4 = make_memory(tmp_dir, "stale_medium.md", {"name": "Stale med", "decay": "medium"})
        set_file_age(p4, 70)

        # Fast-decay, 20 days old BUT recently verified -> should NOT archive
        p5 = make_memory(tmp_dir, "verified_fast.md", {
            "name": "Verified",
            "decay": "fast",
            "last_verified": datetime.now().strftime("%Y-%m-%d"),
        })
        set_file_age(p5, 20)

        make_memory(tmp_dir, "MEMORY.md", {}, "Index")

        archived = hook.run_archive(tmp_dir, state)

        check("archives stale fast-decay", "stale_fast.md" in archived)
        check("keeps fresh fast-decay", "fresh_fast.md" not in archived)
        check("never archives slow-decay", "old_slow.md" not in archived)
        check("archives stale medium-decay", "stale_medium.md" in archived)
        check("keeps recently verified", "verified_fast.md" not in archived)
        check("archived dir created", (tmp_dir / "archived").exists())
        check("file moved to archived/", (tmp_dir / "archived" / "stale_fast.md").exists())
        check("file removed from root", not (tmp_dir / "stale_fast.md").exists())


# --- Test: Decay promotion ---

def test_promotion():
    print("\n--- Decay promotion ---")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # Fast, verified 3x, 35 days old -> promote to medium
        p1 = make_memory(tmp_dir, "promote_me.md", {
            "name": "Promotable",
            "decay": "fast",
            "verify_count": "3",
        })
        set_file_age(p1, 35)

        # Fast, verified 2x, 35 days old -> NOT enough verifications
        p2 = make_memory(tmp_dir, "not_enough.md", {
            "name": "Not enough",
            "decay": "fast",
            "verify_count": "2",
        })
        set_file_age(p2, 35)

        # Fast, verified 3x, 10 days old -> NOT old enough
        p3 = make_memory(tmp_dir, "too_new.md", {
            "name": "Too new",
            "decay": "fast",
            "verify_count": "3",
        })
        set_file_age(p3, 10)

        # Medium, verified 5x, 65 days old -> promote to slow
        p4 = make_memory(tmp_dir, "medium_promote.md", {
            "name": "Medium up",
            "decay": "medium",
            "verify_count": "5",
        })
        set_file_age(p4, 65)

        make_memory(tmp_dir, "MEMORY.md", {}, "Index")

        promoted = hook.run_promotion(tmp_dir)

        check("promotes fast -> medium", ("promote_me.md", "fast", "medium") in promoted)
        check("skips insufficient verifications", not any(p[0] == "not_enough.md" for p in promoted))
        check("skips too-new memory", not any(p[0] == "too_new.md" for p in promoted))
        check("promotes medium -> slow", ("medium_promote.md", "medium", "slow") in promoted)

        # Verify frontmatter actually changed
        content = (tmp_dir / "promote_me.md").read_text()
        fm = hook.parse_frontmatter(content)
        check("frontmatter updated to medium", fm.get("decay") == "medium")


# --- Test: MEMORY.md index rebuild ---

def test_index_rebuild():
    print("\n--- MEMORY.md index rebuild ---")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        make_memory(tmp_dir, "fast_one.md", {"name": "Fast One", "decay": "fast", "description": "A fast thing"})
        make_memory(tmp_dir, "slow_one.md", {"name": "Slow One", "decay": "slow", "description": "A slow thing"})
        make_memory(tmp_dir, "MEMORY.md", {}, "Old index")

        hook.update_memory_index(tmp_dir)

        index = (tmp_dir / "MEMORY.md").read_text()
        check("index contains fast prefix", "[fast]" in index)
        check("index contains fast memory link", "[Fast One](fast_one.md)" in index)
        check("index contains slow memory link", "[Slow One](slow_one.md)" in index)
        check("slow has no [fast] prefix", "[fast] [Slow One]" not in index)


# --- Test: State file ---

def test_state():
    print("\n--- State file ---")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        state = {"last_archive_run": "2026-04-11", "archived": ["old.md"]}

        hook.save_state(tmp_dir, state)
        loaded = hook.load_state(tmp_dir)

        check("state round-trips", loaded["last_archive_run"] == "2026-04-11")
        check("archived list preserved", "old.md" in loaded["archived"])

        empty = hook.load_state(Path("/nonexistent"))
        check("missing state returns default", empty == {"last_archive_run": None, "last_promotion_run": None, "archived": []})


# --- Run all ---

if __name__ == "__main__":
    test_parse_frontmatter()
    test_update_frontmatter()
    test_freshness()
    test_archive()
    test_promotion()
    test_index_rebuild()
    test_state()

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
