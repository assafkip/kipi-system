#!/usr/bin/env python3
"""Pins linear-triage-health.py and the needs-triage marking in alert-to-linear.py.

The numbers asserted below are LITERAL, never recomputed from the same helper the
code uses. A baseline captured by calling `measure()` twice cannot see a change
that moves both sides, which is how a mutant survives a green suite in this repo.

Every fixture here is shaped like a real Linear GraphQL node (the keys the actual
OPEN_ISSUES_QUERY selects), not like a convenient dict. A fixture I invent tests
my assumption; this one at least tests the query's own shape.
"""
import importlib.util
import os
from datetime import datetime, timedelta, timezone

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")

NOW = datetime(2026, 8, 16, 12, 0, 0, tzinfo=timezone.utc)


def _load(filename: str, modname: str):
    path = os.path.join(SCRIPTS, filename)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


health = _load("linear-triage-health.py", "linear_triage_health")
alerts = _load("alert-to-linear.py", "alert_to_linear_for_labels")


def issue(ident, *, project=None, labels=(), days_old=0, state="Backlog",
          state_type="backlog", title=None):
    """One issue node in the shape OPEN_ISSUES_QUERY actually returns."""
    stamp = (NOW - timedelta(days=days_old)).isoformat().replace("+00:00", "Z")
    return {
        "id": f"uuid-{ident}",
        "identifier": ident,
        "title": title or f"{ident} some work",
        "createdAt": stamp,
        "updatedAt": stamp,
        "state": {"name": state, "type": state_type},
        "project": {"id": f"p-{project}", "name": project} if project else None,
        "labels": {"nodes": [{"name": n} for n in labels]},
    }


# --- the three numbers -------------------------------------------------------

def test_unrouted_counts_only_issues_with_no_project():
    """The 229. An unset project is what makes an issue unreachable."""
    issues = [
        issue("ASK-1"),                       # unrouted
        issue("ASK-2"),                       # unrouted
        issue("ASK-3", project="kipi-system"),
        issue("ASK-4", project="cole-gtm"),
    ]
    m = health.measure(issues, NOW)
    assert m["unrouted"] == 2
    assert m["open"] == 4


def test_needs_triage_counted_and_oldest_reported():
    """A count alone hides the shape, so the oldest is part of the measurement."""
    issues = [
        issue("ASK-1", labels=["needs-triage", "owner:sana"], days_old=3),
        issue("ASK-2", labels=["needs-triage"], days_old=41),
        issue("ASK-3", labels=["owner:sana"], days_old=99),   # not triage
    ]
    m = health.measure(issues, NOW)
    assert m["needs_triage"] == 2
    assert m["oldest_triage_id"] == "ASK-2"
    assert m["oldest_triage_days"] == pytest.approx(41.0, abs=0.1)


def test_label_matching_is_case_insensitive():
    """Linear preserves the case a label was created with; the count must not care."""
    m = health.measure([issue("ASK-1", labels=["Needs-Triage"])], NOW)
    assert m["needs_triage"] == 1


# --- the self-exclusion ------------------------------------------------------

def test_self_tickets_are_excluded():
    """slack-notify.sh files a ticket, so this script's alert lands on its own board.

    Without the exclusion a backlog monitor inflates the backlog it reports and
    then alerts about the number it caused. This is the negative self-test for
    that: the self ticket is unrouted, so if the filter breaks, unrouted goes to 2.
    """
    self_title = f"[kipi-system] {health.SELF_MARKER} 229 unrouted (no project)"
    issues = [issue("ASK-1"), issue("ASK-2", title=self_title)]

    assert health.is_self_ticket(issues[1]) is True
    assert health.is_self_ticket(issues[0]) is False

    kept = [i for i in issues if not health.is_self_ticket(i)]
    assert health.measure(kept, NOW)["unrouted"] == 1


# --- open vs closed ----------------------------------------------------------

def test_duplicate_state_is_not_open():
    """This team carries a Duplicate state. Counting it as open keeps dead issues forever."""
    assert health.is_open(issue("ASK-1")) is True
    assert health.is_open(issue("ASK-2", state="Done", state_type="completed")) is False
    assert health.is_open(issue("ASK-3", state="Canceled", state_type="canceled")) is False
    assert health.is_open(issue("ASK-4", state="Duplicate", state_type="duplicate")) is False


def test_open_is_read_from_type_not_name():
    """Names are renameable per-team strings; types are Linear's closed set."""
    renamed = issue("ASK-1", state="Shipped", state_type="completed")
    assert health.is_open(renamed) is False


# --- dormancy ----------------------------------------------------------------

def test_dormant_finds_only_routed_quiet_work():
    issues = [
        issue("ASK-1", project="kipi-system", days_old=100),   # dormant
        issue("ASK-2", project="kipi-system", days_old=10),    # recent
        issue("ASK-3", days_old=200),                          # unrouted, skipped
        issue("ASK-4", project="kipi-system", days_old=200,
              labels=["needs-triage"]),                        # inflow, skipped
        issue("ASK-5", project="kipi-system", days_old=200,
              labels=["dormant"]),                             # already flagged
    ]
    found = health.find_dormant(issues, NOW, 75)
    assert [i["identifier"] for i, _ in found] == ["ASK-1"]


def test_dormant_threshold_boundary_is_inclusive_and_configurable():
    """Exactly at the threshold counts; one day under does not."""
    at = [issue("ASK-1", project="p", days_old=75)]
    under = [issue("ASK-2", project="p", days_old=74)]
    assert len(health.find_dormant(at, NOW, 75)) == 1
    assert len(health.find_dormant(under, NOW, 75)) == 0
    # configurable, and the 90 case is the one a 75-day default would over-report
    assert len(health.find_dormant(at, NOW, 90)) == 0


def test_dormant_sorted_oldest_first():
    issues = [
        issue("ASK-1", project="p", days_old=80),
        issue("ASK-2", project="p", days_old=300),
        issue("ASK-3", project="p", days_old=120),
    ]
    found = health.find_dormant(issues, NOW, 75)
    assert [i["identifier"] for i, _ in found] == ["ASK-2", "ASK-3", "ASK-1"]


def test_dormancy_comment_flags_and_never_closes():
    """GitHub's stale-bot warning: a bot that silently closes teaches people the tracker lies."""
    body = health.dormancy_comment(120.0, 75)
    assert health.DORMANT_MARKER in body
    assert "120 days" in body
    low = body.lower()
    assert "nothing was closed" in low
    # the comment must not claim an automatic close is coming
    assert "will be closed" not in low
    assert "auto-clos" not in low


# --- alerting posture --------------------------------------------------------

def test_quiet_below_every_threshold():
    """'Still fine' every day is how a channel stops being read."""
    m = {"unrouted": 3, "needs_triage": 2, "oldest_triage_days": 1.0,
         "oldest_triage_id": "ASK-1"}
    assert health.breaches(m) == []


def test_each_threshold_can_fire_on_its_own():
    base = {"unrouted": 0, "needs_triage": 0, "oldest_triage_days": 0.0,
            "oldest_triage_id": ""}

    only_unrouted = dict(base, unrouted=health.UNROUTED_ALERT_AT)
    only_triage = dict(base, needs_triage=health.TRIAGE_ALERT_AT)
    only_old = dict(base, oldest_triage_days=float(health.OLDEST_ALERT_DAYS),
                    oldest_triage_id="ASK-9")

    assert len(health.breaches(only_unrouted)) == 1
    assert len(health.breaches(only_triage)) == 1
    assert len(health.breaches(only_old)) == 1
    # and one under each boundary stays silent, so the >= is pinned in both directions
    assert health.breaches(dict(base, unrouted=health.UNROUTED_ALERT_AT - 1)) == []
    assert health.breaches(dict(base, needs_triage=health.TRIAGE_ALERT_AT - 1)) == []


def test_dormancy_default_can_actually_fire_on_this_board():
    """A threshold the population can never reach reads as protection and is not.

    The board was created 2026-07-25. A 90-day default could not fire until late
    October; 75 is inside the researched 60-90 band and reachable.
    """
    assert health.DEFAULT_DORMANT_DAYS == 75
    assert 60 <= health.DEFAULT_DORMANT_DAYS <= 90


# --- the fixture guard -------------------------------------------------------

def test_main_refuses_under_pytest():
    """A suite must never be able to comment on a real issue.

    This asserts the chokepoint, not a per-test stub: per-test stubbing only
    protects tests someone remembered to fix (ASK-879 is the open issue for the
    non-pytest runners this does NOT cover).
    """
    assert os.environ.get("PYTEST_CURRENT_TEST")
    assert health.main(["linear-triage-health.py"]) == health.EXIT_REFUSED_FIXTURE


# --- the filer marking (alert-to-linear.py) ----------------------------------

class FakeLinear:
    """Records the mutations it was asked to run. No network, no live path."""

    def __init__(self, existing=(), fail_create_for=()):
        self.existing = list(existing)
        self.fail_create_for = set(fail_create_for)
        self.created = []

    def graphql(self, query, variables):
        if "labels(first" in query:
            return {"team": {"labels": {"nodes": [
                {"id": f"id-{n}", "name": n} for n in self.existing]}}}
        if "issueLabelCreate" in query:
            name = variables["input"]["name"]
            if name in self.fail_create_for:
                raise RuntimeError(f"refused to create {name}")
            self.created.append(variables["input"])
            return {"issueLabelCreate": {"success": True,
                                         "issueLabel": {"id": f"new-{name}"}}}
        raise AssertionError(f"unexpected query: {query[:60]}")


def test_both_labels_resolved_when_both_exist():
    ln = FakeLinear(existing=["owner:sana", "needs-triage", "Bug"])
    ids = alerts._label_ids(ln, "team", [alerts.OWNER_LABEL, alerts.TRIAGE_LABEL])
    assert ids == ["id-owner:sana", "id-needs-triage"]
    assert ln.created == []


def test_missing_triage_label_is_created_with_its_description():
    """The label explains itself on the board, or nobody knows what it means."""
    ln = FakeLinear(existing=["owner:sana"])
    ids = alerts._label_ids(ln, "team", [alerts.OWNER_LABEL, alerts.TRIAGE_LABEL])
    assert ids == ["id-owner:sana", "new-needs-triage"]
    assert len(ln.created) == 1
    assert ln.created[0]["name"] == "needs-triage"
    assert ln.created[0]["description"] == alerts.TRIAGE_LABEL_DESCRIPTION


def test_a_failed_create_keeps_the_label_that_did_resolve():
    """Losing the mark is a worse board; losing the ticket is a lost alert.

    Negative self-test for the per-name try: with one try around the whole loop,
    this returns [] and the ticket files with no owner label at all.
    """
    ln = FakeLinear(existing=["owner:sana"], fail_create_for=["needs-triage"])
    ids = alerts._label_ids(ln, "team", [alerts.OWNER_LABEL, alerts.TRIAGE_LABEL])
    assert ids == ["id-owner:sana"]


def test_label_lookup_failure_never_raises():
    """An alert filed with no label still reaches Sana; a raised exception loses it."""

    class Broken:
        def graphql(self, query, variables):
            raise RuntimeError("linear is down")

    assert alerts._label_ids(Broken(), "team", [alerts.OWNER_LABEL]) == []


def test_triage_label_constant_matches_what_health_measures():
    """Two files, one vocabulary. A rename in one is the drift this pins.

    The filer WRITES the label and the health script COUNTS it. If those strings
    ever diverge the queue reads as permanently empty, which looks exactly like a
    drain that is keeping pace.
    """
    assert alerts.TRIAGE_LABEL == health.TRIAGE_LABEL == "needs-triage"


def test_no_limit_makes_every_dormant_issue_writable():
    """A run with no --limit writes to ALL dormant issues, not the first 20.

    This is the regression pin for a shipped defect, so the fixture is 25 items
    on purpose: the write and the print used to share one loop over
    `dormant[:20]`, so --apply flagged 20 and silently skipped the rest while
    printing "... and N more". Measured on the live board 2026-08-16: 193 dormant
    at a 7-day threshold, 173 of which would never have been written to. Any
    reintroduced display bound turns this red.
    """
    dormant = [(issue(f"ASK-{n}", project="p"), 30.0) for n in range(25)]
    assert len(health.select_to_flag(dormant, 0)) == 25


def test_limit_caps_the_write_and_keeps_the_oldest_first():
    """--limit bounds blast radius, and bounds it from the oldest end.

    find_dormant sorts oldest-first, so a capped run must spend its budget on
    the issues that have been quiet longest rather than an arbitrary slice.
    """
    dormant = [(issue(f"ASK-{n}", project="p"), float(50 - n)) for n in range(10)]
    picked = health.select_to_flag(dormant, 3)
    assert [i["identifier"] for i, _ in picked] == ["ASK-0", "ASK-1", "ASK-2"]


def test_negative_limit_is_refused_rather_than_silently_emptying():
    """A negative slice would return [] and read as "nothing was dormant".

    Refusing is the point: a silent empty write set is indistinguishable from a
    clean board, which is the one wrong conclusion this script exists to prevent.
    """
    with pytest.raises(ValueError):
        health.select_to_flag([(issue("ASK-1", project="p"), 30.0)], -1)
