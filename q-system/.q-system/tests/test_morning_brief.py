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
    """Every COLLECTED section, empty-and-healthy, with per-section overrides.

    `owed` and `overnight` stayed here after 2026-09-03. They stopped being FOUNDER
    sections and route to Sana instead; they did not stop being collected.
    """
    base = {k: ([], None) for k in ("calendar", "mail", "owed", "overnight")}
    base.update(overrides)
    return base


def test_every_section_can_say_failed_distinctly_from_zero(brief):
    # Read from the registry, not typed. `owed` and `overnight` left this list on
    # 2026-09-03: they no longer RENDER, so a broken one cannot look different from an
    # empty one in a message that shows neither. The property they keep is asserted
    # separately below, and it is the one that still matters for them.
    for name, _title in brief.SECTIONS:
        empty, _ = brief.build(NOW, _sources())
        broken, degraded = brief.build(NOW, _sources(**{name: ([], "boom")}))
        assert empty != broken, f"{name}: a broken section renders like an empty one"
        assert "COULD NOT READ" in broken, f"{name}: no failure marker"
        assert "boom" in broken, f"{name}: the reason is dropped"
        assert degraded, f"{name}: a broken section did not mark the run degraded"


def test_a_broken_ENGINEERING_section_still_degrades_the_run_without_rendering(brief):
    """The half of the property above that survives for a routed section.

    He never sees `Owed today` again, but a Linear outage must still mark the run
    degraded, because the deadman and the receipt read that flag. A section that stops
    being visible must not quietly stop being MONITORED, which is exactly what deleting
    the collectors would have done."""
    for name, _title in brief.ENGINEERING_SECTIONS:
        message, degraded = brief.build(NOW, _sources(**{name: ([], "boom")}))
        assert degraded, f"{name}: a broken engineering section did not degrade the run"
        assert "boom" not in message, f"{name}: engineering detail reached his brief"


def test_all_empty_is_not_degraded_and_says_nothing(brief):
    message, degraded = brief.build(NOW, _sources())
    assert not degraded
    assert "COULD NOT READ" not in message
    # Counted from the module's own SECTIONS, never typed. It was 4 until 2026-09-03,
    # when `owed` and `overnight` left the founder's brief for Sana's queue; taking the
    # number from the registry means the next section change moves it by itself.
    assert message.count("nothing") == len(brief.SECTIONS)


def test_all_founder_sections_are_present_by_name(brief):
    message, _ = brief.build(NOW, _sources())
    for _key, title in brief.SECTIONS:
        assert title in message, f"section {title} missing from the brief"


def test_the_engineering_sections_are_ABSENT_from_his_brief(brief):
    """Founder 2026-09-03: "I'm not looking for this to be a build dashboard, but a
    consulting dashboard." He found his board reporting Sana's Linear queue and the
    overnight launchd run. This is the assertion that keeps them out, and it is the
    inverse of the one above rather than a deletion of it."""
    message, _ = brief.build(NOW, _sources())
    for _key, title in brief.ENGINEERING_SECTIONS:
        assert title not in message, f"{title} is engineering and is not his to read"


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


class _FakeBoard:
    def __init__(self, root):
        self._root = root

    def consulting_root(self):
        return self._root


@pytest.fixture
def mail_instance(tmp_path, monkeypatch, brief):
    """A throwaway consulting instance for the ledger-backed mail collector
    (ASK-1323). The contract itself lives in test_morning_brief_mail.py; these
    cases only keep the section's two exits visible from the engine suite."""
    ledger = tmp_path / "q-consult" / "email-watch" / "ledger.py"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("# stand-in\n", encoding="utf-8")
    log = tmp_path / "q-consult" / "output" / "mail-sweep.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("mail-sweep: stamped ok at "
                   + dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                   + "\n", encoding="utf-8")
    original = brief._optional_module
    monkeypatch.setattr(brief, "_optional_module",
                        lambda stem: _FakeBoard(tmp_path)
                        if "consulting_board" in stem else original(stem))
    return tmp_path


def test_mail_collector_reports_a_ledger_failure(brief, mail_instance):
    rows, error = brief.collect_mail(NOW, runner=lambda argv, t: (None, "ledger timed out"))
    assert rows == []
    assert "timed out" in error


def test_mail_collector_paints_the_ledgers_rows(brief, mail_instance):
    payload = json.dumps([{"thread_id": "t1", "client": "all-points",
                           "last_from": "chris@pi.com", "subject": "SOW",
                           "needs_reply_since": "2026-08-13"}])
    rows, error = brief.collect_mail(NOW, runner=lambda argv, t: (payload, None))
    assert error is None
    assert any("all-points" in r and "SOW" in r for r in rows)


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
    # owner:assaf, because after the 2026-08-30 reshape an unlabelled issue is
    # counted in the tail rather than listed. What this case still proves is the
    # part that matters: BOTH producers reach the output in one call. The
    # tail-vs-lead routing is covered by its own cases below.
    nodes = [{"identifier": "ASK-9", "title": "sign the SOW", "dueDate": None,
              "state": {"name": "Todo", "type": "unstarted"},
              "labels": {"nodes": [{"name": "owner:assaf"}]}}]
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

def test_deadman_does_not_count_an_undelivered_alarm_as_already_alarmed(deadman, tmp_path):
    """PR #294 review, major: _already_alarmed matched on the date alone, so a
    refused 09:00 send suppressed every retry for the rest of the day."""
    state = tmp_path / "alarm.json"
    deadman._record_alarm(NOW, {"delivered": False, "reason": "HTTP 502"}, state_path=state)
    assert deadman._already_alarmed(NOW, state_path=state) is False
    deadman._record_alarm(NOW, {"delivered": True}, state_path=state)
    assert deadman._already_alarmed(NOW, state_path=state) is True


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


# --------------------------------------------------------------------------
# "Owed today", second shape. Measured 2026-08-30 before choosing it:
#   72 open issues assigned to the founder
#   50 carry owner:sana, 1 carries owner:assaf, 21 carry no owner label
#   1 has a due date at all (overdue since 2026-08-10)
# A due-date filter alone would render one row today and zero most days: a
# guard that cannot fire. A flat list renders his engineer's queue as his day.
# So the section leads with what is HIS and keeps the rest as counted tail
# lines -- visible, never hidden, never mistakable for an action.
# --------------------------------------------------------------------------

def _loops_at(tmp_path, loops):
    (tmp_path / "memory").mkdir(exist_ok=True)
    (tmp_path / "memory" / "open-loops.json").write_text(json.dumps({"loops": loops}))
    return tmp_path


def _issue(ident, title, labels=(), due=None, priority=0):
    return {"identifier": ident, "title": title, "dueDate": due, "priority": priority,
            "state": {"name": "Todo", "type": "unstarted"},
            "labels": {"nodes": [{"name": n} for n in labels]}}


def test_owed_leads_with_founder_owned_and_counts_the_rest(brief, tmp_path):
    _loops_at(tmp_path, [])
    nodes = [
        _issue("ASK-1", "sign the SOW", labels=["owner:assaf"]),
        _issue("ASK-2", "overdue thing", due="2026-08-10"),
        _issue("ASK-3", "sana engineering a", labels=["owner:sana"]),
        _issue("ASK-4", "sana engineering b", labels=["owner:sana"]),
        _issue("ASK-5", "unlabelled engineering"),
    ]
    rows, error = brief.collect_owed(
        NOW, qroot=tmp_path,
        graphql=lambda q, v: {"viewer": {"assignedIssues": {"nodes": nodes}}})
    assert error is None
    body = "\n".join(rows)
    assert "ASK-1" in body and "ASK-2" in body
    # The tail is a COUNT, not five more rows competing for the 15-row cap.
    assert "ASK-3" not in body and "ASK-4" not in body
    assert "2 " in body and "owner:sana" in body, "Sana's count vanished instead of being counted"
    assert "1 " in body, "the unlabelled remainder vanished"
    # A counted tail must not read like something to do.
    assert rows.index([r for r in rows if "ASK-1" in r][0]) < rows.index(
        [r for r in rows if "owner:sana" in r][0])


def test_owed_needs_founder_loops_are_in_the_lead_tier(brief, tmp_path):
    _loops_at(tmp_path, [
        {"id": "L1", "title": "reply to Ally", "status": "open", "needs_founder": True},
        {"id": "L2", "title": "sana's", "status": "open", "needs_founder": False},
    ])
    rows, error = brief.collect_owed(
        NOW, qroot=tmp_path,
        graphql=lambda q, v: {"viewer": {"assignedIssues": {"nodes": []}}})
    assert error is None
    assert any("reply to Ally" in r for r in rows)
    assert not any("sana's" in r for r in rows)


def test_owed_all_sana_renders_a_real_empty_lead_tier(brief, tmp_path):
    """Nothing owed by him is a legitimate answer and must not read as broken."""
    _loops_at(tmp_path, [])
    nodes = [_issue(f"ASK-{i}", "eng", labels=["owner:sana"]) for i in range(30)]
    rows, error = brief.collect_owed(
        NOW, qroot=tmp_path,
        graphql=lambda q, v: {"viewer": {"assignedIssues": {"nodes": nodes}}})
    assert error is None
    body = "\n".join(rows)
    assert "30 " in body and "owner:sana" in body
    assert "COULD NOT READ" not in body


def test_owed_still_separates_broken_from_empty_after_the_reshape(brief, tmp_path):
    """The constraint that does not move, re-asserted against the new shape."""
    _loops_at(tmp_path, [])

    def boom(q, v):
        raise RuntimeError("403 forbidden")

    rows, error = brief.collect_owed(NOW, qroot=tmp_path, graphql=boom)
    assert error and "403" in error
    empty_rows, empty_error = brief.collect_owed(
        NOW, qroot=tmp_path,
        graphql=lambda q, v: {"viewer": {"assignedIssues": {"nodes": []}}})
    assert empty_error is None
    assert brief._section("Owed today", rows, error) != brief._section(
        "Owed today", empty_rows, empty_error)


# --------------------------------------------------------------------------
# Phase 2, issue mbl-brief-core (prd-morning-brief-learns-2026-09-01, finding-2).
# Three groups, all seen RED before the code existed:
#   WITHHELD  -- the lead tier stops at three and SAYS how many it withheld,
#                split by source from provenance tags (finding-15).
#   ISOLATION -- a collector that raises costs its own section only, and the
#                exception MESSAGE never reaches the founder-facing brief
#                (finding-14: a mail/HTTP error can carry a token or a URL).
#   REGISTRY  -- optional sections register once and ride the same guard, so
#                no later issue edits this file (the single-owner rule).
# --------------------------------------------------------------------------

LEAD_FIXTURE = [
    ("ASK-1", "sign the SOW", ["owner:assaf"], None),
    ("ASK-2", "overdue thing", [], "2026-08-10"),
    ("ASK-6", "answer the auditor", ["owner:assaf"], None),
    ("ASK-7", "due yesterday", [], "2026-08-29"),
]


def _five_leads(brief, tmp_path):
    _loops_at(tmp_path, [
        {"id": "L1", "title": "reply to Ally", "status": "open", "needs_founder": True},
    ])
    nodes = [_issue(i, t, labels=l, due=d) for i, t, l, d in LEAD_FIXTURE]
    nodes.append(_issue("ASK-9", "sana eng", labels=["owner:sana"]))
    return brief.collect_owed(
        NOW, qroot=tmp_path,
        graphql=lambda q, v: {"viewer": {"assignedIssues": {"nodes": nodes}}})


def test_owed_withheld_count_is_stated_and_split_by_source(brief, tmp_path):
    rows, error = _five_leads(brief, tmp_path)
    assert error is None
    leads = [r for r in rows if r.startswith(("DUE", "ASK-", "loop "))]
    assert len(leads) == 3, f"lead tier must stop at three, got {leads}"
    withheld = [r for r in rows if r.startswith("withheld")]
    assert withheld == ["withheld 2 more: 1 in Linear, 1 in open-loops"], rows
    # The counted tail (Sana's queue) survives the reshape and stays after the
    # withheld line: a count, never a task.
    assert any("owner:sana" in r for r in rows)
    assert rows.index(withheld[0]) < rows.index(
        [r for r in rows if "owner:sana" in r][0])


def test_owed_three_or_fewer_leads_has_no_withheld_line(brief, tmp_path):
    _loops_at(tmp_path, [])
    nodes = [_issue("ASK-1", "sign the SOW", labels=["owner:assaf"])]
    rows, error = brief.collect_owed(
        NOW, qroot=tmp_path,
        graphql=lambda q, v: {"viewer": {"assignedIssues": {"nodes": nodes}}})
    assert error is None
    assert not any(r.startswith("withheld") for r in rows)


def test_owed_items_carry_provenance_tags(brief, tmp_path):
    """The split is DERIVED from tags on structured items, never guessed from
    the rendered strings (finding-15)."""
    _loops_at(tmp_path, [
        {"id": "L1", "title": "reply to Ally", "status": "open", "needs_founder": True},
    ])
    nodes = [_issue("ASK-1", "sign the SOW", labels=["owner:assaf"])]
    items, tail, errors = brief.owed_items(
        NOW, qroot=tmp_path,
        graphql=lambda q, v: {"viewer": {"assignedIssues": {"nodes": nodes}}})
    assert errors == []
    assert sorted(i["source"] for i in items) == ["linear", "loops"]
    assert all(set(i) >= {"source", "text"} for i in items)


def _all_ok(brief, monkeypatch):
    ok = lambda *a, **k: (["fine"], None)  # noqa: E731
    for name in ("collect_calendar", "collect_mail", "collect_owed", "collect_overnight"):
        monkeypatch.setattr(brief, name, ok)


def test_a_raising_collector_costs_its_own_section_only(brief, tmp_path, monkeypatch):
    log = tmp_path / "morning-brief-errors.log"

    def boom(*a, **k):
        raise RuntimeError("token=abc123 leaked")

    _all_ok(brief, monkeypatch)
    monkeypatch.setattr(brief, "collect_mail", boom)
    monkeypatch.setattr(brief, "OPTIONAL_SECTIONS", ())
    sources = brief.collect_all(NOW, log_path=log)
    message, degraded = brief.build(NOW, sources)
    assert degraded
    # One less than the founder's section count: mail is the victim here. Derived, so
    # the 2026-09-03 drop from four sections to two did not need this line rewritten by
    # hand -- and neither will the next change.
    assert message.count("fine") == len(brief.SECTIONS) - 1, (
        "the healthy sections did not render")
    assert "COULD NOT READ: mail failed (RuntimeError)" in message
    assert "abc123" not in message, "an exception message reached the brief"
    assert "abc123" in log.read_text(), "the message was not kept in the local log"


def test_a_collector_past_its_budget_is_a_timeout_not_a_hang(brief, tmp_path, monkeypatch):
    import time

    def slow(*a, **k):
        time.sleep(0.5)
        return (["late"], None)

    _all_ok(brief, monkeypatch)
    monkeypatch.setattr(brief, "collect_owed", slow)
    monkeypatch.setattr(brief, "OPTIONAL_SECTIONS", ())
    sources = brief.collect_all(NOW, log_path=tmp_path / "e.log", fixed_budget_s=0.05)
    rows, error = sources["owed"]
    assert rows == [] and "timed out" in error and "0.05" in error


def test_the_fixed_four_are_bounded_by_default_not_only_when_a_test_asks(brief, tmp_path, monkeypatch):
    """PR #294 review, major: collect_all passed None as every fixed collector's
    budget, so a hung calendar or mail call blocked delivery and the receipt
    indefinitely. The default must be finite, sit above the claude -p timeout
    (so the subprocess bound fires first), and actually cut a hung collector."""
    import inspect, threading
    assert brief.FIXED_BUDGET_S > brief.CLAUDE_TIMEOUT
    assert inspect.signature(brief.collect_all).parameters["fixed_budget_s"].default is None
    gate = threading.Event()

    def hangs(*a, **k):
        gate.wait()

    _all_ok(brief, monkeypatch)
    monkeypatch.setattr(brief, "collect_mail", hangs)
    monkeypatch.setattr(brief, "OPTIONAL_SECTIONS", ())
    monkeypatch.setattr(brief, "FIXED_BUDGET_S", 0.05)
    try:
        sources = brief.collect_all(NOW, log_path=tmp_path / "e.log")  # no fixed_budget_s: the default path
    finally:
        gate.set()
    rows, error = sources["mail"]
    assert rows == [] and "timed out" in error, (rows, error)


def test_a_hung_collector_runs_on_a_daemon_thread_so_exit_is_not_blocked(brief, tmp_path, monkeypatch):
    """Codex findings 1+2 on mbl-brief-core: a pool worker is non-daemon and is
    joined at interpreter exit, so a collector that never returns would keep the
    07:00 process alive forever. The guard must abandon it on a daemon thread."""
    import threading
    gate = threading.Event()

    def hangs(*a, **k):
        gate.wait()  # released in teardown; a real hang has no release
        return ([], None)

    _all_ok(brief, monkeypatch)
    monkeypatch.setattr(brief, "collect_mail", hangs)
    monkeypatch.setattr(brief, "OPTIONAL_SECTIONS", ())
    try:
        sources = brief.collect_all(NOW, log_path=tmp_path / "e.log", fixed_budget_s=0.05)
        assert "timed out" in sources["mail"][1]
        stuck = [t for t in threading.enumerate() if t.name == "brief-mail"]
        assert stuck, "the abandoned worker was not found"
        assert all(t.daemon for t in stuck), "a non-daemon worker would block interpreter exit"
    finally:
        gate.set()


def test_an_optional_module_that_raises_at_import_costs_its_own_section_only(brief, tmp_path, monkeypatch):
    """Codex finding-3 on mbl-brief-core: the import ran outside the guard."""
    _all_ok(brief, monkeypatch)

    def bad_import(stem):
        raise ImportError("secret=import-time-token")

    monkeypatch.setattr(brief, "OPTIONAL_SECTIONS", (("broken_mod", "broken", "Broken"),))
    monkeypatch.setattr(brief, "_optional_module", bad_import)
    sources = brief.collect_all(NOW, log_path=tmp_path / "e.log")
    message, degraded = brief.build(NOW, sources)
    assert degraded
    # Every founder section is healthy here; only the optional module broke. Derived
    # from the registry so the section set can change without this line being rewritten.
    assert message.count("fine") == len(brief.SECTIONS), (
        "the healthy sections did not render")
    assert "COULD NOT READ: broken failed (ImportError)" in message
    assert "import-time-token" not in message


def test_fixed_collectors_are_unbounded_by_default_and_optional_ones_are_not(brief, tmp_path, monkeypatch):
    """First live dry-run 2026-09-01: mail shells claude -p and needs more than
    20s. The 20s bound is for optional sections (the board), never the four."""
    import time
    _all_ok(brief, monkeypatch)

    def slow_mail(*a, **k):
        time.sleep(0.2)
        return (["slow but fine"], None)

    class SlowMod:
        @staticmethod
        def collect(now, sources):
            time.sleep(0.2)
            return (["late"], None)

    monkeypatch.setattr(brief, "collect_mail", slow_mail)
    monkeypatch.setattr(brief, "OPTIONAL_SECTIONS", (("slow_mod", "slow", "Slow"),))
    monkeypatch.setattr(brief, "_optional_module", lambda stem: SlowMod)
    sources = brief.collect_all(NOW, log_path=tmp_path / "e.log", budget_s=0.05)
    assert sources["mail"] == (["slow but fine"], None), "a fixed collector was cut off by the optional budget"
    assert "timed out" in sources["slow"][1]


def test_every_registered_section_is_guarded(brief, tmp_path, monkeypatch):
    """Enumerate SECTIONS + OPTIONAL_SECTIONS from the module (never a copy in
    the test) and prove each one is behind the guard."""

    class FakeMod:
        @staticmethod
        def collect(now, sources):
            raise RuntimeError("secret=xyz")

    monkeypatch.setattr(brief, "OPTIONAL_SECTIONS",
                        (("fake_section", "fake", "Fake section"),))
    monkeypatch.setattr(brief, "_optional_module", lambda stem: FakeMod)
    # RENDERED keys only. The guard still wraps `owed` and `overnight` (they are in
    # collect_all's fixed tuple and asserted below), but since 2026-09-03 they do not
    # reach his message, so "COULD NOT READ: owed failed" cannot be looked for there.
    keys = [k for k, _ in brief.SECTIONS] + [k for _, k, _ in brief.OPTIONAL_SECTIONS]
    engineering = {k for k, _ in brief.ENGINEERING_SECTIONS}
    for victim in engineering:
        _all_ok(brief, monkeypatch)
        def boom(*a, **k):
            raise RuntimeError("secret=xyz")
        monkeypatch.setattr(brief, f"collect_{victim}", boom)
        sources = brief.collect_all(NOW, log_path=tmp_path / "e.log")
        assert sources[victim][1] and "xyz" not in sources[victim][1], victim
        assert brief.build(NOW, sources)[1], f"{victim} broke and the run was not degraded"
    keys = [k for k in keys if k not in engineering]
    assert "fake" in keys
    for victim in keys:
        _all_ok(brief, monkeypatch)
        if victim != "fake":
            def boom(*a, **k):
                raise RuntimeError("secret=xyz")
            monkeypatch.setattr(brief, f"collect_{victim}", boom)
        sources = brief.collect_all(NOW, log_path=tmp_path / "e.log")
        message, degraded = brief.build(NOW, sources)
        assert degraded, victim
        assert f"COULD NOT READ: {victim} failed (RuntimeError)" in message, victim
        assert "xyz" not in message, victim


def test_an_absent_optional_module_renders_no_section_and_logs_once(brief, tmp_path, monkeypatch):
    _all_ok(brief, monkeypatch)
    monkeypatch.setattr(brief, "OPTIONAL_SECTIONS",
                        (("not_built_yet", "ghost", "Ghost section"),))
    monkeypatch.setattr(brief, "_optional_module", lambda stem: None)
    log = tmp_path / "e.log"
    sources = brief.collect_all(NOW, log_path=log)
    assert "ghost" not in sources, "an absent module must not produce a section"
    message, degraded = brief.build(NOW, sources)
    assert not degraded
    assert "Ghost section" not in message
    assert log.read_text().count("not_built_yet") == 1, "absent module must log exactly once"


def test_an_optional_module_returning_none_is_off_not_a_section(brief, tmp_path, monkeypatch):
    """The registry's OFF signal (amendment on mbl-board-section-bounded): a
    present module whose collect() returns None has decided it is switched off
    (the board with no page-id file). No section, no COULD NOT READ, not
    'nothing'; one log line so the absence is visible."""
    _all_ok(brief, monkeypatch)

    class Off:
        @staticmethod
        def collect(now, sources):
            return None

    monkeypatch.setattr(brief, "OPTIONAL_SECTIONS", (("notion_board", "board", "Notion board"),))
    monkeypatch.setattr(brief, "_optional_module", lambda stem: Off)
    log = tmp_path / "e.log"
    sources = brief.collect_all(NOW, log_path=log)
    assert "board" not in sources
    message, degraded = brief.build(NOW, sources)
    assert not degraded and "Notion board" not in message
    assert "board" in log.read_text() and "off" in log.read_text()


def test_a_present_optional_module_renders_after_the_fixed_sections(brief, tmp_path, monkeypatch):
    _all_ok(brief, monkeypatch)

    class Mod:
        @staticmethod
        def collect(now, sources):
            # `owed` is still COLLECTED after 2026-09-03, it just stopped being
            # rendered, so an optional module still sees it. That is the whole reason
            # the collectors were routed rather than deleted.
            assert sources["owed"] == (["fine"], None), "optional sections see every collected section"
            return (["Widgetcorp"], None)

    monkeypatch.setattr(brief, "OPTIONAL_SECTIONS",
                        (("unknown_terms", "unknown_terms", "Terms I do not know"),))
    monkeypatch.setattr(brief, "_optional_module", lambda stem: Mod)
    sources = brief.collect_all(NOW, log_path=tmp_path / "e.log")
    message, degraded = brief.build(NOW, sources)
    assert not degraded
    last_fixed = brief.SECTIONS[-1][1]
    assert message.index(last_fixed) < message.index("Terms I do not know") < message.index("Widgetcorp")


def test_the_documented_hour_is_the_one_launchd_runs():
    """Codex round 6 (minor): CLAUDE.md said 07:00 while the plist ran 07:40.

    Held by a check rather than by care, because the two live in different files and
    the only thing that had been keeping them together was somebody remembering. The
    plist is the record: it is what actually fires.
    """
    import pathlib
    import plistlib
    import re
    root = pathlib.Path(__file__).resolve().parents[3]
    plist = root / "q-system" / ".q-system" / "scripts" / "com.kipi.morning-brief.plist"
    when = plistlib.loads(plist.read_bytes())["StartCalendarInterval"]
    runs_at = "%02d:%02d" % (when["Hour"], when["Minute"])
    docs = (root / "CLAUDE.md").read_text(encoding="utf-8")
    stated = re.search(r"Runs itself at ([0-9:]+) \(`com\.kipi\.morning-brief`\)", docs)
    assert stated, "CLAUDE.md no longer states the brief's schedule at all"
    assert stated.group(1) == runs_at, (
        f"CLAUDE.md says {stated.group(1)}, launchd runs {runs_at}")


def test_no_hourly_slot_fires_before_the_card_it_mirrors():
    """Codex round 7 (major): the hourly inbox job's first slot was 07:05.

    The consulting state card is written at 07:30 by another repo's job, and the board
    MIRRORS that card: `read_heartbeat` withholds a card stamped yesterday, so a run at
    07:05 can only ever see yesterday's. Every morning it spent a headless Opus mail
    call, threw the result away, refused the board write and exited 1 into the launchd
    watchdog. Not broken. Early, by construction, forever.

    The anchor is the BRIEF's own slot rather than a 07:30 literal, because that plist
    is this repo's record of "after the card is written" and a literal here would be a
    second copy of it to drift.
    """
    import pathlib
    import plistlib
    scripts = pathlib.Path(__file__).resolve().parents[1] / "scripts"

    def minute_of_day(entry):
        return entry["Hour"] * 60 + entry["Minute"]

    brief = plistlib.loads((scripts / "com.kipi.morning-brief.plist").read_bytes())
    after_the_card = minute_of_day(brief["StartCalendarInterval"])

    hourly = plistlib.loads((scripts / "com.kipi.morning-inbox.plist").read_bytes())
    slots = hourly["StartCalendarInterval"]
    assert isinstance(slots, list) and slots, "the hourly job lost its schedule"
    early = ["%02d:%02d" % (s["Hour"], s["Minute"])
             for s in slots if minute_of_day(s) < after_the_card]
    assert not early, (
        f"slots {early} fire before the state card exists (the brief waits until "
        f"{after_the_card // 60:02d}:{after_the_card % 60:02d}); each one is a wasted "
        "model call and an exit 1 the watchdog reads as a broken hour")


def test_the_deadman_alarm_names_no_clock_time():
    """Codex round 9 (minor): the alarm said "the 07:00 job did not run" while launchd
    ran it at 07:40. That was the THIRD copy of the schedule, after CLAUDE.md and a
    comment in the plist, and it is the copy that reaches the founder.

    The fix is to carry no hour rather than to sync a third one. A number that only
    has to agree with two other places is a number that eventually will not.
    """
    import datetime as dt
    import importlib.util
    import json
    import pathlib
    import re
    import tempfile
    path = (pathlib.Path(__file__).resolve().parents[1] / "scripts"
            / "morning-brief-deadman.py")
    spec = importlib.util.spec_from_file_location("deadman", path)
    deadman = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deadman)

    # DRIVE the alarm rather than grep its source: the first cut of this test scanned
    # every double-quoted string and caught the module docstring's narrative, which
    # says nothing to the founder.
    with tempfile.TemporaryDirectory() as tmp:
        receipt = pathlib.Path(tmp) / "receipt.json"
        receipt.write_text(json.dumps({"date": "2026-09-02", "delivered": True}))
        ok, reason = deadman.check(dt.datetime(2026, 9, 3, 9, 30), receipt_path=receipt)
    assert ok is False
    assert not re.search(r"\b\d{1,2}:\d{2}\b", reason), (
        f"the alarm names a wall-clock time again: {reason!r}")


def test_inbox_only_says_OFF_rather_than_COULD_NOT_READ(brief, capsys, monkeypatch):
    """Codex round 7 (minor): a module that reported itself OFF is absent from
    `collect_hourly`, and this loop's default turned that absence into
    "COULD NOT READ: never collected".

    That is the empty-versus-broken rule inverted, in the one surface an operator
    reads, on any machine with no GroupMe token and no Notion token -- which is the
    default -- twelve times a day. A log that cries wolf twelve times a day is a log
    nobody reads on the morning it is right.
    """
    mb = brief
    monkeypatch.setattr(mb, "collect_hourly", lambda *a, **k: {"mail": ([], None)})
    rc = mb.main(["--inbox-only"])
    out = capsys.readouterr().out
    assert "COULD NOT READ" not in out, out
    assert "[groupme] off" in out and "[board_rows] off" in out, out
    assert rc == 0, "an OFF section made a healthy hour report itself broken"


def test_but_a_real_failure_still_exits_1(brief, capsys, monkeypatch):
    """The negative control. If OFF and BROKEN both print quietly, the fix has
    replaced a false alarm with a missing one."""
    mb = brief
    monkeypatch.setattr(mb, "collect_hourly",
                        lambda *a, **k: {"mail": ([], "gmail down")})
    rc = mb.main(["--inbox-only"])
    out = capsys.readouterr().out
    assert "COULD NOT READ: gmail down" in out and rc == 1


class TestNoCapUpstreamOfTheBoard:
    """claude review 2026-09-04, major. A producer-side cap on mail trimmed threads
    before `buckets()` saw them, so their board rows were archived inside a scope
    that reported healthy -- an unanswered client thread vanished off his board,
    pin and all.

    Round 11 fixed this class inside the painter (`capped`: a cap is a write budget,
    not a statement that the work is finished). A second cap upstream of the producer
    routed around that rule. Display is capped by `_section`; data is not capped."""

    def test_every_thread_the_ledger_returns_reaches_the_caller(self, brief, mail_instance):
        n = 40
        payload = json.dumps([
            {"thread_id": f"t{i}", "last_from": f"p{i}@x.com", "subject": f"s{i}"}
            for i in range(n)])
        rows, error = brief.collect_mail(None, lambda argv, t: (payload, None))
        assert error is None
        assert len(rows) == n, (
            f"the producer dropped {n - len(rows)} threads; their board rows would be "
            "archived inside a healthy scope")
        assert len({r.key for r in rows}) == n

    def test_no_synthetic_overflow_row_is_minted(self, brief, mail_instance):
        """An overflow row needs a stable id and a scope. Inventing one puts a row on
        the board that no thread corresponds to."""
        payload = json.dumps([
            {"thread_id": f"t{i}", "last_from": "p@x.com", "subject": "s"}
            for i in range(30)])
        rows, _ = brief.collect_mail(None, lambda argv, t: (payload, None))
        assert not any("more unanswered" in str(r) for r in rows)
        assert all(getattr(r, "key", "").startswith("mail:t") for r in rows)

    def test_the_SECTION_still_caps_what_he_reads(self, brief):
        """The Slack message stays short. That was the cap's only legitimate job."""
        rows = [brief.Row(f"line {i}", f"mail:t{i}") for i in range(40)]
        out = brief._section("Mail", rows, None)
        assert len(out) == brief.MAX_ROWS + 2, out[:3]
        assert "and 25 more" in out[-1]
