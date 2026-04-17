"""Unit tests for the plugin's config resolution module.

Covers:
  - CLAUDE_PROJECT_DIR env var is honored for repo root discovery.
  - Walk-up discovery finds `.prd-os/config.json` before `.git`.
  - strict=True raises ConfigMissingError when the config file is absent.
  - strict=False returns defaults when the config file is absent.
  - Partial configs inherit defaults for missing keys.
  - Path overrides resolve relative to the repo root.
  - Absolute paths in config are preserved as-is.
  - Schema version gating: supported passes, unsupported raises.
  - Invalid JSON raises ConfigError.
  - Invalid top-level (non-object) raises ConfigError.
  - Invalid control_plane_files raises ConfigError.
  - default_config_payload matches the documented default structure.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def test_discover_repo_root_uses_env(import_config, fake_repo, monkeypatch):
    # fake_repo already sets CLAUDE_PROJECT_DIR to the ephemeral repo.
    found = import_config.discover_repo_root()
    assert found == fake_repo.resolve()


def test_discover_repo_root_walks_up_to_config(import_config, tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    repo = tmp_path / "project"
    (repo / ".prd-os").mkdir(parents=True)
    (repo / ".prd-os" / "config.json").write_text("{}")
    nested = repo / "sub" / "nest"
    nested.mkdir(parents=True)
    found = import_config.discover_repo_root(start=nested)
    assert found == repo.resolve()


def test_discover_repo_root_walks_up_to_git(import_config, tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    repo = tmp_path / "project"
    (repo / ".git").mkdir(parents=True)
    nested = repo / "deep" / "nest"
    nested.mkdir(parents=True)
    found = import_config.discover_repo_root(start=nested)
    assert found == repo.resolve()


def test_discover_repo_root_raises_when_no_marker(import_config, tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    isolated = tmp_path / "island"
    isolated.mkdir()
    # Walk-up from an isolated dir with no .git and no .prd-os should hit
    # filesystem root without finding a marker. On most dev machines, / has
    # neither, so this raises.
    with pytest.raises(import_config.RepoRootNotFoundError):
        import_config.discover_repo_root(start=isolated)


def test_load_strict_raises_when_missing(import_config, fake_repo):
    with pytest.raises(import_config.ConfigMissingError):
        import_config.load(fake_repo, strict=True)


def test_load_non_strict_returns_defaults(import_config, fake_repo):
    cfg = import_config.load(fake_repo, strict=False)
    assert cfg.source_path is None
    assert cfg.schema_version == import_config.CURRENT_SCHEMA_VERSION
    assert cfg.issues_dir == (fake_repo / ".prd-os" / "issues").resolve()
    assert cfg.state_dir == (fake_repo / ".claude" / "state").resolve()
    assert cfg.codex_base_ref == "origin/main"
    assert cfg.codex_review_mode == "background"
    assert cfg.control_plane_files == ()


def test_partial_config_inherits_defaults(import_config, fake_repo, write_config):
    write_config(fake_repo, {
        "config_schema_version": 1,
        "issues_dir": "custom/issues",
    })
    cfg = import_config.load(fake_repo, strict=True)
    assert cfg.issues_dir == (fake_repo / "custom" / "issues").resolve()
    # Defaults preserved for unspecified keys.
    assert cfg.prds_dir == (fake_repo / ".prd-os" / "prds").resolve()
    assert cfg.state_dir == (fake_repo / ".claude" / "state").resolve()


def test_absolute_paths_in_config_preserved(import_config, fake_repo, write_config, tmp_path):
    external = tmp_path / "external-issues"
    external.mkdir()
    write_config(fake_repo, {
        "config_schema_version": 1,
        "issues_dir": str(external),
    })
    cfg = import_config.load(fake_repo, strict=True)
    assert cfg.issues_dir == external.resolve()


def test_schema_version_unsupported_raises(import_config, fake_repo, write_config):
    write_config(fake_repo, {"config_schema_version": 99})
    with pytest.raises(import_config.ConfigVersionError):
        import_config.load(fake_repo, strict=True)


def test_invalid_json_raises(import_config, fake_repo):
    (fake_repo / ".prd-os").mkdir()
    (fake_repo / ".prd-os" / "config.json").write_text("{not valid json")
    with pytest.raises(import_config.ConfigError):
        import_config.load(fake_repo, strict=True)


def test_non_object_top_level_raises(import_config, fake_repo):
    (fake_repo / ".prd-os").mkdir()
    (fake_repo / ".prd-os" / "config.json").write_text("[]")
    with pytest.raises(import_config.ConfigError):
        import_config.load(fake_repo, strict=True)


def test_control_plane_files_must_be_list_of_strings(import_config, fake_repo, write_config):
    write_config(fake_repo, {
        "config_schema_version": 1,
        "control_plane_files": [1, 2, 3],
    })
    with pytest.raises(import_config.ConfigError):
        import_config.load(fake_repo, strict=True)


def test_codex_must_be_object(import_config, fake_repo, write_config):
    write_config(fake_repo, {
        "config_schema_version": 1,
        "codex": "origin/main",
    })
    with pytest.raises(import_config.ConfigError):
        import_config.load(fake_repo, strict=True)


@pytest.mark.parametrize("bad_codex", [None, "origin/main", ["x"], 42, True])
def test_explicit_non_dict_codex_raises(
    import_config, fake_repo, write_config, bad_codex
):
    """An explicit `codex` key with a non-dict value (including null) must
    raise ConfigError, not silently fall back to defaults. Codex stop-review
    flagged `codex: null` as the bypass vector: `data.get("codex") or {}`
    collapsed None to {} before the type check."""
    write_config(fake_repo, {"config_schema_version": 1, "codex": bad_codex})
    with pytest.raises(import_config.ConfigError):
        import_config.load(fake_repo, strict=True)


def test_missing_codex_key_uses_defaults(import_config, fake_repo, write_config):
    """Omitting `codex` entirely is valid — defaults apply. Distinguishes
    absent (fine) from explicit-null (error)."""
    write_config(fake_repo, {"config_schema_version": 1})
    cfg = import_config.load(fake_repo, strict=True)
    assert cfg.codex_base_ref == "origin/main"
    assert cfg.codex_review_mode == "background"


def test_default_config_payload_has_expected_shape(import_config):
    payload = import_config.default_config_payload()
    assert payload["config_schema_version"] == import_config.CURRENT_SCHEMA_VERSION
    for key in ("prds_dir", "issues_dir", "findings_dir", "state_dir", "codex", "control_plane_files"):
        assert key in payload
    assert isinstance(payload["codex"], dict)
    assert payload["codex"].keys() == {"base_ref", "review_mode"}


@pytest.mark.parametrize(
    "key",
    ["prds_dir", "issues_dir", "findings_dir", "state_dir"],
)
@pytest.mark.parametrize(
    "bad_value",
    [123, None, ["a", "b"], {"nested": "thing"}, True],
)
def test_non_string_path_values_raise(
    import_config, fake_repo, write_config, key, bad_value
):
    """Malformed path values (int, null, list, object, bool) must raise
    ConfigError, never crash with TypeError inside Path(). Codex stop-review
    flagged this as a runner-crash vector."""
    write_config(fake_repo, {"config_schema_version": 1, key: bad_value})
    with pytest.raises(import_config.ConfigError):
        import_config.load(fake_repo, strict=True)


@pytest.mark.parametrize("key", ["base_ref", "review_mode"])
@pytest.mark.parametrize("bad_value", [42, None, ["x"], {"y": 1}, True])
def test_non_string_codex_values_raise(
    import_config, fake_repo, write_config, key, bad_value
):
    """Malformed codex string fields must raise ConfigError, not pass through
    as wrong-typed values into the runner/hook layer."""
    write_config(
        fake_repo,
        {"config_schema_version": 1, "codex": {key: bad_value}},
    )
    with pytest.raises(import_config.ConfigError):
        import_config.load(fake_repo, strict=True)


def test_ktlyst_compatibility_config_loads(import_config, fake_repo, write_config):
    """ktlyst migration: plugin config can point at the existing ktlyst paths
    so the plugin runner operates against live q-ktlyst issues without moves."""
    write_config(fake_repo, {
        "config_schema_version": 1,
        "issues_dir": "q-ktlyst/.q-system/issues",
        "state_dir": ".claude/state",
    })
    cfg = import_config.load(fake_repo, strict=True)
    assert cfg.issues_dir == (fake_repo / "q-ktlyst" / ".q-system" / "issues").resolve()
    assert cfg.state_dir == (fake_repo / ".claude" / "state").resolve()
    assert cfg.active_issue_state_path == (
        fake_repo / ".claude" / "state" / "active-issue.json"
    ).resolve()
