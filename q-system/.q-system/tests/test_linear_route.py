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
          project=None, state="backlog", body=None):
    desc = body if body is not None else DOR.format(files=files)
    return {
        "id": f"uuid-{ident}",
        "identifier": ident,
        "title": f"title {ident}",
        "description": desc,
        "state": {"name": "Backlog", "type": state},
        "project": {"name": project} if project else None,
        "labels": {"nodes": [{"name": n} for n in labels]},
    }


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


def test_no_dor_is_not_pending(board):
    assert not route.is_pending(issue("ASK-4", body="just prose, no readiness"))


def test_founder_owned_is_not_pending(board):
    assert not route.is_pending(issue("ASK-5", labels=["owner:assaf"]))


@pytest.mark.parametrize("held", ["needs-scope", "blocked:capability"])
def test_held_is_not_pending(board, held):
    assert not route.is_pending(issue("ASK-6", labels=["owner:sana", held]))


def test_closed_state_is_not_pending(board):
    assert not route.is_pending(issue("ASK-7", labels=["owner:sana"], state="completed"))


def test_fleet_alert_is_not_pending(board):
    body = ("<!-- kipi-alert-fingerprint: abc123 -->\n\n"
            + DOR.format(files="q-system/.q-system/scripts/x.py"))
    assert not route.is_pending(issue("ASK-8", body=body))


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
    body = ("<!-- route-unknown: no rule fired -->\n\n"
            + DOR.format(files="somewhere/unknown.py"))
    rows = route.plan_actions([issue("ASK-14", body=body, labels=["owner:sana"])], board)
    assert rows[0]["mark_unroutable"] is False


def test_a_row_with_nothing_to_do_is_dropped(board):
    """An unroutable ticket already marked AND already owned needs no write."""
    body = ("<!-- route-unknown: no rule fired -->\n\n"
            + DOR.format(files="somewhere/unknown.py"))
    rows = route.plan_actions([issue("ASK-15", body=body, labels=["owner:sana"])], board)
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


def test_refuses_under_pytest():
    """The chokepoint, proven rather than documented. PYTEST_CURRENT_TEST is set."""
    assert os.environ.get("PYTEST_CURRENT_TEST")
    assert route.main(["--apply"]) == route.EXIT_REFUSED_FIXTURE


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
