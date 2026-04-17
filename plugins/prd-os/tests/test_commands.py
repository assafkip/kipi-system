"""Structural checks on the slash-command markdown files.

The command files are prompt glue; their behavior is covered by the
underlying script tests. These checks just catch typos and missing frontmatter
so a stale or renamed script reference is obvious without running the
plugin live.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
COMMANDS_DIR = PLUGIN_ROOT / "commands"
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"

EXPECTED = {
    "prd-start.md": ["prd_runner.py"],
    "prd-review.md": ["prd_runner.py", "findings_writer.py"],
    "prd-triage.md": ["prd_runner.py", "findings_writer.py"],
    "prd-approve.md": ["prd_runner.py"],
    "prd-split.md": ["prd_split.py"],
}

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_command_file_exists(name):
    assert (COMMANDS_DIR / name).is_file(), f"missing command file: {name}"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_command_has_frontmatter_with_description(name):
    text = (COMMANDS_DIR / name).read_text()
    m = FRONTMATTER_RE.match(text)
    assert m, f"{name}: missing YAML frontmatter"
    fm = m.group(1)
    assert re.search(r"^description:\s*\S", fm, re.MULTILINE), (
        f"{name}: frontmatter missing description"
    )


@pytest.mark.parametrize("name,scripts", sorted(EXPECTED.items()))
def test_command_references_existing_scripts(name, scripts):
    text = (COMMANDS_DIR / name).read_text()
    for script in scripts:
        assert script in text, f"{name}: expected reference to {script}"
        assert (SCRIPTS_DIR / script).is_file(), (
            f"{name}: references {script} but it does not exist"
        )


def test_no_unexpected_command_files():
    actual = {p.name for p in COMMANDS_DIR.glob("*.md")}
    extra = actual - set(EXPECTED)
    assert not extra, f"unexpected command files present: {sorted(extra)}"
