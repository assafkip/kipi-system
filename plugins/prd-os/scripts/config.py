"""Config resolution for the prd-os plugin.

Reads `.prd-os/config.json` from the host repo and exposes typed path
accessors for the runner scripts and hooks. Falls back to documented
defaults for missing keys so partial configs stay valid.

Repo root discovery order:
  1. CLAUDE_PROJECT_DIR environment variable (set by Claude Code).
  2. Walk up from CWD looking for `.prd-os/config.json`, then `.git`.
  3. Raise RepoRootNotFoundError.

Two load modes:
  - strict=True (runners, hooks): `.prd-os/config.json` must exist. Missing
    keys get defaults; missing file is a hard error.
  - strict=False (init / bootstrap): missing file means use all defaults.
    `/prd-os-init` uses this to decide what to write.

Config is versioned via `config_schema_version`. Unsupported versions raise
ConfigVersionError. The plugin's CHANGELOG documents each schema bump and
whether migration is automatic or manual.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


CONFIG_RELPATH = ".prd-os/config.json"
CURRENT_SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = (1,)

DEFAULTS = {
    "prds_dir": ".prd-os/prds",
    "issues_dir": ".prd-os/issues",
    "findings_dir": ".prd-os/findings",
    "state_dir": ".claude/state",
    "codex": {
        "base_ref": "origin/main",
        "review_mode": "background",
    },
    "control_plane_files": [],
}


class ConfigError(Exception):
    """Base class for config resolution errors."""


class ConfigMissingError(ConfigError):
    """Raised in strict mode when .prd-os/config.json is missing."""


class ConfigVersionError(ConfigError):
    """Raised when config_schema_version is unsupported."""


class RepoRootNotFoundError(ConfigError):
    """Raised when repo root cannot be discovered."""


@dataclass(frozen=True)
class Config:
    repo_root: Path
    prds_dir: Path
    issues_dir: Path
    findings_dir: Path
    state_dir: Path
    codex_base_ref: str
    codex_review_mode: str
    control_plane_files: tuple[str, ...]
    schema_version: int
    source_path: Optional[Path]  # None when defaults-only (strict=False)

    @property
    def active_issue_state_path(self) -> Path:
        return self.state_dir / "active-issue.json"

    @property
    def active_prd_state_path(self) -> Path:
        return self.state_dir / "active-prd.json"


def discover_repo_root(start: Optional[Path] = None) -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        candidate = Path(env).resolve()
        if candidate.is_dir():
            return candidate
    cwd = (start or Path.cwd()).resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / CONFIG_RELPATH).is_file():
            return candidate
        if (candidate / ".git").exists():
            return candidate
    raise RepoRootNotFoundError(
        "cannot locate repo root. Set CLAUDE_PROJECT_DIR or run inside a "
        "repo that contains .prd-os/config.json or .git."
    )


def load(repo_root: Optional[Path] = None, *, strict: bool = True) -> Config:
    root = (repo_root.resolve() if repo_root else discover_repo_root())
    config_path = root / CONFIG_RELPATH
    if not config_path.is_file():
        if strict:
            raise ConfigMissingError(
                f"{CONFIG_RELPATH} not found under {root}. "
                "Run /prd-os-init in this repo first."
            )
        data: dict = {}
        source: Optional[Path] = None
    else:
        try:
            data = json.loads(config_path.read_text())
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{config_path}: invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"{config_path}: top-level must be a JSON object")
        source = config_path

    version = data.get("config_schema_version", CURRENT_SCHEMA_VERSION)
    if not isinstance(version, int) or version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ConfigVersionError(
            f"unsupported config_schema_version: {version!r}. "
            f"Supported: {SUPPORTED_SCHEMA_VERSIONS}"
        )

    if "codex" in data:
        codex_raw = data["codex"]
        if not isinstance(codex_raw, dict):
            raise ConfigError("codex must be a JSON object")
    else:
        codex_raw = {}
    base_ref = _require_str(
        codex_raw, "base_ref", DEFAULTS["codex"]["base_ref"], where="codex.base_ref"
    )
    review_mode = _require_str(
        codex_raw, "review_mode", DEFAULTS["codex"]["review_mode"], where="codex.review_mode"
    )

    cpf = data.get("control_plane_files", DEFAULTS["control_plane_files"])
    if not isinstance(cpf, list) or not all(isinstance(x, str) for x in cpf):
        raise ConfigError("control_plane_files must be a list of strings")

    return Config(
        repo_root=root,
        prds_dir=_resolve(root, _require_str(data, "prds_dir", DEFAULTS["prds_dir"])),
        issues_dir=_resolve(root, _require_str(data, "issues_dir", DEFAULTS["issues_dir"])),
        findings_dir=_resolve(root, _require_str(data, "findings_dir", DEFAULTS["findings_dir"])),
        state_dir=_resolve(root, _require_str(data, "state_dir", DEFAULTS["state_dir"])),
        codex_base_ref=base_ref,
        codex_review_mode=review_mode,
        control_plane_files=tuple(cpf),
        schema_version=version,
        source_path=source,
    )


def _resolve(root: Path, rel_or_abs: str) -> Path:
    p = Path(rel_or_abs)
    if p.is_absolute():
        return p.resolve()
    return (root / p).resolve()


def _require_str(src: dict, key: str, default: str, where: Optional[str] = None) -> str:
    """Return src[key] when present and a string, else default.

    Raises ConfigError if the key is present but not a string. Explicit `null`
    counts as present for purposes of type-checking (JSON null => None != str),
    so `"prds_dir": null` is an error, not a silent fallback to default.
    """
    if key not in src:
        return default
    value = src[key]
    if not isinstance(value, str):
        label = where or key
        raise ConfigError(
            f"{label} must be a string, got {type(value).__name__}: {value!r}"
        )
    return value


def default_config_payload() -> dict:
    """Payload `/prd-os-init` writes to scaffold a new repo."""
    return {
        "config_schema_version": CURRENT_SCHEMA_VERSION,
        "prds_dir": DEFAULTS["prds_dir"],
        "issues_dir": DEFAULTS["issues_dir"],
        "findings_dir": DEFAULTS["findings_dir"],
        "state_dir": DEFAULTS["state_dir"],
        "codex": dict(DEFAULTS["codex"]),
        "control_plane_files": list(DEFAULTS["control_plane_files"]),
    }
