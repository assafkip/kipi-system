from __future__ import annotations
import shutil
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

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
]

# State files are runtime-generated, don't need migration (they'll be created fresh)
# But if they exist, move them
STATE_DIRS = [
    ("q-system/output", "output", "state"),
]


class Migrator:
    def __init__(self, paths):
        """paths is a KipiPaths instance or duck-type with config_dir, data_dir, state_dir, repo_dir."""
        self.paths = paths

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

        return {
            "needs_migration": needs_migration,
            "already_migrated": already_migrated,
            "templates_skipped": templates,
        }

    def migrate(self, dry_run: bool = False) -> dict:
        """Copy files from old repo locations to XDG directories."""
        if not dry_run:
            self.paths.ensure_dirs()

        copied = []
        skipped = []
        errors = []

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

        return {"copied": copied, "skipped": skipped, "errors": errors}

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

        return {
            "present": present,
            "missing": missing,
            "complete": len(missing) == 0,
        }
