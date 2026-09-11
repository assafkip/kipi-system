from pathlib import Path

import pytest

from kipi_mcp.paths import (
    APP_NAME,
    KipiPaths,
    PathContractError,
    _detect_instance,
    _slugify,
    generate_instance_name,
)


def test_default_resolution():
    paths = KipiPaths()
    expected_base = Path.home() / f".{APP_NAME}"
    assert paths._base == expected_base
    assert "instances" in str(paths.config_dir)


def test_slugify():
    assert _slugify("EQbit") == "eqbit"
    assert _slugify("Some Really Long Company Name Inc") == "some-really-long-com"
    assert _slugify("hello world!!!") == "hello-world"
    assert _slugify("  --spaces-- ") == "spaces"


def test_generate_instance_name_format():
    name = generate_instance_name("EQbit")
    assert name.startswith("eqbit-")
    parts = name.split("-")
    assert len(parts) >= 2
    suffix = parts[-1]
    assert any(c.isdigit() for c in suffix)
    assert any(c.isalpha() for c in suffix)


def test_generate_instance_name_avoids_existing():
    existing = set()
    names = set()
    for _ in range(10):
        name = generate_instance_name("test", existing)
        assert name not in existing
        existing.add(name)
        names.add(name)
    assert len(names) == 10


def test_constructor_overrides(tmp_path):
    base = tmp_path / "base"
    repo = tmp_path / "repo"
    paths = KipiPaths(base_dir=base, repo_dir=repo, instance="test")
    inst = base / "instances" / "test"
    assert paths.config_dir == inst
    assert paths.data_dir == inst
    assert paths.state_dir == inst
    assert paths.repo_dir == repo


def test_env_var_plugin_data(monkeypatch, tmp_path):
    monkeypatch.setenv("KIPI_PLUGIN_DATA", str(tmp_path / "pd"))
    monkeypatch.setenv("KIPI_PLUGIN_ROOT", str(tmp_path / "r"))
    monkeypatch.setenv("KIPI_INSTANCE", "myinst")
    paths = KipiPaths()
    inst = tmp_path / "pd" / "instances" / "myinst"
    assert paths.config_dir == inst
    assert paths.data_dir == inst
    assert paths.state_dir == inst
    assert paths.repo_dir == tmp_path / "r"


def test_all_dirs_collapse_to_one(tmp_path):
    """config_dir, data_dir, state_dir all resolve to the same path."""
    paths = KipiPaths(base_dir=tmp_path, instance="proj")
    assert paths.config_dir == paths.data_dir == paths.state_dir
    assert paths.config_dir == tmp_path / "instances" / "proj"


def test_instance_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("KIPI_INSTANCE", "my-project")
    paths = KipiPaths(base_dir=tmp_path / "base")
    assert paths.instance == "my-project"


def test_instance_from_active_file(monkeypatch, tmp_path):
    monkeypatch.delenv("KIPI_INSTANCE", raising=False)
    base = tmp_path / "base"
    base.mkdir()
    (base / "active-instance").write_text("ktlyst\n")
    paths = KipiPaths(base_dir=base)
    assert paths.instance == "ktlyst"


def test_instance_falls_back_to_default(monkeypatch, tmp_path):
    monkeypatch.delenv("KIPI_INSTANCE", raising=False)
    paths = KipiPaths(base_dir=tmp_path / "base")
    assert paths.instance == "default"


def test_global_dir(tmp_path):
    paths = KipiPaths(base_dir=tmp_path, instance="test")
    assert paths.global_dir == tmp_path / "global"
    assert paths.voice_dir == tmp_path / "global" / "voice"
    assert paths.audhd_dir == tmp_path / "global" / "audhd"


def test_instance_subdirectories(tmp_path):
    paths = KipiPaths(base_dir=tmp_path, instance="proj")
    inst = tmp_path / "instances" / "proj"
    # canonical_dir and my_project_dir are DELIBERATELY absent from this list now.
    # They are repo-derived (see _state_root) because plugin-data held no content,
    # which is what made kipi_canonical_digest return all-files-not-found. The rest
    # of the table is genuinely tool-owned state and still lives under plugin data.
    assert paths.marketing_config_dir == inst / "marketing"
    assert paths.memory_dir == inst / "memory"
    assert paths.output_dir == inst / "output"
    assert paths.bus_dir == inst / "bus"
    assert paths.metrics_db == inst / "metrics.db"
    assert paths.founder_profile == inst / "founder-profile.md"
    assert paths.enabled_integrations == inst / "enabled-integrations.md"


def test_repo_subdirectories(tmp_path):
    paths = KipiPaths(repo_dir=tmp_path)
    assert paths.q_system_dir == tmp_path / "q-system"
    assert paths.agents_dir == tmp_path / "q-system" / "agent-pipeline" / "agents"
    assert paths.templates_dir == tmp_path / "q-system" / "agent-pipeline" / "templates"
    assert paths.schedule_template == tmp_path / "q-system" / "marketing" / "templates" / "schedule-template.html"
    assert paths.methodology_dir == tmp_path / "q-system" / "methodology"


def test_registry_path_under_base(tmp_path):
    paths = KipiPaths(base_dir=tmp_path, instance="test")
    assert paths.registry_path == tmp_path / "instance-registry.json"


def test_ensure_dirs(tmp_path):
    paths = KipiPaths(base_dir=tmp_path, instance="test")
    paths.ensure_dirs()

    expected = [
        paths.global_dir,
        paths.voice_dir,
        paths.audhd_dir,
        paths.config_dir,
        paths.marketing_config_dir,
        paths.marketing_config_dir / "assets",
        paths.memory_dir,
        paths.memory_dir / "working",
        paths.memory_dir / "weekly",
        paths.memory_dir / "monthly",
        paths.output_dir,
        paths.output_dir / "drafts",
        paths.bus_dir,
    ]
    for d in expected:
        assert d.is_dir(), f"{d} was not created"

    # And the two repo-owned dirs must NOT be conjured. They are tracked git
    # content; ensure_dirs() with an unset repo_dir used to create them inside the
    # real plugin directory. `instance="test"` is unregistered, so asking for the
    # path at all is the fail-closed refusal -- which is itself the assertion.
    with pytest.raises(PathContractError):
        _ = paths.canonical_dir


# --------------------------------------------------------------- path contract (srsa)
# These pin the defect that made kipi_canonical_digest return valid:false in every
# instance: canonical_dir and my_project_dir resolved to plugin-data
# (~/.kipi-system/instances/<name>/), which holds zero files, instead of to the
# instance's own tree. The digest exists to save 40-60K tokens against reading full
# canonical; returning nothing sent agents back to raw files, where consulting has THREE
# diverged copies. Written to fail first -- see the issue's reproducer-first acceptance.


def test_canonical_dir_resolves_instance_domain_dir(registry_with_domain_dir, monkeypatch):
    registry_path, repo = registry_with_domain_dir
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    paths = KipiPaths(base_dir=registry_path.parent, instance="domain-instance")
    assert paths.canonical_dir == repo / "q-domain" / "canonical"


def test_my_project_dir_resolves_instance_domain_dir(registry_with_domain_dir, monkeypatch):
    """Part 5. Same defect, same file, different property.

    morning_init.py:192 reads current-state.md from my_project_dir, so fixing only
    canonical leaves current_state empty. Asserted directly and NOT via digest["valid"]:
    _validate_digest needs 5 of 7 checks and 6 stay reachable without works_today, so
    valid can go true with this half still broken.
    """
    registry_path, repo = registry_with_domain_dir
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    paths = KipiPaths(base_dir=registry_path.parent, instance="domain-instance")
    assert paths.my_project_dir == repo / "q-domain" / "my-project"


def test_null_domain_dir_falls_back_to_subtree_prefix(tmp_registry_with_instances, tmp_path, monkeypatch):
    """instance_q_dir null means the state root IS <path>/<subtree_prefix>.

    NOT <path>/<subtree_prefix>/q-system. A literal reading of the contract sentence
    produces q-system/q-system, and those nested shadow trees were removed fleet-wide on
    2026-07-01; re-deriving one here would resurrect the thing that flattening deleted.
    """
    repo = tmp_path / "test-instance"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    paths = KipiPaths(base_dir=tmp_registry_with_instances.parent, instance="test-instance")
    assert paths.canonical_dir == repo / "q-system" / "canonical"


def test_duplicate_registry_paths_fail_closed(tmp_path, monkeypatch):
    """Codex PR #240 round 3, major. The NAME axis was guarded in _state_root and
    the PATH axis was not, so two rows sharing one path let the first silently win:

        resolved_instance=alpha, ambiguity_reported=no

    An unattended server then binds to whichever row is listed first and reads that
    project's canonical data. Both axes now refuse.
    """
    import json
    repo = tmp_path / "repo"
    (repo / "q-system" / "canonical").mkdir(parents=True)
    base = tmp_path / "base"
    base.mkdir()
    (base / "instance-registry.json").write_text(json.dumps({
        "skeleton": {"path": str(tmp_path / "nope")},
        "instances": [
            {"name": "alpha", "path": str(repo), "subtree_prefix": "q-system",
             "instance_q_dir": None},
            {"name": "beta", "path": str(repo), "subtree_prefix": "q-system",
             "instance_q_dir": None},
        ],
    }), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.setenv("KIPI_PLUGIN_DATA", str(base))
    monkeypatch.delenv("KIPI_INSTANCE", raising=False)

    with pytest.raises(PathContractError) as exc:
        KipiPaths()
    assert exc.value.kind == "duplicate-path"


def test_unregistered_repo_fails_closed(tmp_path, tmp_registry_with_instances, monkeypatch):
    """An unmapped repo must RAISE, never silently pick a default.

    The whole defect class is a resolver that guesses and returns an empty directory that
    reads as 'no data' rather than 'wrong path'.
    """
    stranger = tmp_path / "not-in-registry"
    stranger.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(stranger))
    paths = KipiPaths(base_dir=tmp_registry_with_instances.parent, instance="nope")
    with pytest.raises(PathContractError):
        _ = paths.canonical_dir


def test_ensure_dirs_never_creates_repo_owned_dirs(registry_with_domain_dir, monkeypatch):
    """ensure_dirs() must not mkdir canonical/ or my-project/ once they are repo-derived.

    They are tracked git content, not tool-created state. Before this, ensure_dirs() with
    an unset repo_dir would happily create them inside the real plugin directory.
    """
    registry_path, repo = registry_with_domain_dir
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    paths = KipiPaths(base_dir=registry_path.parent, instance="domain-instance")

    # The fixture pre-creates both, so remove them: the only thing that can bring
    # them back inside this test is ensure_dirs itself.
    expected_canon = repo / "q-domain" / "canonical"
    expected_proj = repo / "q-domain" / "my-project"
    for d in (expected_canon, expected_proj):
        if d.is_dir():
            d.rmdir()

    paths.ensure_dirs()

    # Assert the RESOLVED properties. The first draft asserted that
    # `repo/q-domain/should-not-appear` was absent -- nothing anywhere creates that
    # name, so it held identically against fixed and unfixed code. Measured
    # 2026-08-22: it was the one new case that PASSED on the reproducer run, which
    # is how a vacuous test hides. A test that cannot fail is not a test.
    # LITERAL paths, not the properties: with the tree deleted the property now
    # refuses (correctly), and a refusal is not what this case is testing.
    assert not expected_canon.exists(), f"ensure_dirs created {expected_canon}"
    assert not expected_proj.exists(), f"ensure_dirs created {expected_proj}"
    assert paths.bus_dir.is_dir(), "ensure_dirs must still create tool-owned state"
