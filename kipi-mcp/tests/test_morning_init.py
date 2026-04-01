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
    retry_notion_queue,
    _check_db_integrity,
    auto_backup,
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
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        _create_file(paths.memory_dir / "last-handoff.md")
        result = preflight(paths)
        assert result["ready"] is True
        assert all(v is True for v in result["files"].values())

    def test_missing_required_file(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        # objections.md missing
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        result = preflight(paths)
        assert result["ready"] is False
        assert result["files"]["objections"] is False
        assert result["files"]["talk_tracks"] is True

    def test_optional_missing_still_ready(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        # handoff missing (optional)
        result = preflight(paths)
        assert result["ready"] is True
        assert result["files"]["handoff"] is False

    def test_returns_date(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        result = preflight(paths)
        assert "date" in result

    def test_empty_file_rejected(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "tiny")  # 4 bytes < 50
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        result = preflight(paths)
        assert result["ready"] is False
        assert result["files"]["talk_tracks"] == "empty"
        assert len(result["content_warnings"]) >= 1
        assert "talk_tracks" in result["content_warnings"][0]

    def test_valid_content_passes(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        result = preflight(paths)
        assert result["ready"] is True
        assert result["content_warnings"] == []
        assert all(v is True for k, v in result["files"].items() if k != "handoff")


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

    def test_bootstrap_includes_recently_closed_loops(self, paths):
        from kipi_mcp.loop_tracker import LoopTracker
        lt = LoopTracker(db_path=paths.metrics_db)
        lt.init_db()
        opened = lt.open("email_sent", "TestTarget", "intro")
        lt.close(opened["loop_id"], "replied", "system")
        result = session_bootstrap(paths)
        assert "recently_closed_loops" in result
        assert len(result["recently_closed_loops"]) >= 1
        assert result["recently_closed_loops"][0]["target"] == "TestTarget"
        assert "recently_closed" in result["loop_stats"]


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
    def test_cleanup_runs_on_init(self, paths):
        from kipi_mcp.harvest_store import HarvestStore
        store = HarvestStore(db_path=paths.output_dir / "test.db")
        store.init_db()
        # Create an old run
        import sqlite3
        conn = sqlite3.connect(str(store.db_path))
        conn.execute(
            "INSERT INTO harvest_runs (run_id, started_at, mode, status) VALUES (?, ?, ?, ?)",
            ("old-run", "2026-01-01T00:00:00", "incremental", "complete"),
        )
        conn.commit()
        conn.close()
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        result = morning_init(paths, energy_level=3, harvest_store=store)
        assert result["cleanup"]["deleted_runs"] >= 1

    def test_old_files_cleaned(self, paths):
        import os, time
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        # Create an old morning log (backdate mtime)
        old_log = paths.output_dir / "morning-log-2025-01-01.json"
        old_log.write_text("{}")
        old_time = time.time() - (15 * 86400)  # 15 days ago
        os.utime(old_log, (old_time, old_time))
        morning_init(paths, energy_level=3)
        assert not old_log.exists()

    def test_returns_complete_bundle(self, paths):
        _create_file(paths.canonical_dir / "talk-tracks.md", "# Metaphor\nTest." + "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "# Obj\nResp." + "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
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
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        result = morning_init(paths, energy_level=2)
        assert result["energy"]["max_hitlist"] == 5
        assert result["energy"]["skip_deep_focus"] is True

        result = morning_init(paths, energy_level=5)
        assert result["energy"]["max_hitlist"] == 999
        assert result["energy"]["skip_deep_focus"] is False

    def test_morning_init_detects_handoff(self, paths):
        from kipi_mcp.harvest_store import HarvestStore
        store = HarvestStore(db_path=paths.output_dir / "test.db")
        store.init_db()
        today = datetime.now().strftime("%Y-%m-%d")
        store.save_handoff(
            date=today, run_id=f"{today}-001",
            phases_completed="phase_0,phase_1",
            notes="Stopped mid-harvest",
        )
        _create_file(paths.canonical_dir / "talk-tracks.md", "x" * 100)
        _create_file(paths.canonical_dir / "objections.md", "x" * 100)
        _create_file(paths.my_project_dir / "relationships.md", "x" * 100)
        result = morning_init(paths, energy_level=3, harvest_store=store)
        assert result["resume_from"] is not None
        assert result["resume_from"]["phases_completed"] == "phase_0,phase_1"
        assert result["resume_from"]["notes"] == "Stopped mid-harvest"


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
    @pytest.fixture
    def store(self, tmp_path):
        from kipi_mcp.harvest_store import HarvestStore
        s = HarvestStore(db_path=tmp_path / "test.db")
        s.init_db()
        return s

    def _store_agent_record(self, store, source_name):
        run = store.create_run("incremental")
        store.store_record(
            run_id=run["run_id"],
            source_name=source_name,
            record_key=f"test-{source_name}",
            summary_json='{"test": true}',
        )

    def test_all_present(self, paths, store):
        for agent in [
            "agent:pipeline-followup", "agent:engagement-hitlist",
            "agent:outbound-detection", "agent:loop-review",
            "agent:signals-content", "agent:value-routing",
        ]:
            self._store_agent_record(store, agent)
        result = deliverables_check(paths, harvest_store=store)
        assert result["passed"] is True
        assert len(result["missing"]) == 0

    def test_missing_hitlist(self, paths, store):
        for agent in [
            "agent:pipeline-followup",
            "agent:outbound-detection", "agent:loop-review",
            "agent:signals-content", "agent:value-routing",
        ]:
            self._store_agent_record(store, agent)
        # hitlist missing
        result = deliverables_check(paths, harvest_store=store)
        assert result["passed"] is False
        assert any("hitlist" in m for m in result["missing"])

    def test_no_store(self, paths):
        result = deliverables_check(paths, harvest_store=None)
        assert result["passed"] is False
        assert len(result["missing"]) > 0


# ── DB Integrity ──


class TestDbIntegrity:
    def test_db_integrity_check_ok(self, tmp_path):
        import sqlite3
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.close()
        result = _check_db_integrity(db_path)
        assert result["status"] == "ok"
        assert result["detail"] == "ok"

    def test_db_integrity_check_no_db(self, tmp_path):
        result = _check_db_integrity(tmp_path / "nonexistent.db")
        assert result["status"] == "no_db"


# ── Auto Backup ──


class TestAutoBackup:
    @pytest.fixture
    def backup_mgr(self, paths):
        from kipi_mcp.backup import BackupManager
        _create_file(paths.canonical_dir / "talk-tracks.md", "# TT")
        return BackupManager(paths)

    def test_auto_backup_creates_archive(self, backup_mgr):
        result = auto_backup(backup_mgr)
        assert "backup" in result
        assert result["backup"]["files_count"] >= 1
        assert Path(result["backup"]["path"]).exists()

    def test_auto_backup_rotation_keeps_5(self, backup_mgr, paths):
        out = paths.output_dir
        for i in range(7):
            backup_mgr.backup(output_path=out / f"kipi-backup-2026010{i}-000000.tar.gz")
        assert len(backup_mgr.list_backups()) == 7
        result = auto_backup(backup_mgr, max_backups=5)
        assert result["rotation"]["kept"] == 5
        assert len(result["rotation"]["deleted"]) >= 2
        # 7 + 1 new = 8, rotate keeps 5
        assert len(backup_mgr.list_backups()) == 5
