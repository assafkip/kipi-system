#!/usr/bin/env python3
"""No workflow but the nightly gates.yml may run a whole suite (RULE-2026-10-01-A).

Founder bar, 2026-10-01: "no 6000-test runs on small changes". The full suite
kept coming back through doors nobody listed: validate.yml's push branch (fixed
in #490), then verify.yml's `verify.sh --full` on every PR and push, then an
unscoped `pytest plugins/prd-os/tests/` step. Each was found one at a time. This
test reads EVERY workflow file, so the next door is red on the PR that opens it.

A full-suite door, in a step's code (comment lines are ignored, so a why-comment
may name the shape it forbids):
  * verify.sh with no mode or --full (its default IS --full)
  * capability-gate.py with neither --diff-base nor --check-only
  * pytest over a directory or over nothing (the whole rootdir)
  * validate-separation.py without CAPABILITY_GATE_SKIP "1" (phase 1 otherwise
    runs the capability gate's full suite inside itself)
  * `kipi check` (it runs that same phase)
A selector that falls back to the full suite on a change it cannot vouch for is
NOT a door: that is conditional, and the fallback is the safety.

Honest limit: a pytest argument built from a shell variable is not judged. A
selector-built list is the normal shape of that, and this test cannot tell it
from a variable holding a directory.

The detector is full_suite_doors.py, shared with the fleet scanner; its fixtures
live in test_full_suite_doors.py. The second half drives verify.yml's step for real, with a recording `bash` stub
on a sealed PATH, the way test_validate_workflow.py drives validate.yml.

KIPI_WORKFLOWS_DIR grades another directory (the pre-fix workflows go red).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = Path(os.environ.get("KIPI_WORKFLOWS_DIR") or ROOT / ".github" / "workflows")
NIGHTLY = "gates.yml"

sys.path.insert(0, str(ROOT / "q-system" / ".q-system" / "scripts"))
import full_suite_doors as fsd  # noqa: E402  the ONE detector (fleet scanner shares it)


def _workflow_files() -> list[Path]:
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    assert files, f"no workflows under {WORKFLOWS}"
    return files


@pytest.mark.parametrize("wf", [p.name for p in _workflow_files()])
def test_only_the_nightly_can_run_a_whole_suite(wf):
    if wf == NIGHTLY:
        pytest.skip("the nightly is the one place the full suite runs")
    text = (WORKFLOWS / wf).read_text()
    doors = fsd.resolve_local(fsd.workflow_doors(text),
                              lambda rel: (ROOT / rel).read_text() if (ROOT / rel).is_file() else None)
    assert not doors, f"{wf} can run a whole suite on PR or push:\n  " + "\n  ".join(doors)


def test_the_nightly_still_exists_and_is_nightly_only():
    assert (WORKFLOWS / NIGHTLY).is_file(), "the full suite needs its one home"
    assert not fsd.runs_on_pr_or_push((WORKFLOWS / NIGHTLY).read_text()), \
        "the nightly must not run on PR or push"


# ---------------------------------------------------------------- verify.yml drive
def _run_block(text: str, step_prefix: str) -> str:
    lines = text.splitlines()
    starts = [i for i, l in enumerate(lines) if l.strip().startswith(step_prefix)]
    assert len(starts) == 1, f"expected one {step_prefix!r} step, found {len(starts)}"
    i = starts[0]
    run = next(j for j in range(i, len(lines)) if re.match(r"^\s+run:\s*\|\s*$", lines[j]))
    ind = len(lines[run]) - len(lines[run].lstrip())
    body = []
    for l in lines[run + 1:]:
        if l.strip() and len(l) - len(l.lstrip()) <= ind:
            break
        body.append(l)
    w = min(len(l) - len(l.lstrip()) for l in body if l.strip())
    return "\n".join(l[w:] for l in body) + "\n"


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "LC_ALL": "C"}

    def git(*a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", *a],
                              cwd=r, env=env, check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q", "-b", "main")
    (r / "a.txt").write_text("one\n")
    git("add", "a.txt")
    git("commit", "-q", "-m", "first commit")
    first = git("rev-parse", "HEAD")
    (r / "b.txt").write_text("two\n")
    git("add", "b.txt")
    git("commit", "-q", "-m", "second commit")
    return r, first


def _drive_verify(tmp_path, r, event, base_ref="", before=""):
    b = tmp_path / "bin"
    b.mkdir()
    (b / "git").symlink_to(shutil.which("git"))
    rec = tmp_path / "argv.txt"
    stub = b / "bash"
    stub.write_text(f"#!/bin/sh\nfor a in \"$@\"; do printf '%s\\n' \"$a\"; done > '{rec}'\n")
    stub.chmod(0o755)
    real_bash = shutil.which("bash")
    script = _run_block((WORKFLOWS / "verify.yml").read_text(), "- name: verify.sh")
    env = {"PATH": str(b), "HOME": str(tmp_path), "LC_ALL": "C",
           "EVENT": event, "BASE_REF": base_ref, "PUSH_BEFORE": before}
    p = subprocess.run([real_bash, "-e", "-c", script], cwd=r, env=env, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    argv = rec.read_text().splitlines()
    assert argv and argv[0].endswith("verify.sh"), argv
    assert "--full" not in argv and argv[1] == "--changed", f"verify ran unscoped: {argv}"
    return argv[argv.index("--base") + 1]


def test_verify_push_diffs_against_before(tmp_path, repo):
    r, first = repo
    assert _drive_verify(tmp_path, r, "push", before=first) == first


@pytest.mark.parametrize("before", ["0" * 40, "deadbeef" * 5, ""])
def test_verify_unusable_push_base_falls_back_to_first_parent(tmp_path, repo, before):
    r, _ = repo
    assert _drive_verify(tmp_path, r, "push", before=before) == "HEAD^"


def test_verify_pull_request_diffs_against_its_target(tmp_path, repo):
    r, _ = repo
    assert _drive_verify(tmp_path, r, "pull_request", base_ref="main") == "origin/main"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
