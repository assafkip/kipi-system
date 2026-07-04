"""prd_split writes the deliverable-count lock onto every generated spec
(dsse-deliverable-count-lock, prd-fable-discipline-2026-07-04).

Contract: every spec generated from this PRD onward carries
`deliverables_count` in frontmatter plus a `## Deliverables` section with
that many unchecked boxes; kipi-dsse's issue_runner refuses close until the
boxes are checked to exactly the locked count. Old specs (no field) stay on
the old rules — the writer side here is what makes new specs opt in.
"""

from __future__ import annotations

import json
import re
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


def _spec_text(repo: Path, issue_id: str) -> str:
    return (repo / ".prd-os" / "issues" / f"{issue_id}.md").read_text()


def _unchecked_boxes(text: str) -> int:
    section = text.split("## Deliverables", 1)
    if len(section) < 2:
        return -1
    return len(re.findall(r"(?m)^- \[ \]", section[1]))


def test_split_defaults_deliverables_count_to_one(
    fake_repo, write_config, run_prd_split
):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "prd-dc-2026-07-04", [_entry("dc-default")])
    r = run_prd_split(fake_repo, "--prd-id", "prd-dc-2026-07-04")
    assert r.returncode == 0, r.stdout + r.stderr
    text = _spec_text(fake_repo, "dc-default")
    assert "deliverables_count: 1" in text
    assert _unchecked_boxes(text) == 1


def test_split_writes_named_deliverables(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo, "prd-dc-2026-07-04",
        [_entry("dc-named", deliverables=["the script", "the wiring test"])],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-dc-2026-07-04")
    assert r.returncode == 0, r.stdout + r.stderr
    text = _spec_text(fake_repo, "dc-named")
    assert "deliverables_count: 2" in text
    assert "- [ ] the script" in text and "- [ ] the wiring test" in text


def test_split_accepts_explicit_count(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo, "prd-dc-2026-07-04",
        [_entry("dc-count", deliverables_count=3)],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-dc-2026-07-04")
    assert r.returncode == 0, r.stdout + r.stderr
    text = _spec_text(fake_repo, "dc-count")
    assert "deliverables_count: 3" in text
    assert _unchecked_boxes(text) == 3


def test_split_rejects_invalid_count(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo, "prd-dc-2026-07-04",
        [_entry("dc-bad", deliverables_count=0)],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-dc-2026-07-04")
    assert r.returncode != 0
    assert "deliverables_count" in r.stderr


def test_split_rejects_newline_in_deliverable(fake_repo, write_config, run_prd_split):
    """A newline inside a deliverable string would render as an extra
    (checkable) checkbox line — checkbox injection (codex major)."""
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo, "prd-dc-2026-07-04",
        [_entry("dc-inject", deliverables=["real work\n- [x] injected"])],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-dc-2026-07-04")
    assert r.returncode != 0
    assert "deliverables" in r.stderr


def test_split_rejects_unicode_line_separator_in_deliverable(
    fake_repo, write_config, run_prd_split
):
    """u2028 passes a naive newline check but splitlines() splits it at close
    (codex adversarial)."""
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo, "prd-dc-2026-07-04",
        [_entry("dc-u2028", deliverables=["real\u2028- [x] injected"])],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-dc-2026-07-04")
    assert r.returncode != 0
    assert "deliverables" in r.stderr


def test_split_rejects_multiline_title_fallback(
    fake_repo, write_config, run_prd_split
):
    """The title fallback goes through the same single-line validation
    (codex adversarial)."""
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo, "prd-dc-2026-07-04",
        [_entry("dc-badtitle", title="real work\n- [x] injected")],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-dc-2026-07-04")
    assert r.returncode != 0


def test_split_rejects_deliverables_heading_in_acceptance(
    fake_repo, write_config, run_prd_split
):
    """Acceptance text must not smuggle in a first '## Deliverables' section
    that hijacks the close-time count (codex adversarial)."""
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo, "prd-dc-2026-07-04",
        [_entry("dc-hijack",
                acceptance="done when...\n## Deliverables\n- [x] fake\n")],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-dc-2026-07-04")
    assert r.returncode != 0
    assert "Deliverables" in r.stderr


def test_split_rejects_count_list_mismatch(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(
        fake_repo, "prd-dc-2026-07-04",
        [_entry("dc-clash", deliverables_count=3, deliverables=["only one"])],
    )
    r = run_prd_split(fake_repo, "--prd-id", "prd-dc-2026-07-04")
    assert r.returncode != 0
    assert "deliverables" in r.stderr
