#!/usr/bin/env python3
"""A blocking finding becomes a Linear issue without the founder in the middle.

why (founder, 2026-08-13, verbatim): "notification dont work for me. I get a ton of
notifications and all id do is open an instance and say 'make an issue for it'.
whats the point of having me in the middle" -- and "if an engineering decision needs
to be made, it can and should be made by Sana, not wait for me".

So: a DoR supplied at file time auto-promotes, and a blocking item WITHOUT one is
handed to Sana's queue rather than dropped or escalated to him.

The first version of this feature REFUSED a blocking add with no DoR and broke 34
tests. That was the design telling the truth: many spillover items are created by
machinery (a `deferred` finding auto-creates one, sp-5bcfbfe8) where nothing holds
the context a DoR needs. Refusing there breaks the auto-capture that stops orphans,
which is worse than a missing DoR. Hence hand-off, not refusal -- and this file pins
that, so nobody "tightens" it back into a refusal.
"""
import json
import subprocess
import sys
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "prd_runner.py"


def _add(repo, *extra, severity="minor", desc="a finding", source="t-1"):
    return subprocess.run(
        [sys.executable, str(RUNNER), "--repo-root", str(repo), "spillover", "add",
         "--severity", severity, "--source", source, "--desc", desc, *extra],
        capture_output=True, text=True)


def _init(tmp_path):
    (tmp_path / ".prd-os").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".prd-os" / "config.json").write_text(json.dumps({"version": 1}))
    return tmp_path


def test_a_minor_note_needs_no_dor_and_files_no_issue(tmp_path):
    """Notes stay cheap. Demanding a DoR for every passing observation is how a
    ledger stops being written to at all."""
    repo = _init(tmp_path)
    res = _add(repo, severity="minor")
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out["status"] == "open"
    assert "promotion" not in out


def test_a_blocking_item_without_a_dor_is_handed_to_sana_not_refused(tmp_path):
    """It must still be RECORDED. A refusal here would break machine-created
    spillover and lose the finding entirely."""
    repo = _init(tmp_path)
    for severity in ("major", "blocker"):
        res = _add(repo, severity=severity, source=f"t-{severity}")
        assert res.returncode == 0, res.stderr
        out = json.loads(res.stdout.strip().splitlines()[-1])
        assert out["status"] == "open", out
        assert out["promotion"]["status"] == "needs_dor", out
        assert out["promotion"]["owner"] == "sana", out


def test_the_founder_is_never_named_as_the_owner_of_a_handoff(tmp_path):
    """The whole point. If this ever says 'founder', the router is back."""
    repo = _init(tmp_path)
    res = _add(repo, severity="blocker", source="t-owner")
    blob = json.dumps(json.loads(res.stdout.strip().splitlines()[-1])).lower()
    assert "founder" not in blob
    assert "notify" not in blob


def test_a_dor_with_no_promote_records_without_filing(tmp_path):
    """The escape hatch, so a caller can bank a DoR without touching Linear."""
    repo = _init(tmp_path)
    res = _add(repo, "--dor", "# DoR\nallowed files: none", "--no-promote",
               severity="major", source="t-nopromote")
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out["status"] == "open"
    # Explicitly suppressed, NOT "needs_dor": a DoR was supplied. Reporting the
    # opposite of the truth is the defect class this ledger exists to catch.
    assert out["promotion"]["status"] == "suppressed", out


def test_promotion_failure_keeps_the_item_and_owns_the_next_step(tmp_path):
    """A promotion that cannot run must never lose the finding: it degrades to the
    behaviour that existed before this feature, loudly."""
    sys.path.insert(0, str(RUNNER.parent))
    import prd_runner as P

    class Args:
        desc = "something"
        title = None
    class Cfg:
        repo_root = "/nonexistent-repo"

    res = P._spillover_autopromote(Cfg(), "sp-x", Args(), "# DoR")
    assert res["status"] in ("skipped", "failed", "not_promoted"), res
    assert "founder" not in json.dumps(res).lower()


def test_needs_dor_lists_the_queue(tmp_path):
    repo = _init(tmp_path)
    _add(repo, severity="blocker", source="t-queue", desc="needs a dor")
    _add(repo, severity="minor", source="t-quiet", desc="just a note")
    res = subprocess.run(
        [sys.executable, str(RUNNER), "--repo-root", str(repo), "spillover", "needs-dor"],
        capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert "needs a dor" in res.stdout
    assert "just a note" not in res.stdout
    assert "1 blocking item(s) need a DoR" in res.stdout
