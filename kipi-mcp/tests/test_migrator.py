import os
import sqlite3
import time
from types import SimpleNamespace

import pytest

from kipi_mcp.migrator import FILE_MAP, DIR_MAP, STATE_DIRS, LEGACY_DB_CANDIDATES, Migrator


def make_paths(tmp_path, instance="test-instance"):
    inst_dir = tmp_path / "instances" / instance
    paths = SimpleNamespace(
        _base=tmp_path,
        config_dir=inst_dir,
        data_dir=inst_dir,
        state_dir=inst_dir,
        global_dir=tmp_path / "global",
        repo_dir=tmp_path / "repo",
        instance=instance,
    )
    paths.ensure_dirs = lambda: None
    return paths


def _create_file(path, content="real content"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _create_legacy_db(path):
    """Create a real SQLite database at the given path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO test_table VALUES (1, 'migrated')")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------

def test_detect_fresh_install(tmp_path):
    """No user data files in repo -> empty needs_migration."""
    paths = make_paths(tmp_path)
    paths.repo_dir.mkdir()
    m = Migrator(paths, "fresh")
    result = m.detect()
    assert result["needs_migration"] == []
    assert result["already_migrated"] == []
    assert result["templates_skipped"] == []


def test_detect_template_files_skipped(tmp_path):
    """Files containing {{SETUP_NEEDED}} are listed as templates, not migration targets."""
    paths = make_paths(tmp_path)
    old = paths.repo_dir / "q-system/my-project/founder-profile.md"
    _create_file(old, "# Profile\n{{SETUP_NEEDED}}\n")

    m = Migrator(paths, "test-instance")
    result = m.detect()
    assert "q-system/my-project/founder-profile.md" in result["templates_skipped"]
    assert result["needs_migration"] == []


def test_detect_user_data_needs_migration(tmp_path):
    """Populated files flagged for migration."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/my-project/founder-profile.md", "name: Ike")
    _create_file(paths.repo_dir / "q-system/canonical/objections.md", "obj 1")

    m = Migrator(paths, "test-instance")
    result = m.detect()
    assert "q-system/my-project/founder-profile.md" in result["needs_migration"]
    assert "q-system/canonical/objections.md" in result["needs_migration"]


def test_detect_already_migrated(tmp_path):
    """Files already in XDG location listed as already_migrated."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/my-project/founder-profile.md", "name: Ike")
    _create_file(paths.config_dir / "founder-profile.md", "name: Ike")

    m = Migrator(paths, "test-instance")
    result = m.detect()
    assert "q-system/my-project/founder-profile.md" in result["already_migrated"]
    assert result["needs_migration"] == []


def test_detect_instance_info(tmp_path):
    """detect() returns instance_name in result."""
    paths = make_paths(tmp_path)
    paths.repo_dir.mkdir(parents=True)

    m = Migrator(paths, "test-instance")
    result = m.detect()
    assert result["instance_name"] == "test-instance"

    m2 = Migrator(paths, "my-proj-spark7")
    result2 = m2.detect()
    assert result2["instance_name"] == "my-proj-spark7"


def test_detect_legacy_db(tmp_path):
    """detect() flags legacy metrics.db for migration."""
    paths = make_paths(tmp_path)
    _create_legacy_db(paths.repo_dir / "q-system" / "output" / "metrics.db")

    m = Migrator(paths, "test-instance")
    result = m.detect()
    assert "q-system/output/metrics.db" in result["needs_migration"]


def test_detect_legacy_db_already_migrated(tmp_path):
    """detect() marks legacy db as already_migrated when dest exists."""
    paths = make_paths(tmp_path)
    _create_legacy_db(paths.repo_dir / "q-system" / "output" / "metrics.db")
    _create_legacy_db(paths.data_dir / "metrics.db")

    m = Migrator(paths, "test-instance")
    result = m.detect()
    assert "q-system/output/metrics.db" in result["already_migrated"]


# ---------------------------------------------------------------------------
# migrate() — file copying
# ---------------------------------------------------------------------------

def test_migrate_copies_files(tmp_path):
    """Files copied to correct XDG locations."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/my-project/founder-profile.md", "name: Ike")
    _create_file(paths.repo_dir / "q-system/canonical/objections.md", "obj 1")
    _create_file(paths.repo_dir / "q-system/my-project/current-state.md", "state data")

    m = Migrator(paths, "test-instance")
    result = m.migrate()

    assert len(result["errors"]) == 0
    assert (paths.config_dir / "founder-profile.md").read_text() == "name: Ike"
    assert (paths.config_dir / "canonical/objections.md").read_text() == "obj 1"
    assert (paths.data_dir / "my-project/current-state.md").read_text() == "state data"


def test_migrate_skips_templates(tmp_path):
    """Template files not copied."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/my-project/founder-profile.md", "{{SETUP_NEEDED}}")

    m = Migrator(paths, "test-instance")
    result = m.migrate()

    assert not any(c["from"] == "q-system/my-project/founder-profile.md" for c in result["copied"])
    assert any(s["reason"] == "template" for s in result["skipped"])
    assert not (paths.config_dir / "founder-profile.md").exists()


def test_migrate_skips_already_present(tmp_path):
    """Idempotent: doesn't overwrite newer files in XDG location."""
    paths = make_paths(tmp_path)
    old_file = paths.repo_dir / "q-system/my-project/founder-profile.md"
    _create_file(old_file, "old content")

    new_file = paths.config_dir / "founder-profile.md"
    _create_file(new_file, "new content")
    future = time.time() + 10
    os.utime(new_file, (future, future))

    m = Migrator(paths, "test-instance")
    result = m.migrate()

    assert any(s["reason"] == "already_migrated" for s in result["skipped"])
    assert new_file.read_text() == "new content"


def test_migrate_dry_run(tmp_path):
    """Reports what would happen without actually copying."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/my-project/founder-profile.md", "name: Ike")

    m = Migrator(paths, "test-instance")
    result = m.migrate(dry_run=True)

    assert len(result["copied"]) == 1
    assert result["copied"][0]["from"] == "q-system/my-project/founder-profile.md"
    assert not (paths.config_dir / "founder-profile.md").exists()


def test_migrate_directories(tmp_path):
    """memory/ directory recursively copied to data dir."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/memory/working/session.md", "session notes")
    _create_file(paths.repo_dir / "q-system/memory/weekly/week1.md", "week 1")

    m = Migrator(paths, "test-instance")
    result = m.migrate()

    assert len(result["errors"]) == 0
    assert (paths.data_dir / "memory/working/session.md").read_text() == "session notes"
    assert (paths.data_dir / "memory/weekly/week1.md").read_text() == "week 1"


# ---------------------------------------------------------------------------
# migrate() — SQLite
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("legacy_path", LEGACY_DB_CANDIDATES)
def test_migrate_copies_sqlite_from_each_candidate(tmp_path, legacy_path):
    """metrics.db found in any legacy location gets copied to data_dir."""
    paths = make_paths(tmp_path)
    _create_legacy_db(paths.repo_dir / legacy_path)

    m = Migrator(paths, "test-instance")
    result = m.migrate()

    assert len(result["errors"]) == 0
    dest = paths.data_dir / "metrics.db"
    assert dest.exists()
    conn = sqlite3.connect(str(dest))
    row = conn.execute("SELECT val FROM test_table WHERE id=1").fetchone()
    conn.close()
    assert row[0] == "migrated"


def test_migrate_sqlite_first_candidate_wins(tmp_path):
    """When multiple legacy DBs exist, first candidate (q-system/output/) wins."""
    paths = make_paths(tmp_path)
    db1 = paths.repo_dir / "q-system/output/metrics.db"
    db1.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db1))
    conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO test_table VALUES (1, 'from-output')")
    conn.commit()
    conn.close()

    db2 = paths.repo_dir / "metrics.db"
    conn = sqlite3.connect(str(db2))
    conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO test_table VALUES (1, 'from-root')")
    conn.commit()
    conn.close()

    m = Migrator(paths, "test-instance")
    result = m.migrate()

    dest = paths.data_dir / "metrics.db"
    conn = sqlite3.connect(str(dest))
    row = conn.execute("SELECT val FROM test_table WHERE id=1").fetchone()
    conn.close()
    assert row[0] == "from-output"


def test_migrate_sqlite_skip_if_dest_newer(tmp_path):
    """Idempotent: doesn't overwrite newer metrics.db at destination."""
    paths = make_paths(tmp_path)
    _create_legacy_db(paths.repo_dir / "q-system/output/metrics.db")
    _create_legacy_db(paths.data_dir / "metrics.db")
    future = time.time() + 10
    os.utime(paths.data_dir / "metrics.db", (future, future))

    m = Migrator(paths, "test-instance")
    result = m.migrate()

    assert any(
        s["file"] == "q-system/output/metrics.db" and s["reason"] == "already_migrated"
        for s in result["skipped"]
    )


def test_migrate_sqlite_dry_run(tmp_path):
    """dry_run reports DB copy without actually copying."""
    paths = make_paths(tmp_path)
    _create_legacy_db(paths.repo_dir / "metrics.db")

    m = Migrator(paths, "test-instance")
    result = m.migrate(dry_run=True)

    assert any(c["from"] == "metrics.db" for c in result["copied"])
    assert not (paths.data_dir / "metrics.db").exists()


# ---------------------------------------------------------------------------
# verify()
# ---------------------------------------------------------------------------

def test_verify_after_migration(tmp_path):
    """verify() returns complete=True after successful migrate()."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/my-project/founder-profile.md", "name: Ike")
    _create_file(paths.repo_dir / "q-system/canonical/objections.md", "obj 1")

    m = Migrator(paths, "test-instance")
    m.migrate()
    result = m.verify()

    assert result["complete"] is True
    assert len(result["missing"]) == 0
    assert len(result["present"]) == 2


def test_verify_missing_files(tmp_path):
    """verify() reports missing files when migration hasn't run."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/my-project/founder-profile.md", "name: Ike")

    m = Migrator(paths, "test-instance")
    result = m.verify()

    assert result["complete"] is False
    assert len(result["missing"]) == 1
    assert result["missing"][0]["source"] == "q-system/my-project/founder-profile.md"


def test_verify_includes_sqlite(tmp_path):
    """verify() checks metrics.db presence."""
    paths = make_paths(tmp_path)
    _create_legacy_db(paths.repo_dir / "q-system/output/metrics.db")

    m = Migrator(paths, "test-instance")
    result = m.verify()
    assert result["complete"] is False
    assert any("metrics.db" in item["expected"] for item in result["missing"])

    m.migrate()
    result2 = m.verify()
    assert result2["complete"] is True
    assert any("metrics.db" in p for p in result2["present"])
