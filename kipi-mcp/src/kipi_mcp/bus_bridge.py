from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


BUS_TO_STEPS: dict[str, list[str]] = {
    "preflight.json": [
        "0a_checkpoint", "0b_missed_debrief", "0b.5_loop_escalation",
        "0c_load_canonical", "0d_load_voice", "0e_load_audhd", "0f_connection_check",
    ],
    "calendar.json": ["1_calendar"],
    "gmail.json": ["1_gmail"],
    "notion.json": ["1_notion_actions", "1_notion_pipeline"],
    "meeting-prep.json": [],
    "linkedin-posts.json": ["3_linkedin_activity"],
    "linkedin-dms.json": ["3.8_dm_check"],
    "dp-pipeline.json": ["3.5_dp_pipeline"],
    "signals.json": ["4_signals_linkedin", "4_x_signals", "4_x_hot_take", "4_x_bts"],
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
    "kipi-promo.json": ["4_kipi_promo"],
    "canonical-digest.json": ["0c_canonical_digest"],
    "content-metrics.json": ["1b_content_metrics"],
    "copy-diffs.json": ["1c_copy_diff"],
    "behavioral-signals.json": ["3b_behavioral_signals"],
    "prospect-activity.json": ["3c_prospect_activity"],
    "outreach-queue.json": ["7b_outreach_queue"],
}


class BusBridge:
    def __init__(self, bus_dir: Path, output_dir: Path):
        self._bus_dir = bus_dir
        self._output_dir = output_dir

    def bridge(self, date: str = "") -> dict:
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        bus_day = self._bus_dir / date
        if not bus_day.is_dir():
            raise ValueError(f"No bus directory for {date}: {bus_day}")

        now = datetime.now().strftime("%H:%M")
        steps: dict[str, dict] = {}

        for bus_file, step_ids in BUS_TO_STEPS.items():
            path = bus_day / bus_file
            exists = path.is_file()
            status = "done" if exists else "skipped"

            if exists:
                try:
                    data = json.loads(path.read_text())
                    if "error" in data:
                        status = "failed"
                except (json.JSONDecodeError, KeyError):
                    status = "failed"

            for step_id in step_ids:
                steps[step_id] = {"status": status, "timestamp": now, "bus_file": bus_file}

        schedule_path = self._output_dir / f"schedule-data-{date}.json"
        html_path = self._output_dir / f"daily-schedule-{date}.html"

        steps["8_briefing_output"] = {
            "status": "done" if schedule_path.is_file() else "skipped",
            "timestamp": now,
        }
        steps["11_html_output"] = {
            "status": "done" if html_path.is_file() else "skipped",
            "timestamp": now,
        }
        steps["8.5_start_here"] = {
            "status": "done" if html_path.is_file() else "skipped",
            "timestamp": now,
        }

        log = {
            "date": date,
            "steps": steps,
            "gates_checked": {},
            "action_cards": [],
            "state_checksums": {},
            "verification_queue": [],
        }

        self._output_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._output_dir / f"morning-log-{date}.json"
        log_path.write_text(json.dumps(log, indent=2))

        done = sum(1 for s in steps.values() if s["status"] == "done")
        return {"log_path": str(log_path), "date": date, "done": done, "total": len(steps)}
