"""Self-contained test for the wiring contract at issue close.

Runs the LIVE kipi-dsse issue_runner.py (the copy production invokes via
`${CLAUDE_PLUGIN_ROOT}/scripts/issue_runner.py`), NOT the legacy prd-os copy.
A created-but-never-committed allowed_file must block close; committing it
unblocks; a never-created allowed_file must not block.

Run: python3 test_wiring_contract.py   (also discoverable by pytest)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

def _review_artifact(repo, kind: str = "standard") -> str:
    """A stand-in for the reviewer's own output.

    Fixtures come from producers, and the producer here is "whatever the
    reviewer printed" -- an opaque blob. What the runner asserts about it is
    only that it exists, is non-empty, and hashes stably, so a representative
    blob is the honest fixture rather than a fabricated verdict schema.
    """
    d = Path(repo) / ".prd-os/reviews"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{kind}.md"
    f.write_text(f"# {kind} review\nVERDICT: APPROVE\nno findings\n")
    return str(f)


RUNNER = Path(__file__).resolve().parent / "issue_runner.py"

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


def _write_spec(repo, issue_id, allowed_files):
    issues = repo / ".prd-os" / "issues"
    issues.mkdir(parents=True, exist_ok=True)
    allow = "\n" + "\n".join(f"  - {p}" for p in allowed_files)
    (issues / f"{issue_id}.md").write_text(
        "---\n"
        f"id: {issue_id}\n"
        f"title: {issue_id} fixture\n"
        "status: open\n"
        "priority: p0\n"
        f"allowed_files: {allow}\n"
        "disallowed_files: []\n"
        # A real passing check: `verify` refuses an empty list, because a
        # receipt meaning "the checks ran and passed" must not be issuable
        # when there were none (prd_split.py already refused empty lists at
        # split time for the same reason; this fixture bypasses split).
        "required_checks:\n  - python3 -c \"print('ok')\"\n"
        "required_reviews: []\n"
        "---\n\n"
        f"{_MARKER}\n\nFixture.\n"
    )


def _drive_close(repo, issue_id):
    _runner(repo, "load", issue_id)
    _runner(repo, "approve")
    # Earn the receipts through the verbs that compute them. `mark <receipt>`
    # was removed 2026-08-05: it wrote a receipt on the caller's word, which is
    # the class "code that RECORDS a claim it never COMPUTED". Tests now take
    # the production path, so this precondition is a real one.
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


def _setup(tmp):
    repo = Path(tmp)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / ".prd-os").mkdir(parents=True, exist_ok=True)
    (repo / ".prd-os" / "config.json").write_text(json.dumps({
        "config_schema_version": 1,
        "issues_dir": ".prd-os/issues",
        "state_dir": ".claude/state",
    }))
    src = repo / "src"
    src.mkdir()
    (src / "tracked.py").write_text("x = 1\n")
    (src / "untracked.py").write_text("y = 2\n")
    return repo, src


def test_close_blocks_on_untracked_allowed_file():
    with tempfile.TemporaryDirectory() as tmp:
        repo, src = _setup(tmp)
        _write_spec(repo, "issue-wire", ["src/tracked.py", "src/untracked.py"])
        # commit everything EXCEPT src/untracked.py
        _git(repo, "add", "src/tracked.py", ".prd-os")
        _git(repo, "commit", "-q", "-m", "init")

        blocked = _drive_close(repo, "issue-wire")
        assert blocked.returncode == 2, blocked.stdout + blocked.stderr
        assert "wiring contract failed" in blocked.stderr, blocked.stderr
        assert "src/untracked.py" in blocked.stderr
        assert "src/tracked.py" not in blocked.stderr

        # commit the missing file -> close proceeds
        _git(repo, "add", "src/untracked.py")
        _git(repo, "commit", "-q", "-m", "add file")
        ok = _drive_close(repo, "issue-wire")
        assert ok.returncode == 0, ok.stdout + ok.stderr


def test_close_ignores_never_created_allowed_file():
    with tempfile.TemporaryDirectory() as tmp:
        repo, src = _setup(tmp)
        _write_spec(repo, "issue-glob", ["src/tracked.py", "src/never_made.py"])
        _git(repo, "add", "src/tracked.py", "src/untracked.py", ".prd-os")
        _git(repo, "commit", "-q", "-m", "init")
        ok = _drive_close(repo, "issue-glob")
        assert ok.returncode == 0, ok.stdout + ok.stderr


if __name__ == "__main__":
    test_close_blocks_on_untracked_allowed_file()
    test_close_ignores_never_created_allowed_file()
    print("wiring-contract tests: PASS")
