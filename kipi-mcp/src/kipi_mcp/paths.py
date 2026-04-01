from __future__ import annotations
import os
import random
import re
from pathlib import Path

APP_NAME = "kipi-system"

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


def _detect_instance(base_dir: Path) -> str:
    """Resolve instance name from active-instance file or KIPI_INSTANCE env var.

    Reads {base_dir}/active-instance. Written by /q-setup.
    Falls back to 'default' if not configured.
    """
    env = os.environ.get("KIPI_INSTANCE")
    if env:
        return env
    marker = base_dir / "active-instance"
    if marker.exists():
        name = marker.read_text().strip()
        if name:
            return name
    return "default"


class KipiPaths:
    """Single source of truth for all kipi directory paths.

    Directory layout under a single base directory:
      {base}/
        global/              <- shared across instances (voice, audhd)
        instances/{name}/    <- per-instance everything (config + data + state)
        instance-registry.json

    The base directory is resolved from (in order):
    1. base_dir constructor arg (for tests)
    2. KIPI_PLUGIN_DATA env var (mapped from CLAUDE_PLUGIN_DATA in .mcp.json)
    3. ~/.kipi-system fallback (standalone / dev use)
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        repo_dir: Path | None = None,
        instance: str | None = None,
    ):
        self._base = Path(
            base_dir
            or os.environ.get("KIPI_PLUGIN_DATA")
            or Path.home() / f".{APP_NAME}"
        )
        self.repo_dir = Path(
            repo_dir
            or os.environ.get("KIPI_PLUGIN_ROOT")
            or Path(__file__).resolve().parents[3]
        )
        self.instance = instance or _detect_instance(self._base)

    # --- Base directories ---

    @property
    def _instance_dir(self) -> Path:
        return self._base / "instances" / self.instance

    @property
    def config_dir(self) -> Path:
        return self._instance_dir

    @property
    def data_dir(self) -> Path:
        return self._instance_dir

    @property
    def state_dir(self) -> Path:
        return self._instance_dir

    @property
    def global_dir(self) -> Path:
        """Shared config across all instances (voice, audhd)."""
        return self._base / "global"

    # --- Global subdirectories (shared) ---

    @property
    def voice_dir(self) -> Path:
        return self.global_dir / "voice"

    @property
    def audhd_dir(self) -> Path:
        return self.global_dir / "audhd"

    # --- Per-instance subdirectories ---

    @property
    def canonical_dir(self) -> Path:
        return self._instance_dir / "canonical"

    @property
    def marketing_config_dir(self) -> Path:
        return self._instance_dir / "marketing"

    @property
    def my_project_dir(self) -> Path:
        return self._instance_dir / "my-project"

    @property
    def memory_dir(self) -> Path:
        return self._instance_dir / "memory"

    @property
    def output_dir(self) -> Path:
        return self._instance_dir / "output"

    @property
    def bus_dir(self) -> Path:
        return self._instance_dir / "bus"

    @property
    def metrics_db(self) -> Path:
        return self._instance_dir / "metrics.db"

    @property
    def harvest_db(self) -> Path:
        return self._instance_dir / "harvest.db"

    @property
    def system_db(self) -> Path:
        return self._instance_dir / "system.db"

    # --- Repo subdirectories (system code, stays in git) ---

    @property
    def q_system_dir(self) -> Path:
        return self.repo_dir / "q-system"

    @property
    def agents_dir(self) -> Path:
        return self.repo_dir / "q-system" / "agent-pipeline" / "agents"

    @property
    def templates_dir(self) -> Path:
        return self.repo_dir / "q-system" / "agent-pipeline" / "templates"

    @property
    def schedule_template(self) -> Path:
        return self.repo_dir / "q-system" / "marketing" / "templates" / "schedule-template.html"

    @property
    def methodology_dir(self) -> Path:
        return self.repo_dir / "q-system" / "methodology"

    @property
    def registry_path(self) -> Path:
        return self._base / "instance-registry.json"

    @property
    def sources_dir(self) -> Path:
        """Plugin-level source YAML configs (ships with repo)."""
        return self.repo_dir / "kipi-mcp" / "sources"

    @property
    def instance_sources_dir(self) -> Path:
        """User-level source YAML overrides (per instance)."""
        return self._instance_dir / "sources"

    # --- Config files ---

    @property
    def founder_profile(self) -> Path:
        return self._instance_dir / "founder-profile.md"

    @property
    def enabled_integrations(self) -> Path:
        return self._instance_dir / "enabled-integrations.md"

    def ensure_dirs(self) -> None:
        """Create all directories if they don't exist."""
        for d in [
            self.global_dir,
            self.voice_dir,
            self.audhd_dir,
            self._instance_dir,
            self.canonical_dir,
            self.marketing_config_dir,
            self.marketing_config_dir / "assets",
            self.my_project_dir,
            self.memory_dir,
            self.memory_dir / "working",
            self.memory_dir / "weekly",
            self.memory_dir / "monthly",
            self.output_dir,
            self.output_dir / "drafts",
            self.bus_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)
