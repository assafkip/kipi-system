#!/usr/bin/env python3
"""Pins filer_cap.py and its wiring into alert-to-linear.py (ASK-2012, Step 6).

THE REPRODUCER IS FIRST AND IT IS THE REAL BOARD. `test_the_flood_is_real` runs
the captured 28-day payload with the cap DISABLED and asserts the number this
issue exists for -- 507 tickets from one filer in 28 days, 5 of them ever
completed. It is the RED that every other test here is the green for, and it
cannot be satisfied by an invented fixture: the rows come from
capture_board_28d.py reading the live board (provenance is inside the payload).
"""
import importlib.util
import json
import os
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
PAYLOAD = os.path.join(HERE, "fixtures", "filer-cap-replay-28d.json")


def _load(filename, mod_name):
    path = os.path.join(SCRIPTS, filename)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cap = _load("filer_cap.py", "filer_cap")


@pytest.fixture
def sdir(tmp_path):
    return str(tmp_path / "filer-cap")


@pytest.fixture(scope="module")
def rows():
    with open(PAYLOAD, encoding="utf-8") as fh:
        return json.load(fh)["rows"]


# --- the reproducer: the flood, from the producer ----------------------------

def test_the_flood_is_real(rows):
    """Uncapped, one filer mints 507 permanent objects and 5 get worked."""
    alert = [r for r in rows if r["filer"] == "alert"]
    assert len(alert) == 507, "the fixture is not the board this issue measured"
    assert sum(1 for r in alert if r["completed"]) == 5
    uncapped = cap.replay(alert, cap_hour=10 ** 9, cap_day=10 ** 9,
                          sdir=None, only=("alert",))
    assert uncapped["ticket"] == 507 and uncapped["listed"] == 0


def test_the_cap_cuts_the_flood_and_keeps_every_worked_ticket(rows, sdir):
    """The DoR's gate, run against the corpus. Both halves have to hold."""
    out = cap.replay(rows, sdir=sdir)
    assert out["completed_ticketed"] == out["completed_total"] == 5, (
        f"a ticket somebody worked came out listed: {out['completed_listed']}")
    assert out["listed"] == 161 and out["ticket"] == 346


def test_the_gate_can_go_red(rows, sdir):
    """A check that cannot fail is decoration. Tighten the cap until it does."""
    out = cap.replay(rows, cap_hour=1, cap_day=1, sdir=sdir)
    assert out["completed_listed"], "the gate passed a cap of 1/day; it is inert"


def test_scoring_the_uncapped_classes_is_what_failed_first(rows, sdir):
    """`other` is the board's human work, not a filer. Pinned so the scope
    cannot be widened back without the test saying what that costs."""
    out = cap.replay(rows, sdir=sdir, only=())
    assert out["completed_ticketed"] < out["completed_total"]
    assert any(r["filer"] == "other" for r in out["completed_listed"])


# --- the four rules in decide(), one test each -------------------------------

def test_within_budget_tickets(sdir):
    now = time.time()
    d = cap.decide("f", "fp1", now, sdir=sdir)
    assert d.ticket and "within budget" in d.reason


def test_over_the_hourly_cap_is_recorded_not_dropped(sdir):
    now = time.time()
    for i in range(cap.DEFAULT_CAP_HOUR):
        assert cap.decide("f", f"fp{i}", now, sdir=sdir).ticket
    d = cap.decide("f", "overflow", now, sdir=sdir)
    assert not d.ticket and "hourly cap" in d.reason
    assert "overflow" in cap.listed_rows("f", now, sdir=sdir)


def test_the_daily_cap_bites_after_the_hourly_one_resets(sdir):
    now = time.time()
    made = 0
    for hour in range(10):
        at = now + hour * cap.HOUR
        for i in range(cap.DEFAULT_CAP_HOUR):
            if cap.decide("f", f"h{hour}-{i}", at, sdir=sdir).ticket:
                made += 1
    assert made == cap.DEFAULT_CAP_DAY, f"daily cap did not bind ({made})"


def test_recurrence_promotes_past_an_empty_bucket(sdir):
    now = time.time()
    for i in range(cap.DEFAULT_CAP_HOUR):
        cap.decide("f", f"fp{i}", now, sdir=sdir)
    assert not cap.decide("f", "recurring", now, sdir=sdir).ticket
    d = cap.decide("f", "recurring", now + 60, sdir=sdir)
    assert d.ticket and "promoted" in d.reason
    assert "recurring" not in cap.listed_rows("f", now + 60, sdir=sdir)


def test_a_promotion_spends_a_token_even_though_it_did_not_check_one(sdir):
    """Otherwise the bucket and the tripwire both under-count real creates."""
    now = time.time()
    cap.decide("f", "x", now, sdir=sdir, cap_hour=1)       # bucket now full
    cap.decide("f", "y", now, sdir=sdir, cap_hour=1)       # listed
    before = len(cap._read("f", sdir).get("spent"))
    assert cap.decide("f", "y", now + 1, sdir=sdir, cap_hour=1).ticket
    assert len(cap._read("f", sdir).get("spent")) == before + 1


def test_a_listed_row_expires_after_fourteen_days(sdir):
    now = time.time()
    cap.decide("f", "old", now, sdir=sdir, cap_hour=0)
    assert cap.listed_rows("f", now, sdir=sdir)
    later = now + (cap.LIST_TTL_DAYS + 1) * cap.DAY
    assert not cap.listed_rows("f", later, sdir=sdir)


def test_an_expired_row_does_not_promote(sdir):
    """Expiry has to beat recurrence or the TTL is decoration: a shape that
    fires once a month would promote forever on its second sighting."""
    now = time.time()
    cap.decide("f", "rare", now, sdir=sdir, cap_hour=0)
    later = now + (cap.LIST_TTL_DAYS + 1) * cap.DAY
    assert not cap.decide("f", "rare", later, sdir=sdir, cap_hour=0).ticket


def test_a_paused_filer_creates_nothing_not_even_a_promotion(sdir):
    now = time.time()
    cap.decide("f", "seen", now, sdir=sdir, cap_hour=0)     # on the list
    cap.pause("f", "created 40 and closed 2 over 7 days", now, sdir=sdir)
    d = cap.decide("f", "seen", now + 60, sdir=sdir)
    assert not d.ticket and "paused" in d.reason
    assert not cap.decide("f", "brand-new", now + 60, sdir=sdir).ticket


def test_the_pause_expires_and_the_filer_resumes(sdir):
    now = time.time()
    cap.pause("f", "tripwire", now, days=7, sdir=sdir)
    assert not cap.decide("f", "a", now, sdir=sdir).ticket
    assert cap.decide("f", "a", now + 8 * cap.DAY, sdir=sdir).ticket


def test_an_unreadable_cache_fails_open(sdir, monkeypatch):
    """A broken budget must never be the thing that silences the fleet."""
    monkeypatch.setattr(cap, "_decide",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    d = cap.decide("f", "fp", time.time(), sdir=sdir)
    assert d.ticket and "failing open" in d.reason


# --- the filer ladder --------------------------------------------------------

def test_the_ladder_prefers_an_explicit_statement(monkeypatch):
    monkeypatch.setenv("KIPI_ALERT_FILER", "chief")
    assert cap.filer_for("[consulting] anything") == "chief"


def test_the_ladder_falls_back_to_the_label_then_to_alert(monkeypatch):
    monkeypatch.delenv("KIPI_ALERT_FILER", raising=False)
    assert cap.filer_for("[cole-gtm] a job died") == "cole-gtm"
    assert cap.filer_for("a job died with no prefix") == "alert"


def test_a_filer_name_cannot_escape_the_state_dir(sdir):
    """The id arrives from caller-controlled `[label]` text."""
    cap.decide("../../etc/passwd", "fp", time.time(), sdir=sdir)
    assert os.listdir(sdir) and all(
        os.path.realpath(os.path.join(sdir, f)).startswith(
            os.path.realpath(sdir)) for f in os.listdir(sdir))


# --- the tripwire ------------------------------------------------------------

def test_the_tripwire_pauses_a_filer_that_creates_more_than_it_closes(rows):
    now = time.time()
    verdict = cap.tripwire(rows, now)
    assert verdict, "no rows inside the 7-day window; the fixture is stale"
    assert all(set(v) == {"created", "closed", "pause"} for v in verdict.values())
    for v in verdict.values():
        assert v["pause"] == (v["created"] > v["closed"])


# --- the wiring into alert-to-linear ----------------------------------------

def test_alert_to_linear_calls_the_cap_on_the_create_path_only():
    """A repeat must not spend budget: it mints nothing."""
    alert = _load("alert-to-linear.py", "alert_to_linear_capwire")
    src = open(os.path.join(SCRIPTS, "alert-to-linear.py"), encoding="utf-8").read()
    assert "_cap.decide(" in src
    body = src.split("def _file_alert_serialized", 1)[1]
    call = body.index("_cap.decide(")
    door = body.index("THE ONE DOOR TO A PERMANENT LINEAR OBJECT")
    assert call > door, "the cap is being spent above the create gate"
    assert alert._cap is cap.__class__ or hasattr(alert._cap, "decide")


def test_a_capped_alert_returns_ok_and_files_nothing(monkeypatch, sdir):
    """Exit 0: it was recorded, not lost. EXIT_FAILED here would make the
    heartbeat's halt branch fire on a budget that is working."""
    alert = _load("alert-to-linear.py", "alert_to_linear_capped")
    monkeypatch.setattr(alert._cap, "decide",
                        lambda *a, **k: cap.Decision(cap.LISTED, "at its hourly cap"))

    def _boom(*a, **k):                     # nothing may reach Linear
        raise AssertionError("a capped alert reached Linear")

    stub = type("ln", (), {"graphql": staticmethod(_boom)})()
    code, line = alert._file_alert_serialized("[x] a new failure", "fp0", stub,
                                              time.time(), may_create=True)
    assert code == alert.EXIT_OK
    assert "recorded, not ticketed" in line
