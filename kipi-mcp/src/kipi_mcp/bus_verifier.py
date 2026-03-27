from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class BusVerifier:
    def __init__(self, bus_dir: Path):
        self._bus_dir = bus_dir

    def verify(self, date: str, phase: int) -> dict:
        bus_day = self._bus_dir / date

        if not bus_day.is_dir():
            return {
                "pass": False,
                "phase": phase,
                "date": date,
                "results": [{"status": "fail", "type": "required", "file": "",
                              "detail": f"Bus directory does not exist: {bus_day}"}],
            }

        spec = self._phase_specs().get(phase)
        if spec is None:
            return {"pass": True, "phase": phase, "date": date, "results": []}

        required = list(spec.get("required", []))
        optional = list(spec.get("optional", []))
        checks = spec.get("checks", {})

        day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A").lower()
        if phase == 4 and day_name in ("tuesday", "thursday"):
            if "tl-content.json" in optional:
                optional.remove("tl-content.json")
            if "tl-content.json" not in required:
                required.append("tl-content.json")

        results: list[dict] = []
        all_pass = True

        for f in required:
            path = bus_day / f
            if not path.is_file():
                results.append({"status": "fail", "type": "required", "file": f, "detail": "MISSING"})
                all_pass = False
                continue
            try:
                data = json.loads(path.read_text())
                if "error" in data:
                    results.append({"status": "warn", "type": "required", "file": f,
                                    "detail": f"has error key ({data['error']})"})
                elif f in checks and not checks[f](data):
                    results.append({"status": "fail", "type": "required", "file": f,
                                    "detail": "structure check failed"})
                    all_pass = False
                else:
                    results.append({"status": "ok", "type": "required", "file": f, "detail": ""})
            except json.JSONDecodeError as e:
                results.append({"status": "fail", "type": "required", "file": f,
                                "detail": f"invalid JSON ({e})"})
                all_pass = False

        for f in optional:
            path = bus_day / f
            if not path.is_file():
                results.append({"status": "skip", "type": "optional", "file": f, "detail": "not present"})
                continue
            try:
                data = json.loads(path.read_text())
                if "error" in data:
                    results.append({"status": "warn", "type": "optional", "file": f,
                                    "detail": "has error key"})
                elif f in checks and not checks[f](data):
                    results.append({"status": "warn", "type": "optional", "file": f,
                                    "detail": "structure check failed"})
                else:
                    results.append({"status": "ok", "type": "optional", "file": f, "detail": ""})
            except json.JSONDecodeError:
                results.append({"status": "warn", "type": "optional", "file": f,
                                "detail": "invalid JSON"})

        return {"pass": all_pass, "phase": phase, "date": date, "results": results}

    @staticmethod
    def _phase_specs() -> dict:
        return {
            0: {
                "required": ["preflight.json", "energy.json"],
                "checks": {
                    "preflight.json": lambda d: d.get("ready") is True,
                    "energy.json": lambda d: d.get("level") in range(1, 6),
                },
            },
            1: {
                "required": ["calendar.json", "gmail.json", "notion.json"],
                "optional": ["vc-pipeline.json", "content-metrics.json", "copy-diffs.json"],
                "checks": {
                    "calendar.json": lambda d: "today" in d or "this_week" in d,
                    "gmail.json": lambda d: "emails" in d,
                    "notion.json": lambda d: "contacts" in d and "actions" in d,
                    "canonical-digest.json": lambda d: "talk_tracks" in d and "objections" in d and "decisions" in d,
                },
            },
            2: {
                "required": ["meeting-prep.json", "warm-intros.json"],
                "checks": {},
            },
            3: {
                "required": ["linkedin-posts.json", "linkedin-dms.json", "dp-pipeline.json"],
                "optional": ["behavioral-signals.json", "prospect-activity.json"],
                "checks": {
                    "linkedin-posts.json": lambda d: "posts" in d,
                    "linkedin-dms.json": lambda d: "dms" in d,
                    "behavioral-signals.json": lambda d: "signals" in d,
                },
            },
            4: {
                "required": ["signals.json"],
                "optional": ["value-routing.json", "post-visuals.json", "promo.json", "tl-content.json"],
                "checks": {
                    "signals.json": lambda d: "selected_signal" in d or "linkedin_draft" in d,
                },
            },
            5: {
                "required": ["temperature.json", "leads.json", "hitlist.json"],
                "optional": ["pipeline-followup.json", "loop-review.json"],
                "checks": {
                    "hitlist.json": lambda d: "actions" in d and len(d["actions"]) > 0,
                    "temperature.json": lambda d: "scores" in d or "prospects" in d,
                },
            },
            6: {
                "required": ["compliance.json", "positioning.json"],
                "checks": {
                    "compliance.json": lambda d: "overall_pass" in d or "items_checked" in d,
                },
            },
            7: {
                "required": [],
                "optional": ["outreach-queue.json"],
                "checks": {
                    "outreach-queue.json": lambda d: "queue" in d,
                },
            },
            9: {
                "required": [],
                "optional": ["notion-push.json", "daily-checklists.json"],
                "checks": {},
            },
        }
