from __future__ import annotations
import os
import random
import re
from pathlib import Path
from platformdirs import user_config_path, user_data_path, user_state_path

APP_NAME = "kipi-system"

# Word list for Discord-style instance suffixes
_SUFFIX_WORDS = [
    "arrow", "blaze", "comet", "delta", "ember", "frost", "ghost", "haven",
    "ion", "jade", "kite", "lunar", "maple", "noble", "orbit", "prism",
    "quasar", "ridge", "spark", "tidal", "unity", "viper", "wave", "xenon",
    "yeti", "zephyr", "atlas", "bolt", "crest", "drift", "echo", "flare",
    "grove", "hawk", "iris", "jewel", "karma", "latch", "mist", "nova",
    "opal", "pulse", "quest", "reef", "sage", "torch", "umbra", "vault",
    "wisp", "apex", "bass", "crow", "dusk", "fern", "glow", "haze",
    "iron", "jazz", "kelp", "loom", "moth", "neon", "onyx", "peak",
]


def _slugify(name: str, max_len: int = 20) -> str:
    """Lowercase, strip non-alphanum, truncate."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:max_len]


def generate_instance_name(company: str, existing: set[str] | None = None) -> str:
    """Generate a Discord-style instance name: slug-word##.

    Examples: eqbit-dragon12, acme-frost7
    Checks against existing names and retries on collision.
    """
    existing = existing or set()
    slug = _slugify(company)
    for _ in range(50):
        word = random.choice(_SUFFIX_WORDS)
        num = random.randint(1, 99)
        name = f"{slug}-{word}{num}"
        if name not in existing:
            return name
    return f"{slug}-{random.randint(1000, 9999)}"


def _detect_instance(repo_dir: Path) -> str:
    """Resolve instance name from env var, .kipi-instance file, or repo dirname."""
    env = os.environ.get("KIPI_INSTANCE")
    if env:
        return env
    marker = repo_dir / ".kipi-instance"
    if marker.exists():
        name = marker.read_text().strip()
        if name:
            return name
    return repo_dir.name


class KipiPaths:
    """Single source of truth for all kipi directory paths.

    Directory layout:
      {base}/kipi/
        global/          ← shared across instances (voice, audhd)
        instances/{name}/ ← per-instance data

    On macOS all three bases resolve to ~/Library/Application Support/kipi/.
    On Linux they split to ~/.config/kipi/, ~/.local/share/kipi/, ~/.local/state/kipi/.
    """

    def __init__(
        self,
        config_dir: Path | None = None,
        data_dir: Path | None = None,
        state_dir: Path | None = None,
        repo_dir: Path | None = None,
        instance: str | None = None,
    ):
        self._config_base = Path(config_dir or os.environ.get("KIPI_CONFIG_DIR", user_config_path(APP_NAME)))
        self._data_base = Path(data_dir or os.environ.get("KIPI_DATA_DIR", user_data_path(APP_NAME)))
        self._state_base = Path(state_dir or os.environ.get("KIPI_STATE_DIR", user_state_path(APP_NAME)))
        self.repo_dir = Path(repo_dir or os.environ.get("KIPI_HOME", Path(__file__).resolve().parents[3]))
        self.instance = instance or _detect_instance(self.repo_dir)

    # --- Base directories ---

    @property
    def config_dir(self) -> Path:
        return self._config_base / "instances" / self.instance

    @property
    def data_dir(self) -> Path:
        return self._data_base / "instances" / self.instance

    @property
    def state_dir(self) -> Path:
        return self._state_base / "instances" / self.instance

    @property
    def global_dir(self) -> Path:
        """Shared config across all instances (voice, audhd)."""
        return self._config_base / "global"

    # --- Global subdirectories (shared) ---

    @property
    def voice_dir(self) -> Path:
        return self.global_dir / "voice"

    @property
    def audhd_dir(self) -> Path:
        return self.global_dir / "audhd"

    # --- Per-instance config subdirectories ---

    @property
    def canonical_dir(self) -> Path:
        return self.config_dir / "canonical"

    @property
    def marketing_config_dir(self) -> Path:
        return self.config_dir / "marketing"

    # --- Per-instance data subdirectories ---

    @property
    def my_project_dir(self) -> Path:
        return self.data_dir / "my-project"

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    # --- Per-instance state subdirectories ---

    @property
    def output_dir(self) -> Path:
        return self.state_dir / "output"

    @property
    def bus_dir(self) -> Path:
        return self.state_dir / "bus"

    # --- Repo subdirectories (system code, stays in git) ---

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

    # --- Config files ---

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
        """Create all directories if they don't exist."""
        for d in [
            # Global shared
            self.global_dir,
            self.voice_dir,
            self.audhd_dir,
            # Per-instance config
            self.config_dir,
            self.canonical_dir,
            self.marketing_config_dir,
            self.marketing_config_dir / "assets",
            # Per-instance data
            self.data_dir,
            self.my_project_dir,
            self.memory_dir,
            self.memory_dir / "working",
            self.memory_dir / "weekly",
            self.memory_dir / "monthly",
            # Per-instance state
            self.state_dir,
            self.output_dir,
            self.output_dir / "drafts",
            self.bus_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)
