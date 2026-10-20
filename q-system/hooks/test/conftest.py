"""Shared fixtures for this test directory."""
import pytest


@pytest.fixture(autouse=True)
def _not_a_cloud_session(monkeypatch):
    # auto-commit.py commits nothing when CLAUDE_CODE_REMOTE is set
    # (sp-8680be69). Its tests fire the hook with an inherited os.environ, so
    # inside a cloud session (a routine, a cloud PR review) every one of them
    # went red on the marker, not on a defect. Measured: 19 + 6 reds.
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
