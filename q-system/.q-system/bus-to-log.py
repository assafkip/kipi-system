#!/usr/bin/env python3
"""Bridge bus/ JSON files to morning-log.json for the audit harness."""
import json, glob, os, sys
from datetime import datetime

date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
bus_dir = f"q-system/.q-system/agent-pipeline/bus/{date}"
log_path = f"q-system/output/morning-log-{date}.json"

if not os.path.isdir(bus_dir):
    print(f"No bus directory for {date}")
    sys.exit(1)

# Map bus files to step IDs the audit harness expects
bus_to_steps = {
    "preflight.json": ["0a_checkpoint", "0b_missed_debrief", "0b.5_loop_escalation",
                        "0c_load_canonical", "0d_load_voice", "0e_load_audhd", "0f_connection_check"],
    "calendar.json": ["1_calendar"],
    "gmail.json": ["1_gmail"],
    "notion.json": ["1_notion_actions", "1_notion_pipeline"],
    "meeting-prep.json": [],
    "linkedin-posts.json": ["3_linkedin_activity"],
    "linkedin-dms.json": ["3.8_dm_check"],
    "prospect-pipeline.json": ["3.5_prospect_pipeline"],
    "signals.json": ["4_signals_linkedin", "4_x_signals", "4_x_hot_take"],
    "value-routing.json": ["4.1_value_drops"],
    "temperature.json": ["5.8_temperature_scoring"],
    "leads.json": ["5.9_lead_sourcing"],
    "hitlist.json": ["5.9b_engagement_hitlist"],
    "compliance.json": ["6_decision_compliance"],
    "positioning.json": ["7_positioning_freshness"],
    "loop-review.json": ["5.86_loop_review"],
    "pipeline-followup.json": ["5.85_pipeline_followup"],
    "notion-push.json": ["9_notion_push"],
    "daily-checklists.json": ["10_daily_checklists"],
    "founder-brand-post.json": ["4_founder_brand_post"],
}

steps = {}
now = datetime.now().strftime("%H:%M")

for bus_file, step_ids in bus_to_steps.items():
    path = os.path.join(bus_dir, bus_file)
    exists = os.path.isfile(path)
    status = "done" if exists else "skipped"

    # Check for error key in the file
    if exists:
        try:
            with open(path) as f:
                data = json.load(f)
            if "error" in data:
                status = "failed"
        except (json.JSONDecodeError, KeyError):
            status = "failed"

    for step_id in step_ids:
        steps[step_id] = {
            "status": status,
            "timestamp": now,
            "bus_file": bus_file
        }

# Add build steps
schedule_path = f"q-system/output/schedule-data-{date}.json"
html_path = f"q-system/output/daily-schedule-{date}.html"

steps["8_briefing_output"] = {
    "status": "done" if os.path.isfile(schedule_path) else "skipped",
    "timestamp": now
}
steps["11_html_output"] = {
    "status": "done" if os.path.isfile(html_path) else "skipped",
    "timestamp": now
}
steps["8.5_start_here"] = {
    "status": "done" if os.path.isfile(html_path) else "skipped",
    "timestamp": now
}

# Write the log
log = {
    "date": date,
    "steps": steps,
    "gates_checked": {},
    "action_cards": [],
    "state_checksums": {},
    "verification_queue": []
}

os.makedirs(os.path.dirname(log_path), exist_ok=True)

with open(log_path, "w") as f:
    json.dump(log, f, indent=2)

done = sum(1 for s in steps.values() if s["status"] == "done")
total = len(steps)
print(f"Wrote {log_path}: {done}/{total} steps logged from bus/ files")
