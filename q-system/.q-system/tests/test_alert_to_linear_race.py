#!/usr/bin/env python3
"""Two concurrent alert writers must open ONE permanent Linear ticket, not two.

THE DEFECT (PR #198 review round 4, major). alert-to-linear.py's file_alert
reads the fingerprint state, and only if it finds no open ticket does it create
one. Two callers that both reach the read before either reaches the write both
see "no ticket" and both create. Two permanent Linear objects for one condition:
nothing collapses them, a human closes each by hand, and a queue that repeats
itself is a queue people learn to skim. The heartbeat can overlap with itself
(each instance is bounded at 1800s, so a wide sweep can outlive the gap to the
next fire) and it is one of ~30 call sites, several of them launchd jobs that
fire on the hour.

WHY THIS SUITE IS BUILT THE WAY IT IS. A concurrency test that spawns two
workers and asserts "one ticket" is exactly the shape that passes for the wrong
reason -- the two runs serialize by luck, or the payload sends both down an
early-exit path, and the assertion holds against code with no locking at all.
This session already produced one of those. So every case here carries its own
negative control: the SAME spawn, with only `mod._fingerprint_lock` replaced by
a no-op, must produce more than one create. If the control cannot go red, the
test is decoration and this suite fails saying so.

The control lives in the child helper, NOT behind a production env switch. A
knob that disables serialization on the live alert path is a way to lose the
fix; a test that monkeypatches its own copy of the module is not.

Nothing here can reach Linear: the child replaces _load_linear with a fake that
records creates to a file, and _state_dir with a tmp path.
"""
import json
import os
import subprocess
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ALERT = os.path.join(HERE, "..", "scripts", "alert-to-linear.py")

# The window. A real issueCreate is an HTTP round trip; the fake makes that
# duration explicit so the race is deterministic instead of lucky. Long enough
# that every child is inside file_alert before the first create returns, which
# is what a wall-clock barrier alone cannot guarantee.
SLOW = 1.5

MSG_A = "[fake-instance] heartbeat: sweep HALTED, the runner itself is unavailable"
MSG_B = "[fake-instance] SECURITY: unsanctioned change detected in a watched tree"


CHILD = r'''
import contextlib, json, os, sys, time
import importlib.util

spec = importlib.util.spec_from_file_location("alert_child", os.environ["RACE_MODULE"])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

STATE = os.environ["RACE_STATE"]
CREATES = os.environ["RACE_CREATES"]
TAG = os.environ["RACE_TAG"]
SLOW = float(os.environ["RACE_SLOW"])

mod._state_dir = lambda: STATE


class Fake:
    def linear_api_key(self):
        return "stub"

    def graphql(self, query, variables):
        if "teams(filter" in query:
            return {"teams": {"nodes": [{"id": "team-1", "key": "ASK"}]}}
        if "labels(first" in query:
            return {"team": {"labels": {"nodes": [
                {"id": "lab-1", "name": "owner:sana"}]}}}
        if "projects(first" in query:
            return {"team": {"projects": {"nodes": []}}}
        if "issueCreate" in query:
            # Sleep BEFORE recording: the window has to be open while the other
            # children are doing their own _read_state, which is the moment the
            # unlocked code makes its wrong decision.
            time.sleep(SLOW)
            with open(CREATES, "a", encoding="utf-8") as fh:
                fh.write(TAG + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return {"issueCreate": {"success": True, "issue": {
                "id": "iss-" + TAG, "identifier": "ASK-9" + TAG,
                "url": "https://linear.app/x"}}}
        if "issue(id" in query:
            return {"issue": {"id": "iss-x", "identifier": "ASK-901",
                              "url": "https://linear.app/x",
                              "state": {"type": "unstarted"}}}
        if "commentCreate" in query:
            return {"commentCreate": {"success": True}}
        return {}


mod._load_linear = lambda: Fake()

if os.environ.get("RACE_NOLOCK") == "1":
    @contextlib.contextmanager
    def _nolock(fp, wait=None):
        yield True
    mod._fingerprint_lock = _nolock

# WALL-CLOCK BARRIER, not a sleep in the parent. Interpreter startup plus module
# exec is tens to hundreds of ms and varies per child; a parent-side sleep window
# is exactly how a race control comes out flaky (2 of 5, measured elsewhere in
# this fleet). Every child waits for the same absolute instant.
barrier = float(os.environ["RACE_BARRIER"])
while time.time() < barrier:
    time.sleep(0.002)

code, line = mod.file_alert(os.environ["RACE_MSG"], now=1000.0)
print(json.dumps({"code": code, "line": line, "end": time.time()}))
'''


def _spawn(tmp_path, messages, nolock, creates_name):
    """Run one child per message, all released at one wall-clock instant.

    Returns (creates_recorded, [child result dicts], barrier).
    """
    child_py = tmp_path / f"child_{creates_name}.py"
    child_py.write_text(CHILD, encoding="utf-8")
    state = tmp_path / f"state_{creates_name}"
    state.mkdir()
    creates = tmp_path / f"creates_{creates_name}"
    creates.write_text("", encoding="utf-8")

    # 2.5s of lead so every child is parked on the barrier before it opens.
    barrier = time.time() + 2.5
    procs = []
    for i, msg in enumerate(messages):
        env = dict(os.environ)
        # PYTEST_CURRENT_TEST would make main() refuse -- the children call
        # file_alert directly, but drop it anyway so nothing in the child can
        # take a fixture-refusal path and make the count zero for a reason that
        # has nothing to do with the lock.
        env.pop("PYTEST_CURRENT_TEST", None)
        env.update({
            "RACE_MODULE": os.path.abspath(ALERT),
            "RACE_STATE": str(state),
            "RACE_CREATES": str(creates),
            "RACE_TAG": str(i),
            "RACE_SLOW": str(SLOW),
            "RACE_BARRIER": f"{barrier:.6f}",
            "RACE_MSG": msg,
            "RACE_NOLOCK": "1" if nolock else "0",
        })
        procs.append(subprocess.Popen(
            [sys.executable, str(child_py)], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))

    results = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, f"child crashed: rc={p.returncode} err={err}"
        results.append(json.loads(out.strip().splitlines()[-1]))

    recorded = [l for l in creates.read_text(encoding="utf-8").splitlines() if l]
    return recorded, results, barrier


def test_the_control_can_go_red_without_the_lock(tmp_path):
    """THE NEGATIVE SELF-TEST, run first and on its own.

    If four simultaneous writers do NOT duplicate once the lock is removed, the
    fixture is not reproducing the race and the assertion below it proves
    nothing. This case failing means the harness is broken, not the fix.
    """
    recorded, _results, _b = _spawn(tmp_path, [MSG_A] * 4, nolock=True,
                                    creates_name="control")
    assert len(recorded) > 1, (
        "the no-lock control created "
        f"{len(recorded)} ticket(s); the fixture is not reproducing the race, "
        "so the locked assertion beside it would pass against unlocked code")


def test_concurrent_writers_open_exactly_one_ticket(tmp_path):
    """The fix. Four writers, one fingerprint, one permanent Linear object."""
    recorded, results, _b = _spawn(tmp_path, [MSG_A] * 4, nolock=False,
                                   creates_name="locked")
    assert len(recorded) == 1, (
        f"{len(recorded)} tickets created for one condition: {results}")
    # And the losers are not silently dropped -- they land on the repeat path,
    # which is the count that makes a still-firing alert visible as still-firing.
    repeats = [r for r in results if "repeat #" in r["line"]]
    assert len(repeats) == 3, f"expected 3 counted repeats, got {results}"
    assert not any("refusing to create a duplicate" in r["line"] for r in results), \
        "a writer timed out on the lock in an uncontended fixture"


def test_two_different_alerts_are_not_serialized_behind_each_other(tmp_path):
    """The lock is per fingerprint, and a global one would fail HERE, not in prod.

    A single global lock passes the duplicate test above while queueing every
    unrelated alert behind the slowest HTTP call in the fleet. Two distinct
    shapes must still create in parallel, so the wall clock is the instrument:
    serialized would be >= 2 x SLOW, parallel is ~1 x SLOW. The bound is
    1.7 x SLOW, which leaves 0.45s of jitter at SLOW=1.5 and still cannot be
    reached by a serialized run.
    """
    recorded, results, barrier = _spawn(tmp_path, [MSG_A, MSG_B], nolock=False,
                                        creates_name="distinct")
    assert len(recorded) == 2, "two distinct alerts must each get their ticket"
    elapsed = max(r["end"] for r in results) - barrier
    assert elapsed < SLOW * 1.7, (
        f"two unrelated alerts took {elapsed:.2f}s for {SLOW}s of work each; "
        "they are sharing one lock instead of one per fingerprint")


def _module_with_fake(monkeypatch, state_dir, created, name):
    """A fresh module copy with Linear stubbed and its state dir pointed at tmp."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, ALERT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_state_dir", lambda: str(state_dir))

    class Fake:
        def linear_api_key(self):
            return "stub"

        def graphql(self, query, variables):
            if "teams(filter" in query:
                return {"teams": {"nodes": [{"id": "t", "key": "ASK"}]}}
            if "labels(first" in query:
                return {"team": {"labels": {"nodes": []}}}
            if "projects(first" in query:
                return {"team": {"projects": {"nodes": []}}}
            if "issueCreate" in query:
                created.append(1)
                return {"issueCreate": {"success": True, "issue": {
                    "id": "i", "identifier": "ASK-902", "url": "u"}}}
            if "issue(id" in query:
                return {"issue": {"id": "i", "identifier": "ASK-902", "url": "u",
                                  "state": {"type": "unstarted"}}}
            if "commentCreate" in query:
                return {"commentCreate": {"success": True}}
            return {}

    monkeypatch.setattr(mod, "_load_linear", lambda: Fake())
    return mod


def test_a_caller_without_the_lock_never_creates(tmp_path, monkeypatch):
    """THE ROUND-5 FINDING, pinned.

    The first cut of this fix let an unlocked caller file anyway, which made
    "no duplicates" contingent on LOCK_WAIT_SECONDS being longer than the
    slowest holder -- and the value shipped (25s) was shorter than ONE of the
    six HTTP calls the section can make, each capped at 30s. The reviewer
    reproduced creates=2 by scaling the wait below the request duration.

    Creation is now gated on holding the lock, so no value of that number can
    bring the duplicate back. An unlocked caller with nothing to count reports a
    failed send, which is slack-notify.sh's documented exit 1 and reaches Linear
    by the launchd route rather than by a second permanent ticket.
    """
    state = tmp_path / "state"
    state.mkdir()
    created = []
    mod = _module_with_fake(monkeypatch, state, created, "alert_nolock")

    # An unwritable state dir: makedirs and open both fail, so no lock is held.
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    with mod._fingerprint_lock("deadbeef") as held:
        assert held is True, "control: a writable dir must yield a held lock"
    monkeypatch.setattr(mod, "_state_dir", lambda: str(blocked / "sub"))
    with mod._fingerprint_lock("deadbeef") as held:
        assert held is False, "the lock reported success on an unwritable dir"

    code, line = mod.file_alert(MSG_A, now=1000.0)
    assert created == [], "an unlocked caller created a permanent Linear ticket"
    assert code == mod.EXIT_FAILED, f"want a reported failure, got {code}: {line}"
    assert "refusing to create a duplicate" in line, line
    assert MSG_A in line, "the undelivered message must stay readable"


def test_a_slow_holder_that_outlives_the_wait_costs_no_duplicate(tmp_path):
    """The reviewer's scenario end to end, with real processes and a real flock.

    LOCK_WAIT_SECONDS is forced BELOW the holder's work so the waiter is
    guaranteed to time out -- the exact condition that produced creates=2 before
    this round. One create is the whole assertion.
    """
    env_wait = "0.3"          # far below SLOW, so the second child always gives up
    child_py = tmp_path / "child_slow.py"
    child_py.write_text(CHILD, encoding="utf-8")
    state = tmp_path / "state_slow"
    state.mkdir()
    creates = tmp_path / "creates_slow"
    creates.write_text("", encoding="utf-8")

    barrier = time.time() + 2.5
    procs = []
    for i in range(2):
        env = dict(os.environ)
        env.pop("PYTEST_CURRENT_TEST", None)
        env.update({
            "RACE_MODULE": os.path.abspath(ALERT),
            "RACE_STATE": str(state),
            "RACE_CREATES": str(creates),
            "RACE_TAG": str(i),
            "RACE_SLOW": str(SLOW),
            "RACE_BARRIER": f"{barrier:.6f}",
            "RACE_MSG": MSG_A,
            "RACE_NOLOCK": "0",
            "KIPI_ALERT_LOCK_WAIT_SECONDS": env_wait,
        })
        procs.append(subprocess.Popen(
            [sys.executable, str(child_py)], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))

    results = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, f"child crashed: rc={p.returncode} err={err}"
        results.append(json.loads(out.strip().splitlines()[-1]))

    recorded = [l for l in creates.read_text(encoding="utf-8").splitlines() if l]
    assert len(recorded) == 1, (
        f"a {env_wait}s wait against {SLOW}s of held work produced "
        f"{len(recorded)} tickets: {results}")
    refused = [r for r in results if "refusing to create a duplicate" in r["line"]]
    assert len(refused) == 1, (
        "the loser neither counted nor refused out loud -- if it silently "
        f"succeeded, the wait did not actually expire: {results}")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
