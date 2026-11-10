#!/usr/bin/env python3
"""A hold names a consumer, checked in code (ASK-4306).

Rule-ID: RULE-2026-11-09-B
Founder, 2026-11-09: "No agent can be waiting on things that are never gonna get
done... It should be fixed in code."

SCAR. ASK-3834's lane held V8 on ASK-4195 and V6 on ASK-4277. Both are spillover
tickets filed through the fleet-alert path, which linear-worker.sh is_fleet_alert()
skips. The lane waited on work nothing would ever do. test_no_handoff_to_nobody.py
checks the WORDING of a message and never a real wait; this checks the wait.

EVERY CASE USES FIXTURES. Linear, GitHub, the fleet set and the lane dir are all
replaced, so no case reads or writes a live path. The control cases (a ticket the
worker WOULD pick, an owned PR) are what make each refusal mean something: a
harness that refuses everything would pass the refusal cases and fail the controls.
"""
import importlib.util
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"


def load(file, name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def stamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


NOW = datetime.now(timezone.utc)

DOR = "## Definition of Ready\n- a reproducer\n"
ALERT = "spillover from ASK-3834\n<!-- kipi-alert-fingerprint: abc123 -->\n"


def issue(ident, desc="", state=("Backlog", "backlog"), labels=("owner:sana",),
          project="kipi-system", started=None):
    return {"id": "uuid-" + ident, "identifier": ident, "title": "t", "description": desc,
            "state": {"name": state[0], "type": state[1]}, "startedAt": started,
            "project": {"name": project} if project else None,
            "labels": {"nodes": [{"name": n} for n in labels]}}


BOARD = {
    # a spillover ticket filed through the alert path: no DoR, alert marker
    "ASK-4195": issue("ASK-4195", ALERT),
    # a ticket the worker would pick: owner:sana, DoR, queue state, its project
    "ASK-5001": issue("ASK-5001", DOR),
    # In Progress, started an hour ago, no claim
    "ASK-5002": issue("ASK-5002", DOR, ("In Progress", "started"), started=stamp(NOW - timedelta(hours=1))),
    "ASK-5003": issue("ASK-5003", DOR, ("In Progress", "started"), started=stamp(NOW - timedelta(hours=1))),
    # held by a label the worker refuses
    "ASK-5004": issue("ASK-5004", DOR, labels=("owner:sana", "needs-scope")),
    "ASK-5005": issue("ASK-5005", DOR, labels=("owner:assaf",)),
    "ASK-5006": issue("ASK-5006", DOR, ("Done", "completed")),
    # alert marker AND a DoR: the worker still skips it
    "ASK-5007": issue("ASK-5007", DOR + ALERT),
    # a project no checkout backs
    "ASK-5008": issue("ASK-5008", DOR, project="nowhere"),
    # owner:sana with a project and no DoR: linear-dor-drafter.py's "draft" population
    "ASK-7001": issue("ASK-7001", "needs a spec"),
    # refused once by the worker: the drafter's "redraft" population
    "ASK-7002": issue("ASK-7002", DOR, labels=("owner:sana", "needs-scope")),
}


@pytest.fixture
def wc(tmp_path, monkeypatch):
    monkeypatch.setenv("KIPI_LANES_DIR", str(tmp_path / "lanes"))
    monkeypatch.setenv("KIPI_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "lanes").mkdir()
    mod = load("wait-has-consumer.py", "wait_has_consumer_under_test")
    ls = mod.linear_sync()

    def fake_graphql(query, variables):
        node = BOARD.get(variables.get("id"))
        return {"issue": node}

    monkeypatch.setattr(ls, "graphql", fake_graphql)
    monkeypatch.setattr(mod, "local_projects", lambda: {"kipi-system"})
    # The nightly queues are Linear reads of the whole board; every case sets its own.
    monkeypatch.setattr(mod, "_dor_queue", lambda: [])
    monkeypatch.setattr(mod, "_triage_queue", lambda: [])
    mod.tmp = tmp_path
    return mod


def marker(wc, ident, until):
    p = wc.tmp / "lanes" / (ident + ".json")
    p.write_text(json.dumps({"issue": ident, "agent": "sana-lane", "since": stamp(NOW),
                             "until": stamp(until), "pr": "-", "worktree": "-"}))


def fake_pr(wc, monkeypatch, *, state="OPEN", cross=False, in_fleet=True, killed=False, archived=False):
    po = wc.pr_owner()
    repo = wc.tmp / "kipi-system"
    repo.mkdir(exist_ok=True)
    if killed:
        (repo / ".kipi-no-dispatch").write_text("")
    rows = [("kipi-system", str(repo), "")] if in_fleet else []
    monkeypatch.setattr(po, "fleet_repos", lambda root=None: (rows, ""))
    monkeypatch.setattr(po, "slug_for", lambda root, path, targets: "assafkip/kipi-system")
    monkeypatch.setattr(po, "archived", lambda path, label: archived)
    monkeypatch.setattr(po, "gh_json", lambda argv: {"state": state, "isCrossRepository": cross, "number": 9})


# --- the four cases the ticket names, each seen red before the script existed ---

def test_hold_on_alert_spillover_with_no_dor_refuses(wc):
    ok, text = wc.consumer_for("ASK-4195")
    assert not ok
    assert text.startswith("nothing picks this up:")
    assert "fleet alert" in text


def test_hold_on_open_pr_with_an_owner_passes(wc, monkeypatch):
    fake_pr(wc, monkeypatch)
    ok, text = wc.consumer_for("assafkip/kipi-system#9")
    assert ok
    assert "pr-owner.py" in text


def test_hold_on_in_progress_ticket_with_a_live_lane_marker_passes(wc):
    marker(wc, "ASK-5002", NOW + timedelta(hours=5))
    ok, text = wc.consumer_for("ASK-5002")
    assert ok
    assert "lane marker" in text


def test_hold_on_in_progress_ticket_with_no_marker_and_no_claim_refuses(wc):
    ok, text = wc.consumer_for("ASK-5003")
    assert not ok
    assert text.startswith("nothing picks this up:")


# --- controls and the other arms ---

def test_a_ticket_the_worker_would_pick_passes(wc):
    ok, text = wc.consumer_for("ASK-5001")
    assert ok
    assert "linear-worker.sh" in text


def test_an_expired_lane_marker_is_not_a_consumer(wc):
    marker(wc, "ASK-5003", NOW - timedelta(minutes=1))
    ok, _ = wc.consumer_for("ASK-5003")
    assert not ok


@pytest.mark.parametrize("ident,word", [
    ("ASK-5004", "needs-scope"),
    ("ASK-5005", "owner:assaf"),
    ("ASK-5006", "Done"),
    ("ASK-5007", "fleet alert"),
    ("ASK-5008", "nowhere"),
    ("ASK-9999", "does not exist"),
])
def test_each_refusal_names_its_reason(wc, ident, word):
    ok, text = wc.consumer_for(ident)
    assert not ok
    assert word in text


@pytest.mark.parametrize("kw,word", [
    ({"state": "CLOSED"}, "not open"),
    ({"cross": True}, "outside"),
    ({"in_fleet": False}, "fleet"),
    ({"killed": True}, "kill switch"),
    ({"archived": True}, "archive"),
])
def test_a_pr_pr_owner_does_not_own_refuses(wc, monkeypatch, kw, word):
    fake_pr(wc, monkeypatch, **kw)
    ok, text = wc.consumer_for("assafkip/kipi-system#9")
    assert not ok
    assert word in text


def test_cannot_look_is_neither_a_consumer_nor_nothing(wc, monkeypatch):
    ls = wc.linear_sync()

    def boom(q, v):
        raise RuntimeError("linear down")

    monkeypatch.setattr(ls, "graphql", boom)
    with pytest.raises(wc.CannotLook):
        wc.consumer_for("ASK-5001")


def test_the_worker_rule_is_the_workers_own_text(wc):
    # ready() is cut out of linear-worker.sh, never copied: break its source and
    # the cut must fail loudly rather than fall back to a private rule.
    src = (SCRIPTS / "linear-worker.sh").read_text()
    with pytest.raises(wc.CannotLook):
        wc.worker_rule(src.replace("def ready(i):", "def renamed(i):"))


def test_main_exit_codes(wc, capsys):
    assert wc.main(["ASK-5001"]) == 0
    assert wc.main(["ASK-4195"]) == 1
    assert "nothing picks this up" in capsys.readouterr().out
    assert wc.main(["banana"]) == 64


# --- lane-mark.py hold ---

@pytest.fixture
def lm(tmp_path, monkeypatch):
    monkeypatch.setenv("KIPI_LANES_DIR", str(tmp_path / "lanes"))
    mod = load("lane-mark.py", "lane_mark_under_test")
    mod.tmp = tmp_path
    return mod


def start(lm, ident="ASK-3834"):
    assert lm.main(["start", ident, "--agent", "sana-lane", "--worktree", "/w"]) == 0


def test_hold_refuses_when_the_blocker_has_no_consumer(lm, monkeypatch, capsys):
    start(lm)
    monkeypatch.setattr(lm, "check_blocker", lambda b, w="": (False, "nothing picks this up: alert ticket"))
    assert lm.main(["hold", "ASK-3834", "--on", "ASK-4195"]) == 1
    cur = json.load(open(lm.tmp / "lanes" / "ASK-3834.json"))
    assert "holds" not in cur
    assert "nothing picks this up" in capsys.readouterr().err


def test_hold_records_when_the_blocker_has_a_consumer(lm, monkeypatch):
    start(lm)
    monkeypatch.setattr(lm, "check_blocker", lambda b, w="": (True, "linear-worker.sh would pick ASK-5001"))
    assert lm.main(["hold", "ASK-3834", "--on", "ASK-5001"]) == 0
    cur = json.load(open(lm.tmp / "lanes" / "ASK-3834.json"))
    assert cur["holds"][0]["on"] == "ASK-5001"
    assert "linear-worker.sh" in cur["holds"][0]["consumer"]
    # a later touch keeps the record of what the lane waits on
    assert lm.main(["touch", "ASK-3834"]) == 0
    assert json.load(open(lm.tmp / "lanes" / "ASK-3834.json"))["holds"][0]["on"] == "ASK-5001"


def test_hold_needs_a_marker_and_an_on_blocker(lm, monkeypatch):
    monkeypatch.setattr(lm, "check_blocker", lambda b, w="": (True, "x"))
    assert lm.main(["hold", "ASK-3834", "--on", "ASK-5001"]) == 1   # no marker
    start(lm)
    assert lm.main(["hold", "ASK-3834"]) == 64                       # no --on


def test_hold_fails_closed_when_the_check_cannot_run(lm, monkeypatch):
    start(lm)

    def boom(b, w=""):
        raise RuntimeError("linear down")

    monkeypatch.setattr(lm, "check_blocker", boom)
    assert lm.main(["hold", "ASK-3834", "--on", "ASK-5001"]) == 1
    assert "holds" not in json.load(open(lm.tmp / "lanes" / "ASK-3834.json"))


def test_the_real_check_blocker_reaches_the_real_script(lm):
    # Not the seam: check_blocker must load wait-has-consumer.py by its real path.
    mod = lm.load_consumer_module()
    assert hasattr(mod, "consumer_for")


def test_hold_on_a_typo_is_64_not_a_retryable_failure(lm):
    start(lm)
    assert lm.main(["hold", "ASK-3834", "--on", "not-a-ref"]) == 64


def test_hold_on_an_ended_lane_refuses(lm, monkeypatch):
    start(lm)
    assert lm.main(["end", "ASK-3834"]) == 0
    monkeypatch.setattr(lm, "check_blocker", lambda b, w="": (True, "x"))
    assert lm.main(["hold", "ASK-3834", "--on", "ASK-5001"]) == 1
    assert "holds" not in json.load(open(lm.tmp / "lanes" / "ASK-3834.json"))


def test_a_lane_cannot_hold_on_its_own_ticket(wc):
    marker(wc, "ASK-5002", NOW + timedelta(hours=5))
    ok, text = wc.consumer_for("ASK-5002", waiter="ASK-5002")
    assert not ok and "own ticket" in text
    assert wc.consumer_for("ASK-5002", waiter="ASK-3834")[0]


# --- local_projects: the dispatcher's set, not every checkout (PR #712 review, major 1) ---

def test_local_projects_is_the_dispatch_set_minus_kill_switches(wc, monkeypatch):
    po = wc.pr_owner()
    on, off, killed = (wc.tmp / n for n in ("on", "off", "killed"))
    for d in (on, off, killed):
        d.mkdir()
    (killed / ".kipi-no-dispatch").write_text("")
    # off: has a registry row and a checkout but the dispatcher does not enter it
    monkeypatch.setattr(po, "fleet_repos", lambda root=None: ([("on", str(on), ""), ("killed", str(killed), "")], ""))
    lr = wc._load("lr", "linear_registry.py", "linear_registry_for_wait")
    facts = {"ok": True, "local_repos": [{"project": "ProjOn", "path": str(on)},
                                         {"project": "ProjOff", "path": str(off)},
                                         {"project": "ProjKilled", "path": str(killed)}]}
    monkeypatch.setattr(lr, "registry_facts", lambda *a, **k: facts)
    mod = load("wait-has-consumer.py", "wait_has_consumer_lp")
    mod._MODS.update({"po": po, "lr": lr})
    assert mod.local_projects() == {"ProjOn"}


def test_hold_does_not_erase_an_end_that_lands_during_the_check(lm, monkeypatch):
    start(lm)

    def check_then_end(b, w=""):
        assert lm.main(["end", "ASK-3834"]) == 0   # the lane ends while the check runs
        return True, "linear-worker.sh would pick it"

    monkeypatch.setattr(lm, "check_blocker", check_then_end)
    assert lm.main(["hold", "ASK-3834", "--on", "ASK-5001"]) == 1
    cur = json.load(open(lm.tmp / "lanes" / "ASK-3834.json"))
    assert cur.get("ended") and "holds" not in cur


def test_hold_on_an_expired_marker_refuses(lm, monkeypatch):
    start(lm)
    p = lm.tmp / "lanes" / "ASK-3834.json"
    cur = json.load(open(p))
    cur["until"] = stamp(NOW - timedelta(hours=1))
    p.write_text(json.dumps(cur))
    monkeypatch.setattr(lm, "check_blocker", lambda b, w="": (True, "x"))
    assert lm.main(["hold", "ASK-3834", "--on", "ASK-5001"]) == 1


def test_an_unreadable_lane_marker_is_not_a_consumer(wc):
    (wc.tmp / "lanes" / "ASK-5002.json").write_text("{not json")
    with pytest.raises(wc.CannotLook):
        wc.consumer_for("ASK-5002")


# --- ASK-4306 round 4: nightly queues count only inside their cap (PR #712 review, round 3) ---

@pytest.mark.parametrize("ident,mode", [("ASK-7001", "draft"), ("ASK-7002", "redraft")])
def test_a_ticket_inside_the_drafters_cap_has_a_consumer(wc, monkeypatch, ident, mode):
    monkeypatch.setattr(wc, "_dor_queue", lambda: [ident])
    ok, text = wc.consumer_for(ident)
    assert ok, text
    assert "linear-dor-drafter.py" in text and "inside 24h" in text


def test_a_ticket_behind_the_drafters_cap_is_nobody(wc, monkeypatch):
    cap = wc._plist_limit("com.kipi.linear-dor.plist")
    monkeypatch.setattr(wc, "_dor_queue", lambda: [f"ASK-{n}" for n in range(100, 100 + cap)] + ["ASK-7001"])
    ok, text = wc.consumer_for("ASK-7001")
    assert not ok
    assert text.startswith("nothing picks this up:") and f"queued behind {cap}" in text
    # control: one place earlier and it is inside the cap
    monkeypatch.setattr(wc, "_dor_queue", lambda: [f"ASK-{n}" for n in range(100, 100 + cap - 1)] + ["ASK-7001"])
    assert wc.consumer_for("ASK-7001")[0]


def test_the_alert_spillover_case_still_refuses_when_it_is_behind_the_cap(wc, monkeypatch):
    # ASK-4195, the scar: the nightly triage takes 60 of 1,094. Behind the cap it is nobody.
    cap = wc._plist_limit("com.kipi.linear-alert-triage.plist")
    monkeypatch.setattr(wc, "_triage_queue", lambda: [f"ASK-{n}" for n in range(2000, 2000 + cap + 5)] + ["ASK-4195"])
    ok, text = wc.consumer_for("ASK-4195")
    assert not ok and "queued behind" in text and "fleet alert" in text
    monkeypatch.setattr(wc, "_triage_queue", lambda: ["ASK-4195"])
    ok, text = wc.consumer_for("ASK-4195")
    assert ok and "linear-alert-triage.py" in text


def test_a_held_or_refused_alert_is_not_in_the_triage_queue(wc):
    # the default queue is empty: an alert the triage lane will not take has no consumer
    ok, text = wc.consumer_for("ASK-4195")
    assert not ok and "fleet alert" in text


def test_the_cap_is_read_from_the_plist_not_copied(wc, monkeypatch):
    monkeypatch.setattr(wc, "SCRIPTS", wc.tmp)
    with pytest.raises(wc.CannotLook):
        wc._plist_limit("com.kipi.linear-dor.plist")


def test_a_lane_cannot_hold_on_the_pr_it_drives(wc, monkeypatch):
    fake_pr(wc, monkeypatch)
    marker(wc, "ASK-3834", NOW + timedelta(hours=5))
    path = wc.tmp / "lanes" / "ASK-3834.json"
    data = json.loads(path.read_text())
    data["pr"] = "9"
    path.write_text(json.dumps(data))
    ok, text = wc.consumer_for("assafkip/kipi-system#9", waiter="ASK-3834")
    assert not ok and "lane itself drives" in text
    # controls: another waiter, and another PR number, both still pass
    assert wc.consumer_for("assafkip/kipi-system#9", waiter="ASK-3835")[0]
    assert wc.consumer_for("assafkip/kipi-system#10", waiter="ASK-3834")[0]


# --- wait-guard.sh: the first caller of the check (PR #712 review, round 3, finding 3) ---

def _guard_dir(tmp_path, stub_rc, stub_out):
    import shutil
    d = tmp_path / "guard"
    d.mkdir()
    shutil.copy(SCRIPTS / "wait-guard.sh", d / "wait-guard.sh")
    (d / "wait-has-consumer.py").write_text(
        "import sys\nprint(%r)\nsys.exit(%d)\n" % (stub_out, stub_rc))
    return d / "wait-guard.sh"


@pytest.mark.parametrize("rc,ok", [(0, True), (1, False), (2, False)])
def test_wait_guard_passes_the_checks_verdict_through(tmp_path, rc, ok):
    import subprocess
    guard = _guard_dir(tmp_path, rc, "the stub's reason")
    r = subprocess.run(["bash", str(guard), "ASK-1"], capture_output=True, text=True)
    assert r.returncode == rc
    if ok:
        assert "OK to wait" in r.stdout
    else:
        assert "DO NOT WAIT" in r.stderr and "the stub's reason" in r.stderr


def test_wait_guard_with_the_real_check_rejects_a_typo_and_no_argument():
    import subprocess
    typo = subprocess.run(["bash", str(SCRIPTS / "wait-guard.sh"), "not-a-ref"], capture_output=True, text=True)
    assert typo.returncode == 64 and "DO NOT WAIT" in typo.stderr
    assert subprocess.run(["bash", str(SCRIPTS / "wait-guard.sh")], capture_output=True, text=True).returncode == 64
