from __future__ import annotations

from datetime import datetime


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

        self._check_pipeline_followups(data, errors)
        self._check_quick_wins(data, warnings)
        self._check_day_content(data, day, errors, warnings)
        self._check_section_ordering(section_ids, errors)
        self._check_energy_tags(data, warnings)

        return {"pass": len(errors) == 0, "errors": errors, "warnings": warnings}

    def _get_section(self, data: dict, section_id: str) -> dict | None:
        for s in data.get("sections", []):
            if s.get("id") == section_id:
                return s
        return None

    def _check_pipeline_followups(self, data: dict, errors: list[str]) -> None:
        pf = self._get_section(data, "pipeline-followups")
        if not pf:
            errors.append(
                "MISSING SECTION: 'pipeline-followups' is REQUIRED. "
                "Phase 4 pipeline-followup agent must generate follow-up copy "
                "for at least 3 warm/active contacts."
            )
            return

        items = pf.get("items", [])
        count = len(items)
        if count < 3:
            errors.append(
                f"Pipeline follow-ups has {count} items (minimum 3 required). "
                f"Query Notion Contacts DB for warm/active contacts needing follow-up."
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
        if "pipeline-followups" in section_ids and "new-leads" in section_ids:
            pf_idx = section_ids.index("pipeline-followups")
            nl_idx = section_ids.index("new-leads")
            if pf_idx > nl_idx:
                errors.append(
                    "Section ordering: pipeline-followups must come BEFORE new-leads. "
                    "Follow-ups close deals. New leads are exciting distractions."
                )

    def _check_energy_tags(self, data: dict, warnings: list[str]) -> None:
        for s in data["sections"]:
            for item in s.get("items", []):
                if not item.get("energy"):
                    warnings.append(
                        f"Item {item.get('id', '?')} in section {s.get('id', '?')} "
                        f"has no energy tag."
                    )
