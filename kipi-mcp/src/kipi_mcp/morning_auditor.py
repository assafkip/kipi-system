from __future__ import annotations

from datetime import datetime


class MorningAuditor:
    def audit(self, log: dict) -> dict:
        date_str = log["date"]
        day_of_week = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A").lower()
        steps = log.get("steps", {})
        action_cards = log.get("action_cards", [])
        checksums = log.get("state_checksums", {})
        gates = log.get("gates_checked", {})

        issues: list[str] = []

        expected = self._expected_steps(day_of_week)
        optional = self._optional_steps()

        completed = {k for k, v in steps.items() if v.get("status") == "done"}
        failed = {k for k, v in steps.items() if v.get("status") == "failed"}
        skipped = {k for k, v in steps.items() if v.get("status") == "skipped"}
        partial = {k for k, v in steps.items() if v.get("status") == "partial"}
        not_logged = expected - completed - failed - skipped - partial

        total_required = len(expected)
        total_done = len(completed & expected)

        for s in sorted(failed):
            err = steps[s].get("error", "unknown")
            issues.append(f"Step {s} failed: {err}")

        for s in sorted(not_logged):
            issues.append(f"Step {s} silently skipped")

        for s in sorted(partial):
            issues.append(f"Step {s} only partially completed")

        gates_ok = self._check_gates(gates, completed, partial, issues)

        if not checksums.get("session_start"):
            issues.append("State file checksums not captured at session start")
        elif not checksums.get("session_end"):
            issues.append("State file checksums not captured at session end")

        pct = total_done / total_required * 100 if total_required > 0 else 0

        if not not_logged and not failed and not partial and gates_ok:
            verdict = "COMPLETE"
        elif pct >= 80 and not failed:
            verdict = "MOSTLY COMPLETE"
        elif pct >= 50:
            verdict = "PARTIAL"
        else:
            verdict = "INCOMPLETE"

        return {
            "date": date_str,
            "day_of_week": day_of_week,
            "verdict": verdict,
            "pct": round(pct, 1),
            "required": total_required,
            "done": total_done,
            "failed": len(failed),
            "partial": len(partial),
            "skipped": len(skipped),
            "missing": len(not_logged),
            "gates_ok": gates_ok,
            "action_card_count": len(action_cards),
            "issues": issues,
        }

    def _expected_steps(self, day_of_week: str) -> set[str]:
        expected = {
            "0f_connection_check", "0a_checkpoint", "0b_missed_debrief",
            "0b.5_loop_escalation",
            "0c_load_canonical", "0d_load_voice", "0e_load_audhd",
            "1_calendar", "1_gmail", "1_notion_actions", "1_notion_pipeline",
            "3_linkedin_activity", "3.5_dp_pipeline",
            "3.8_dm_check", "5.8_temperature_scoring",
            "5.85_pipeline_followup",
            "5.86_loop_review",
            "5.9_lead_sourcing", "5.9b_engagement_hitlist",
            "6_decision_compliance", "7_positioning_freshness",
            "8_briefing_output", "8.5_start_here",
            "9_notion_push", "10_daily_checklists", "11_html_output",
            "0c_canonical_digest",
            "1b_content_metrics", "3b_behavioral_signals",
            "7b_outreach_queue",
        }

        if day_of_week == "monday":
            expected.update({"3.7_content_intel", "5_site_metrics", "5.5_prospect_tracking"})

        if day_of_week in ("monday", "wednesday", "friday"):
            expected.update({"4_signals_linkedin", "4_x_signals", "4_x_hot_take", "4_x_bts"})
        if day_of_week in ("tuesday", "thursday"):
            expected.update({"4_tl_linkedin", "4_tl_x"})
        if day_of_week == "wednesday":
            expected.add("4_kipi_promo")
        if day_of_week == "monday":
            expected.add("4_medium_draft")

        expected.add("4.1_value_drops")

        return expected

    def _optional_steps(self) -> set[str]:
        return {
            "1_vc_pipeline", "1.5_warm_intro", "2.5_x_activity",
            "3.2_publish_reconciliation", "4.5_marketing_health",
            "0g_monthly_checks", "9.5_investor_update_check", "7.5_checkpoint_drift",
            "2_meeting_prep",
            "1c_copy_diff", "3c_prospect_activity",
        }

    def _check_gates(self, gates: dict, completed: set[str], partial: set[str],
                      issues: list[str]) -> bool:
        gate_steps = {
            "step_8": "8_briefing_output",
            "step_9": "9_notion_push",
            "step_11": "11_html_output",
        }
        gates_ok = True

        for gate_name, gate_step in gate_steps.items():
            gate_data = gates.get(gate_name, {})
            if not gate_data:
                if gate_step in completed or gate_step in partial:
                    issues.append(f"{gate_name} ran without gate check")
                    gates_ok = False
            elif gate_data.get("checked"):
                if not gate_data.get("all_prior_done"):
                    missing = gate_data.get("missing", [])
                    issues.append(f"{gate_name} proceeded despite missing: {', '.join(missing)}")
                    gates_ok = False
            else:
                issues.append(f"{gate_name} gate not checked")
                gates_ok = False

        if not gates:
            issues.append("No gate checks recorded")
            gates_ok = False

        return gates_ok
