#!/usr/bin/env python3
"""RED FIRST. Issue mbl-draft-sent-pairing (prd-morning-brief-learns, Codex
finding-7). Pairing is by Gmail id only. Every run here uses a tmp_path ledger
and a tmp_path metrics.db (the fable-discipline lint refuses a live DB path in
a test), and the runner is injected; the live runner is refused under pytest.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
MODULE = SCRIPTS / "draft-vs-sent.py"


@pytest.fixture(scope="module")
def dvs():
    assert MODULE.is_file(), f"missing: {MODULE}"
    spec = importlib.util.spec_from_file_location("draft_vs_sent", MODULE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SUBJECT = "Pilot kickoff"


def _ledger(dvs, tmp_path):
    """Two drafts, SAME subject, SAME contact (Codex standard finding on this
    issue: without a subject in the ledger the same-subject case was untestable)."""
    ledger = tmp_path / "drafts-ledger.jsonl"
    dvs.record_draft("m-111", "Marta Kowalski", "Hi Marta, draft one about the pilot.", "brief", ledger, subject=SUBJECT)
    dvs.record_draft("m-222", "Marta Kowalski", "Hi Marta, draft two about the pilot.", "q-create", ledger, subject=SUBJECT)
    rows = dvs.read_ledger(ledger)
    assert rows[0]["subject"] == rows[1]["subject"] == SUBJECT
    return ledger


def _runner_with(sent: dict):
    def runner(prompt, tools):
        assert "m-111" in prompt and "m-222" in prompt, "every ledger id is looked up"
        return json.dumps(sent), None
    return runner


def test_two_drafts_same_subject_pair_only_by_id(dvs, tmp_path):
    ledger = _ledger(dvs, tmp_path)
    db = tmp_path / "metrics.db"
    sent = {"m-222": {"body": "Hi Marta, draft two about the pilot, now with the dates.",
                      "subject": SUBJECT, "to": ["marta@example.com"]}}
    result = dvs.pair(ledger, db, runner=_runner_with(sent))
    assert result["paired"] == 1 and result["unmatched"] == 1 and result["unmatched_ids"] == ["m-111"]
    rows = sqlite3.connect(str(db)).execute("SELECT action_type, original, edited FROM copy_edits").fetchall()
    assert len(rows) == 1 and rows[0][0].endswith("m-222")
    assert "draft two" in rows[0][1] and "now with the dates" in rows[0][2]


def test_identical_draft_and_sent_is_skipped_not_stored(dvs, tmp_path):
    ledger = _ledger(dvs, tmp_path)
    db = tmp_path / "metrics.db"
    sent = {"m-111": {"body": "Hi Marta, draft one about the pilot.", "to": ["marta@example.com"]},
            "m-222": {"body": "Hi Marta, draft two about the pilot.", "to": []}}
    result = dvs.pair(ledger, db, runner=_runner_with(sent))
    assert result["paired"] == 0 and result["identical"] == 2
    assert sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM copy_edits").fetchone()[0] == 0


def test_a_rerun_does_not_duplicate_rows(dvs, tmp_path):
    ledger = _ledger(dvs, tmp_path)
    db = tmp_path / "metrics.db"
    sent = {"m-222": {"body": "changed", "to": []}}
    dvs.pair(ledger, db, runner=_runner_with(sent))
    # The second run must not even look m-222 up again, so the strict runner
    # (which demands every ledger id in the prompt) is the wrong seam here.
    second = dvs.pair(ledger, db, runner=lambda p, t: (json.dumps(sent), None))
    assert second["paired"] == 0 and second["already_paired"] == 1
    assert sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM copy_edits").fetchone()[0] == 1


def test_a_rerun_on_a_later_day_does_not_duplicate_and_does_not_look_up_again(dvs, tmp_path):
    """Codex adversarial finding: the UNIQUE key includes the date, so day 2
    re-inserted every pair. Now a paired id is skipped before any lookup."""
    import datetime as dt
    ledger = _ledger(dvs, tmp_path)
    db = tmp_path / "metrics.db"
    sent = {"m-222": {"body": "changed", "subject": SUBJECT, "to": []}}
    day1 = dt.datetime(2026, 9, 8, 6, 30, tzinfo=dt.timezone.utc)
    dvs.pair(ledger, db, runner=_runner_with(sent), now=day1)
    looked_up = []

    def runner2(prompt, tools):
        looked_up.append(prompt)
        return json.dumps(sent), None
    second = dvs.pair(ledger, db, runner=runner2, now=day1 + dt.timedelta(days=1))
    assert second["paired"] == 0 and second["already_paired"] == 1
    assert sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM copy_edits").fetchone()[0] == 1
    assert looked_up and "m-222" not in looked_up[0] and "m-111" in looked_up[0]


def test_lookups_are_windowed_and_capped(dvs, tmp_path):
    """Codex adversarial finding: every historical id was sent in one prompt
    on every run. Only drafts from the last 30 days, at most 50 per run."""
    import datetime as dt
    ledger = tmp_path / "l.jsonl"
    now = dt.datetime(2026, 9, 8, 6, 30, tzinfo=dt.timezone.utc)
    old = (now - dt.timedelta(days=45)).isoformat(timespec="seconds")
    ledger.write_text(json.dumps({"draft_id": "m-old", "contact": "x", "body": "b", "source": "brief", "at": old}) + "\n")
    for i in range(60):
        dvs.record_draft(f"m-{i:03d}", "x", f"body {i}", "brief", ledger)
    prompts = []

    def runner(prompt, tools):
        prompts.append(prompt)
        return "{}", None
    result = dvs.pair(ledger, tmp_path / "metrics.db", runner=runner, now=now)
    assert result["too_old"] == 1 and result["looked_up"] == 50 and result["deferred"] == 10
    assert "m-old" not in prompts[0] and prompts[0].count("m-0") >= 50


def test_invalid_runner_entries_are_dropped_not_stored_or_crashed(dvs, tmp_path):
    """Codex adversarial finding: an entry with no string body was stored as
    an empty sent message, and body: null crashed at .strip()."""
    ledger = _ledger(dvs, tmp_path)
    db = tmp_path / "metrics.db"
    sent = {"m-111": {"to": ["marta@example.com"]}, "m-222": {"body": None, "subject": SUBJECT}}
    result = dvs.pair(ledger, db, runner=_runner_with(sent))
    assert result["paired"] == 0 and result["unmatched"] == 2
    assert sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM copy_edits").fetchone()[0] == 0


def test_similarity_is_never_used(dvs, tmp_path):
    """A sent message whose body matches a draft but whose id is unknown must
    NOT pair: the id is the only key."""
    ledger = _ledger(dvs, tmp_path)
    db = tmp_path / "metrics.db"
    # Same subject, same contact, same body as draft m-111, under an id the
    # ledger never issued: a subject- or body-based pairer would take it.
    sent = {"m-999": {"body": "Hi Marta, draft one about the pilot.", "subject": SUBJECT,
                      "to": ["marta@example.com"]}}
    result = dvs.pair(ledger, db, runner=_runner_with(sent))
    assert result["paired"] == 0 and result["unmatched"] == 2
    assert sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM copy_edits").fetchone()[0] == 0
    src = MODULE.read_text(encoding="utf-8")
    for banned in ("difflib.SequenceMatcher", "similar(", "fuzzy", "subject"):
        assert banned not in src.lower() or banned == "subject" and "subject, recipient or time similarity is never used" in src.lower(), banned


def test_record_draft_requires_an_id_and_appends(dvs, tmp_path):
    ledger = tmp_path / "l.jsonl"
    with pytest.raises(ValueError):
        dvs.record_draft("", "x", "body", "brief", ledger)
    dvs.record_draft("m-1", "x", "body", "brief", ledger)
    dvs.record_draft("m-2", "y", "body", "q-create", ledger)
    assert [r["draft_id"] for r in dvs.read_ledger(ledger)] == ["m-1", "m-2"]


def test_live_runner_is_refused_under_pytest(dvs, tmp_path):
    ledger = _ledger(dvs, tmp_path)
    with pytest.raises(RuntimeError, match="refused by draft-vs-sent"):
        dvs.pair(ledger, tmp_path / "metrics.db", runner=None)


def test_never_writes_exemplars(dvs):
    src = MODULE.read_text(encoding="utf-8")
    assert "exemplars.jsonl" in src and "NEVER q-consult/voice/exemplars.jsonl" in src
    assert "open(" not in src.replace("path.open(", "").replace(".open(\"a\"", ""), "the only file this writes is the ledger"


# --- issue mbl-draft-sent-projection (Codex finding-8): a projection, never the bodies

DRAFT = ("Hi Marta,\nThe unchanged sentence about the Zephyrine board stays.\n"
         "Draft wording: we could start next week.\nBest, A\ncc: ops@example.com")
SENT = ("Hi Marta,\nThe unchanged sentence about the Zephyrine board stays.\n"
        "Final wording: we start Monday the 8th.\nBest, A\ncc: ops@example.com")


def test_stored_row_holds_a_diff_not_the_bodies(dvs, tmp_path):
    ledger = tmp_path / "l.jsonl"
    dvs.record_draft("m-1", "Marta Kowalski", DRAFT, "brief", ledger, subject="Pilot")
    db = tmp_path / "metrics.db"
    dvs.pair(ledger, db, runner=lambda p, t: (json.dumps({"m-1": {"body": SENT, "to": ["marta@example.com"]}}), None),
             salt="unit-salt")
    original, edited, summary = sqlite3.connect(str(db)).execute(
        "SELECT original, edited, edit_summary FROM copy_edits").fetchone()
    blob = original + edited + (summary or "")
    assert "unchanged sentence" not in blob, "an unchanged line is not part of the delta"
    assert "Draft wording" in original and "Final wording" in edited
    assert "@" not in blob, "a recipient address reached the stored row"
    assert "Hi Marta" not in blob and "Best, A" not in blob


def test_a_test_never_creates_the_machine_salt_file(dvs, tmp_path, monkeypatch):
    monkeypatch.setattr(dvs, "SALT_FILE", tmp_path / "draft-salt")
    ledger = tmp_path / "l.jsonl"
    dvs.record_draft("m-1", "x", "a", "brief", ledger)
    dvs.pair(ledger, tmp_path / "metrics.db", runner=lambda p, t: (json.dumps({"m-1": {"body": "b", "to": []}}), None))
    assert not (tmp_path / "draft-salt").exists(), "pair() under pytest wrote a salt file"


def test_recipients_are_hashed_with_a_salt(dvs):
    a = dvs.hash_recipient("ops@example.com", "salt-a")
    b = dvs.hash_recipient("ops@example.com", "salt-b")
    assert a != b and len(a) == 12 and "@" not in a
    assert dvs.mask_recipients("mail ops@example.com and Marta.K@Example.com now", "salt-a").count("@") == 0


def test_purge_deletes_91_day_old_rows_and_keeps_89(dvs, tmp_path):
    import datetime as dt
    db = tmp_path / "metrics.db"
    now = dt.datetime(2026, 9, 8, 6, 30, tzinfo=dt.timezone.utc)
    con = dvs._connect(db)
    for days, ident in ((91, "old"), (89, "fresh")):
        con.execute("INSERT INTO copy_edits (date, contact_name, action_type, original, edited) VALUES (?,?,?,?,?)",
                    ((now - dt.timedelta(days=days)).strftime("%Y-%m-%d"), "x", f"draft-vs-sent:{ident}", "-a", "+b"))
    con.execute("INSERT INTO copy_edits (date, contact_name, action_type, original, edited) VALUES (?,?,?,?,?)",
                ((now - dt.timedelta(days=400)).strftime("%Y-%m-%d"), "x", "linkedin-comment", "-a", "+b"))
    con.commit()
    con.close()
    assert dvs.purge(db, now=now) == 1
    left = sqlite3.connect(str(db)).execute("SELECT action_type FROM copy_edits ORDER BY action_type").fetchall()
    assert left == [("draft-vs-sent:fresh",), ("linkedin-comment",)], "purge touched the wrong rows"


def test_this_file_runs_its_own_tests_under_python3():
    if os.environ.get("KIPI_SELFTEST_INNER"):
        pytest.skip("inner run")
    env = dict(os.environ, KIPI_SELFTEST_INNER="1")
    ok = subprocess.run([sys.executable, __file__], capture_output=True, text=True, env=env)
    assert ok.returncode == 0 and "passed" in ok.stdout, ok.stdout[-600:]
    none = subprocess.run([sys.executable, __file__, "-k", "no_such_test_zzz"], capture_output=True, text=True, env=env)
    assert none.returncode != 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
