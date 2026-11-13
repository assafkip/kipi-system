"""The pre-push step runs the REAL capability gate and refuses an inert engine.

Reproducer for ASK-4814 (rca-pr794-round-cap-2026-11-12.md, root cause #1).
PR #794 added startup_census.py with no caller and no declared_inert entry. CI
reported `inert-engine` 21 to 23 minutes after each of three pushes, while the
same finding takes about 17 seconds to compute locally. Nothing ran it before a
push: lefthook.yml had no pre-push section.

No stub anywhere. Each case builds a throwaway clone of this repo's HEAD, so the
gate judges the real manifest and the real wiring surfaces, and runs the real
pre-push script, which runs the real capability-gate.py. The clone is its own
repo (not a worktree), so the founder's spillover ledger is never read.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PREPUSH = REPO / "q-system/.q-system/scripts/prepush-capability-gate.sh"
PROBE = "q-system/.q-system/scripts/prepush_probe_engine.py"
ENGINE = "import sys\n\n\ndef main():\n    return 0\n\n\nif __name__ == '__main__':\n    sys.exit(main())\n"


# verify.sh runs this suite from inside a git hook, where GIT_DIR and
# GIT_INDEX_FILE point at the REAL repo. A `git add` in the clone would then
# write the real index. Every git call here runs with GIT_* removed.
def _env():
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          cwd=str(cwd), env=_env(), capture_output=True, text=True,
                          check=True).stdout


def _clone_of_head(tmp_path):
    """HEAD of this checkout as a plain repo, with origin/main pinned to it."""
    clone = tmp_path / "clone"
    clone.mkdir()
    _git(clone, "init", "-q")
    _git(clone, "fetch", "-q", "--no-tags", str(REPO), "HEAD")
    _git(clone, "checkout", "-q", "FETCH_HEAD")
    _git(clone, "update-ref", "refs/remotes/origin/main", "HEAD")
    return clone


def _commit(clone, rel, text, mode=0o644):
    path = clone / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)
    _git(clone, "add", rel)
    _git(clone, "commit", "-q", "--no-verify", "-m", f"add {rel}")


def _prepush(clone):
    return subprocess.run(["bash", str(PREPUSH)], cwd=str(clone), env=_env(),
                          capture_output=True, text=True, timeout=200)


@pytest.fixture(scope="module")
def clone_with_probe(tmp_path_factory):
    clone = _clone_of_head(tmp_path_factory.mktemp("prepush"))
    _commit(clone, PROBE, ENGINE, mode=0o755)
    return clone


def test_an_undeclared_engine_refuses_the_push(clone_with_probe):
    """The PR #794 shape: a new runnable script, no caller, no declared_inert."""
    run = _prepush(clone_with_probe)
    out = run.stdout + run.stderr
    assert run.returncode == 1, out
    assert f"RED: inert-engine: {PROBE} has no reference on any wiring surface" in out, out
    assert "capability-gate: RED (1)" in out, out


def test_its_declared_inert_entry_lets_the_push_through(clone_with_probe):
    """Same clone plus the fix PR #794 shipped: a declared_inert fragment."""
    frag = "q-system/.q-system/capability/declared_inert/" + PROBE.replace("/", "__") + ".json"
    entry = {"path": PROBE, "reason": "test probe (ASK-4814)", "spillover_id": "sp-test"}
    _commit(clone_with_probe, frag, json.dumps(entry, indent=1) + "\n")
    run = _prepush(clone_with_probe)
    out = run.stdout + run.stderr
    assert run.returncode == 0, out
    assert "capability-gate: GREEN" in out, out
    assert f"DECLARED-INERT (sp-test): {PROBE}" in out, out


def test_no_origin_main_skips_loudly_and_never_blocks(tmp_path):
    """A repo with no origin/main has no base to scope to. The step says so and
    lets the push through: CI still runs the full gate on the pushed head."""
    clone = _clone_of_head(tmp_path)
    _git(clone, "update-ref", "-d", "refs/remotes/origin/main")
    run = _prepush(clone)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "capability pre-push: SKIPPED" in run.stderr
