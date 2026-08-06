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


def _ledger_lines(repo):
    """Raw ledger lines, for asserting append-only behaviour.

    A missing file is zero events, not an error: a refused command must leave
    no ledger at all, and that is a state this helper has to be able to report.
    """
    path = repo / ".prd-os" / "spillover.jsonl"
    if not path.is_file():
        return []
    return [l for l in path.read_text().splitlines() if l.strip()]

def test_gates_run_red_while_a_blocking_severity_item_is_open(repo):
    # No registered gates at all, but an open BLOCKING-severity spillover item
    # must still make the STANDING re-proof fail. The can't-be-forgotten
    # property, now scoped to severities that were actually assessed.
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1",
        "--severity", "major")
    g = run(repo, "gates", "run")
    assert g.returncode != 0, "gates run stayed green with an open major item"
    assert "sp1" in (g.stdout + g.stderr)


def test_gates_run_is_green_but_reports_a_minor_item(repo):
    """The contract change (approved PRD prd-spillover-current-state-2026-07-24,
    goal 5: "make gates run identify pre-existing debt separately from new
    debt").

    Every open item used to turn the gate red as one undifferentiated group. It
    reached 550 open and stayed red for months, which teaches everyone to step
    over it -- worse than no gate, because it launders "we have enforcement".

    A minor item is now REPORTED and does not block."""
    run(repo, "spillover", "add", "--source", "s", "--desc", "nit", "--id", "sp-n",
        "--severity", "minor")
    g = run(repo, "gates", "run")
    assert g.returncode == 0, (
        f"a minor item still blocks the gate: {g.stdout}{g.stderr}")
    assert "sp-n" in (g.stdout + g.stderr), (
        "the minor item is not blocking AND not reported -- that is silent, "
        "which is how 533 of them accumulated unnoticed")


def test_the_report_does_not_call_untriaged_items_minor(repo):
    """`--severity` DEFAULTS to minor, so a defaulted item is indistinguishable
    from one assessed as minor. 533 of 550 open items sit at that default. The
    report must not launder "nobody looked at it" as "we judged it small"."""
    run(repo, "spillover", "add", "--source", "s", "--desc", "nit", "--id", "sp-n")
    out = run(repo, "gates", "run").stdout
    assert "untriaged" in out.lower(), (
        f"report presents the default as a real severity judgement: {out}")


def test_a_blocking_item_still_blocks_when_minor_items_exist(repo):
    """Negative-fire: the minor bucket must not swallow the blocking one."""
    run(repo, "spillover", "add", "--source", "s", "--desc", "nit", "--id", "sp-n",
        "--severity", "minor")
    run(repo, "spillover", "add", "--source", "s", "--desc", "bad", "--id", "sp-b",
        "--severity", "blocker")
    g = run(repo, "gates", "run")
    assert g.returncode != 0
    assert "sp-b" in (g.stdout + g.stderr)


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
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1",
        # Blocking severity on purpose: this test asserts `gates run` stays
        # RED after a REFUSED resolve. Since 2026-08-05 the gate only blocks
        # on blocker/major/high, so a default-severity item would leave it
        # green and the assertion would pass for the wrong reason.
        "--severity", "major")
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
    run(repo, "spillover", "add", "--source", "s", "--desc", "leak", "--id", "sp1",
        # Blocking severity on purpose: this test asserts `gates run` stays
        # RED after a REFUSED resolve. Since 2026-08-05 the gate only blocks
        # on blocker/major/high, so a default-severity item would leave it
        # green and the assertion would pass for the wrong reason.
        "--severity", "major")
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


def test_archive_still_refuses_on_a_minor_item(repo):
    """The standing gate and the terminal closeout have different bars, and
    that difference must be pinned or a later reader will "fix" the
    inconsistency. `gates run` blocks only on blocker/major/high so it can be
    green day to day. `archive` refuses on ANY open item, because
    no-orphan-findings.md requires every item the work touched to be reported
    at closeout."""
    import json as _json
    created = run(repo, "new", "arch", "--title", "T")
    prd_id = _json.loads(created.stdout)["created"]
    run(repo, "advance", "draft")
    # Sourced from THIS PRD: archive is scoped to the items the work opened.
    run(repo, "spillover", "add", "--source", prd_id, "--desc", "nit",
        "--id", "sp-n", "--severity", "minor")
    assert run(repo, "gates", "run").returncode == 0, "minor should not block the gate"
    assert run(repo, "archive").returncode != 0, (
        "archive let through a minor item THIS PRD opened; closeout must report all"
    )


def test_archive_ignores_a_minor_item_another_prd_opened(repo):
    """The scope half, added after Codex round 3 produced a repro.

    Refusing on the GLOBAL ledger made archive unreachable: 533 items sit at
    the default `minor`, so every PRD inherited the fleet's whole backlog as
    its own exit condition. no-orphan-findings.md says report every item THE
    WORK TOUCHED, which is what this pins."""
    import json as _json
    run(repo, "spillover", "add", "--source", "SOME-OTHER-PRD", "--desc",
        "unrelated backlog", "--id", "sp-other", "--severity", "minor")
    created = run(repo, "new", "arch2", "--title", "T")
    prd_id = _json.loads(created.stdout)["created"]
    run(repo, "advance", "draft")
    assert run(repo, "archive").returncode == 0, (
        "another PRD's open item blocked this archive; the terminal step is "
        "unreachable whenever the fleet backlog is non-empty"
    )


# ---------------------------------------------------------------------------
# An unrecognized severity must never read as "minor".
# Codex, PR #110 round 2, with a reproducer: `--severity critical` was stored
# verbatim, reported as minor-or-untriaged, and the gate returned green.
# ---------------------------------------------------------------------------


def _load_runner():
    import importlib.util
    from pathlib import Path as _P
    path = _P(__file__).resolve().parents[1] / "scripts/prd_runner.py"
    spec = importlib.util.spec_from_file_location("prd_runner_sev", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("severity", ["critical", "urgent", "sev1", "P0", "BLOCKER!"])
def test_unknown_severity_is_treated_as_blocking(severity):
    """Fail-closed. The word a human reaches for under pressure is exactly the
    one the allowlist did not contain, so the louder the label the quieter the
    gate got."""
    mod = _load_runner()
    assert mod._is_blocking_severity(severity), (
        f"{severity!r} was classified non-blocking; an unknown severity must block"
    )


@pytest.mark.parametrize("severity", ["minor", "low", "medium", "MINOR", " Low "])
def test_known_nonblocking_severities_still_do_not_block(severity):
    """The negative half: without this the fix could pass by blocking on
    everything, which is the permanently-red gate it replaced."""
    mod = _load_runner()
    assert not mod._is_blocking_severity(severity)


@pytest.mark.parametrize("severity", ["blocker", "major", "high"])
def test_blocking_severities_still_block(severity):
    mod = _load_runner()
    assert mod._is_blocking_severity(severity)


def test_cli_refuses_an_unrecognized_severity_at_the_door():
    """Fail-closed in the gate is the backstop; the CLI should never store it."""
    import subprocess, sys
    from pathlib import Path as _P
    runner = _P(__file__).resolve().parents[1] / "scripts/prd_runner.py"
    proc = subprocess.run(
        [sys.executable, str(runner), "spillover", "add", "--source", "t",
         "--desc", "d", "--severity", "critical"],
        capture_output=True, text=True)
    assert proc.returncode != 0, "CLI accepted an unrecognized severity"
    assert "critical" in (proc.stderr + proc.stdout)


# ---------------------------------------------------------------------------
# reclassify: correct a severity through a NEW event, never a mutation
# ---------------------------------------------------------------------------
#
# 549 of 559 open items sit at the `minor` DEFAULT, i.e. untriaged. `gates run`
# now blocks only on blocker/major/high, so triaging that backlog is the work
# that makes the gate mean something -- and there was no verb to do it with.
# `add`, `list`, `check`, `triage` (read-only), `resolve`. Nothing could raise
# an item.
#
# Shape per the approved PRD prd-spillover-current-state-2026-07-24: "correct
# severity through new events only", "preserve append-only history", "editing
# or deleting prior spillover events" is an explicit non-goal.

def test_reclassify_raises_severity_and_blocks_the_gate(repo):
    run(repo, "spillover", "add", "--source", "s", "--desc", "real bug", "--id", "sp1")
    assert run(repo, "gates", "run").returncode == 0, "precondition: minor is not blocking"
    r = run(repo, "spillover", "reclassify", "sp1", "--severity", "major",
            "--reason", "deletes founder data on an empty-prefix instance")
    assert r.returncode == 0, r.stderr
    assert run(repo, "gates", "run").returncode != 0, (
        "reclassify to major did not make the standing gate block"
    )


def test_reclassify_appends_and_never_rewrites_history(repo):
    run(repo, "spillover", "add", "--source", "s", "--desc", "d", "--id", "sp1")
    before = _ledger_lines(repo)
    run(repo, "spillover", "reclassify", "sp1", "--severity", "high", "--reason", "why")
    after = _ledger_lines(repo)
    assert after[:len(before)] == before, "reclassify rewrote prior events"
    assert len(after) == len(before) + 1, "reclassify did not append exactly one event"
    assert json.loads(after[-1])["severity"] == "high"


def test_reclassify_records_the_reason(repo):
    """A severity change with no stated reason is the hand-clear this ledger
    refuses everywhere else."""
    run(repo, "spillover", "add", "--source", "s", "--desc", "d", "--id", "sp1")
    bad = run(repo, "spillover", "reclassify", "sp1", "--severity", "major")
    assert bad.returncode != 0, "reclassify accepted a severity change with no reason"
    ok = run(repo, "spillover", "reclassify", "sp1", "--severity", "major",
             "--reason", "it can delete data")
    assert ok.returncode == 0
    assert "it can delete data" in _ledger_lines(repo)[-1]


def test_reclassify_refuses_an_unknown_severity(repo):
    run(repo, "spillover", "add", "--source", "s", "--desc", "d", "--id", "sp1")
    r = run(repo, "spillover", "reclassify", "sp1", "--severity", "urgent",
            "--reason", "x")
    assert r.returncode != 0, "unknown severity accepted; the gate reads this field"


def test_reclassify_refuses_an_unknown_id(repo):
    """Negative-fire: a typo must not silently create a new open item.

    Asserts the MESSAGE, not just a nonzero exit. Mutation showed exit-code-only
    could not tell a clean refusal from a TypeError crash -- dropping the guard
    made `dict(None)` raise, which is also nonzero, so the test passed while the
    behaviour was a stack trace."""
    r = run(repo, "spillover", "reclassify", "sp-nope", "--severity", "major",
            "--reason", "x")
    assert r.returncode != 0, "reclassify invented an item that never existed"
    assert "unknown spillover id" in r.stderr, (
        f"refused, but not cleanly -- stderr was: {r.stderr!r}")
    assert "Traceback" not in r.stderr, "refusal is a crash, not a decision"
    assert not _ledger_lines(repo), "a refused reclassify still wrote an event"


def test_reclassify_refuses_a_whitespace_only_reason(repo):
    """argparse `required=True` already rejects a MISSING --reason, so the
    in-code check is only reachable via whitespace. Mutation proved the earlier
    test never exercised it: deleting the check left the suite green because
    argparse fired first."""
    run(repo, "spillover", "add", "--source", "s", "--desc", "d", "--id", "sp1")
    r = run(repo, "spillover", "reclassify", "sp1", "--severity", "major",
            "--reason", "   ")
    assert r.returncode != 0, "a whitespace-only reason was accepted as a reason"
    assert "--reason is required" in r.stderr


def test_reclassify_preserves_status_and_description(repo):
    """Only severity moves. A reclassify that drops the description would make
    the ledger unreadable, and one that flips status would resolve by side
    effect."""
    run(repo, "spillover", "add", "--source", "s", "--desc", "the original text",
        "--id", "sp1")
    run(repo, "spillover", "reclassify", "sp1", "--severity", "major", "--reason", "r")
    rec = json.loads(_ledger_lines(repo)[-1])
    assert rec["description"] == "the original text"
    assert rec["status"] == "open"
    assert rec["source"] == "s"


def test_reclassify_can_lower_severity_too(repo):
    """Triage runs both ways: an over-flagged item must be demotable, or the
    only safe move is to leave everything blocking."""
    run(repo, "spillover", "add", "--source", "s", "--desc", "d", "--id", "sp1",
        "--severity", "blocker")
    assert run(repo, "gates", "run").returncode != 0
    run(repo, "spillover", "reclassify", "sp1", "--severity", "minor",
        "--reason", "reread it: cosmetic, no data path")
    assert run(repo, "gates", "run").returncode == 0
