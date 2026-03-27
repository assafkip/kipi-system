import os
import time
from types import SimpleNamespace

import pytest

from kipi_mcp.migrator import FILE_MAP, DIR_MAP, STATE_DIRS, Migrator


def make_paths(tmp_path):
    paths = SimpleNamespace(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        state_dir=tmp_path / "state",
        repo_dir=tmp_path / "repo",
    )
    paths.ensure_dirs = lambda: None
    return paths


def _create_file(path, content="real content"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------

def test_detect_fresh_install(tmp_path):
    """No user data files in repo -> empty needs_migration."""
    paths = make_paths(tmp_path)
    paths.repo_dir.mkdir()
    m = Migrator(paths)
    result = m.detect()
    assert result["needs_migration"] == []
    assert result["already_migrated"] == []
    assert result["templates_skipped"] == []


def test_detect_template_files_skipped(tmp_path):
    """Files containing {{SETUP_NEEDED}} are listed as templates, not migration targets."""
    paths = make_paths(tmp_path)
    old = paths.repo_dir / "q-system/my-project/founder-profile.md"
    _create_file(old, "# Profile\n{{SETUP_NEEDED}}\n")

    m = Migrator(paths)
    result = m.detect()
    assert "q-system/my-project/founder-profile.md" in result["templates_skipped"]
    assert result["needs_migration"] == []


def test_detect_user_data_needs_migration(tmp_path):
    """Populated files flagged for migration."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/my-project/founder-profile.md", "name: Ike")
    _create_file(paths.repo_dir / "q-system/canonical/objections.md", "obj 1")

    m = Migrator(paths)
    result = m.detect()
    assert "q-system/my-project/founder-profile.md" in result["needs_migration"]
    assert "q-system/canonical/objections.md" in result["needs_migration"]


def test_detect_already_migrated(tmp_path):
    """Files already in XDG location listed as already_migrated."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/my-project/founder-profile.md", "name: Ike")
    # Also present in config dir
    _create_file(paths.config_dir / "founder-profile.md", "name: Ike")

    m = Migrator(paths)
    result = m.detect()
    assert "q-system/my-project/founder-profile.md" in result["already_migrated"]
    assert result["needs_migration"] == []


# ---------------------------------------------------------------------------
# migrate()
# ---------------------------------------------------------------------------

def test_migrate_copies_files(tmp_path):
    """Files copied to correct XDG locations."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/my-project/founder-profile.md", "name: Ike")
    _create_file(paths.repo_dir / "q-system/canonical/objections.md", "obj 1")
    _create_file(paths.repo_dir / "q-system/my-project/current-state.md", "state data")

    m = Migrator(paths)
    result = m.migrate()

    assert len(result["errors"]) == 0
    assert (paths.config_dir / "founder-profile.md").read_text() == "name: Ike"
    assert (paths.config_dir / "canonical/objections.md").read_text() == "obj 1"
    assert (paths.data_dir / "my-project/current-state.md").read_text() == "state data"


def test_migrate_skips_templates(tmp_path):
    """Template files not copied."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/my-project/founder-profile.md", "{{SETUP_NEEDED}}")

    m = Migrator(paths)
    result = m.migrate()

    assert len(result["copied"]) == 0
    assert any(s["reason"] == "template" for s in result["skipped"])
    assert not (paths.config_dir / "founder-profile.md").exists()


def test_migrate_skips_already_present(tmp_path):
    """Idempotent: doesn't overwrite newer files in XDG location."""
    paths = make_paths(tmp_path)
    old_file = paths.repo_dir / "q-system/my-project/founder-profile.md"
    _create_file(old_file, "old content")

    new_file = paths.config_dir / "founder-profile.md"
    _create_file(new_file, "new content")
    # Make destination newer
    future = time.time() + 10
    os.utime(new_file, (future, future))

    m = Migrator(paths)
    result = m.migrate()

    assert any(s["reason"] == "already_migrated" for s in result["skipped"])
    assert new_file.read_text() == "new content"


def test_migrate_dry_run(tmp_path):
    """Reports what would happen without actually copying."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/my-project/founder-profile.md", "name: Ike")

    m = Migrator(paths)
    result = m.migrate(dry_run=True)

    assert len(result["copied"]) == 1
    assert result["copied"][0]["from"] == "q-system/my-project/founder-profile.md"
    assert not (paths.config_dir / "founder-profile.md").exists()


def test_migrate_directories(tmp_path):
    """memory/ directory recursively copied to data dir."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/memory/working/session.md", "session notes")
    _create_file(paths.repo_dir / "q-system/memory/weekly/week1.md", "week 1")

    m = Migrator(paths)
    result = m.migrate()

    assert len(result["errors"]) == 0
    assert (paths.data_dir / "memory/working/session.md").read_text() == "session notes"
    assert (paths.data_dir / "memory/weekly/week1.md").read_text() == "week 1"


# ---------------------------------------------------------------------------
# verify()
# ---------------------------------------------------------------------------

def test_verify_after_migration(tmp_path):
    """verify() returns complete=True after successful migrate()."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/my-project/founder-profile.md", "name: Ike")
    _create_file(paths.repo_dir / "q-system/canonical/objections.md", "obj 1")

    m = Migrator(paths)
    m.migrate()
    result = m.verify()

    assert result["complete"] is True
    assert len(result["missing"]) == 0
    assert len(result["present"]) == 2


def test_verify_missing_files(tmp_path):
    """verify() reports missing files when migration hasn't run."""
    paths = make_paths(tmp_path)
    _create_file(paths.repo_dir / "q-system/my-project/founder-profile.md", "name: Ike")

    m = Migrator(paths)
    result = m.verify()

    assert result["complete"] is False
    assert len(result["missing"]) == 1
    assert result["missing"][0]["source"] == "q-system/my-project/founder-profile.md"
