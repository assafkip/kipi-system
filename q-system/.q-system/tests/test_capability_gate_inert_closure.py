"""The inert-engine check's wired-closure must cross the plugin boundary.

Reproducer for PR #294 (2026-09-02): CI reported reddit_read.py, lessons_recall.py
and notion_board.py as inert engines. All three had a real caller:
  - reddit_read.py   <- plugins/kipi-core/kipi-mcp/src/kipi_mcp/web_read.py (the MCP
                        tool registry, which the wiring-check rule names as wiring)
  - lessons_recall.py <- plugins/kipi-core/skills/improve/scripts/improve_ground.py,
                        itself referenced by that skill's SKILL.md
The check gathered its surface from skeleton globs only and ran the plugin
closure AFTER the skeleton closure, so a wired plugin engine could never wire a
skeleton engine, and the MCP server's source tree was not a surface at all.

The principle the check already states holds: an UNWIRED engine still cannot wire
its sibling (case 2 pins it), so this is not a loosening.
"""
import importlib.util
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[1] / "scripts" / "capability-gate.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("capgate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ENGINE = "import sys\n\ndef main():\n    return 0\n\nif __name__ == '__main__':\n    sys.exit(main())\n"


def _skeleton(root: Path) -> Path:
    eng = root / "q-system/.q-system/scripts/eng.py"
    eng.parent.mkdir(parents=True)
    eng.write_text(ENGINE)
    eng.chmod(0o755)
    return eng


def _run(gate, root):
    errors, notes = [], []
    gate.check_inert_engines(root, {"declared_inert": []}, errors, notes)
    return [e for e in errors if "inert-engine" in e]


def test_control_an_engine_with_no_caller_is_reported(gate, tmp_path):
    """The check can go red: nothing references eng.py."""
    _skeleton(tmp_path)
    assert any("eng.py" in e for e in _run(gate, tmp_path))


def test_a_wired_plugin_skill_script_wires_the_skeleton_engine_it_calls(gate, tmp_path):
    _skeleton(tmp_path)
    tool = tmp_path / "plugins/x/skills/s/scripts/tool.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("from pathlib import Path\n" + ENGINE.replace("return 0", "return Path('eng.py').exists()"))
    (tmp_path / "plugins/x/skills/s/SKILL.md").write_text("Run scripts/tool.py first.\n")
    assert _run(gate, tmp_path) == []


def test_an_unwired_plugin_script_cannot_wire_a_skeleton_engine(gate, tmp_path):
    """Same tree, but nothing references tool.py: two dead engines citing each
    other stay dead. The closure principle is unchanged."""
    _skeleton(tmp_path)
    tool = tmp_path / "plugins/x/skills/s/scripts/tool.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("from pathlib import Path\n" + ENGINE.replace("return 0", "return Path('eng.py').exists()"))
    (tmp_path / "plugins/x/skills/s/SKILL.md").write_text("This skill has no scripts.\n")
    assert any("eng.py" in e for e in _run(gate, tmp_path))


def test_the_mcp_server_source_tree_is_a_wiring_surface(gate, tmp_path):
    _skeleton(tmp_path)
    src = tmp_path / "plugins/x/kipi-mcp/src/kipi_mcp/web.py"
    src.parent.mkdir(parents=True)
    src.write_text("SCRIPT = 'q-system/.q-system/scripts/eng.py'\n")
    assert _run(gate, tmp_path) == []
