#!/usr/bin/env python3
"""RED FIRST. Issue mbl-friction-artifact (prd-morning-brief-learns, Codex
finding-18). Every case here failed before friction-note.sh and
weekly-improve.py existed. Live paths are never touched: the ledger is a
tmp_path file via KIPI_FRICTION_FILE, and slack_founder refuses under
PYTEST_CURRENT_TEST (asserted, not assumed).
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
NOTE = SCRIPTS / "friction-note.sh"
WEEKLY = SCRIPTS / "weekly-improve.py"


@pytest.fixture(scope="module")
def weekly():
    assert WEEKLY.is_file(), f"missing: {WEEKLY}"
    spec = importlib.util.spec_from_file_location("weekly_improve", WEEKLY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _note(tmp_path, text, target=None):
    assert NOTE.is_file(), f"missing: {NOTE}"
    env = dict(os.environ, KIPI_FRICTION_FILE=str(tmp_path / "friction.jsonl"))
    cmd = ["bash", str(NOTE), text] + (["--target", target] if target else [])
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


# --- the writer -------------------------------------------------------------

def test_writer_assigns_an_id_and_creates_the_file(tmp_path):
    r = _note(tmp_path, "the brief lists Sana's tickets as mine, change the owner rule", "rule")
    assert r.returncode == 0, r.stderr
    rows = [json.loads(l) for l in (tmp_path / "friction.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["id"].startswith("fr-") and rows[0]["id"].endswith("-01")
    r2 = _note(tmp_path, "voice-lint misses the rule-of-three in comments", "lint")
    assert r2.returncode == 0
    ids = [json.loads(l)["id"] for l in (tmp_path / "friction.jsonl").read_text().splitlines()]
    assert ids[1].endswith("-02") and ids[0] != ids[1]


def test_writer_ids_are_max_plus_one_and_unique_under_concurrency(tmp_path):
    """Both Codex reviewers on this issue: a line COUNT re-issues an id after a
    gap, and two writers that both count before either appends mint the same
    id. The suffix is max(existing)+1 under one exclusive lock."""
    import concurrent.futures
    import datetime as dt
    today = dt.date.today().isoformat()
    ledger = tmp_path / "friction.jsonl"
    ledger.write_text(json.dumps({"id": f"fr-{today}-01", "target": "rule", "text": "a"}) + "\n"
                      + json.dumps({"id": f"fr-{today}-03", "target": "rule", "text": "b"}) + "\n")
    r = _note(tmp_path, "change the owner rule after a gap", "rule")
    assert r.returncode == 0, r.stderr
    assert f"fr-{today}-04" in r.stdout, r.stdout
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: _note(tmp_path, f"concurrent line {i} for the owner rule", "rule"), range(8)))
    assert all(x.returncode == 0 for x in results), [x.stderr for x in results]
    ids = [json.loads(l)["id"] for l in ledger.read_text().splitlines()]
    assert len(ids) == len(set(ids)) == 11, ids


def test_writer_refuses_an_email_address(tmp_path):
    r = _note(tmp_path, "ask someone@example.com why the brief is late", "rule")
    assert r.returncode == 1 and "email" in r.stderr
    assert not (tmp_path / "friction.jsonl").exists()


def test_writer_refuses_roadmap_and_unknown(tmp_path):
    assert _note(tmp_path, "sell the brief as a product", "rule").returncode == 1
    assert _note(tmp_path, "change the owner rule", "vibes").returncode == 1
    assert _note(tmp_path, "change the owner rule").returncode == 1  # no target
    assert not (tmp_path / "friction.jsonl").exists()


# --- the reader: empty is not broken ------------------------------------------

def test_empty_and_unreadable_render_differently(weekly, tmp_path):
    empty_msg, empty_degraded = weekly.build(tmp_path / "absent.jsonl", tmp_path / "no-inbox")
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json\n")
    bad_msg, bad_degraded = weekly.build(bad, tmp_path / "no-inbox")
    assert "nothing this week" in empty_msg and not empty_degraded
    assert "COULD NOT READ" in bad_msg and bad_degraded
    assert empty_msg != bad_msg


def test_one_line_yields_a_proposal_citing_id_and_masked_excerpt(weekly, tmp_path):
    """The email sits INSIDE the 60-character cutoff, so truncation alone
    cannot hide it (Codex standard finding on this issue: the first version put
    it after the cutoff and an `and ... or ...` precedence slip made the
    assertion pass on any excerpt containing '...')."""
    ledger = tmp_path / "friction.jsonl"
    long_text = ("ping ops@example.com: the brief lists Sana's tickets as mine, change the "
                 "owner rule so that owner:sana never renders as mine again")
    ledger.write_text(json.dumps({"id": "fr-2026-09-08-01", "target": "rule", "text": long_text}) + "\n")
    msg, degraded = weekly.build(ledger, tmp_path / "no-inbox")
    assert not degraded
    assert "fr-2026-09-08-01" in msg
    assert long_text not in msg, "the whole line must never be delivered"
    assert "ops@example.com" not in msg, "an email address reached the delivered message"
    assert "[email]" in msg, "masking did not run"
    cited = [l for l in msg.splitlines() if "fr-2026-09-08-01" in l][0]
    assert len(cited.split('"')[1]) <= weekly.EXCERPT_CHARS


def test_excerpt_masks_an_email_even_in_a_short_line(weekly):
    out = weekly.excerpt("ask ops@example.com about the rule")
    assert "ops@example.com" not in out and "[email]" in out and "..." not in out


def test_old_rows_are_not_resent_and_only_old_rows_render_nothing_this_week(weekly, tmp_path):
    """Codex adversarial finding on this issue: an append-only ledger read
    whole re-delivers every old line every week."""
    import datetime as dt
    now = dt.datetime(2026, 9, 8, 6, 30, tzinfo=dt.timezone.utc)
    old = (now - dt.timedelta(days=30)).isoformat(timespec="seconds")
    fresh = (now - dt.timedelta(days=1)).isoformat(timespec="seconds")
    ledger = tmp_path / "friction.jsonl"
    ledger.write_text(json.dumps({"id": "fr-2026-08-09-01", "at": old, "target": "rule",
                                  "text": "old: change the owner rule"}) + "\n")
    msg, degraded = weekly.build(ledger, tmp_path / "no-inbox", now=now)
    assert "nothing this week" in msg and "1 older line(s) not re-sent" in msg and not degraded
    assert "fr-2026-08-09-01" not in msg
    ledger.write_text(ledger.read_text() + json.dumps(
        {"id": "fr-2026-09-07-01", "at": fresh, "target": "rule", "text": "new: change the owner rule"}) + "\n")
    msg2, _ = weekly.build(ledger, tmp_path / "no-inbox", now=now)
    assert "fr-2026-09-07-01" in msg2 and "fr-2026-08-09-01" not in msg2


def test_roadmap_line_that_reached_the_file_is_refused_at_read_time(weekly, tmp_path):
    ledger = tmp_path / "friction.jsonl"
    ledger.write_text(json.dumps({"id": "fr-2026-09-08-01", "target": "rule",
                                  "text": "sell the brief as a product to founders"}) + "\n")
    msg, _ = weekly.build(ledger, tmp_path / "no-inbox")
    assert "refused 1 line(s)" in msg and "fr-2026-09-08-01" in msg
    assert "sell the brief" not in msg


def test_is_refused_contract(weekly):
    assert weekly.is_refused("sell the brief as a product", "rule") is True
    assert weekly.is_refused("", "rule") is True
    assert weekly.is_refused("change the owner rule", "vibes") is True
    assert weekly.is_refused("change the owner rule in the brief", "rule") is False


# --- delivery ------------------------------------------------------------------

def test_delivery_goes_through_slack_founder_and_never_slack_notify(weekly, tmp_path, capsys):
    src = WEEKLY.read_text(encoding="utf-8") + NOTE.read_text(encoding="utf-8")
    assert "slack-notify" not in src, "slack-notify.sh files a Linear ticket; it is not the founder channel"
    assert "slack_founder" in WEEKLY.read_text(encoding="utf-8")
    ledger = tmp_path / "friction.jsonl"
    ledger.write_text(json.dumps({"id": "fr-2026-09-08-01", "target": "rule", "text": "change the owner rule"}) + "\n")
    rc = weekly.main(["--friction", str(ledger), "--inbox", str(tmp_path / "no-inbox")])
    out = capsys.readouterr().out
    assert rc == 1, "under pytest the send is refused, and a refused send is not a delivery"
    assert '"refused": true' in out and '"delivered": false' in out


def test_this_file_runs_its_own_tests_under_python3():
    r = subprocess.run([sys.executable, __file__, "-k", "no_such_test_zzz"], capture_output=True, text=True)
    assert r.returncode != 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", *sys.argv[1:]]))
