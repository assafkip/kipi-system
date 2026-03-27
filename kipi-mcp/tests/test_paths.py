from pathlib import Path

from kipi_mcp.paths import APP_NAME, KipiPaths, _detect_instance, _slugify, generate_instance_name


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


def test_env_var_kipi_home_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("KIPI_PLUGIN_ROOT", raising=False)
    monkeypatch.setenv("KIPI_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("KIPI_INSTANCE", "inst")
    paths = KipiPaths(base_dir=tmp_path)
    assert paths.repo_dir == tmp_path / "h"


def test_all_dirs_collapse_to_one(tmp_path):
    """config_dir, data_dir, state_dir all resolve to the same path."""
    paths = KipiPaths(base_dir=tmp_path, instance="proj")
    assert paths.config_dir == paths.data_dir == paths.state_dir
    assert paths.config_dir == tmp_path / "instances" / "proj"


def test_instance_from_file(tmp_path):
    repo = tmp_path / "my-cool-project"
    repo.mkdir()
    (repo / ".kipi-instance").write_text("cool-project\n")
    paths = KipiPaths(base_dir=tmp_path / "base", repo_dir=repo)
    assert paths.instance == "cool-project"


def test_instance_falls_back_to_dirname(tmp_path):
    repo = tmp_path / "my-repo-name"
    repo.mkdir()
    paths = KipiPaths(base_dir=tmp_path / "base", repo_dir=repo)
    assert paths.instance == "my-repo-name"


def test_global_dir(tmp_path):
    paths = KipiPaths(base_dir=tmp_path, instance="test")
    assert paths.global_dir == tmp_path / "global"
    assert paths.voice_dir == tmp_path / "global" / "voice"
    assert paths.audhd_dir == tmp_path / "global" / "audhd"


def test_instance_subdirectories(tmp_path):
    paths = KipiPaths(base_dir=tmp_path, instance="proj")
    inst = tmp_path / "instances" / "proj"
    assert paths.canonical_dir == inst / "canonical"
    assert paths.marketing_config_dir == inst / "marketing"
    assert paths.my_project_dir == inst / "my-project"
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
        paths.canonical_dir,
        paths.marketing_config_dir,
        paths.marketing_config_dir / "assets",
        paths.my_project_dir,
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
