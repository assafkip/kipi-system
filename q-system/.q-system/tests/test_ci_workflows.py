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

The second half drives verify.yml's step for real, with a recording `bash` stub
on a sealed PATH, the way test_validate_workflow.py drives validate.yml.

KIPI_WORKFLOWS_DIR grades another directory (the pre-fix workflows go red).
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = Path(os.environ.get("KIPI_WORKFLOWS_DIR") or ROOT / ".github" / "workflows")
NIGHTLY = "gates.yml"

# Options whose NEXT token is a value, not a test path.
_PYTEST_VALUE_OPTS = {"-m", "-k", "-o", "-p", "-c", "-n", "--rootdir", "--ignore",
                      "--deselect", "--junitxml", "--maxfail", "--confcutdir", "-W"}


def _code(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def _steps(text: str) -> list[str]:
    return re.split(r"(?m)^\s*- (?=name:|uses:|run:)", _code(text))[1:]


def _pytest_door(line: str) -> bool:
    # pytest as the COMMAND (`pip install pytest` names it as a package).
    m = re.search(r"(?:^|[;&|(]\s*)(?:python3?\s+-m\s+)?(?:py\.test|pytest)\b(.*)$", line)
    if not m:
        return False
    try:
        toks = shlex.split(m.group(1), comments=False)
    except ValueError:
        toks = m.group(1).split()
    toks = [t for t in toks if t not in ("|", "||", "&&", ";", "\\")]
    paths, skip = [], False
    for t in toks:
        if skip:
            skip = False
            continue
        if t in _PYTEST_VALUE_OPTS:
            skip = True
            continue
        if t.startswith("-"):
            continue
        if t in ("tee",) or t.startswith((">", "2>")):
            break
        paths.append(t)
    if not paths:
        return True                      # bare pytest: the whole rootdir
    for p in paths:
        if p.startswith("$"):
            continue                     # the documented limit above
        if not (p.endswith(".py") or ".py::" in p):
            return True                  # a directory: a whole suite
    return False


def full_suite_doors(text: str) -> list[str]:
    hits = []
    for step in _steps(text):
        for line in step.splitlines():
            s = re.sub(r"^(?:-\s*)?run:\s*", "", line.strip())
            if re.match(r"^(?:-\s*)?name:", s):
                continue                 # a step's label is not code
            # verify.sh as the COMMAND, never as an argument: the harness steps
            # pass it to test_verify_*.sh, which grade it on fixtures.
            v = re.search(r"(?:^|[;&|]\s*|(?:^|\s)(?:bash|sh)\s+)(?:\S*/)?verify\.sh\b(.*)$", s)
            if v and not re.match(r"\s+--(changed|staged)\b", v.group(1)):
                hits.append(f"verify.sh runs --full: {s}")
            if "capability-gate.py" in s and "--diff-base" not in s and "--check-only" not in s:
                hits.append(f"capability gate with no diff base: {s}")
            if _pytest_door(s):
                hits.append(f"pytest over a whole suite: {s}")
            if re.search(r"\bkipi\s+check\b", s):
                hits.append(f"kipi check runs the full gate: {s}")
        # As a command: the protected-files step lists the name as a string.
        if re.search(r"python3?\s+\S*validate-separation\.py", step) and not re.search(r'CAPABILITY_GATE_SKIP:\s*"?1"?', step):
            hits.append("validate-separation.py without CAPABILITY_GATE_SKIP runs the full gate")
    return hits


def _workflow_files() -> list[Path]:
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    assert files, f"no workflows under {WORKFLOWS}"
    return files


@pytest.mark.parametrize("wf", [p.name for p in _workflow_files()])
def test_only_the_nightly_can_run_a_whole_suite(wf):
    if wf == NIGHTLY:
        pytest.skip("the nightly is the one place the full suite runs")
    doors = full_suite_doors((WORKFLOWS / wf).read_text())
    assert not doors, f"{wf} can run a whole suite on PR or push:\n  " + "\n  ".join(doors)


def test_the_nightly_still_exists():
    assert (WORKFLOWS / NIGHTLY).is_file(), "the full suite needs its one home"


@pytest.mark.parametrize("snippet,door", [
    ("      - run: bash q-system/.q-system/verify.sh --full", True),
    ("      - run: bash q-system/.q-system/verify.sh", True),
    ("      - run: bash q-system/.q-system/verify.sh --changed --base \"$base\"", False),
    ("      - run: bash q-system/.q-system/verify.sh --staged", False),
    ("      - run: bash q-system/.q-system/test_verify_changed.sh q-system/.q-system/verify.sh", False),
    ("      - run: q-system/.q-system/verify.sh", True),
    ("      - name: verify.sh --full\n        run: echo labelled only", False),
    ("      - run: python3 q-system/.q-system/scripts/capability-gate.py --repo-root .", True),
    ("      - run: python3 q-system/.q-system/scripts/capability-gate.py --repo-root . --diff-base x", False),
    ("      - run: pytest plugins/prd-os/tests/ -q", True),
    ("      - run: python3 -m pytest -q", True),
    ("      - run: python -m pytest tests -m \"not slow\"", True),
    ("      - run: pytest q-system/.q-system/tests/test_auto_commit.py -q", False),
    ("      - run: pytest a/test_x.py::test_one -m \"not slow\"", False),
    ("      - run: python3 -m pytest $TEST_TARGETS -q", False),
    ("      - run: kipi check", True),
    ("      - run: pip install pytest", False),
    ("      - run: |\n          FILES=(\n            \"validate-separation.py\"\n          )", False),
    ("      - name: v\n        run: python3 validate-separation.py 1 --verbose", True),
    ("      - name: v\n        run: python3 validate-separation.py 1 --verbose\n"
     "        env:\n          CAPABILITY_GATE_SKIP: \"1\"", False),
    ("      # a comment naming verify.sh --full is not a door\n      - run: echo hi", False),
])
def test_the_detector_fires_on_every_door_and_only_there(snippet, door):
    """A detector with no fixture of its own is a check nobody has seen fail."""
    hits = full_suite_doors("jobs:\n  j:\n    steps:\n" + snippet + "\n")
    assert bool(hits) is door, (snippet, hits)


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
