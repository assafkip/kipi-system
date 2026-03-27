from datetime import datetime
from pathlib import Path
import json


class StepLogger:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def _log_path(self, date: str) -> Path:
        return self.output_dir / f"morning-log-{date}.json"

    def _load(self, date: str) -> dict:
        path = self._log_path(date)
        if not path.exists():
            raise FileNotFoundError(f"No log file for {date}: {path}")
        return json.loads(path.read_text())

    def _save(self, date: str, data: dict) -> None:
        self._log_path(date).write_text(json.dumps(data, indent=2) + "\n")

    def init(self, date: str) -> dict:
        path = self._log_path(date)
        data = {
            "date": date,
            "session_start": datetime.now().isoformat(),
            "steps": {},
            "action_cards": [],
            "state_checksums": {
                "session_start": {},
                "session_end": {},
                "drift_detected": [],
            },
            "verification_queue": [],
            "gates_checked": {},
            "audit": None,
        }
        self._save(date, data)
        return {"created": str(path)}

    def log_step(self, date: str, step_id: str, status: str, result: str = "", error: str = "") -> dict:
        data = self._load(date)
        data["steps"][step_id] = {
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "result": result or None,
            "error": error or None,
        }
        self._save(date, data)
        return {"step_id": step_id, "status": status}

    def add_card(self, date: str, card_id: str, card_type: str, target: str, draft_text: str, url: str = "") -> dict:
        data = self._load(date)
        data["action_cards"].append({
            "id": card_id,
            "type": card_type,
            "target": target,
            "draft_text": draft_text[:200],
            "url": url or None,
            "card_delivered": False,
            "founder_confirmed": False,
            "logged_to": [],
        })
        self._save(date, data)
        return {"card_id": card_id, "target": target}

    def deliver_cards(self, date: str) -> dict:
        data = self._load(date)
        count = 0
        for card in data["action_cards"]:
            if not card["card_delivered"]:
                card["card_delivered"] = True
                count += 1
        self._save(date, data)
        return {"delivered": count}

    def gate_check(self, date: str, gate_step: str, all_prior_done: bool, missing: str = "") -> dict:
        data = self._load(date)
        data["gates_checked"][gate_step] = {
            "checked": True,
            "all_prior_done": all_prior_done,
            "missing": [s.strip() for s in missing.split(",") if s.strip()] if missing else [],
        }
        self._save(date, data)
        return {"gate_step": gate_step, "passed": all_prior_done}

    def checksum(self, date: str, phase: str, key: str, value: str) -> dict:
        data = self._load(date)
        data["state_checksums"][f"session_{phase}"][key] = value
        if phase == "end":
            start_val = data["state_checksums"]["session_start"].get(key)
            if start_val is not None and start_val != value:
                data["state_checksums"]["drift_detected"].append(key)
        self._save(date, data)
        return {"phase": phase, "key": key, "value": value}

    def verify(self, date: str, claim: str, source: str, verified: bool, result: str = "") -> dict:
        data = self._load(date)
        entry = {
            "claim": claim,
            "source_file": source,
            "verified": verified,
            "verification_method": "",
            "result": result or None,
        }
        for i, existing in enumerate(data["verification_queue"]):
            if existing["claim"] == claim:
                data["verification_queue"][i] = entry
                break
        else:
            data["verification_queue"].append(entry)
        self._save(date, data)
        return {"claim": claim, "verified": verified}
