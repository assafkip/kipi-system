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
    (tmp_path / "t").mkdir(exist_ok=True)
    # HOME and TMPDIR pinned: the review harness runs this suite with TMPDIR
    # under ~/.config/kipi/review-scratch (PR #892 round 2, 5 tests red there).
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path / "repo"), "TMPDIR": str(tmp_path / "t"),
           "HOME": str(tmp_path / "home"),
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


def _ticket(tmp_path, title):
    repo = tmp_path / "repo"
    (repo / ".claude/state").mkdir(parents=True)
    (repo / ".prd-os/issues").mkdir(parents=True)
    (repo / ".prd-os/issues/ASK-1.md").write_text(f"---\nid: ASK-1\ntitle: {title}\n---\n")
    (repo / ".claude/state/active-issue.json").write_text(
        json.dumps({"issue_id": "ASK-1", "spec_path": ".prd-os/issues/ASK-1.md"}))


def test_a_ticket_that_names_a_built_thing_blocks(tmp_path):
    _ticket(tmp_path, "a deadman for the morning brief")
    r = _run(tmp_path, _target(tmp_path), _script(NEW_DOC))
    assert r.returncode == 2 and "BLOCKED" in r.stderr, r.stderr


def test_an_active_ticket_never_hides_a_duplicate_file(tmp_path):
    """PR #892 round 1: `ticket or docstring` let the ticket replace the file."""
    # A ticket improve_ground calls adopt. The scar title this used ("Fleet bills
    # the Claude plan ...") is already-built itself since ASK-5805; see below.
    _ticket(tmp_path, "Fleet counts review spend per PR in the weekly report")
    r = _run(tmp_path, _target(tmp_path), _script(REAL_DOC))
    assert r.returncode == 2 and "morning-brief-deadman.py" in r.stderr, r.stderr


def test_the_scar_ticket_now_blocks_on_the_switch_that_exists(tmp_path):
    """ASK-5805 (recall gap from PR #892): ASK-5782's own title got `adopt`, so
    the gate could not catch the parallel billing path it was built for."""
    _ticket(tmp_path, "Fleet bills the Claude plan, stops at 60% weekly")
    r = _run(tmp_path, _target(tmp_path), _script(REAL_DOC))
    assert r.returncode == 2 and "kipi-dispatch.sh" in r.stderr, r.stderr


def test_a_lesson_only_cite_is_advisory_not_a_block(tmp_path):
    """The corpus is test_improve_ground.py's own covered-idea fixture: recall
    weighs only terms shared by two lessons, so a lone invented lesson scores 0."""
    lessons = tmp_path / "lessons"
    lessons.mkdir()
    for slug, title, body in (
        ("every-stage-needs-its-own-trigger", "Every stage needs its own trigger",
         "a stage with no registered trigger is dead; list triggers, list stages, diff the two lists; launchd plist scheduler"),
        ("a-scheduled-job-runs-in-a-bare-environment", "A scheduled job runs in a bare environment",
         "a launchd plist trigger starts a job with no shell profile; test the stages under a stripped environment"),
        ("verify-the-copy-the-reader-actually-reads", "Verify the copy the reader actually reads",
         "the running system may load a different clone; grep the loaded copy, marketplace cache, plugin version"),
    ):
        (lessons / f"{slug}.md").write_text(
            f"---\nid: {slug}\nkind: pattern\ntitle: {title}\ndate: 2026-09-01\n---\n\n{body}\n")
    idea = "list every launchd plist trigger and diff it against the stages that should run"
    r = _run(tmp_path, _target(tmp_path), _script(idea))
    assert r.returncode == 0 and "advisory" in r.stderr and "every-stage-needs-its-own-trigger" in r.stderr, r.stderr


def test_a_fleet_worktree_under_config_kipi_is_in_scope(tmp_path):
    """PR #892 round 2: ~/.config/kipi/worktrees/<ticket>/ is a live lane root."""
    home = tmp_path / "home"
    target = home / ".config/kipi/worktrees/ask-1/q-system/.q-system/scripts/new-thing.py"
    r = _run(tmp_path, target, _script(REAL_DOC), extra_env={"HOME": str(home)})
    assert r.returncode == 2 and "BLOCKED" in r.stderr, r.stderr
    tree = home / ".config/kipi/review-trees/pr-1/q-system/.q-system/scripts/repro.py"
    assert _run(tmp_path, tree, _script(REAL_DOC), extra_env={"HOME": str(home)}).returncode == 0


def test_scratch_space_is_out_of_scope(tmp_path):
    home = tmp_path / "home"
    for rel in ("review-scratch/run.x", "some-job/state"):
        (home / ".config/kipi" / rel).mkdir(parents=True)
        r = _run(tmp_path, home / ".config/kipi" / rel / "repro.py", _script(REAL_DOC), extra_env={"HOME": str(home)})
        assert r.returncode == 0 and r.stderr == "", (rel, r.stderr)
    r = _run(tmp_path, _target(tmp_path), _script(REAL_DOC), extra_env={"TMPDIR": str(tmp_path)})
    assert r.returncode == 0 and r.stderr == ""


def test_a_new_test_file_is_out_of_scope(tmp_path):
    r = _run(tmp_path, _target(tmp_path, "repo/plugins/kipi-core/scripts/test_new_thing.py"), _script(REAL_DOC))
    assert r.returncode == 0 and r.stderr == ""
