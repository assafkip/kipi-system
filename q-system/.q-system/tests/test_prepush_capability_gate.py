"""The pre-push step runs the REAL capability gate on each PUSHED commit.

Reproducer for ASK-4814 (rca-pr794-round-cap-2026-11-12.md, root cause #1).
PR #794 added startup_census.py with no caller and no declared_inert entry. CI
reported `inert-engine` 21 to 23 minutes after each of three pushes, while the
same finding takes about 17 seconds to compute locally. Nothing ran it before a
push: lefthook.yml had no pre-push section.

No stub anywhere. Each case builds a throwaway clone of this repo's HEAD, so the
gate judges the real manifest and the real wiring surfaces, and runs the real
pre-push script, which runs the real capability-gate.py. The clone is its own
repo (not a worktree), so the founder's spillover ledger is never read.

The script is fed git's pre-push stdin by hand, the same lines lefthook passes
with `use_stdin: true` (probed with lefthook 2.1.6, 2026-11-12).
"""
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PREPUSH = REPO / "q-system/.q-system/scripts/prepush-capability-gate.sh"
PROBE = "q-system/.q-system/scripts/prepush_probe_engine.py"
STRAY = "q-system/.q-system/scripts/prepush_untracked_stray.py"
ENGINE = "import sys\n\n\ndef main():\n    return 0\n\n\nif __name__ == '__main__':\n    sys.exit(main())\n"
ZERO = "0" * 40


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
    return _git(clone, "rev-parse", "HEAD").strip()


def _branch_line(sha, ref="refs/heads/topic"):
    return f"{ref} {sha} {ref} {ZERO}\n"


def _prepush(clone, stdin):
    return subprocess.run(["bash", str(PREPUSH)], cwd=str(clone), env=_env(), input=stdin,
                          capture_output=True, text=True, timeout=200)


def _worktrees(clone):
    return _git(clone, "worktree", "list", "--porcelain").count("worktree ")


@pytest.fixture(scope="module")
def clone_red_then_green(tmp_path_factory):
    """Two commits on top of HEAD: RED adds an undeclared engine, GREEN adds its
    declared_inert entry. The working tree is left on GREEN."""
    clone = _clone_of_head(tmp_path_factory.mktemp("prepush"))
    red = _commit(clone, PROBE, ENGINE, mode=0o755)
    frag = "q-system/.q-system/capability/declared_inert/" + PROBE.replace("/", "__") + ".json"
    entry = {"path": PROBE, "reason": "test probe (ASK-4814)", "spillover_id": "sp-test"}
    green = _commit(clone, frag, json.dumps(entry, indent=1) + "\n")
    return clone, red, green


def test_a_pushed_undeclared_engine_refuses_the_push(clone_red_then_green):
    """The PR #794 shape, pushed while the working tree sits on a GREEN commit:
    the commit named on stdin is judged, not the working tree."""
    clone, red, _ = clone_red_then_green
    run = _prepush(clone, _branch_line(red))
    out = run.stdout + run.stderr
    assert run.returncode == 1, out
    assert f"RED: inert-engine: {PROBE} has no reference on any wiring surface" in out, out
    assert "capability-gate: RED (1)" in out, out
    assert f"REFUSED {red[:12]}" in out, out
    assert _worktrees(clone) == 1, "the temp worktree was left behind"


def test_its_declared_inert_entry_passes_despite_an_untracked_stray(clone_red_then_green):
    """The fix PR #794 shipped, pushed from a tree that also holds an untracked
    undeclared script. The gate walks files on disk, so judging the working
    tree would refuse this push for a file the push does not carry."""
    clone, _, green = clone_red_then_green
    stray = clone / STRAY
    stray.write_text(ENGINE)
    stray.chmod(0o755)
    try:
        run = _prepush(clone, _branch_line(green))
    finally:
        stray.unlink()
    out = run.stdout + run.stderr
    assert run.returncode == 0, out
    assert "capability-gate: GREEN" in out, out
    # A pass prints the verdict, not the gate's ~12 KB of notes: every agent
    # push carries this output into its context.
    assert "DECLARED-INERT" not in out, out
    assert STRAY not in out, out
    assert _worktrees(clone) == 1, "the temp worktree was left behind"


def test_a_delete_and_a_tag_push_judge_nothing(clone_red_then_green):
    """A branch delete carries no commit, and validate.yml never runs on a tag.
    Neither may cost a gate run, even when the tag names the RED commit."""
    clone, red, _ = clone_red_then_green
    stdin = f"(delete) {ZERO} refs/heads/gone {red}\n" + _branch_line(red, "refs/tags/v1")
    run = _prepush(clone, stdin)
    out = run.stdout + run.stderr
    assert run.returncode == 0, out
    assert "nothing to judge" in run.stderr, out
    assert "capability-gate" not in out, out


def test_no_origin_main_skips_loudly_and_never_blocks(tmp_path):
    """A repo with no origin/main has no base to scope to. The step says so and
    lets the push through: CI still runs the full gate on the pushed head."""
    clone = _clone_of_head(tmp_path)
    head = _git(clone, "rev-parse", "HEAD").strip()
    _git(clone, "update-ref", "-d", "refs/remotes/origin/main")
    run = _prepush(clone, _branch_line(head))
    assert run.returncode == 0, run.stdout + run.stderr
    assert f"capability pre-push: SKIPPED {head[:12]}" in run.stderr


def test_an_instance_is_not_judged(tmp_path):
    """kipi update ships this script to every instance. With no
    instance-registry.json at the top it exits 0 before reading stdin."""
    clone = _clone_of_head(tmp_path)
    _git(clone, "rm", "-q", "instance-registry.json")
    _git(clone, "commit", "-q", "--no-verify", "-m", "be an instance")
    red = _commit(clone, PROBE, ENGINE, mode=0o755)
    run = _prepush(clone, _branch_line(red))
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stdout + run.stderr == ""


def test_lefthook_pre_push_runs_this_script_with_stdin():
    """The wiring itself. Without `use_stdin: true` lefthook hands the script an
    empty stdin, and every push would pass as "nothing to judge"."""
    text = (REPO / "lefthook.yml").read_text()
    m = re.search(r"(?ms)^pre-push:[ \t]*\n(.*?)(?=^[A-Za-z][\w-]*:|\Z)", text)
    assert m, "lefthook.yml has no top-level pre-push section"
    code = [ln for ln in m.group(1).splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]
    run_re = re.compile(r"(\s*)run:\s*bash q-system/\.q-system/scripts/prepush-capability-gate\.sh\s*$")
    hits = [i for i, ln in enumerate(code) if run_re.match(ln)]
    assert len(hits) == 1, f"expected one pre-push run line for the script, got {len(hits)}"
    indent = len(run_re.match(code[hits[0]]).group(1))
    start = hits[0]
    while start > 0 and len(code[start - 1]) - len(code[start - 1].lstrip()) >= indent:
        start -= 1
    end = hits[0] + 1
    while end < len(code) and len(code[end]) - len(code[end].lstrip()) >= indent:
        end += 1
    block = code[start:end]
    assert any(re.match(r"\s*use_stdin:\s*true\s*$", ln) for ln in block), block
