from __future__ import annotations
import os
from pathlib import Path
from platformdirs import user_config_path, user_data_path, user_state_path


class KipiPaths:
    """Single source of truth for all kipi directory paths."""

    def __init__(
        self,
        config_dir: Path | None = None,
        data_dir: Path | None = None,
        state_dir: Path | None = None,
        repo_dir: Path | None = None,
    ):
        self.config_dir = Path(config_dir or os.environ.get("KIPI_CONFIG_DIR", user_config_path("kipi")))
        self.data_dir = Path(data_dir or os.environ.get("KIPI_DATA_DIR", user_data_path("kipi")))
        self.state_dir = Path(state_dir or os.environ.get("KIPI_STATE_DIR", user_state_path("kipi")))
        self.repo_dir = Path(repo_dir or os.environ.get("KIPI_HOME", Path(__file__).resolve().parents[3]))

    # Config subdirectories
    @property
    def canonical_dir(self) -> Path:
        return self.config_dir / "canonical"

    @property
    def voice_dir(self) -> Path:
        return self.config_dir / "voice"

    @property
    def audhd_dir(self) -> Path:
        return self.config_dir / "audhd"

    @property
    def marketing_config_dir(self) -> Path:
        return self.config_dir / "marketing"

    # Data subdirectories
    @property
    def my_project_dir(self) -> Path:
        return self.data_dir / "my-project"

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    # State subdirectories
    @property
    def output_dir(self) -> Path:
        return self.state_dir / "output"

    @property
    def bus_dir(self) -> Path:
        return self.state_dir / "bus"

    # Repo subdirectories (system code, stays in git)
    @property
    def q_system_dir(self) -> Path:
        return self.repo_dir / "q-system"

    @property
    def agents_dir(self) -> Path:
        return self.repo_dir / "q-system" / ".q-system" / "agent-pipeline" / "agents"

    @property
    def steps_dir(self) -> Path:
        return self.repo_dir / "q-system" / ".q-system" / "steps"

    @property
    def commands_file(self) -> Path:
        return self.repo_dir / "q-system" / ".q-system" / "commands.md"

    @property
    def templates_dir(self) -> Path:
        return self.repo_dir / "q-system" / ".q-system" / "agent-pipeline" / "templates"

    @property
    def schedule_template(self) -> Path:
        return self.repo_dir / "q-system" / "marketing" / "templates" / "schedule-template.html"

    @property
    def methodology_dir(self) -> Path:
        return self.repo_dir / "q-system" / "methodology"

    @property
    def registry_path(self) -> Path:
        return self.repo_dir / "instance-registry.json"

    # Config files (top-level in config_dir)
    @property
    def founder_profile(self) -> Path:
        return self.config_dir / "founder-profile.md"

    @property
    def enabled_integrations(self) -> Path:
        return self.config_dir / "enabled-integrations.md"

    def detect_legacy_layout(self) -> bool:
        """Check if user data still lives in the repo (old format)."""
        old_profile = self.repo_dir / "q-system" / "my-project" / "founder-profile.md"
        if not old_profile.exists():
            return False
        content = old_profile.read_text()
        return "{{SETUP_NEEDED}}" not in content

    def ensure_dirs(self) -> None:
        """Create all XDG directories if they don't exist."""
        for d in [
            self.config_dir,
            self.canonical_dir,
            self.voice_dir,
            self.audhd_dir,
            self.marketing_config_dir,
            self.marketing_config_dir / "assets",
            self.data_dir,
            self.my_project_dir,
            self.memory_dir,
            self.memory_dir / "working",
            self.memory_dir / "weekly",
            self.memory_dir / "monthly",
            self.state_dir,
            self.output_dir,
            self.output_dir / "drafts",
            self.bus_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)
