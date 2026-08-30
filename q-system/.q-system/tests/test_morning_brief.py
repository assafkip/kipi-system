#!/usr/bin/env python3
"""Engine test for the morning brief (ASK-1178).

RED FIRST. Every case here was written and seen to fail before
`morning-brief.py`, `morning-brief-deadman.py` or `slack_founder.py` existed.
The first run is a bare ImportError on all of them; that counts as red only
because the import assertions below name the missing module explicitly. A
collection error is NOT a red run (it means zero tests executed), so the module
loader returns a skip-free failure rather than blowing up at import time.

## What this suite may NOT do

No live data path. It never calls Slack, never calls `claude -p`, never reads
the founder's real Linear key, and never writes `~/.config/kipi/`. Every
outbound seam is either injected or refused by the chokepoint under
`PYTEST_CURRENT_TEST`. Two cases assert those refusals directly, because a
chokepoint nobody tests is a chokepoint that gets removed in a refactor.

## The property the whole file exists for

A section that could not be read must never render like a section that was
empty. That is the defect that killed the 9-phase pipeline: it produced
nothing for 148 days and every consumer read the nothing as a quiet day.
So `test_every_section_can_say_failed_distinctly_from_zero` walks all four
sections and asserts the two renderings differ, section by section, rather
than spot-checking one of them.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"


def _load(stem: str, filename: str):
    """Import a hyphenated script by path.

    Named modules, not a glob: a loader that silently returns None on a missing
    file would turn "the script does not exist" into a passing test, which is
    the exact shape this suite is built to refuse.
    """
    path = SCRIPTS / filename
    assert path.is_file(), f"missing script: {path}"
    spec = importlib.util.spec_from_file_location(stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[stem] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def brief():
    return _load("morning_brief", "morning-brief.py")


@pytest.fixture(scope="module")
def deadman():
    return _load("morning_brief_deadman", "morning-brief-deadman.py")


@pytest.fixture(scope="module")
def sender():
    return _load("slack_founder", "slack_founder.py")


NOW = dt.datetime(2026, 8, 30, 7, 0, 0, tzinfo=dt.timezone.utc).astimezone()


# --------------------------------------------------------------------------
# Constraint 3: FAILED is distinct from zero, in every one of the four sections
# --------------------------------------------------------------------------

def _sources(**overrides):
    """Four sections, all empty-and-healthy, with per-section overrides."""
    base = {k: ([], None) for k in ("calendar", "mail", "owed", "overnight")}
    base.update(overrides)
    return base


def test_every_section_can_say_failed_distinctly_from_zero(brief):
    for name in ("calendar", "mail", "owed", "overnight"):
        empty, _ = brief.build(NOW, _sources())
        broken, degraded = brief.build(NOW, _sources(**{name: ([], "boom")}))
        assert empty != broken, f"{name}: a broken section renders like an empty one"
        assert "COULD NOT READ" in broken, f"{name}: no failure marker"
        assert "boom" in broken, f"{name}: the reason is dropped"
        assert degraded, f"{name}: a broken section did not mark the run degraded"


def test_all_empty_is_not_degraded_and_says_nothing(brief):
    message, degraded = brief.build(NOW, _sources())
    assert not degraded
    assert "COULD NOT READ" not in message
    assert message.count("nothing") == 4


def test_all_four_sections_are_present_by_name(brief):
    message, _ = brief.build(NOW, _sources())
    for title in ("Today", "Mail", "Owed", "Overnight"):
        assert title in message, f"section {title} missing from the brief"


def test_no_html_no_cards_no_scores(brief):
    """Constraint 4. The founder asked for prose, not the thing that died."""
    rows = [{"title": "x", "line": "y"}]
    message, _ = brief.build(NOW, _sources(
        calendar=(["09:00 standup (assaf, cole)"], None),
        owed=(["ASK-1 do the thing"], None),
    ))
    for banned in ("<html", "<div", "<table", "<br", "score:", "Score:"):
        assert banned not in message, f"brief contains {banned!r}"
    assert rows  # the fixture is deliberately unused by build(); shape only


# --------------------------------------------------------------------------
# Constraint 2: delivery is read off Slack's answer, never off an exit code
# --------------------------------------------------------------------------

class _Resp:
    def __init__(self, body, status=200):
        self._body = body.encode()
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_webhook_ok_body_is_the_only_success(sender):
    got = sender.post_webhook("https://hooks.slack.com/x", "hi",
                              opener=lambda req, timeout: _Resp("ok"))
    assert got["delivered"] is True


def test_webhook_http_200_with_a_non_ok_body_is_a_failure(sender):
    """The trap: Slack answers 200 and still refuses. An exit code sees green."""
    got = sender.post_webhook("https://hooks.slack.com/x", "hi",
                              opener=lambda req, timeout: _Resp("no_service"))
    assert got["delivered"] is False
    assert "no_service" in json.dumps(got)


def test_bot_post_reads_ok_false_as_undelivered(sender):
    body = json.dumps({"ok": False, "error": "channel_not_found"})
    got = sender.post_bot("xoxb-fake", "C0", "hi",
                          opener=lambda req, timeout: _Resp(body))
    assert got["delivered"] is False
    assert got.get("error") == "channel_not_found"


def test_bot_post_reads_ok_true_as_delivered(sender):
    got = sender.post_bot("xoxb-fake", "C0", "hi",
                          opener=lambda req, timeout: _Resp(json.dumps({"ok": True})))
    assert got["delivered"] is True


def test_no_credential_is_reported_not_swallowed(sender):
    got = sender.deliver("hi", webhook="", token="", channel="C0")
    assert got["delivered"] is False
    assert got.get("reason")


# --------------------------------------------------------------------------
# Constraint 1: nothing routes through slack-notify.sh
# --------------------------------------------------------------------------

def _executable_source(path: Path) -> str:
    """The file's code with comments AND docstrings removed.

    First version stripped only `#` lines and went red on all three files, which
    all name slack-notify.sh in their module docstring for the right reason: to
    say why they do not use it. A text check that cannot tell a warning about a
    thing from a call to it is not a check, it is a ban on the word. Every one of
    these files is REQUIRED to explain the choice; only the code must be clean.
    """
    import io
    import tokenize
    out, prev_end, prev_type = [], (1, 0), None
    with open(path, "rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING and prev_type in (
                    None, tokenize.INDENT, tokenize.NEWLINE, tokenize.NL,
                    tokenize.DEDENT, tokenize.ENCODING):
                # A bare string statement: a docstring.
                prev_type = tok.type
                continue
            out.append(tok.string)
            prev_type = tok.type
            prev_end = tok.end
    assert prev_end
    return "\n".join(out)


def test_no_source_file_calls_slack_notify(brief, deadman, sender):
    for filename in ("morning-brief.py", "morning-brief-deadman.py", "slack_founder.py"):
        code = _executable_source(SCRIPTS / filename)
        assert "slack-notify" not in code, (
            f"{filename} routes the founder's brief through the fleet ALERT path, "
            "which files a Linear ticket for Sana and sends nothing to Slack")


def test_the_slack_notify_check_can_actually_fail(tmp_path):
    """Negative self-test. Without this the case above passes on an empty string.

    Proves two things at once: a real call site IS caught, and a mention inside a
    docstring is NOT -- which is the distinction the stripper exists to make.
    """
    caller = tmp_path / "caller.py"
    caller.write_text('import subprocess\nsubprocess.run(["bash", "slack-notify.sh", "x"])\n')
    assert "slack-notify" in _executable_source(caller)

    explainer = tmp_path / "explainer.py"
    explainer.write_text('"""We never use slack-notify.sh; it files a ticket."""\nx = 1\n')
    assert "slack-notify" not in _executable_source(explainer)


# --------------------------------------------------------------------------
# Test isolation: the live seams refuse themselves under pytest
# --------------------------------------------------------------------------

def test_sender_refuses_to_deliver_under_pytest(sender):
    assert os.environ.get("PYTEST_CURRENT_TEST")
    got = sender.deliver("this must never reach the founder",
                         webhook="https://hooks.slack.com/real",
                         token="xoxb-real", channel="C04Q71LA283")
    assert got["delivered"] is False
    assert got.get("refused") is True


def test_model_call_refuses_under_pytest(brief):
    text, error = brief.run_claude("say hi", ["mcp__x__y"])
    assert text is None
    assert "refused" in (error or "").lower()


# --------------------------------------------------------------------------
# Collectors: each one turns a broken source into an error, not into []
# --------------------------------------------------------------------------

def test_calendar_collector_reports_a_model_failure(brief):
    rows, error = brief.collect_calendar(
        NOW, runner=lambda prompt, tools: (None, "claude exited 1"))
    assert rows == []
    assert "claude exited 1" in error


def test_calendar_collector_reports_unparseable_output(brief):
    rows, error = brief.collect_calendar(
        NOW, runner=lambda prompt, tools: ("I could not reach the calendar", None))
    assert rows == []
    assert error


def test_calendar_collector_parses_events(brief):
    payload = json.dumps({"events": [
        {"start": "09:00", "title": "Chris PI sync", "who": ["chris"]}]})
    rows, error = brief.collect_calendar(NOW, runner=lambda p, t: (payload, None))
    assert error is None
    assert len(rows) == 1
    assert "Chris PI sync" in rows[0]


def test_calendar_empty_is_empty_not_an_error(brief):
    rows, error = brief.collect_calendar(
        NOW, runner=lambda p, t: (json.dumps({"events": []}), None))
    assert rows == []
    assert error is None


def test_mail_collector_reports_a_model_failure(brief):
    rows, error = brief.collect_mail(NOW, runner=lambda p, t: (None, "timeout"))
    assert rows == []
    assert "timeout" in error


def test_mail_collector_parses_threads(brief):
    payload = json.dumps({"threads": [
        {"from": "chris@pi.com", "subject": "SOW", "age_hours": 20}]})
    rows, error = brief.collect_mail(NOW, runner=lambda p, t: (payload, None))
    assert error is None
    assert any("chris@pi.com" in r for r in rows)


def test_owed_reports_a_linear_failure_without_hiding_the_loops(brief, tmp_path):
    """A half-broken section still says it is half broken."""
    loops = tmp_path / "memory"
    loops.mkdir()
    (loops / "open-loops.json").write_text(json.dumps({"loops": [
        {"id": "L1", "title": "reply to Ally", "status": "open", "needs_founder": True},
        {"id": "L2", "title": "not yours", "status": "open", "needs_founder": False},
        {"id": "L3", "title": "done", "status": "closed", "needs_founder": True},
    ]}))

    def boom(query, variables):
        raise RuntimeError("401 unauthorized")

    rows, error = brief.collect_owed(NOW, qroot=tmp_path, graphql=boom)
    assert error and "401" in error
    assert any("reply to Ally" in r for r in rows), "the loops half was thrown away"
    assert not any("not yours" in r for r in rows)
    assert not any("done" in r for r in rows)


def test_owed_reports_a_missing_loop_ledger_as_an_error(brief, tmp_path):
    """MISSING IS NOT EMPTY -- loops_path's own rule, inherited here."""
    rows, error = brief.collect_owed(
        NOW, qroot=tmp_path,
        graphql=lambda q, v: {"viewer": {"assignedIssues": {"nodes": []}}})
    assert error, "an unreadable loop ledger rendered as zero loops"


def test_owed_lists_linear_and_loops_together(brief, tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "open-loops.json").write_text(json.dumps({"loops": [
        {"id": "L1", "title": "reply to Ally", "status": "open", "needs_founder": True}]}))
    nodes = [{"identifier": "ASK-9", "title": "sign the SOW",
              "state": {"name": "Todo", "type": "unstarted"}}]
    rows, error = brief.collect_owed(
        NOW, qroot=tmp_path,
        graphql=lambda q, v: {"viewer": {"assignedIssues": {"nodes": nodes}}})
    assert error is None
    assert any("ASK-9" in r for r in rows)
    assert any("reply to Ally" in r for r in rows)


def test_overnight_reports_a_launchctl_outage(brief):
    def blind(label):
        return ("unknown", None)
    rows, error = brief.collect_overnight(NOW, status_fn=blind, labels=["com.kipi.x"])
    assert error, "launchctl being unreadable rendered as a healthy night"


def test_overnight_names_a_failing_job(brief):
    def status(label):
        return ("failing", 127) if label == "com.kipi.bad" else ("ok", 0)
    rows, error = brief.collect_overnight(
        NOW, status_fn=status, labels=["com.kipi.bad", "com.kipi.good"])
    assert error is None
    assert any("com.kipi.bad" in r and "127" in r for r in rows)


def test_overnight_with_no_jobs_at_all_is_an_error(brief):
    """Zero watched jobs is a broken discovery, not a quiet night."""
    rows, error = brief.collect_overnight(NOW, status_fn=lambda l: ("ok", 0), labels=[])
    assert error


# --------------------------------------------------------------------------
# Constraint 6: the deadman
# --------------------------------------------------------------------------

def test_deadman_alarms_when_no_receipt_exists(deadman, tmp_path):
    ok, reason = deadman.check(NOW, receipt_path=tmp_path / "nope.json")
    assert ok is False
    assert reason


def test_deadman_alarms_on_a_stale_receipt(deadman, tmp_path):
    receipt = tmp_path / "r.json"
    receipt.write_text(json.dumps({"date": "2026-08-29", "delivered": True}))
    ok, reason = deadman.check(NOW, receipt_path=receipt)
    assert ok is False
    assert "2026-08-29" in reason


def test_deadman_alarms_when_todays_brief_failed_to_deliver(deadman, tmp_path):
    receipt = tmp_path / "r.json"
    receipt.write_text(json.dumps({"date": NOW.strftime("%Y-%m-%d"),
                                   "delivered": False, "reason": "no webhook"}))
    ok, reason = deadman.check(NOW, receipt_path=receipt)
    assert ok is False
    assert "no webhook" in reason


def test_deadman_is_silent_on_a_delivered_brief(deadman, tmp_path):
    receipt = tmp_path / "r.json"
    receipt.write_text(json.dumps({"date": NOW.strftime("%Y-%m-%d"), "delivered": True}))
    ok, reason = deadman.check(NOW, receipt_path=receipt)
    assert ok is True
    assert reason is None


def test_deadman_alarms_on_a_corrupt_receipt(deadman, tmp_path):
    receipt = tmp_path / "r.json"
    receipt.write_text("{not json")
    ok, reason = deadman.check(NOW, receipt_path=receipt)
    assert ok is False


def test_brief_writes_a_receipt_the_deadman_can_read(brief, deadman, tmp_path):
    """The producer/consumer pair, in one test, against one file.

    A deadman keyed on a receipt nobody writes is the 09:00 alarm that never
    fires, which is the same defect one layer up.
    """
    receipt = tmp_path / "receipt.json"
    brief.write_receipt({"delivered": True}, NOW, receipt_path=receipt)
    ok, reason = deadman.check(NOW, receipt_path=receipt)
    assert ok is True, reason


# --------------------------------------------------------------------------
# Wiring: the deadman is a different job from the one it watches
# --------------------------------------------------------------------------

def test_two_plists_exist_and_are_different_jobs(brief):
    job = SCRIPTS / "com.kipi.morning-brief.plist"
    watcher = SCRIPTS / "com.kipi.morning-brief-deadman.plist"
    assert job.is_file(), f"missing {job}"
    assert watcher.is_file(), f"missing {watcher}"
    job_text = job.read_text()
    watch_text = watcher.read_text()
    assert "com.kipi.morning-brief</string>" in job_text
    assert "com.kipi.morning-brief-deadman</string>" in watch_text
    assert "morning-brief.py" in job_text
    assert "morning-brief-deadman.py" in watch_text
    # The whole point of constraint 6: the watcher must not be a step inside
    # the watched job. If one plist ran both, a dead job would take its own
    # alarm down with it.
    assert "morning-brief-deadman.py" not in job_text
    assert "/morning-brief.py" not in watch_text


def test_the_watcher_does_not_share_the_watched_job_trigger(brief):
    """A watcher on the same trigger class shares the suspect's failure mode."""
    job = (SCRIPTS / "com.kipi.morning-brief.plist").read_text()
    watcher = (SCRIPTS / "com.kipi.morning-brief-deadman.plist").read_text()
    assert "StartCalendarInterval" in job
    assert "StartInterval" in watcher, (
        "the deadman uses the same calendar trigger as the job it watches; a "
        "powered-off Mac skips both and nothing says so")


def test_plists_are_templates_not_machine_specific(brief):
    for name in ("com.kipi.morning-brief.plist", "com.kipi.morning-brief-deadman.plist"):
        text = (SCRIPTS / name).read_text()
        assert "__KIPI_REPO__" in text, f"{name} hardcodes a checkout path"
        assert "/Users/" not in text.replace("__HOME__", ""), (
            f"{name} hardcodes a home directory; install-plist.sh renders __HOME__")


def test_overnight_puts_failures_above_the_row_cap(brief):
    """The first live run buried both real failures under 26 paused jobs.

    A section capped at 15 rows whose noise sorts first is a section that
    reports nothing, however correct each individual row is.
    """
    paused = {f"com.cole.paused{i:02d}" for i in range(26)}
    labels = sorted(paused) + ["com.kipi.bad"]

    def status(label):
        return ("failing", 127) if label == "com.kipi.bad" else ("not_loaded", None)

    rows, error = brief.collect_overnight(
        NOW, status_fn=status, labels=labels, paused=paused)
    assert error is None
    assert rows[0].startswith("FAILED  com.kipi.bad")
    rendered = "\n".join(brief._section("Overnight jobs", rows, error))
    assert "com.kipi.bad" in rendered, "the failure fell below the row cap"
    assert "26 more paused on purpose" in rendered, "paused jobs vanished entirely"
