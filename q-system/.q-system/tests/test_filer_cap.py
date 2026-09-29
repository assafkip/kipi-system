#!/usr/bin/env python3
"""Pins filer_cap.py and its wiring into alert-to-linear.py (ASK-2012, Step 6).

THE REPRODUCER IS FIRST AND IT IS THE REAL BOARD. `test_the_flood_is_real` runs
the captured 28-day payload with the cap DISABLED and asserts the number this
issue exists for -- 507 tickets from one filer in 28 days, 5 of them ever
completed. It is the RED that every other test here is the green for, and it
cannot be satisfied by an invented fixture: the rows come from
capture_board_28d.py reading the live board (provenance is inside the payload).
"""
import datetime
import importlib.util
import json
import os
import subprocess
import sys
import time

import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
PAYLOAD = os.path.join(HERE, "fixtures", "filer-cap-replay-28d.json")
FILER_CAP = os.path.join(SCRIPTS, "filer_cap.py")
AUTOMATION = os.path.join(HERE, "..", "..", "..", "automation")


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


# --- the promotion ceiling (PR #465 round 2, major 1) ------------------------

def test_a_repeating_flood_cannot_walk_past_the_cap_through_rule_2(sdir):
    """THE REPRODUCER for the round-2 major, in the shape the docstring names:
    105 distinct conditions from a job that runs hourly. Rule 2 spent a token
    without checking one, so every listed fingerprint promoted on its next
    firing and the steady state was 105 permanent Linear objects every other
    hour, against a documented 6/hour."""
    now = time.time()
    fps = [f"fp{i:03d}" for i in range(105)]
    per_hour = []
    for hour in range(4):
        t = now + hour * cap.HOUR
        per_hour.append(sum(1 for fp in fps
                            if cap.decide("alert", fp, t, sdir=sdir).ticket))

    ceiling = cap.DEFAULT_CAP_HOUR * cap.PROMOTE_HEADROOM
    assert per_hour[0] == cap.DEFAULT_CAP_HOUR, per_hour
    assert all(n <= ceiling for n in per_hour), per_hour
    # The pre-fix number, kept as the thing this must never return to.
    assert max(per_hour) < 105, per_hour
    # And the whole day stays under the day ceiling.
    assert sum(per_hour) <= cap.DEFAULT_CAP_DAY * cap.PROMOTE_HEADROOM, per_hour


def test_a_promotion_over_the_ceiling_is_relisted_and_not_dropped(sdir):
    """The ceiling delays a promotion; it must never lose one. The row keeps
    its count, so it promotes as soon as the hour frees.

    Explicit caps, not the defaults: cap_hour=1 makes the ceiling exactly
    PROMOTE_HEADROOM, so each step below is one decision rather than a race
    against the default budget.
    """
    now = time.time()
    caps = {"cap_hour": 1, "cap_day": 1000, "sdir": sdir}
    assert cap.decide("alert", "A", now, **caps).ticket          # spends 1 of 1
    assert not cap.decide("alert", "B", now, **caps).ticket      # hourly cap
    assert not cap.decide("alert", "C", now, **caps).ticket      # hourly cap

    promoted = cap.decide("alert", "B", now, **caps)             # 1 < ceiling 2
    assert promoted.ticket and "promoted" in promoted.reason, promoted.reason

    blocked = cap.decide("alert", "C", now, **caps)              # 2 >= ceiling 2
    assert not blocked.ticket and "ceiling" in blocked.reason, blocked.reason
    assert "C" in cap.listed_rows("alert", now, sdir=sdir), "the row was dropped"

    later = cap.decide("alert", "C", now + cap.HOUR + 1, **caps)
    assert later.ticket and "promoted" in later.reason, later.reason


# --- the refund (PR #465 round 2, major 2) -----------------------------------

def test_a_failed_create_gives_its_token_back(sdir):
    """A Linear outage burned the hourly budget on sends that minted nothing,
    and every alert after the 6th came back EXIT_OK "recorded, not ticketed" --
    so the heartbeat's halt branch read a hard-down Linear as a working
    budget."""
    now = time.time()
    for i in range(cap.DEFAULT_CAP_HOUR):
        d = cap.decide("alert", f"down{i}", now, sdir=sdir)
        assert d.ticket and d.refundable
        assert cap.refund(d, sdir=sdir), "the token did not come back"

    after = cap.decide("alert", "down-next", now, sdir=sdir)
    assert after.ticket, f"{cap.DEFAULT_CAP_HOUR} failed sends still spent the budget"

    # A refund is idempotent: a second call must not credit a token twice.
    d = cap.decide("alert", "once", now, sdir=sdir)
    assert cap.refund(d, sdir=sdir) is True
    assert cap.refund(d, sdir=sdir) is False


def test_a_refunded_promotion_keeps_the_recurrence_that_earned_it(sdir):
    now = time.time()
    cap.decide("alert", "rec", now, sdir=sdir)                    # ticket
    for i in range(cap.DEFAULT_CAP_HOUR * cap.PROMOTE_HEADROOM):   # fill the hour
        cap.decide("alert", f"pad{i}", now, sdir=sdir)
    cap.decide("alert", "rec2", now, sdir=sdir)                   # listed
    promoted = cap.decide("alert", "rec2", now + cap.HOUR + 1, sdir=sdir)
    assert promoted.ticket and promoted.promoted_row is not None

    assert cap.refund(promoted, sdir=sdir)
    rows = cap.listed_rows("alert", now + cap.HOUR + 1, sdir=sdir)
    assert "rec2" in rows, "a failed create lost the recurrence count"


def test_alert_to_linear_refunds_on_every_create_failure_path():
    """Wiring, not behaviour: every EXIT_FAILED below the decide goes through
    the refund helper. A path that returns EXIT_FAILED directly would silently
    keep spending."""
    src = open(os.path.join(SCRIPTS, "alert-to-linear.py"), encoding="utf-8").read()
    # THIS function only. An unbounded split runs on into main(), whose own
    # bare `return EXIT_FAILED` lines are nothing to do with the cap.
    rest = src.split("def _file_alert_serialized", 1)[1]
    end = re.search(r"^def ", rest, re.M)
    body = rest[:end.start()] if end else rest
    tail = body[body.index("_cap.decide("):]
    assert "_cap.refund(decision)" in tail
    # Everything after the _failed() helper's own body: those returns must all
    # go through it.
    after_helper = tail[tail.index("return EXIT_FAILED, line") + 24:]
    direct = [ln.strip() for ln in after_helper.splitlines()
              if "return EXIT_FAILED" in ln]
    assert not direct, f"an unrefunded failure path below the cap: {direct}"


# --- the undo for the tripwire (PR #465 round 2, major 3) --------------------

def test_unpause_lifts_a_chokepoint_that_reconcile_armed(sdir):
    now = time.time()
    cap.pause_chokepoint("alert", "created 128 and closed 6", now, sdir=sdir)
    assert cap.chokepoint_paused("alert", now, sdir=sdir)
    assert not cap.decide("alert", "fp", now, sdir=sdir).ticket

    cap.unpause_chokepoint("alert", sdir=sdir)
    assert cap.chokepoint_paused("alert", now, sdir=sdir) is None
    assert cap.decide("alert", "fp2", now, sdir=sdir).ticket


def test_the_unpause_verb_is_reachable_from_the_cli(tmp_path):
    """unpause_chokepoint() existed and no CLI verb reached it, so recovery was
    hand-deleting a cache file nothing documented."""
    sd = str(tmp_path / "state")
    env = dict(os.environ, KIPI_FILER_CAP_DIR=sd)
    env.pop("PYTEST_CURRENT_TEST", None)
    cap.pause_chokepoint("alert", "armed", time.time(), sdir=sd)

    res = subprocess.run([sys.executable, FILER_CAP, "unpause", "--chokepoint", "alert"],
                         capture_output=True, text=True, env=env, timeout=60)
    assert res.returncode == 0, res.stderr
    assert "unpaused chokepoint alert" in res.stdout
    assert cap.chokepoint_paused("alert", time.time(), sdir=sd) is None


def test_reset_says_so_when_the_chokepoint_is_still_paused(tmp_path):
    """`reset --filer alert` printed success and exited 0 while the chokepoint
    stayed paused, so the filer still could not file."""
    sd = str(tmp_path / "state")
    env = dict(os.environ, KIPI_FILER_CAP_DIR=sd)
    env.pop("PYTEST_CURRENT_TEST", None)
    cap.pause_chokepoint("alert", "created 128 and closed 6", time.time(), sdir=sd)

    res = subprocess.run([sys.executable, FILER_CAP, "reset", "--filer", "alert"],
                         capture_output=True, text=True, env=env, timeout=60)
    assert res.returncode == 0, res.stderr
    assert "STILL PAUSED" in res.stdout, res.stdout
    assert "unpause --chokepoint alert" in res.stdout, res.stdout


# --- the tripwire ------------------------------------------------------------

def _fixture_now(rows) -> float:
    """The clock the fixture was captured against, read from the fixture.

    Scar (PR #465 round 2, major): this used time.time() against a STATIC
    payload, so the 7-day window walked off the end of the data and the suite
    was scheduled to go red around 2026-10-06 with no code change. A suite that
    fails for calendar reasons is how a suite stops being read. The window is
    relative to the newest row, which is what "the last 7 days of this capture"
    always meant.
    """
    stamps = [cap._epoch(r.get("created_at")) for r in rows]
    stamps = [s for s in stamps if s is not None]
    assert stamps, "no parseable created_at in the payload; the fixture is broken"
    return max(stamps)


def test_the_tripwire_pauses_a_filer_that_creates_more_than_it_closes(rows):
    now = _fixture_now(rows)
    verdict = cap.tripwire(rows, now)
    assert verdict, "no rows inside the 7-day window; the fixture is stale"
    assert all(set(v) == {"created", "closed", "pause"} for v in verdict.values())
    for v in verdict.values():
        assert v["pause"] == (v["created"] > v["closed"]
                              and v["created"] >= cap.TRIPWIRE_MIN_CREATED)


def test_the_tripwire_does_not_arm_on_a_filer_with_no_volume():
    """A pause silences a whole chokepoint for 7 days. `created > closed` alone
    tripped on ONE create and zero closes in a week, which is every quiet filer
    (PR #465 round 2, major)."""
    now = time.time()
    stamp = (datetime.datetime.fromtimestamp(now - cap.DAY, datetime.timezone.utc)
             .isoformat().replace("+00:00", "Z"))
    quiet = [{"filer": "lgtm", "created_at": stamp, "state_type": "started"}]
    assert cap.tripwire(quiet, now)["lgtm"]["pause"] is False

    loud = [dict(quiet[0]) for _ in range(cap.TRIPWIRE_MIN_CREATED)]
    assert cap.tripwire(loud, now)["lgtm"]["pause"] is True

    # The floor is a floor, not a replacement: the same volume, all of it
    # closed, is a healthy filer and must not arm.
    closed = [dict(r, state_type="completed") for r in loud]
    assert cap.tripwire(closed, now)["lgtm"]["pause"] is False


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
    # `alert._cap is cap.__class__` was always False, so this resolved on a
    # hasattr true for any module importing filer_cap (PR #465 round 2, nit).
    # What it meant to check is that alert-to-linear loads THIS filer_cap.
    assert os.path.realpath(alert._cap.__file__) == \
        os.path.realpath(os.path.join(SCRIPTS, "filer_cap.py"))


def test_spillover_does_not_spend_the_alert_budget():
    """Caught live, not in review: the FIRST capture after the cap shipped came
    back "recorded, not ticketed (alert is at its daily cap)" and the row got no
    Linear issue. A spillover message carries no `[label]`, so the ladder's last
    rung handed it the alert budget. Both call sites now declare themselves."""
    src = open(os.path.join(SCRIPTS, "spillover-linear-check.py"),
               encoding="utf-8").read()
    assert src.count('"KIPI_ALERT_FILER", "spillover"') == 2, (
        "a spillover filing path that does not declare its filer shares the "
        "alert budget and gets swallowed")
    assert cap.filer_for("spillover sp-abc123 (high) from ASK-1: ...") == "alert", (
        "the ladder's fallback is what makes the declaration load-bearing; if "
        "this ever stops being 'alert', re-check the two call sites")


# --- PR #465 review round 1: four majors, one reproducer each ---------------

def _clean_env():
    """os.environ minus every cap variable, so a subprocess is its own RUN."""
    return {k: v for k, v in os.environ.items()
            if not k.startswith("KIPI_FILER_CAP")}


def test_the_pytest_state_dir_is_fresh_every_run(tmp_path):
    """A temp dir keyed ONLY on the node id outlives the run that made it, so
    run 2 starts with run 1's spent tokens still in the bucket and the alert
    suite goes red at the cap after a handful of runs. Two real processes with
    the same node id, which is exactly what two consecutive runs are."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import importlib.util, os\n"
        f"spec = importlib.util.spec_from_file_location('fc', {FILER_CAP!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "d = m.state_dir()\n"
        "os.makedirs(d, exist_ok=True)\n"
        "marker = os.path.join(d, 'ran-before')\n"
        "print('INHERITED' if os.path.exists(marker) else 'FRESH')\n"
        "open(marker, 'w').close()\n")
    env = _clean_env()
    env["PYTEST_CURRENT_TEST"] = "test_filer_cap.py::test_freshness (call)"
    runs = [subprocess.run([sys.executable, str(probe)], env=env, text=True,
                           capture_output=True) for _ in range(2)]
    assert runs[0].stdout.strip() == "FRESH", runs[0].stderr
    assert runs[1].stdout.strip() == "FRESH", (
        "the second run inherited the first run's bucket; the suite is green "
        "until the inherited spend reaches the cap, then red until it ages out")


def test_a_security_detection_is_exempt_from_the_cap():
    """is_noise() refuses to suppress this class outright (ASK-870). A cap that
    LISTS it is the same drop one layer down: a security detection that does not
    recur is pruned at 14 days and nobody ever sees it."""
    alert = _load("alert-to-linear.py", "alert_to_linear_security")
    msg = "SECURITY: unsanctioned .claude/ change -- 1 modified, reverted 1"
    assert alert.is_noise(msg) is False
    assert alert.never_capped(msg) is True
    assert alert.never_capped("[cole-gtm] a job died") is False


def test_a_full_bucket_still_files_a_security_detection(sdir, monkeypatch):
    """The wiring half. With the day's budget spent, an ordinary alert is
    recorded and the security detection is not."""
    alert = _load("alert-to-linear.py", "alert_to_linear_security_wired")
    monkeypatch.setattr(alert, "_state_dir", lambda: sdir)
    monkeypatch.setenv("KIPI_FILER_CAP_DIR", sdir)
    monkeypatch.delenv("KIPI_ALERT_FILER", raising=False)
    now = time.time()
    for i in range(cap.DEFAULT_CAP_DAY):
        cap.decide("alert", f"spend{i}", now, sdir=sdir)
    stub = type("ln", (), {"graphql": staticmethod(lambda *a, **k: {})})()

    _, ordinary = alert._file_alert_serialized("a brand new ordinary failure",
                                               "fp-ordinary", stub, now)
    assert "recorded, not ticketed" in ordinary

    _, security = alert._file_alert_serialized(
        "SECURITY: unsanctioned .claude/ change -- 1 modified, reverted 1",
        "fp-security", stub, now)
    assert "recorded, not ticketed" not in security, (
        "a security detection was listed instead of ticketed")


def test_the_recorded_list_has_a_reader(sdir):
    """Two writers and zero readers makes a listing a drop with extra steps:
    the 14-day prune is then the only thing that ever touches a row."""
    now = time.time()
    cap.decide("f", "about-to-expire", now - (cap.LIST_TTL_DAYS - 1) * cap.DAY,
               sdir=sdir, cap_hour=0)
    cap.decide("f", "seen-today", now, sdir=sdir, cap_hour=0)
    env = _clean_env()
    env["KIPI_FILER_CAP_DIR"] = sdir
    out = subprocess.run([sys.executable, FILER_CAP, "digest"], env=env,
                         text=True, capture_output=True)
    assert out.returncode == 0, out.stderr
    assert "about-to-expire" in out.stdout and "seen-today" in out.stdout
    assert "expiring" in out.stdout.lower(), (
        "a reader that does not say which rows are about to be dropped does "
        "not close the drop")


def test_the_digest_is_scheduled():
    """A reader nothing runs is still zero readers."""
    plist = os.path.join(AUTOMATION, "com.kipi.filer-cap-digest.plist")
    assert os.path.exists(plist), "the digest has no launchd job"
    body = open(plist, encoding="utf-8").read()
    assert "filer_cap.py digest" in body and "--notify" in body


def test_pausing_the_taxonomy_class_pauses_every_runtime_bucket(sdir):
    """`reconcile` knows the capture's CLASS names (alert, other). filer_for
    keys a bucket per `[label]` repo. Pausing the class name alone wrote
    alert.json and paused nothing that actually files."""
    now = time.time()
    cap.pause_chokepoint("alert", "created 128 and closed 6 over 7 days", now,
                         sdir=sdir)
    bucket = cap.filer_for("[consulting] a job died")
    assert bucket == "consulting"
    d = cap.decide(bucket, "fp", now, sdir=sdir)
    assert not d.ticket and "paused" in d.reason


def test_reconcile_only_pauses_a_class_this_repo_has_a_chokepoint_for(sdir):
    """`other` and `radar` file through paths this cap never sees, so pausing
    them would be a pause that stops nothing while reading as protection."""
    assert "alert" in cap.CLASS_TO_CHOKEPOINT
    assert "other" not in cap.CLASS_TO_CHOKEPOINT
    now = time.time()
    cap.reconcile_apply({"alert": {"created": 128, "closed": 6, "pause": True},
                         "other": {"created": 58, "closed": 9, "pause": True}},
                        now, sdir=sdir)
    assert cap.chokepoint_paused("alert", now, sdir=sdir)
    assert not cap.chokepoint_paused("other", now, sdir=sdir)


def test_a_repeat_on_an_open_ticket_never_reaches_the_cap(monkeypatch, sdir):
    """PROMOTE_AT's grounding, made executable (review round 1, minor).

    The old calibration note justified PROMOTE_AT with the repeat rate among
    CREATED rows. Those are fingerprints that got a ticket, and a re-fire of one
    returns from the repeat branch above the cap -- so that rate describes a
    population rule 2 never sees. This is the code path that makes it true, and
    it also pins the budget rule: a repeat mints nothing, so it spends nothing."""
    alert = _load("alert-to-linear.py", "alert_to_linear_repeat")
    monkeypatch.setattr(alert, "_state_dir", lambda: sdir)
    monkeypatch.setattr(alert, "_read_state",
                        lambda fp: {"issue_id": "iss-1", "identifier": "ASK-1",
                                    "count": 4, "first_at": time.time()})
    monkeypatch.setattr(alert._cap, "decide", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("a repeat spent budget it could not mint")))
    open_issue = {"issue": {"id": "iss-1", "state": {"type": "started"}}}
    stub = type("ln", (), {"graphql": staticmethod(lambda *a, **k: open_issue)})()
    code, line = alert._file_alert_serialized("a condition still firing", "fp-r",
                                             stub, time.time())
    assert code == alert.EXIT_OK and "repeat #5" in line


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
