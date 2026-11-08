#!/usr/bin/env python3
"""Reproducer for ASK-1887: a DoR ticket nothing routes is a ticket nothing picks up.

RED BEFORE GREEN. Written against `linear-route.py` before that file existed, so
the first run is an ImportError and the second is the behaviour.

WHAT THIS PINS, and what it deliberately does not. Every case here is the PURE
half: selection, path extraction, the routing rules, the write cap. The network
half (board walk, issueUpdate, commentCreate) is not exercised, because a suite
that can reach live Linear is the 2026-08-01 scar where 14/14 green paged the
founder twice. `linear-route.py` carries the same PYTEST_CURRENT_TEST chokepoint
its siblings do, and `test_refuses_under_pytest` is the case that proves the
chokepoint is real rather than documented.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys

import pytest

# LIVES IN tests/, NOT BESIDE THE SCRIPT IT PINS. verify.sh's pytest runner walks
# q-system/.q-system/tests and never q-system/.q-system/scripts, so a suite placed
# next to its subject is green because nothing runs it -- the shape this repo calls
# an inert engine. `SCRIPTS` is the one path indirection that buys.
HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    # REGISTERED BEFORE EXEC, not after. `@dataclasses.dataclass` resolves
    # annotations through `sys.modules[cls.__module__]`, so a module loaded by
    # path and never registered raises AttributeError on its first dataclass.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


route = _load("linear_route", "linear-route.py")


DOR = """## Definition of Ready

* **Outcome:** something true.
* **Files:** `{files}`
* **Check:** run it.
* **Blast radius:** small.
* **Not doing:** anything else.
"""


def issue(ident="ASK-1", *, files="q-system/.q-system/scripts/x.py", labels=(),
          project=None, state="backlog", body=None, comments=(), truncated=False):
    desc = body if body is not None else DOR.format(files=files)
    return {
        "id": f"uuid-{ident}",
        "identifier": ident,
        "title": f"title {ident}",
        "description": desc,
        "state": {"name": "Backlog", "type": state},
        "project": {"name": project} if project else None,
        "labels": {"nodes": [{"name": n} for n in labels]},
        "comments": {"nodes": [{"body": b} for b in comments],
                     "pageInfo": {"hasNextPage": truncated}},
    }


class FakeSync:
    """One graphql() that returns whatever the test queued, and records the calls."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def graphql(self, query, variables):
        self.calls.append((query, variables))
        return self.results.pop(0)


@pytest.fixture()
def board(tmp_path):
    """A registry and a matching on-disk tree, so the rules have something to read.

    The directories are REAL because R1 and R3 both ask the filesystem. A fixture
    that only described the tree would let a rule that never touches disk pass.
    """
    skel = tmp_path / "kipi-system"
    (skel / "q-system" / ".q-system" / "scripts").mkdir(parents=True)
    (skel / "q-system" / ".q-system" / "scripts" / "x.py").write_text("#\n")
    (skel / "q-system" / "my-project").mkdir(parents=True)
    (skel / "q-system" / "my-project" / "icp.md").write_text("#\n")
    (skel / "plugins").mkdir()
    (skel / "plugins" / "p.md").write_text("#\n")

    consulting = tmp_path / "consulting"
    (consulting / "q-consult" / "canonical").mkdir(parents=True)
    (consulting / "q-consult" / "canonical" / "crm.md").write_text("#\n")

    gtm = tmp_path / "cole-gtm"
    (gtm / "projects").mkdir(parents=True)
    (gtm / "projects" / "site.md").write_text("#\n")

    reg = tmp_path / "instance-registry.json"
    reg.write_text(json.dumps({
        "skeleton": {"path": str(skel), "linear_project": "kipi-system"},
        "instances": [
            {"name": "ASK_AI_consultant", "linear_project": "ASK Consulting",
             "path": str(consulting), "instance_q_dir": "q-consult"},
            {"name": "cole-gtm", "linear_project": "cole-GTM", "path": str(gtm),
             "instance_q_dir": None},
        ],
    }))
    # The updater is parsed, not retyped: the routing rule that calls a path
    # instance-owned reads THIS list, so the fixture must supply one.
    updater = tmp_path / "kipi-update.sh"
    updater.write_text(
        "#!/bin/bash\n"
        "INSTANCE_OWNED_SUBTREES=(\n  my-project\n  canonical\n  memory\n  output\n)\n"
    )
    return route.RoutingFacts.load(str(reg), str(updater))


# --------------------------------------------------------------------------
# selection: which issues are in the population at all
# --------------------------------------------------------------------------

def test_dor_with_no_project_is_pending(board):
    assert route.is_pending(issue("ASK-1", labels=["owner:sana"]))


def test_dor_with_no_owner_label_is_pending(board):
    assert route.is_pending(issue("ASK-2", project="kipi-system"))


def test_fully_routed_issue_is_not_pending(board):
    assert not route.is_pending(
        issue("ASK-3", labels=["owner:sana"], project="kipi-system"))


def test_no_dor_with_a_project_is_not_pending(board):
    assert not route.is_pending(issue("ASK-4", body="just prose, no readiness", project="kipi-system"))


def test_no_dor_and_no_project_is_pending(board):
    """ASK-3959: 351 open no-project tickets, 13 with a DoR. Without a project the
    drafter skips it and the alert lane refuses it, so the router must take it."""
    assert route.is_pending(issue("ASK-4", body="just prose, no readiness"))


def test_founder_owned_is_not_pending(board):
    assert not route.is_pending(issue("ASK-5", labels=["owner:assaf"]))


@pytest.mark.parametrize("held", ["needs-scope", "blocked:capability"])
def test_held_is_not_pending(board, held):
    assert not route.is_pending(issue("ASK-6", labels=["owner:sana", held]))


def test_closed_state_is_not_pending(board):
    assert not route.is_pending(issue("ASK-7", labels=["owner:sana"], state="completed"))


def test_fleet_alert_with_a_project_is_not_pending(board):
    body = ("<!-- kipi-alert-fingerprint: abc123 -->\n\n"
            + DOR.format(files="q-system/.q-system/scripts/x.py"))
    assert not route.is_pending(issue("ASK-8", body=body, project="kipi-system"))


def test_fleet_alert_with_no_project_routes_on_its_title_only(board):
    """ASK-3959: the lane refuses an alert with no project. Its body is a raw
    alert line that can name any repo's files, so only the filer's own label counts."""
    body = "<!-- kipi-alert-fingerprint: abc123 -->\n\nsomething broke in `q-consult/x.py`"
    it = issue("ASK-8", body=body)
    assert route.is_pending(it)
    assert route.evidence_decision(it, board).project is None      # paths ignored, no title label
    it["title"] = "[kipi-system] worker: something broke"
    assert route.evidence_decision(it, board).project == board.skeleton_project


def test_no_dor_routes_on_an_instance_q_dir_path(board):
    """R2 in free text: an instance's own q-dir prefix names its repo."""
    it = issue("ASK-9", body="the lane drops `q-consult/canonical/crm.md` again")
    rows = route.plan_actions([it], board)
    proj = next(p for p, r in board.rows_by_project.items() if r.get("q_dir") == "q-consult")
    assert rows and rows[0]["set_project"] == proj


def test_no_dor_never_routes_on_a_skeleton_managed_path(board):
    """PR #675 review, major: R3 in free text is too weak. A kipi-update-shipped
    path exists in every instance, so it says nothing about the ticket's repo."""
    it = issue("ASK-9", body="the reaper misses `q-system/.q-system/scripts/x.py` again")
    d = route.evidence_decision(it, board)
    assert d.project is None and "cannot route on" in d.reason and "the text" in d.reason


def test_no_dor_title_and_paths_that_disagree_refuse(board):
    it = issue("ASK-10", body="see `q-consult/canonical/crm.md`")
    q_proj = next(p for p, r in board.rows_by_project.items() if r.get("q_dir") == "q-consult")
    it["title"] = "[nosuchlabel] thing"
    assert route.evidence_decision(it, board).project == q_proj      # an unknown label adds nothing
    it["title"] = f"[{board.skeleton_project}] thing"
    assert route.evidence_decision(it, board).project is None        # the label and the path disagree


def test_no_dor_unrouted_gets_no_route_unknown_comment(board):
    """A comment nobody reads is not a consumer; the no-DoR class gets none."""
    rows = route.plan_actions([issue("ASK-11", body="no paths, no label")], board)
    assert rows and not rows[0]["set_project"] and not rows[0]["mark_unroutable"]


# --------------------------------------------------------------------------
# path extraction out of the DoR
# --------------------------------------------------------------------------

def test_files_line_yields_backticked_paths():
    body = DOR.format(files="a/b.py` and `c/d.py")
    assert route.dor_file_paths(body) == ["a/b.py", "c/d.py"]


def test_extraction_stops_at_the_next_dor_field():
    body = ("## Definition of Ready\n\n"
            "* **Files:** `q-system/a.py`\n"
            "* **Check:** `q-system/b.py` is NOT a file to touch\n")
    assert route.dor_file_paths(body) == ["q-system/a.py"]


def test_non_path_backticks_are_ignored():
    body = DOR.format(files="ready()` and `q-system/a.py")
    assert route.dor_file_paths(body) == ["q-system/a.py"]


def test_no_files_field_yields_nothing():
    assert route.dor_file_paths("## Definition of Ready\n\n* **Outcome:** x\n") == []


# --------------------------------------------------------------------------
# the routing rules
# --------------------------------------------------------------------------

def test_r1_absolute_path_under_a_row(board):
    path = os.path.join(board.rows_by_project["ASK Consulting"]["path"],
                        "q-consult", "canonical", "crm.md")
    decision = route.route_paths([path], board)
    assert decision.project == "ASK Consulting"
    assert decision.rule == "R1"


def test_r2_instance_q_dir_prefix(board):
    decision = route.route_paths(["q-consult/canonical/crm.md"], board)
    assert decision.project == "ASK Consulting"
    assert decision.rule == "R2"


def test_r3_skeleton_owned_relative_path(board):
    decision = route.route_paths(["q-system/.q-system/scripts/x.py"], board)
    assert decision.project == "kipi-system"
    assert decision.rule == "R3"


def test_r3_covers_a_root_level_skeleton_path(board):
    decision = route.route_paths(["plugins/p.md"], board)
    assert decision.project == "kipi-system"
    assert decision.rule == "R3"


def test_instance_owned_subtree_is_not_skeleton_work(board):
    """`q-system/my-project/` is authored per instance, so the path names no repo."""
    decision = route.route_paths(["q-system/my-project/icp.md"], board)
    assert decision.project is None
    assert "instance-owned" in decision.reason


def test_a_path_that_exists_nowhere_routes_nothing(board):
    decision = route.route_paths(["q-system/.q-system/scripts/absent.py"], board)
    assert decision.project is None


def test_two_rules_disagreeing_refuses_rather_than_picks(board):
    paths = [
        os.path.join(board.rows_by_project["ASK Consulting"]["path"], "q-consult/canonical/crm.md"),
        os.path.join(board.rows_by_project["cole-GTM"]["path"], "projects/site.md"),
    ]
    decision = route.route_paths(paths, board)
    assert decision.project is None
    assert "disagree" in decision.reason
    assert "ASK Consulting" in decision.reason and "cole-GTM" in decision.reason


def test_empty_path_list_routes_nothing(board):
    decision = route.route_paths([], board)
    assert decision.project is None


def test_routing_reads_the_registry_not_a_hardcoded_map(board, tmp_path):
    """MUTANT: move the row's path and the same DoR must stop routing there.

    A rule that answered from a literal table would keep returning
    "ASK Consulting" here and this case is the only thing that can tell them
    apart.
    """
    reg = json.loads((tmp_path / "instance-registry.json").read_text())
    reg["instances"][0]["path"] = str(tmp_path / "moved-away")
    (tmp_path / "instance-registry-mutant.json").write_text(json.dumps(reg))
    mutated = route.RoutingFacts.load(str(tmp_path / "instance-registry-mutant.json"),
                                      str(tmp_path / "kipi-update.sh"))
    assert route.route_paths(["q-consult/canonical/crm.md"], mutated).project is None


def test_unreadable_registry_classifies_nothing(tmp_path):
    facts = route.RoutingFacts.load(str(tmp_path / "missing.json"),
                                    str(tmp_path / "missing.sh"))
    assert facts.ok is False
    assert route.route_paths(["q-system/.q-system/scripts/x.py"], facts).project is None


# --------------------------------------------------------------------------
# the actions a run would take
# --------------------------------------------------------------------------

def test_plan_sets_project_and_owner_on_a_session_filed_ticket(board):
    rows = route.plan_actions([issue("ASK-9")], board)
    assert len(rows) == 1
    assert rows[0]["set_project"] == "kipi-system"
    assert rows[0]["add_label"] == "owner:sana"


def test_plan_leaves_an_existing_owner_label_alone(board):
    rows = route.plan_actions([issue("ASK-10", labels=["owner:sana"])], board)
    assert rows[0]["set_project"] == "kipi-system"
    assert rows[0]["add_label"] is None


def test_machine_filed_job_inflow_never_gets_an_owner_label(board):
    """The DoR's Not-doing line: those jobs need a liveness check, not a worker."""
    body = ("<!-- kipi-key: fleet-health/launchd-dark/com-cole-radar -->\n\n"
            + DOR.format(files="q-system/.q-system/scripts/x.py"))
    rows = route.plan_actions([issue("ASK-11", project="kipi-system", body=body)], board)
    assert rows[0]["add_label"] is None
    assert rows[0]["set_project"] is None  # already on a project


def test_job_migration_inflow_is_the_same_population(board):
    body = ("<!-- kipi-key: job-migration/com-kipi-disk-janitor -->\n\n"
            + DOR.format(files="q-system/.q-system/scripts/x.py"))
    rows = route.plan_actions([issue("ASK-12", body=body)], board)
    assert rows[0]["add_label"] is None


def test_unroutable_ticket_is_marked_not_guessed(board):
    rows = route.plan_actions([issue("ASK-13", files="somewhere/unknown.py")], board)
    assert rows[0]["set_project"] is None
    assert rows[0]["mark_unroutable"] is True
    assert rows[0]["reason"]


def test_an_already_marked_ticket_is_not_re_marked(board):
    """THE FIXTURE COMES FROM THE PRODUCER (PR #461 review, major).

    This case used to paste the marker into the DESCRIPTION, which is not where
    `apply_row` puts it -- it writes a COMMENT. The test agreed with itself and
    with nothing else, so `is_marked_unroutable` read a field the mark never
    reaches and every unroutable ticket was re-commented on every daily tick,
    each re-mark spending one of the run's 10 write slots. Calling the producer
    for the body is what makes that class unavailable rather than remembered.
    """
    marked = issue("ASK-14", files="somewhere/unknown.py", labels=["owner:sana"],
                   comments=[route.unroutable_comment("no rule fired")])
    rows = route.plan_actions([marked], board)
    assert rows[0]["mark_unroutable"] is False


def test_a_hand_written_mark_in_the_description_also_counts(board):
    """A person who pastes the marker into the body has marked it too."""
    body = ("<!-- route-unknown: routed by hand -->\n\n"
            + DOR.format(files="somewhere/unknown.py"))
    rows = route.plan_actions([issue("ASK-14b", body=body, labels=["owner:sana"])], board)
    assert rows[0]["mark_unroutable"] is False


def test_a_truncated_comment_read_never_re_marks(board):
    """An incomplete read is UNKNOWN, and UNKNOWN must not spend a write slot.

    The asymmetry is deliberate and is the opposite of `already_flagged()` in
    linear-triage-health.py: there, a missed flag is the expensive outcome; here,
    a daily duplicate comment is. So a truncated page with no marker on it is
    treated as marked, and counted under `mark_unknown` so the silence is named.
    """
    deep = issue("ASK-14c", files="somewhere/unknown.py", labels=["owner:sana"],
                 comments=["something else"], truncated=True)
    rows = route.plan_actions([deep], board)
    assert rows[0]["mark_unroutable"] is False
    assert route.measure([deep], board)["mark_unknown"] == 1


def test_board_query_asks_for_the_comments_the_reader_parses():
    """Bind the query to the reader: drop the field and the mark is unreadable."""
    assert "comments(" in route.BOARD_QUERY
    assert "body" in route.BOARD_QUERY
    assert "hasNextPage" in route.BOARD_QUERY


def test_a_row_with_nothing_to_do_is_dropped(board):
    """An unroutable ticket already marked AND already owned needs no write."""
    marked = issue("ASK-15", files="somewhere/unknown.py", labels=["owner:sana"],
                   comments=[route.unroutable_comment("no rule fired")])
    rows = route.plan_actions([marked], board)
    assert route.rows_with_work(rows) == []


def test_measure_splits_routable_from_unroutable(board):
    issues = [
        issue("ASK-16", labels=["owner:sana"]),                      # routable
        issue("ASK-17", files="somewhere/unknown.py"),               # unroutable
        issue("ASK-18", labels=["owner:sana"], project="kipi-system"),  # not pending
    ]
    m = route.measure(issues, board)
    assert m["pending"] == 2
    assert m["routable"] == 1
    assert m["unroutable"] == 1
    assert m["registry_ok"] is True


# --------------------------------------------------------------------------
# the write cap
# --------------------------------------------------------------------------

def test_limit_bounds_the_writes():
    rows = [{"id": f"ASK-{n}"} for n in range(10)]
    assert len(route.select_to_write(rows, 3)) == 3
    assert len(route.select_to_write(rows, 0)) == 10


def test_negative_limit_is_a_usage_error():
    with pytest.raises(ValueError):
        route.select_to_write([], -1)


# --------------------------------------------------------------------------
# the board-name check (ASK-4089): a route to a project the board lacks is
# refused in the plan, so it never takes one of the nightly write slots
# --------------------------------------------------------------------------

# The fixture board has two of the registry's three projects. cole-GTM is the
# registry row with no board project, the shape the first live run measured.
ON_BOARD = {"kipi-system", "ask consulting"}


def _gtm_ticket(tmp_path, ident="ASK-40"):
    return issue(ident, files=str(tmp_path / "cole-gtm" / "projects" / "site.md"))


def test_off_board_route_spends_no_write_slot(board, tmp_path):
    """RED ON MAIN: the off-board row took the only slot and failed at write time."""
    issues = [_gtm_ticket(tmp_path), issue("ASK-41")]
    rows = route.plan_actions(issues, board, ON_BOARD)
    picked = route.select_to_write(route.rows_with_work(rows), 1)
    assert [r["identifier"] for r in picked] == ["ASK-41"]
    off = next(r for r in rows if r["identifier"] == "ASK-40")
    assert off["set_project"] is None
    assert off["add_label"] is None
    # No route-unknown comment either: the DoR is fine, the board is not.
    assert off["mark_unroutable"] is False
    assert off["not_on_board"] == "cole-GTM"


def test_off_board_route_is_counted_and_named(board, tmp_path):
    m = route.measure([_gtm_ticket(tmp_path), issue("ASK-41")], board, ON_BOARD)
    assert m["not_on_board"] == 1
    assert m["not_on_board_ids"] == [{"id": "ASK-40", "project": "cole-GTM"}]
    # Still unroutable: no project was written.
    assert m["unroutable"] == 1
    assert m["routable"] == 1
    assert ("route refused: 'cole-GTM' is not a project on the board, so no project "
            "write for 1 ticket(s) (ASK-40)") in route.render(m, [])


def test_a_ticket_that_has_a_project_refuses_nothing(board, tmp_path):
    """PR #679 review, minor 2: no set_project would be written, so nothing is refused,
    and the owner label still lands."""
    t = issue("ASK-42", files=str(tmp_path / "cole-gtm" / "projects" / "site.md"),
              project="kipi-system")
    rows = route.plan_actions([t], board, ON_BOARD)
    assert rows[0]["not_on_board"] is None
    assert rows[0]["add_label"] == "owner:sana"
    assert route.measure([t], board, ON_BOARD)["not_on_board"] == 0


def test_an_off_board_ticket_is_not_counted_as_a_short_comment_read(board, tmp_path):
    """PR #679 review, minor 3: mark_unknown means the comment page ran out."""
    t = issue("ASK-43", files=str(tmp_path / "cole-gtm" / "projects" / "site.md"),
              truncated=True)
    rows = route.plan_actions([t], board, ON_BOARD)
    assert rows[0]["not_on_board"] == "cole-GTM"
    assert rows[0]["mark_unknown"] is False


def test_refusal_lines_are_one_per_project_not_per_ticket():
    refused = [{"id": f"ASK-{n}", "project": "cole-GTM"} for n in range(60)]
    refused.append({"id": "ASK-99", "project": "openwitness"})
    lines = route.not_on_board_lines(refused)
    assert len(lines) == 2
    assert "for 60 ticket(s) (ASK-0, ASK-1, ASK-2, ...)" in lines[0]
    assert "'openwitness'" in lines[1] and "for 1 ticket(s) (ASK-99)" in lines[1]


def test_board_check_ignores_case(board, tmp_path):
    """The board map is lowercased by _name_id_map; the check must match it."""
    rows = route.plan_actions([_gtm_ticket(tmp_path)], board, ON_BOARD | {"cole-gtm"})
    assert rows[0]["set_project"] == "cole-GTM"
    assert rows[0]["not_on_board"] is None


def test_no_board_list_leaves_the_check_off(board, tmp_path):
    """A dry run whose project read failed passes None here, and routes as before."""
    rows = route.plan_actions([_gtm_ticket(tmp_path)], board)
    assert rows[0]["set_project"] == "cole-GTM"
    assert route.measure([_gtm_ticket(tmp_path)], board)["not_on_board"] == 0


# --------------------------------------------------------------------------
# why a write failed: a local lookup miss is not Linear refusing
# --------------------------------------------------------------------------

ROW = {"id": "uuid-1", "identifier": "ASK-20", "set_project": "kipi-system",
       "add_label": None, "mark_unroutable": False, "reason": "r", "label_ids": []}


def test_a_missing_board_project_is_a_local_failure(board):
    """PR #461 review, minor: this never reached Linear, so nothing refused it."""
    with pytest.raises(route.WriteRefused) as exc:
        route.apply_row(FakeSync([]), dict(ROW), {}, {})
    assert exc.value.kind == "no-such-project"


def test_a_missing_team_label_is_a_local_failure(board):
    row = dict(ROW, set_project=None, add_label="owner:sana")
    with pytest.raises(route.WriteRefused) as exc:
        route.apply_row(FakeSync([]), row, {}, {})
    assert exc.value.kind == "no-such-label"


def test_a_rejected_mutation_is_named_as_linear_refusing(board):
    sync = FakeSync([{"issueUpdate": {"success": False}}])
    with pytest.raises(route.WriteRefused) as exc:
        route.apply_row(sync, dict(ROW), {"kipi-system": "pid"}, {})
    assert exc.value.kind == "linear-refused-project"


def test_a_rejected_comment_is_named_as_linear_refusing(board):
    row = dict(ROW, set_project=None, mark_unroutable=True)
    sync = FakeSync([{"commentCreate": {"success": False}}])
    with pytest.raises(route.WriteRefused) as exc:
        route.apply_row(sync, row, {}, {})
    assert exc.value.kind == "linear-refused-comment"


def test_every_write_failure_carries_a_kind(board):
    """No unnamed failure class: an alert that cannot say why says the wrong why."""
    assert route.WRITE_FAILURE_KINDS == (
        "no-such-project", "no-such-label", "linear-refused-project",
        "linear-refused-label", "linear-refused-comment")


def test_refuses_under_pytest():
    """The chokepoint, proven rather than documented. PYTEST_CURRENT_TEST is set."""
    assert os.environ.get("PYTEST_CURRENT_TEST")
    assert route.main(["--apply"]) == route.EXIT_REFUSED_FIXTURE


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
