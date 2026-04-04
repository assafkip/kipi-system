#!/usr/bin/env python3
"""Loop Tracker - closes loops that AUDHD opens.

Every outbound action (DM, email, comment, connection request) opens a loop.
The morning routine reads open loops and forces follow-up or explicit close.

Usage:
  python3 q-system/.q-system/loop-tracker.py open <type> <target> <context> [notion_id] [card_id] [follow_up_text]
  python3 q-system/.q-system/loop-tracker.py close <loop_id> <reason> <closed_by>
  python3 q-system/.q-system/loop-tracker.py escalate
  python3 q-system/.q-system/loop-tracker.py list [min_level]
  python3 q-system/.q-system/loop-tracker.py force-close <loop_id> <park|kill>
  python3 q-system/.q-system/loop-tracker.py stats
  python3 q-system/.q-system/loop-tracker.py prune [days]
  python3 q-system/.q-system/loop-tracker.py touch <loop_id>

Loop types: dm_sent, email_sent, materials_sent, comment_posted,
            action_created, debrief_next_step, dp_offer_sent,
            connection_request_sent, lead_sourced
"""

import json
import os
import sys
from datetime import datetime, timedelta

# Resolve QROOT from script location (../ from .q-system/)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
QROOT = os.path.join(SCRIPT_DIR, "..")
LOOP_FILE = os.path.join(QROOT, "output", "open-loops.json")


def load_data():
    if not os.path.exists(LOOP_FILE):
        return {"schema_version": 1, "loops": []}
    with open(LOOP_FILE) as f:
        return json.load(f)


def save_data(data):
    os.makedirs(os.path.dirname(LOOP_FILE), exist_ok=True)
    with open(LOOP_FILE, "w") as f:
        json.dump(data, f, indent=2)


def cmd_open(loop_type, target, context, notion_id="", card_id="", follow_up=""):
    data = load_data()

    # Check for duplicate: same target + type already open
    for loop in data["loops"]:
        if loop["target"] == target and loop["type"] == loop_type and loop["status"] == "open":
            loop["touch_count"] = loop.get("touch_count", 1) + 1
            if follow_up:
                loop["follow_up_text"] = follow_up
            save_data(data)
            print(f'Loop updated: {loop["id"]} touch #{loop["touch_count"]} -> {target}')
            return

    # Generate ID
    today = datetime.now().strftime("%Y-%m-%d")
    existing_today = [l for l in data["loops"] if l["id"].startswith(f"L-{today}")]
    counter = len(existing_today) + 1
    loop_id = f"L-{today}-{counter:03d}"

    loop = {
        "id": loop_id,
        "type": loop_type,
        "target": target,
        "target_notion_id": notion_id or None,
        "opened": today,
        "opened_by": "morning_routine",
        "action_card_id": card_id or None,
        "context": context,
        "channel": loop_type.replace("_sent", "").replace("_posted", "").replace("_created", "").replace("_sourced", ""),
        "touch_count": 1,
        "follow_up_text": follow_up or None,
        "escalation_level": 0,
        "last_escalated": None,
        "status": "open",
        "closed": None,
        "closed_by": None,
        "closed_reason": None,
    }

    data["loops"].append(loop)
    save_data(data)
    print(f"Loop opened: {loop_id} ({loop_type}) -> {target}")


def cmd_close(loop_id, reason, closed_by):
    data = load_data()
    found = False
    for loop in data["loops"]:
        if loop["id"] == loop_id and loop["status"] == "open":
            loop["status"] = "closed"
            loop["closed"] = datetime.now().strftime("%Y-%m-%d")
            loop["closed_by"] = closed_by
            loop["closed_reason"] = reason
            found = True
            break

    if found:
        save_data(data)
        print(f"Loop closed: {loop_id} ({closed_by}: {reason})")
    else:
        print(f"Loop not found or already closed: {loop_id}")


def cmd_force_close(loop_id, action):
    data = load_data()
    for loop in data["loops"]:
        if loop["id"] == loop_id and loop["status"] == "open":
            loop["status"] = f"{action}ed"
            loop["closed"] = datetime.now().strftime("%Y-%m-%d")
            loop["closed_by"] = "founder"
            loop["closed_reason"] = action
            break

    save_data(data)
    print(f"Loop force-closed: {loop_id} -> {action}")


def cmd_escalate():
    data = load_data()
    today = datetime.now()
    counts = {0: 0, 1: 0, 2: 0, 3: 0}

    for loop in data["loops"]:
        if loop["status"] != "open":
            continue
        opened = datetime.strptime(loop["opened"], "%Y-%m-%d")
        age = (today - opened).days

        if age >= 14:
            new_level = 3
        elif age >= 7:
            new_level = 2
        elif age >= 3:
            new_level = 1
        else:
            new_level = 0

        if new_level > loop.get("escalation_level", 0):
            loop["escalation_level"] = new_level
            loop["last_escalated"] = today.strftime("%Y-%m-%d")

        counts[loop["escalation_level"]] += 1

    save_data(data)
    total = sum(counts.values())
    print(f"Escalated: {total} open loops (L0:{counts[0]} L1:{counts[1]} L2:{counts[2]} L3:{counts[3]})")


def cmd_touch(loop_id):
    data = load_data()
    for loop in data["loops"]:
        if loop["id"] == loop_id and loop["status"] == "open":
            loop["touch_count"] = loop.get("touch_count", 1) + 1
            break

    save_data(data)
    print(f"Touch added: {loop_id}")


def cmd_list(min_level=0):
    data = load_data()
    today = datetime.now()
    for loop in sorted(data["loops"], key=lambda x: x.get("escalation_level", 0), reverse=True):
        if loop["status"] != "open":
            continue
        if loop.get("escalation_level", 0) < min_level:
            continue
        opened = datetime.strptime(loop["opened"], "%Y-%m-%d")
        age = (today - opened).days
        level = loop.get("escalation_level", 0)
        level_label = ["NEW", "WARM", "HOT", "FORCE"][level]
        ctx = loop["context"][:60]
        print(f'  [{level_label}] {loop["id"]} | {loop["type"]} | {loop["target"]} | {age}d | touches:{loop.get("touch_count", 1)} | {ctx}')


def cmd_stats():
    data = load_data()
    today = datetime.now()
    open_loops = [l for l in data["loops"] if l["status"] == "open"]
    closed_today = [l for l in data["loops"] if l.get("closed") == today.strftime("%Y-%m-%d")]
    counts = {0: 0, 1: 0, 2: 0, 3: 0}
    oldest = 0

    for loop in open_loops:
        level = loop.get("escalation_level", 0)
        counts[level] = counts.get(level, 0) + 1
        opened = datetime.strptime(loop["opened"], "%Y-%m-%d")
        age = (today - opened).days
        oldest = max(oldest, age)

    auto_closed = len([l for l in closed_today if l.get("closed_by", "").startswith("auto")])
    manual_closed = len([l for l in closed_today if l.get("closed_by") == "founder"])

    print(f"Open: {len(open_loops)} | Closed today: {len(closed_today)} ({auto_closed} auto, {manual_closed} manual)")
    print(f"L0:{counts[0]} L1:{counts[1]} L2:{counts[2]} L3:{counts[3]} | Oldest: {oldest}d")


def cmd_prune(days=30):
    data = load_data()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    before = len(data["loops"])
    data["loops"] = [l for l in data["loops"] if l["status"] == "open" or (l.get("closed", "9999") > cutoff)]
    after = len(data["loops"])
    save_data(data)
    print(f"Pruned: {before - after} loops older than {days} days. {after} remaining.")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 q-system/.q-system/loop-tracker.py <open|close|force-close|escalate|touch|list|stats|prune> [args...]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "open":
        cmd_open(
            sys.argv[2], sys.argv[3], sys.argv[4],
            sys.argv[5] if len(sys.argv) > 5 else "",
            sys.argv[6] if len(sys.argv) > 6 else "",
            sys.argv[7] if len(sys.argv) > 7 else "",
        )
    elif cmd == "close":
        cmd_close(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "force-close":
        cmd_force_close(sys.argv[2], sys.argv[3])
    elif cmd == "escalate":
        cmd_escalate()
    elif cmd == "touch":
        cmd_touch(sys.argv[2])
    elif cmd == "list":
        cmd_list(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    elif cmd == "stats":
        cmd_stats()
    elif cmd == "prune":
        cmd_prune(int(sys.argv[2]) if len(sys.argv) > 2 else 30)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print("Usage: python3 q-system/.q-system/loop-tracker.py <open|close|force-close|escalate|touch|list|stats|prune> [args...]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
