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

# THE STUB ABOVE SWALLOWS $2, WHICH IS WHY THE FIRST CUT OF THIS SUITE COULD NOT
# SEE THE REMOTE DEFECT AT ALL (PR #205 codex round 1, major). Promoting the
# skeleton into local_repos without translating its pin only moved it from the
# UNREACHABLE bucket to the REFUSED one. This stub records argv and mirrors ONE
# branch of the shipped gate -- repo-preflight.sh check 4, "the registry row pins
# no expected_remote; an unpinned repo is never entered" -- because the real
# script reaches gh and the GitHub API in checks 6 and 7 and cannot run hermetic.
# Only that branch is mirrored, and the ARGV log is what the assertions lean on,
# so a drift in the gate's wording cannot make this suite pass or fail for the
# wrong reason.
STUB_PREFLIGHT_RECORDS_REMOTE = '''#!/usr/bin/env bash
printf '%s\\037%s\\n' "${1:-}" "${2:-}" >> "$PREFLIGHT_ARGV_LOG"
if [ -z "${2:-}" ]; then
  printf 'FAIL remote: the registry row pins no expected_remote; an unpinned repo is never entered\\n'
  printf 'REFUSED %s\\n' "${1:-}"
  exit 1
fi
printf 'OK %s\\n' "${1:-}"
exit 0
'''

# The skeleton's pin, as the live registry states it: a TOP-LEVEL `remote` key on
# the `skeleton` object. Instance rows state theirs at `dispatch.expected_remote`
# instead, and the fixture below carries both shapes so the translation cannot be
# written as "read one field everywhere".
SKEL_REMOTE = "https://example.invalid/skeleton-pin.git"
TARGET_REMOTE = "https://example.invalid/target-pin.git"

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


def _build(tmp_path, registry, board, preflight_stub=None, extra_env=None):
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
        env.update(extra_env or {})
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


@pytest.fixture()
def registry_pins_two_shapes(tmp_path):
    """Both pin shapes in one registry, plus a row that pins nothing.

    The skeleton states its pin at top-level `remote`; an instance states its at
    `dispatch.expected_remote`. A translation written as "read one field" gets
    one of the two wrong, so both travel here. The unpinned row is the negative
    half: it must keep arriving EMPTY.
    """
    pinned = tmp_path / "pinned-dir"
    unpinned = tmp_path / "unpinned-dir"
    stray = tmp_path / "stray-dir"
    for d in (pinned, unpinned, stray):
        d.mkdir()
    registry = {
        "skeleton": {"linear_project": SKEL_PROJECT, "remote": SKEL_REMOTE},
        "instances": [
            {"name": "targetproj", "path": str(tmp_path / "target")},
            {"name": "dispatchpinproj", "path": str(pinned),
             "dispatch": {"expected_remote": TARGET_REMOTE}},
            {"name": "unpinnedproj", "path": str(unpinned)},
            # An INSTANCE carrying the skeleton's field name. No live row looks
            # like this today; it exists so the scoping decision is testable
            # rather than a claim in a comment.
            {"name": "strayremoteproj", "path": str(stray),
             "remote": "https://example.invalid/stray.git"},
        ],
    }
    board = [
        _issue("ASK-900", "targetproj", ("owner:assaf",)),
        _issue("ASK-901", SKEL_PROJECT),
        _issue("ASK-903", "dispatchpinproj"),
        _issue("ASK-904", "unpinnedproj"),
        _issue("ASK-905", "strayremoteproj"),
    ]
    argv_log = tmp_path / "preflight-argv.log"
    run, skel, target = _build(
        tmp_path, registry, board,
        preflight_stub=STUB_PREFLIGHT_RECORDS_REMOTE,
        extra_env={"PREFLIGHT_ARGV_LOG": str(argv_log)})
    return run, skel, target, pinned, unpinned, stray, argv_log


def _argv_rows(log):
    if not log.exists():
        return []
    return [ln.split("\x1f") for ln in log.read_text().splitlines() if ln]


def test_the_skeletons_pinned_remote_reaches_preflight(registry_pins_two_shapes):
    """Reproducer 3. RED after the ASK-881 fix, before this one.

    Promoting the skeleton into local_repos gave the gate a row it could finally
    be asked about -- and then handed it an empty remote, because the row builder
    reads `dispatch.expected_remote` and the skeleton pins at top-level `remote`.
    The gate refuses an unpinned row by design, so the skeleton simply moved from
    UNREACHABLE to REFUSED and every other repo's run reported the skeleton off
    limits for a pin that is right there in the registry.
    """
    run, skel, target, pinned, unpinned, stray, argv_log = registry_pins_two_shapes
    rc, out = run(target)
    assert rc == 0, f"expected a clean run, got exit {rc}:\n{out}"

    seen = dict((row[0], row[1]) for row in _argv_rows(argv_log) if len(row) == 2)
    assert seen.get(str(skel)) == SKEL_REMOTE, (
        "the registry pins the skeleton's remote at its top-level `remote` key. "
        "The worker read only `dispatch.expected_remote`, so the gate was asked "
        f"about an unpinned repo. preflight saw: {seen!r}")

    # The OTHER shape must not regress. A translation that replaced the dispatch
    # read instead of adding to it would pass the assertion above and break every
    # instance row that actually pins one.
    assert seen.get(str(pinned)) == TARGET_REMOTE, (
        "an instance row still states its pin at dispatch.expected_remote; "
        f"preflight saw: {seen!r}")

    # NEGATIVE SELF-TEST. "Unpinned is never entered" is the gate's rule, so a fix
    # that defaulted to the checkout's own git origin -- or to any non-empty
    # string -- would satisfy both assertions above while quietly admitting every
    # repo nobody ever pinned.
    assert seen.get(str(unpinned)) == "", (
        "a row that pins nothing must still arrive empty; inventing a remote for "
        f"it hands the gate a pin the registry never stated. preflight saw: {seen!r}")

    # KILLS THE WIDER MUTANT. A bare `or e.get("remote")` on every row passes
    # every assertion above, and it is the version that softens the rule: a stray
    # `remote` on an instance nobody opted into dispatch would start reading as a
    # pin, turning a refusal into an entry. Top-level `remote` is the SKELETON
    # object's shape and is only honoured there.
    assert seen.get(str(stray)) == "", (
        "top-level `remote` is the skeleton object's field. Honouring it on an "
        "instance row would promote a value nobody wrote as a dispatch pin into "
        f"one. preflight saw: {seen!r}")

    refused = _line(out, "REFUSED by preflight")
    assert SKEL_PROJECT not in refused, (
        f"the skeleton pins {SKEL_REMOTE} and must clear the remote check:\n  {refused}")
    assert "dispatchpinproj" not in refused, f"pinnedproj pins a remote too:\n  {refused}"
    assert "unpinnedproj" in refused, (
        "the unpinned row is the one the gate is supposed to refuse; if it is "
        f"missing here the stub never ran and the argv assertions are hollow:\n{out}")


if __name__ == "__main__":
    # THE MANIFEST RUNNER IS `python3 <file>` and the allowed set is python3|bash
    # (capability-gate.py:127). A pytest module with no __main__ collects nothing
    # under that runner and exits 0, reporting coverage that never ran
    # (sp-bbdcf57b). This file runs itself.
    import sys
    raise SystemExit(subprocess.call(
        [sys.executable, "-m", "pytest", "-q", os.path.abspath(__file__)]))
