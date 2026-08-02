"""spill-01 reproducer: out-of-scope findings land in a durable ledger and turn
the STANDING gate (`gates run`) red until each is resolved against a CLOSED issue.

Reproducer-first: before the spillover code exists every test here fails
(`spillover` is an unknown subcommand; `gates run` stays green with an open item).
The ADHD-proof property under test: an item that is merely "mentioned" cannot
clear the gate; only a real, closed, tracked issue (or an explicit recorded void)
can.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PRD_RUNNER = PLUGIN_ROOT / "scripts" / "prd_runner.py"


def run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PRD_RUNNER), "--repo-root", str(repo), *args],
        capture_output=True, text=True,
    )


def _load_runner():
    """Import prd_runner in-process so the Linear fetch can be monkeypatched.

    The tracker lookup is stubbed at the function boundary rather than through
    an env-var endpoint override on purpose: an override would be a real bypass
    surface on the resolve path, and the whole point of this command is that a
    resolution cannot be asserted. A test seam that production also honours is
    a hand-clear with extra steps.
    """
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("prd_runner_under_test", PRD_RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / ".prd-os").mkdir(parents=True)
    (r / ".git").mkdir()
    (r / ".prd-os" / "config.json").write_text(json.dumps({
        "config_schema_version": 1,
        "prds_dir": ".prd-os/prds",
        "issues_dir": ".prd-os/issues",
        "findings_dir": ".prd-os/findings",
        "state_dir": ".claude/state",
    }))
    return r


def _ledger(repo: Path) -> Path:
    return repo / ".prd-os" / "spillover.jsonl"


def _write_issue(repo: Path, issue_id: str, status: str) -> None:
    d = repo / ".prd-os" / "issues"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{issue_id}.md").write_text(
        f"---\nid: {issue_id}\nstatus: {status}\n---\n\n# {issue_id}\n"
    )


def test_add_appends_open_item(repo):
    r = run(repo, "spillover", "add", "--source", "prd-x", "--desc", "obsidian export skips archived", "--id", "sp1")
    assert r.returncode == 0, r.stderr
    lines = _ledger(repo).read_text().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["id"] == "sp1" and rec["status"] == "open" and rec["source"] == "prd-x"


def test_add_is_idempotent_by_id(repo):
    run(repo, "spillover", "add", "--source", "s", "--desc", "d", "--id", "sp1")
    run(repo, "spillover", "add", "--source", "s", "--desc", "d", "--id", "sp1")
    # last-write-wins read collapses to one effective item, still open
    r = run(repo, "spillover", "list", "--json")
    items = json.loads(r.stdout)
    assert len([i for i in items if i["id"] == "sp1"]) == 1


def test_check_red_while_open_green_when_none(repo):
    assert run(repo, "spillover", "check").returncode == 0  # empty ledger = green
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1")
    assert run(repo, "spillover", "check").returncode == 1  # open item = red


def test_gates_run_red_while_spillover_open(repo):
    # No registered gates at all, but an open spillover item must still make the
    # STANDING re-proof fail. This is the can't-be-forgotten property.
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1")
    g = run(repo, "gates", "run")
    assert g.returncode != 0, "gates run stayed green with an open spillover item"
    assert "sp1" in (g.stdout + g.stderr)


def test_resolve_refuses_unless_issue_closed(repo):
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1")
    _write_issue(repo, "iss-1", status="in-progress")
    bad = run(repo, "spillover", "resolve", "sp1", "--resolution-ref", "iss-1")
    assert bad.returncode != 0, "resolve accepted a non-closed issue"
    assert run(repo, "spillover", "check").returncode == 1  # still open

    _write_issue(repo, "iss-1", status="closed")
    ok = run(repo, "spillover", "resolve", "sp1", "--resolution-ref", "iss-1")
    assert ok.returncode == 0, ok.stderr
    assert run(repo, "spillover", "check").returncode == 0  # now green
    assert run(repo, "gates", "run").returncode == 0


def test_resolve_refuses_unknown_issue(repo):
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1")
    bad = run(repo, "spillover", "resolve", "sp1", "--resolution-ref", "nope")
    assert bad.returncode != 0


def test_void_resolves_with_recorded_reason(repo):
    run(repo, "spillover", "add", "--source", "s", "--desc", "not real", "--id", "sp1")
    ok = run(repo, "spillover", "resolve", "sp1", "--void", "duplicate of sp0")
    assert ok.returncode == 0, ok.stderr
    assert run(repo, "spillover", "check").returncode == 0
    last = [json.loads(l) for l in _ledger(repo).read_text().splitlines() if json.loads(l)["id"] == "sp1"][-1]
    assert last["status"] == "resolved" and last.get("void_reason") == "duplicate of sp0"


def test_resolve_requires_a_target(repo):
    run(repo, "spillover", "add", "--source", "s", "--desc", "x", "--id", "sp1")
    bad = run(repo, "spillover", "resolve", "sp1")  # neither --resolution-ref nor --void
    assert bad.returncode != 0


# --- ASK-209: resolving against the tracker that actually owns the issue -----
#
# This repo's work ships through Linear, so `--resolution-ref ASK-204` used to be
# looked up in `.prd-os/issues/`, never found, and refused -- while ASK-204 was
# provably closed (PR #19, merge 990d7c1). The ledger then held finished work
# open forever and `gates run` went RED on nothing, which is how a gate stops
# carrying information. The fix VERIFIES a Linear identifier against Linear.
# It does not trust the operator's word for it: an unverifiable ref is refused,
# never recorded as resolved.


@pytest.fixture
def runner():
    return _load_runner()


def _resolve(module, repo: Path, *args: str) -> int:
    return module.main(["--repo-root", str(repo), "spillover", "resolve", *args])


def _stub_linear(monkeypatch, module, table: dict):
    """Stand in for the Linear API. Unknown identifier -> the same error the
    real fetch raises, so 'unknown' and 'open' stay distinguishable."""
    def fake(identifier: str) -> dict:
        if identifier not in table:
            raise module.LinearRefError(f"Linear has no issue {identifier}")
        return table[identifier]
    monkeypatch.setattr(module, "_linear_issue_state", fake)


def test_resolve_verifies_closed_linear_issue(repo, runner, monkeypatch):
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1")
    _stub_linear(monkeypatch, runner, {"ASK-204": {"type": "completed", "name": "Done"}})

    code = _resolve(runner, repo, "sp1", "--resolution-ref", "ASK-204",
                    "--evidence", "PR #19 / 990d7c1")
    assert code == 0

    last = [json.loads(l) for l in _ledger(repo).read_text().splitlines()
            if json.loads(l)["id"] == "sp1"][-1]
    assert last["status"] == "resolved"
    assert last["resolution_ref"] == "ASK-204"
    # The record has to be auditable offline: which tracker answered, what it
    # said, and when. Otherwise the next reader has to re-hit the API to know
    # whether this was verified or asserted.
    assert last["resolution_tracker"] == "linear"
    assert last["resolution_verified_state"] == "Done"
    assert last["resolution_evidence"] == "PR #19 / 990d7c1"
    assert run(repo, "spillover", "check").returncode == 0
    assert run(repo, "gates", "run").returncode == 0


def test_resolve_refuses_open_linear_issue(repo, runner, monkeypatch):
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1")
    _stub_linear(monkeypatch, runner, {"ASK-999": {"type": "started", "name": "In Progress"}})

    assert _resolve(runner, repo, "sp1", "--resolution-ref", "ASK-999") != 0
    assert run(repo, "spillover", "check").returncode == 1  # still open
    assert run(repo, "gates", "run").returncode != 0


def test_resolve_refuses_canceled_linear_issue(repo, runner, monkeypatch):
    # Canceled is not fixed. A canceled issue shipped no fix, so letting it
    # resolve an item would clear the gate on work that never happened. The
    # honest exit for a non-item is --void, which records a reason.
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1")
    _stub_linear(monkeypatch, runner, {"ASK-998": {"type": "canceled", "name": "Canceled"}})

    assert _resolve(runner, repo, "sp1", "--resolution-ref", "ASK-998") != 0
    assert run(repo, "spillover", "check").returncode == 1


def test_resolve_refuses_unknown_linear_identifier(repo, runner, monkeypatch):
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1")
    _stub_linear(monkeypatch, runner, {})  # Linear knows nothing

    assert _resolve(runner, repo, "sp1", "--resolution-ref", "ASK-4242") != 0
    assert run(repo, "spillover", "check").returncode == 1


def test_resolve_refuses_malformed_ref_without_calling_linear(repo, runner, monkeypatch):
    # A ref that is neither a local spec nor a well-formed Linear identifier is
    # refused before any network call, so a typo cannot become a live lookup.
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1")
    called = []
    monkeypatch.setattr(runner, "_linear_issue_state",
                        lambda ident: called.append(ident) or {"type": "completed", "name": "Done"})

    assert _resolve(runner, repo, "sp1", "--resolution-ref", "ASK-two-oh-four") != 0
    assert called == [], "a malformed ref reached the Linear API"
    assert run(repo, "spillover", "check").returncode == 1


def test_resolve_refuses_when_linear_auth_is_missing(repo, tmp_path):
    """No key, no network, no resolution -- the item stays open and the gate red.

    Recording an unverifiable ref as `pending` was the alternative. It is worse:
    the operator's assertion would be the only thing standing between a finding
    and a clean ledger, which is exactly the hand-clear this command exists to
    prevent. Refusing keeps the item visible until someone can actually prove it.
    """
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1")
    env = dict(os.environ)
    env.pop("KIPI_LINEAR_API_KEY", None)
    env["HOME"] = str(tmp_path / "empty-home")  # no ~/.config/kipi/linear-api-key
    (tmp_path / "empty-home").mkdir()

    bad = subprocess.run(
        [sys.executable, str(PRD_RUNNER), "--repo-root", str(repo),
         "spillover", "resolve", "sp1", "--resolution-ref", "ASK-204"],
        capture_output=True, text=True, env=env,
    )
    assert bad.returncode != 0
    assert "sp1" in bad.stderr
    assert run(repo, "spillover", "check").returncode == 1
    assert run(repo, "gates", "run").returncode != 0


def test_local_issue_spec_still_wins_over_linear(repo, runner, monkeypatch):
    # A repo that tracks issues locally under a Linear-shaped id keeps working
    # offline: the local spec is checked first and Linear is never consulted.
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1")
    _write_issue(repo, "ASK-204", status="closed")
    monkeypatch.setattr(runner, "_linear_issue_state",
                        lambda ident: pytest.fail("local spec should have answered"))

    assert _resolve(runner, repo, "sp1", "--resolution-ref", "ASK-204") == 0
    assert run(repo, "spillover", "check").returncode == 0


# --- ASK-148: reading a 350-item ledger by producer instead of one at a time ---
#
# The ledger accretes ~50 items/day from a handful of producers, so `list --open`
# prints 350 undifferentiated lines and nobody can see which SOURCE is worth
# opening an issue against. `triage` is the read-only lens: same rows, grouped
# and counted. It resolves nothing and voids nothing -- the only two exits from
# the ledger stay exactly where they were.


def _add(repo: Path, sid: str, source: str, severity: str) -> None:
    run(repo, "spillover", "add", "--source", source, "--desc", f"finding {sid}",
        "--id", sid, "--severity", severity)


def test_triage_reports_no_open_items_on_an_empty_ledger(repo):
    r = run(repo, "spillover", "triage")
    assert r.returncode == 0, r.stderr
    assert "no open spillover items" in r.stdout


def test_triage_groups_by_severity_with_counts(repo):
    _add(repo, "sp1", "ASK-113", "minor")
    _add(repo, "sp2", "ASK-113", "minor")
    _add(repo, "sp3", "ASK-221", "blocker")

    r = run(repo, "spillover", "triage")
    assert r.returncode == 0, r.stderr
    assert "3 open spillover item(s)" in r.stdout
    assert "minor" in r.stdout and "blocker" in r.stdout
    sev = r.stdout.split("by severity")[1].split("by source")[0]
    assert "minor" in sev.split("blocker")[0], f"severity groups not count-ordered:\n{sev}"


def test_triage_groups_by_source_with_counts(repo):
    _add(repo, "sp1", "ASK-113", "minor")
    _add(repo, "sp2", "ASK-113", "minor")
    _add(repo, "sp3", "ASK-221", "minor")

    r = run(repo, "spillover", "triage")
    src = r.stdout.split("by source")[1]
    assert "ASK-113" in src and "ASK-221" in src
    assert src.index("ASK-113") < src.index("ASK-221"), f"sources not count-ordered:\n{src}"


def test_triage_counts_only_open_items(repo):
    _add(repo, "sp1", "ASK-113", "minor")
    _add(repo, "sp2", "ASK-113", "minor")
    run(repo, "spillover", "resolve", "sp2", "--void", "not a real item")

    r = run(repo, "spillover", "triage")
    assert "1 open spillover item(s)" in r.stdout
    assert "sp2" not in r.stdout


def test_triage_never_writes_to_the_ledger(repo):
    _add(repo, "sp1", "ASK-113", "minor")
    before = _ledger(repo).read_bytes()

    assert run(repo, "spillover", "triage").returncode == 0
    assert _ledger(repo).read_bytes() == before, "triage mutated the ledger"


def test_triage_leaves_the_gate_red(repo):
    # The lens does not clear anything: `check` and `gates run` are unchanged by
    # having looked. A read that could turn a gate green would be a bulk-clear.
    _add(repo, "sp1", "ASK-113", "blocker")
    run(repo, "spillover", "triage")

    assert run(repo, "spillover", "check").returncode == 1
    assert run(repo, "gates", "run").returncode != 0
