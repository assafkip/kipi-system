#!/usr/bin/env python3
"""
Collection gate: decides skip/collect per data source based on staleness.

Usage:
    python3 collection-gate.py <date> [--json]

Reads: q-system/memory/collection-state.json
Writes: bus/{date}/collection-gate.json

Exit codes:
    0 = gate verdicts written successfully
    1 = error writing output
    2 = argument error
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
STATE_PATH = os.path.join(QROOT, "memory", "collection-state.json")
BUS_BASE = os.path.join(QROOT, ".q-system", "agent-pipeline", "bus")

# Default staleness thresholds in hours
THRESHOLDS = {
    "calendar": 4,
    "gmail": 2,
    "crm": 6,
    "x-activity": 8,
    "linkedin-posts": 8,
    "linkedin-dms": 4,
    "lead-sourcing": 12,
}


def load_state():
    """Load persistent collection state. Returns empty sources on any error."""
    if not os.path.isfile(STATE_PATH):
        return {"sources": {}}
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"sources": {}}


def evaluate_source(source, threshold_hours, source_state, bus_dir, date, now):
    """Evaluate a single source and return its verdict dict."""
    last_collected_str = source_state.get("last_collected")
    last_bus_date = source_state.get("last_bus_date")
    bus_file = source_state.get("bus_file", f"{source}.json")

    verdict = "collect"
    reason = "no prior collection recorded"
    since = None

    if not last_collected_str or not last_bus_date:
        return {
            "verdict": verdict,
            "reason": reason,
            "threshold_hours": threshold_hours,
            "since": since,
        }

    try:
        last_collected = datetime.fromisoformat(last_collected_str)
        age = now - last_collected
        threshold = timedelta(hours=threshold_hours)
        bus_file_path = os.path.join(bus_dir, bus_file)
        file_exists_today = os.path.isfile(bus_file_path)

        if last_bus_date == date and file_exists_today and age < threshold:
            verdict = "skip"
            hours_ago = age.total_seconds() / 3600
            reason = (
                f"collected {hours_ago:.1f}h ago "
                f"(threshold: {threshold_hours}h), bus file exists"
            )
        elif last_bus_date == date and file_exists_today:
            hours_ago = age.total_seconds() / 3600
            reason = (
                f"stale: collected {hours_ago:.1f}h ago "
                f"(threshold: {threshold_hours}h)"
            )
            since = last_collected_str
        elif last_bus_date != date:
            reason = f"no collection yet for {date} (last was {last_bus_date})"
            since = last_collected_str
        else:
            reason = "bus file missing for today despite state entry"
    except (ValueError, TypeError):
        reason = "invalid timestamp in state"

    return {
        "verdict": verdict,
        "reason": reason,
        "threshold_hours": threshold_hours,
        "since": since,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: collection-gate.py <date> [--json]", file=sys.stderr)
        sys.exit(2)

    date = sys.argv[1]
    json_flag = "--json" in sys.argv
    now = datetime.now(timezone.utc)

    bus_dir = os.path.join(BUS_BASE, date)
    os.makedirs(bus_dir, exist_ok=True)

    state = load_state()
    sources = state.get("sources", {})

    verdicts = {}
    for source, threshold_hours in THRESHOLDS.items():
        source_state = sources.get(source, {})
        verdicts[source] = evaluate_source(
            source, threshold_hours, source_state, bus_dir, date, now
        )

    skip_count = sum(1 for v in verdicts.values() if v["verdict"] == "skip")
    collect_count = sum(1 for v in verdicts.values() if v["verdict"] == "collect")

    output = {
        "bus_version": 1,
        "date": date,
        "generated_by": "collection-gate",
        "gate_timestamp": now.isoformat(),
        "verdicts": verdicts,
        "summary": {
            "skip_count": skip_count,
            "collect_count": collect_count,
        },
    }

    output_path = os.path.join(bus_dir, "collection-gate.json")
    try:
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)
    except OSError as e:
        print(f"ERROR: Failed to write {output_path}: {e}", file=sys.stderr)
        sys.exit(1)

    if json_flag:
        print(json.dumps(output, indent=2))
    else:
        print(f"Collection gate: {output_path}")
        for src, v in verdicts.items():
            status = "SKIP" if v["verdict"] == "skip" else "COLLECT"
            print(f"  {status:7s} {src}: {v['reason']}")
        print(f"  Total: {skip_count} skip, {collect_count} collect")

    sys.exit(0)


if __name__ == "__main__":
    main()
