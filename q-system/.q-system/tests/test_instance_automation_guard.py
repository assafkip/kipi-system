#!/usr/bin/env python3
"""instance-automation-guard's instance-owned carve-out, held to the truth.

sp-c2e12da4: the guard blocked scripts under q-system/output/ while
kipi-update.sh excludes output/ from the q-system rsync --delete. The
clobber premise was false for every subtree in INSTANCE_OWNED_SUBTREES,
and each false block forced an automation-guard-skip marker onto a real
experiment artifact.

THE PARITY TEST IS THE FIX's TEETH: the carve-out list lives in two
languages (bash array drives rsync; python tuple drives the hook), and
two hand-typed lists are one edit apart from disagreeing again. The test
parses the bash array out of kipi-update.sh and refuses any drift.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))          # .q-system/tests
QSYSTEM_Q = os.path.dirname(HERE)                          # .q-system
SKELETON = os.path.dirname(os.path.dirname(QSYSTEM_Q))     # repo root
UPDATE_SH = os.path.join(SKELETON, "kipi-update.sh")
GUARD = os.path.join(QSYSTEM_Q, "scripts", "instance-automation-guard.py")
assert os.path.exists(GUARD), GUARD
assert os.path.exists(UPDATE_SH), UPDATE_SH


def _owned_from_bash():
    src = open(UPDATE_SH, encoding="utf-8").read()
    m = re.search(r"INSTANCE_OWNED_SUBTREES=\(([^)]*)\)", src, re.S)
    assert m, "INSTANCE_OWNED_SUBTREES vanished from kipi-update.sh"
    return [ln.strip().strip('"').strip("'")
            for ln in m.group(1).splitlines() if ln.strip()]


def _owned_from_python():
    ns = {}
    exec(open(GUARD, encoding="utf-8").read(), ns)
    return list(ns["INSTANCE_OWNED_SUBTREES"])


def _run_guard(file_path, project_dir):
    import json as _json
    payload = _json.dumps({"tool_input": {"file_path": file_path}})
    env = dict(os.environ, CLAUDE_PROJECT_DIR=project_dir)
    proc = subprocess.run(
        [sys.executable, GUARD], input=payload,
        capture_output=True, text=True, env=env, timeout=30)
    return proc.returncode


def test_the_two_lists_agree():
    bash_list = _owned_from_bash()
    py_list = _owned_from_python()
    assert py_list == bash_list, (
        "instance-automation-guard's carve-out drifted from "
        "kipi-update.sh's INSTANCE_OWNED_SUBTREES: %r vs %r -- one of "
        "these edits forgot the other" % (py_list, bash_list))


def _fake_instance(tmp_path):
    inst = tmp_path / "inst"
    (inst / "q-system").mkdir(parents=True)
    return str(inst)


def test_an_output_script_in_an_instance_passes(tmp_path):
    """THE DEFECT ITSELF: q-system/output is instance-owned, so a script
    there survives kipi update and must not be blocked."""
    inst = _fake_instance(tmp_path)
    target = os.path.join(inst, "q-system", "output", "probe.py")
    rc = _run_guard(target, inst)
    assert rc == 0, "exit %d on an instance-owned subtree" % rc


def test_a_q_system_root_script_still_blocks(tmp_path):
    inst = _fake_instance(tmp_path)
    target = os.path.join(inst, "q-system", "income-scanner.py")
    rc = _run_guard(target, inst)
    assert rc == 2, "the original protection must stay armed"


def test_owned_subtree_prefixes_do_not_overmatch(tmp_path):
    """outputx/ is not output/. The case match in kipi-update.sh is
    "$sub"/* with an explicit slash; the hook must spell it identically."""
    inst = _fake_instance(tmp_path)
    for decoy in ("outputx", "memoryhole", "research-old"):
        target = os.path.join(inst, "q-system", decoy, "probe.py")
        rc = _run_guard(target, inst)
        assert rc == 2, "%s must still block (prefix overmatch)" % decoy


def test_bypass_marker_and_skeleton_paths_unchanged(tmp_path):
    inst = _fake_instance(tmp_path)
    marked = os.path.join(inst, "q-system", "marked.py")
    with open(marked, "w") as fh:
        fh.write("#!/bin/sh\n# automation-guard-skip\n")
    rc = _run_guard('{"tool_input":{"file_path":%r}}' % marked, inst)
    assert rc == 0, "bypass marker must keep working"

    rc = _run_guard(
        os.path.join(str(SKELETON), "q-system", ".q-system", "s.py"),
        str(SKELETON))
    assert rc == 0, "skeleton scripts must keep propagating"


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-q"]))
