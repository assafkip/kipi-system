"""Tests for improve-ground-gate.py (ASK-5804).

The founder ordered a hook, not a memory note, after #885 to #888 built a
parallel gate next to an existing switch. These pin the five behaviours the
ticket names plus the active-ticket source. Every case runs the hook as a
subprocess with a temp CLAUDE_PROJECT_DIR and an empty temp lessons corpus,
so no case reads or writes a live data path and the verdict comes only from
improve_ground's KNOWN_BUILT table and the docstring under test.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HOOK = REPO / "q-system/.q-system/scripts/improve-ground-gate.py"
GROUND = REPO / "plugins/kipi-core/skills/improve/scripts/improve_ground.py"
# A real, existing script's docstring, never an invented one: what a new
# duplicate of the morning-brief deadman would open with.
REAL_DOC = (REPO / "q-system/.q-system/scripts/morning-brief-deadman.py").read_text().split('"""')[1]
NEW_DOC = "Convert sqlite rows into iCalendar VEVENT blocks for a calendar export."


def _run(tmp_path, file_path, content, tool="Write", ground=GROUND, extra_env=None):
    corpus = tmp_path / "lessons"
    corpus.mkdir(exist_ok=True)
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path / "repo"),
           "KIPI_IMPROVE_GROUND": str(ground), "KIPI_LESSONS_CORPORA": str(corpus)}
    env.update(extra_env or {})
    (tmp_path / "repo").mkdir(exist_ok=True)
    payload = {"tool_name": tool, "tool_input": {"file_path": str(file_path), "content": content}}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=30)


def _script(doc):
    return f'#!/usr/bin/env python3\n"""{doc}"""\nimport sys\n'


def _target(tmp_path, rel="repo/plugins/kipi-core/scripts/new_thing.py"):
    return tmp_path / rel


def test_a_new_file_describing_something_built_is_blocked_naming_it(tmp_path):
    r = _run(tmp_path, _target(tmp_path), _script(REAL_DOC))
    assert r.returncode == 2 and "BLOCKED" in r.stderr, r.stderr
    assert "morning-brief" in r.stderr and "BLOCKED" in r.stderr


def test_a_new_file_for_something_new_passes(tmp_path):
    r = _run(tmp_path, _target(tmp_path), _script(NEW_DOC))
    assert r.returncode == 0, r.stderr
    assert "BLOCKED" not in r.stderr


def test_an_existing_path_or_an_edit_fast_exits(tmp_path):
    existing = _target(tmp_path)
    existing.parent.mkdir(parents=True)
    existing.write_text("x\n")
    assert _run(tmp_path, existing, _script(REAL_DOC)).returncode == 0
    r = _run(tmp_path, _target(tmp_path, "repo/plugins/kipi-core/scripts/other.py"), _script(REAL_DOC), tool="Edit")
    assert r.returncode == 0 and r.stderr == ""


def test_a_path_outside_the_four_globs_fast_exits(tmp_path):
    r = _run(tmp_path, tmp_path / "repo/q-system/output/notes.py", _script(REAL_DOC))
    assert r.returncode == 0 and r.stderr == ""


def test_config_kipi_is_in_scope(tmp_path):
    home = tmp_path / "home"
    (home / ".config/kipi").mkdir(parents=True)
    r = _run(tmp_path, home / ".config/kipi/new-switch.py", _script(REAL_DOC), extra_env={"HOME": str(home)})
    assert r.returncode == 2 and "BLOCKED" in r.stderr, r.stderr


def test_a_missing_or_failing_improve_ground_passes_with_the_note(tmp_path):
    r = _run(tmp_path, _target(tmp_path), _script(REAL_DOC), ground=tmp_path / "absent.py")
    assert r.returncode == 0 and "did not check" in r.stderr
    broken = tmp_path / "broken.py"
    broken.write_text("raise SystemExit('boom')\n")
    r = _run(tmp_path, _target(tmp_path), _script(REAL_DOC), ground=broken)
    assert r.returncode == 0 and "did not check" in r.stderr


def test_the_skip_marker_bypasses(tmp_path):
    r = _run(tmp_path, _target(tmp_path), _script(REAL_DOC) + "# improve-ground-skip: truly new\n")
    assert r.returncode == 0 and r.stderr == ""


def test_the_active_ticket_title_is_grounded_before_the_docstring(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".claude/state").mkdir(parents=True)
    (repo / ".prd-os/issues").mkdir(parents=True)
    (repo / ".prd-os/issues/ASK-1.md").write_text("---\nid: ASK-1\ntitle: a deadman for the morning brief\n---\n")
    (repo / ".claude/state/active-issue.json").write_text(
        json.dumps({"issue_id": "ASK-1", "spec_path": ".prd-os/issues/ASK-1.md"}))
    r = _run(tmp_path, _target(tmp_path), _script(NEW_DOC))
    assert r.returncode == 2 and "BLOCKED" in r.stderr, r.stderr


def test_a_new_test_file_is_out_of_scope(tmp_path):
    r = _run(tmp_path, _target(tmp_path, "repo/plugins/kipi-core/scripts/test_new_thing.py"), _script(REAL_DOC))
    assert r.returncode == 0 and r.stderr == ""
