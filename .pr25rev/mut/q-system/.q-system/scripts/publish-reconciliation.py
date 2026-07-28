#!/usr/bin/env python3
"""
Deterministic publish reconciliation.
Detects content published outside the Q system by fuzzy-matching
LinkedIn/X posts against Content Pipeline DB entries.

Usage:
    python3 publish-reconciliation.py <date>
    python3 publish-reconciliation.py <date> --json

Exit 0 = success
Exit 1 = error reading input files
"""

import json
import os
import re
import sys
from difflib import SequenceMatcher

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUS_BASE = os.path.join(QROOT, ".q-system", "agent-pipeline", "bus")


def read_bus_file(bus_dir, filename):
    """Read a JSON bus file, return None if missing."""
    path = os.path.join(bus_dir, filename)
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def normalize_text(text):
    """Normalize text for comparison: lowercase, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def fuzzy_match(text_a, text_b, threshold=0.6):
    """Compare first 50 chars, return similarity ratio."""
    a = normalize_text(text_a)[:50]
    b = normalize_text(text_b)[:50]
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def extract_founder_posts(linkedin_data):
    """Extract founder's own posts from linkedin-posts.json."""
    posts = []
    if not linkedin_data:
        return posts
    for post in linkedin_data.get("posts", []):
        # Only include founder's posts (not other people's)
        if post.get("is_founder", True):
            posts.append({
                "text": post.get("full_post_text", post.get("text", "")),
                "url": post.get("url", post.get("post_url", "")),
                "date": post.get("date", post.get("published_date", "")),
                "platform": "LinkedIn",
            })
    return posts


def extract_x_posts(x_data):
    """Extract founder's X posts from x-activity.json."""
    posts = []
    if not x_data:
        return posts
    for post in x_data.get("founder_posts", x_data.get("tweets", [])):
        posts.append({
            "text": post.get("full_post_text", post.get("text", "")),
            "url": post.get("url", post.get("tweet_url", "")),
            "date": post.get("date", post.get("created_at", "")),
            "platform": "X",
        })
    return posts


def extract_drafts(notion_data):
    """Extract drafted/scheduled content from crm.json."""
    drafts = []
    if not notion_data:
        return drafts
    # Content pipeline entries
    for entry in notion_data.get("content_pipeline", notion_data.get("drafts", [])):
        status = entry.get("status", "").lower()
        if status in ("drafted", "scheduled", "ready"):
            drafts.append({
                "page_id": entry.get("id", entry.get("page_id", "")),
                "text": entry.get("text", entry.get("content", entry.get("title", ""))),
                "platform": entry.get("platform", ""),
                "status": status,
            })
    return drafts


def parse_posting_targets():
    """Read weekly posting targets from _cadence-config.md or use defaults.
    Defaults from cadence config: LinkedIn 3-5/week, X 15-25/week."""
    targets = {"linkedin": 4, "x": 20}
    cadence_path = os.path.join(QROOT, ".q-system", "agent-pipeline", "agents", "_cadence-config.md")
    try:
        with open(cadence_path) as f:
            content = f.read()
        m = re.search(r'LinkedIn\s*\|\s*(\d+)', content)
        if m:
            targets["linkedin"] = int(m.group(1))
        m = re.search(r'\|\s*X\s*\|\s*(\d+)', content)
        if m:
            targets["x"] = int(m.group(1))
    except FileNotFoundError:
        pass
    return targets


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 publish-reconciliation.py <date> [--json]", file=sys.stderr)
        sys.exit(2)

    date = sys.argv[1]
    json_output = "--json" in sys.argv
    bus_dir = os.path.join(BUS_BASE, date)

    if not os.path.isdir(bus_dir):
        print(f"Bus directory not found: {bus_dir}", file=sys.stderr)
        sys.exit(1)

    # Read inputs
    linkedin_data = read_bus_file(bus_dir, "linkedin-posts.json")
    x_data = read_bus_file(bus_dir, "x-activity.json")
    notion_data = read_bus_file(bus_dir, "crm.json")

    founder_posts = extract_founder_posts(linkedin_data) + extract_x_posts(x_data)
    drafts = extract_drafts(notion_data)

    targets = parse_posting_targets()

    # Reconcile
    reconciled = []
    notion_updates = []
    matched_draft_ids = set()

    for post in founder_posts:
        best_match = None
        best_score = 0.0

        for draft in drafts:
            # Platform filter
            if draft["platform"] and draft["platform"].lower() != post["platform"].lower():
                continue

            score = fuzzy_match(post["text"], draft["text"])
            if score > best_score and score >= 0.6:
                best_score = score
                best_match = draft

        out_of_system = best_match is None
        matched_id = best_match["page_id"] if best_match else None

        if matched_id:
            matched_draft_ids.add(matched_id)

        reconciled.append({
            "platform": post["platform"],
            "post_url": post["url"],
            "post_preview": post["text"][:100],
            "matched_draft": matched_id,
            "match_score": round(best_score, 2) if best_match else 0,
            "publish_date": post["date"],
            "out_of_system": out_of_system,
        })

        if matched_id:
            notion_updates.append({
                "page_id": matched_id,
                "new_status": "Published",
                "post_url": post["url"],
            })

    # Cadence update
    linkedin_count = sum(1 for r in reconciled if r["platform"] == "LinkedIn")
    x_count = sum(1 for r in reconciled if r["platform"] == "X")

    result = {
        "date": date,
        "reconciled": reconciled,
        "cadence_update": {
            "linkedin": {"published_this_week": linkedin_count, "target": targets["linkedin"]},
            "x": {"published_this_week": x_count, "target": targets["x"]},
        },
        "notion_updates_needed": notion_updates,
    }

    # Write output
    output_path = os.path.join(bus_dir, "publish-reconciliation.json")
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        oos = sum(1 for r in reconciled if r["out_of_system"])
        print(f"Publish reconciliation ({date}):")
        print(f"  Posts found: {len(reconciled)} ({linkedin_count} LinkedIn, {x_count} X)")
        print(f"  Matched to drafts: {len(notion_updates)}")
        print(f"  Out-of-system: {oos}")
        print(f"  Written to {output_path}")

    sys.exit(0)


if __name__ == "__main__":
    main()
