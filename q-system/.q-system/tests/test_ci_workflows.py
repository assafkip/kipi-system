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


# ---------------------------------------------------------------- tree-wide gates
# A REQUIRED CHECK IS RED ONLY FOR WHAT THE CHANGE INTRODUCED (ASK-3828, RCA
# 2026-11-06 root cause #6). A check whose verdict reads the whole tree goes red
# on every PR the day main carries a finding, and no PR author can make it green:
# the PR waits for a human or the floor gets bypassed (merge-bypass-gate.py
# exists because of that). Those checks run nightly on main, where a red files
# one issue against the commit that broke it (gates-red-filer.py). On a PR or a
# push they may run only in a form scoped to the change:
#   * capability-gate.py WITH --diff-base: structure findings already on the
#     base are reported, not failed, and tests are the ones the diff earns.
#     `--check-only` alone is the whole-tree structure check.
#   * covers-lint.py WITH path arguments: only the declarations the change
#     touched. With none it sweeps every fragment.
#   * never validate-separation.py or `kipi check`: phase 1 is a whole-skeleton
#     sweep with no diff mode.
# Honest limit, same as the pytest rule above: a path argument held in a shell
# variable is trusted, and the step's own `if [ -n ... ]` guard is what keeps an
# empty variable from turning into a sweep.
def _covers_lint_scoped(line: str) -> bool:
    toks = line.split("covers-lint.py", 1)[1].split()
    rest, skip = [], False
    for t in toks:
        if t in ("|", "||", "&&", ";") or t.startswith((">", "2>")):
            break
        if skip:
            skip = False
            continue
        if t == "--repo-root":
            skip = True
            continue
        if not t.startswith("-") and t != "\\":
            rest.append(t)
    return bool(rest)


def tree_wide_gates(text: str) -> list[str]:
    if not fsd.runs_on_pr_or_push(text):
        return []
    hits = []
    for line in fsd.code_lines(text).splitlines():
        s = line.strip()
        if re.match(r"^(?:-\s*)?name:", s):
            continue
        if "capability-gate.py" in s and "--diff-base" not in s:
            hits.append(f"capability gate without --diff-base grades the whole tree: {s}")
        if "covers-lint.py" in s and not _covers_lint_scoped(s):
            hits.append(f"covers-lint with no paths sweeps every declaration: {s}")
        # As a command only: validate.yml's protected-file list names the file
        # as a string, and a string runs nothing.
        if re.search(r"\bpython3?\s+\S*validate-separation\.py\b", s):
            hits.append(f"validate-separation.py is a whole-skeleton sweep: {s}")
        if re.search(r"\bkipi\s+check\b", s):
            hits.append(f"kipi check is a whole-tree gate: {s}")
    return hits


@pytest.mark.parametrize("wf", [p.name for p in _workflow_files()])
def test_no_pr_or_push_workflow_runs_a_tree_wide_gate(wf):
    hits = tree_wide_gates((WORKFLOWS / wf).read_text())
    assert not hits, f"{wf} can go red on a PR for files the PR did not touch:\n  " + "\n  ".join(hits)


@pytest.mark.parametrize("line,tree_wide", [
    ("        run: python3 q-system/.q-system/scripts/covers-lint.py --repo-root .", True),
    ("        run: python3 s/covers-lint.py", True),
    ("          python3 s/covers-lint.py --repo-root . $frags", False),
    ("          python3 s/capability-gate.py --repo-root . --check-only", True),
    ("          python3 s/capability-gate.py --repo-root . --diff-base \"$base\"", False),
    ("        run: python3 validate-separation.py 1 --verbose", True),
    ("        run: kipi check", True),
    ("        run: pytest q-system/.q-system/tests/test_auto_commit.py -q", False),
    ("      # covers-lint.py --repo-root . used to sweep here", False),
])
def test_the_tree_wide_detector_fires_on_every_shape(line, tree_wide):
    """A detector nobody has seen fail is not a check (fable-discipline)."""
    text = "on:\n  pull_request:\njobs:\n  j:\n    steps:\n      - name: x\n" + line + "\n"
    assert bool(tree_wide_gates(text)) is tree_wide, line


# The text rule above trusts `--diff-base` to mean "scoped". These drive the real
# gate the way validate.yml calls it, so the flag cannot be scoped in name only.
# The PR #600 shape, both ways: a finding main already carries must not fail an
# unrelated PR, and a finding the PR adds must still fail it.
GATE = ROOT / "q-system" / ".q-system" / "scripts" / "capability-gate.py"


@pytest.fixture
def gate_repo(tmp_path):
    import capability_manifest  # noqa: E402  same scripts dir, already on sys.path
    r = tmp_path / "repo"
    (r / "q-system/.q-system/scripts").mkdir(parents=True)
    capability_manifest.explode(r, {"schema_version": 1, "expected_tests": [], "required_data": [],
                                    "skeleton_only": [], "declared_inert": [], "uncovered_known": []})
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "LC_ALL": "C"}

    def git(*a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", *a],
                              cwd=r, env=env, check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q", "-b", "main")
    # main already carries an undeclared test: a tree finding, nobody's PR
    (r / "q-system/.q-system/scripts/test_on_main.py").write_text("import sys; sys.exit(0)\n")
    git("add", "-A")
    git("commit", "-q", "-m", "main with a tree finding")
    return r, git("rev-parse", "HEAD"), git


def _gate(r, base):
    p = subprocess.run([sys.executable, str(GATE), "--repo-root", str(r), "--check-only",
                        "--diff-base", base], capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout + p.stderr


def test_a_finding_main_already_has_does_not_fail_the_pr(gate_repo):
    r, base, git = gate_repo
    (r / "README.md").write_text("an unrelated change\n")
    git("add", "-A")
    git("commit", "-q", "-m", "the PR")
    rc, out = _gate(r, base)
    assert rc == 0, f"the PR went red for a file it did not touch:\n{out}"
    assert "test_on_main.py" in out, "the base's finding must still be printed, not hidden"


def test_an_accented_filename_on_main_does_not_turn_the_scoping_off(tmp_path):
    """#608 review: `git ls-tree` C-quotes a non-ASCII path, so one accented file on
    the base read as missing from the export and nothing was demoted."""
    import capability_manifest  # noqa: E402
    r = tmp_path / "repo"
    (r / "q-system/.q-system/scripts").mkdir(parents=True)
    capability_manifest.explode(r, {"schema_version": 1, "expected_tests": [], "required_data": [],
                                    "skeleton_only": [], "declared_inert": [], "uncovered_known": []})
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "LC_ALL": "C"}

    def git(*a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", *a],
                              cwd=r, env=env, check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q", "-b", "main")
    (r / "q-system/.q-system/scripts/test_on_main.py").write_text("import sys; sys.exit(0)\n")
    (r / "caf\u00e9.md").write_text("accented\n")
    git("add", "-A")
    git("commit", "-q", "-m", "main")
    base = git("rev-parse", "HEAD")
    (r / "README.md").write_text("an unrelated change\n")
    git("add", "-A")
    git("commit", "-q", "-m", "the PR")
    rc, out = _gate(r, base)
    assert rc == 0, f"one accented filename on main reddened an unrelated PR:\n{out}"


def test_a_finding_the_pr_adds_still_fails_it(gate_repo):
    r, base, git = gate_repo
    (r / "q-system/.q-system/scripts/test_from_pr.py").write_text("import sys; sys.exit(0)\n")
    git("add", "-A")
    git("commit", "-q", "-m", "the PR adds an undeclared test")
    rc, out = _gate(r, base)
    assert rc == 1, f"the PR's own undeclared test passed:\n{out}"
    assert "RED: present-but-undeclared: q-system/.q-system/scripts/test_from_pr.py" in out
    assert "RED: present-but-undeclared: q-system/.q-system/scripts/test_on_main.py" not in out


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
