"""scs-validated-event-fold reproducer: the spillover fold must FAIL CLOSED on a
malformed ledger instead of silently skipping the line.

Reproducer-first. Before `spillover_events.py` exists and is wired into
`_read_spillover`, the tests below fail against the shipped behaviour:
`except json.JSONDecodeError: continue` (prd_runner.py) drops the bad line and
returns a fold that is missing whatever that line said.

THE PROPERTY THAT MATTERS is not tidiness, it is that a corrupt line cannot
quietly REMOVE a blocking finding from the standing gate. `gates run` is the
no-bypass re-proof of last resort; a ledger reader that skips what it cannot
parse turns any write-tear, partial flush, or hand-edit into a silent
gate-clearing event. A gate that reports safety it cannot provide is worse than
no gate, because it launders "we have enforcement" (the same reasoning that
moved the ledger to a single git-common-dir root after 26 worktree copies hid
71 findings from main).

None of these tests touch the real ledger. Every one builds its own repo under
tmp_path; `.git` is a plain directory so `_ledger_root`'s git lookup fails and
falls back to that tmp root.
"""

from __future__ import annotations

import importlib.util
import json
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
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("prd_runner_fold_test", PRD_RUNNER)
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


def ledger(repo: Path) -> Path:
    return repo / ".prd-os" / "spillover.jsonl"


def event(**over) -> str:
    rec = {
        "id": "sp-aaaa1111",
        "source": "test-source",
        "description": "a real finding",
        "severity": "minor",
        "status": "open",
        "created_at": "2026-08-06T00:00:00Z",
    }
    rec.update(over)
    return json.dumps(rec)


def write_ledger(repo: Path, *lines: str) -> None:
    ledger(repo).write_text("".join(line + "\n" for line in lines))


# --------------------------------------------------------------------------
# 1. The live defect: a corrupt line must not be skipped.
# --------------------------------------------------------------------------

def test_invalid_json_line_is_refused_with_line_evidence(repo: Path):
    """A line that is not JSON fails the read closed, naming the line number.

    Shipped behaviour skips it and returns the rest, so this asserts the
    REFUSAL, not merely that the good records survived.
    """
    write_ledger(repo, event(id="sp-good0001"), "{not json at all", event(id="sp-good0002"))
    result = run(repo, "spillover", "check")
    assert result.returncode == 2, (
        f"expected a fail-closed exit 2 on a corrupt ledger, got {result.returncode}.\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}")
    # Line evidence: the operator has to be able to find the bad line.
    assert ":2:" in result.stderr, f"no line-2 evidence in stderr: {result.stderr!r}"
    # A REFUSAL, not a crash. An uncaught raise exits 1 -- the same code
    # `spillover check` uses for "there are open items" -- so a traceback would
    # be indistinguishable from normal operation to any caller.
    assert "Traceback" not in result.stderr, (
        f"refusal arrived as an uncaught exception: {result.stderr!r}")


def test_corrupt_line_cannot_hide_a_blocking_item_from_the_gate(repo: Path):
    """THE security property. A torn write after a blocker must not turn the
    gate green.

    This is the test the whole issue exists for: with the silent skip, deleting
    half of a blocker's line is a way to clear the standing gate that leaves no
    trace anywhere.
    """
    blocker = event(id="sp-blocking1", severity="blocker",
                    description="a real blocking finding")
    # A torn write: the blocker's record truncated mid-line, exactly what a
    # partial flush or a crashed writer leaves behind.
    write_ledger(repo, event(id="sp-ordinary1"), blocker[: len(blocker) // 2])
    result = run(repo, "gates", "run")
    assert result.returncode != 0, (
        "gates run went GREEN over a ledger it could not fully parse; a torn "
        f"write is a silent gate-clear.\nstdout={result.stdout!r}\nstderr={result.stderr!r}")
    combined = result.stdout + result.stderr
    assert "spillover.jsonl" in combined, (
        f"gate failed but never named the unreadable ledger: {combined!r}")
    # Without this, a traceback satisfies the `!= 0` assertion above AND puts
    # the ledger path in the output, passing this test for the wrong reason.
    assert "Traceback" not in combined, (
        f"gate failed by crashing rather than refusing: {combined!r}")


# --------------------------------------------------------------------------
# 2. Schema validation: a parseable line can still be an invalid event.
# --------------------------------------------------------------------------

def test_unknown_status_is_refused(repo: Path):
    """`status` drives the gate. An unrecognised value must not be folded in.

    Same fail-closed reasoning the severity allowlist already uses: the word a
    human reaches for under pressure is the one the allowlist lacks, so an
    unknown value must be loud, never a silent pass.
    """
    write_ledger(repo, event(id="sp-weird001", status="kinda-done"))
    result = run(repo, "spillover", "check")
    assert result.returncode == 2, (
        f"unknown status was accepted, got exit {result.returncode}.\n"
        f"stderr={result.stderr!r}")
    assert "kinda-done" in result.stderr, (
        f"refusal did not name the offending value: {result.stderr!r}")


def test_record_without_an_id_is_refused(repo: Path):
    """An id-less record is unaddressable: it can never be resolved or voided.

    Shipped behaviour drops it (`if rec.get("id")`), so a finding written
    without an id vanishes rather than blocking anything.
    """
    write_ledger(repo, json.dumps({"status": "open", "description": "orphan"}))
    result = run(repo, "spillover", "check")
    assert result.returncode == 2, (
        f"id-less record was silently dropped, got exit {result.returncode}.\n"
        f"stderr={result.stderr!r}")


def test_non_object_line_is_refused(repo: Path):
    """Valid JSON that is not an object (a bare list/string) is not an event."""
    write_ledger(repo, json.dumps(["not", "an", "event"]))
    result = run(repo, "spillover", "check")
    assert result.returncode == 2, (
        f"non-object line was skipped, got exit {result.returncode}.\n"
        f"stderr={result.stderr!r}")


# --------------------------------------------------------------------------
# 3. Fold order: file order is authority, timestamps are evidence.
# --------------------------------------------------------------------------

def test_duplicate_id_folds_to_the_last_occurrence_in_file_order(repo: Path):
    """Last write wins, and `last` means last IN THE FILE."""
    write_ledger(
        repo,
        event(id="sp-dupe0001", status="open"),
        event(id="sp-dupe0001", status="resolved", void_reason="not a real item"),
    )
    result = run(repo, "spillover", "check")
    assert result.returncode == 0, (
        f"the resolving event did not win the fold.\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}")


def test_out_of_order_timestamp_does_not_reorder_the_fold(repo: Path):
    """A later file line with an EARLIER timestamp still wins.

    Resolved decision in the parent PRD: "append order is deterministic;
    timestamps are evidence, not ordering authority". Clocks skew across
    machines and worktrees; byte order in an append-only file does not.

    This is the mutation-sensitive one: an implementation that sorts by
    `created_at` before folding passes every other test in this file and fails
    only here.
    """
    write_ledger(
        repo,
        event(id="sp-clock001", status="open", created_at="2026-08-06T12:00:00Z"),
        event(id="sp-clock001", status="resolved", void_reason="voided",
              created_at="2026-01-01T00:00:00Z"),
    )
    result = run(repo, "spillover", "check")
    assert result.returncode == 0, (
        "a timestamp older than the prior event reordered the fold; file order "
        f"must win.\nstdout={result.stdout!r}\nstderr={result.stderr!r}")


# --------------------------------------------------------------------------
# 4. The valid-ledger path still works (a validator that refuses everything
#    would pass every test above).
# --------------------------------------------------------------------------

def test_a_valid_ledger_still_folds_and_reports_open_items(repo: Path):
    """Negative self-test for the guard itself.

    Without this, a `return 2` hardcoded at the top of the reader satisfies
    every refusal test on this page.
    """
    write_ledger(repo, event(id="sp-open0001"), event(id="sp-open0002"))
    result = run(repo, "spillover", "check")
    assert result.returncode == 1, (
        f"expected exit 1 (two open items), got {result.returncode}.\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}")
    assert "sp-open0001" in result.stderr and "sp-open0002" in result.stderr


def test_every_status_and_severity_the_live_ledger_uses_is_accepted(repo: Path):
    """Fail-closed must not brick the real fleet ledger.

    Measured against `.prd-os/spillover.jsonl` on 2026-08-06 (860 events):
    statuses open/resolved/promoted, severities minor/major/high/medium/low/
    blocker. `promoted` appears nowhere in the parent PRD's event list, so a
    validator written from the PRD alone would have refused 7 live records and
    taken every prd-os command down with it.
    """
    lines = [event(id="sp-st%02d" % i, status=s)
             for i, s in enumerate(("open", "resolved", "promoted"))]
    lines += [event(id="sp-sv%02d" % i, status="resolved", severity=v)
              for i, v in enumerate(
                  ("minor", "major", "high", "medium", "low", "blocker"))]
    write_ledger(repo, *lines)
    result = run(repo, "spillover", "check")
    assert result.returncode == 1, (
        f"a status or severity the live ledger uses was refused.\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}")


# --------------------------------------------------------------------------
# 5. sp-940e1013: reads fail closed, so writes must validate.
#
# Making _read_spillover strict created a new foot-gun: a writer that appends a
# malformed record now bricks EVERY prd-os read until a human edits the file by
# hand. Previously the lenient reader absorbed a bad write. The write path has
# to refuse first, and it has to refuse WITHOUT touching the file.
#
# Validation here takes NO lock on purpose. `_spillover_lock` is LOCK_EX on a
# separate fd and `reclassify` already holds it across its read-modify-append;
# acquiring it again inside the append would deadlock the process against
# itself. Validating a record is pure -- it reads nothing -- so it needs no lock.
# --------------------------------------------------------------------------

def _cfg_for(repo: Path):
    runner = _load_runner()
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
    from config import load as load_config
    return runner, load_config(repo, strict=True)


@pytest.mark.parametrize("bad,label", [
    ({"id": "sp-x", "status": "kinda-done", "description": "d"}, "unknown status"),
    ({"status": "open", "description": "d"}, "no id"),
    ({"id": "  ", "status": "open", "description": "d"}, "blank id"),
])
def test_append_refuses_an_invalid_record_and_leaves_the_ledger_untouched(
        repo: Path, bad, label):
    """The refusal must happen BEFORE the write, not after.

    Asserting the exception alone would pass an implementation that appends and
    then raises -- which is the worst case, since the bad line is now on disk
    AND the caller saw an error. So this asserts the file's exact bytes.
    """
    runner, cfg = _cfg_for(repo)
    write_ledger(repo, event(id="sp-before01"))
    before = ledger(repo).read_bytes()
    with pytest.raises(runner.SpilloverLedgerError):
        runner._spillover_append(cfg, bad)
    assert ledger(repo).read_bytes() == before, (
        f"a refused append ({label}) still modified the ledger")


def test_a_refused_append_leaves_the_ledger_readable(repo: Path):
    """THE property sp-940e1013 is about: a bad write must not brick reads.

    Without write-side validation the malformed record lands, and every
    subsequent `spillover check` / `gates run` exits 2 on an unreadable ledger
    until someone hand-edits it.
    """
    runner, cfg = _cfg_for(repo)
    write_ledger(repo, event(id="sp-alive001"))
    with pytest.raises(runner.SpilloverLedgerError):
        runner._spillover_append(cfg, {"id": "sp-bad", "status": "nonsense"})
    result = run(repo, "spillover", "check")
    assert result.returncode == 1, (
        "the ledger stopped being readable after a refused append; exit 1 means "
        f"one open item, which is the healthy state.\nstderr={result.stderr!r}")
    assert "sp-alive001" in result.stderr


def test_a_valid_append_still_writes(repo: Path):
    """Negative self-test. A validator that refuses everything passes the three
    tests above and breaks the whole product."""
    runner, cfg = _cfg_for(repo)
    write_ledger(repo, event(id="sp-first001"))
    runner._spillover_append(cfg, json.loads(event(id="sp-second01")))
    assert "sp-second01" in ledger(repo).read_text()
    result = run(repo, "spillover", "check")
    assert result.returncode == 1
    assert "sp-second01" in result.stderr


def test_the_cli_add_path_still_works_end_to_end(repo: Path):
    """Wiring proof: validation sits on the real CLI write path, not only on a
    directly-called helper."""
    result = run(repo, "spillover", "add", "--source", "t", "--desc", "a finding")
    assert result.returncode == 0, f"add broke: {result.stderr!r}"
    assert run(repo, "spillover", "check").returncode == 1
