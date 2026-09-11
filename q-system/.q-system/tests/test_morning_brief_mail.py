#!/usr/bin/env python3
"""The brief's mail section reads the consulting ledger, not a model (ASK-1323).

RED FIRST: this file was written against the model-backed `collect_mail` and every
case failed there (the old collector formatted a prompt and parsed `{"threads":...}`;
these inject a ledger-shaped runner and a JSON list).

## The property this file exists for

`board_rows` archives rows inside a scope that reported healthy. So the collector's
two exits must be different things: `([], None)` is "the ledger answered and nothing
needs him" (clear the stale rows), and `([], error)` is "the ledger could not be read"
(keep the board as it is). Every failure shape below lands on the second exit.

## What this suite may NOT do

No live data path. `run_ledger` refuses under pytest and one case asserts that
refusal, so no test here can read the founder's real Notion ledger by accident.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
BRIEF_PATH = SCRIPTS / "morning-brief.py"


def _load(stem: str, filename: str):
    spec = importlib.util.spec_from_file_location(stem, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def brief():
    return _load("morning_brief_mail_under_test", "morning-brief.py")


class _FakeBoard:
    """Stands in for consulting_board: the only thing collect_mail asks of it is
    where the instance lives."""

    def __init__(self, root: Path):
        self._root = root

    def consulting_root(self) -> Path:
        return self._root


@pytest.fixture
def instance(tmp_path, monkeypatch, brief):
    """A throwaway consulting instance with a ledger script present, and the brief's
    sibling loader pointed at it. Nothing under the real home directory is read."""
    ledger = tmp_path / "q-consult" / "email-watch" / "ledger.py"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("# stand-in; the runner is injected\n", encoding="utf-8")
    log = tmp_path / "q-consult" / "output" / "mail-sweep.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("mail-sweep: stamped ok at "
                   + dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                   + "\n", encoding="utf-8")
    original = brief._optional_module

    def swapped(stem):
        bare = stem[:-3] if stem.endswith(".py") else stem
        if bare.endswith("consulting_board"):
            return _FakeBoard(tmp_path)
        return original(stem)

    monkeypatch.setattr(brief, "_optional_module", swapped)
    return tmp_path


LEDGER_ROWS = [
    {"thread_id": "19ff4af34dbc0f56", "client": "silicon-docks",
     "last_from": "john@silicondocks.vc", "subject": "Re: Intro: John + Assaf",
     "needs_reply_since": "2026-09-02T16:27:46+00:00"},
    {"thread_id": "1a01ae47d7ac6241", "client": "", "last_from": "csalgado@allpointsinv.com",
     "subject": "Re: My one pager", "needs_reply_since": ""},
]


def _runner(stdout, error=None):
    calls = []

    def run(argv, timeout):
        calls.append((list(argv), timeout))
        return stdout, error
    run.calls = calls
    return run


# ---------------------------------------------------------------------------
# the healthy exits
# ---------------------------------------------------------------------------

def test_rows_are_the_ledgers_rows_keyed_by_thread_id(brief, instance):
    rows, error = brief.collect_mail(None, runner=_runner(json.dumps(LEDGER_ROWS)))
    assert error is None
    assert [r.key for r in rows] == ["mail:19ff4af34dbc0f56", "mail:1a01ae47d7ac6241"]
    assert "silicon-docks" in rows[0] and "Re: Intro: John + Assaf" in rows[0]
    assert "[since 2026-09-02]" in rows[0]
    # no client slug: the sender is the name; no since: no bracket at all
    assert rows[1].startswith("csalgado@allpointsinv.com")
    assert "[since" not in rows[1]


def test_an_empty_ledger_answer_is_empty_and_healthy(brief, instance):
    """The exit board_rows reads as "clear the stale rows". It must be reachable."""
    rows, error = brief.collect_mail(None, runner=_runner("[]\n"))
    assert rows == []
    assert error is None


def test_the_runner_is_asked_for_needs_reply_json_on_the_instances_ledger(brief, instance):
    run = _runner("[]")
    brief.collect_mail(None, runner=run)
    (argv, timeout), = run.calls
    assert argv[0] == sys.executable
    assert argv[1] == str(instance / "q-consult" / "email-watch" / "ledger.py")
    assert argv[2:] == ["needs-reply", "--json"]
    assert timeout == brief.LEDGER_TIMEOUT_S


# ---------------------------------------------------------------------------
# every failure is an error, never a quiet empty
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stdout, error, expect", [
    (None, "ledger exit 1: NOTION_TOKEN_ASK is not set", "NOTION_TOKEN_ASK"),
    (None, "ledger timed out after 60s", "timed out"),
    ("NOTION_TOKEN_ASK is not set. Refusing to run.", None, "other than JSON"),
    ("", None, "other than JSON"),
    (json.dumps({"rows": []}), None, "not a list"),
    (json.dumps([{"client": "x", "subject": "no id"}]), None, "no thread id"),
    (json.dumps(["not a dict"]), None, "no thread id"),
])
def test_every_unreadable_shape_keeps_the_board(brief, instance, stdout, error, expect):
    rows, err = brief.collect_mail(None, runner=_runner(stdout, error))
    assert rows == []
    assert err and expect in err


def _stamp(instance, when: str) -> None:
    (instance / "q-consult" / "output" / "mail-sweep.log").write_text(
        "=== 2026-09-07T01:25:01Z mail-sweep ===\nfiled 0\n"
        f"mail-sweep: stamped ok at {when}\nmail-sweep: done\n", encoding="utf-8")


NOW = dt.datetime(2026, 9, 7, 14, 0, tzinfo=dt.timezone.utc)


def test_a_fresh_sweep_stamp_lets_an_empty_answer_be_healthy(brief, instance):
    _stamp(instance, "2026-09-07T13:31:10Z")
    rows, error = brief.collect_mail(NOW, runner=_runner("[]"))
    assert (rows, error) == ([], None)


def test_a_stale_sweep_stamp_keeps_the_board_and_never_runs_the_ledger(brief, instance):
    """PR #318 reviewer, round 2: a sweep that died leaves a readable ledger that never
    changes, and an empty answer from it would archive rows. Three hours is the line."""
    _stamp(instance, "2026-09-07T10:31:10Z")
    run = _runner("[]")
    rows, error = brief.collect_mail(NOW, runner=run)
    assert rows == []
    assert "3.5h ago" in error and "older than 3h" in error
    assert run.calls == [], "a stale ledger is not even asked"


def test_the_last_stamp_counts_and_a_failed_run_after_it_does_not_refresh(brief, instance):
    (instance / "q-consult" / "output" / "mail-sweep.log").write_text(
        "mail-sweep: stamped ok at 2026-09-07T09:31:10Z\n"
        "=== 2026-09-07T13:25:01Z mail-sweep ===\nmail-sweep: stamped failed at 2026-09-07T13:26:00Z\n",
        encoding="utf-8")
    rows, error = brief.collect_mail(NOW, runner=_runner("[]"))
    assert rows == [] and "older than 3h" in error


@pytest.mark.parametrize("log_text, expect", [
    (None, "no mail-sweep log"),
    ("=== 2026-09-07T13:25:01Z mail-sweep ===\nmail-sweep: done\n", "never stamped ok"),
    ("mail-sweep: stamped ok at yesterday\n", "not a timestamp"),
])
def test_no_witness_is_an_error_not_a_quiet_empty(brief, instance, log_text, expect):
    log = instance / "q-consult" / "output" / "mail-sweep.log"
    if log_text is None:
        log.unlink()
    else:
        log.write_text(log_text, encoding="utf-8")
    rows, error = brief.collect_mail(NOW, runner=_runner("[]"))
    assert rows == [] and expect in error


def test_the_freshness_window_matches_an_hourly_sweep(brief):
    assert brief.LEDGER_FRESH_HOURS == 3


def test_one_bad_row_fails_the_whole_read(brief, instance):
    """Half a list would archive the other half's rows inside a healthy scope."""
    payload = json.dumps([LEDGER_ROWS[0], {"subject": "no id"}])
    rows, err = brief.collect_mail(None, runner=_runner(payload))
    assert rows == [] and err


def test_a_missing_ledger_script_is_an_error_not_an_empty_section(brief, instance):
    (instance / "q-consult" / "email-watch" / "ledger.py").unlink()
    run = _runner("[]")
    rows, err = brief.collect_mail(None, runner=run)
    assert rows == []
    assert "not found" in err and "KIPI_CONSULTING_ROOT" in err
    assert run.calls == [], "nothing may run when the script is absent"


def test_no_consulting_board_sibling_is_an_error(brief, monkeypatch):
    monkeypatch.setattr(brief, "_optional_module", lambda stem: None)
    rows, err = brief.collect_mail(None, runner=_runner("[]"))
    assert rows == []
    assert "consulting_board" in err


# ---------------------------------------------------------------------------
# the chokepoint, the shell, and what must not come back
# ---------------------------------------------------------------------------

def test_the_ledger_timeout_sits_under_the_guard_budget(brief, monkeypatch):
    """Otherwise the guard abandons the mail thread while the ledger child runs on,
    and the section's error is the guard's instead of the ledger's (F3)."""
    assert brief.LEDGER_TIMEOUT_S < brief.FIXED_BUDGET_S
    monkeypatch.setenv("KIPI_BRIEF_LEDGER_TIMEOUT", "600")
    tuned = _load("morning_brief_mail_tuned", "morning-brief.py")
    assert tuned.LEDGER_TIMEOUT_S < tuned.FIXED_BUDGET_S
    assert tuned.LEDGER_TIMEOUT_S == int(tuned.FIXED_BUDGET_S) - 1


def test_run_ledger_refuses_under_pytest(brief):
    assert os.environ.get("PYTEST_CURRENT_TEST")
    stdout, err = brief.run_ledger(["python3", "anything"])
    assert stdout is None and "refused under pytest" in err


def test_run_ledger_goes_through_the_login_shell(brief, monkeypatch):
    """launchd hands the brief a bare environment; NOTION_TOKEN_ASK lives in the
    founder's shell profile. Measured 2026-09-06: bare env + zsh -l prints [],
    bare env alone prints the refusal. Same shell and flag as crm-run.sh."""
    seen = {}

    class _Proc:
        returncode = 0
        stdout = "[]"
        stderr = ""

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["timeout"] = kw.get("timeout")
        return _Proc()

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(brief.subprocess, "run", fake_run)
    stdout, err = brief.run_ledger(["/usr/bin/python3", "/x/ledger.py", "needs-reply", "--json"],
                                   timeout=7)
    assert (stdout, err) == ("[]", None)
    assert tuple(seen["cmd"][:3]) == ("/bin/zsh", "-l", "-c")
    assert seen["cmd"][3] == "exec /usr/bin/python3 /x/ledger.py needs-reply --json"
    assert seen["timeout"] == 7


def test_run_ledger_reports_a_nonzero_exit_with_its_last_line(brief, monkeypatch):
    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "Traceback\nNOTION_TOKEN_ASK is not set. Refusing to run.\n"

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(brief.subprocess, "run", lambda *a, **k: _Proc())
    stdout, err = brief.run_ledger(["x"])
    assert stdout is None
    assert err.startswith("ledger exit 1:") and "NOTION_TOKEN_ASK" in err


def test_the_model_read_is_gone_from_the_mail_section(brief):
    src = BRIEF_PATH.read_text(encoding="utf-8")
    for gone in ("MAIL_PROMPT", "MAIL_WINDOW_DAYS", "MAIL_TOOL"):
        assert gone not in src, f"{gone} came back"
    # the module docstring may keep the connector's tool names as history; the
    # SECTION may not reach for the Gmail search tool
    section = src[src.index("# Section 2"):src.index("# Section 3")]
    assert "search_threads" not in section
    assert "run_claude" not in section
    for section in getattr(brief, "SECTIONS", ()):
        if section[0] == "mail":
            assert not re.search(r"\(\d+d\)", section[1]), (
                "the label carries a day window the ledger does not have")


def test_the_brief_holds_no_ledger_import(brief):
    """The ledger is a subprocess, never an import: the consulting package has its
    own boundary test and this side keeps the same line."""
    src = BRIEF_PATH.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+.*\bledger\b", src, re.M)
    assert "sys.path" not in src
