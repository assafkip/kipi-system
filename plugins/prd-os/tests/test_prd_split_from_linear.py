"""Tests for `prd_split.py --from-linear` (ASK-214).

A Linear issue has no parent PRD, so before this mode existed no legitimate
issue spec could be produced for Linear work: `issue_runner.py load` refused
every candidate on provenance, `close` could never run, and the PR receipt gate
therefore blocked 100% of its target population forever.

These tests pin the two halves of the fix:
  1. the generator turns a Definition of Ready into a spec the REAL issue
     runner accepts (no forged marker, no weakened MARKER_RE);
  2. a thin DoR is refused with the issue named, rather than papered over with
     an empty allowed_files that would make `scope` enforce nothing.

Plus the regression pin that matters most: a pre-existing PRD-manifest
invocation still renders byte-identical output.

Runnable two ways -- `pytest` collects it, and `python3 <this file>` shells
pytest on itself so the capability manifest's python3 runner really executes
the suite instead of importing it and passing silently.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
ISSUE_RUNNER = REPO_ROOT / "plugins/kipi-dsse/scripts/issue_runner.py"

DOR = """Some prose above the DoR.

## Definition of Ready

- **Outcome:** the widget stops dropping frames on resize.
- **Files:** `src/widget.py`, `tests/test_widget.py` (new)
- **Check:** `python3 -m pytest tests/test_widget.py -q`
- **Blast radius:** skeleton-only, no fleet propagation.
- **Not doing:** the renderer rewrite, `src/renderer.py`, `converge.sh`

## Acceptance criteria

- [ ] frames hold at 60fps
"""


def _bootstrap(repo: Path, write_config) -> None:
    write_config(
        repo,
        {
            "config_schema_version": 1,
            "prds_dir": ".prd-os/prds",
            "issues_dir": ".prd-os/issues",
            "findings_dir": ".prd-os/findings",
            "state_dir": ".claude/state",
        },
    )


def _payload(repo: Path, *, description: str, title: str = "Fix the widget") -> str:
    path = repo / "linear-payload.json"
    path.write_text(json.dumps({
        "identifier": "ASK-999",
        "title": title,
        "description": description,
    }))
    return str(path)


def _run_issue_runner(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    return subprocess.run(
        [sys.executable, str(ISSUE_RUNNER), *args],
        cwd=str(repo), capture_output=True, text=True, env=env,
    )


# ---------------------------------------------------------------------------
# happy path: the generated spec is accepted by the real issue runner
# ---------------------------------------------------------------------------


def test_from_linear_creates_spec_named_for_the_issue(
    fake_repo, write_config, run_prd_split
):
    _bootstrap(fake_repo, write_config)
    result = run_prd_split(
        fake_repo, "--from-linear", "ASK-999",
        "--linear-json", _payload(fake_repo, description=DOR),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["prd_id"] == "linear:ASK-999"
    spec = fake_repo / ".prd-os/issues/ASK-999.md"
    assert spec.is_file()
    assert payload["created"] == [".prd-os/issues/ASK-999.md"]


def test_generated_spec_maps_every_dor_field(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    run_prd_split(
        fake_repo, "--from-linear", "ASK-999",
        "--linear-json", _payload(fake_repo, description=DOR),
    )
    text = (fake_repo / ".prd-os/issues/ASK-999.md").read_text()
    assert "id: ASK-999" in text
    assert "title: Fix the widget" in text
    assert "  - src/widget.py" in text
    assert "  - tests/test_widget.py" in text
    assert "  - python3 -m pytest tests/test_widget.py -q" in text
    # Not doing -> disallowed. A basename is widened so the deny can bite;
    # `scope` fnmatches repo-relative paths, so bare `converge.sh` would only
    # ever match a repo-root file.
    assert "  - src/renderer.py" in text
    assert "  - **/converge.sh" in text
    # Outcome -> the Acceptance body.
    assert "the widget stops dropping frames on resize." in text
    # Prose in the Not-doing bullet must not become a path.
    assert "renderer rewrite" not in text


def test_marker_is_honest_and_conforming(fake_repo, write_config, run_prd_split):
    """The emitter really is prd_split.py, so the marker keeps saying so.

    Pinned against issue_runner's OWN MARKER_RE, imported rather than copied:
    a private copy here is how a gate and its producer drift apart.
    """
    _bootstrap(fake_repo, write_config)
    run_prd_split(
        fake_repo, "--from-linear", "ASK-999",
        "--linear-json", _payload(fake_repo, description=DOR),
    )
    text = (fake_repo / ".prd-os/issues/ASK-999.md").read_text()
    marker = next(
        line.strip() for line in text.splitlines()
        if line.strip().startswith("<!-- generated-by:")
    )
    sys.path.insert(0, str(ISSUE_RUNNER.parent))
    import importlib.util

    spec = importlib.util.spec_from_file_location("dsse_issue_runner", ISSUE_RUNNER)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    matched = runner.MARKER_RE.fullmatch(marker)
    assert matched, marker
    assert matched.group("prd") == "linear:ASK-999"
    assert matched.group("finding") == "linear-dor"
    assert runner._require_marker(text) is None


@pytest.mark.skipif(not ISSUE_RUNNER.is_file(), reason="kipi-dsse not present")
def test_issue_runner_load_accepts_the_generated_spec(
    fake_repo, write_config, run_prd_split
):
    """The blocker, proven gone: `load` refused every Linear spec on provenance."""
    _bootstrap(fake_repo, write_config)
    gen = run_prd_split(
        fake_repo, "--from-linear", "ASK-999",
        "--linear-json", _payload(fake_repo, description=DOR),
    )
    assert gen.returncode == 0, gen.stderr
    loaded = _run_issue_runner(fake_repo, "load", "ASK-999")
    assert loaded.returncode == 0, loaded.stderr
    state = json.loads(loaded.stdout)
    assert state["loaded"] == "ASK-999"
    assert state["allowed_files"] == ["src/widget.py", "tests/test_widget.py"]
    assert state["required_checks"] == ["python3 -m pytest tests/test_widget.py -q"]


@pytest.mark.skipif(not ISSUE_RUNNER.is_file(), reason="kipi-dsse not present")
def test_scope_enforcement_comes_free_with_the_spec(
    fake_repo, write_config, run_prd_split
):
    _bootstrap(fake_repo, write_config)
    run_prd_split(
        fake_repo, "--from-linear", "ASK-999",
        "--linear-json", _payload(fake_repo, description=DOR),
    )
    _run_issue_runner(fake_repo, "load", "ASK-999")
    assert _run_issue_runner(fake_repo, "scope", "src/widget.py").returncode == 0
    denied = _run_issue_runner(fake_repo, "scope", "src/renderer.py")
    assert denied.returncode == 2
    assert "disallowed" in denied.stderr
    outside = _run_issue_runner(fake_repo, "scope", "src/other.py")
    assert outside.returncode == 2


def test_rerun_is_byte_identical(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    args = (
        "--from-linear", "ASK-999",
        "--linear-json", _payload(fake_repo, description=DOR),
    )
    run_prd_split(fake_repo, *args)
    first = (fake_repo / ".prd-os/issues/ASK-999.md").read_text()
    second_run = run_prd_split(fake_repo, *args)
    assert second_run.returncode == 0, second_run.stderr
    assert json.loads(second_run.stdout)["created"] == []
    assert (fake_repo / ".prd-os/issues/ASK-999.md").read_text() == first


def test_refuses_to_clobber_a_differing_spec(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    spec = fake_repo / ".prd-os/issues/ASK-999.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("hand-written, do not lose me\n")
    result = run_prd_split(
        fake_repo, "--from-linear", "ASK-999",
        "--linear-json", _payload(fake_repo, description=DOR),
    )
    assert result.returncode == 2
    assert "refusing to clobber" in result.stderr
    assert spec.read_text() == "hand-written, do not lose me\n"


def test_dry_run_writes_nothing(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    result = run_prd_split(
        fake_repo, "--from-linear", "ASK-999", "--dry-run",
        "--linear-json", _payload(fake_repo, description=DOR),
    )
    assert result.returncode == 0, result.stderr
    assert not (fake_repo / ".prd-os/issues/ASK-999.md").exists()


# ---------------------------------------------------------------------------
# a thin DoR is refused, with the issue named
# ---------------------------------------------------------------------------


def test_missing_files_line_is_refused_and_names_the_issue(
    fake_repo, write_config, run_prd_split
):
    """13 of 56 worker-READY issues carry no `**Files:**`; they cannot produce a
    diff, so converge exits on an empty PR. Refusing here makes that readable."""
    _bootstrap(fake_repo, write_config)
    dor = DOR.replace("- **Files:** `src/widget.py`, `tests/test_widget.py` (new)\n", "")
    result = run_prd_split(
        fake_repo, "--from-linear", "ASK-999",
        "--linear-json", _payload(fake_repo, description=dor),
    )
    assert result.returncode != 0
    assert "ASK-999" in result.stderr
    assert "**Files:**" in result.stderr
    assert not (fake_repo / ".prd-os/issues/ASK-999.md").exists()


@pytest.mark.parametrize("value", [
    "unknown - needs a recon pass",
    "TBD",
    "n/a until the recon pass lands",
])
def test_unknown_files_is_refused(fake_repo, write_config, run_prd_split, value):
    _bootstrap(fake_repo, write_config)
    dor = DOR.replace(
        "- **Files:** `src/widget.py`, `tests/test_widget.py` (new)",
        f"- **Files:** {value}",
    )
    result = run_prd_split(
        fake_repo, "--from-linear", "ASK-999",
        "--linear-json", _payload(fake_repo, description=dor),
    )
    assert result.returncode != 0
    assert "ASK-999" in result.stderr
    assert not (fake_repo / ".prd-os/issues/ASK-999.md").exists()


def test_prose_only_files_line_is_refused(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    dor = DOR.replace(
        "- **Files:** `src/widget.py`, `tests/test_widget.py` (new)",
        "- **Files:** wherever the resize handler lives",
    )
    result = run_prd_split(
        fake_repo, "--from-linear", "ASK-999",
        "--linear-json", _payload(fake_repo, description=dor),
    )
    assert result.returncode != 0
    assert "ASK-999" in result.stderr


def test_missing_check_line_is_refused(fake_repo, write_config, run_prd_split):
    """An empty required_checks would let an issue be 'verified' against
    nothing -- the same silent bypass the PRD path already refuses."""
    _bootstrap(fake_repo, write_config)
    dor = DOR.replace("- **Check:** `python3 -m pytest tests/test_widget.py -q`\n", "")
    result = run_prd_split(
        fake_repo, "--from-linear", "ASK-999",
        "--linear-json", _payload(fake_repo, description=dor),
    )
    assert result.returncode != 0
    assert "ASK-999" in result.stderr
    assert "Check" in result.stderr


def test_missing_dor_section_is_refused(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    result = run_prd_split(
        fake_repo, "--from-linear", "ASK-999",
        "--linear-json", _payload(fake_repo, description="just a title, no DoR"),
    )
    assert result.returncode != 0
    assert "ASK-999" in result.stderr
    assert "Definition of Ready" in result.stderr


def test_path_in_both_files_and_not_doing_is_refused(
    fake_repo, write_config, run_prd_split
):
    """`scope` denies before it allows, so such a spec would block its own work."""
    _bootstrap(fake_repo, write_config)
    dor = DOR.replace(
        "- **Not doing:** the renderer rewrite, `src/renderer.py`, `converge.sh`",
        "- **Not doing:** `src/widget.py`",
    )
    result = run_prd_split(
        fake_repo, "--from-linear", "ASK-999",
        "--linear-json", _payload(fake_repo, description=dor),
    )
    assert result.returncode != 0
    assert "ASK-999" in result.stderr
    assert "src/widget.py" in result.stderr


def test_bad_issue_id_is_refused_before_any_fetch(
    fake_repo, write_config, run_prd_split
):
    """The id is also the spec filename, so its pattern is the traversal guard."""
    _bootstrap(fake_repo, write_config)
    for bad in ("../../etc/passwd", "ask-999", "ASK999", ""):
        result = run_prd_split(fake_repo, "--from-linear", bad)
        assert result.returncode == 2, bad
        assert "Linear issue id" in result.stderr, bad


def test_linear_json_without_from_linear_is_refused(
    fake_repo, write_config, run_prd_split
):
    _bootstrap(fake_repo, write_config)
    result = run_prd_split(fake_repo, "--linear-json", "whatever.json")
    assert result.returncode == 2
    assert "--from-linear" in result.stderr


def test_from_linear_and_prd_id_are_mutually_exclusive(
    fake_repo, write_config, run_prd_split
):
    _bootstrap(fake_repo, write_config)
    result = run_prd_split(
        fake_repo, "--from-linear", "ASK-999", "--prd-id", "prd-x"
    )
    assert result.returncode == 2
    assert "mutually exclusive" in result.stderr


# ---------------------------------------------------------------------------
# regression pin: the pre-existing PRD path is untouched
# ---------------------------------------------------------------------------


LEGACY_GOLDEN = """---
id: issue-a
title: Issue A
status: open
priority: p1
parent_prd: prd-legacy
allowed_files:
  - src/a.py
disallowed_files: []
required_checks:
  - pytest -q
required_reviews: []
deliverables_count: 1
---
<!-- generated-by: prd_split.py prd=prd-legacy finding=finding-a at=AT -->

# Issue A

## Context

Parent PRD: `.prd-os/prds/prd-legacy.md`

## Acceptance

<!-- fill in -->

## Deliverables

<!-- Check each box when it ships; close refuses until checked count equals \
deliverables_count (locked at issue-start). -->
- [ ] Issue A
"""


def test_legacy_prd_invocation_is_byte_identical(
    fake_repo, write_config, run_prd_split
):
    """An additive flag must not move one byte of the PRD path's output."""
    _bootstrap(fake_repo, write_config)
    prds = fake_repo / ".prd-os/prds"
    prds.mkdir(parents=True, exist_ok=True)
    manifest = [{
        "id": "issue-a",
        "title": "Issue A",
        "finding_id": "finding-a",
        "allowed_files": ["src/a.py"],
        "required_checks": ["pytest -q"],
    }]
    (prds / "prd-legacy.md").write_text(
        "---\nid: prd-legacy\ntitle: legacy\nstatus: approved\n---\n\n"
        "## Issues\n\n```json\n" + json.dumps(manifest, indent=2) + "\n```\n"
    )
    result = run_prd_split(fake_repo, "--prd-id", "prd-legacy")
    assert result.returncode == 0, result.stderr
    produced = (fake_repo / ".prd-os/issues/issue-a.md").read_text()
    normalized = re.sub(r"at=\S+ -->", "at=AT -->", produced)
    assert normalized == LEGACY_GOLDEN


if __name__ == "__main__":
    # The capability manifest runs expected_tests as `python3 <path>`. Importing
    # a pytest module that way collects nothing and exits 0 -- a silent pass is
    # exactly the absence this repo's capability gate exists to catch.
    sys.exit(subprocess.run(
        [sys.executable, "-m", "pytest", str(Path(__file__).resolve()), "-q"],
        cwd=str(PLUGIN_ROOT.parent.parent),
    ).returncode)
