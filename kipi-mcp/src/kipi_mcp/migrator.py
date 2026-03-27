from __future__ import annotations
import shutil
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Candidate locations for metrics.db in the old repo layout (checked in order)
LEGACY_DB_CANDIDATES = [
    "q-system/output/metrics.db",
    "q-system/metrics.db",
    "metrics.db",
]

# Map of (old_repo_relative_path, new_xdg_relative_path, target_base)
# target_base is "config", "data", or "state"
FILE_MAP = [
    # Config files
    ("q-system/my-project/founder-profile.md", "founder-profile.md", "config"),
    ("q-system/my-project/enabled-integrations.md", "enabled-integrations.md", "config"),
    # Canonical files
    ("q-system/canonical/discovery.md", "canonical/discovery.md", "config"),
    ("q-system/canonical/objections.md", "canonical/objections.md", "config"),
    ("q-system/canonical/talk-tracks.md", "canonical/talk-tracks.md", "config"),
    ("q-system/canonical/decisions.md", "canonical/decisions.md", "config"),
    ("q-system/canonical/engagement-playbook.md", "canonical/engagement-playbook.md", "config"),
    ("q-system/canonical/lead-lifecycle-rules.md", "canonical/lead-lifecycle-rules.md", "config"),
    ("q-system/canonical/market-intelligence.md", "canonical/market-intelligence.md", "config"),
    ("q-system/canonical/pricing-framework.md", "canonical/pricing-framework.md", "config"),
    ("q-system/canonical/verticals.md", "canonical/verticals.md", "config"),
    ("q-system/canonical/content-intelligence.md", "canonical/content-intelligence.md", "config"),
    # Voice/AUDHD → global (shared across instances)
    (".claude/skills/founder-voice/references/voice-dna.md", "voice/voice-dna.md", "global"),
    (".claude/skills/founder-voice/references/writing-samples.md", "voice/writing-samples.md", "global"),
    (".claude/skills/audhd-executive-function/references/user-profile.md", "audhd/user-profile.md", "global"),
    (".claude/skills/audhd-executive-function/references/research.md", "audhd/research.md", "global"),
    # Marketing config
    ("q-system/marketing/content-guardrails.md", "marketing/content-guardrails.md", "config"),
    ("q-system/marketing/brand-voice.md", "marketing/brand-voice.md", "config"),
    ("q-system/marketing/content-themes.md", "marketing/content-themes.md", "config"),
    # Data files
    ("q-system/my-project/current-state.md", "my-project/current-state.md", "data"),
    ("q-system/my-project/relationships.md", "my-project/relationships.md", "data"),
    ("q-system/my-project/competitive-landscape.md", "my-project/competitive-landscape.md", "data"),
    ("q-system/my-project/progress.md", "my-project/progress.md", "data"),
    ("q-system/my-project/notion-ids.md", "my-project/notion-ids.md", "data"),
]

# Directories to copy recursively
DIR_MAP = [
    ("q-system/memory", "memory", "data"),
    ("q-system/marketing/assets", "marketing/assets", "config"),
    ("q-system/seed-materials", "seed-materials", "data"),
]

# State files are runtime-generated, don't need migration (they'll be created fresh)
# But if they exist, move them
STATE_DIRS = [
    ("q-system/output", "output", "state"),
]


class Migrator:
    def __init__(self, paths, instance_name: str | None = None):
        """paths is a KipiPaths instance or duck-type with config_dir, data_dir, state_dir, repo_dir.

        Args:
            instance_name: If provided, overrides the instance name on paths and
                writes a .kipi-instance marker during migrate(). Required when
                migrating from a legacy layout that has no .kipi-instance file.
        """
        self.paths = paths
        self._instance_override = instance_name
        if instance_name:
            self.paths.instance = instance_name

    def _target_dir(self, base: str) -> Path:
        if base == "config":
            return self.paths.config_dir
        elif base == "data":
            return self.paths.data_dir
        elif base == "state":
            return self.paths.state_dir
        elif base == "global":
            return self.paths.global_dir
        raise ValueError(f"Unknown base: {base}")

    def _has_instance_marker(self) -> bool:
        """Check if .kipi-instance marker exists in the repo."""
        marker = self.paths.repo_dir / ".kipi-instance"
        return marker.exists() and bool(marker.read_text().strip())

    def _find_legacy_db(self) -> Path | None:
        """Find metrics.db in old repo locations."""
        for candidate in LEGACY_DB_CANDIDATES:
            path = self.paths.repo_dir / candidate
            if path.exists() and path.is_file():
                return path
        return None

    def _is_template(self, path: Path) -> bool:
        """Check if file is a template (contains {{SETUP_NEEDED}})."""
        if not path.exists() or not path.is_file():
            return False
        try:
            return "{{SETUP_NEEDED}}" in path.read_text()
        except (UnicodeDecodeError, PermissionError):
            return False

    def detect(self) -> dict:
        """Check which files need migration."""
        needs_migration = []
        already_migrated = []
        templates = []

        for old_rel, new_rel, base in FILE_MAP:
            old_path = self.paths.repo_dir / old_rel
            new_path = self._target_dir(base) / new_rel

            if not old_path.exists():
                continue
            if self._is_template(old_path):
                templates.append(old_rel)
                continue
            if new_path.exists():
                already_migrated.append(old_rel)
                continue
            needs_migration.append(old_rel)

        for old_rel, new_rel, base in DIR_MAP + STATE_DIRS:
            old_path = self.paths.repo_dir / old_rel
            if old_path.exists() and old_path.is_dir() and any(old_path.iterdir()):
                new_path = self._target_dir(base) / new_rel
                if new_path.exists() and any(new_path.iterdir()):
                    already_migrated.append(old_rel + "/")
                else:
                    needs_migration.append(old_rel + "/")

        # Check for legacy metrics.db
        legacy_db = self._find_legacy_db()
        db_dest = self.paths.data_dir / "metrics.db"
        if legacy_db and not db_dest.exists():
            needs_migration.append(str(legacy_db.relative_to(self.paths.repo_dir)))
        elif legacy_db and db_dest.exists():
            already_migrated.append(str(legacy_db.relative_to(self.paths.repo_dir)))

        has_marker = self._has_instance_marker()
        return {
            "needs_migration": needs_migration,
            "already_migrated": already_migrated,
            "templates_skipped": templates,
            "instance_name": self.paths.instance,
            "has_instance_marker": has_marker,
            "instance_name_is_fallback": not has_marker and not self._instance_override,
        }

    def migrate(self, dry_run: bool = False) -> dict:
        """Copy files from old repo locations to XDG directories.

        Raises ValueError if legacy layout is detected but no instance_name
        was provided and no .kipi-instance marker exists.
        """
        if not self._has_instance_marker() and not self._instance_override:
            raise ValueError(
                "Legacy layout detected but no instance name set. "
                "Pass instance_name to Migrator or call kipi_set_instance_name first. "
                "Use kipi_suggest_instance_name to generate one from your company name."
            )

        if not dry_run:
            self.paths.ensure_dirs()

        copied = []
        skipped = []
        errors = []

        # Write .kipi-instance marker if we're setting a new instance name
        if self._instance_override:
            marker = self.paths.repo_dir / ".kipi-instance"
            if dry_run:
                copied.append({"from": "(generated)", "to": str(marker), "note": f"instance={self._instance_override}"})
            else:
                try:
                    marker.write_text(self._instance_override + "\n")
                    copied.append({"from": "(generated)", "to": str(marker), "note": f"instance={self._instance_override}"})
                except Exception as e:
                    errors.append({"file": ".kipi-instance", "error": str(e)})

        # Migrate individual files
        for old_rel, new_rel, base in FILE_MAP:
            old_path = self.paths.repo_dir / old_rel
            new_path = self._target_dir(base) / new_rel

            if not old_path.exists():
                continue
            if self._is_template(old_path):
                skipped.append({"file": old_rel, "reason": "template"})
                continue
            if new_path.exists():
                if old_path.stat().st_mtime <= new_path.stat().st_mtime:
                    skipped.append({"file": old_rel, "reason": "already_migrated"})
                    continue

            if dry_run:
                copied.append({"from": old_rel, "to": str(new_path)})
                continue

            try:
                new_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old_path, new_path)
                copied.append({"from": old_rel, "to": str(new_path)})
            except Exception as e:
                errors.append({"file": old_rel, "error": str(e)})

        # Migrate directories
        for old_rel, new_rel, base in DIR_MAP + STATE_DIRS:
            old_path = self.paths.repo_dir / old_rel
            new_path = self._target_dir(base) / new_rel

            if not old_path.exists() or not old_path.is_dir():
                continue

            for src_file in old_path.rglob("*"):
                if not src_file.is_file():
                    continue
                if self._is_template(src_file):
                    skipped.append({"file": str(src_file.relative_to(self.paths.repo_dir)), "reason": "template"})
                    continue

                rel = src_file.relative_to(old_path)
                dst_file = new_path / rel

                if dst_file.exists() and src_file.stat().st_mtime <= dst_file.stat().st_mtime:
                    skipped.append({"file": str(src_file.relative_to(self.paths.repo_dir)), "reason": "already_migrated"})
                    continue

                if dry_run:
                    copied.append({"from": str(src_file.relative_to(self.paths.repo_dir)), "to": str(dst_file)})
                    continue

                try:
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dst_file)
                    copied.append({"from": str(src_file.relative_to(self.paths.repo_dir)), "to": str(dst_file)})
                except Exception as e:
                    errors.append({"file": str(src_file.relative_to(self.paths.repo_dir)), "error": str(e)})

        # Migrate metrics.db
        legacy_db = self._find_legacy_db()
        if legacy_db:
            db_dest = self.paths.data_dir / "metrics.db"
            old_rel = str(legacy_db.relative_to(self.paths.repo_dir))
            if db_dest.exists() and legacy_db.stat().st_mtime <= db_dest.stat().st_mtime:
                skipped.append({"file": old_rel, "reason": "already_migrated"})
            elif dry_run:
                copied.append({"from": old_rel, "to": str(db_dest)})
            else:
                try:
                    db_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(legacy_db, db_dest)
                    copied.append({"from": old_rel, "to": str(db_dest)})
                except Exception as e:
                    errors.append({"file": old_rel, "error": str(e)})

        return {
            "copied": copied,
            "skipped": skipped,
            "errors": errors,
            "instance_name": self.paths.instance,
        }

    def verify(self) -> dict:
        """Verify all expected files exist in new locations."""
        present = []
        missing = []

        for old_rel, new_rel, base in FILE_MAP:
            old_path = self.paths.repo_dir / old_rel
            new_path = self._target_dir(base) / new_rel

            if not old_path.exists() or self._is_template(old_path):
                continue

            if new_path.exists():
                present.append(str(new_path))
            else:
                missing.append({"expected": str(new_path), "source": old_rel})

        # Verify metrics.db if it existed in old layout
        legacy_db = self._find_legacy_db()
        if legacy_db:
            db_dest = self.paths.data_dir / "metrics.db"
            if db_dest.exists():
                present.append(str(db_dest))
            else:
                missing.append({
                    "expected": str(db_dest),
                    "source": str(legacy_db.relative_to(self.paths.repo_dir)),
                })

        return {
            "present": present,
            "missing": missing,
            "complete": len(missing) == 0,
        }
