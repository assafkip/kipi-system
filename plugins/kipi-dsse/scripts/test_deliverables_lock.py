"""Deliverable-count lock (dsse-deliverable-count-lock, prd-fable-discipline).

The spec promises N deliverables (`deliverables_count`, locked at load like
allowed_files); close counts checked `- [x]` lines under `## Deliverables`
and REFUSES on mismatch — the taste-skill lesson turned deterministic: a
promised-N/delivered-fewer gap must fail a gate, not rely on prose.

Compat contract (finding-3 of the PRD review): a spec WITHOUT the field
closes under the old rules, check skipped entirely; a malformed value is
rejected at LOAD (issue-start), not discovered at closeout.

Run: python3 test_deliverables_lock.py   (also discoverable by pytest)
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

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


def _write_spec(repo, issue_id, count=None, deliverables_md=""):
    issues = repo / ".prd-os" / "issues"
    issues.mkdir(parents=True, exist_ok=True)
    count_line = f"deliverables_count: {count}\n" if count is not None else ""
    (issues / f"{issue_id}.md").write_text(
        "---\n"
        f"id: {issue_id}\n"
        f"title: {issue_id} fixture\n"
        "status: open\n"
        "priority: p0\n"
        "allowed_files:\n  - src/tracked.py\n"
        "disallowed_files: []\n"
        # `verify` refuses an empty check list (a receipt cannot attest that
        # nothing ran), so the fixture carries a real passing check.
        "required_checks:\n  - python3 -c \"print('ok')\"\n"
        "required_reviews: []\n"
        f"{count_line}"
        "---\n\n"
        f"{_MARKER}\n\nFixture.\n"
        f"{deliverables_md}"
    )


def _drive_close(repo, issue_id):
    _runner(repo, "load", issue_id)
    _runner(repo, "approve")
    # Receipts are earned, not stamped: `mark <receipt>` was removed
    # 2026-08-05 (it recorded a claim it never computed).
    _runner(repo, "verify")
    _runner(repo, "triage")
    _runner(repo, "record-review", "standard")
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
    return repo


def _commit_all(repo):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")


def test_load_rejects_malformed_count():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup(tmp)
        for bad in (0, -3, '"three"'):
            _write_spec(repo, "issue-bad", count=bad)
            _commit_all(repo)
            r = _runner(repo, "load", "issue-bad")
            assert r.returncode == 2, f"count={bad}: {r.stdout}{r.stderr}"
            assert "deliverables_count" in r.stderr, r.stderr


def test_close_refuses_on_count_mismatch_then_passes_when_met():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup(tmp)
        _write_spec(
            repo, "issue-lock", count=2,
            deliverables_md="\n## Deliverables\n- [x] one\n- [ ] two\n",
        )
        _commit_all(repo)
        blocked = _drive_close(repo, "issue-lock")
        assert blocked.returncode == 2, blocked.stdout + blocked.stderr
        assert "deliverables" in blocked.stderr.lower(), blocked.stderr
        assert "2" in blocked.stderr and "1" in blocked.stderr, blocked.stderr

        # check the second box -> close proceeds (issue still loaded)
        spec = repo / ".prd-os/issues/issue-lock.md"
        spec.write_text(spec.read_text().replace("- [ ] two", "- [x] two"))
        _commit_all(repo)
        ok = _runner(repo, "close")
        assert ok.returncode == 0, ok.stdout + ok.stderr


def test_load_rejects_present_but_empty_and_quoted_count():
    """Only an ABSENT key opts out; empty (`deliverables_count:`) and quoted
    (`"2"`) forms are pre-load edit paths around the gate (codex major)."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup(tmp)
        for bad in ("", '"2"'):
            _write_spec(repo, "issue-sneak", count=bad)
            _commit_all(repo)
            r = _runner(repo, "load", "issue-sneak")
            assert r.returncode == 2, f"count={bad!r}: {r.stdout}{r.stderr}"
            assert "deliverables_count" in r.stderr, r.stderr


def test_close_ignores_indented_and_second_section_boxes():
    """A checked nested subtask (indented) or a checked box in a SECOND
    Deliverables section must not satisfy the locked count (codex major)."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup(tmp)
        _write_spec(
            repo, "issue-inject", count=2,
            deliverables_md=(
                "\n## Deliverables\n"
                "- [x] real one\n"
                "  - [x] nested subtask does not count\n"
                "- [ ] real two\n"
                "\n## Notes\n\n## Deliverables\n- [x] injected\n"
            ),
        )
        _commit_all(repo)
        blocked = _drive_close(repo, "issue-inject")
        assert blocked.returncode == 2, blocked.stdout + blocked.stderr
        assert "1 checked" in blocked.stderr, blocked.stderr


def test_approve_leaves_spec_untouched_on_invalid_count():
    """approve validates BEFORE the status flip; a failed approve must not
    leave the spec in-progress (codex major)."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup(tmp)
        _write_spec(repo, "issue-flip", count=2)
        _commit_all(repo)
        _runner(repo, "load", "issue-flip")
        # corrupt the count after load, then approve
        spec = repo / ".prd-os/issues/issue-flip.md"
        spec.write_text(spec.read_text().replace(
            "deliverables_count: 2", "deliverables_count: 0"))
        r = _runner(repo, "approve")
        assert r.returncode == 2, r.stdout + r.stderr
        assert "status: open" in spec.read_text(), "spec was mutated on failure"


def test_close_refuses_when_section_missing_but_count_present():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup(tmp)
        _write_spec(repo, "issue-nosec", count=1)
        _commit_all(repo)
        blocked = _drive_close(repo, "issue-nosec")
        assert blocked.returncode == 2, blocked.stdout + blocked.stderr
        assert "deliverables" in blocked.stderr.lower(), blocked.stderr


def test_compat_spec_without_field_closes_under_old_rules():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _setup(tmp)
        _write_spec(repo, "issue-old", count=None)
        _commit_all(repo)
        ok = _drive_close(repo, "issue-old")
        assert ok.returncode == 0, ok.stdout + ok.stderr


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  [PASS] {fn.__name__}")
    print(f"deliverables-lock self-test: all {len(fns)} cases passed")
