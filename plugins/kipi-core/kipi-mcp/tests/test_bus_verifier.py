from __future__ import annotations

import json

import pytest

from kipi_mcp.bus_verifier import BusVerifier


@pytest.fixture
def verifier(tmp_path):
    return BusVerifier(tmp_path)


def _write(bus_dir, date, filename, data):
    d = bus_dir / date
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(json.dumps(data))


def test_phase0_all_required_present_and_valid(verifier, tmp_path):
    date = "2026-03-27"
    _write(tmp_path, date, "preflight.json", {"ready": True})
    _write(tmp_path, date, "energy.json", {"level": 3})
    result = verifier.verify(date, 0)
    assert result["pass"] is True
    assert result["phase"] == 0
    assert result["date"] == date
    assert all(r["status"] == "ok" for r in result["results"])


def test_phase0_missing_preflight(verifier, tmp_path):
    date = "2026-03-27"
    _write(tmp_path, date, "energy.json", {"level": 3})
    result = verifier.verify(date, 0)
    assert result["pass"] is False
    fail_results = [r for r in result["results"] if r["status"] == "fail"]
    assert any(r["file"] == "preflight.json" for r in fail_results)


def test_phase1_all_required_present(verifier, tmp_path):
    date = "2026-03-27"
    _write(tmp_path, date, "calendar.json", {"today": []})
    _write(tmp_path, date, "gmail.json", {"emails": []})
    _write(tmp_path, date, "notion.json", {"contacts": [], "actions": []})
    result = verifier.verify(date, 1)
    assert result["pass"] is True


def test_phase1_calendar_with_error_key(verifier, tmp_path):
    """A REQUIRED file carrying an error key is a hard fail, not a warning.

    INVERTED 2026-08-22 (prd-canonical-read-path-repair / crpr-bus-verifier-can-fail).
    This test previously asserted `warn`, which pinned the defect in place: the
    error branch ran BEFORE the structure check and emitted warn without setting
    all_pass=False, so any required file containing {"error": ...} produced
    pass:true while having delivered no data at all. The bug survived because a
    green test asserted it. Asserting `pass is False` is the fix; the warn/fail
    status is secondary, so this asserts the verdict, not the label.
    """
    date = "2026-03-27"
    _write(tmp_path, date, "calendar.json", {"error": "auth failed"})
    _write(tmp_path, date, "gmail.json", {"emails": []})
    _write(tmp_path, date, "notion.json", {"contacts": [], "actions": []})
    result = verifier.verify(date, 1)
    assert result["pass"] is False
    assert any(r["file"] == "calendar.json" and r["status"] == "fail"
               for r in result["results"])


def test_phase3_missing_required(verifier, tmp_path):
    date = "2026-03-27"
    _write(tmp_path, date, "linkedin-posts.json", {"posts": []})
    result = verifier.verify(date, 3)
    assert result["pass"] is False
    fail_files = [r["file"] for r in result["results"] if r["status"] == "fail"]
    assert "linkedin-dms.json" in fail_files
    assert "dp-pipeline.json" in fail_files


def test_phase4_tuesday_tl_content_missing_fails(verifier, tmp_path):
    date = "2026-03-24"  # Tuesday
    _write(tmp_path, date, "signals.json", {"selected_signal": "test"})
    result = verifier.verify(date, 4)
    assert result["pass"] is False
    fail_results = [r for r in result["results"] if r["status"] == "fail"]
    assert any(r["file"] == "tl-content.json" for r in fail_results)


def test_phase4_wednesday_tl_content_missing_ok(verifier, tmp_path):
    date = "2026-03-25"  # Wednesday
    _write(tmp_path, date, "signals.json", {"selected_signal": "test"})
    result = verifier.verify(date, 4)
    assert result["pass"] is True
    skip_results = [r for r in result["results"] if r["status"] == "skip"]
    assert any(r["file"] == "tl-content.json" for r in skip_results)


def test_phase5_hitlist_empty_actions_fails(verifier, tmp_path):
    date = "2026-03-27"
    _write(tmp_path, date, "temperature.json", {"scores": []})
    _write(tmp_path, date, "leads.json", {})
    _write(tmp_path, date, "hitlist.json", {"actions": []})
    result = verifier.verify(date, 5)
    assert result["pass"] is False
    fail_results = [r for r in result["results"] if r["status"] == "fail"]
    assert any(r["file"] == "hitlist.json" for r in fail_results)


def test_unknown_phase_passes(verifier, tmp_path):
    date = "2026-03-27"
    (tmp_path / date).mkdir(parents=True, exist_ok=True)
    result = verifier.verify(date, 99)
    assert result["pass"] is True
    assert result["results"] == []


def test_bus_dir_missing_raises(verifier):
    result = verifier.verify("2099-01-01", 0)
    assert result["pass"] is False
    assert any("does not exist" in r["detail"] for r in result["results"])


def test_phase0_invalid_json(verifier, tmp_path):
    date = "2026-03-27"
    d = tmp_path / date
    d.mkdir(parents=True, exist_ok=True)
    (d / "preflight.json").write_text("{bad json")
    _write(tmp_path, date, "energy.json", {"level": 3})
    result = verifier.verify(date, 0)
    assert result["pass"] is False
    fail_results = [r for r in result["results"] if r["status"] == "fail"]
    assert any(r["file"] == "preflight.json" for r in fail_results)


def test_phase0_structure_check_fails(verifier, tmp_path):
    date = "2026-03-27"
    _write(tmp_path, date, "preflight.json", {"ready": False})
    _write(tmp_path, date, "energy.json", {"level": 3})
    result = verifier.verify(date, 0)
    assert result["pass"] is False


# --------------------------------------------------------------------------
# canonical-digest.json: three independent defects, three independent tests.
# prd-canonical-read-path-repair-2026-08-22 / crpr-bus-verifier-can-fail.
#
# Before this work the check existed in phase 1's `checks` dict but in NEITHER
# `required` nor `optional`, so its lambda was never invoked once. It read as
# protection while being dead code.
# --------------------------------------------------------------------------

import kipi_mcp.bus_verifier as BV

# The exact all-empty digest captured from a real run, 2026-08-22.
EMPTY_DIGEST = {
    "talk_tracks": {}, "objections": [], "current_state": {}, "discovery": {},
    "decisions": [], "warnings": [
        "talk-tracks.md not found", "objections.md not found",
        "current-state.md not found", "discovery.md not found",
        "decisions.md not found",
    ],
    "valid": False,
}

# Codex finding-14's counterexample: NONEMPTY, and it must still be rejected.
PLACEHOLDER_DIGEST = {
    "talk_tracks": {"metaphor": "placeholder"}, "objections": [], "current_state": {},
    "discovery": {}, "decisions": [], "warnings": [], "valid": False,
}

# Shaped like the real live tree: no talk_tracks (retired to pointer docs), but
# real decisions and objections. This MUST pass or every run against real data reds.
LIVE_SHAPED_DIGEST = {
    "talk_tracks": {"metaphor": "", "definition": ""},
    "objections": [{"name": "Why this was retired rather than rewritten", "response": "x"}],
    "current_state": {}, "discovery": {},
    "decisions": [{"rule": "RULE-2026-08-18-A: ...", "summary": "y"}],
    "warnings": [], "valid": False,
}


def _phase1_baseline(bus_dir, date):
    _write(bus_dir, date, "calendar.json", {"today": []})
    _write(bus_dir, date, "gmail.json", {"emails": []})
    _write(bus_dir, date, "notion.json", {"contacts": [], "actions": []})


def test_canonical_digest_check_is_reachable(verifier, tmp_path, monkeypatch):
    """DEFECT 1: the file was in no list, so the lambda never ran."""
    monkeypatch.setattr(BV, "canonical_digest_is_required", lambda: True)
    date = "2026-03-27"
    _phase1_baseline(tmp_path, date)
    _write(tmp_path, date, "canonical-digest.json", EMPTY_DIGEST)
    result = verifier.verify(date, 1)
    files = [r["file"] for r in result["results"]]
    assert "canonical-digest.json" in files, "check never reached: file in no list"
    assert result["pass"] is False


def test_canonical_digest_rejects_empty_and_placeholder(verifier, tmp_path, monkeypatch):
    """DEFECT 2: key-presence passed both of these."""
    monkeypatch.setattr(BV, "canonical_digest_is_required", lambda: True)
    for i, digest in enumerate((EMPTY_DIGEST, PLACEHOLDER_DIGEST)):
        date = f"2026-04-0{i + 1}"
        _phase1_baseline(tmp_path, date)
        _write(tmp_path, date, "canonical-digest.json", digest)
        assert verifier.verify(date, 1)["pass"] is False, f"digest {i} wrongly passed"
    # ... and the live shape must still pass, or real data reds every run.
    date = "2026-04-09"
    _phase1_baseline(tmp_path, date)
    _write(tmp_path, date, "canonical-digest.json", LIVE_SHAPED_DIGEST)
    assert verifier.verify(date, 1)["pass"] is True


def test_canonical_digest_error_key_is_a_hard_fail(verifier, tmp_path, monkeypatch):
    """DEFECT 3: the error branch warned and left all_pass untouched, so this
    passed even after defects 1 and 2 were fixed. Assert on pass, never on warn."""
    monkeypatch.setattr(BV, "canonical_digest_is_required", lambda: True)
    date = "2026-03-28"
    _phase1_baseline(tmp_path, date)
    _write(tmp_path, date, "canonical-digest.json", {"error": "canonical digest unavailable"})
    assert verifier.verify(date, 1)["pass"] is False


def test_sequencing_both_branches_of_the_promotion_predicate(verifier, tmp_path, monkeypatch):
    """The promotion must be OPTIONAL while canonical_dir is still plugin-data,
    or wiring this in reds every phase-1 run on 23 instances at once.
    Both branches asserted: a predicate whose false branch is never exercised
    reports success by default."""
    date = "2026-03-29"
    _phase1_baseline(tmp_path, date)  # digest deliberately absent

    monkeypatch.setattr(BV, "canonical_digest_is_required", lambda: False)
    res = verifier.verify(date, 1)
    assert res["pass"] is True, "optional branch must not red a run with no digest"
    assert any(r["file"] == "canonical-digest.json" and r["status"] == "skip"
               for r in res["results"]), "optional branch must still reach the file"

    monkeypatch.setattr(BV, "canonical_digest_is_required", lambda: True)
    assert verifier.verify(date, 1)["pass"] is False, "required branch must red a missing digest"


def test_promotion_predicate_reads_the_real_path_contract(monkeypatch):
    """PRECONDITION (finding-27). While canonical_dir resolves under the plugin-data
    base this is False, and that is the intended block: it flips to True only once
    srsa-authoritative-path-contract lands. Fails toward NOT-required so a crash
    here cannot cause the outage the predicate exists to prevent."""
    monkeypatch.setenv("KIPI_PLUGIN_DATA", "/tmp/some-plugin-data")
    monkeypatch.setattr(BV, "KipiPaths", None, raising=False)
    assert BV._canonical_dir_is_plugin_data() is True
