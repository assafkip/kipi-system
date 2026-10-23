"""One generated spec carries exactly one deliverable PR (ASK-2541).

why: RCA token-burn-recurs-after-gate-2026-10-06 root cause #4. One brief
bundled five jobs (three PRs, a dry run, a review loop) and its agent re-read
about 180k tokens of context on every waiting turn. A spec is what a worker is
briefed from, so prd_split refuses a manifest entry or a Linear DoR that names
more than one PR, and says how to split it.

Red on the pre-fix prd_split: every multi-PR case below exits 0 there.
The single-PR controls pin that the refusal is about PR count, not the word
"PR": a spec that mentions one PR, or a real PR number, still splits.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


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


def _write_prd(repo: Path, prd_id: str, entries: list[dict]) -> None:
    prds = repo / ".prd-os" / "prds"
    prds.mkdir(parents=True, exist_ok=True)
    (prds / f"{prd_id}.md").write_text(
        "---\n"
        f"id: {prd_id}\n"
        "title: Fixture\n"
        "status: approved\n"
        "---\n\n# Fixture\n\n## Issues\n\n"
        "```json\n" + json.dumps(entries, indent=2) + "\n```\n"
    )


def _entry(issue_id: str, **extra) -> dict:
    return {
        "id": issue_id,
        "title": f"{issue_id} fixture",
        "finding_id": f"finding-{issue_id}",
        "allowed_files": ["src/a.py"],
        "required_checks": ["true"],
        "bypass_exempt": "fixture",
        **extra,
    }


def _issues(repo: Path) -> list[Path]:
    d = repo / ".prd-os" / "issues"
    return sorted(d.glob("*.md")) if d.is_dir() else []


MULTI_PR_ENTRIES = {
    "labels-in-acceptance": {
        "acceptance": "PR 1 adds the ledger row. PR 2 adds the channel filter.",
    },
    "counted-in-title": {"title": "Split the meter work into three PRs"},
    "per-item": {"acceptance": "Two fixes, one PR each, in order."},
    "deliverables-each-a-pr": {
        "deliverables": [
            "PR for the ledger row merged",
            "PR for the channel filter merged",
        ],
    },
}


@pytest.mark.parametrize("case", sorted(MULTI_PR_ENTRIES))
def test_multi_pr_manifest_entry_is_refused(
    case, fake_repo, write_config, run_prd_split
):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "prd-onejob", [_entry("one-job", **MULTI_PR_ENTRIES[case])])
    r = run_prd_split(fake_repo, "--prd-id", "prd-onejob")
    assert r.returncode == 2, (case, r.stdout, r.stderr)
    assert "more than one deliverable PR" in r.stderr, r.stderr
    # the refusal says HOW to split, not only that it refused
    assert "own manifest entry" in r.stderr and "one agent per PR" in r.stderr
    assert _issues(fake_repo) == [], "a refused manifest must write nothing"


def test_refusal_names_the_offending_entry_even_when_others_are_clean(
    fake_repo, write_config, run_prd_split
):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "prd-onejob", [
        _entry("clean-one"),
        _entry("bundled", acceptance="Ship as two separate PRs."),
    ])
    r = run_prd_split(fake_repo, "--prd-id", "prd-onejob")
    assert r.returncode == 2
    assert "entry #1" in r.stderr, r.stderr
    assert _issues(fake_repo) == [], "all-or-nothing: no partial split"


SINGLE_PR_CONTROLS = {
    "plain": {},
    "one-pr-mentioned": {"acceptance": "One PR, armed for auto-merge."},
    "real-pr-number": {"acceptance": "Supersedes PR #233 and PR 241."},
    "many-deliverables-one-pr": {
        "deliverables": ["test is red on main", "test is green", "PR merged"],
    },
    "fenced-sibling-label": {
        "acceptance": "Build exactly PR 2 of the plan, nothing from PR 3.",
    },
}


@pytest.mark.parametrize("case", sorted(SINGLE_PR_CONTROLS))
def test_single_pr_entry_still_splits(case, fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "prd-onejob", [_entry("one-job", **SINGLE_PR_CONTROLS[case])])
    r = run_prd_split(fake_repo, "--prd-id", "prd-onejob")
    assert r.returncode == 0, (case, r.stdout, r.stderr)
    assert [p.name for p in _issues(fake_repo)] == ["one-job.md"]


DOR_TEMPLATE = """## Definition of Ready

- **Outcome:** {outcome}
- **Files:** `src/widget.py`, `tests/test_widget.py`
- **Check:** `python3 -m pytest tests/test_widget.py -q`
"""


def _linear_payload(repo: Path, *, outcome: str, title: str = "Fix the widget") -> str:
    path = repo / "linear-payload.json"
    path.write_text(json.dumps({
        "identifier": "ASK-999",
        "title": title,
        "description": DOR_TEMPLATE.format(outcome=outcome),
    }))
    return str(path)


def test_multi_pr_linear_dor_is_refused(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    payload = _linear_payload(
        fake_repo, outcome="the ledger lands as PR A and the filter as PR B."
    )
    r = run_prd_split(fake_repo, "--from-linear", "ASK-999", "--linear-json", payload)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "ASK-999" in r.stderr and "more than one deliverable PR" in r.stderr
    assert "own Linear issue" in r.stderr
    assert _issues(fake_repo) == []


def test_multi_pr_linear_title_is_refused(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    payload = _linear_payload(
        fake_repo, outcome="the widget holds 60fps.",
        title="Widget fixes, a PR each",
    )
    r = run_prd_split(fake_repo, "--from-linear", "ASK-999", "--linear-json", payload)
    assert r.returncode == 2, (r.stdout, r.stderr)


def test_single_pr_linear_dor_still_splits(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    payload = _linear_payload(fake_repo, outcome="the widget holds 60fps in one PR.")
    r = run_prd_split(fake_repo, "--from-linear", "ASK-999", "--linear-json", payload)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert [p.name for p in _issues(fake_repo)] == ["ASK-999.md"]
