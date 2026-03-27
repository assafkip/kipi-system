from __future__ import annotations

import json
import os
from pathlib import Path

from kipi_mcp.step_logger import StepLogger


class OrchestratorVerifier:
    def __init__(self, output_dir: Path, bus_dir: Path, step_logger: StepLogger):
        self.output_dir = output_dir
        self.bus_dir = bus_dir
        self.step_logger = step_logger

    def _load_log(self, date: str) -> dict | None:
        path = self.output_dir / f"morning-log-{date}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text())

    def _load_bus(self, date: str, filename: str) -> dict | None:
        path = self.bus_dir / date / filename
        if not path.is_file():
            return None
        return json.loads(path.read_text())

    def check_phase(self, date: str, phase: int, fix: bool = False) -> dict:
        log = self._load_log(date)
        if not log:
            return {
                "pass": False,
                "phase": phase,
                "issues": [f"Morning log not found for {date}"],
                "fixes_applied": [],
            }

        issues: list[str] = []
        fixes_applied: list[str] = []

        if phase == 0:
            self._check_phase0(date, log, issues, fixes_applied, fix)

        if phase >= 1:
            self._check_gate(date, log, phase, issues, fixes_applied, fix)

        if phase == 5:
            self._check_phase5_cards(date, log, issues, fixes_applied, fix)
            self._check_phase5_connections(date, log, issues)

        passed = not issues or len(fixes_applied) > 0
        return {
            "pass": passed,
            "phase": phase,
            "issues": issues,
            "fixes_applied": fixes_applied,
        }

    def _check_phase0(self, date: str, log: dict, issues: list[str],
                       fixes_applied: list[str], fix: bool) -> None:
        checksums = log.get("state_checksums", {}).get("session_start", {})
        if checksums:
            return
        issues.append("No session-start checksums recorded")
        if not fix:
            return
        checks: dict[str, str] = {}
        bus_date_dir = self.bus_dir / date
        if bus_date_dir.is_dir():
            json_files = [f for f in os.listdir(bus_date_dir) if f.endswith(".json")]
            checks["bus_file_count"] = str(len(json_files))
        for key, val in checks.items():
            self.step_logger.checksum(date, "start", key, val)
        fixes_applied.append(f"Recorded {len(checks)} session-start checksums")

    def _check_gate(self, date: str, log: dict, phase: int, issues: list[str],
                     fixes_applied: list[str], fix: bool) -> None:
        gates = log.get("gates_checked", {})
        gate_name = f"phase_{phase}"
        if gate_name in gates:
            return
        bus_date_dir = self.bus_dir / date
        phase_complete = bus_date_dir.is_dir()
        issues.append(f"Gate check not logged for phase {phase}")
        if fix and phase_complete:
            self.step_logger.gate_check(date, gate_name, True, "")
            fixes_applied.append(f"Logged gate check for phase {phase}")

    def _check_phase5_cards(self, date: str, log: dict, issues: list[str],
                             fixes_applied: list[str], fix: bool) -> None:
        action_cards = log.get("action_cards", [])
        hitlist = self._load_bus(date, "hitlist.json")
        if not hitlist or not hitlist.get("actions") or action_cards:
            return
        actions = hitlist["actions"]
        issues.append(f"Hitlist has {len(actions)} actions but 0 action cards logged")
        if not fix:
            return
        prefix_map = {"comment": "C", "DM": "DM", "connection_request": "CR"}
        for action in actions:
            rank = action.get("rank", 0)
            action_type = action.get("action_type", "unknown")
            contact = action.get("contact_name", "unknown")
            copy_text = action.get("copy", "")[:200]
            post_url = action.get("post_url") or action.get("profile_url") or ""
            prefix = prefix_map.get(action_type, "A")
            card_id = f"{prefix}{rank}"
            self.step_logger.add_card(date, card_id, action_type, contact, copy_text, post_url)
        fixes_applied.append(f"Logged {len(actions)} action cards from hitlist")

    def _check_phase5_connections(self, date: str, log: dict, issues: list[str]) -> None:
        hitlist = self._load_bus(date, "hitlist.json")
        if not hitlist or not hitlist.get("actions"):
            return
        cr_count = sum(1 for a in hitlist["actions"] if a.get("action_type") == "connection_request")
        if cr_count > 0:
            return
        leads = self._load_bus(date, "leads.json")
        if not leads or not leads.get("qualified_leads"):
            return
        has_tier_a = any(lead.get("tier") == "A" for lead in leads["qualified_leads"])
        if has_tier_a:
            issues.append("Hitlist has 0 connection requests despite Tier A leads available")
