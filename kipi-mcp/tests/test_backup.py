"""Tests for kipi_mcp.backup module."""
import json
import tarfile
import pytest
from pathlib import Path

from kipi_mcp.backup import BackupManager, MANIFEST_NAME


@pytest.fixture
def backup_mgr(tmp_kipi_paths):
    """BackupManager with tmp paths and sample data."""
    # Seed some files
    (tmp_kipi_paths.config_dir / "founder-profile.md").write_text("# Profile\nName: Test")
    (tmp_kipi_paths.canonical_dir / "talk-tracks.md").write_text("# Talk Tracks")
    (tmp_kipi_paths.voice_dir / "voice-dna.md").write_text("# Voice DNA")  # global
    (tmp_kipi_paths.my_project_dir / "current-state.md").write_text("# State")
    (tmp_kipi_paths.memory_dir / "graph.jsonl").write_text('{"s":"a","p":"knows","o":"b"}')
    (tmp_kipi_paths.output_dir / "morning-log-2026-03-27.json").write_text("{}")
    return BackupManager(tmp_kipi_paths)


def test_backup_creates_archive(backup_mgr, tmp_kipi_paths):
    result = backup_mgr.backup()
    assert result["files_count"] == 6  # 1 global + 5 instance files
    assert result["size_bytes"] > 0
    assert Path(result["path"]).exists()
    assert "kipi-backup-" in result["path"]


def test_backup_custom_output_path(backup_mgr, tmp_path):
    out = tmp_path / "custom" / "my-backup.tar.gz"
    result = backup_mgr.backup(output_path=out)
    assert result["path"] == str(out)
    assert out.exists()


def test_backup_contains_manifest(backup_mgr):
    result = backup_mgr.backup()
    with tarfile.open(result["path"], "r:gz") as tar:
        names = tar.getnames()
        assert MANIFEST_NAME in names
        manifest = json.loads(tar.extractfile(MANIFEST_NAME).read())
        assert manifest["version"] == 1
        assert len(manifest["files"]) == 6


def test_backup_archive_structure(backup_mgr):
    result = backup_mgr.backup()
    with tarfile.open(result["path"], "r:gz") as tar:
        names = [n for n in tar.getnames() if n != MANIFEST_NAME]
        prefixes = {n.split("/")[0] for n in names}
        assert prefixes == {"global", "instance"}


def test_backup_skips_other_backups(backup_mgr, tmp_kipi_paths):
    # Create a fake old backup in output dir
    fake = tmp_kipi_paths.output_dir / "kipi-backup-20260101-000000.tar.gz"
    fake.write_text("fake")
    result = backup_mgr.backup()
    with tarfile.open(result["path"], "r:gz") as tar:
        names = tar.getnames()
        assert not any("kipi-backup-" in n and n.endswith(".tar.gz") for n in names if n != MANIFEST_NAME)


def test_restore_dry_run(backup_mgr, tmp_path):
    result = backup_mgr.backup()
    from kipi_mcp.paths import KipiPaths
    new_paths = KipiPaths(
        base_dir=tmp_path / "new_base",
        repo_dir=tmp_path / "repo",
        instance="restored",
    )
    new_paths.ensure_dirs()
    new_mgr = BackupManager(new_paths)

    restore_result = new_mgr.restore(Path(result["path"]), dry_run=True)
    assert restore_result["dry_run"] is True
    assert len(restore_result["restored"]) == 6
    assert not (new_paths.config_dir / "founder-profile.md").exists()


def test_restore_writes_files(backup_mgr, tmp_path):
    result = backup_mgr.backup()
    from kipi_mcp.paths import KipiPaths
    new_paths = KipiPaths(
        base_dir=tmp_path / "restored_base",
        repo_dir=tmp_path / "repo",
        instance="restored",
    )
    new_paths.ensure_dirs()
    new_mgr = BackupManager(new_paths)

    restore_result = new_mgr.restore(Path(result["path"]), dry_run=False)
    assert restore_result["dry_run"] is False
    assert len(restore_result["restored"]) == 6
    assert (new_paths.config_dir / "founder-profile.md").read_text() == "# Profile\nName: Test"
    assert (new_paths.my_project_dir / "current-state.md").read_text() == "# State"


def test_restore_missing_archive_raises(backup_mgr):
    with pytest.raises(FileNotFoundError):
        backup_mgr.restore(Path("/nonexistent/backup.tar.gz"))


def test_list_backups_empty(tmp_kipi_paths):
    mgr = BackupManager(tmp_kipi_paths)
    assert mgr.list_backups() == []


def test_list_backups_returns_sorted(backup_mgr, tmp_path):
    # Use explicit output paths to guarantee distinct filenames
    backup_mgr.backup(output_path=tmp_path / "kipi-backup-20260101-000000.tar.gz")
    backup_mgr.backup(output_path=tmp_path / "kipi-backup-20260102-000000.tar.gz")
    # Copy them into the output dir where list_backups looks
    import shutil
    for f in tmp_path.glob("kipi-backup-*.tar.gz"):
        shutil.copy2(f, backup_mgr.paths.output_dir / f.name)
    backups = backup_mgr.list_backups()
    assert len(backups) >= 2


def test_rotate_keeps_max(backup_mgr, tmp_kipi_paths):
    """Create 7 backups, rotate(5), verify only 5 remain."""
    out = tmp_kipi_paths.output_dir
    for i in range(7):
        backup_mgr.backup(output_path=out / f"kipi-backup-2026010{i}-000000.tar.gz")
    assert len(backup_mgr.list_backups()) == 7
    result = backup_mgr.rotate(5)
    assert result["kept"] == 5
    assert len(result["deleted"]) == 2
    assert len(backup_mgr.list_backups()) == 5


def test_rotate_nothing_to_delete(backup_mgr, tmp_kipi_paths):
    """Create 3 backups, rotate(5), verify all 3 remain."""
    out = tmp_kipi_paths.output_dir
    for i in range(3):
        backup_mgr.backup(output_path=out / f"kipi-backup-2026010{i}-000000.tar.gz")
    result = backup_mgr.rotate(5)
    assert result["kept"] == 3
    assert result["deleted"] == []
    assert len(backup_mgr.list_backups()) == 3


def test_roundtrip_preserves_content(backup_mgr, tmp_path):
    """Full roundtrip: backup -> restore to new location -> verify identical."""
    result = backup_mgr.backup()
    from kipi_mcp.paths import KipiPaths
    new_paths = KipiPaths(
        base_dir=tmp_path / "rt_base",
        repo_dir=tmp_path / "repo",
        instance="rt",
    )
    new_paths.ensure_dirs()
    new_mgr = BackupManager(new_paths)
    new_mgr.restore(Path(result["path"]), dry_run=False)

    assert (new_paths.canonical_dir / "talk-tracks.md").read_text() == "# Talk Tracks"
    assert (new_paths.voice_dir / "voice-dna.md").read_text() == "# Voice DNA"
    assert (new_paths.memory_dir / "graph.jsonl").read_text() == '{"s":"a","p":"knows","o":"b"}'
    assert (new_paths.output_dir / "morning-log-2026-03-27.json").read_text() == "{}"
