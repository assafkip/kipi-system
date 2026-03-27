from pathlib import Path

from platformdirs import user_config_path, user_data_path, user_state_path

from kipi_mcp.paths import KipiPaths, _detect_instance


def test_default_resolution():
    paths = KipiPaths()
    # Instance dirs are under instances/{name}/
    assert paths._config_base == user_config_path("kipi")
    assert paths._data_base == user_data_path("kipi")
    assert paths._state_base == user_state_path("kipi")
    assert "instances" in str(paths.config_dir)


def test_constructor_overrides(tmp_path):
    cfg = tmp_path / "cfg"
    dat = tmp_path / "dat"
    st = tmp_path / "st"
    repo = tmp_path / "repo"
    paths = KipiPaths(config_dir=cfg, data_dir=dat, state_dir=st, repo_dir=repo, instance="test")
    assert paths.config_dir == cfg / "instances" / "test"
    assert paths.data_dir == dat / "instances" / "test"
    assert paths.state_dir == st / "instances" / "test"
    assert paths.repo_dir == repo


def test_env_var_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("KIPI_CONFIG_DIR", str(tmp_path / "c"))
    monkeypatch.setenv("KIPI_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("KIPI_STATE_DIR", str(tmp_path / "s"))
    monkeypatch.setenv("KIPI_HOME", str(tmp_path / "r"))
    monkeypatch.setenv("KIPI_INSTANCE", "myinst")
    paths = KipiPaths()
    assert paths.config_dir == tmp_path / "c" / "instances" / "myinst"
    assert paths.data_dir == tmp_path / "d" / "instances" / "myinst"
    assert paths.state_dir == tmp_path / "s" / "instances" / "myinst"
    assert paths.repo_dir == tmp_path / "r"


def test_instance_from_file(tmp_path):
    repo = tmp_path / "my-cool-project"
    repo.mkdir()
    (repo / ".kipi-instance").write_text("cool-project\n")
    paths = KipiPaths(config_dir=tmp_path / "cfg", repo_dir=repo)
    assert paths.instance == "cool-project"


def test_instance_falls_back_to_dirname(tmp_path):
    repo = tmp_path / "my-repo-name"
    repo.mkdir()
    paths = KipiPaths(config_dir=tmp_path / "cfg", repo_dir=repo)
    assert paths.instance == "my-repo-name"


def test_global_dir(tmp_path):
    paths = KipiPaths(config_dir=tmp_path / "cfg", instance="test")
    assert paths.global_dir == tmp_path / "cfg" / "global"
    assert paths.voice_dir == tmp_path / "cfg" / "global" / "voice"
    assert paths.audhd_dir == tmp_path / "cfg" / "global" / "audhd"


def test_config_subdirectories(tmp_path):
    paths = KipiPaths(config_dir=tmp_path, instance="proj")
    assert paths.canonical_dir == tmp_path / "instances" / "proj" / "canonical"
    assert paths.marketing_config_dir == tmp_path / "instances" / "proj" / "marketing"


def test_data_subdirectories(tmp_path):
    paths = KipiPaths(data_dir=tmp_path, instance="proj")
    assert paths.my_project_dir == tmp_path / "instances" / "proj" / "my-project"
    assert paths.memory_dir == tmp_path / "instances" / "proj" / "memory"


def test_state_subdirectories(tmp_path):
    paths = KipiPaths(state_dir=tmp_path, instance="proj")
    assert paths.output_dir == tmp_path / "instances" / "proj" / "output"
    assert paths.bus_dir == tmp_path / "instances" / "proj" / "bus"


def test_repo_subdirectories(tmp_path):
    paths = KipiPaths(repo_dir=tmp_path)
    assert paths.q_system_dir == tmp_path / "q-system"
    assert paths.agents_dir == tmp_path / "q-system" / ".q-system" / "agent-pipeline" / "agents"
    assert paths.steps_dir == tmp_path / "q-system" / ".q-system" / "steps"
    assert paths.commands_file == tmp_path / "q-system" / ".q-system" / "commands.md"
    assert paths.templates_dir == tmp_path / "q-system" / ".q-system" / "agent-pipeline" / "templates"
    assert paths.schedule_template == tmp_path / "q-system" / "marketing" / "templates" / "schedule-template.html"
    assert paths.methodology_dir == tmp_path / "q-system" / "methodology"
    assert paths.registry_path == tmp_path / "instance-registry.json"


def test_detect_legacy_layout_with_user_data(tmp_path):
    paths = KipiPaths(repo_dir=tmp_path)
    profile = tmp_path / "q-system" / "my-project" / "founder-profile.md"
    profile.parent.mkdir(parents=True)
    profile.write_text("name: Ike\nrole: founder\n")
    assert paths.detect_legacy_layout() is True


def test_detect_legacy_layout_with_template(tmp_path):
    paths = KipiPaths(repo_dir=tmp_path)
    profile = tmp_path / "q-system" / "my-project" / "founder-profile.md"
    profile.parent.mkdir(parents=True)
    profile.write_text("{{SETUP_NEEDED}}\nFill in your profile here.\n")
    assert paths.detect_legacy_layout() is False


def test_detect_legacy_layout_no_file(tmp_path):
    paths = KipiPaths(repo_dir=tmp_path)
    assert paths.detect_legacy_layout() is False


def test_ensure_dirs(tmp_path):
    paths = KipiPaths(
        config_dir=tmp_path / "cfg",
        data_dir=tmp_path / "dat",
        state_dir=tmp_path / "st",
        instance="test",
    )
    paths.ensure_dirs()

    expected = [
        paths.global_dir,
        paths.voice_dir,
        paths.audhd_dir,
        paths.config_dir,
        paths.canonical_dir,
        paths.marketing_config_dir,
        paths.marketing_config_dir / "assets",
        paths.data_dir,
        paths.my_project_dir,
        paths.memory_dir,
        paths.memory_dir / "working",
        paths.memory_dir / "weekly",
        paths.memory_dir / "monthly",
        paths.state_dir,
        paths.output_dir,
        paths.output_dir / "drafts",
        paths.bus_dir,
    ]
    for d in expected:
        assert d.is_dir(), f"{d} was not created"
