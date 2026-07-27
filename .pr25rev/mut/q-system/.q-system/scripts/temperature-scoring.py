#!/usr/bin/env python3
"""
Deterministic temperature scoring for prospects.
Consolidates engagement signals per prospect and produces a temperature score.
Replaces the 05-temperature-scoring LLM agent.

Usage:
    python3 temperature-scoring.py <date>
    python3 temperature-scoring.py <date> --json

Exit 0 = success
Exit 1 = error
"""

import json
import os
import sys
from datetime import datetime, timedelta

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUS_BASE = os.path.join(QROOT, ".q-system", "agent-pipeline", "bus")
AGENTS_DIR = os.path.join(QROOT, ".q-system", "agent-pipeline", "agents")

# Signal weights (from agent prompt spec)
SIGNAL_WEIGHTS = {
    "dm_reply": 3,
    "email_reply": 3,
    "connection_accepted": 2,
    "comment_on_post": 2,
    "like_on_post": 1,
    "link_click": 2,
    "demo_request": 4,
    "no_contact_14d": -1,
    "no_contact_30d": -2,
    "regulated_sector": 1,
}

REGULATED_SECTORS = {"energy", "transport", "banking", "health", "digital infra", "cloud", "ict"}

TEMPERATURE_BUCKETS = {
    "Hot": lambda s: s >= 8,
    "Warm": lambda s: 4 <= s < 8,
    "Cool": lambda s: 1 <= s < 4,
    "Cold": lambda s: s < 1,
}


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


def parse_cadence_config():
    """Parse auto-close and timeout thresholds from _cadence-config.json (structured).
    Falls back to hardcoded defaults if file missing."""
    config = {
        "dm_timeout_days": 14,
        "auto_close_days": 21,
        "auto_close_touches": 3,
    }
    json_path = os.path.join(AGENTS_DIR, "_cadence-config.json")
    try:
        with open(json_path) as f:
            data = json.load(f)
        limits = data.get("platform_limits", {})
        if "auto_cooling_days" in limits:
            config["dm_timeout_days"] = limits["auto_cooling_days"]
        if "auto_pass_days" in limits:
            config["auto_close_days"] = limits["auto_pass_days"]
        if "auto_pass_min_touches" in limits:
            config["auto_close_touches"] = limits["auto_pass_min_touches"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return config


def extract_prospects(linkedin_dms, linkedin_posts, gmail, notion):
    """Build a prospect map from all data sources."""
    prospects = {}  # keyed by name (lowercase)

    def ensure(name, notion_id=""):
        key = name.strip().lower()
        if key and key not in prospects:
            prospects[key] = {
                "name": name.strip(),
                "notion_id": notion_id,
                "signals": [],
                "last_contact_date": None,
                "touch_count": 0,
                "sector": "",
            }
        return key

    # DMs
    if linkedin_dms:
        for dm in linkedin_dms.get("dms", []):
            name = dm.get("contact_name", dm.get("name", ""))
            key = ensure(name)
            if not key:
                continue
            if dm.get("reply_received") or dm.get("direction") == "inbound":
                prospects[key]["signals"].append({
                    "type": "DM reply",
                    "weight": SIGNAL_WEIGHTS["dm_reply"],
                    "date": dm.get("date", ""),
                })
                prospects[key]["touch_count"] += 1
            if dm.get("date"):
                prospects[key]["last_contact_date"] = dm["date"]

    # Post interactions
    if linkedin_posts:
        for post in linkedin_posts.get("posts", []):
            for interaction in post.get("interactions", post.get("engagements", [])):
                name = interaction.get("name", interaction.get("author", ""))
                key = ensure(name)
                if not key:
                    continue
                itype = interaction.get("type", "like").lower()
                if "comment" in itype:
                    prospects[key]["signals"].append({
                        "type": "Comment on post",
                        "weight": SIGNAL_WEIGHTS["comment_on_post"],
                        "date": interaction.get("date", ""),
                    })
                elif "like" in itype:
                    prospects[key]["signals"].append({
                        "type": "Like on post",
                        "weight": SIGNAL_WEIGHTS["like_on_post"],
                        "date": interaction.get("date", ""),
                    })

    # Gmail
    if gmail:
        for email in gmail.get("emails", []):
            sender = email.get("from_name", email.get("sender", ""))
            if email.get("direction") == "inbound" or email.get("is_reply"):
                key = ensure(sender)
                if key:
                    prospects[key]["signals"].append({
                        "type": "Email reply",
                        "weight": SIGNAL_WEIGHTS["email_reply"],
                        "date": email.get("date", ""),
                    })

    # Notion contacts (enrich with sector, notion_id, last_contact)
    if notion:
        for contact in notion.get("contacts", []):
            name = contact.get("name", "")
            key = ensure(name, contact.get("id", ""))
            if not key:
                continue
            prospects[key]["notion_id"] = contact.get("id", prospects[key]["notion_id"])
            prospects[key]["sector"] = contact.get("sector", contact.get("industry", ""))
            if contact.get("last_interaction"):
                prospects[key]["last_contact_date"] = contact["last_interaction"]
            prospects[key]["touch_count"] = max(
                prospects[key]["touch_count"],
                contact.get("touch_count", 0),
            )

    return prospects


def score_prospect(prospect, today, cadence_config):
    """Calculate temperature score for a single prospect."""
    raw_score = sum(s["weight"] for s in prospect["signals"])

    # Inactivity penalty
    days_since = None
    if prospect["last_contact_date"]:
        try:
            last = datetime.strptime(prospect["last_contact_date"][:10], "%Y-%m-%d")
            days_since = (today - last).days
            if days_since >= 30:
                raw_score += SIGNAL_WEIGHTS["no_contact_30d"]
            elif days_since >= 14:
                raw_score += SIGNAL_WEIGHTS["no_contact_14d"]
        except ValueError:
            pass

    # Regulated sector bonus
    sector = prospect["sector"].lower()
    if any(s in sector for s in REGULATED_SECTORS):
        raw_score += SIGNAL_WEIGHTS["regulated_sector"]

    # Temperature bucket
    temperature = "Cold"
    for bucket, check in TEMPERATURE_BUCKETS.items():
        if check(raw_score):
            temperature = bucket
            break

    # Auto-close flag
    flag_auto_close = False
    rule = None
    if days_since is not None:
        if (days_since >= cadence_config["auto_close_days"]
                and prospect["touch_count"] >= cadence_config["auto_close_touches"]):
            flag_auto_close = True
            rule = "cadence-auto-close"

    return {
        "name": prospect["name"],
        "notion_id": prospect["notion_id"],
        "raw_score": raw_score,
        "temperature": temperature,
        "trend": "flat",  # would need historical data for trend
        "signals": prospect["signals"],
        "days_since_last_contact": days_since if days_since is not None else -1,
        "flag_auto_close": flag_auto_close,
        "rule": rule,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 temperature-scoring.py <date> [--json]", file=sys.stderr)
        sys.exit(2)

    date = sys.argv[1]
    json_output = "--json" in sys.argv
    bus_dir = os.path.join(BUS_BASE, date)

    if not os.path.isdir(bus_dir):
        print(f"Bus directory not found: {bus_dir}", file=sys.stderr)
        sys.exit(1)

    today = datetime.strptime(date, "%Y-%m-%d")
    cadence_config = parse_cadence_config()

    # Read bus files
    linkedin_dms = read_bus_file(bus_dir, "linkedin-dms.json")
    linkedin_posts = read_bus_file(bus_dir, "linkedin-posts.json")
    gmail = read_bus_file(bus_dir, "gmail.json")
    notion = read_bus_file(bus_dir, "crm.json")

    missing = []
    if not linkedin_dms:
        missing.append("linkedin-dms.json")
    if not linkedin_posts:
        missing.append("linkedin-posts.json")
    if not gmail:
        missing.append("gmail.json")
    if not notion:
        missing.append("crm.json")

    if missing:
        print(f"Note: Missing bus files (continuing with available): {', '.join(missing)}")

    # Extract and score
    prospects = extract_prospects(linkedin_dms, linkedin_posts, gmail, notion)
    scores = []
    for key in sorted(prospects.keys()):
        scored = score_prospect(prospects[key], today, cadence_config)
        if scored["signals"]:  # Only include prospects with signals
            scores.append(scored)

    # Sort by raw score descending
    scores.sort(key=lambda x: x["raw_score"], reverse=True)

    # Summary
    summary = {
        "hot": sum(1 for s in scores if s["temperature"] == "Hot"),
        "warm": sum(1 for s in scores if s["temperature"] == "Warm"),
        "cool": sum(1 for s in scores if s["temperature"] == "Cool"),
        "cold": sum(1 for s in scores if s["temperature"] == "Cold"),
        "flagged_for_close": sum(1 for s in scores if s["flag_auto_close"]),
    }

    result = {
        "date": date,
        "scores": scores,
        "summary": summary,
    }

    # Write output
    output_path = os.path.join(bus_dir, "temperature.json")
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        print(f"Temperature scoring ({date}):")
        print(f"  Prospects scored: {len(scores)}")
        print(f"  Hot: {summary['hot']}, Warm: {summary['warm']}, Cool: {summary['cool']}, Cold: {summary['cold']}")
        print(f"  Flagged for auto-close: {summary['flagged_for_close']}")
        print(f"  Written to {output_path}")

    sys.exit(0)


if __name__ == "__main__":
    main()
