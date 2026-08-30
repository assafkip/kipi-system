#!/usr/bin/env python3
"""SKIPPED is routine, UNREACHABLE is a fact nobody can act on from here (ASK-729).

why this shape: linear-worker.sh reported every out-of-repo issue on ONE line --
"N ready-shaped issue(s) skipped as out-of-repo". Measured 2026-08-13 against the
live board that line read 45, and it mixed two populations that call for opposite
responses:

  * a project whose checkout EXISTS on this machine, just not the one this run is
    in. Routine. The dispatcher's rotation reaches it on a later turn.
  * a project with NO local checkout at all. No dispatcher on this machine can
    ever reach it, on any turn, however long you wait.

Collapsing the second into the first is why 45 issues sat for 13 days looking like
a filter doing its job. The count was never wrong; the CLASS was.

This test runs the SHIPPED linear-worker.sh end to end against a throwaway
skeleton, a throwaway target repo and a stubbed Linear. It asserts on the log the
worker actually writes, because the defect was in what the run SAID, and a unit
test over a predicate cannot see a reporting line.

The negative self-test matters more than the positive one here: it is easy to
write an UNREACHABLE line that fires on everything, which would be the same
single-bucket defect with a louder word. So the test pins BOTH directions -- the
reachable project must NOT appear in the unreachable line, and vice versa.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
WORKER = SCRIPTS / "linear-worker.sh"

# Stands in for linear-sync.py: the ONE seam that reaches the network. Serves the
# fixture board from a file so the test never invents a payload shape the real
# query would not return.
STUB_SYNC = '''
import json, os
def graphql(q, v):
    if "teams(" in q:
        return {"teams": {"nodes": [{"id": "TEAM"}]}}
    issues = json.load(open(os.environ["FIXTURE_ISSUES"]))
    return {"issues": {"nodes": issues,
                       "pageInfo": {"hasNextPage": False, "endCursor": None}}}
'''


def _issue(ident, project, labels=("owner:sana",)):
    return {
        "id": ident,
        "identifier": ident,
        "title": "t " + ident,
        # ready() requires this heading; without it the issue is not ready-shaped
        # and would drop out for a reason that has nothing to do with reachability.
        "description": "## Definition of Ready\nstuff",
        "state": {"name": "Backlog", "type": "backlog"},
        "project": {"name": project} if project else None,
        "labels": {"nodes": [{"name": l} for l in labels]},
    }


@pytest.fixture()
def harness(tmp_path):
    """A skeleton, a target repo with a real origin, and a stubbed Linear."""
    skel = tmp_path / "skel"
    (skel / "q-system" / ".q-system").mkdir(parents=True)
    shutil.copytree(SCRIPTS, skel / "q-system" / ".q-system" / "scripts")
    (skel / "q-system" / ".q-system" / "scripts" / "linear-sync.py").write_text(STUB_SYNC)
    # PREFLIGHT STUBBED, AND ONLY HERE (ASK-840). This file asserts ONE thing: a
    # project with a checkout is not the same fact as a project without one. Since
    # ASK-840 the worker also asks repo-preflight whether the checkout it found may
    # be entered, and `haslocal` below is a bare mkdir -- not a git repo, no remote
    # -- so the real gate refuses it and it lands in the third bucket. That would
    # make this file fail for a reason it is not about. The bucket the real gate
    # feeds is asserted against the REAL script in
    # test_dispatch_alias_reachability.py, which is where that claim belongs.
    pf = skel / "q-system" / ".q-system" / "scripts" / "repo-preflight.sh"
    pf.write_text('#!/usr/bin/env bash\nprintf "OK %s\\n" "${1:-}"\nexit 0\n')
    pf.chmod(0o755)

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

    # haslocal EXISTS on disk; nolocal deliberately does not.
    (tmp_path / "haslocal").mkdir()
    registry = {"instances": [
        {"name": "targetproj", "path": str(target)},
        {"name": "haslocal", "path": str(tmp_path / "haslocal")},
        {"name": "nolocal", "path": str(tmp_path / "no-such-checkout")},
    ]}
    (skel / "instance-registry.json").write_text(json.dumps(registry))

    board = [
        # project_known guard: some issue must name this repo's project, or the
        # run exits 9 before reporting anything.
        _issue("ASK-900", "targetproj", ("owner:assaf",)),
        _issue("ASK-901", "haslocal"),
        _issue("ASK-902", "haslocal"),
        _issue("ASK-903", "nolocal"),
        _issue("ASK-904", "nolocal"),
        _issue("ASK-905", "nolocal"),
        # An issue with no project set is not merely "elsewhere", it is
        # unaddressable. It belongs with UNREACHABLE, not with routine skips.
        _issue("ASK-906", None),
    ]
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
            ["bash", str(skel / "q-system" / ".q-system" / "scripts" / "linear-worker.sh"),
             "--repo", str(target)],
            capture_output=True, text=True, env=env, timeout=300)
        return p.stdout + p.stderr

    return run


def _line(out, needle):
    for ln in out.splitlines():
        if needle in ln:
            return ln
    return ""


def test_no_checkout_is_reported_unreachable_not_skipped(harness):
    out = harness()

    unreachable = _line(out, "UNREACHABLE")
    assert unreachable, (
        "no UNREACHABLE line. 4 of the 6 dropped issues (3 nolocal + 1 unset) have "
        "no local checkout and no dispatcher can reach them, but the run reported "
        f"them as a routine skip. Output was:\n{out}")

    # The counts are the whole point: 2 reachable-but-elsewhere, 4 unreachable.
    assert "4" in unreachable, f"expected 4 unreachable, got: {unreachable}"
    assert "nolocal" in unreachable, f"expected nolocal named, got: {unreachable}"

    # NEGATIVE SELF-TEST. An UNREACHABLE line that fires on everything is the same
    # single-bucket defect wearing a louder word, and it would pass every
    # assertion above. haslocal HAS a checkout, so it must not appear here.
    assert "haslocal" not in unreachable, (
        f"haslocal has a local checkout and is reachable on a later rotation turn; "
        f"reporting it as unreachable is a false alarm: {unreachable}")


def test_skipped_line_keeps_only_the_reachable_projects(harness):
    out = harness()

    skipped = _line(out, "skipped as out-of-repo")
    assert skipped, f"the routine-skip line disappeared entirely:\n{out}"

    assert "haslocal" in skipped, f"expected haslocal in the skip line: {skipped}"
    # The other direction of the same negative test.
    assert "nolocal" not in skipped, (
        f"nolocal has no checkout anywhere; counting it as a routine skip is the "
        f"exact defect ASK-729 fixes: {skipped}")
    assert " 2 " in skipped, f"expected 2 routine skips, got: {skipped}"


def test_digest_patterns_match_the_lines_the_worker_actually_writes(harness):
    """The reporting is only fixed if the thing that surfaces it can see it.

    A log line nobody parses is the state this issue started in, so the digest's
    own patterns are asserted against real worker output rather than against a
    hand-typed sample that could agree with my assumption instead of the code.
    """
    digest = SCRIPTS / "daily-linear-digest.py"
    if not digest.exists():
        pytest.skip("daily-linear-digest.py not present in this checkout")

    import re
    src = digest.read_text()
    pats = re.findall(r're\.compile\(r"([^"]+)"\)', src)
    assert pats, "no BLOCKED_PATTERNS found in daily-linear-digest.py"

    out = harness()
    for needle in ("UNREACHABLE", "skipped as out-of-repo"):
        line = _line(out, needle)
        assert line, f"worker wrote no {needle!r} line"
        assert any(re.search(p, line) for p in pats), (
            f"the digest recognises no pattern for the worker's {needle!r} line, so "
            f"it stays invisible in the daily report:\n  {line}")
