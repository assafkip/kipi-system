"""The bypass_check registered at close must have RUN, not merely been recorded.

sp-50db1764 (blocker): `_enforce_spine_contract` called
`prd_runner.gate_register(...)` at close WITHOUT executing the command, so any
issue could append a permanently-red standing gate into .prd-os/gates.jsonl --
a registry that only grows and has no hand-clear. Measured across 64 open
issue specs: of the 6 whose bypass_check target file exists today, 2 exit 5
(pytest collected nothing). A check that cannot fail makes every green in this
registry untrustworthy.

Run: python3 test_bypass_check_runs_at_close.py   (also discoverable by pytest)
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

_MARKER = (
    "<!-- generated-by: prd_split.py prd=prd-fixture finding=finding-fixture "
    "at=2026-04-20T00:00:00Z -->"
)


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _runner(repo, *args):
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    return subprocess.run([sys.executable, str(RUNNER), *args],
                          cwd=str(repo), capture_output=True, text=True, env=env)


def _review_artifact(repo, kind: str = "standard") -> str:
    d = Path(repo) / ".prd-os/reviews"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{kind}.md"
    f.write_text(f"# {kind} review\nVERDICT: APPROVE\nno findings\n")
    return str(f)


def _write_spec(repo, issue_id, bypass_check):
    issues = repo / ".prd-os" / "issues"
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
        f"bypass_check: \"{bypass_check}\"\n"
        "---\n\n"
        f"{_MARKER}\n\nFixture.\n"
    )


def _drive_close(repo, issue_id):
    _runner(repo, "load", issue_id)
    _runner(repo, "approve")
    _runner(repo, "verify")
    _runner(repo, "triage")
    _runner(repo, "record-review", "standard")
    _runner(repo, "complete-review", "standard",
            "--verdict", "approve",
            "--evidence-file", _review_artifact(repo, "standard"))
    _runner(repo, "record-review", "adversarial")
    _runner(repo, "complete-review", "adversarial",
            "--verdict", "approve",
            "--evidence-file", _review_artifact(repo, "adversarial"))
    return _runner(repo, "close")


def _gate_rows(repo):
    path = Path(repo) / ".prd-os" / "gates.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def _setup(tmp):
    repo = Path(tmp)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("# t\n")
    # `_enforce_spine_contract` imports prd_runner from
    # <repo>/plugins/prd-os/scripts; a fixture without it fails registration
    # for an environmental reason and every assertion below would pass or fail
    # for the wrong one. Mirror the production layout.
    shutil.copytree(HERE.parent.parent / "prd-os" / "scripts",
                    repo / "plugins" / "prd-os" / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (repo / "plugins" / ".gitkeep").write_text("")
    prd = repo / ".prd-os"
    prd.mkdir(exist_ok=True)
    (prd / "config.json").write_text(json.dumps({
        "config_schema_version": 1,
        "issues_dir": ".prd-os/issues",
        "state_dir": ".claude/state",
    }))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_close_refuses_when_bypass_check_fails():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup(tmp)
        _write_spec(repo, "bypass-red",
                    'python3 -c \\"import sys; sys.exit(3)\\"')
        proc = _drive_close(repo, "bypass-red")
        assert proc.returncode != 0, (
            "close succeeded while its bypass_check exited 3 — a gate was "
            f"registered for a command that never ran green\n{proc.stdout}")
        assert "3" in proc.stderr, proc.stderr
        assert _gate_rows(repo) == [], (
            "a REFUSED close still appended to the permanent gate registry"
        )
        spec = (repo / ".prd-os/issues/bypass-red.md").read_text()
        assert "status: closed" not in spec, (
            f"the spec flipped to closed on a refused close:\n{spec[:300]}")


def test_close_names_rc5_collected_nothing_distinctly():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup(tmp)
        _write_spec(repo, "bypass-empty",
                    'python3 -c \\"import sys; sys.exit(5)\\"')
        proc = _drive_close(repo, "bypass-empty")
        assert proc.returncode != 0, (
            "close succeeded while its bypass_check exited 5")
        combined = proc.stdout + proc.stderr
        assert "5" in combined, (
            f"rc=5 refusal does not name the code, so it reads like rc=1: {combined}")


def test_close_registers_the_gate_only_after_it_ran_green():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup(tmp)
        _write_spec(repo, "bypass-green", 'python3 -c \\"print(1)\\"')
        proc = _drive_close(repo, "bypass-green")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        rows = [r for r in _gate_rows(repo) if r["issue_id"] == "bypass-green"]
        assert rows, "green bypass_check was never registered"
        assert rows[0]["command"] == 'python3 -c "print(1)"', rows[0]
        import hashlib
        expected = hashlib.sha256(
            rows[0]["command"].encode()).hexdigest()[:8]
        assert rows[0]["gate_id"] == f"bypass-green-{expected}", rows[0]


if __name__ == "__main__":
    test_close_refuses_when_bypass_check_fails()
    test_close_names_rc5_collected_nothing_distinctly()
    test_close_registers_the_gate_only_after_it_ran_green()
    print("bypass-check-runs-at-close tests: PASS")
