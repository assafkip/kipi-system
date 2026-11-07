"""ASK-3829: closes on parallel branches merge clean, and close/verify run in a repo shaped like chief.

Four checks from the ticket's Definition of Ready, each against a temp fixture repo:

1. Two worktrees each close one issue with a bypass_check; both merge into the fixture main
   with no conflict. Before this change both appended a line to `.prd-os/receipts.jsonl` and
   `.prd-os/gates.jsonl` at the same offset, so the second merge conflicted.
2. `issue_runner.py close` registers its gate in a repo with no `plugins/` dir and no hand-set
   PYTHONPATH, from the source layout and from the install-cache layout
   (`cache/<marketplace>/<plugin>/<version>/scripts`). sp-93f41220: chief failed with
   "No module named prd_runner" and was closed twice by hand with a PYTHONPATH.
3. A required check carrying `-q` under a repo whose pytest addopts already carry `-q` gets a
   parsed count. sp-dae00232: pytest at -qq prints no summary line, and verify refused.
4. Done criterion: 20 branches each add one receipt and one gate through the real writers, all 20
   merge into main with no conflict, and the fold returns the 20 new rows plus the legacy rows.

The fixture repos carry no `.gitattributes`. That is GitHub's merge semantics: GitHub does not
run the `merge=union` driver kipi-system's `.gitattributes` sets, so a local merge that a union
driver resolves is still CONFLICTING on the PR page (measured on 37 PRs, capability_manifest.py).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "issue_runner.py"
PRDOS_SCRIPTS = HERE.parents[1] / "prd-os" / "scripts"

sys.path.insert(0, str(HERE))
import ledger_fragments  # noqa: E402

_MARKER = ("<!-- generated-by: prd_split.py prd=prd-fixture finding=finding-fixture "
           "at=2026-04-20T00:00:00Z -->")
LEGACY_RECEIPTS = [
    {"issue_id": "old-1", "closed_at": "2026-09-01T00:00:00Z", "commit_sha": "a" * 40},
    {"issue_id": "old-2", "closed_at": "2026-09-02T00:00:00Z", "commit_sha": "b" * 40},
]
LEGACY_GATES = [
    {"gate_id": "old-1-deadbeef", "prd_id": "prd-old", "issue_id": "old-1",
     "command": "true", "lifecycle": "regression", "registered_at": "2026-09-01T00:00:00Z"},
]


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _clean_env(repo):
    env = dict(os.environ)
    for leak in ("PYTHONPATH", "KIPI_REAL_PATH_LOG", "PYTEST_PLUGINS", "PYTEST_ADDOPTS"):
        env.pop(leak, None)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    return env


def _runner(repo, *args, runner=RUNNER):
    # No PYTHONPATH on purpose: the runner has to find prd-os itself (sp-93f41220).
    return subprocess.run([sys.executable, str(runner), *args], cwd=str(repo),
                          capture_output=True, text=True, env=_clean_env(repo))


def _review_artifact(repo, kind):
    d = Path(repo) / ".prd-os" / "reviews"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{kind}.md"
    f.write_text(f"# {kind} review\nVERDICT: APPROVE\nno findings\n")
    return str(f)


def _write_spec(repo, issue_id, check='python3 -c \\"print(1)\\"'):
    issues = Path(repo) / ".prd-os" / "issues"
    issues.mkdir(parents=True, exist_ok=True)
    (issues / f"{issue_id}.md").write_text(
        "---\n"
        f"id: {issue_id}\n"
        f"title: {issue_id} fixture\n"
        "status: open\n"
        "priority: p0\n"
        "allowed_files:\n  - README.md\n"
        "disallowed_files: []\n"
        "required_checks:\n  - python3 -c \"print('ok')\"\n"
        "required_reviews: []\n"
        f"bypass_check: \"{check}\"\n"
        "---\n\n"
        f"{_MARKER}\n\nFixture.\n")


def _drive_close(repo, issue_id, runner=RUNNER):
    for step in (["load", issue_id], ["approve"], ["verify"], ["triage"],
                 ["record-review", "standard"]):
        _runner(repo, *step, runner=runner)
    _runner(repo, "complete-review", "standard", "--verdict", "approve",
            "--evidence-file", _review_artifact(repo, "standard"), runner=runner)
    _runner(repo, "record-review", "adversarial", runner=runner)
    _runner(repo, "complete-review", "adversarial", "--verdict", "approve",
            "--evidence-file", _review_artifact(repo, "adversarial"), runner=runner)
    return _runner(repo, "close", runner=runner)


def _init_repo(root, *, plugins_copy):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "README.md").write_text("# t\n")
    if plugins_copy:
        shutil.copytree(PRDOS_SCRIPTS, root / "plugins" / "prd-os" / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
    prd = root / ".prd-os"
    prd.mkdir(exist_ok=True)
    (prd / "config.json").write_text(json.dumps({
        "config_schema_version": 1, "issues_dir": ".prd-os/issues",
        "findings_dir": ".prd-os/findings", "state_dir": ".claude/state",
        "receipts_path": ".prd-os/receipts.jsonl"}))
    (prd / "receipts.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in LEGACY_RECEIPTS))
    (prd / "gates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in LEGACY_GATES))
    # __pycache__ as every real repo ignores it: CI writes bytecode, and two worktrees that each
    # `git add -A` their own .pyc conflict on binaries that have nothing to do with the ledgers.
    (root / ".gitignore").write_text(".claude/state/\n__pycache__/\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _rows(ledger):
    return [json.loads(text) for _src, _n, text in ledger_fragments.iter_lines(ledger)
            if text.strip()]


# --- check 1: two worktrees, two closes, two clean merges -----------------------------------

def test_two_worktrees_each_close_one_issue_and_both_merge_clean():
    with tempfile.TemporaryDirectory() as tmp:
        main = _init_repo(Path(tmp) / "main", plugins_copy=True)
        for issue in ("iss-a", "iss-b"):
            _write_spec(main, issue)
        _git(main, "add", "-A")
        _git(main, "commit", "-q", "-m", "specs")
        trees = {}
        for issue in ("iss-a", "iss-b"):
            tree = Path(tmp) / f"wt-{issue}"
            added = _git(main, "worktree", "add", "-q", "-b", f"br-{issue}", str(tree), "main")
            assert added.returncode == 0, added.stderr
            closed = _drive_close(tree, issue)
            assert closed.returncode == 0, f"close {issue} failed:\n{closed.stdout}\n{closed.stderr}"
            _git(tree, "add", "-A")
            committed = _git(tree, "commit", "-q", "-m", f"close {issue}")
            assert committed.returncode == 0, committed.stdout + committed.stderr
            trees[issue] = tree
        for issue in ("iss-a", "iss-b"):
            merged = _git(main, "merge", "--no-ff", "-q", "-m", f"merge {issue}", f"br-{issue}")
            assert merged.returncode == 0, (
                f"merging the {issue} close into main CONFLICTED:\n{merged.stdout}{merged.stderr}\n"
                f"{_git(main, 'diff', '--name-only', '--diff-filter=U').stdout}")
        receipts = _rows(main / ".prd-os" / "receipts.jsonl")
        closed_ids = [r["issue_id"] for r in receipts if r.get("closed_at")]
        assert closed_ids[:2] == ["old-1", "old-2"], closed_ids
        assert sorted(closed_ids[2:]) == ["iss-a", "iss-b"], closed_ids
        gates = _rows(main / ".prd-os" / "gates.jsonl")
        assert sorted(g["issue_id"] for g in gates) == ["iss-a", "iss-b", "old-1"], gates
        legacy = (main / ".prd-os" / "receipts.jsonl").read_text()
        assert legacy == "".join(json.dumps(r, sort_keys=True) + "\n" for r in LEGACY_RECEIPTS), (
            "a close rewrote the legacy receipts ledger; history is read-only")


# --- check 2: close finds prd-os from where the runner is installed --------------------------

def _chief_like(tmp):
    """chief's shape: no plugins/ dir, findings_dir set, pytest addopts carrying -q."""
    root = _init_repo(Path(tmp) / "chief", plugins_copy=False)
    (root / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\naddopts = "-q --no-header"\n')
    _write_spec(root, "chief-1")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "spec")
    return root


def _gate_ids(repo):
    return [g["gate_id"] for g in _rows(Path(repo) / ".prd-os" / "gates.jsonl")]


def test_close_registers_its_gate_in_a_repo_with_no_plugins_dir():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _chief_like(tmp)
        assert not (repo / "plugins").exists()
        closed = _drive_close(repo, "chief-1")
        assert closed.returncode == 0, closed.stdout + closed.stderr
        assert "No module named" not in closed.stderr, closed.stderr
        assert any(g.startswith("chief-1-") for g in _gate_ids(repo)), _gate_ids(repo)


def test_close_registers_its_gate_from_the_install_cache_layout():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _chief_like(tmp)
        cache = Path(tmp) / "cache" / "kipi"
        shutil.copytree(HERE, cache / "kipi-dsse" / "9.9.9" / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(PRDOS_SCRIPTS, cache / "prd-os" / "9.9.9" / "scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        # An older install beside it with no prd_runner: the resolver must pick a usable one.
        (cache / "prd-os" / "0.1.0" / "scripts").mkdir(parents=True)
        cached_runner = cache / "kipi-dsse" / "9.9.9" / "scripts" / "issue_runner.py"
        closed = _drive_close(repo, "chief-1", runner=cached_runner)
        assert closed.returncode == 0, closed.stdout + closed.stderr
        assert any(g.startswith("chief-1-") for g in _gate_ids(repo)), _gate_ids(repo)


# --- check 3: -q on top of addopts -q still yields a count ------------------------------------

def _verify_qq(tmp, check):
    """verify one issue whose required check is `check`, in a repo whose addopts carry -q."""
    repo = _init_repo(Path(tmp) / "qq", plugins_copy=False)
    (repo / "pyproject.toml").write_text('[tool.pytest.ini_options]\naddopts = "-q"\n')
    (repo / "tests").mkdir()
    (repo / "tests" / "test_two.py").write_text(
        "def test_one():\n    assert True\n\n\ndef test_two():\n    assert True\n")
    issues = repo / ".prd-os" / "issues"
    issues.mkdir(parents=True, exist_ok=True)
    (issues / "qq-1.md").write_text(
        "---\nid: qq-1\ntitle: qq\nstatus: open\npriority: p0\n"
        "allowed_files:\n  - tests/test_two.py\ndisallowed_files: []\n"
        f"required_checks:\n  - {check}\n"
        f"required_reviews: []\n---\n\n{_MARKER}\n\nFixture.\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "spec")
    for step in (["load", "qq-1"], ["approve"]):
        r = _runner(repo, *step)
        assert r.returncode == 0, r.stdout + r.stderr
    verified = _runner(repo, "verify")
    state = json.loads(_runner(repo, "status").stdout)
    rows = (state.get("verified_green") or {}).get("defined_vs_ran") or []
    return verified, rows


def test_a_dash_q_check_under_addopts_dash_q_gets_a_parsed_count():
    with tempfile.TemporaryDirectory() as tmp:
        verified, rows = _verify_qq(
            tmp, "python3 -m pytest tests/test_two.py -q -p no:cacheprovider")
        assert "printed no count" not in verified.stderr, verified.stderr
        assert rows and rows[0].get("status") == "ok", (rows, verified.stderr)
        assert rows[0].get("ran") == 2 and rows[0].get("defined") == 2, rows


def test_a_check_that_sets_its_own_pythonpath_still_runs_and_counts():
    """PR #621 review, major 1: a check that assigns PYTHONPATH itself (six specs in
    .prd-os/issues do) dropped an injected plugin dir while PYTEST_PLUGINS survived, and pytest
    aborted with "Error importing plugin". Whatever the runner adds must not need an import."""
    with tempfile.TemporaryDirectory() as tmp:
        verified, rows = _verify_qq(
            tmp, "PYTHONPATH=tests python3 -m pytest tests/test_two.py -q -p no:cacheprovider")
        assert "Error importing plugin" not in verified.stdout + verified.stderr, verified.stderr
        assert rows and rows[0].get("status") == "ok", (rows, verified.stderr)
        assert rows[0].get("ran") == 2, rows


# --- check 4 (Done): 20 branches, 20 clean merges, fold = 20 + legacy -------------------------

def _write_through_the_real_writers(repo, n):
    sys.path.insert(0, str(PRDOS_SCRIPTS))
    import issue_runner
    import prd_runner
    from config import load as load_config
    issue_runner._append_receipt(
        Path(repo) / ".prd-os" / "receipts.jsonl",
        {"issue_id": f"par-{n:02d}", "closed_at": f"2026-11-06T00:00:{n:02d}Z",
         "commit_sha": f"{n:040x}"})
    prd_runner.gate_register(load_config(Path(repo)), prd_id="prd-par", issue_id=f"par-{n:02d}",
                             command=f"python3 -c 'print({n})'", lifecycle="regression",
                             protects="fixture")


def _merge_all(repo, order):
    for n in order:
        merged = _git(repo, "merge", "--no-ff", "-q", "-m", f"merge par-{n:02d}", f"par-{n:02d}")
        if merged.returncode != 0:
            return (n, merged.stdout + merged.stderr
                    + _git(repo, "diff", "--name-only", "--diff-filter=U").stdout)
    return None


def test_twenty_branches_each_write_one_row_and_all_twenty_merge_clean():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _init_repo(Path(tmp) / "twenty", plugins_copy=False)
        for n in range(20):
            _git(repo, "checkout", "-q", "-b", f"par-{n:02d}", "main")
            _write_through_the_real_writers(repo, n)
            _git(repo, "add", "-A")
            c = _git(repo, "commit", "-q", "-m", f"par-{n:02d}")
            assert c.returncode == 0, c.stdout + c.stderr
        _git(repo, "checkout", "-q", "main")
        clone = Path(tmp) / "reverse"
        assert subprocess.run(["git", "clone", "-q", str(repo), str(clone)],
                              capture_output=True).returncode == 0
        for n in range(20):
            _git(clone, "branch", "-q", f"par-{n:02d}", f"origin/par-{n:02d}")
        _git(clone, "config", "user.email", "t@example.com")
        _git(clone, "config", "user.name", "Test")

        conflict = _merge_all(repo, range(20))
        assert conflict is None, f"branch par-{conflict[0]:02d} CONFLICTED on merge:\n{conflict[1]}"
        receipts = _rows(repo / ".prd-os" / "receipts.jsonl")
        gates = _rows(repo / ".prd-os" / "gates.jsonl")
        assert len(receipts) == 20 + len(LEGACY_RECEIPTS), len(receipts)
        assert len(gates) == 20 + len(LEGACY_GATES), len(gates)
        assert receipts[:2] == LEGACY_RECEIPTS, "legacy rows must fold first, in file order"
        assert [r["issue_id"] for r in receipts[2:]] == [f"par-{n:02d}" for n in range(20)], (
            "fragments must fold in write order")

        # Deterministic: the same branches merged in the reverse order fold to the same rows.
        assert _merge_all(clone, reversed(range(20))) is None
        assert _rows(clone / ".prd-os" / "receipts.jsonl") == receipts
        assert _rows(clone / ".prd-os" / "gates.jsonl") == gates


# --- the two plugin copies of the chokepoint are one file -------------------------------------

def test_the_two_plugin_copies_of_ledger_fragments_are_byte_identical():
    """prd_runner imports ledger_fragments from sys.modules when issue_runner loaded it first, so
    the kipi-dsse copy is the one that writes gates in a close. Two copies that drift are two
    writers with one name."""
    ours = (HERE / "ledger_fragments.py").read_bytes()
    theirs = (PRDOS_SCRIPTS / "ledger_fragments.py").read_bytes()
    assert ours == theirs, "plugins/kipi-dsse/scripts/ledger_fragments.py drifted from prd-os's copy"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
