"""usage_breaker replayed against a REAL week of Step 2 ledger rows (ASK-2010).

The fixture beside this file is the live `~/.config/kipi/usage-ledger.jsonl` of
2026-09-29, copied row for row with `session_id` nulled and `limit_text`
flattened to its first clause. Nothing here is invented: the shares, the
over-share verdicts and the limit warnings below are what the fleet actually
spent between 2026-09-23 and 2026-09-28.

Two real windows carry the two cases the DoR names:

  end 2026-09-24  lgtm 0.605 / radar 0.395, equal share 0.500  -> ONE bot over
  end 2026-09-28  radar 0.620 / lgtm 0.368 / chief 0.012, share 0.333 -> TWO over

The first is the DoR's "one bot over its share pauses, the others run, exactly
one alert". The second is what the same week looks like one day later, and it is
kept because a test that only ever sees its happy window cannot tell a breaker
from a constant.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from voiceloop import usage_breaker  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "usage-week-2026-09-28.json")
MODULE = os.path.join(os.path.dirname(__file__), "..", "usage_breaker.py")


def load_rows():
    """The fixture is a JSON ARRAY, not the ledger's own JSONL.

    The repo's blocked-paths pre-commit hook refuses a `.jsonl` file outright,
    and it is right to: a live ledger must never land in git. So the frozen copy
    is stored as an array and written back out as JSONL wherever a test needs to
    hand the CLI a real ledger path.
    """
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def rows():
    return load_rows()


@pytest.fixture()
def ledger(tmp_path):
    """The fixture rows as a JSONL file the CLI can read through KIPI_USAGE_LEDGER."""
    p = tmp_path / "usage-ledger.jsonl"
    p.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in load_rows()))
    return str(p)


# --- the arithmetic, against the measured week ------------------------------

def test_spend_by_bot_matches_the_measured_week(rows):
    spend = usage_breaker.spend_by_bot(usage_breaker.window(rows, "2026-09-28"))
    assert sorted(spend) == ["chief", "lgtm", "radar"]
    total = sum(spend.values())
    assert round(spend["radar"] / total, 3) == 0.620
    assert round(spend["lgtm"] / total, 3) == 0.368
    assert round(spend["chief"] / total, 3) == 0.012


def test_window_is_seven_days_and_excludes_what_falls_out(rows):
    inside = usage_breaker.window(rows, "2026-09-24")
    assert {str(r["ts"])[:10] for r in inside} == {"2026-09-23", "2026-09-24"}
    # chief's first row is 2026-09-28: a window ending the 24th cannot see it.
    assert "chief" not in usage_breaker.spend_by_bot(inside)


def test_shares_are_equal_when_no_bot_is_priority():
    assert usage_breaker.shares(["a", "b", "c"], priority=[]) == pytest.approx(
        {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3})


def test_priority_bots_get_the_reserved_fifth_on_top_of_an_equal_split():
    got = usage_breaker.shares(["a", "b", "c"], priority=["c"], reserve=0.2)
    assert got["a"] == pytest.approx(0.8 / 3)
    assert got["c"] == pytest.approx(0.8 / 3 + 0.2)
    assert sum(got.values()) == pytest.approx(1.0)


def test_shares_never_sum_under_one_when_the_reserve_has_no_claimant():
    # A reserve nobody can spend would leave every bot judged against 0.8/N and
    # push an ordinary fleet over its own line on day one.
    assert sum(usage_breaker.shares(["a", "b"], priority=[]).values()) == pytest.approx(1.0)


# --- the DoR's replay -------------------------------------------------------

def test_one_bot_over_its_share_pauses_and_the_others_run(rows):
    over = usage_breaker.over_share(rows, "2026-09-24")
    assert over == ["lgtm"], "the real 7-day window ending 2026-09-24 has exactly one bot over"
    assert usage_breaker.decide(rows, "radar", now="2026-09-24T12:00:00Z").action == "run"
    assert usage_breaker.decide(rows, "lgtm", now="2026-09-24T12:00:00Z").action == "pause"


def test_the_same_week_one_day_later_holds_two_bots_over(rows):
    assert usage_breaker.over_share(rows, "2026-09-28") == ["lgtm", "radar"]
    assert usage_breaker.decide(rows, "chief", now="2026-09-28T12:00:00Z").action == "run"


def test_a_bot_with_no_rows_in_the_window_is_never_paused(rows):
    d = usage_breaker.decide(rows, "worker", now="2026-09-28T12:00:00Z")
    assert d.action == "run"
    assert d.share_used == 0.0


# --- the fleet floor --------------------------------------------------------

def test_a_limit_warning_pauses_a_low_priority_bot_that_is_under_its_share(rows):
    # 19 rows in the real week carry a limit_text, so the warning is real too.
    assert usage_breaker.limit_warning(usage_breaker.window(rows, "2026-09-28"))
    d = usage_breaker.decide(rows, "chief", now="2026-09-28T12:00:00Z",
                             cfg={"low_priority": ["chief"]})
    assert d.action == "pause"
    assert d.reason == "fleet-floor"
    assert d.share_used < d.share_allowed, "paused on the floor, not on its share"


def test_no_limit_warning_means_the_floor_does_not_fire(rows):
    clean = [dict(r, limit_text=None) for r in rows]
    d = usage_breaker.decide(clean, "chief", now="2026-09-28T12:00:00Z",
                             cfg={"low_priority": ["chief"]})
    assert d.action == "run"


# --- the CLI: exit codes, one alert, one trial run --------------------------

def run_cli(tmp_path, bot, now, *, notify, ledger, env_extra=None, args=()):
    script, _ = notify
    env = dict(os.environ)
    env.update({
        "KIPI_USAGE_LEDGER": ledger,
        "KIPI_USAGE_BREAKER_STATE": str(tmp_path / "breaker.json"),
        "KIPI_NOTIFY": str(script),
    })
    env.pop("KIPI_USAGE_SHARES", None)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, MODULE, "check", "--bot", bot, "--now", now, *args],
                          capture_output=True, text=True, env=env)


@pytest.fixture()
def notify(tmp_path):
    """A stub standing in for slack-notify.sh, so the suite can read what was paged."""
    sink = tmp_path / "paged.txt"
    script = tmp_path / "notify.sh"
    script.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> {sink}\n')
    script.chmod(0o755)
    return script, sink


def paged(notify):
    _, sink = notify
    return sink.read_text().splitlines() if sink.exists() else []


def test_exit_0_for_a_bot_under_its_share(tmp_path, notify, ledger):
    r = run_cli(tmp_path, "radar", "2026-09-24T12:00:00Z", notify=notify, ledger=ledger)
    assert r.returncode == 0, r.stderr
    assert paged(notify) == []


def test_exit_3_and_exactly_one_alert_for_the_bot_over_its_share(tmp_path, notify, ledger):
    first = run_cli(tmp_path, "lgtm", "2026-09-24T12:00:00Z", notify=notify, ledger=ledger)
    assert first.returncode == 3, first.stderr
    assert len(paged(notify)) == 1
    assert "lgtm" in paged(notify)[0]
    # An hour later the pause still holds and NOBODY is paged a second time: the
    # worker runs every 15 minutes, so a per-check alert would be 96 pages a day.
    second = run_cli(tmp_path, "lgtm", "2026-09-24T13:00:00Z", notify=notify, ledger=ledger)
    assert second.returncode == 3
    assert len(paged(notify)) == 1


def test_one_trial_run_after_24_hours_then_the_pause_closes_again(tmp_path, notify, ledger):
    assert run_cli(tmp_path, "lgtm", "2026-09-24T12:00:00Z", notify=notify, ledger=ledger).returncode == 3
    # 23h: still held.
    assert run_cli(tmp_path, "lgtm", "2026-09-25T11:00:00Z", notify=notify, ledger=ledger).returncode == 3
    # 24h: exactly one trial run is granted.
    assert run_cli(tmp_path, "lgtm", "2026-09-25T12:00:00Z", notify=notify, ledger=ledger).returncode == 0
    # and only one -- the next check is held again, without a second page.
    assert run_cli(tmp_path, "lgtm", "2026-09-25T12:01:00Z", notify=notify, ledger=ledger).returncode == 3
    assert len(paged(notify)) == 1


def test_a_dry_check_reads_the_verdict_without_spending_the_trial(tmp_path, notify, ledger):
    """The one trial run belongs to the round that would actually spend.

    kipi-dispatch.sh runs `kipi work` WITHOUT --apply to pick the next issue, and
    converge launches the real `--apply` round minutes later. Both pass through
    the same brake, so the dry pick consumed the 24h trial and the round that was
    going to do the work was held for another day (claude review of PR #472,
    minor). A check that cannot spend anything must not be able to spend the
    permission to spend.
    """
    assert run_cli(tmp_path, "lgtm", "2026-09-24T12:00:00Z", notify=notify, ledger=ledger).returncode == 3
    # 24h in, the dry caller is told "you may run" and the trial is still unspent.
    dry = run_cli(tmp_path, "lgtm", "2026-09-25T12:00:00Z", notify=notify, ledger=ledger, args=("--dry",))
    assert dry.returncode == 0
    assert json.loads((tmp_path / "breaker.json").read_text())["bots"]["lgtm"]["trial_at"] is None
    # The round that spends still gets its trial.
    assert run_cli(tmp_path, "lgtm", "2026-09-25T12:05:00Z", notify=notify, ledger=ledger).returncode == 0
    assert json.loads((tmp_path / "breaker.json").read_text())["bots"]["lgtm"]["trial_at"]
    # and only one, as before: the trial is spent now.
    assert run_cli(tmp_path, "lgtm", "2026-09-25T12:06:00Z", notify=notify, ledger=ledger).returncode == 3
    assert len(paged(notify)) == 1


def test_a_dry_check_still_reports_a_held_bot_as_paused(tmp_path, notify, ledger):
    """--dry changes what is WRITTEN, never what is ANSWERED.

    A dry caller that read 0 while the bot is held would send the dispatcher on
    to claim an issue for a worker that pauses on the next breath.
    """
    assert run_cli(tmp_path, "lgtm", "2026-09-24T12:00:00Z", notify=notify, ledger=ledger).returncode == 3
    held = run_cli(tmp_path, "lgtm", "2026-09-24T13:00:00Z", notify=notify, ledger=ledger, args=("--dry",))
    assert held.returncode == 3
    assert len(paged(notify)) == 1


def test_a_dry_first_pause_neither_writes_state_nor_pages(tmp_path, notify, ledger):
    """The ticket belongs to the run that was about to spend, not to the pick.

    If the dry pick recorded the pause, the `--apply` round behind it would read
    "already paused" and the one alert would describe a run that never existed.
    """
    dry = run_cli(tmp_path, "lgtm", "2026-09-24T12:00:00Z", notify=notify, ledger=ledger, args=("--dry",))
    assert dry.returncode == 3
    assert paged(notify) == []
    assert not (tmp_path / "breaker.json").exists() or \
        json.loads((tmp_path / "breaker.json").read_text())["bots"].get("lgtm") in (None, {})
    # The apply round is the one that records it and pages, exactly once.
    assert run_cli(tmp_path, "lgtm", "2026-09-24T12:01:00Z", notify=notify, ledger=ledger).returncode == 3
    assert len(paged(notify)) == 1


def test_a_recovered_bot_clears_its_pause_and_can_be_paged_again(tmp_path, notify, ledger):
    assert run_cli(tmp_path, "lgtm", "2026-09-24T12:00:00Z", notify=notify, ledger=ledger).returncode == 3
    state = json.loads((tmp_path / "breaker.json").read_text())
    assert state["bots"]["lgtm"]["paused_at"]
    # An empty window is a recovered bot: no spend, no share used.
    assert run_cli(tmp_path, "lgtm", "2026-10-20T12:00:00Z", notify=notify, ledger=ledger).returncode == 0
    assert json.loads((tmp_path / "breaker.json").read_text())["bots"].get("lgtm", {}).get("paused_at") is None


def test_the_brake_fails_OPEN_and_says_so_when_the_ledger_is_unreadable(tmp_path, notify, ledger):
    r = run_cli(tmp_path, "lgtm", "2026-09-24T12:00:00Z", notify=notify, ledger=ledger,
                env_extra={"KIPI_USAGE_LEDGER": str(tmp_path / "nope.jsonl")})
    assert r.returncode == 0
    # Visible, per the DoR's "the brake must fail in a way that is visible".
    assert "no usage rows" in (r.stderr + r.stdout).lower()
    assert paged(notify) == []


def test_the_off_switch_is_honoured(tmp_path, notify, ledger):
    r = run_cli(tmp_path, "lgtm", "2026-09-24T12:00:00Z", notify=notify, ledger=ledger,
                env_extra={"KIPI_USAGE_BREAKER": "0"})
    assert r.returncode == 0, r.stderr
    assert paged(notify) == []


# --- the four findings from the claude review of PR #472 --------------------
# Each of these was run RED against the pre-fix module before the fix landed.
# Do not relax one without re-reading why it is here.


def test_a_bot_the_ledger_never_records_is_unmetered_not_under_share(tmp_path, notify, ledger):
    """major 1. `linear-worker.sh` checks bot `worker` and NOTHING writes that name.

    `prompt_render.py` is the ledger's only writer and no call site passes
    `bot="worker"`, so the pre-fix brake computed 0.000 of its share on every
    window of the real week and exited 0 forever while looking like a brake.
    It still exits 0 -- pausing a bot for not being instrumented yet is the wrong
    trade -- but it says so on stderr and pages Sana exactly once.
    """
    r = run_cli(tmp_path, "worker", "2026-09-28T12:00:00Z", notify=notify, ledger=ledger)
    assert r.returncode == 0, r.stderr
    assert "UNMETERED" in r.stderr
    assert len(paged(notify)) == 1, paged(notify)
    assert "worker" in paged(notify)[0] and "UNMETERED" in paged(notify)[0]
    # The one-alert contract holds across ticks, the same way a pause's does.
    assert run_cli(tmp_path, "worker", "2026-09-28T13:00:00Z",
                   notify=notify, ledger=ledger).returncode == 0
    assert len(paged(notify)) == 1, paged(notify)


def test_a_metered_bot_is_never_called_unmetered(tmp_path, notify, ledger):
    """The negative half. Without it, `unmetered` could swallow every verdict."""
    r = run_cli(tmp_path, "radar", "2026-09-24T12:00:00Z", notify=notify, ledger=ledger)
    assert r.returncode == 0, r.stderr
    assert "UNMETERED" not in r.stderr
    assert paged(notify) == []


def test_an_empty_window_is_a_quiet_fleet_not_an_unmetered_bot(tmp_path, notify, ledger):
    """No rows for ANYONE is not the same fact as no rows for THIS bot.

    Conflating them pages about every bot during any quiet week, and clobbers the
    resume of a bot whose pause has aged out of the window.
    """
    r = run_cli(tmp_path, "lgtm", "2026-10-20T12:00:00Z", notify=notify, ledger=ledger)
    assert r.returncode == 0, r.stderr
    assert "UNMETERED" not in r.stderr
    assert paged(notify) == []


def test_no_share_line_pauses_anything_until_the_window_clears_the_floor(tmp_path, notify):
    """major 2. A share is a RANK, so somebody is always over it.

    Three cents across two bots, one holding 60% of it. Pre-fix that paused the
    top spender and filed a Linear ticket about $0.018.
    """
    ledger = tmp_path / "pennies.jsonl"
    pennies = [
        {"ts": "2026-09-24T01:00:00Z", "bot": "lgtm", "total_cost_usd": 0.018},
        {"ts": "2026-09-24T02:00:00Z", "bot": "radar", "total_cost_usd": 0.012},
    ]
    ledger.write_text("".join(json.dumps(r) + "\n" for r in pennies))
    r = run_cli(tmp_path, "lgtm", "2026-09-24T12:00:00Z", notify=notify, ledger=str(ledger))
    assert r.returncode == 0, r.stderr
    assert paged(notify) == []
    # The ranking itself is unchanged: lgtm IS the top spender, it is just not
    # worth pausing. The floor suppresses the ACTION, never the arithmetic.
    assert usage_breaker.decide(pennies, "lgtm", "2026-09-24").reason == "under-floor"
    assert usage_breaker.over_share(pennies, "2026-09-24") == []


def test_the_dollar_floor_does_not_excuse_the_real_week(rows):
    """The floor must not be red on the fleet's own population.

    $26.97 and $49.23 are what the two real windows in the fixture hold, so the
    $5.00 default leaves the DoR's own check intact: lgtm still pauses.
    """
    d = usage_breaker.decide(rows, "lgtm", "2026-09-24")
    assert (d.action, d.reason) == ("pause", "over-share")
    assert usage_breaker.over_share(rows, "2026-09-24") == ["lgtm"]


def test_the_fleet_floor_is_not_subject_to_the_dollar_floor(tmp_path, notify):
    """A `limit_text` row is the subscription refusing a call -- a fact, not a rank.

    Two cents of spend, so the dollar floor is nowhere near cleared, and the
    low-priority bot pauses anyway.
    """
    ledger = tmp_path / "limited.jsonl"
    ledger.write_text(json.dumps(
        {"ts": "2026-09-24T01:00:00Z", "bot": "lgtm", "total_cost_usd": 0.02,
         "limit_text": "weekly limit reached"}) + "\n")
    shares_cfg = tmp_path / "shares.json"
    shares_cfg.write_text(json.dumps({"low_priority": ["lgtm"]}))
    r = run_cli(tmp_path, "lgtm", "2026-09-24T12:00:00Z", notify=notify, ledger=str(ledger),
                env_extra={"KIPI_USAGE_SHARES": str(shares_cfg)})
    assert r.returncode == 3, r.stdout + r.stderr
    assert len(paged(notify)) == 1


def test_an_unwritable_state_file_pauses_but_never_pages(tmp_path, notify, ledger):
    """minor. `write_state` returned a bool the caller threw away.

    Nothing remembered the pause, so every one of the worker's 15-minute ticks
    re-entered the first-pause branch: 96 Linear tickets a day out of a contract
    that promises one. The alert is now gated on the write that backs it.
    """
    (tmp_path / "nodir").write_text("i am a file, not a directory")
    r = run_cli(tmp_path, "lgtm", "2026-09-24T12:00:00Z", notify=notify, ledger=ledger,
                env_extra={"KIPI_USAGE_BREAKER_STATE": str(tmp_path / "nodir" / "breaker.json")})
    assert r.returncode == 3, r.stdout + r.stderr
    assert "NOT paging" in r.stderr
    assert paged(notify) == []
