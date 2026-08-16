#!/usr/bin/env python3
"""The skeleton is a registry ROW too, and linear-worker.sh never read it (ASK-881).

instance-registry.json keeps the skeleton under its OWN top-level `skeleton` key,
not as a member of `instances`. ASK-839 fixed that blind spot in
`alert-to-linear.py:_registry_rows()`. `linear-worker.sh` still had the unfixed
shape at HEAD 2026-08-16: its REGISTRY_FACTS block reads

    entries = reg.get("instances", reg) if isinstance(reg, dict) else reg

and stops there. Two facts come out of that one read and BOTH were wrong for the
skeleton:

  1. repo identity. With no skeleton row, `name` stays empty and REPO_PROJECT
     falls all the way through to `basename $TARGET_REPO`. It is right today only
     because basename(kipi-system) happens to equal the board project name -- the
     exact "derivation that works until it doesn't" ASK-840 removed everywhere
     else. Any checkout of the skeleton whose directory is named anything else
     (a worktree, a CI clone, a rename) resolves to a project that does not
     exist, and the run dies MISCONFIG having picked nothing.

  2. reachability. local_repos is built from the same `entries`, so the skeleton
     checkout is never counted as locally present. An issue on the skeleton's
     project, raised from any OTHER repo in the rotation, is reported UNREACHABLE
     -- the log telling the operator to clone a repo that is on the disk it is
     running from.

Both are asserted through the SHIPPED linear-worker.sh end to end against a
throwaway skeleton and a stubbed Linear, the same harness shape as
test_dispatch_alias_reachability.py: the defect lives in what the run SAID, and a
unit test over a predicate cannot see a reporting line.

The negative half is a `standalone` row. `_registry_rows()` excludes those on
purpose (`has_skeleton: false`, so they ship no notifier and cannot reach the
path), and a "fix" that merely emptied the UNREACHABLE bucket would satisfy every
positive assertion here. It must stay unreachable.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent

# The ONE seam that reaches the network, same stub as the sibling suite.
STUB_SYNC = '''
import json, os
def graphql(q, v):
    if "teams(" in q:
        return {"teams": {"nodes": [{"id": "TEAM"}]}}
    issues = json.load(open(os.environ["FIXTURE_ISSUES"]))
    return {"issues": {"nodes": issues,
                       "pageInfo": {"hasNextPage": False, "endCursor": None}}}
'''

STUB_PREFLIGHT_OK = '''#!/usr/bin/env bash
printf 'OK %s\\n' "${1:-}"
exit 0
'''

# The skeleton's board name is deliberately NOT its directory basename. If those
# two agreed, the basename fallback would answer correctly and this suite would
# pass against the unfixed code -- which is the whole reason the live fleet never
# noticed.
SKEL_DIR = "skel-checkout"
SKEL_PROJECT = "Skeleton Board Name"


def _issue(ident, project, labels=("owner:sana",)):
    return {
        "id": ident,
        "identifier": ident,
        "title": "t " + ident,
        "description": "## Definition of Ready\nstuff",
        "state": {"name": "Backlog", "type": "backlog"},
        "project": {"name": project} if project else None,
        "labels": {"nodes": [{"name": l} for l in labels]},
    }


def _git_repo(path, origin):
    """A checkout with a real origin: git fetch runs before any reporting under
    test, so a fake remote would exit 9 and measure the guard instead."""
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(path), "config", k, v], check=True)
    (path / "f.txt").write_text("x")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", str(origin)],
                   check=True)
    subprocess.run(["git", "-C", str(path), "push", "-q", "origin", "HEAD:main"],
                   check=True)


def _build(tmp_path, registry, board, preflight_stub=None):
    """A skeleton that is itself a checkout, a second target repo, a stubbed Linear.

    Returns (run, skel, target): `run(repo)` drives the shipped worker against
    whichever of the two repos the case is about.
    """
    skel = tmp_path / SKEL_DIR
    (skel / "q-system" / ".q-system").mkdir(parents=True)
    shutil.copytree(SCRIPTS, skel / "q-system" / ".q-system" / "scripts")
    scripts = skel / "q-system" / ".q-system" / "scripts"
    (scripts / "linear-sync.py").write_text(STUB_SYNC)
    if preflight_stub is not None:
        (scripts / "repo-preflight.sh").write_text(preflight_stub)
        (scripts / "repo-preflight.sh").chmod(0o755)

    _git_repo(skel, tmp_path / "skel-origin.git")
    target = tmp_path / "target"
    _git_repo(target, tmp_path / "target-origin.git")

    registry = dict(registry)
    registry["skeleton"] = dict(registry.get("skeleton") or {}, path=str(skel))
    (skel / "instance-registry.json").write_text(json.dumps(registry))

    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps(board))
    state = tmp_path / "state"
    state.mkdir()

    def run(repo):
        env = dict(os.environ)
        env.update({
            "KIPI_SKEL": str(skel),
            "KIPI_STATE_DIR": str(state),
            "FIXTURE_ISSUES": str(fixture),
            "KIPI_NOTIFY": "/bin/true",
        })
        # KIPI_LINEAR_PROJECT would short-circuit the registry read this suite is
        # about, so it is cleared rather than assumed absent from the caller.
        env.pop("KIPI_LINEAR_PROJECT", None)
        p = subprocess.run(
            ["bash", str(scripts / "linear-worker.sh"), "--repo", str(repo)],
            capture_output=True, text=True, env=env, timeout=300)
        return p.returncode, p.stdout + p.stderr

    return run, skel, target


def _line(out, needle):
    for ln in out.splitlines():
        if needle in ln:
            return ln
    return ""


@pytest.fixture()
def skeleton_only_in_its_own_key(tmp_path):
    """The registry shape the fleet actually ships: skeleton NOT in `instances`."""
    registry = {
        "skeleton": {"linear_project": SKEL_PROJECT},
        "instances": [{"name": "targetproj", "path": str(tmp_path / "target")}],
        "standalone": [{"name": "standaloneproj",
                        "path": str(tmp_path / "standalone-dir"),
                        "has_skeleton": False}],
    }
    (tmp_path / "standalone-dir").mkdir()
    board = [
        _issue("ASK-900", "targetproj", ("owner:assaf",)),
        _issue("ASK-901", SKEL_PROJECT),
        _issue("ASK-902", "standaloneproj"),
    ]
    return _build(tmp_path, registry, board, preflight_stub=STUB_PREFLIGHT_OK)


def test_skeleton_resolves_its_own_board_name(skeleton_only_in_its_own_key):
    """Reproducer 1. RED at HEAD: `skeleton` is never read, so the run MISCONFIGs."""
    run, skel, _target = skeleton_only_in_its_own_key
    rc, out = run(skel)

    assert "MISCONFIG" not in out, (
        "the skeleton's own board name is stated in the registry's top-level "
        "`skeleton` row, but the worker only walked `instances`, fell through to "
        f"basename({SKEL_DIR}) and matched no project. The run picked nothing for "
        f"a config reason it invented:\n{out}")
    assert rc == 0, f"expected a clean run, got exit {rc}:\n{out}"
    assert f"project={SKEL_PROJECT}" in out, (
        "the worker must report the identity the registry STATES, not one derived "
        f"from the directory name (ASK-840). Output was:\n{out}")
    assert "1 ready issue(s)" in out, (
        f"ASK-901 is on the skeleton's project and is ready:\n{out}")


def test_skeleton_checkout_counts_as_locally_present(skeleton_only_in_its_own_key):
    """Reproducer 2. RED at HEAD: local_repos misses the skeleton, so its issues
    are reported UNREACHABLE from every other repo in the rotation."""
    run, _skel, target = skeleton_only_in_its_own_key
    rc, out = run(target)
    assert rc == 0, f"expected a clean run, got exit {rc}:\n{out}"

    unreachable = _line(out, "UNREACHABLE")
    assert SKEL_PROJECT not in unreachable, (
        "the skeleton checkout is on this disk -- it is the checkout the worker is "
        "reading its own registry out of. Reporting it unreachable tells the "
        f"operator to clone the repo he is running from:\n  {unreachable}")

    skipped = _line(out, "skipped as out-of-repo")
    assert SKEL_PROJECT in skipped, (
        "the skeleton has a local checkout and cleared preflight, so it is a "
        f"routine skip the rotation reaches on a later turn. Output was:\n{out}")

    # NEGATIVE SELF-TEST. A `standalone` row carries has_skeleton: false, ships no
    # notifier and cannot be dispatched to; _registry_rows() excludes it on
    # purpose. Emptying the UNREACHABLE bucket would pass every assertion above,
    # so the row that must NOT be promoted is asserted here.
    assert "standaloneproj" in unreachable, (
        "a standalone row has no skeleton and can never be dispatched to; "
        f"promoting it would only lengthen the queue with unreachable work: "
        f"{unreachable}")


if __name__ == "__main__":
    # THE MANIFEST RUNNER IS `python3 <file>` and the allowed set is python3|bash
    # (capability-gate.py:127). A pytest module with no __main__ collects nothing
    # under that runner and exits 0, reporting coverage that never ran
    # (sp-bbdcf57b). This file runs itself.
    import sys
    raise SystemExit(subprocess.call(
        [sys.executable, "-m", "pytest", "-q", os.path.abspath(__file__)]))
