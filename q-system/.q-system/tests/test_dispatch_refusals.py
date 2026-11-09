#!/usr/bin/env python3
"""ASK-3958: a refusal that does not heal gets one consumer, at 12h, per repo+check.

RED BEFORE GREEN. Written before dispatch-refusals.py existed, so the first run is
a missing file. Every case runs the script as the dispatcher does (a subprocess,
stdout as its input) against a tmp state file and a fixed clock. None of them can
reach the live ~/.config/kipi/dispatch-refusals.tsv: the script refuses that path
under pytest, and test_refuses_the_live_path_under_pytest proves the refusal.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "dispatch-refusals.py"
H = 3600
T0 = 1_800_000_000


def run(state, *args, at=T0, hours=None, env_extra=None):
    env = dict(os.environ, KIPI_DISPATCH_REFUSALS=str(state), KIPI_DISPATCH_NOW=str(at))
    if hours is not None:
        env["KIPI_DISPATCH_REFUSAL_HOURS"] = str(hours)
    if env_extra:
        env.update(env_extra)
    res = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                         text=True, env=env)
    return res.returncode, res.stdout.split("\n")[:-1] if res.stdout else []


@pytest.fixture()
def state(tmp_path):
    return tmp_path / "dispatch-refusals.tsv"


def test_a_first_refusal_files_nothing(state):
    assert run(state, "refused", "ktlyst", "hooks") == (0, [])


def test_eleven_hours_files_nothing(state):
    """The mutant: a consumer that fires early would file every measured transient."""
    run(state, "refused", "ktlyst", "hooks", at=T0)
    assert run(state, "refused", "ktlyst", "hooks", at=T0 + 11 * H) == (0, [])


def test_twelve_hours_is_due(state):
    run(state, "refused", "ktlyst", "hooks", at=T0)
    assert run(state, "refused", "ktlyst", "hooks", at=T0 + 12 * H) == (0, ["DUE hooks"])


def test_a_new_check_does_not_inherit_the_old_clock(state):
    run(state, "refused", "ktlyst", "hooks", at=T0)
    rc, out = run(state, "refused", "ktlyst", "hooks", "remote", at=T0 + 12 * H)
    assert out == ["DUE hooks"]
    # `remote` started failing at +12h, so it is not due until +24h.
    assert run(state, "refused", "ktlyst", "remote", at=T0 + 20 * H)[1] == ["CLEARED hooks"]
    assert run(state, "refused", "ktlyst", "remote", at=T0 + 24 * H)[1] == ["DUE remote"]


def test_a_check_that_stops_failing_is_cleared_and_its_clock_reset(state):
    run(state, "refused", "ktlyst", "hooks", at=T0)
    assert run(state, "refused", "ktlyst", "remote", at=T0 + H)[1] == ["CLEARED hooks"]
    # hooks fails again: a new episode, a new clock.
    run(state, "refused", "ktlyst", "hooks", at=T0 + 2 * H)
    assert run(state, "refused", "ktlyst", "hooks", at=T0 + 13 * H)[1] == []


def test_a_pass_clears_every_check(state):
    run(state, "refused", "ktlyst", "hooks", "remote", at=T0)
    rc, out = run(state, "passed", "ktlyst", at=T0 + H)
    assert sorted(out) == ["CLEARED hooks", "CLEARED remote"]
    assert state.read_text() == ""


def test_a_pass_on_a_clean_repo_writes_nothing(state):
    assert run(state, "passed", "ktlyst") == (0, [])
    assert not state.exists()


def test_other_repos_keep_their_clocks(state):
    run(state, "refused", "ktlyst", "hooks", at=T0)
    run(state, "refused", "brag", "hooks", at=T0 + 6 * H)
    run(state, "passed", "brag", at=T0 + 7 * H)
    assert run(state, "refused", "ktlyst", "hooks", at=T0 + 12 * H)[1] == ["DUE hooks"]


def test_a_kill_switch_refusal_is_never_due(state):
    """PR #681 r1 major. `.kipi-no-dispatch` is a decision (written on purpose by
    ~/.config/kipi/usage-pacer.py and the 2026-11-08 usage pause, both outside this
    repo), so a ticket asking Sana to fix it is noise that argues against the one
    gate that protects client work."""
    for h in (0, 13, 37, 61):
        assert run(state, "refused", "ktlyst", "kill-switch", at=T0 + h * H) == (0, [])
    assert not state.exists() or "kill-switch" not in state.read_text()


def test_a_kill_switch_tick_is_not_an_observation(state):
    """Preflight stops at the kill switch, so that tick says nothing about hooks.
    It must neither clear the hooks clock nor advance it."""
    run(state, "refused", "ktlyst", "hooks", at=T0)
    assert run(state, "refused", "ktlyst", "kill-switch", at=T0 + 6 * H)[1] == []
    assert state.read_text() == f"ktlyst\thooks\t{T0}\t{T0}\n"
    assert run(state, "refused", "ktlyst", "hooks", at=T0 + 12 * H)[1] == ["DUE hooks"]


def test_a_long_gap_restarts_the_clock(state):
    """PR #681 r1 minor. Two refusals 30 days apart are not 30 days of refusal:
    the row left the rotation, came back, and refused once."""
    run(state, "refused", "ktlyst", "hooks", at=T0)
    assert run(state, "refused", "ktlyst", "hooks", at=T0 + 30 * 24 * H)[1] == []
    t1 = T0 + 30 * 24 * H
    assert state.read_text() == f"ktlyst\thooks\t{t1}\t{t1}\n"
    assert run(state, "refused", "ktlyst", "hooks", at=t1 + 12 * H)[1] == ["DUE hooks"]


def test_just_past_the_gap_bound_restarts(state):
    run(state, "refused", "ktlyst", "hooks", at=T0)
    assert run(state, "refused", "ktlyst", "hooks", at=T0 + 49 * H)[1] == []


def test_the_daily_cap_gap_keeps_the_clock(state):
    """The mutant a tight gap bound would be. Measured on dispatch.log: the daily
    cap stops pick_list ~23.3h a day (max 24.1h, one 34.5h outlier), so a bound
    under that restarts every clock daily and nothing is ever filed."""
    run(state, "refused", "ktlyst", "hooks", at=T0)
    run(state, "refused", "ktlyst", "hooks", at=T0 + H)
    assert run(state, "refused", "ktlyst", "hooks", at=T0 + H + int(34.5 * H))[1] == ["DUE hooks"]


def test_the_gap_bound_is_read_from_the_env(state):
    env = {"KIPI_DISPATCH_REFUSAL_GAP_HOURS": "2"}
    run(state, "refused", "ktlyst", "hooks", at=T0, env_extra=env)
    assert run(state, "refused", "ktlyst", "hooks", at=T0 + 13 * H, env_extra=env)[1] == []


def test_the_threshold_is_read_from_the_env(state):
    run(state, "refused", "ktlyst", "hooks", at=T0, hours=1)
    assert run(state, "refused", "ktlyst", "hooks", at=T0 + H, hours=1)[1] == ["DUE hooks"]


def test_a_malformed_row_costs_its_clock_not_the_run(state):
    state.write_text("garbage\nktlyst\thooks\tnot-a-number\t1\n")
    assert run(state, "refused", "ktlyst", "hooks", at=T0) == (0, [])
    assert state.read_text() == f"ktlyst\thooks\t{T0}\t{T0}\n"


def test_usage_errors_exit_2(state):
    # Python exits 2 on a missing script too, so without this the case is green on
    # a branch that never shipped the file.
    assert SCRIPT.is_file()
    assert run(state)[0] == 2
    assert run(state, "refused", "ktlyst")[0] == 2
    assert run(state, "bogus", "ktlyst")[0] == 2


def test_refuses_the_live_path_under_pytest(tmp_path):
    """The chokepoint, proven. PYTEST_CURRENT_TEST is set by pytest itself."""
    assert os.environ.get("PYTEST_CURRENT_TEST")
    # HOME is the tmp dir, so even a broken chokepoint writes nowhere real. The
    # default path is then tmp's, and the refusal must still fire on it.
    env = {k: v for k, v in os.environ.items() if k != "KIPI_DISPATCH_REFUSALS"}
    env["HOME"] = str(tmp_path)
    res = subprocess.run([sys.executable, str(SCRIPT), "refused", "ktlyst", "hooks"],
                         capture_output=True, text=True, env=env)
    assert res.returncode == 4
    assert not (tmp_path / ".config" / "kipi" / "dispatch-refusals.tsv").exists()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
