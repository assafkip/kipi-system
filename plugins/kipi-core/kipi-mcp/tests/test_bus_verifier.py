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


def _real_paths_env(monkeypatch, tmp_path, instance="promo-inst"):
    """Point the REAL KipiPaths at a tmp base and return its canonical dir.

    Deliberately uses no monkeypatch of the predicate and no stub of KipiPaths: the
    whole point of these two cases is to drive the production code path.
    """
    base = tmp_path / "plugin-data"
    repo = tmp_path / "repo"
    monkeypatch.setenv("KIPI_PLUGIN_DATA", str(base))
    monkeypatch.setenv("KIPI_INSTANCE", instance)
    # canonical_dir is REGISTRY-derived now, not {base}/instances/<name>/canonical.
    # That change is exactly what this pair of cases was written to anticipate:
    # "when the path contract repoints canonical_dir at a live tree, the promotion
    # happens on its own with no edit here" (bus_verifier docstring). The predicate
    # is untouched; only where the tree lives moved.
    canonical = repo / "q-system" / "canonical"
    canonical.mkdir(parents=True, exist_ok=True)
    base.mkdir(parents=True, exist_ok=True)
    (base / "instance-registry.json").write_text(json.dumps({
        "skeleton": {"path": str(repo)},
        "instances": [{"name": instance, "path": str(repo),
                       "subtree_prefix": "q-system", "instance_q_dir": None}],
        "excluded": [], "eliminated": [],
    }), encoding="utf-8")
    return canonical


def test_promotion_predicate_true_branch_is_reachable(monkeypatch, tmp_path):
    """REPRODUCER (Codex PR #240 blocker). The promotion predicate used to ask
    "is canonical_dir under the plugin-data base?" -- and `KipiPaths.canonical_dir`
    is DEFINED as `{base}/instances/<name>/canonical` where `{base}` is exactly
    KIPI_PLUGIN_DATA or ~/.kipi-system. So the answer was yes for every reachable
    configuration: a tautology, not a sequencing guard. Its true branch could only
    ever be entered by monkeypatching the predicate itself, which is how three
    tests above reached the required branch and why the check stayed permanently
    optional in production.

    This case drives the real code path with a canonical tree that HAS content.
    """
    canonical = _real_paths_env(monkeypatch, tmp_path)
    (canonical / "decisions.md").write_text("### RULE-2026-08-18-A: real content\n")
    assert BV.canonical_digest_is_required() is True


def test_promotion_predicate_false_while_the_canonical_tree_is_empty(monkeypatch, tmp_path):
    """The other half, same real code path. SEQUENCING (finding-27): the resolved
    canonical dir holds ZERO files today (measured 2026-08-22, and re-measured on
    this machine: 1 instance dir, canonical/ present, 0 .md files), so the digest
    stays OPTIONAL and no phase-1 run reds. It promotes itself the moment the path
    contract points canonical_dir at a tree that actually holds content."""
    _real_paths_env(monkeypatch, tmp_path, instance="empty-inst")
    assert BV.canonical_digest_is_required() is False


def test_promotion_predicate_fails_toward_optional_when_it_cannot_tell(monkeypatch):
    """A crash in the predicate must not be able to cause the outage it exists to
    prevent, so an unresolvable path contract means NOT required."""
    def _boom():
        raise RuntimeError("path contract unresolvable")

    monkeypatch.setattr(BV, "_canonical_content_present", _boom)
    assert BV.canonical_digest_is_required() is False
