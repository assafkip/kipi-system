"""ASK-430 reproducer: a DEFAULTED severity must be distinguishable from an
ASSESSED one, and a row written before the field existed must read as `unknown`.

WHY THIS IS NOT A REPORTING NICETY. When this was specced, `severity` was a hint
for a human reading `gates run`. It is not any more: any deferred item becomes a
Linear issue worked by a machine, and `severity` is the ROUTING INPUT that
decides whether an item ever reaches one. `spillover add` defaults
`--severity minor` and records nothing distinguishing "nobody looked" from "we
judged it small", so after the fact the two are the same bytes.

Measured on the live ledger 2026-08-06 (read-only, `spillover list --open
--json`): 610 open items, 589 at `minor`, and ZERO carrying any provenance. So
"assessed minor" is currently unobservable, and a routing rule that keys on
`severity` is keying on a field whose value is indistinguishable from its
default.

THE TEST THAT DECIDES WHETHER THE FIELD IS HONEST is
`test_preexisting_row_reads_unknown_not_assessed`. Reading a missing
`severity_source` as "assessed" would launder ~610 unexamined rows as examined
in one deploy, which is the same hand-clear this ledger refuses everywhere else,
wearing a provenance field as a coat. Its mutant is documented in
MUTANTS.md-in-the-PR-body: flip the default to explicit/assessed, expect RED.

NOT IN SCOPE, deliberately: any bulk reclassification of the existing
population. Existing rows become MEASURABLE, not APPROVED.

None of these tests touch the live ledger. Every one builds its own repo under
tmp_path and passes `--repo-root`, so `_ledger_root`'s git lookup never reaches
the host checkout.
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
    """Import prd_runner as a module so the provenance READER can be called
    directly. The CLI covers the writer; a routing consumer (the ratchet) will
    import the reader, so the reader is tested at the surface it is used from."""
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "prd_runner_provenance_test", PRD_RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / ".prd-os").mkdir(parents=True)
    (r / ".git").mkdir()  # plain dir: git lookup fails, falls back to this root
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


def rows(repo: Path) -> list[dict]:
    """Every EVENT on disk, in file order. Deliberately not the folded view:
    provenance is a property of the event that was written, and folding would
    hide a second event overwriting the first."""
    text = ledger(repo).read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def row_by_id(repo: Path, sid: str) -> dict:
    matches = [r for r in rows(repo) if r["id"] == sid]
    assert matches, f"no row with id {sid!r} in {[r['id'] for r in rows(repo)]}"
    return matches[-1]


def preexisting(repo: Path, sid: str, severity: str = "minor") -> None:
    """Append a row in the PRE-CHANGE shape: no `severity_source` key at all.

    Written as raw bytes rather than through the CLI on purpose. The CLI will
    stamp provenance after this change, so routing it through the CLI would
    produce a row that cannot exist in the population this test is about -- the
    ~610 rows already on disk. The fixture has to come from the producer that
    actually made them, which was `spillover add` BEFORE this commit.
    """
    ledger(repo).parent.mkdir(parents=True, exist_ok=True)
    with ledger(repo).open("a") as fh:
        fh.write(json.dumps({
            "id": sid, "source": "legacy-source",
            "description": "a row written before severity_source existed",
            "severity": severity, "status": "open",
            "created_at": "2026-07-01T00:00:00Z",
        }) + "\n")


# --------------------------------------------------------------------------
# GREEN CONTROL. Must pass BEFORE and AFTER the change. If this ever goes red
# alongside the others, the tests are failing for a setup reason (a broken
# fixture, a repo that is not where I think it is) rather than for the absence
# of provenance, and every RED below is uninformative.
# --------------------------------------------------------------------------

def test_control_add_still_defaults_severity_to_minor(repo: Path):
    """The DEFAULT VALUE does not change; only whether we record that it was a
    default. A test suite that cannot show one thing holding still while another
    moves cannot tell a real failure from a broken harness."""
    assert run(repo, "spillover", "add", "--source", "ctl",
               "--desc", "control item", "--id", "sp-ctl00001").returncode == 0
    assert row_by_id(repo, "sp-ctl00001")["severity"] == "minor"


# --------------------------------------------------------------------------
# DELIVERABLE 1: `add` records WHERE the severity came from.
# --------------------------------------------------------------------------

def test_add_without_severity_flag_records_default(repo: Path):
    assert run(repo, "spillover", "add", "--source", "s",
               "--desc", "no flag passed", "--id", "sp-def00001").returncode == 0
    rec = row_by_id(repo, "sp-def00001")
    assert rec["severity"] == "minor"
    assert rec["severity_source"] == "default"


def test_add_with_explicit_severity_records_explicit(repo: Path):
    assert run(repo, "spillover", "add", "--source", "s", "--desc", "flag passed",
               "--severity", "major", "--id", "sp-exp00001").returncode == 0
    rec = row_by_id(repo, "sp-exp00001")
    assert rec["severity"] == "major"
    assert rec["severity_source"] == "explicit"


def test_explicit_minor_is_distinguishable_from_defaulted_minor(repo: Path):
    """THE POINT OF THE FIELD. Both rows read `severity: minor`; one was judged
    small and one was never looked at. Before this change the two rows were
    byte-identical apart from id and timestamp, so no routing rule and no report
    could tell them apart -- which is exactly the founder's "550 sit at minor,
    untriaged" claim being unprovable AND unrefutable."""
    run(repo, "spillover", "add", "--source", "s", "--desc", "never looked",
        "--id", "sp-aaa00001")
    run(repo, "spillover", "add", "--source", "s", "--desc", "judged small",
        "--severity", "minor", "--id", "sp-bbb00001")
    defaulted = row_by_id(repo, "sp-aaa00001")
    assessed = row_by_id(repo, "sp-bbb00001")
    assert defaulted["severity"] == assessed["severity"] == "minor"
    assert defaulted["severity_source"] != assessed["severity_source"]


# --------------------------------------------------------------------------
# DELIVERABLE 3: pre-existing rows read `unknown`, NEVER `assessed`.
# This is the honesty test. Ordered before deliverable 2 because the report's
# correctness depends on the reader's.
# --------------------------------------------------------------------------

def test_preexisting_row_reads_unknown_not_assessed(repo: Path):
    """A row with no `severity_source` predates the field. Nobody knows whether
    anyone looked at it, and "we do not know" is the only honest answer.

    MUTANT (the one the issue names): make the reader return `explicit` for a
    missing key. That single change would relabel every one of the ~610 rows on
    the live ledger as examined without anyone reading one of them. This
    assertion is what stands between that mutant and the ledger.
    """
    runner = _load_runner()
    legacy = {"id": "sp-old00001", "severity": "minor", "status": "open"}
    assert runner.severity_source(legacy) == "unknown"
    assert runner.severity_source(legacy) != "explicit"


def test_unknown_provenance_survives_a_round_trip_through_the_ledger(repo: Path):
    """Not just the in-memory reader: a legacy row read back off disk must still
    report unknown. A reader that is honest about a dict but whose caller
    back-fills a default on read would pass the test above and still launder the
    population."""
    runner = _load_runner()
    preexisting(repo, "sp-old00002")
    result = run(repo, "spillover", "list", "--open", "--json")
    assert result.returncode == 0
    (loaded,) = [r for r in json.loads(result.stdout) if r["id"] == "sp-old00002"]
    assert "severity_source" not in loaded, (
        "reading must not INVENT provenance; the ledger is append-only and a "
        "read that back-fills a field is writing history it did not observe")
    assert runner.severity_source(loaded) == "unknown"


def test_garbage_provenance_reads_unknown_not_explicit(repo: Path):
    """Fail toward `unknown`, matching `_is_blocking_severity`'s fail-closed
    direction. An unrecognised value is not evidence that someone assessed it."""
    runner = _load_runner()
    for junk in ("assessed", "ASSESSED", "", None, "yes", 1, {}):
        assert runner.severity_source({"severity_source": junk}) == "unknown"


# --------------------------------------------------------------------------
# DELIVERABLE 2: the REPORT splits the bucket -- and so does the ROUTING path.
# `gates run` was the only consumer when this was specced. The ratchet is now a
# second one, and it decides whether an item ever reaches a machine, so the
# split has to be a FUNCTION both can call rather than a string only the report
# can read.
# --------------------------------------------------------------------------

def test_report_splits_assessed_from_never_triaged(repo: Path):
    run(repo, "spillover", "add", "--source", "s", "--desc", "never looked",
        "--id", "sp-nt000001")
    run(repo, "spillover", "add", "--source", "s", "--desc", "judged small",
        "--severity", "minor", "--id", "sp-as000001")
    out = run(repo, "gates", "run").stdout
    assert "minor-or-untriaged" not in out, (
        "one bucket is the defect: it reports 'nobody looked' and 'we judged it "
        "small' as the same number")
    assert "1 assessed" in out
    assert "1 untriaged" in out


def test_report_does_not_count_unknown_rows_as_assessed(repo: Path):
    """The laundering path, at the REPORT surface. Three legacy rows and one
    genuinely assessed row must not print as four assessed."""
    preexisting(repo, "sp-old00003")
    preexisting(repo, "sp-old00004")
    preexisting(repo, "sp-old00005")
    run(repo, "spillover", "add", "--source", "s", "--desc", "judged small",
        "--severity", "minor", "--id", "sp-as000002")
    out = run(repo, "gates", "run").stdout
    assert "1 assessed" in out
    assert "3 unknown" in out
    assert "4 assessed" not in out


def test_routing_consumer_can_import_the_split_instead_of_re_deriving(repo: Path):
    """prd-os OWNS this ledger and therefore owns its vocabulary. The ratchet
    (`q-system/.q-system/scripts/spillover-ratchet.py`, ASK-457) currently
    selects rows with a hardcoded `severity == "minor"` literal, which is a
    derivation split waiting to drift -- the same shape as
    FINDING_TO_LEDGER_SEVERITY living here rather than in the two findings
    writers. Ship the classifier as an importable function so the second
    consumer has something to import; a report-only string would force it to
    re-derive.

    Direction matters: the CONSUMER imports from the OWNER. prd-os must never
    import a severity vocabulary from kipi-dsse or from q-system to get this --
    that swaps one derivation split for a worse one.
    """
    runner = _load_runner()
    items = [
        {"id": "a", "severity": "minor", "severity_source": "default"},
        {"id": "b", "severity": "minor", "severity_source": "explicit"},
        {"id": "c", "severity": "minor"},                      # legacy
        {"id": "d", "severity": "low", "severity_source": "default"},
    ]
    split = runner.spillover_provenance_split(items)
    assert [r["id"] for r in split["assessed"]] == ["b"]
    assert [r["id"] for r in split["never_triaged"]] == ["a", "d"]
    assert [r["id"] for r in split["unknown"]] == ["c"]
    # Every input lands in exactly one bucket: a routing consumer that iterates
    # the buckets must not silently drop a row (the ratchet dropping low/medium
    # is sp-61faebb3, filed, not fixed here).
    assert sum(len(v) for v in split.values()) == len(items)


# --------------------------------------------------------------------------
# DELIVERABLE 4: `reclassify` is an assessment by construction.
# --------------------------------------------------------------------------

def test_reclassify_stamps_explicit(repo: Path):
    run(repo, "spillover", "add", "--source", "s", "--desc", "never looked",
        "--id", "sp-rec00001")
    assert row_by_id(repo, "sp-rec00001")["severity_source"] == "default"
    result = run(repo, "spillover", "reclassify", "sp-rec00001",
                 "--severity", "major", "--reason", "it is a data-loss path")
    assert result.returncode == 0, result.stderr
    rec = row_by_id(repo, "sp-rec00001")
    assert rec["severity"] == "major"
    assert rec["severity_source"] == "explicit"
    assert rec["reclassified_from"] == "minor"


def test_reclassify_promotes_a_legacy_row_out_of_unknown(repo: Path):
    """The ONLY sanctioned way an existing row becomes assessed: someone states
    a reason, one item at a time, through an append-only event. There is no bulk
    path here and this issue does not add one."""
    runner = _load_runner()
    preexisting(repo, "sp-old00006")
    assert runner.severity_source(row_by_id(repo, "sp-old00006")) == "unknown"
    assert run(repo, "spillover", "reclassify", "sp-old00006",
               "--severity", "minor",
               "--reason", "read it; it is a cosmetic log-format nit").returncode == 0
    assert runner.severity_source(row_by_id(repo, "sp-old00006")) == "explicit"
