from datetime import datetime, timedelta
from pathlib import Path
import json


class LoopTracker:
    def __init__(self, loop_file: Path):
        self._path = loop_file

    def _load(self) -> dict:
        if not self._path.exists():
            data = {"schema_version": 1, "loops": []}
            self._save(data)
            return data
        return json.loads(self._path.read_text())

    def _save(self, data: dict) -> None:
        self._path.write_text(json.dumps(data, indent=2))

    def open(
        self,
        loop_type: str,
        target: str,
        context: str,
        notion_id: str = "",
        card_id: str = "",
        follow_up_text: str = "",
    ) -> dict:
        data = self._load()
        today = datetime.now().strftime("%Y-%m-%d")

        for loop in data["loops"]:
            if loop["target"] == target and loop["type"] == loop_type and loop["status"] == "open":
                loop["touch_count"] += 1
                if follow_up_text:
                    loop["follow_up_text"] = follow_up_text
                self._save(data)
                return {"action": "updated", "loop_id": loop["id"], "touch_count": loop["touch_count"]}

        counter = sum(1 for l in data["loops"] if l["opened"] == today) + 1
        channel = loop_type.replace("_sent", "").replace("_posted", "").replace("_created", "").replace("_sourced", "")
        new_loop = {
            "id": f"L-{today}-{counter:03d}",
            "type": loop_type,
            "target": target,
            "target_notion_id": notion_id or None,
            "opened": today,
            "opened_by": "morning_routine",
            "action_card_id": card_id or None,
            "context": context,
            "channel": channel,
            "touch_count": 1,
            "follow_up_text": follow_up_text or None,
            "escalation_level": 0,
            "last_escalated": None,
            "status": "open",
            "closed": None,
            "closed_by": None,
            "closed_reason": None,
        }
        data["loops"].append(new_loop)
        self._save(data)
        return {"action": "opened", "loop_id": new_loop["id"]}

    def close(self, loop_id: str, reason: str, closed_by: str) -> dict:
        data = self._load()
        today = datetime.now().strftime("%Y-%m-%d")
        for loop in data["loops"]:
            if loop["id"] == loop_id and loop["status"] == "open":
                loop["status"] = "closed"
                loop["closed"] = today
                loop["closed_by"] = closed_by
                loop["closed_reason"] = reason
                self._save(data)
                return {"closed": True, "loop_id": loop_id}
        return {"closed": False, "error": "not found or already closed"}

    def force_close(self, loop_id: str, action: str) -> dict:
        data = self._load()
        today = datetime.now().strftime("%Y-%m-%d")
        for loop in data["loops"]:
            if loop["id"] == loop_id and loop["status"] == "open":
                loop["status"] = f"{action}ed"
                loop["closed"] = today
                loop["closed_by"] = "founder"
                loop["closed_reason"] = action
                self._save(data)
                return {"force_closed": True, "loop_id": loop_id, "action": action}
        return {"force_closed": False, "loop_id": loop_id, "action": action}

    def escalate(self) -> dict:
        data = self._load()
        today = datetime.now().strftime("%Y-%m-%d")
        today_dt = datetime.strptime(today, "%Y-%m-%d")
        levels = {"0": 0, "1": 0, "2": 0, "3": 0}
        total_open = 0

        for loop in data["loops"]:
            if loop["status"] != "open":
                continue
            total_open += 1
            opened_dt = datetime.strptime(loop["opened"], "%Y-%m-%d")
            age = (today_dt - opened_dt).days
            if age >= 14:
                new_level = 3
            elif age >= 7:
                new_level = 2
            elif age >= 3:
                new_level = 1
            else:
                new_level = 0
            if new_level > loop["escalation_level"]:
                loop["escalation_level"] = new_level
                loop["last_escalated"] = today
            levels[str(loop["escalation_level"])] += 1

        self._save(data)
        return {"total_open": total_open, "levels": levels}

    def touch(self, loop_id: str) -> dict:
        data = self._load()
        for loop in data["loops"]:
            if loop["id"] == loop_id and loop["status"] == "open":
                loop["touch_count"] += 1
                self._save(data)
                return {"loop_id": loop_id, "touch_count": loop["touch_count"]}
        return {"loop_id": loop_id, "error": "not found or not open"}

    def list(self, min_level: int = 0) -> list[dict]:
        data = self._load()
        today_dt = datetime.now()
        result = []
        for loop in data["loops"]:
            if loop["status"] != "open":
                continue
            if loop["escalation_level"] < min_level:
                continue
            opened_dt = datetime.strptime(loop["opened"], "%Y-%m-%d")
            age = (today_dt - opened_dt).days
            result.append({
                "id": loop["id"],
                "type": loop["type"],
                "target": loop["target"],
                "age_days": age,
                "escalation_level": loop["escalation_level"],
                "touch_count": loop["touch_count"],
                "context": loop["context"],
            })
        result.sort(key=lambda x: x["escalation_level"], reverse=True)
        return result

    def stats(self) -> dict:
        data = self._load()
        today = datetime.now().strftime("%Y-%m-%d")
        today_dt = datetime.now()
        open_count = 0
        closed_today = 0
        levels = {"0": 0, "1": 0, "2": 0, "3": 0}
        oldest_days = 0

        for loop in data["loops"]:
            if loop["status"] == "open":
                open_count += 1
                levels[str(loop["escalation_level"])] += 1
                opened_dt = datetime.strptime(loop["opened"], "%Y-%m-%d")
                age = (today_dt - opened_dt).days
                if age > oldest_days:
                    oldest_days = age
            elif loop.get("closed") == today:
                closed_today += 1

        return {"open": open_count, "closed_today": closed_today, "levels": levels, "oldest_days": oldest_days}

    def prune(self, days: int = 30) -> dict:
        data = self._load()
        today_dt = datetime.now()
        cutoff = today_dt - timedelta(days=days)
        kept = []
        pruned = 0
        for loop in data["loops"]:
            if loop["status"] != "open" and loop.get("closed"):
                closed_dt = datetime.strptime(loop["closed"], "%Y-%m-%d")
                if closed_dt < cutoff:
                    pruned += 1
                    continue
            kept.append(loop)
        data["loops"] = kept
        self._save(data)
        return {"pruned": pruned, "remaining": len(kept)}
