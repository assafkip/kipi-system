"""prd-split: founder hands become activation issues, prose deferrals must be tracked.

ASK-3830, two halves of "closed means shipped".

1. A split produced mechanism issues and nothing for the founder's own step.
   A hand named in Acceptance ("use browse once") had no trigger, so its
   dependents never started (chief: 0 of 17 new doors used from the phone in
   477 turns). Each founder hand now becomes its own activation spec: one PR,
   one "Live:" deliverable (so close needs a live receipt), blocked by the
   mechanism issues, and `issue_runner load` refuses it until they close.

2. "Open for v2 / follow-up" in PRD prose was converted to nothing at split and
   evaporated at archive (kipi-investigations rca-built-not-wired-2026-06-14
   root cause #3). Its fix, `_deferral_tracking_gate` (f00ee9d7), ran at
   archive and was deleted by a fleet sync the next day. The port runs at split,
   where the manifest is read, and is per paragraph: the original passed the
   whole PRD once ANY tracked token appeared anywhere in it.

Red on the pre-fix prd_split: the refusals exit 0 and no activation spec exists.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parents[2]
ISSUE_RUNNER = PLUGINS / "kipi-dsse" / "scripts" / "issue_runner.py"
PRD_TEMPLATE = PLUGINS / "prd-os" / "templates" / "prd.md"
PRD_ID = "prd-fixture-2026-11-06"


def _bootstrap(repo: Path, write_config) -> None:
    write_config(repo, {
        "config_schema_version": 1,
        "prds_dir": ".prd-os/prds",
        "issues_dir": ".prd-os/issues",
        "findings_dir": ".prd-os/findings",
        "state_dir": ".claude/state",
    })


def _entry(issue_id: str, **extra) -> dict:
    return {
        "id": issue_id,
        "title": f"{issue_id} fixture",
        "finding_id": f"finding-{issue_id}",
        "allowed_files": [f"src/{issue_id}.py"],
        "required_checks": [f"pytest tests/test_{issue_id}.py"],
        "bypass_exempt": "fixture",
        **extra,
    }


def _write_prd(repo: Path, prose: str, entries: list[dict]) -> Path:
    prds = repo / ".prd-os" / "prds"
    prds.mkdir(parents=True, exist_ok=True)
    path = prds / f"{PRD_ID}.md"
    path.write_text(
        "---\n"
        f"id: {PRD_ID}\n"
        "title: Fixture\n"
        "status: approved\n"
        "---\n\n# Fixture\n\n" + prose.strip("\n") + "\n\n## Issues\n\n"
        "```json\n" + json.dumps(entries, indent=2) + "\n```\n"
    )
    return path


def _issues(repo: Path) -> dict[str, str]:
    d = repo / ".prd-os" / "issues"
    return {p.stem: p.read_text() for p in sorted(d.glob("*.md"))} if d.is_dir() else {}


def _fm_list(spec: str, key: str) -> list[str]:
    m = re.search(rf"(?m)^{key}:\n((?:  - .*\n)+)", spec)
    return [l[4:] for l in m.group(1).splitlines()] if m else []


TWO = [_entry("issue-a"), _entry("issue-b")]


# ---------------------------------------------------------------------------
# 3. Prose deferrals must name a tracked item
# ---------------------------------------------------------------------------

def test_dor_an_untracked_deferral_refuses_the_split_naming_the_line(
        fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "## Proposed approach\n\nShip the new panel.\n\n"
               "Open for v2: remove the old panel.\n", TWO)
    r = run_prd_split(fake_repo, "--prd-id", PRD_ID)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "Open for v2: remove the old panel." in r.stderr, r.stderr
    # Line 13 of the file: 5 frontmatter lines, blank, "# Fixture", blank, the
    # heading, blank, "Ship the new panel.", blank, then the deferral.
    assert re.search(r"line 13\b", r.stderr), r.stderr
    assert _issues(fake_repo) == {}


def test_a_dry_run_refuses_too(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "The cache warmer is a follow-up.\n", TWO)
    r = run_prd_split(fake_repo, "--prd-id", PRD_ID, "--dry-run")
    assert r.returncode == 2 and "follow-up" in r.stderr, r.stderr


@pytest.mark.parametrize("ref", [
    "`issue-b`",          # a manifest entry of this PRD
    "issue-b",            # bare id
    "ASK-1234",           # a Linear ticket
    "sp-1a2b3c4d",        # a spillover item
])
def test_a_deferral_that_names_its_tracking_item_splits(
        fake_repo, write_config, run_prd_split, ref):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, f"Removing the old panel is deferred to v2, tracked as {ref}.\n", TWO)
    r = run_prd_split(fake_repo, "--prd-id", PRD_ID)
    assert r.returncode == 0, r.stderr


def test_an_existing_spec_from_another_prd_counts_as_tracked(
        fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    issues = fake_repo / ".prd-os" / "issues"
    issues.mkdir(parents=True)
    (issues / "old-panel-removal.md").write_text("---\nid: old-panel-removal\n---\n")
    _write_prd(fake_repo, "Old panel removal is a follow-up (old-panel-removal).\n", TWO)
    assert run_prd_split(fake_repo, "--prd-id", PRD_ID).returncode == 0


def test_a_tracking_id_that_resolves_to_nothing_still_refuses(
        fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "Old panel removal is a follow-up, see `ghost-issue`.\n", TWO)
    r = run_prd_split(fake_repo, "--prd-id", PRD_ID)
    assert r.returncode == 2, r.stderr


def test_the_id_may_sit_on_the_next_line_of_the_same_paragraph(
        fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "Removing the old panel is deferred to a\n"
               "later PR, tracked as `issue-b`.\n", TWO)
    assert run_prd_split(fake_repo, "--prd-id", PRD_ID).returncode == 0


def test_one_tracked_paragraph_does_not_excuse_another(
        fake_repo, write_config, run_prd_split):
    """The f00ee9d7 gate passed the whole PRD once any one token resolved."""
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "Search is deferred, tracked as `issue-b`.\n\n"
               "- Export to CSV is open for v2.\n", TWO)
    r = run_prd_split(fake_repo, "--prd-id", PRD_ID)
    assert r.returncode == 2 and "Export to CSV" in r.stderr, r.stderr
    assert "Search is deferred" not in r.stderr, r.stderr


@pytest.mark.parametrize("prose", [
    "<!-- punt this to v2 as a follow-up -->\n",
    "## Deferred to v2\n\nNothing here yet.\n",
    "```\nfollow-up: deferred to v2\n```\n",
    "> founder, verbatim: \"open for v2, as a follow-up\"\n",
    "A `deferred` finding opens a spillover item.\n",
    "The deferred-major rate is a tunable constant.\n",
    "Recorded as out, not deferred.\n",
    "The v2 schema adds one column. See https://api.example.com/v2/check.\n",
    "The bot sends a follow-up message after an hour.\n",
])
def test_non_deferrals_do_not_refuse(fake_repo, write_config, run_prd_split, prose):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, prose, TWO)
    r = run_prd_split(fake_repo, "--prd-id", PRD_ID)
    assert r.returncode == 0, r.stderr


def test_a_prd_written_from_the_template_splits(fake_repo, write_config, run_prd_split):
    """The template's own guidance lives in comments and headings; a PRD born
    from it must not trip either detector."""
    _bootstrap(fake_repo, write_config)
    body = PRD_TEMPLATE.read_text()
    body = (body.replace("{{prd_id}}", PRD_ID).replace("{{title}}", "T")
            .replace("{{created_at}}", "2026-11-06T00:00:00Z").replace("{{owner}}", "t")
            .replace("status: idea", "status: approved"))
    body = body.replace("```json\n[]\n```", "```json\n" + json.dumps(TWO) + "\n```")
    prds = fake_repo / ".prd-os" / "prds"
    prds.mkdir(parents=True)
    (prds / f"{PRD_ID}.md").write_text(body)
    r = run_prd_split(fake_repo, "--prd-id", PRD_ID)
    assert r.returncode == 0, r.stderr
    assert sorted(_issues(fake_repo)) == ["issue-a", "issue-b"]


# ---------------------------------------------------------------------------
# 2. Founder hands become activation issues
# ---------------------------------------------------------------------------

def _activation(repo: Path) -> list[tuple[str, str]]:
    return [(k, v) for k, v in _issues(repo).items() if "-activate-" in k]


def test_dor_a_founder_hand_in_acceptance_produces_an_activation_issue(
        fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "## Acceptance\n\n- The bot answers in voice.\n"
               "- Founder sends one voice note to the bot.\n", TWO)
    r = run_prd_split(fake_repo, "--prd-id", PRD_ID)
    assert r.returncode == 0, r.stderr
    (act_id, spec), = _activation(fake_repo)
    assert act_id == f"{PRD_ID}-activate-1"
    assert "founder sends one voice note" in spec.lower()
    assert _fm_list(spec, "blocked_by") == ["issue-a", "issue-b"]
    assert "- [ ] Live: Founder sends one voice note to the bot" in spec
    assert "deliverables_count: 1" in spec
    assert f"prd={PRD_ID} finding=activation" in spec
    # The field close reads is on the Live spec, and only there: every other
    # spec renders byte-identical to before, so older splits rerun cleanly.
    assert re.search(r"(?m)^live_receipt:$", spec), spec
    assert "live_receipt" not in _issues(fake_repo)["issue-a"]
    # It is a spec of the PRD's own and lands with the mechanism specs.
    assert {"issue-a", "issue-b"} <= set(_issues(fake_repo))
    assert act_id in json.loads(r.stdout)["created"][-1]


def test_an_acceptance_hand_that_names_an_issue_is_blocked_by_that_issue_only(
        fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "## Acceptance\n\n- After `issue-b`, the founder taps allow once.\n", TWO)
    assert run_prd_split(fake_repo, "--prd-id", PRD_ID).returncode == 0
    (_, spec), = _activation(fake_repo)
    assert _fm_list(spec, "blocked_by") == ["issue-b"]
    assert _fm_list(spec, "allowed_files") == ["src/issue-b.py"]
    assert _fm_list(spec, "required_checks") == ["pytest tests/test_issue-b.py"]


def test_a_founder_hand_in_an_entry_acceptance_is_blocked_by_that_entry(
        fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    entries = [_entry("issue-a", acceptance="Builds the helper. Founder hands: H1 "
                      "(Accessibility for the helper binary, once)."), _entry("issue-b")]
    _write_prd(fake_repo, "", entries)
    assert run_prd_split(fake_repo, "--prd-id", PRD_ID).returncode == 0
    (_, spec), = _activation(fake_repo)
    assert _fm_list(spec, "blocked_by") == ["issue-a"]
    assert "H1 (Accessibility for the helper binary, once)" in spec


def test_the_same_hand_in_two_entries_is_one_activation_blocked_by_both(
        fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    hand = "The founder runs the fleet sync."
    entries = [_entry("issue-a", acceptance=hand), _entry("issue-b", acceptance=hand)]
    _write_prd(fake_repo, "", entries)
    assert run_prd_split(fake_repo, "--prd-id", PRD_ID).returncode == 0
    (_, spec), = _activation(fake_repo)
    assert _fm_list(spec, "blocked_by") == ["issue-a", "issue-b"]
    assert _fm_list(spec, "allowed_files") == ["src/issue-a.py", "src/issue-b.py"]


@pytest.mark.parametrize("acceptance", [
    "Founder hands: none.",
    "Founder hands: none (his ordinary first photo is the receipt).",
    "Founder hands: H1 already done in issue-a.",
    "The founder does not review code.",
    "notify excludes fixture rows from its founder-facing count.",
    "Executes the founder-signed table row by row.",
    "No founder action is needed; the job runs itself.",
    "If the founder rejects it, the PR closes.",
])
def test_non_hands_produce_no_activation(fake_repo, write_config, run_prd_split, acceptance):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "", [_entry("issue-a", acceptance=acceptance), _entry("issue-b")])
    r = run_prd_split(fake_repo, "--prd-id", PRD_ID)
    assert r.returncode == 0, r.stderr
    assert _activation(fake_repo) == []


def test_an_activation_is_one_pr_never_a_bundle(fake_repo, write_config, run_prd_split):
    """#612's guard covers the generated spec too."""
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "## Acceptance\n\n- Founder merges PR 1 and PR 2 by hand.\n", TWO)
    r = run_prd_split(fake_repo, "--prd-id", PRD_ID)
    assert r.returncode == 2 and "more than one deliverable PR" in r.stderr, r.stderr
    assert _issues(fake_repo) == {}


def test_a_rerun_is_idempotent(fake_repo, write_config, run_prd_split):
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "## Acceptance\n\n- Founder sends one voice note.\n", TWO)
    assert run_prd_split(fake_repo, "--prd-id", PRD_ID).returncode == 0
    before = _issues(fake_repo)
    again = run_prd_split(fake_repo, "--prd-id", PRD_ID)
    assert again.returncode == 0, again.stderr
    assert _issues(fake_repo) == before


def _load(repo: Path, issue_id: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    return subprocess.run([sys.executable, str(ISSUE_RUNNER), "load", issue_id],
                          cwd=repo, capture_output=True, text=True, env=env)


def test_load_refuses_an_activation_until_its_blockers_close(
        fake_repo, write_config, run_prd_split):
    """blocked_by has a consumer: the issue runner's load."""
    _bootstrap(fake_repo, write_config)
    _write_prd(fake_repo, "## Acceptance\n\n- Founder sends one voice note.\n", TWO)
    assert run_prd_split(fake_repo, "--prd-id", PRD_ID).returncode == 0
    (act_id, _), = _activation(fake_repo)
    r = _load(fake_repo, act_id)
    assert r.returncode == 2 and "blocked by" in r.stderr and "issue-a" in r.stderr, r.stderr
    for iid in ("issue-a", "issue-b"):
        p = fake_repo / ".prd-os" / "issues" / f"{iid}.md"
        p.write_text(p.read_text().replace("status: open", "status: closed", 1))
    r = _load(fake_repo, act_id)
    assert r.returncode == 0, r.stderr
