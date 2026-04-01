from __future__ import annotations

from datetime import datetime

_VALID_ENERGY = {"quickwin", "deepfocus", "people", "admin"}
_VALID_TIME = {"2 min", "5 min", "10 min", "15 min", "30 min", "45 min", "60 min"}

_SECTION_ORDER = [
    "quick-wins",
    "open-loops",
    "pipeline-followups",
    "linkedin-engagement",
    "new-leads",
    "special-outreach",
    "posts",
    "emails",
    "meeting-prep",
    "fyi",
]


class ScheduleVerifier:

    def verify(self, data: dict, day: str = "") -> dict:
        if not data.get("date"):
            raise ValueError("Missing 'date' field")
        if not data.get("sections"):
            raise ValueError("Missing 'sections' array")

        if not day:
            day = datetime.strptime(data["date"], "%Y-%m-%d").strftime("%A").lower()

        errors: list[str] = []
        warnings: list[str] = []
        section_ids = [s.get("id") for s in data["sections"]]

        self._check_pipeline_followups(data, errors, warnings)
        self._check_quick_wins(data, warnings)
        self._check_day_content(data, day, errors, warnings)
        self._check_section_ordering(section_ids, errors)
        self._check_energy_tags(data, warnings)
        self._check_today_focus(data, warnings)

        return {"pass": len(errors) == 0, "errors": errors, "warnings": warnings}

    def _get_section(self, data: dict, section_id: str) -> dict | None:
        for s in data.get("sections", []):
            if s.get("id") == section_id:
                return s
        return None

    def _check_pipeline_followups(self, data: dict, errors: list[str], warnings: list[str]) -> None:
        pf = self._get_section(data, "pipeline-followups")
        if not pf:
            errors.append(
                "MISSING SECTION: 'pipeline-followups' is REQUIRED. "
                "Phase 4 pipeline-followup agent must generate follow-up copy."
            )
            return

        items = pf.get("items", [])
        count = len(items)
        if count < 3:
            warnings.append(
                f"Pipeline follow-ups has {count} items (target 3+). "
                f"Check Notion for warm prospects that may have been missed."
            )

        missing = []
        for item in items:
            blocks = item.get("copyBlocks", [])
            has_text = any(b.get("text", "").strip() for b in blocks)
            if not has_text and not item.get("needsEyes"):
                missing.append(item.get("id", "?"))
        if missing:
            errors.append(
                f"Pipeline follow-up items {missing} have no copy-paste text. "
                f"Every follow-up needs a pre-written DM or email."
            )

    def _check_quick_wins(self, data: dict, warnings: list[str]) -> None:
        qw = self._get_section(data, "quick-wins")
        if not qw:
            warnings.append("No 'quick-wins' section. Usually there's at least 1 quick win.")
        elif len(qw.get("items", [])) == 0:
            warnings.append("Quick wins section is empty.")

    def _check_day_content(self, data: dict, day: str, errors: list[str], warnings: list[str]) -> None:
        if day in ("monday", "wednesday", "friday"):
            self._check_signals(data, errors)
        if day in ("tuesday", "thursday"):
            self._check_thought_leadership(data, errors)
        if day == "monday":
            self._check_medium(data, warnings)
        if day == "wednesday":
            self._check_kipi(data, warnings)

    def _check_signals(self, data: dict, errors: list[str]) -> None:
        for s in data["sections"]:
            sid = s.get("id", "")
            title = str(s.get("title", "")).lower()
            if "signal" in sid + title or "x-post" in sid or "x post" in title:
                return
            for item in s.get("items", []):
                if "signal" in str(item.get("title", "")).lower():
                    return
        errors.append(
            "MISSING CONTENT: Monday/Wednesday/Friday requires signals post. "
            "No signals content found in any section."
        )

    def _check_thought_leadership(self, data: dict, errors: list[str]) -> None:
        for s in data["sections"]:
            for item in s.get("items", []):
                title = str(item.get("title", "")).lower()
                platform = str(item.get("platform", "")).lower()
                if platform == "linkedin" and (
                    "tl" in title
                    or "thought leadership" in title
                    or "adhd" in title
                    or "linkedin post" in title
                ):
                    return
        errors.append(
            "MISSING CONTENT: Tuesday/Thursday requires thought leadership LinkedIn post. "
            "No TL post found in any section."
        )

    def _check_medium(self, data: dict, warnings: list[str]) -> None:
        for s in data["sections"]:
            for item in s.get("items", []):
                if "medium" in str(item.get("title", "")).lower():
                    return
        warnings.append("Monday: No Medium draft found. Check if one is needed.")

    def _check_kipi(self, data: dict, warnings: list[str]) -> None:
        for s in data["sections"]:
            for item in s.get("items", []):
                if "kipi" in str(item.get("title", "")).lower():
                    return
        warnings.append("Wednesday: No Kipi System promo post found.")

    def _check_section_ordering(self, section_ids: list, errors: list[str]) -> None:
        present = [sid for sid in _SECTION_ORDER if sid in section_ids]
        actual_order = [sid for sid in section_ids if sid in _SECTION_ORDER]
        if present != actual_order:
            errors.append(
                f"Section ordering violation. Expected order: {present}. "
                f"Got: {actual_order}. Sections must follow friction ordering "
                f"(quick-wins first, FYI last)."
            )

    def _check_energy_tags(self, data: dict, warnings: list[str]) -> None:
        for s in data["sections"]:
            for item in s.get("items", []):
                energy = item.get("energy")
                if not energy:
                    warnings.append(
                        f"Item {item.get('id', '?')} in section {s.get('id', '?')} "
                        f"has no energy tag."
                    )
                elif energy not in _VALID_ENERGY:
                    warnings.append(
                        f"Item {item.get('id', '?')}: energy '{energy}' is not valid. "
                        f"Use: {', '.join(sorted(_VALID_ENERGY))}."
                    )

    def _check_today_focus(self, data: dict, warnings: list[str]) -> None:
        focus = data.get("todayFocus")
        if not focus:
            warnings.append("No todayFocus array. Should have 3-5 priority items.")
        elif len(focus) < 3:
            warnings.append(f"todayFocus has only {len(focus)} items (target 3-5).")
