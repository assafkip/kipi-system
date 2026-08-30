#!/usr/bin/env python3
"""Pins linear-triage-health.py and the needs-triage marking in alert-to-linear.py.

The numbers asserted below are LITERAL, never recomputed from the same helper the
code uses. A baseline captured by calling `measure()` twice cannot see a change
that moves both sides, which is how a mutant survives a green suite in this repo.

Every fixture here is shaped like a real Linear GraphQL node (the keys the actual
OPEN_ISSUES_QUERY selects), not like a convenient dict. A fixture I invent tests
my assumption; this one at least tests the query's own shape.
"""
import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
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
              labels=["needs-triage"]),                        # ROUTED, stale label
        issue("ASK-5", project="kipi-system", days_old=200,
              labels=["dormant"]),                             # already flagged
        issue("ASK-6", days_old=200, labels=["needs-triage"]), # real inflow, skipped
    ]
    found = health.find_dormant(issues, NOW, 75)
    # ASK-4 was asserted as "inflow, skipped" until round 2 of the PR #204
    # review. That was this suite pinning the defect: the issue is ROUTED, so it
    # is not inflow at all -- nothing removes the label when a human routes an
    # issue. It counted as neither awaiting-triage nor dormant, at any age.
    # ASK-6 is the genuine inflow case that exclusion was reaching for, and it
    # is still skipped. Oldest first, so ASK-4 (200d) precedes ASK-1 (100d).
    assert [i["identifier"] for i, _ in found] == ["ASK-4", "ASK-1"]


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


# --- PR #204 Codex review: the four majors, each with its reproducer ---------

def test_a_routed_ticket_is_no_longer_awaiting_triage():
    """FINDING 1. The filer sets projectId and needs-triage in ONE payload.

    Nothing anywhere removes the label when a human routes the issue, so a
    label-only count reported every routed alert ticket as untriaged forever --
    a permanently growing number, printed by the script whose job is spotting a
    permanently growing number. Reproduced on the PR head: needs_triage=1 for
    the routed ticket below.

    Both directions are pinned. Dropping the `is_unrouted` half turns the first
    assert red; dropping the label half turns the third one red.
    """
    routed = issue("ASK-1", project="kipi-system",
                   labels=["owner:sana", "needs-triage"])
    unrouted_marked = issue("ASK-2", labels=["owner:sana", "needs-triage"])
    routed_unmarked = issue("ASK-3", project="kipi-system", labels=["owner:sana"])

    assert health.measure([routed], NOW)["needs_triage"] == 0
    assert health.measure([unrouted_marked], NOW)["needs_triage"] == 1
    assert health.measure([routed_unmarked], NOW)["needs_triage"] == 0
    # and the predicate itself, so a caller added later reads one definition
    assert health.is_awaiting_triage(routed) is False
    assert health.is_awaiting_triage(unrouted_marked) is True


class CommentLinear:
    """A Linear that answers commentCreate with whatever `success` it was given.

    Modelled on the real reply shape: COMMENT_CREATE selects `success`, and
    Linear returns HTTP 200 with success=false rather than raising.
    """

    def __init__(self, success):
        self.success = success
        self.bodies = []

    def graphql(self, query, variables):
        if "comments(first" in query:
            return {"issue": {"comments": {"nodes": []}}}
        if "commentCreate" in query:
            self.bodies.append(variables["input"]["body"])
            return {"commentCreate": {"success": self.success}}
        raise AssertionError(f"unexpected query: {query[:60]}")


def test_a_refused_comment_is_not_reported_as_flagged():
    """FINDING 2. success=false came back through a clean call and read as written.

    The run then counted it in `flagged=N`. A monitoring script that overstates
    its own writes is the exact failure it exists to catch, one layer up.
    Reproduced on the PR head: flag_dormant returned 'flagged'.
    """
    ln = CommentLinear(success=False)
    out = health.flag_dormant(ln, {"id": "uuid-1", "identifier": "ASK-1"}, 120.0, 75)

    assert out != "flagged"
    assert out.startswith("FAILED")
    # the call really was attempted -- this is a refused write, not a skipped one
    assert len(ln.bodies) == 1


def test_an_accepted_comment_is_still_reported_as_flagged():
    """The positive control for the test above.

    Without it, `return "FAILED"` unconditionally would pass the success=false
    case and the suite would be green on a script that can never flag anything.
    """
    ln = CommentLinear(success=True)
    out = health.flag_dormant(ln, {"id": "uuid-1", "identifier": "ASK-1"}, 120.0, 75)
    assert out == "flagged"
    assert health.DORMANT_MARKER in ln.bodies[0]


def test_a_conflicted_label_create_recovers_the_existing_id():
    """FINDING 4 (alert-to-linear.py). Losing the create race is not having no label.

    Two filers read the team before either created `needs-triage`; the loser's
    create fails BECAUSE the label now exists, and the old code dropped the name
    and filed the ticket unmarked -- invisible to the health script, silently.
    Reproduced on the PR head: ids came back as ['id-owner:sana'].
    """

    class Conflict:
        def __init__(self):
            self.label_queries = 0

        def graphql(self, query, variables):
            if "labels(first" in query:
                self.label_queries += 1
                # the rival process wins between the first read and the refetch
                names = (["owner:sana"] if self.label_queries == 1
                         else ["owner:sana", "needs-triage"])
                return {"team": {"labels": {"nodes": [
                    {"id": f"id-{n}", "name": n} for n in names]}}}
            if "issueLabelCreate" in query:
                raise RuntimeError('[{"message":"Entity with that name already exists"}]')
            raise AssertionError(f"unexpected query: {query[:60]}")

    ln = Conflict()
    ids = alerts._label_ids(ln, "team", [alerts.OWNER_LABEL, alerts.TRIAGE_LABEL])

    assert ids == ["id-owner:sana", "id-needs-triage"]
    assert ln.label_queries == 2, "the recovery must actually re-read the team"


def test_a_create_that_fails_for_another_reason_still_finds_nothing():
    """The negative control for the recovery above.

    The refetch must not invent an id. A create refused for permissions leaves
    the label genuinely absent, so this run comes away with only the label it
    really resolved -- the same posture the pre-existing failed-create test
    pins, kept honest now that a second lookup happens.
    """
    ln = FakeLinear(existing=["owner:sana"], fail_create_for=["needs-triage"])
    ids = alerts._label_ids(ln, "team", [alerts.OWNER_LABEL, alerts.TRIAGE_LABEL])
    assert ids == ["id-owner:sana"]


# --- FINDING 3: the alert result has to reach the exit code ------------------
#
# main() refuses under pytest on purpose, and that chokepoint is worth more than
# this test is. So this drives a COPY of the script in a subprocess with the
# guard's env var cleared, beside a fake linear-sync.py and a fake
# slack-notify.sh. Nothing here can reach the real board: the copy resolves its
# neighbours from its OWN directory, which is a tmp_path. Clearing the var on
# the real module in-process would disarm the guard for every test after it.

FAKE_LINEAR_SYNC = '''
TEAM_QUERY = "query teams"


def linear_api_key():
    return "fake-key-never-sent-anywhere"


def graphql(query, variables):
    if "issues(filter" in query:
        nodes = [{
            "id": f"u{n}", "identifier": f"ASK-{n}", "title": f"work {n}",
            "createdAt": "2026-08-16T00:00:00Z",
            "updatedAt": "2026-08-16T00:00:00Z",
            "state": {"name": "Backlog", "type": "backlog"},
            "project": None,
            "labels": {"nodes": []},
        } for n in range(60)]
        return {"issues": {"nodes": nodes, "pageInfo": {"hasNextPage": False}}}
    return {"teams": {"nodes": [{"id": "team-1", "key": "ASK"}]}}
'''

FAKE_NOTIFY = '#!/usr/bin/env bash\nexit "${FAKE_NOTIFY_EXIT:-0}"\n'


def _stage_health_copy(tmp_path, fake_sync=FAKE_LINEAR_SYNC):
    """Lay a runnable copy of the script beside fake neighbours. Returns its path.

    The copy resolves `linear-sync.py` and `slack-notify.sh` from its OWN
    directory, so staging them here is what makes the run unable to reach the
    real board. It is also what keeps the --apply lock scoped to this tmp_path
    rather than to the installed script.
    """
    shutil.copy(os.path.join(SCRIPTS, "linear-triage-health.py"),
                tmp_path / "linear-triage-health.py")
    (tmp_path / "linear-sync.py").write_text(fake_sync)
    notify = tmp_path / "slack-notify.sh"
    notify.write_text(FAKE_NOTIFY)
    notify.chmod(0o755)
    return tmp_path / "linear-triage-health.py"


# The suite's --apply lock, pinned OUT of the real one.
#
# Until round 5 the lock was keyed on the script's own directory, so a staged
# copy in a tmpdir could not reach the installed job's lock. That isolation was
# a side effect of the key, and the key was the round-5 blocker: two checkouts
# on one machine never contended and both wrote a permanent comment. With the
# key moved to the Linear team, a staged copy resolves to the SAME path as the
# real launchd sweep, so a test that forgot to pin it would contend with the
# real job. Isolation is therefore explicit and defaulted here rather than
# per-test: forgetting it is not an available mistake.
_SUITE_LOCK_DIR = tempfile.mkdtemp(prefix="kipi-triage-health-suite-")


def _health_env(**extra):
    env = dict(os.environ)
    env.pop("PYTEST_CURRENT_TEST", None)
    env.setdefault("KIPI_TRIAGE_HEALTH_LOCK",
                   os.path.join(_SUITE_LOCK_DIR, "apply.lock"))
    env.update({k: str(v) for k, v in extra.items()})
    return env


def _run_health_copy(tmp_path, notify_exit, *, fake_sync=FAKE_LINEAR_SYNC, args=()):
    """Run a copy of the script whose alert path exits `notify_exit`."""
    script = _stage_health_copy(tmp_path, fake_sync)
    return subprocess.run([sys.executable, str(script)] + list(args),
                          capture_output=True, text=True,
                          env=_health_env(FAKE_NOTIFY_EXIT=notify_exit),
                          timeout=120)


def test_a_failed_alert_exits_nonzero(tmp_path):
    """FINDING 3. `alerted (exit 1)` printed, then `return EXIT_OK`.

    launchd reads the exit code, not stdout, so a 3am run whose alert never
    reached anyone was recorded as a clean success -- a breach measured, printed
    into a log nobody opens, and reported as fine. Reproduced on the PR head:
    main() returned 0 after notify failed.

    The fixture breaches UNROUTED_ALERT_AT (60 unrouted against a 50 threshold),
    so the alert is genuinely owed rather than skipped.
    """
    res = _run_health_copy(tmp_path, notify_exit=1)
    assert res.returncode == health.EXIT_ALERT_FAILED, res.stdout + res.stderr
    assert "alert FAILED" in res.stdout
    # the measurement itself is still printed: the numbers are good, the send failed
    assert "unrouted (no project) : 60" in res.stdout


def test_a_delivered_alert_still_exits_zero(tmp_path):
    """The negative control. Same breach, same code path, a working alert path.

    Without it, `return EXIT_ALERT_FAILED` unconditionally would satisfy the test
    above while making every successful run look like a failure -- which on a
    launchd job is the same bug wearing the other sign.
    """
    res = _run_health_copy(tmp_path, notify_exit=0)
    assert res.returncode == health.EXIT_OK, res.stdout + res.stderr
    assert "alert FAILED" not in res.stdout
    assert "alerted (exit 0)" in res.stdout


# --- PR #204 Codex review ROUND 2: five findings, each with its reproducer ---

def test_a_routed_issue_with_a_stale_triage_label_can_go_dormant():
    """ROUND 2 FINDING 1. The issue that fell into NEITHER bucket.

    `is_awaiting_triage()` was narrowed to "label AND unrouted" (round 1), but
    `find_dormant()` kept excluding on the label alone. A routed issue still
    carrying a stale `needs-triage` label was therefore not awaiting triage (it
    has a project) and not dormancy-eligible (it has the label) -- invisible to
    both readings of the same page, at any age. Reproduced on the PR head: a
    100-day-old routed issue gave awaiting_triage=False, dormant_matches=0.

    Asserted literally, never against a baseline recomputed from the same
    helper: a baseline captured from this code cannot see a change moving both
    sides.
    """
    routed_stale = issue("ASK-1", project="kipi-system",
                         labels=["owner:sana", "needs-triage"], days_old=100)

    found = health.find_dormant([routed_stale], NOW, 75)
    assert len(found) == 1, "the routed issue with a stale label must be eligible"
    assert found[0][0]["identifier"] == "ASK-1"
    # and it really is absent from the other bucket, so this is the only one
    assert health.measure([routed_stale], NOW)["needs_triage"] == 0


def test_dormancy_still_skips_real_inflow_and_the_human_override():
    """The negative control for the test above.

    Deleting the exclusion entirely would satisfy that test while flagging the
    unrouted inflow queue -- putting dormancy comments on exactly the noise this
    system exists to stop filing. Both survivors are pinned here.
    """
    unrouted_marked = issue("ASK-2", labels=["owner:sana", "needs-triage"],
                            days_old=100)
    routed_overridden = issue("ASK-3", project="kipi-system",
                              labels=["dormant"], days_old=100)

    # still-unrouted inflow is counted as triage depth, never as stalled work
    assert health.find_dormant([unrouted_marked], NOW, 75) == []
    assert health.measure([unrouted_marked], NOW)["needs_triage"] == 1
    # a human who disagrees applies the label by hand; the sweep honours it
    assert health.find_dormant([routed_overridden], NOW, 75) == []


class BrokenReadLinear:
    """A Linear whose comments READ raises and whose commentCreate succeeds.

    Both halves matter: the mutation must be able to succeed, so a test that
    sees no write is seeing a refusal to write rather than a broken fixture.
    """

    def __init__(self):
        self.mutations = 0

    def graphql(self, query, variables):
        if "comments(first" in query:
            raise RuntimeError("Linear timeout reading comments")
        if "commentCreate" in query:
            self.mutations += 1
            return {"commentCreate": {"success": True}}
        raise AssertionError(f"unexpected query: {query[:60]}")


def test_a_failed_flag_check_is_not_reported_as_already_flagged():
    """ROUND 2 FINDING 3. An unknown state reported as work someone else did.

    `already_flagged()` returned True on ANY exception, so a Linear timeout
    reached the operator as `already-flagged` -- a sentence about a comment that
    exists, produced by a run that learned nothing and wrote nothing. The run
    then looked complete. Reproduced on the PR head: outcome 'already-flagged',
    zero mutations attempted.
    """
    ln = BrokenReadLinear()
    out = health.flag_dormant(ln, {"id": "uuid-1", "identifier": "ASK-1"}, 120.0, 75)

    assert out != "already-flagged"
    assert out.startswith("FAILED")
    # unknown is not "no": it must not have gambled a write
    assert ln.mutations == 0


def test_a_genuine_already_flagged_issue_is_still_skipped():
    """The negative control. Returning FAILED on every read would pass the above.

    A real marker present must still produce `already-flagged` and no write, or
    the nightly sweep grows a comment stack on every dormant issue.
    """

    class Flagged:
        def __init__(self):
            self.mutations = 0

        def graphql(self, query, variables):
            if "comments(first" in query:
                return {"issue": {"comments": {"nodes": [
                    {"body": f"{health.DORMANT_MARKER}\nolder flag"}]}}}
            self.mutations += 1
            return {"commentCreate": {"success": True}}

    ln = Flagged()
    out = health.flag_dormant(ln, {"id": "uuid-1", "identifier": "ASK-1"}, 120.0, 75)
    assert out == "already-flagged"
    assert ln.mutations == 0


def test_already_flagged_raises_rather_than_answering_on_a_broken_read():
    """The predicate itself, so a caller added later cannot inherit the old bug.

    A bool return type has no room for "I could not find out", and both of its
    values are wrong answers. The distinct exception is what makes the unknown
    impossible to consume by accident.
    """
    with pytest.raises(health.FlagCheckFailed):
        health.already_flagged(BrokenReadLinear(), "uuid-1")


# --- ROUND 4 FINDINGS 1+2: the READ is the flag-once guarantee ---------------
#
# One cause, two symptoms. The lock was keyed on the installed copy's directory,
# so two installs never contended; and the idempotency check only read the first
# 100 comments, so it had a permanent blind spot anyway. These pin the fix at the
# level it was made: a complete read, not a bigger lock.


class PaginatedIssue:
    """A Linear issue that serves its comments in pages and honours `after`.

    Shaped like the real `comments(first: 100, after: $after)` connection --
    `nodes` plus a `pageInfo` -- because the defect being pinned is precisely
    that the old query never asked for the second page. A stub that returns all
    comments in one bag cannot fail for the reason we care about, and every
    pre-existing stub in this file is exactly that bag.

    The cursor is a stringified offset. Linear's is opaque, but the only
    property the code under test may rely on is that it round-trips, and an
    offset makes an off-by-one visible in the assertion instead of hiding it.
    """

    PAGE = 100

    def __init__(self, comments=None):
        self.comments = list(comments or [])
        self.writes = 0
        self.pages_served = 0

    def graphql(self, query, variables):
        if "comments(" in query:
            start = int(variables.get("after") or 0)
            chunk = self.comments[start:start + self.PAGE]
            end = start + len(chunk)
            self.pages_served += 1
            return {"issue": {"comments": {
                "nodes": chunk,
                "pageInfo": {"hasNextPage": end < len(self.comments),
                             "endCursor": str(end)},
            }}}
        self.writes += 1
        self.comments.append({"body": variables["input"]["body"]})
        return {"commentCreate": {"success": True}}


def _filler(n):
    return [{"body": f"unrelated comment {i}"} for i in range(n)]


def test_a_marker_past_the_first_page_is_still_found():
    """The finding-2 reproducer, with a stub that actually paginates.

    Measured on the PR head with this same stub: 1 page fetched, result
    `flagged`, 1 duplicate mutation. A dormancy comment is permanent and there
    is no undo, so a second one on an already-flagged issue costs trust in
    every flag the sweep has ever written.
    """
    ln = PaginatedIssue(_filler(100) + [{"body": health.DORMANT_MARKER}])
    out = health.flag_dormant(ln, {"id": "uuid-1", "identifier": "ASK-1"}, 120.0, 75)
    assert out == "already-flagged"
    assert ln.writes == 0
    # Pins the mechanism, not just the outcome: 2 proves it asked for the page
    # the old code never asked for. Without this the test would still pass if a
    # future edit widened `first:` to 200 and re-created the blind spot at 201.
    assert ln.pages_served == 2


def test_two_installs_on_one_machine_share_one_lock():
    """ROUND 5 BLOCKER. This test used to ASSERT the defect.

    Its previous line was `assert path_a != path_b, "premise of the finding"`,
    which pinned two install directories to two lock paths and called that
    settled because "a filesystem lock cannot represent a shared Linear team".
    A filesystem lock cannot span HOSTS; it represents one machine perfectly
    well, and two checkouts on one machine is the realistic collision for this
    fleet -- a worktree plus the installed copy. Keying on the team instead of
    on `HERE` closes it, so the assertion inverts.
    """
    original_here = health.HERE
    try:
        health.HERE = "/opt/kipi-a/scripts"
        path_a = health.apply_lock_path()
        health.HERE = "/opt/kipi-b/scripts"
        path_b = health.apply_lock_path()
    finally:
        health.HERE = original_here
    assert path_a == path_b, "two installs on one machine must contend"


class MarkedIssue:
    """One issue carrying one dormancy marker posted at `marker_at`."""

    def __init__(self, marker_at):
        self.marker_at = marker_at
        self.writes = 0

    def graphql(self, query, variables):
        if "comments(" in query:
            node = {"body": health.DORMANT_MARKER}
            if self.marker_at is not None:
                node["createdAt"] = self.marker_at
            return {"issue": {"comments": {
                "nodes": [node],
                "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
        self.writes += 1
        return {"commentCreate": {"success": True}}


def test_a_revived_issue_that_goes_quiet_again_is_flagged_again():
    """ROUND 5 BLOCKER. The marker was a permanent silencer.

    `dormancy_comment()` prints "still wanted -> comment or update it and this
    clears". Nothing implemented that: `already_flagged()` found the marker
    forever, so an issue that was flagged, revived by a human, and then went
    quiet a SECOND time could never be flagged again. A monitor that goes
    permanently silent on exactly the issues it once identified is worse than
    one that never ran.

    Timeline: marker 2026-01-15, human touches it 2026-03-01, now 2026-06-01.
    """
    issue = {"id": "u1", "identifier": "ASK-1", "title": "real work",
             "updatedAt": "2026-03-01T00:00:00.000Z", "state": {"type": "backlog"},
             "project": {"id": "p1"}, "labels": {"nodes": []}}
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    dormant = health.find_dormant([issue], now, 75)
    assert dormant, "precondition: the revived issue is dormant again"

    ln = MarkedIssue("2026-01-15T00:00:00.000Z")
    assert health.flag_dormant(ln, *dormant[0], 75) == "flagged"
    assert ln.writes == 1


def test_an_issue_untouched_since_its_marker_is_not_flagged_twice():
    """The negative control, and without it the fix above is a comment stack.

    Same marker, same sweep, one field different: nothing touched the issue
    after the flag. It must stay silent. A version of the fix that always
    re-flags passes the test above and fails here.
    """
    issue = {"id": "u1", "identifier": "ASK-1", "title": "real work",
             "updatedAt": "2026-01-10T00:00:00.000Z", "state": {"type": "backlog"},
             "project": {"id": "p1"}, "labels": {"nodes": []}}
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    dormant = health.find_dormant([issue], now, 75)

    ln = MarkedIssue("2026-01-15T00:00:00.000Z")
    assert health.flag_dormant(ln, *dormant[0], 75) == "already-flagged"
    assert ln.writes == 0


def test_the_bots_own_comment_does_not_supersede_its_own_marker():
    """Linear bumps updatedAt on comment creation. Measured, not assumed.

    Sampled 2026-08-17 across 14 ASK issues: in 7 the issue's `updatedAt` equals
    the newest comment's own `updatedAt` to the exact millisecond, and Linear
    stamps a comment's `updatedAt` 15-200ms BEFORE its `createdAt`. So the
    dormancy comment lands with the issue's clock fractionally EARLIER than the
    marker and cannot invalidate itself on the very next sweep.
    """
    marker_at = "2026-01-15T00:00:00.100Z"
    bumped_to = "2026-01-15T00:00:00.083Z"   # the comment's updatedAt, 17ms earlier
    assert not health.marker_superseded(marker_at, bumped_to)


def test_a_marker_with_no_readable_timestamp_still_silences():
    """Unknown is not "go ahead and comment again".

    A comment is permanent and has no undo, so an unusable timestamp errs toward
    silence -- the same posture FlagCheckFailed already takes for a read that
    did not finish.
    """
    for stamp in (None, "", "not-a-date"):
        ln = MarkedIssue(stamp)
        assert health.already_flagged(ln, "u1", "2026-06-01T00:00:00.000Z") is True


def test_the_newest_marker_decides_not_the_first_one_found():
    """An issue flagged twice must be judged on its LATEST flag.

    Returning on the first marker found was correct while the only question was
    "is there a marker". Compared against a clock it inverts: the stale first
    marker reads as superseded and the sweep re-flags an issue that already
    holds a current flag.
    """
    class TwoMarkers:
        writes = 0

        def graphql(self, query, variables):
            if "comments(" in query:
                return {"issue": {"comments": {"nodes": [
                    {"body": health.DORMANT_MARKER,
                     "createdAt": "2026-01-15T00:00:00.000Z"},
                    {"body": health.DORMANT_MARKER,
                     "createdAt": "2026-05-01T00:00:00.000Z"}],
                    "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
            TwoMarkers.writes += 1
            return {"commentCreate": {"success": True}}

    # touched between the two markers: stale by the first, current by the second
    assert health.already_flagged(
        TwoMarkers(), "u1", "2026-03-01T00:00:00.000Z") is True
    assert TwoMarkers.writes == 0


def test_the_marker_read_still_stops_a_duplicate_without_any_lock():
    """The lock is an optimisation; the marker read is the guarantee.

    Kept from the round-4 test this replaces, because it covers what a lock
    never can: two sweeps that do NOT share a filesystem. The filler pushes the
    marker onto page 2, so this also fails on the round-3 head for the
    pagination reason.
    """
    shared = PaginatedIssue(_filler(100))
    issue_node = {"id": "uuid-1", "identifier": "ASK-1"}
    first = health.flag_dormant(shared, issue_node, 120.0, 75)
    second = health.flag_dormant(shared, issue_node, 120.0, 75)
    assert first == "flagged"
    assert second == "already-flagged"
    assert shared.writes == 1


def test_an_unfinishable_comment_walk_is_a_failure_not_a_missing_marker():
    """A stalled cursor must never be answered as "no marker".

    This is the round-2 lesson (an unknown is not a skip) applied to a SECOND
    way of not finishing. Returning False here would write a duplicate onto an
    issue whose marker simply had not been reached yet, which is the original
    defect wearing a different hat.
    """

    class StalledCursor:
        def __init__(self):
            self.writes = 0

        def graphql(self, query, variables):
            if "comments(" in query:
                return {"issue": {"comments": {
                    "nodes": _filler(100),
                    "pageInfo": {"hasNextPage": True, "endCursor": None},
                }}}
            self.writes += 1
            return {"commentCreate": {"success": True}}

    ln = StalledCursor()
    with pytest.raises(health.FlagCheckFailed):
        health.already_flagged(ln, "uuid-1")
    # flag_dormant turns that into a reported FAILURE that reaches the exit
    # code, and writes nothing.
    out = health.flag_dormant(ln, {"id": "uuid-1", "identifier": "ASK-1"}, 120.0, 75)
    assert out.startswith("FAILED")
    assert ln.writes == 0


def test_a_never_ending_cursor_hits_the_cap_and_still_refuses_to_write():
    """The runaway stop is a cap on the LOOP, never a bound on the SEARCH.

    A cap that returned False would be a blind spot at page 51 instead of page
    2 -- the same defect, moved. So it raises, and the caller reports a failure.
    """

    class EndlessPages:
        def __init__(self):
            self.writes = 0
            self.pages_served = 0

        def graphql(self, query, variables):
            if "comments(" in query:
                self.pages_served += 1
                cursor = int(variables.get("after") or 0) + 100
                return {"issue": {"comments": {
                    "nodes": _filler(100),
                    "pageInfo": {"hasNextPage": True, "endCursor": str(cursor)},
                }}}
            self.writes += 1
            return {"commentCreate": {"success": True}}

    ln = EndlessPages()
    with pytest.raises(health.FlagCheckFailed):
        health.already_flagged(ln, "uuid-1")
    assert ln.pages_served == health.COMMENT_PAGE_CAP
    assert ln.writes == 0


def test_a_single_page_issue_with_no_marker_is_still_flagged_normally():
    """The negative control for all of the above.

    Every test in this block asserts something is NOT written. If the paginated
    walk had a bug that made it raise or return True on ordinary input, they
    would all still pass while the sweep silently stopped flagging anything.
    """
    ln = PaginatedIssue(_filler(3))
    out = health.flag_dormant(ln, {"id": "uuid-1", "identifier": "ASK-1"}, 120.0, 75)
    assert out == "flagged"
    assert ln.writes == 1
    assert ln.pages_served == 1


# --- ROUND 4 FINDING 3: a dropped label must be observable -------------------


def _alert_linear(label_create):
    """A Linear double for the alert filer. `label_create` decides that mutation."""

    class L:
        def __init__(self):
            self.created = None
            self.labels = [{"id": "owner-id", "name": "owner:sana"}]

        def linear_api_key(self):
            return "k"

        def graphql(self, q, v):
            if "teams(filter" in q:
                return {"teams": {"nodes": [{"id": "t"}]}}
            if "labels(first" in q:
                return {"team": {"labels": {"nodes": list(self.labels)}}}
            if "issueLabelCreate" in q:
                return label_create(self)
            if "projects(first" in q:
                return {"team": {"projects": {"nodes": []}}}
            if "issueCreate" in q:
                self.created = v["input"]
                return {"issueCreate": {"issue": {"id": "u9",
                                                  "identifier": "ASK-9"}}}
            return {}

    return L()


def _file_one_alert(monkeypatch, ln):
    """Run file_alert against `ln` with state IO stubbed out.

    State is stubbed rather than pointed at a tmp file because this asserts on
    the returned line and on stderr, not on persistence, and a test that touches
    the real state path is what the fable-discipline lint exists to stop.
    """
    monkeypatch.setattr(alerts, "_load_linear", lambda: ln)
    monkeypatch.setattr(alerts, "_read_state", lambda fp: {})
    monkeypatch.setattr(alerts, "_write_state", lambda *a: None)
    return alerts.file_alert("[kipi-system] detector fired", now=1)


def test_a_real_label_failure_is_loud_and_marks_the_file_degraded(monkeypatch, capsys):
    """A permission error looked exactly like success on the PR head.

    Measured there: `(0, 'filed ASK-9')` with `needs-triage` absent. The alert
    still has to be filed -- a dropped alert is worse than an unlabelled one,
    which is this file's standing posture -- but `needs-triage` is the field the
    whole ASK-882 queue measurement reads, so losing it silently makes the
    depth quietly wrong instead of loudly broken.
    """

    def denied(_self):
        raise RuntimeError("permission denied")

    ln = _alert_linear(denied)
    code, line = _file_one_alert(monkeypatch, ln)

    assert code == alerts.EXIT_OK, "the alert must still be filed"
    assert ln.created is not None, "the ticket is created regardless"
    assert alerts.TRIAGE_LABEL not in ln.created.get("labelIds", [])
    # The two visibility surfaces, asserted separately. An `or` across them
    # would pass on whichever half happened to work.
    assert "DEGRADED" in line and alerts.TRIAGE_LABEL in line
    assert "permission denied" in capsys.readouterr().err


def test_a_lost_create_race_stays_quiet_and_undegraded(monkeypatch, capsys):
    """The negative control: the loud path must not fire on the benign one.

    Two filers racing means the loser's create fails because the label now
    EXISTS. That is already handled by the refetch, costs nothing, and must not
    produce a warning -- a warning on every race would train the operator to
    ignore the one that matters.
    """

    def already_exists(self):
        self.labels.append({"id": "triage-id", "name": alerts.TRIAGE_LABEL})
        raise RuntimeError("label already exists")

    ln = _alert_linear(already_exists)
    code, line = _file_one_alert(monkeypatch, ln)

    assert code == alerts.EXIT_OK
    assert "triage-id" in ln.created.get("labelIds", [])
    assert "DEGRADED" not in line
    assert "WARNING" not in capsys.readouterr().err


# --- ROUND 2 FINDING 2: a refused write has to reach the exit code ----------

FAKE_SYNC_ROUTED_DORMANT = '''
import os
TEAM_QUERY = "query teams"
SUCCESS = os.environ.get("FAKE_COMMENT_SUCCESS", "1") == "1"


def linear_api_key():
    return "fake-key-never-sent-anywhere"


def graphql(query, variables):
    if "issues(filter" in query:
        nodes = [{
            "id": f"u{n}", "identifier": f"ASK-{n}", "title": f"work {n}",
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
            "state": {"name": "Backlog", "type": "backlog"},
            "project": {"id": "p-1", "name": "kipi-system"},
            "labels": {"nodes": []},
        } for n in range(3)]
        return {"issues": {"nodes": nodes, "pageInfo": {"hasNextPage": False}}}
    if "comments(first" in query:
        return {"issue": {"comments": {"nodes": []}}}
    if "commentCreate" in query:
        return {"commentCreate": {"success": SUCCESS}}
    return {"teams": {"nodes": [{"id": "team-1", "key": "ASK"}]}}
'''


def _run_apply(tmp_path, comment_success):
    script = _stage_health_copy(tmp_path, FAKE_SYNC_ROUTED_DORMANT)
    return subprocess.run(
        [sys.executable, str(script), "--apply", "--no-notify",
         "--dormant-days", "30"],
        capture_output=True, text=True, timeout=120,
        env=_health_env(FAKE_COMMENT_SUCCESS=1 if comment_success else 0))


def test_an_apply_run_whose_writes_were_all_refused_exits_nonzero(tmp_path):
    """ROUND 2 FINDING 2. flag_dormant said FAILED; main() returned 0 anyway.

    Round 1 stopped `flag_dormant()` reporting a declined mutation as "flagged".
    main() then discarded that per-issue answer when choosing its exit code, so
    a run where EVERY commentCreate came back success=false still returned 0 --
    launchd recorded a clean nightly sweep that wrote nothing. The same shape as
    the alert bug beside it, one layer down. Reproduced on the PR head:
    failed=3, RETURN_CODE 0.
    """
    res = _run_apply(tmp_path, comment_success=False)
    assert res.returncode == health.EXIT_WRITE_FAILED, res.stdout + res.stderr
    assert "failed=3" in res.stdout
    assert "WRITE FAILED" in res.stderr


def test_an_apply_run_whose_writes_landed_exits_zero(tmp_path):
    """The negative control. `return EXIT_WRITE_FAILED` unconditionally would
    satisfy the test above while making every successful sweep look broken --
    on a launchd job, the same defect wearing the other sign.
    """
    res = _run_apply(tmp_path, comment_success=True)
    assert res.returncode == health.EXIT_OK, res.stdout + res.stderr
    assert "flagged=3" in res.stdout
    assert "WRITE FAILED" not in res.stderr


# --- ROUND 2 FINDING 4: check-then-write needs one lock ---------------------

FAKE_SYNC_RACY = '''
import os, time
TEAM_QUERY = "query teams"
LEDGER = os.environ["FAKE_WRITE_LEDGER"]


def linear_api_key():
    return "fake-key-never-sent-anywhere"


def graphql(query, variables):
    if "issues(filter" in query:
        return {"issues": {"nodes": [{
            "id": "u1", "identifier": "ASK-1", "title": "routed work",
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
            "state": {"name": "Backlog", "type": "backlog"},
            "project": {"id": "p-1", "name": "kipi-system"},
            "labels": {"nodes": []},
        }], "pageInfo": {"hasNextPage": False}}}
    if "comments(first" in query:
        try:
            with open(LEDGER) as fh:
                n = len([l for l in fh if l.strip()])
        except OSError:
            n = 0
        # Widen the check-to-write window so an unlocked build loses the race
        # deterministically rather than on timing luck.
        time.sleep(1.0)
        return {"issue": {"comments": {"nodes": [
            {"body": "<!-- kipi-dormancy-flag -->"} for _ in range(n)]}}}
    if "commentCreate" in query:
        with open(LEDGER, "a") as fh:
            fh.write("wrote\\n")
        return {"commentCreate": {"success": True}}
    return {"teams": {"nodes": [{"id": "team-1", "key": "ASK"}]}}
'''


def _apply_procs(tmp_path, count):
    """Launch `count` --apply runs of one staged copy inside the same window."""
    script = _stage_health_copy(tmp_path, FAKE_SYNC_RACY)
    ledger = tmp_path / "writes.log"
    env = _health_env(FAKE_WRITE_LEDGER=str(ledger))
    cmd = [sys.executable, str(script), "--apply", "--no-notify",
           "--dormant-days", "30"]
    procs = [subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
             for _ in range(count)]
    for proc in procs:
        proc.communicate(timeout=180)
    writes = len([l for l in ledger.read_text().splitlines() if l.strip()]) \
        if ledger.exists() else 0
    return writes, sorted(p.returncode for p in procs)


def test_two_concurrent_apply_runs_comment_once(tmp_path):
    """ROUND 2 FINDING 4. Nothing linked the check to the write.

    `already_flagged()` reads, `flag_dormant()` writes, and two concurrent
    --apply runs (the launchd sweep and a founder's manual run) both read "no
    marker" and both wrote. A comment is permanent and there is no undo, and a
    duplicated flag costs trust in every flag. Reproduced on the PR head: 2
    comment mutations on one issue.

    The loser refuses rather than queueing: this runs daily against a 75-day
    threshold, so a skipped sweep costs nothing while a launchd job silently
    waiting on an interactive run looks hung.
    """
    writes, codes = _apply_procs(tmp_path, 2)
    assert writes == 1, f"one issue took {writes} dormancy comments"
    assert codes == [health.EXIT_OK, health.EXIT_LOCKED], codes


def test_two_separate_installs_on_one_machine_comment_once(tmp_path):
    """ROUND 5 BLOCKER, end to end, and the reason the in-process check is thin.

    The reviewer's reproducer varied only `HERE` and then called `flag_dormant`
    directly. `flag_dormant` sits BELOW the lock -- `main()` takes the lock once
    per sweep, `_run` refuses without it -- so calling it directly can never
    observe a lock no matter how it is keyed, and its "2 writes" result was a
    property of the entry point chosen, not of the lock. This runs the real
    entry point from two genuinely different install directories, which is the
    shape the finding describes: a worktree and the installed copy on one
    machine.

    On the round-4 head the two directories hashed to two lock paths, both runs
    won, and one issue took two permanent dormancy comments.

    NOT COVERED, and deliberately so: two different HOSTS. No filesystem lock
    spans machines and `commentCreate` has no idempotency key, so that remains
    documented rather than fixed. There is no way to write that test here.
    """
    install_a = tmp_path / "kipi-a" / "scripts"
    install_b = tmp_path / "kipi-b" / "scripts"
    ledger = tmp_path / "writes.log"
    procs = []
    for install in (install_a, install_b):
        install.mkdir(parents=True)
        script = _stage_health_copy(install, FAKE_SYNC_RACY)
        env = _health_env(FAKE_WRITE_LEDGER=str(ledger),
                          KIPI_TRIAGE_HEALTH_LOCK=str(tmp_path / "shared.lock"))
        procs.append(subprocess.Popen(
            [sys.executable, str(script), "--apply", "--no-notify",
             "--dormant-days", "30"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
    for proc in procs:
        proc.communicate(timeout=180)

    writes = len([l for l in ledger.read_text().splitlines() if l.strip()]) \
        if ledger.exists() else 0
    assert writes == 1, f"two installs left {writes} dormancy comments on one issue"
    assert sorted(p.returncode for p in procs) == \
        [health.EXIT_OK, health.EXIT_LOCKED]


def test_two_installs_resolve_to_one_lock_without_the_override(tmp_path):
    """The negative control for the test above, and it is load-bearing.

    That test pins the shared lock path explicitly, so it would still pass if
    `apply_lock_path()` went back to keying on `HERE` -- the override would be
    doing all the work and the fix could be reverted invisibly. This asserts the
    DEFAULT, unpinned path is the same from two install directories, which is
    the property the override hides.
    """
    original_here = health.HERE
    try:
        health.HERE = str(tmp_path / "kipi-a" / "scripts")
        default_a = health.apply_lock_path()
        health.HERE = str(tmp_path / "kipi-b" / "scripts")
        default_b = health.apply_lock_path()
    finally:
        health.HERE = original_here
    assert default_a == default_b
    assert str(tmp_path) not in default_a, "the lock must not live in the install"


def test_a_single_apply_run_still_writes(tmp_path):
    """The negative control, and it is load-bearing here.

    A lock that never grants would make the test above pass with ZERO writes,
    turning the nightly sweep into a no-op that reports success. This pins that
    the uncontended path still comments.
    """
    writes, codes = _apply_procs(tmp_path, 1)
    assert writes == 1
    assert codes == [health.EXIT_OK]


def test_report_only_runs_take_no_lock(tmp_path):
    """A run that mutates nothing must not serialise against anything.

    Two report-only runs are harmless, so making them queue would be a cost with
    no buyer -- and would make an interactive check fail while the nightly sweep
    holds the lock.
    """
    script = _stage_health_copy(tmp_path, FAKE_SYNC_RACY)
    env = _health_env(FAKE_WRITE_LEDGER=str(tmp_path / "writes.log"))
    cmd = [sys.executable, str(script), "--no-notify", "--dormant-days", "30"]
    procs = [subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) for _ in range(2)]
    for proc in procs:
        proc.communicate(timeout=180)
    assert [p.returncode for p in procs] == [health.EXIT_OK, health.EXIT_OK]
    assert not (tmp_path / "writes.log").exists(), "report-only wrote to Linear"


def test_the_apply_lock_is_scoped_to_the_team_not_the_install_path(tmp_path):
    """Every sweep of one team on one machine resolves to ONE path.

    The inverse of what this file asserted through round 4. The lock key is the
    Linear team being swept, so where the running copy sits is irrelevant --
    which is the whole point, because "where the copy sits" was the accident
    that let two checkouts both comment.
    """
    mine = health.apply_lock_path()
    assert mine.endswith(".lock")
    # not inside the repo: `kipi update` rsyncs this tree and would ship it
    assert not mine.startswith(SCRIPTS)
    assert health.TEAM_KEY in mine, "the team is the key"

    # moving the install path must NOT move the lock
    original_here = health.HERE
    try:
        health.HERE = "/somewhere/else/entirely"
        assert health.apply_lock_path() == mine
    finally:
        health.HERE = original_here

    # a team key that could climb out of the directory is collapsed to a hash
    original_team = health.TEAM_KEY
    try:
        health.TEAM_KEY = "../../etc"
        escaped = health.apply_lock_path()
    finally:
        health.TEAM_KEY = original_team
    assert ".." not in escaped
    assert os.path.dirname(escaped) == os.path.dirname(mine)

    # the override wins, so a caller can pin it explicitly
    os.environ["KIPI_TRIAGE_HEALTH_LOCK"] = str(tmp_path / "pinned.lock")
    try:
        assert health.apply_lock_path() == str(tmp_path / "pinned.lock")
    finally:
        os.environ.pop("KIPI_TRIAGE_HEALTH_LOCK", None)
    assert health.apply_lock_path() == mine


def test_the_write_path_refuses_without_the_lock():
    """Fail closed. `_run` is reachable by a future caller that forgot the lock.

    The guard exists because the alternative is a second write path with no
    chokepoint, which is the defect this finding already cost once.
    """
    args = argparse.Namespace(apply=True, dormant_days=75, no_notify=True,
                              json=False, limit=0)
    with pytest.raises(RuntimeError, match="without the --apply lock"):
        health._run(args, holding_lock=False)


# --- ROUND 2 FINDING 5: the promise has to match the mutations --------------

def test_the_module_promises_only_the_mutation_it_makes():
    """ROUND 2 FINDING 5. The header sold "a comment and a label"; no label
    mutation existed anywhere in the file.

    Pinned against the PROMISE literal rather than the words, because the
    corrected docstring QUOTES the old promise in order to explain it -- a text
    check its own documentation satisfies is broken in the direction that never
    passes. This also fails if someone adds a label write without saying so.
    """
    src = open(os.path.join(SCRIPTS, "linear-triage-health.py")).read()
    writes_label = "issueUpdate" in src or "labelIds" in src

    assert "gets ONE comment and a label" not in src, "the old promise is back"
    assert not writes_label, "a label mutation appeared; update the header"
    assert "gets ONE COMMENT" in src
    # the label is still READ, and that asymmetry is deliberate, not a leftover
    assert health.DORMANT_LABEL in src
