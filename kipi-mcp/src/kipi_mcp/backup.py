"""Backup and restore for kipi user data.

Creates portable tar.gz archives that can be imported on any platform.
Archive layout uses logical prefixes (global/, instance/) that are
mapped back to real directories on restore.
"""
from __future__ import annotations

import json
import tarfile
import io
from datetime import datetime, timezone
from pathlib import Path

from kipi_mcp.paths import KipiPaths

# Logical prefixes inside the archive — platform-independent
_ARCHIVE_DIRS = {
    "global": "global",
    "instance": "instance",
}

MANIFEST_NAME = "kipi-backup-manifest.json"


class BackupManager:
    """Create and restore kipi data archives."""

    def __init__(self, paths: KipiPaths):
        self.paths = paths

    def _source_map(self) -> dict[str, Path]:
        """Map logical archive prefixes to real directories."""
        return {
            "global": self.paths.global_dir,
            "instance": self.paths.config_dir,
        }

    def backup(self, output_path: Path | None = None) -> dict:
        """Create a tar.gz archive of all user data.

        Args:
            output_path: Where to write the archive. Defaults to
                         {state_dir}/output/kipi-backup-{timestamp}.tar.gz

        Returns:
            dict with keys: path, files_count, size_bytes, timestamp
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        if output_path is None:
            self.paths.output_dir.mkdir(parents=True, exist_ok=True)
            output_path = self.paths.output_dir / f"kipi-backup-{timestamp}.tar.gz"

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        manifest = {
            "version": 1,
            "timestamp": timestamp,
            "source_paths": {k: str(v) for k, v in self._source_map().items()},
            "files": [],
        }

        files_count = 0
        with tarfile.open(output_path, "w:gz") as tar:
            for prefix, src_dir in self._source_map().items():
                if not src_dir.exists():
                    continue
                for fpath in sorted(src_dir.rglob("*")):
                    if not fpath.is_file():
                        continue
                    # Skip the backup files themselves
                    if fpath.name.startswith("kipi-backup-") and fpath.suffix == ".gz":
                        continue
                    arcname = f"{_ARCHIVE_DIRS[prefix]}/{fpath.relative_to(src_dir)}"
                    tar.add(fpath, arcname=arcname)
                    manifest["files"].append(arcname)
                    files_count += 1

            # Write manifest into archive
            manifest_bytes = json.dumps(manifest, indent=2).encode()
            info = tarfile.TarInfo(name=MANIFEST_NAME)
            info.size = len(manifest_bytes)
            tar.addfile(info, io.BytesIO(manifest_bytes))

        return {
            "path": str(output_path),
            "files_count": files_count,
            "size_bytes": output_path.stat().st_size,
            "timestamp": timestamp,
        }

    def restore(self, archive_path: Path, dry_run: bool = True) -> dict:
        """Restore user data from a tar.gz archive.

        Args:
            archive_path: Path to the backup archive.
            dry_run: If True, list what would be restored without writing.

        Returns:
            dict with keys: restored (list of files), skipped, dry_run
        """
        archive_path = Path(archive_path)
        if not archive_path.exists():
            raise FileNotFoundError(f"Archive not found: {archive_path}")

        dest_map = {
            _ARCHIVE_DIRS["global"]: self.paths.global_dir,
            _ARCHIVE_DIRS["instance"]: self.paths.config_dir,
            # Legacy archive compat: map old config/data/state to instance dir
            "config": self.paths.config_dir,
            "data": self.paths.data_dir,
            "state": self.paths.state_dir,
        }

        restored = []
        skipped = []

        with tarfile.open(archive_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name == MANIFEST_NAME:
                    continue
                if not member.isfile():
                    continue

                # Determine destination
                parts = member.name.split("/", 1)
                if len(parts) < 2 or parts[0] not in dest_map:
                    skipped.append(member.name)
                    continue

                dest_dir = dest_map[parts[0]]
                dest_file = dest_dir / parts[1]

                if dry_run:
                    restored.append(str(dest_file))
                    continue

                dest_file.parent.mkdir(parents=True, exist_ok=True)
                # Extract to temp then move to avoid partial writes
                extracted = tar.extractfile(member)
                if extracted is None:
                    skipped.append(member.name)
                    continue
                dest_file.write_bytes(extracted.read())
                restored.append(str(dest_file))

        return {
            "restored": restored,
            "skipped": skipped,
            "dry_run": dry_run,
            "archive": str(archive_path),
        }

    def rotate(self, max_backups: int = 5) -> dict:
        """Delete oldest backups beyond max_backups count.

        Rotation is by count (number of backup files), not by calendar date.
        If user skips days, still keeps exactly max_backups most recent files.
        """
        all_backups = self.list_backups()  # sorted newest first
        deleted = []
        if len(all_backups) > max_backups:
            for old in all_backups[max_backups:]:
                Path(old["path"]).unlink(missing_ok=True)
                deleted.append(old["name"])
        return {"kept": min(len(all_backups), max_backups), "deleted": deleted}

    def list_backups(self) -> list[dict]:
        """List existing backup archives in the output directory."""
        backups = []
        output = self.paths.output_dir
        if not output.exists():
            return backups
        for f in sorted(output.glob("kipi-backup-*.tar.gz"), reverse=True):
            backups.append({
                "path": str(f),
                "name": f.name,
                "size_bytes": f.stat().st_size,
                "modified": f.stat().st_mtime,
            })
        return backups
