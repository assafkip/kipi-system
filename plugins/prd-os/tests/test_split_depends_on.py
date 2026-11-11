"""prd_split carries a manifest entry's depends_on into the issue spec (ASK-4233).

why: _validate_entry copied only known keys, so a manifest's depends_on was
dropped at split time and issue-start could not refuse an out-of-order spec
(spillover sp-e37fa02c). The reader side is in kipi-dsse
test_depends_on_start.py. A spec with no depends_on must stay byte-identical
to what it was before, so the control below pins the absence of the key.
"""

from __future__ import annotations

import json
from pathlib import Path


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


def _frontmatter(repo: Path, issue_id: str) -> str:
    text = (repo / ".prd-os" / "issues" / f"{issue_id}.md").read_text()
    return text[: text.find("\n---", 3)]


def test_split_writes_depends_on_into_the_spec(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo, "prd-dep-2026-11-10",
        [_entry("dep-first"), _entry("dep-second", depends_on=["dep-first"])],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-dep-2026-11-10")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "depends_on: [dep-first]" in _frontmatter(fake_repo, "dep-second")


def test_split_writes_several_dependencies_in_order(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo, "prd-dep-2026-11-10",
        [_entry("dep-a"), _entry("dep-b"),
         _entry("dep-c", depends_on=["dep-a", "dep-b"])],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-dep-2026-11-10")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "depends_on: [dep-a, dep-b]" in _frontmatter(fake_repo, "dep-c")


def test_control_entry_without_depends_on_writes_no_key(
    fake_repo, write_config, run_prd_split
):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "prd-dep-2026-11-10", [_entry("dep-plain")])
    r = run_prd_split(fake_repo, "--prd-id", "prd-dep-2026-11-10")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "depends_on" not in _frontmatter(fake_repo, "dep-plain")


def test_split_rejects_a_malformed_depends_on(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    for bad in ("dep-first", ["a, b"], [""], [3], ["x]"]):
        _write_prd(
            fake_repo, "prd-dep-2026-11-10", [_entry("dep-bad", depends_on=bad)]
        )
        r = run_prd_split(fake_repo, "--prd-id", "prd-dep-2026-11-10")
        assert r.returncode != 0, f"{bad!r} was accepted"
        assert "depends_on" in r.stderr, r.stderr
