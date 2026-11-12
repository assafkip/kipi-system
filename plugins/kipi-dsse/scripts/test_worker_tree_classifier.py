"""ASK-4612: a worker tree cut from an instance's origin is sized by the current classifier.

The fleet sync commits the skeleton in an instance's running checkout and never pushes it.
The worker cuts every issue tree from ORIGIN, so the tree's own change-size.py is stale or
absent: on 2026-11-12, 9 of 14 instance remotes had none, and size_class() gave every
worker issue there the strict L depth. linear-worker.sh now exports KIPI_SIZE_CLASSIFIER
(the pinned skeleton's copy) and check_budget.size_class() loads the classifier code from
it, while the diff still comes from the tree.

Every fixture is a scratch skeleton, a scratch instance whose local main is one sync commit
ahead of a bare origin, and a worker-style tree cut from origin with `git worktree add -B`.
"""
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

DSSE = Path(__file__).resolve().parent
ROOT = DSSE.parents[2]
CLASSIFIER = ROOT / "q-system/.q-system/scripts/change-size.py"
WORKER = ROOT / "q-system/.q-system/scripts/linear-worker.sh"
REL = "q-system/.q-system/scripts/change-size.py"
TOOL = "def tool():\n    return 1\n"
SMALL = TOOL + "\n\ndef other():\n    return 7\n"                 # 4 changed lines: S
BIG = "".join(f"V{i} = {i}\n" for i in range(160))               # 160 lines: L
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=cwd,
                       capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    assert r.returncode == 0, r.stderr
    return r.stdout


def _size(tree: Path) -> dict:
    spec = importlib.util.spec_from_file_location("_cb4612", DSSE / "check_budget.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.size_class(tree)


def _fleet(tmp_path: Path, change: dict):
    """(skeleton classifier, instance checkout, worker tree carrying `change`)."""
    skel = tmp_path / "skel"
    (skel / REL).parent.mkdir(parents=True)
    shutil.copy(CLASSIFIER, skel / REL)
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    inst = tmp_path / "inst"
    inst.mkdir()
    _git(inst, "init", "-q", "-b", "main")
    (inst / "scripts").mkdir()
    (inst / "scripts/tool.py").write_text(TOOL)
    _git(inst, "add", "-A")
    _git(inst, "commit", "-qm", "base")
    _git(inst, "remote", "add", "origin", str(origin))
    _git(inst, "push", "-q", "origin", "main")
    # The fleet sync: lands the classifier in the running checkout only, never pushed.
    (inst / REL).parent.mkdir(parents=True)
    shutil.copy(CLASSIFIER, inst / REL)
    _git(inst, "add", "-A")
    _git(inst, "commit", "-qm", "chore: sync q-system from skeleton")
    _git(inst, "fetch", "-q", "origin")
    # A human's uncommitted work in the running checkout, which nothing may touch.
    (inst / "scripts/tool.py").write_text(TOOL + "# human edit\n")
    (inst / "notes.md").write_text("human wip\n")
    tree = tmp_path / "tree"
    _git(inst, "worktree", "add", "-q", "-B", "sana/ask-1", str(tree), "origin/main")
    for rel, text in change.items():
        (tree / rel).write_text(text)
    _git(tree, "add", "-A")
    _git(tree, "commit", "-qm", "the issue's change")
    return skel / REL, inst, tree


def test_origin_is_behind_the_sync_so_the_tree_has_no_classifier(tmp_path):
    _, inst, tree = _fleet(tmp_path, {"scripts/tool.py": SMALL})
    assert not (tree / REL).exists()
    assert _git(inst, "rev-list", "--count", "origin/main..main").strip() == "1"


def test_without_the_pinned_classifier_a_small_tree_diff_is_sized_l(tmp_path, monkeypatch):
    """The defect, kept as a pin: the tree alone cannot size itself."""
    monkeypatch.delenv("KIPI_SIZE_CLASSIFIER", raising=False)
    _, _, tree = _fleet(tmp_path, {"scripts/tool.py": SMALL})
    got = _size(tree)
    assert got["class"] == "L"
    assert "no ASK-1749 classifier" in got["reasons"][0]


def test_the_pinned_classifier_gives_a_small_tree_diff_its_real_class(tmp_path, monkeypatch):
    skel_clf, _, tree = _fleet(tmp_path, {"scripts/tool.py": SMALL})
    monkeypatch.setenv("KIPI_SIZE_CLASSIFIER", str(skel_clf))
    got = _size(tree)
    assert got["class"] == "S", got
    assert got["base"] == "origin/main"


def test_control_a_large_tree_diff_is_still_l_with_the_pinned_classifier(tmp_path, monkeypatch):
    skel_clf, _, tree = _fleet(tmp_path, {"scripts/tool.py": BIG})
    monkeypatch.setenv("KIPI_SIZE_CLASSIFIER", str(skel_clf))
    got = _size(tree)
    assert got["class"] == "L", got
    assert not any("classifier" in r for r in got["reasons"]), got


def test_an_override_that_is_not_a_file_is_l_and_names_itself(tmp_path, monkeypatch):
    _, _, tree = _fleet(tmp_path, {"scripts/tool.py": SMALL})
    (tree / REL).parent.mkdir(parents=True)
    shutil.copy(CLASSIFIER, tree / REL)          # a usable tree copy must NOT be the fallback
    _git(tree, "add", "-A")
    _git(tree, "commit", "-qm", "tree copy")
    monkeypatch.setenv("KIPI_SIZE_CLASSIFIER", str(tmp_path / "gone.py"))
    got = _size(tree)
    assert got["class"] == "L"
    assert "KIPI_SIZE_CLASSIFIER" in got["reasons"][0], got


def test_the_instance_running_checkout_is_left_exactly_as_the_human_left_it(tmp_path, monkeypatch):
    skel_clf, inst, tree = _fleet(tmp_path, {"scripts/tool.py": SMALL})
    before = (_git(inst, "status", "--porcelain=v1", "--untracked-files=all"),
              _git(inst, "rev-parse", "HEAD"), _git(inst, "stash", "list"))
    monkeypatch.setenv("KIPI_SIZE_CLASSIFIER", str(skel_clf))
    _size(tree)
    after = (_git(inst, "status", "--porcelain=v1", "--untracked-files=all"),
             _git(inst, "rev-parse", "HEAD"), _git(inst, "stash", "list"))
    assert after == before
    assert " M scripts/tool.py" in before[0] and "?? notes.md" in before[0]


def _worker_block() -> str:
    lines = WORKER.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if "SIZE CLASSIFIER FROM THE PINNED SKELETON" in l)
    end = next(i for i in range(start, len(lines)) if lines[i] == "fi")
    return "\n".join(lines[start:end + 1])


def _run_block(skel: Path) -> str:
    env = {k: v for k, v in os.environ.items() if k != "KIPI_SIZE_CLASSIFIER"}
    # printenv is a child process: it sees the value only if the block EXPORTS it, which is
    # what the agent's Bash needs. A plain assignment would print here through $VAR.
    script = f'SKEL={str(skel)!r}\n{_worker_block()}\nprintenv KIPI_SIZE_CLASSIFIER || true'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.rstrip("\n")


def test_the_worker_exports_the_pinned_skeleton_classifier(tmp_path):
    skel = tmp_path / "skel"
    (skel / REL).parent.mkdir(parents=True)
    shutil.copy(CLASSIFIER, skel / REL)
    assert _run_block(skel) == str(skel / REL)


def test_the_worker_exports_nothing_when_the_skeleton_has_no_classifier(tmp_path):
    assert _run_block(tmp_path) == ""
