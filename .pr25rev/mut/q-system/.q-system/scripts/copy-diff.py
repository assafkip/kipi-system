#!/usr/bin/env python3
"""
Deterministic copy diff analyzer.
Compares yesterday's generated hitlist copy against what actually posted.
Classifies each action as used_as_is, edited, skipped, or unknown.

Usage:
    python3 copy-diff.py <date>
    python3 copy-diff.py <date> --json

Exit 0 = success
Exit 1 = error
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta
from difflib import SequenceMatcher

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUS_BASE = os.path.join(QROOT, ".q-system", "agent-pipeline", "bus")
DB_PATH = os.path.join(QROOT, ".q-system", "data", "metrics.db")


def read_bus_file(bus_dir, filename):
    """Read JSON bus file, return None if missing."""
    path = os.path.join(bus_dir, filename)
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def normalize(text):
    """Normalize text for comparison."""
    text = text.lower().strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def similarity(a, b):
    """Return similarity ratio between two strings."""
    a_norm = normalize(a)
    b_norm = normalize(b)
    if not a_norm or not b_norm:
        return 0.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def extract_hitlist_actions(hitlist):
    """Extract copy actions from hitlist.json."""
    actions = []
    if not hitlist:
        return actions
    for i, action in enumerate(hitlist.get("actions", [])):
        copy_text = (
            action.get("copy", "")
            or action.get("comment_text", "")
            or action.get("dm_text", "")
            or action.get("cr_text", "")
            or action.get("text", "")
        )
        actions.append({
            "rank": i + 1,
            "contact_name": action.get("contact_name", action.get("name", "")),
            "action_type": action.get("action_type", action.get("type", "")),
            "generated_copy": copy_text,
        })
    return actions


def extract_posted_content(linkedin_posts):
    """Extract founder's recent posts/comments for matching."""
    posted = []
    if not linkedin_posts:
        return posted
    # Founder posts
    for post in linkedin_posts.get("posts", []):
        if post.get("is_founder", True):
            posted.append({
                "text": post.get("full_post_text", post.get("text", "")),
                "type": "post",
            })
    # Founder comments
    for comment in linkedin_posts.get("founder_comments", []):
        posted.append({
            "text": comment.get("text", comment.get("comment_text", "")),
            "type": "comment",
        })
    return posted


def classify_action(action, posted_content):
    """Classify an action as used_as_is, edited, skipped, or unknown."""
    generated = action["generated_copy"]
    if not generated:
        return "unknown", ""

    best_score = 0.0
    best_match = None

    for posted in posted_content:
        score = similarity(generated, posted["text"])
        if score > best_score:
            best_score = score
            best_match = posted

    if best_score >= 0.95:
        return "used_as_is", ""
    elif best_score >= 0.50:
        edit_summary = f"Match score: {best_score:.0%}"
        return "edited", edit_summary
    elif best_score >= 0.30:
        return "unknown", f"Possible match at {best_score:.0%}"
    else:
        return "skipped", ""


def persist_edits(diffs, date):
    """Insert edited actions into copy_edits SQLite table."""
    if not os.path.isfile(DB_PATH):
        return False
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        inserted = 0
        for diff in diffs:
            if diff["status"] == "edited":
                cursor.execute(
                    "INSERT OR IGNORE INTO copy_edits (date, contact_name, action_type, original, edited, edit_summary) VALUES (?, ?, ?, ?, ?, ?)",
                    (date, diff["contact_name"], diff["action_type"],
                     diff.get("generated_copy", ""), "", diff["edit_summary"]),
                )
                inserted += 1
        conn.commit()
        conn.close()
        return inserted > 0
    except Exception:
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 copy-diff.py <date> [--json]", file=sys.stderr)
        sys.exit(2)

    date = sys.argv[1]
    json_output = "--json" in sys.argv

    today = datetime.strptime(date, "%Y-%m-%d")
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    yesterday_bus = os.path.join(BUS_BASE, yesterday)
    today_bus = os.path.join(BUS_BASE, date)

    # Read yesterday's hitlist (generated copy)
    hitlist = read_bus_file(yesterday_bus, "hitlist.json")
    if not hitlist:
        result = {
            "date": date,
            "yesterday": yesterday,
            "diffs": [],
            "note": "no previous hitlist found",
            "stats": {"used_as_is": 0, "edited": 0, "skipped": 0, "unknown": 0},
            "persisted_to_sqlite": False,
        }
        os.makedirs(today_bus, exist_ok=True)
        output_path = os.path.join(today_bus, "copy-diffs.json")
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)
        if json_output:
            print(json.dumps(result, indent=2))
        else:
            print(f"Copy diff ({date}): no previous hitlist found for {yesterday}")
        sys.exit(0)

    # Read today's linkedin posts (what was actually posted)
    linkedin_posts = read_bus_file(today_bus, "linkedin-posts.json")
    posted_content = extract_posted_content(linkedin_posts)

    # Extract and classify
    actions = extract_hitlist_actions(hitlist)
    diffs = []
    stats = {"used_as_is": 0, "edited": 0, "skipped": 0, "unknown": 0}

    for action in actions:
        status, edit_summary = classify_action(action, posted_content)
        stats[status] += 1
        diffs.append({
            "action_rank": action["rank"],
            "contact_name": action["contact_name"],
            "action_type": action["action_type"],
            "status": status,
            "edit_summary": edit_summary,
            "generated_copy": action["generated_copy"][:200],
        })

    # Persist edits to SQLite
    persisted = persist_edits(diffs, date)

    result = {
        "date": date,
        "yesterday": yesterday,
        "actions_checked": len(actions),
        "diffs": diffs,
        "stats": stats,
        "persisted_to_sqlite": persisted,
    }

    # Write output
    os.makedirs(today_bus, exist_ok=True)
    output_path = os.path.join(today_bus, "copy-diffs.json")
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        print(f"Copy diff ({date}):")
        print(f"  Actions checked: {len(actions)}")
        print(f"  Used as-is: {stats['used_as_is']}, Edited: {stats['edited']}")
        print(f"  Skipped: {stats['skipped']}, Unknown: {stats['unknown']}")
        print(f"  Persisted to SQLite: {persisted}")
        print(f"  Written to {output_path}")

    sys.exit(0)


if __name__ == "__main__":
    main()
