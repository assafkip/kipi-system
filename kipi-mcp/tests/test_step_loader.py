import pytest

from kipi_mcp.step_loader import StepLoader


@pytest.fixture
def loader(tmp_path):
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir()
    commands_file = tmp_path / "commands.md"
    commands_file.write_text("")
    return StepLoader(steps_dir, commands_file), steps_dir, commands_file


def test_load_from_file(loader):
    sl, steps_dir, _ = loader
    (steps_dir / "step-5-85.md").write_text("Do the thing for 5.85")
    assert sl.load("5.85") == "Do the thing for 5.85"


def test_load_from_file_simple_id(loader):
    sl, steps_dir, _ = loader
    (steps_dir / "step-4.md").write_text("Step 4 content")
    assert sl.load("4") == "Step 4 content"


def test_load_fallback_to_commands(loader):
    sl, _, commands_file = loader
    commands_file.write_text("**Step 4: Something**\nContent here\n---\nOther stuff")
    result = sl.load("4")
    assert "Step 4: Something" in result
    assert "Content here" in result
    assert "---" not in result


def test_load_not_found(loader):
    sl, _, _ = loader
    result = sl.load("99")
    assert "not found" in result
    assert "99" in result


def test_list_available(loader):
    sl, steps_dir, _ = loader
    (steps_dir / "step-3.md").write_text("")
    (steps_dir / "step-5-85.md").write_text("")
    (steps_dir / "step-5-9.md").write_text("")
    ids = sl.list_available()
    assert sorted(ids) == ["3", "5.85", "5.9"]


def test_load_from_commands_multiline(loader):
    sl, _, commands_file = loader
    content = (
        "**Step 4: Setup**\n"
        "Line 1\n"
        "Line 2\n"
        "Line 3\n"
        "**Step 5 next**\n"
        "Should not appear"
    )
    commands_file.write_text(content)
    result = sl.load("4")
    assert "Line 1" in result
    assert "Line 2" in result
    assert "Line 3" in result
    assert "Should not appear" not in result


def test_load_from_commands_max_lines(loader):
    sl, _, commands_file = loader
    lines = ["**Step 4: Big step**"] + [f"Line {i}" for i in range(100)]
    commands_file.write_text("\n".join(lines))
    result = sl.load("4")
    result_lines = result.splitlines()
    assert len(result_lines) == 80
    assert "Line 0" in result
    assert "Line 78" in result
    assert "Line 79" not in result
