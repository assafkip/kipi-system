#!/usr/bin/env python3
"""Reachability is a fact about a CHECKOUT, not a string match on two names (ASK-840).

why this shape: ASK-729 split the worker's out-of-repo population into SKIPPED and
UNREACHABLE, and answered "is there a checkout" with

    project_of(issue) in {registry row name for every row whose path exists}

That is a string equality between two namespaces nothing ever required to agree.
Measured 2026-08-15 against the live board, they do not:

    Linear project        registry name          path                exists
    ASK Consulting        ASK_AI_consultant      ~/projects/...      YES
    cole-GTM              gtm-partner            ~/projects/...      YES

14 + 3 = 17 of the 44 UNREACHABLE issues were on repos cloned and registered right
then, and the log told the operator to clone repos he already had.

TWO DEFECTS, TWO TESTS, and the second is the one with teeth:

  1. the alias. A row whose Linear project name differs from its registry name must
     classify as reachable. This is the reproducer the issue names.
  2. reachable is not dispatchable. Promoting those 17 into the routine-skip line
     would say "the rotation reaches them later", which for a CLIENT repo is false
     forever -- repo-preflight check 0 refuses it whatever its name resolves to. So
     the third bucket is asserted through the REAL repo-preflight.sh, never a stub:
     a test that stubs the gate it is claiming to consult proves nothing about the
     gate.

Both run the SHIPPED linear-worker.sh end to end against a throwaway skeleton and a
stubbed Linear, and assert on the log the worker actually writes -- same reason as
test_dispatch_reachability.py, whose harness this mirrors: the defect is in what the
run SAID, and a unit test over a predicate cannot see a reporting line.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent

# Stands in for linear-sync.py: the ONE seam that reaches the network.
STUB_SYNC = '''
import json, os
def graphql(q, v):
    if "teams(" in q:
        return {"teams": {"nodes": [{"id": "TEAM"}]}}
    issues = json.load(open(os.environ["FIXTURE_ISSUES"]))
    return {"issues": {"nodes": issues,
                       "pageInfo": {"hasNextPage": False, "endCursor": None}}}
'''

# A preflight that clears everything. Used ONLY for the rows this test wants on the
# far side of the gate; the client-repo row is judged by the real script.
STUB_PREFLIGHT_OK = '''#!/usr/bin/env bash
printf 'OK %s\\n' "${1:-}"
exit 0
'''


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


def _build(tmp_path, registry_rows, board, preflight_stub=None):
    """A skeleton, a target repo with a real origin, a stubbed Linear, a runner."""
    skel = tmp_path / "skel"
    (skel / "q-system" / ".q-system").mkdir(parents=True)
    shutil.copytree(SCRIPTS, skel / "q-system" / ".q-system" / "scripts")
    scripts = skel / "q-system" / ".q-system" / "scripts"
    (scripts / "linear-sync.py").write_text(STUB_SYNC)
    if preflight_stub is not None:
        (scripts / "repo-preflight.sh").write_text(preflight_stub)
        (scripts / "repo-preflight.sh").chmod(0o755)

    # git fetch runs before any of the reporting under test, so origin has to be
    # real or the run exits 9 and this test measures the guard instead.
    subprocess.run(["git", "init", "-q", "--bare", str(tmp_path / "origin.git")], check=True)
    target = tmp_path / "target"
    subprocess.run(["git", "init", "-q", str(target)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(target), "config", k, v], check=True)
    (target / "f.txt").write_text("x")
    subprocess.run(["git", "-C", str(target), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(target), "commit", "-qm", "init"], check=True)
    subprocess.run(["git", "-C", str(target), "remote", "add", "origin",
                    str(tmp_path / "origin.git")], check=True)
    subprocess.run(["git", "-C", str(target), "push", "-q", "origin", "HEAD:main"], check=True)

    rows = [{"name": "targetproj", "path": str(target)}] + registry_rows
    (skel / "instance-registry.json").write_text(json.dumps({"instances": rows}))

    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps(board))
    state = tmp_path / "state"
    state.mkdir()

    def run():
        env = dict(os.environ)
        env.update({
            "KIPI_SKEL": str(skel),
            "KIPI_STATE_DIR": str(state),
            "FIXTURE_ISSUES": str(fixture),
            "KIPI_NOTIFY": "/bin/true",
        })
        p = subprocess.run(
            ["bash", str(scripts / "linear-worker.sh"), "--repo", str(target)],
            capture_output=True, text=True, env=env, timeout=300)
        return p.stdout + p.stderr

    return run


def _line(out, needle):
    for ln in out.splitlines():
        if needle in ln:
            return ln
    return ""


@pytest.fixture()
def aliased(tmp_path):
    """One row whose registry name and Linear project name deliberately disagree."""
    # The alias row's checkout EXISTS. `nolocal` deliberately does not, and is the
    # negative half: a fix that simply empties the UNREACHABLE bucket would pass
    # every positive assertion below.
    (tmp_path / "aliased-dir").mkdir()
    rows = [
        {"name": "registry_side_name", "linear_project": "Board Side Name",
         "path": str(tmp_path / "aliased-dir")},
        {"name": "nolocal", "path": str(tmp_path / "no-such-checkout")},
    ]
    board = [
        # project_known guard: some issue must name this repo's project, or the run
        # exits 9 before reporting anything.
        _issue("ASK-900", "targetproj", ("owner:assaf",)),
        _issue("ASK-901", "Board Side Name"),
        _issue("ASK-902", "Board Side Name"),
        _issue("ASK-903", "nolocal"),
    ]
    return _build(tmp_path, rows, board, preflight_stub=STUB_PREFLIGHT_OK)


def test_registry_name_differing_from_linear_project_is_reachable(aliased):
    """The reproducer ASK-840 names. RED at HEAD: no alias field is read at all."""
    out = aliased()

    unreachable = _line(out, "UNREACHABLE")
    assert "Board Side Name" not in unreachable, (
        "a project whose checkout is on disk right now was reported UNREACHABLE "
        "because its Linear name is spelled differently from its registry name. "
        f"That line asks the operator to clone a repo he already has:\n  {unreachable}")

    skipped = _line(out, "skipped as out-of-repo")
    assert "Board Side Name" in skipped, (
        "the aliased project cleared preflight and has a local checkout, so it is a "
        f"routine skip the rotation reaches on a later turn. Output was:\n{out}")

    # NEGATIVE SELF-TEST. Deleting the UNREACHABLE bucket outright would satisfy the
    # first assertion, so the row that genuinely has no checkout must still land in
    # it -- otherwise this test rewards the opposite bug.
    assert "nolocal" in unreachable, (
        f"nolocal has no checkout anywhere and must stay UNREACHABLE: {unreachable}")


@pytest.fixture()
def client_repo(tmp_path):
    """An aliased row whose path has the shape repo-preflight check 0 refuses.

    NO PREFLIGHT STUB. The point of this test is that resolving the name does not
    resolve the safety question, and the only thing that can show that is the real
    gate. Check 0 is decided on path shape alone and exits before any network call,
    so running it for real here is both honest and cheap.
    """
    client = tmp_path / "consulting" / "projects" / "someclient"
    client.mkdir(parents=True)
    rows = [
        {"name": "registry_side_name", "linear_project": "Board Side Name",
         "path": str(client)},
        {"name": "nolocal", "path": str(tmp_path / "no-such-checkout")},
    ]
    board = [
        _issue("ASK-900", "targetproj", ("owner:assaf",)),
        _issue("ASK-901", "Board Side Name"),
        _issue("ASK-903", "nolocal"),
    ]
    return _build(tmp_path, rows, board)


def test_resolved_name_does_not_promote_a_client_repo_into_the_queue(client_repo):
    """Reachable is not dispatchable, and the worker must say which one it means."""
    out = client_repo()

    refused = _line(out, "REFUSED by preflight")
    assert refused, (
        "an aliased project on a client-repo path has a checkout but repo-preflight "
        "refuses it forever, so it is neither a routine skip nor unreachable. The "
        f"worker reported no third bucket at all. Output was:\n{out}")
    assert "Board Side Name" in refused, f"expected the project named: {refused}"
    assert "client-repo" in refused, (
        "the refusal must carry the reason the real gate gave, or the operator "
        f"cannot tell a permanent refusal from a curable one: {refused}")

    # It must NOT read as a routine skip -- that is the sentence that would be false
    # forever, because no rotation turn will ever make a client repo dispatchable.
    skipped = _line(out, "skipped as out-of-repo")
    assert "Board Side Name" not in skipped, (
        f"a client repo can never be reached by a later rotation turn: {skipped}")
    assert "Board Side Name" not in _line(out, "UNREACHABLE"), (
        "the checkout exists; calling it unreachable sends the operator to clone it")


def test_digest_can_see_the_refused_line(client_repo):
    """A third bucket nobody surfaces is the state this issue started in.

    The daily digest is the one place the founder reads this, and its patterns are
    matched against REAL worker output rather than a hand-typed sample -- a sample
    would only prove the pattern agrees with my idea of the wording. sp-123bc141
    already records the same gap for the DISPATCHER refusal line, which is a
    different producer and stays captured rather than fixed here.
    """
    digest = SCRIPTS / "daily-linear-digest.py"
    if not digest.exists():
        pytest.skip("daily-linear-digest.py not present in this checkout")

    import re
    pats = re.findall(r're\.compile\(r"([^"]+)"\)', digest.read_text())
    assert pats, "no BLOCKED_PATTERNS found in daily-linear-digest.py"

    line = _line(client_repo(), "REFUSED by preflight")
    assert line, "worker wrote no REFUSED line"
    assert any(re.search(p, line) for p in pats), (
        "the digest recognises no pattern for the worker's REFUSED line, so the "
        f"third bucket stays invisible in the daily report:\n  {line}")


if __name__ == "__main__":
    # THE MANIFEST RUNNER IS `python3 <file>`, AND THE ALLOWED SET IS python3|bash
    # (capability-gate.py:127). A pytest module with no __main__ collects nothing
    # under that runner and exits 0, so the manifest reports coverage that never
    # ran -- sp-bbdcf57b, verified across 12 declared tests. Fixing those twelve is
    # not this issue; not adding a thirteenth is free, so this file runs itself.
    import sys
    raise SystemExit(subprocess.call(
        [sys.executable, "-m", "pytest", "-q", os.path.abspath(__file__)]))
