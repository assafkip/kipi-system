#!/usr/bin/env python3
"""RED FIRST. The promotion path (prd-lessons-rail-and-up-rail, Phase 4), one
slice per issue, all in this file. Every run uses two tmp trees (an instance
and a skeleton) built here; the live trees are never read or written.

Slice 1, issue lr-promote-path-containment (Codex finding-2 on the PRD): a
promoter with no containment would copy ../ or a symlink target out of the
instance and into the skeleton, which fans out to 25 instances.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
PROMOTE = ROOT / "kipi-promote.sh"
CLI = ROOT / "kipi"


def _trees(tmp_path):
    inst = tmp_path / "instance"
    skel = tmp_path / "skeleton"
    (inst / "q-system" / "lessons").mkdir(parents=True)
    (inst / "q-system" / ".q-system" / "scripts").mkdir(parents=True)
    (inst / "q-consult" / "pipeline").mkdir(parents=True)
    (skel / "q-system" / "lessons").mkdir(parents=True)
    (inst / "q-system" / "lessons" / "general.md").write_text("---\ntitle: A general lesson\n---\nhow to do a thing\n")
    (inst / "q-consult" / "pipeline" / "voice.py").write_text("print('instance-owned')\n")
    (tmp_path / "outside.md").write_text("outside the instance\n")
    return inst, skel


def _promote(tmp_path, rel, unscrubbed=True, cwd=None):
    inst, skel = tmp_path / "instance", tmp_path / "skeleton"
    env = dict(os.environ, KIPI_PROMOTE_INSTANCE=str(inst), KIPI_PROMOTE_SKELETON=str(skel))
    if unscrubbed:
        env["KIPI_PROMOTE_UNSCRUBBED"] = "1"
    # timeout: a promoter that reads a fifo blocks forever; a hang is a failure, not a wait
    return subprocess.run(["/bin/bash", str(PROMOTE), rel], capture_output=True, text=True, env=env, cwd=cwd or inst, timeout=20)


def _nothing_copied(tmp_path):
    skel = tmp_path / "skeleton"
    files = [p for p in skel.rglob("*") if p.is_file()]
    assert files == [], f"refusal must copy nothing, found {files}"


@pytest.mark.parametrize("rel,why", [
    ("{inst}/q-system/lessons/general.md", "absolute, even when it points inside q-system"),
    ("/etc/hosts", "absolute"),
    ("q-system/../outside.md", "dot-dot"),
    ("q-system/./lessons/general.md", "dot segment"),
    ("q-consult/pipeline/voice.py", "outside q-system"),
    ("q-system/lessons", "directory"),
    ("q-system/lessons/missing.md", "no such file"),
])
def test_containment_refuses_bad_inputs(tmp_path, rel, why):
    inst, _ = _trees(tmp_path)
    r = _promote(tmp_path, rel.format(inst=inst))
    assert r.returncode == 2, (why, r.returncode, r.stderr)
    assert "refused" in r.stderr, r.stderr
    _nothing_copied(tmp_path)


def test_containment_refuses_a_symlinked_file_and_a_symlinked_parent(tmp_path):
    inst, skel = _trees(tmp_path)
    (inst / "q-system" / "lessons" / "link.md").symlink_to(tmp_path / "outside.md")
    r = _promote(tmp_path, "q-system/lessons/link.md")
    assert r.returncode == 2 and "symlink" in r.stderr, r.stderr
    (inst / "q-system" / "linked-dir").symlink_to(tmp_path)
    r = _promote(tmp_path, "q-system/linked-dir/outside.md")
    assert r.returncode == 2 and "symlink" in r.stderr, r.stderr
    _nothing_copied(tmp_path)


def test_containment_refuses_a_fifo(tmp_path):
    inst, _ = _trees(tmp_path)
    os.mkfifo(inst / "q-system" / "lessons" / "pipe.md")
    r = _promote(tmp_path, "q-system/lessons/pipe.md")
    assert r.returncode == 2 and "regular file" in r.stderr, r.stderr
    _nothing_copied(tmp_path)


def test_a_plain_relative_q_system_path_copies_to_the_same_relative_path(tmp_path):
    inst, skel = _trees(tmp_path)
    r = _promote(tmp_path, "q-system/lessons/general.md")
    assert r.returncode == 0, r.stderr
    assert (skel / "q-system" / "lessons" / "general.md").read_text() == (inst / "q-system" / "lessons" / "general.md").read_text()
    (inst / "q-system" / ".q-system" / "scripts" / "new-tool.py").write_text("print('general')\n")
    r = _promote(tmp_path, "q-system/.q-system/scripts/new-tool.py")
    assert r.returncode == 0 and (skel / "q-system" / ".q-system" / "scripts" / "new-tool.py").exists(), "parents are created"


def test_without_the_unscrubbed_seam_containment_passes_but_nothing_is_copied(tmp_path):
    """The containment slice can never ship as a working promoter on its own."""
    _trees(tmp_path)
    r = _promote(tmp_path, "q-system/lessons/general.md", unscrubbed=False)
    assert r.returncode == 3 and "nothing copied" in r.stderr, (r.returncode, r.stderr)
    _nothing_copied(tmp_path)


def test_unscrubbed_seam_is_ignored_outside_pytest(tmp_path):
    inst, skel = _trees(tmp_path)
    env = dict(os.environ, KIPI_PROMOTE_INSTANCE=str(inst), KIPI_PROMOTE_SKELETON=str(skel), KIPI_PROMOTE_UNSCRUBBED="1")
    env.pop("PYTEST_CURRENT_TEST", None)
    r = subprocess.run(["/bin/bash", str(PROMOTE), "q-system/lessons/general.md"], capture_output=True, text=True, env=env, cwd=inst)
    assert r.returncode == 3, "the seam only opens under pytest"
    _nothing_copied(tmp_path)


def test_destination_chain_with_a_symlink_is_refused_and_nothing_lands_outside(tmp_path):
    """Codex adversarial: mkdir/cp followed a symlinked destination directory."""
    inst, skel = _trees(tmp_path)
    outside = tmp_path / "outside-skeleton"
    outside.mkdir()
    (skel / "q-system" / "lessons").rmdir()
    (skel / "q-system" / "lessons").symlink_to(outside)
    r = _promote(tmp_path, "q-system/lessons/general.md")
    assert r.returncode == 2 and "contained copy failed" in r.stderr, (r.returncode, r.stderr)
    assert list(outside.iterdir()) == [], "nothing may land through the symlink"


def test_the_copy_is_the_containment_not_a_precheck_plus_cp():
    """Codex adversarial: validate-then-cp is a race. The copy walks both chains
    with O_NOFOLLOW relative to directory fds, so a swapped component fails."""
    src = PROMOTE.read_text()
    assert "O_NOFOLLOW" in src and "dir_fd=" in src
    assert "\ncp " not in src and " cp " not in src.replace("contained copy", ""), "no plain cp anywhere"


def test_the_seam_also_requires_a_temp_rooted_instance():
    """Codex adversarial: PYTEST_CURRENT_TEST alone is anyone's to set."""
    src = PROMOTE.read_text()
    assert "/private/var/folders/*" in src and '[ "$_tmp_rooted" != "1" ]' in src


def test_unresolvable_skeleton_refuses(tmp_path):
    inst, _ = _trees(tmp_path)
    env = dict(os.environ, KIPI_PROMOTE_INSTANCE=str(inst), KIPI_PROMOTE_SKELETON=str(tmp_path / "nowhere"))
    r = subprocess.run(["/bin/bash", str(PROMOTE), "q-system/lessons/general.md"], capture_output=True, text=True, env=env, cwd=inst)
    assert r.returncode == 2 and "skeleton" in r.stderr


def test_cli_registers_promote(tmp_path):
    src = CLI.read_text()
    assert "kipi promote" in src and "kipi-promote.sh" in src
    h = subprocess.run(["/bin/bash", str(CLI), "help"], capture_output=True, text=True)
    assert "promote" in h.stdout, h.stdout[-500:]
    # the dispatch itself, not the help text: `kipi promote` must reach the promoter
    inst, skel = _trees(tmp_path)
    env = dict(os.environ, KIPI_PROMOTE_INSTANCE=str(inst), KIPI_PROMOTE_SKELETON=str(skel))
    r = subprocess.run(["/bin/bash", str(CLI), "promote", "q-system/lessons/missing.md"], capture_output=True, text=True, env=env, cwd=inst, timeout=20)
    assert r.returncode == 2 and "kipi promote: refused: no such file" in r.stderr, (r.returncode, r.stderr[-300:], r.stdout[-300:])


def test_this_file_runs_its_own_tests_under_python3():
    if os.environ.get("KIPI_SELFTEST_INNER"):
        pytest.skip("inner run")
    env = dict(os.environ, KIPI_SELFTEST_INNER="1")
    ok = subprocess.run([sys.executable, __file__], capture_output=True, text=True, env=env)
    assert ok.returncode == 0 and "passed" in ok.stdout, ok.stdout[-600:]
    none = subprocess.run([sys.executable, __file__, "-k", "no_such_test_zzz"], capture_output=True, text=True, env=env)
    assert none.returncode != 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
