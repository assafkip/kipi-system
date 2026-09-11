from __future__ import annotations
import os
import random
import re
from pathlib import Path

APP_NAME = "kipi-system"


class PathContractError(RuntimeError):
    """Carries a `kind` so callers can tell a MISCONFIGURATION from a normal state.

    Not decoration. bus_verifier has to distinguish "this repo simply is not an
    instance" (the skeleton, a fresh clone -- there is no canonical tree and that
    is fine) from "the registry is missing or the registered tree is absent"
    (someone must fix something). Message-matching for that would be fragile, so
    the kind is set at each raise site:

        no-registry       the registry file does not exist        -> misconfig
        unreadable        the registry exists but will not parse  -> misconfig
        duplicate-name    two rows claim one instance name        -> misconfig
        no-canonical      registered, but the tree is not there   -> misconfig
        unregistered      this repo is not a registered instance  -> NORMAL
    """

    def __init__(self, message: str, kind: str = "unknown"):
        super().__init__(message)
        self.kind = kind


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
        # Whether base_dir was HANDED to us decides how registry_path resolves.
        # A test that passes base_dir must stay hermetic; the deployed server, which
        # passes nothing, must be allowed to go find a registry that exists.
        self._base_explicit = base_dir is not None
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
        self.instance = instance or self._resolve_instance()

    def _resolve_instance(self) -> str:
        """Which instance this process serves. ORDER IS THE SECURITY PROPERTY.

        SCAR (Codex review of PR #240, major -- a leak introduced by the fix that
        exists to prevent leaks). The first version consulted CLAUDE_PROJECT_DIR
        only when the answer was already the "default" sentinel, so the
        `{base}/active-instance` marker outranked it. That marker lives in PLUGIN
        DATA, which is SHARED BY EVERY PROJECT on the machine. Measured:

            CLAUDE_PROJECT_DIR : ~/projects/consulting
            shared marker says : KTLYST_strategy
            canonical_dir      : ~/projects/cole-gtm/projects/strategy/q-ktlyst/canonical

        A session in one project read another project's canonical tree. Ordering:

          1. explicit `instance=` argument -- the caller states it outright.
          2. KIPI_INSTANCE -- per-PROCESS env, deliberate and not shared.
          3. CLAUDE_PROJECT_DIR matched against the registry -- per-PROJECT and
             authoritative for "which project is this process actually in".
          4. the shared active-instance marker -- legacy, and last precisely
             because one stale write to it would otherwise redirect every project.
          5. "default".
        """
        env = os.environ.get("KIPI_INSTANCE")
        if env:
            return env
        from_project = self._instance_from_project_dir()
        if from_project:
            return from_project
        return _detect_instance(self._base)

    def _instance_from_project_dir(self) -> str | None:
        """Registry row whose path IS the current project dir, or None."""
        import json as _json
        project = os.environ.get("CLAUDE_PROJECT_DIR")
        if not project:
            return None
        reg = self.registry_path
        if not reg.is_file():
            return None
        try:
            data = _json.loads(reg.read_text(encoding="utf-8"))
            target = Path(project).resolve()
        except (OSError, ValueError):
            return None
        # Collect ALL matches, never `return` on the first. Duplicate registry
        # PATHS are the sibling of the duplicate-NAME hazard guarded in
        # _state_root, and this site had only the name half. Measured with two
        # rows sharing one path: resolved_instance=alpha, ambiguity_reported=no --
        # an unattended server binds to whichever row is listed first and reads
        # that project's canonical data. Refusing is the only safe answer; picking
        # is what this whole contract exists to stop.
        matches = []
        for entry in data.get("instances", []):
            try:
                if Path(entry.get("path", "")).resolve() == target:
                    matches.append(entry.get("name"))
            except (OSError, ValueError):
                continue
        if len(matches) > 1:
            raise PathContractError(
                f"{project} is claimed by {len(matches)} registry rows "
                f"({', '.join(sorted(str(m) for m in matches))}). Refusing to let "
                f"the first row win. Remove the duplicate path from the registry.",
                kind="duplicate-path")
        return matches[0] if matches else None

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
    def _state_root(self) -> Path:
        """The instance's OWN tree that owns canonical/ and my-project/.

        THE DEFECT THIS FIXES. These two properties used to return
        `{base}/instances/{name}/...` -- plugin DATA, which holds no repo content.
        So kipi_canonical_digest read an empty directory and returned
        all-files-not-found on every instance, and agents fell back to reading raw
        canonical (40-60K tokens), where one instance has three diverged copies.

        Registry is the authority, keyed by instance name. Formula per
        prd-single-runtime-state-authority: `instance_q_dir` when set, else
        `subtree_prefix`, else q-system.

        FAILS CLOSED. An unmapped instance RAISES rather than returning a path to
        nothing: an empty directory reads downstream as "no data" when the truth is
        "wrong path", and that misreading is the whole reason this contract exists.

        NOT `<path>/<subtree_prefix>/q-system`. A literal reading of the contract
        sentence produces q-system/q-system, and those nested shadow trees were
        deleted fleet-wide on 2026-07-01.
        """
        import json as _json
        reg = self.registry_path
        if not reg.is_file():
            raise PathContractError(
                f"no instance registry at {reg}; cannot resolve a state root for "
                f"{self.instance!r} without guessing", kind="no-registry")
        try:
            data = _json.loads(reg.read_text(encoding="utf-8"))
        except Exception as exc:
            raise PathContractError(f"registry {reg} is unreadable: {exc}", kind="unreadable")

        matches = [e for e in data.get("instances", [])
                   if e.get("name") == self.instance]
        if len(matches) > 1:
            raise PathContractError(
                f"{self.instance!r} appears {len(matches)} times in {reg}. Refusing "
                f"to let the first row silently win.", kind="duplicate-name")
        if matches:
            entry = matches[0]
            sub = (entry.get("instance_q_dir")
                   or entry.get("subtree_prefix")
                   or "q-system")
            root = Path(entry.get("path", "")) / sub
            # A REGISTERED row is not proof the tree is there. Measured across the
            # live registry: 4 of 25 instances (registry rows whose q-system/ holds
            # no canonical/) resolved to a directory that does not exist and were
            # handed back as authoritative. Returning a path to nothing is the exact
            # failure this contract exists to remove -- downstream it reads as "no
            # data" when the truth is "wrong path". Same rule evidence_ledger's
            # instance_root already applies.
            if not (root / "canonical").is_dir():
                raise PathContractError(
                    f"{self.instance!r} resolves to {root}, which has no canonical/ "
                    f"subdirectory. There is no canonical tree here; refusing to "
                    f"return a path to nothing. Fix the registry row or create the "
                    f"tree.", kind="no-canonical")
            return root

        skel = data.get("skeleton") or {}
        if isinstance(skel, dict) and skel.get("path"):
            try:
                if Path(skel["path"]).resolve() == Path(self.repo_dir).resolve():
                    return Path(skel["path"]) / "q-system"
            except OSError:
                pass

        raise PathContractError(
            f"{self.instance!r} is not a registered instance in {reg}. Refusing to "
            f"resolve canonical/ or my-project/ by guessing.", kind="unregistered")

    @property
    def canonical_dir(self) -> Path:
        return self._state_root / "canonical"

    @property
    def marketing_config_dir(self) -> Path:
        return self._instance_dir / "marketing"

    @property
    def my_project_dir(self) -> Path:
        return self._state_root / "my-project"

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
        """Where the fleet registry actually is.

        SCAR (2026-08-22): this returned `{base}/instance-registry.json`
        unconditionally, and in the DEPLOYED server `{base}` is KIPI_PLUGIN_DATA
        (see plugins/kipi-core/.mcp.json) -- i.e. ~/.kipi-system, which holds no
        registry and never has. Once canonical_dir became registry-derived, the
        resolver therefore fail-closed on every live MCP call:

            PathContractError: no instance registry at
            ~/.kipi-system/instance-registry.json

        Failing closed on an input that can never exist is still a dead tool. The
        repoint was proved by hand-feeding base_dir, which is a sound UNIT proof of
        the resolver and says nothing about the configuration the server runs under.

        Resolution order, first hit wins:
          0. base_dir was passed explicitly -> use it, no search. Keeps every test
             hermetic and stops a fixture from reaching the real fleet registry.
          1. $KIPI_REGISTRY -- explicit operator override.
          2. {base}/instance-registry.json when it really exists.
          3. walk UP from repo_dir. The plugin runs from the marketplace clone
             (CLAUDE_PLUGIN_ROOT -> .../marketplaces/kipi/plugins/kipi-core) and that
             clone is a checkout of this repo, which TRACKS instance-registry.json at
             its root. Verified present. This is also the dev-checkout answer, so one
             rule covers both without hardcoding a path.
          4. $KIPI_FLEET_ROOT (default ~/projects), the convention
             verify-alert-wiring.sh:16 already uses.
        """
        if self._base_explicit:
            return self._base / "instance-registry.json"

        override = os.environ.get("KIPI_REGISTRY")
        if override:
            return Path(override)

        default = self._base / "instance-registry.json"
        if default.is_file():
            return default

        repo = Path(self.repo_dir)
        for d in (repo, *repo.parents):
            cand = d / "instance-registry.json"
            if cand.is_file():
                return cand

        fleet = Path(os.environ.get("KIPI_FLEET_ROOT") or Path.home() / "projects")
        cand = fleet / APP_NAME / "instance-registry.json"
        if cand.is_file():
            return cand

        # Nothing found: return the documented default so the refusal names a
        # stable path rather than whichever candidate was checked last.
        return default

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
            self.marketing_config_dir,
            self.marketing_config_dir / "assets",
            self.memory_dir,
            self.memory_dir / "working",
            self.memory_dir / "weekly",
            self.memory_dir / "monthly",
            self.output_dir,
            self.output_dir / "drafts",
            self.bus_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)
