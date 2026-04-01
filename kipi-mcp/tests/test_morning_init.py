import hashlib
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from kipi_mcp.morning_init import (
    preflight,
    session_bootstrap,
    canonical_digest,
    morning_init,
    gate_check,
    deliverables_check,
)


@pytest.fixture
def paths(tmp_path):
    from kipi_mcp.paths import KipiPaths
    p = KipiPaths(base_dir=tmp_path / "base", repo_dir=tmp_path / "repo", instance="test")
    p.ensure_dirs()
    return p


def _create_file(path: Path, content: str = "test"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ── Preflight ──


class TestPreflight:
    def test_all_files_exist(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md")
        _create_file(paths.canonical_dir / "objections.md")
        _create_file(paths.my_project_dir / "relationships.md")
        _create_file(paths.memory_dir / "last-handoff.md")
        result = preflight(paths)
        assert result["ready"] is True
        assert all(v is True for v in result["files"].values())

    def test_missing_required_file(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md")
        # objections.md missing
        _create_file(paths.my_project_dir / "relationships.md")
        result = preflight(paths)
        assert result["ready"] is False
        assert result["files"]["objections"] is False
        assert result["files"]["talk_tracks"] is True

    def test_optional_missing_still_ready(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md")
        _create_file(paths.canonical_dir / "objections.md")
        _create_file(paths.my_project_dir / "relationships.md")
        # handoff missing (optional)
        result = preflight(paths)
        assert result["ready"] is True
        assert result["files"]["handoff"] is False

    def test_returns_date(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md")
        _create_file(paths.canonical_dir / "objections.md")
        _create_file(paths.my_project_dir / "relationships.md")
        result = preflight(paths)
        assert "date" in result


# ── Bootstrap ──


class TestBootstrap:
    def test_no_previous_session(self, paths):
        result = session_bootstrap(paths)
        assert result["action_cards"] == []
        assert result["loop_stats"]["open"] == 0

    def test_recovers_action_cards(self, paths):
        log = {
            "action_cards": [
                {"id": "c1", "confirmed": False, "text": "Follow up with Alice"},
                {"id": "c2", "confirmed": True, "text": "Done"},
            ]
        }
        date = datetime.now().strftime("%Y-%m-%d")
        log_path = paths.output_dir / f"morning-log-{date}.json"
        log_path.write_text(json.dumps(log))
        result = session_bootstrap(paths)
        assert len(result["action_cards"]) == 1
        assert result["action_cards"][0]["id"] == "c1"

    def test_loop_stats(self, paths):
        loops = [
            {"id": "L1", "status": "open", "escalation_level": 0},
            {"id": "L2", "status": "open", "escalation_level": 2},
            {"id": "L3", "status": "closed", "escalation_level": 1},
        ]
        (paths.output_dir / "open-loops.json").write_text(json.dumps(loops))
        result = session_bootstrap(paths)
        assert result["loop_stats"]["open"] == 2
        assert result["loop_stats"]["level_0"] == 1
        assert result["loop_stats"]["level_2"] == 1

    def test_stall_detection(self, paths):
        old_date = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")
        content = f"## Alice\n- Company: Acme\n- Last contact: {old_date}\n"
        _create_file(paths.my_project_dir / "relationships.md", content)
        result = session_bootstrap(paths)
        assert len(result["stalls"]) == 1
        assert result["stalls"][0]["contact"] == "Alice"
        assert result["stalls"][0]["days_stale"] >= 20

    def test_canonical_checksums(self, paths):
        content = "# Test talk track\nMetaphor goes here."
        _create_file(paths.canonical_dir / "talk-tracks.md", content)
        _create_file(paths.canonical_dir / "objections.md", "# Obj 1\nResponse.")
        result = session_bootstrap(paths)
        expected = hashlib.sha256(content.encode()).hexdigest()[:16]
        assert result["checksums"]["talk_tracks"] == expected


# ── Canonical Digest ──


class TestCanonicalDigest:
    def test_extracts_talk_tracks(self, paths):
        content = (
            "# Primary Metaphor\nYour brain externalized.\n\n"
            "# Key Definition\nA second brain that remembers everything.\n\n"
            "# Wedge Formula\n3 out of 5 founders forget. This fixes it.\n\n"
            "# Banned Phrases\n- leverage\n- synergy\n- game-changer\n\n"
            "# Detection Rule\nIf they say 'I keep forgetting', pivot to demo.\n"
        )
        _create_file(paths.canonical_dir / "talk-tracks.md", content)
        result = canonical_digest(paths)
        tt = result["talk_tracks"]
        assert "externalized" in tt["metaphor"]
        assert "second brain" in tt["definition"]
        assert len(tt["banned_phrases"]) == 3
        assert "leverage" in tt["banned_phrases"]

    def test_extracts_objections(self, paths):
        content = "# Too expensive\nWe save 20 hours/week. That's worth more than the cost. Most teams see ROI in 2 weeks.\n\n# Already have a tool\nGreat. Does it remember what each person said last month? Our system compounds knowledge."
        _create_file(paths.canonical_dir / "objections.md", content)
        result = canonical_digest(paths)
        assert len(result["objections"]) == 2
        assert result["objections"][0]["name"] == "Too expensive"
        assert "20 hours" in result["objections"][0]["response"]

    def test_extracts_current_state(self, paths):
        content = "# What Works Today\n- Morning briefing\n- Loop tracking\n\n# Validated\n- AUDHD friction ordering\n\n# Unvalidated\n- Auto-posting\n"
        _create_file(paths.my_project_dir / "current-state.md", content)
        result = canonical_digest(paths)
        cs = result["current_state"]
        assert "Morning briefing" in cs["works_today"]
        assert "AUDHD friction ordering" in cs["validated"]
        assert "Auto-posting" in cs["unvalidated"]

    def test_extracts_decisions(self, paths):
        content = "# [RULE] Never auto-post\nFounder must approve all posts before publishing.\n\n# [RULE] Haiku for data pulls\nUse haiku model for all data-fetching agents.\n"
        _create_file(paths.canonical_dir / "decisions.md", content)
        result = canonical_digest(paths)
        assert len(result["decisions"]) >= 2

    def test_missing_file_graceful(self, paths):
        # Only create talk-tracks, skip the rest
        _create_file(paths.canonical_dir / "talk-tracks.md", "# Metaphor\nTest.")
        result = canonical_digest(paths)
        assert len(result["warnings"]) >= 1
        assert result["talk_tracks"]["metaphor"] != ""

    def test_validation_gate(self, paths):
        # Create all files with valid content
        _create_file(paths.canonical_dir / "talk-tracks.md", "# Primary Metaphor\nBrain ext.\n# Key Definition\nSecond brain.\n")
        _create_file(paths.canonical_dir / "objections.md", "# Obj1\nResponse here.\n")
        _create_file(paths.my_project_dir / "current-state.md", "# What Works Today\n- Item1\n")
        _create_file(paths.canonical_dir / "discovery.md", "# Top Questions\n- Q1\n")
        _create_file(paths.canonical_dir / "decisions.md", "# [RULE] Test\nDo this.\n")
        result = canonical_digest(paths)
        assert result["valid"] is True


# ── Morning Init ──


class TestMorningInit:
    def test_creates_bus_dir(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md")
        _create_file(paths.canonical_dir / "objections.md")
        _create_file(paths.my_project_dir / "relationships.md")
        result = morning_init(paths, energy_level=3)
        bus_today = paths.bus_dir / result["date"]
        assert bus_today.exists()

    def test_cleans_old_bus(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md")
        _create_file(paths.canonical_dir / "objections.md")
        _create_file(paths.my_project_dir / "relationships.md")
        old_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        old_dir = paths.bus_dir / old_date
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "test.json").write_text("{}")
        morning_init(paths, energy_level=3)
        assert not old_dir.exists()

    def test_returns_complete_bundle(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "# Metaphor\nTest.")
        _create_file(paths.canonical_dir / "objections.md", "# Obj\nResp.")
        _create_file(paths.my_project_dir / "relationships.md")
        _create_file(paths.my_project_dir / "current-state.md", "# What Works Today\n- X\n")
        _create_file(paths.canonical_dir / "discovery.md", "# Questions\n- Q\n")
        _create_file(paths.canonical_dir / "decisions.md", "# [RULE] R\nD.\n")
        result = morning_init(paths, energy_level=3)
        assert "preflight" in result
        assert "bootstrap" in result
        assert "canonical_digest" in result
        assert "energy" in result
        assert "date" in result

    def test_energy_compression(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md")
        _create_file(paths.canonical_dir / "objections.md")
        _create_file(paths.my_project_dir / "relationships.md")
        result = morning_init(paths, energy_level=2)
        assert result["energy"]["max_hitlist"] == 5
        assert result["energy"]["skip_deep_focus"] is True

        result = morning_init(paths, energy_level=5)
        assert result["energy"]["max_hitlist"] == 999
        assert result["energy"]["skip_deep_focus"] is False


# ── Gate Check ──


class TestGateCheck:
    def test_no_log_file(self, paths):
        result = gate_check(paths, phase=6, date="2026-04-01")
        assert result["passed"] is False
        assert "not found" in result["error"]

    def test_all_prior_phases_done(self, paths):
        date = "2026-04-01"
        log = {
            "date": date,
            "steps": {
                "phase_0_init": {"status": "done"},
                "phase_1_harvest": {"status": "done"},
                "phase_2_analysis": {"status": "done"},
                "phase_3_content": {"status": "done"},
                "phase_4_pipeline": {"status": "done"},
                "phase_5_compliance": {"status": "done"},
            },
        }
        log_path = paths.output_dir / f"morning-log-{date}.json"
        log_path.write_text(json.dumps(log))
        result = gate_check(paths, phase=6, date=date)
        assert result["passed"] is True
        assert result["missing"] == []

    def test_missing_phase(self, paths):
        date = "2026-04-01"
        log = {
            "date": date,
            "steps": {
                "phase_0_init": {"status": "done"},
                "phase_1_harvest": {"status": "done"},
                # phase_2_analysis missing
                "phase_3_content": {"status": "done"},
                "phase_4_pipeline": {"status": "done"},
                "phase_5_compliance": {"status": "done"},
            },
        }
        log_path = paths.output_dir / f"morning-log-{date}.json"
        log_path.write_text(json.dumps(log))
        result = gate_check(paths, phase=6, date=date)
        assert result["passed"] is False
        assert "phase_2_analysis" in result["missing"]

    def test_skipped_counts_as_done(self, paths):
        date = "2026-04-01"
        log = {
            "date": date,
            "steps": {
                "phase_0_init": {"status": "done"},
                "phase_1_harvest": {"status": "done"},
                "phase_2_analysis": {"status": "skipped"},
                "phase_3_content": {"status": "done"},
                "phase_4_pipeline": {"status": "done"},
                "phase_5_compliance": {"status": "done"},
            },
        }
        log_path = paths.output_dir / f"morning-log-{date}.json"
        log_path.write_text(json.dumps(log))
        result = gate_check(paths, phase=6, date=date)
        assert result["passed"] is True


# ── Deliverables Check ──


class TestDeliverablesCheck:
    def test_all_present(self, paths):
        date = datetime.now().strftime("%Y-%m-%d")
        bus = paths.bus_dir / date
        bus.mkdir(parents=True, exist_ok=True)
        (bus / "pipeline-followup.json").write_text("{}")
        (bus / "hitlist.json").write_text('{"actions": [1]}')
        (bus / "outbound-actions.json").write_text("{}")
        (bus / "loop-review.json").write_text("{}")
        (bus / "signals.json").write_text("{}")
        (bus / "value-routing.json").write_text("{}")
        result = deliverables_check(paths, date=date)
        assert result["passed"] is True
        assert len(result["missing"]) == 0

    def test_missing_hitlist(self, paths):
        date = datetime.now().strftime("%Y-%m-%d")
        bus = paths.bus_dir / date
        bus.mkdir(parents=True, exist_ok=True)
        (bus / "pipeline-followup.json").write_text("{}")
        # hitlist missing
        (bus / "outbound-actions.json").write_text("{}")
        (bus / "loop-review.json").write_text("{}")
        (bus / "signals.json").write_text("{}")
        (bus / "value-routing.json").write_text("{}")
        result = deliverables_check(paths, date=date)
        assert result["passed"] is False
        assert any("hitlist" in m for m in result["missing"])

    def test_empty_hitlist_actions(self, paths):
        date = datetime.now().strftime("%Y-%m-%d")
        bus = paths.bus_dir / date
        bus.mkdir(parents=True, exist_ok=True)
        (bus / "pipeline-followup.json").write_text("{}")
        (bus / "hitlist.json").write_text('{"actions": []}')  # empty
        (bus / "outbound-actions.json").write_text("{}")
        (bus / "loop-review.json").write_text("{}")
        (bus / "signals.json").write_text("{}")
        (bus / "value-routing.json").write_text("{}")
        result = deliverables_check(paths, date=date)
        assert result["passed"] is False
        assert any("empty" in m for m in result["missing"])
