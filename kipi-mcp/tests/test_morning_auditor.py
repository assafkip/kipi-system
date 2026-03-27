from __future__ import annotations

import pytest
from kipi_mcp.morning_auditor import MorningAuditor


@pytest.fixture
def auditor():
    return MorningAuditor()


COMMON_STEPS = {
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
    "4.1_value_drops",
}

MWF_CONTENT = {"4_signals_linkedin", "4_x_signals", "4_x_hot_take", "4_x_bts"}
TTH_CONTENT = {"4_tl_linkedin", "4_tl_x"}
MONDAY_EXTRAS = {"3.7_content_intel", "5_site_metrics", "5.5_prospect_tracking", "4_medium_draft"}
WEDNESDAY_EXTRA = {"4_kipi_promo"}


def _make_log(date, steps_done=None, steps_failed=None, steps_skipped=None,
              steps_partial=None, gates=None, action_cards=None,
              checksums=None, verifications=None):
    steps = {}
    for s in (steps_done or []):
        steps[s] = {"status": "done"}
    for s in (steps_failed or []):
        steps[s] = {"status": "failed", "error": "test error"}
    for s in (steps_skipped or []):
        steps[s] = {"status": "skipped", "error": "not needed"}
    for s in (steps_partial or []):
        steps[s] = {"status": "partial", "result": "incomplete"}
    return {
        "date": date,
        "steps": steps,
        "action_cards": action_cards or [],
        "state_checksums": checksums or {"session_start": {}, "session_end": {}, "drift_detected": []},
        "verification_queue": verifications or [],
        "gates_checked": gates or {},
    }


def _all_wednesday_steps():
    return COMMON_STEPS | MWF_CONTENT | WEDNESDAY_EXTRA


def _all_monday_steps():
    return COMMON_STEPS | MWF_CONTENT | MONDAY_EXTRAS


def _all_tuesday_steps():
    return COMMON_STEPS | TTH_CONTENT


def test_complete_verdict(auditor):
    all_steps = _all_wednesday_steps()
    gates = {
        "step_8": {"checked": True, "all_prior_done": True, "missing": []},
        "step_9": {"checked": True, "all_prior_done": True, "missing": []},
        "step_11": {"checked": True, "all_prior_done": True, "missing": []},
    }
    checksums = {
        "session_start": {"canonical_file_count": "5"},
        "session_end": {"canonical_file_count": "5"},
        "drift_detected": [],
    }
    log = _make_log("2026-03-25", steps_done=list(all_steps), gates=gates, checksums=checksums)
    result = auditor.audit(log)
    assert result["verdict"] == "COMPLETE"
    assert result["pct"] == 100.0
    assert result["gates_ok"] is True
    assert result["issues"] == []


def test_mostly_complete(auditor):
    all_steps = list(_all_wednesday_steps())
    done = all_steps[:int(len(all_steps) * 0.88)]
    missing = all_steps[int(len(all_steps) * 0.88):]
    gates = {
        "step_8": {"checked": True, "all_prior_done": True, "missing": []},
        "step_9": {"checked": True, "all_prior_done": True, "missing": []},
        "step_11": {"checked": True, "all_prior_done": True, "missing": []},
    }
    log = _make_log("2026-03-25", steps_done=done, gates=gates)
    result = auditor.audit(log)
    assert result["verdict"] == "MOSTLY COMPLETE"
    assert result["pct"] >= 80
    assert result["missing"] == len(missing)


def test_partial_verdict(auditor):
    all_steps = list(_all_wednesday_steps())
    done = all_steps[:int(len(all_steps) * 0.6)]
    log = _make_log("2026-03-25", steps_done=done)
    result = auditor.audit(log)
    assert result["verdict"] == "PARTIAL"


def test_incomplete_verdict(auditor):
    all_steps = list(_all_wednesday_steps())
    done = all_steps[:int(len(all_steps) * 0.3)]
    log = _make_log("2026-03-25", steps_done=done)
    result = auditor.audit(log)
    assert result["verdict"] == "INCOMPLETE"


def test_monday_has_extras(auditor):
    all_steps = _all_monday_steps()
    gates = {
        "step_8": {"checked": True, "all_prior_done": True, "missing": []},
        "step_9": {"checked": True, "all_prior_done": True, "missing": []},
        "step_11": {"checked": True, "all_prior_done": True, "missing": []},
    }
    log = _make_log("2026-03-23", steps_done=list(all_steps), gates=gates)
    result = auditor.audit(log)
    assert result["verdict"] == "COMPLETE"
    assert result["required"] == len(all_steps)


def test_tuesday_has_tth_content(auditor):
    all_steps = _all_tuesday_steps()
    gates = {
        "step_8": {"checked": True, "all_prior_done": True, "missing": []},
        "step_9": {"checked": True, "all_prior_done": True, "missing": []},
        "step_11": {"checked": True, "all_prior_done": True, "missing": []},
    }
    log = _make_log("2026-03-24", steps_done=list(all_steps), gates=gates)
    result = auditor.audit(log)
    assert result["verdict"] == "COMPLETE"


def test_failed_steps_in_issues(auditor):
    all_steps = list(_all_wednesday_steps())
    failed = [all_steps[0]]
    done = all_steps[1:]
    gates = {
        "step_8": {"checked": True, "all_prior_done": True, "missing": []},
        "step_9": {"checked": True, "all_prior_done": True, "missing": []},
        "step_11": {"checked": True, "all_prior_done": True, "missing": []},
    }
    log = _make_log("2026-03-25", steps_done=done, steps_failed=failed, gates=gates)
    result = auditor.audit(log)
    assert result["failed"] == 1
    assert any("failed" in i for i in result["issues"])


def test_missing_steps_in_issues(auditor):
    done = list(COMMON_STEPS)[:5]
    log = _make_log("2026-03-25", steps_done=done)
    result = auditor.audit(log)
    assert result["missing"] > 0
    assert any("silently skipped" in i for i in result["issues"])


def test_gates_missing_means_not_ok(auditor):
    all_steps = list(_all_wednesday_steps())
    log = _make_log("2026-03-25", steps_done=all_steps, gates={})
    result = auditor.audit(log)
    assert result["gates_ok"] is False


def test_gate_ran_without_check(auditor):
    all_steps = list(_all_wednesday_steps())
    log = _make_log("2026-03-25", steps_done=all_steps, gates={
        "step_8": {"checked": True, "all_prior_done": True, "missing": []},
        "step_11": {"checked": True, "all_prior_done": True, "missing": []},
    })
    result = auditor.audit(log)
    assert result["gates_ok"] is False
    assert any("step_9" in i for i in result["issues"])


def test_action_cards_unconfirmed(auditor):
    cards = [
        {"id": "C1", "type": "comment", "target": "Alice", "card_delivered": True, "founder_confirmed": False},
        {"id": "C2", "type": "DM", "target": "Bob", "card_delivered": True, "founder_confirmed": True},
    ]
    log = _make_log("2026-03-25", steps_done=list(_all_wednesday_steps()),
                     action_cards=cards,
                     gates={
                         "step_8": {"checked": True, "all_prior_done": True, "missing": []},
                         "step_9": {"checked": True, "all_prior_done": True, "missing": []},
                         "step_11": {"checked": True, "all_prior_done": True, "missing": []},
                     })
    result = auditor.audit(log)
    assert result["action_card_count"] == 2


def test_empty_log(auditor):
    log = _make_log("2026-03-25")
    result = auditor.audit(log)
    assert result["verdict"] == "INCOMPLETE"
    assert result["done"] == 0
    assert result["missing"] > 0
    assert result["date"] == "2026-03-25"
    assert result["day_of_week"] == "wednesday"
