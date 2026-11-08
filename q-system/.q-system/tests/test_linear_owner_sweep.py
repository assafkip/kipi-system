#!/usr/bin/env python3
"""Every open fleet ticket has an owner label (ASK-4010).

RED FIRST. The first case asks every consumer that can write an owner label,
linear-route.py on main and linear-owner-sweep.py once it exists, what it would
do with one ownerless kipi-system ticket. On main linear-route.py skips it (job
inflow, ASK-1887 "Not doing") and nothing else exists, so the ticket stays
unowned and the case is red on behaviour, not on an import.

NEVER A LIVE PATH. Everything here is the pure half or a fake transport. --apply
refuses under pytest, and test_refuses_apply_under_pytest proves the rail is real.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
SWEEP_PATH = SCRIPTS / "linear-owner-sweep.py"


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


route = _load("linear_route_for_owner_sweep", SCRIPTS / "linear-route.py")
sweep = _load("linear_owner_sweep", SWEEP_PATH) if SWEEP_PATH.exists() else None

FLEET = frozenset({"kipi-system", "cole-GTM"})
DOR = ("## Definition of Ready\n\n* **Outcome:** x.\n"
       "* **Files:** `q-system/.q-system/scripts/x.py`\n* **Check:** y.\n")
JOB_INFLOW = "<!-- kipi-key: fleet-health/stranded-commits/x -->\n\nbody\n\n" + DOR


def ticket(ident="ASK-9001", *, labels=(), project="kipi-system", state="backlog",
           desc=JOB_INFLOW):
    return {"id": f"uuid-{ident}", "identifier": ident, "title": "t", "description": desc,
            "state": {"type": state}, "project": ({"name": project} if project else None),
            "labels": {"nodes": [{"id": f"lid-{n}", "name": n} for n in labels]},
            "comments": {"nodes": [], "pageInfo": {"hasNextPage": False}}}


def owners_after_every_consumer(issue: dict) -> list:
    """Which consumers would give this ticket an owner label. [] means nobody."""
    who = []
    facts = route.RoutingFacts.load(str(SCRIPTS.parents[2] / "instance-registry.json"))
    for row in route.plan_actions([issue], facts):
        if row.get("add_label"):
            who.append("linear-route.py")
    if sweep is not None:
        if issue["identifier"] in [i["identifier"] for i in sweep.plan([issue], FLEET)["sweep"]]:
            who.append("linear-owner-sweep.py")
    return who


# --- the red case -----------------------------------------------------------

def test_an_ownerless_fleet_ticket_gets_an_owner_from_some_consumer():
    who = owners_after_every_consumer(ticket())
    assert who, ("ASK-9001 (kipi-system, no owner:* label, open) is left unowned by "
                 "every consumer on this tree: linear-route.py skips job inflow and "
                 "nothing else writes an owner label")


# --- the sweep's rules --------------------------------------------------------

needs_sweep = pytest.mark.skipif(sweep is None, reason="linear-owner-sweep.py not on this tree")


@needs_sweep
@pytest.mark.parametrize("labels", [("owner:sana",), ("Owner:Sana",), ("owner:cole",)])
def test_an_owned_ticket_is_never_swept(labels):
    p = sweep.plan([ticket(labels=labels)], FLEET)
    assert p["sweep"] == [] and p["owned"] == 1


@needs_sweep
def test_owner_assaf_is_counted_and_never_relabelled():
    p = sweep.plan([ticket("ASK-1", labels=("owner:assaf",)),
                    ticket("ASK-2", labels=("owner:assaf", "needs-scope"))], FLEET)
    assert p["sweep"] == []
    assert p["founder"] == ["ASK-1", "ASK-2"]


@needs_sweep
def test_project_unset_is_the_fleets_population():
    p = sweep.plan([ticket(project=None, desc="no dor")], FLEET)
    assert [i["identifier"] for i in p["sweep"]] == ["ASK-9001"]


@needs_sweep
def test_outside_project_is_listed_not_swept():
    p = sweep.plan([ticket("ASK-7", project="Chief")], FLEET)
    assert p["sweep"] == [] and p["outside"] == {"Chief": ["ASK-7"]}


@needs_sweep
@pytest.mark.parametrize("state", ["completed", "canceled"])
def test_a_closed_ticket_is_never_swept(state):
    assert sweep.plan([ticket(state=state)], FLEET)["sweep"] == []


@needs_sweep
@pytest.mark.parametrize("state", ["backlog", "unstarted", "started", "triage"])
def test_every_open_state_is_in_scope(state):
    assert len(sweep.plan([ticket(state=state)], FLEET)["sweep"]) == 1


@needs_sweep
def test_unreadable_registry_classifies_nothing(tmp_path):
    bad = tmp_path / "reg.json"
    bad.write_text("{not json")
    assert sweep.fleet_projects(str(bad)) == (frozenset(), False)


@needs_sweep
def test_registry_rows_name_the_fleet(tmp_path):
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"skeleton": {"name": "kipi-system", "path": "/nowhere/a"},
                               "instances": [{"name": "x", "linear_project": "cole-GTM",
                                              "path": "/nowhere/b"}]}))
    names, ok = sweep.fleet_projects(str(reg))
    assert ok and names == frozenset({"kipi-system", "cole-GTM"})


# --- the comment ------------------------------------------------------------

BANNED = ("someone", "somebody", "a human", "a person", "manual", "operator", "parked for later")


@needs_sweep
@pytest.mark.parametrize("issue,named", [
    (ticket(), "com.kipi.dispatch"),
    (ticket(desc="plain body"), "linear-dor-drafter.py"),
    (ticket(project=None, desc=DOR), "linear-route.py"),
    (ticket(project=None, desc="plain body"), "ASK-3959"),
    (ticket(desc="<!-- kipi-alert-fingerprint: abc -->"), "linear-alert-triage.py"),
])
def test_the_comment_names_the_next_consumer(issue, named):
    body = sweep.sweep_comment(issue)
    assert body.startswith(f"<!-- {sweep.SWEEP_MARKER}:")
    assert named in body
    assert not [w for w in BANNED if w in body.lower()]
    # PR #654 review, minor: the comment once said the run evidence keeps the
    # ticket visible. last-run.json is overwritten nightly and no script reads it,
    # so the sentence named an artifact where it owed a consumer, on up to 44
    # permanent Linear comments.
    assert "evidence" not in body.lower()


# --- the write path, against a fake transport -------------------------------

class FakeSync:
    def __init__(self, *, fresh_labels=(), comments=(), truncated=False,
                 comment_ok=True, label_ok=True, state="backlog"):
        self.calls = []
        self.fresh = {"id": "uuid-ASK-9001", "identifier": "ASK-9001", "state": {"type": state},
                      "labels": {"nodes": [{"id": "x", "name": n} for n in fresh_labels]},
                      "comments": {"nodes": [{"body": b} for b in comments],
                                   "pageInfo": {"hasNextPage": truncated}}}
        self.comment_ok, self.label_ok = comment_ok, label_ok

    def graphql(self, query, variables):
        if "commentCreate" in query:
            self.calls.append(("comment", variables["input"]["body"]))
            return {"commentCreate": {"success": self.comment_ok}}
        if "issueUpdate" in query:
            self.calls.append(("label", variables["input"]))
            return {"issueUpdate": {"success": self.label_ok}}
        if "issue(id" in query:
            self.calls.append(("read", variables["id"]))
            return {"issue": self.fresh}
        raise AssertionError(f"unexpected query {query[:40]}")


def kinds(fake):
    return [c[0] for c in fake.calls]


@needs_sweep
def test_comment_then_label_with_added_label_ids():
    fake = FakeSync()
    did = sweep.apply_one(fake, ticket(), "LID")
    assert kinds(fake) == ["read", "comment", "label"]
    assert fake.calls[2][1] == {"addedLabelIds": ["LID"]}
    assert "commented" in did and "labelled owner:sana" in did


@needs_sweep
def test_a_rerun_after_a_failed_label_does_not_comment_twice():
    body = sweep.sweep_comment(ticket())
    fake = FakeSync(comments=(body,))
    sweep.apply_one(fake, ticket(), "LID")
    assert kinds(fake) == ["read", "label"]


@needs_sweep
def test_an_owner_that_arrived_after_the_walk_wins():
    fake = FakeSync(fresh_labels=("owner:cole",))
    assert sweep.apply_one(fake, ticket(), "LID") == "owned-since-walk"
    assert kinds(fake) == ["read"]


@needs_sweep
def test_a_refused_comment_stops_before_the_label():
    fake = FakeSync(comment_ok=False)
    with pytest.raises(sweep.WriteRefused):
        sweep.apply_one(fake, ticket(), "LID")
    assert kinds(fake) == ["read", "comment"]


@needs_sweep
def test_a_refused_label_is_reported():
    fake = FakeSync(label_ok=False)
    with pytest.raises(sweep.WriteRefused):
        sweep.apply_one(fake, ticket(), "LID")


@needs_sweep
def test_truncated_comments_label_without_a_second_comment():
    fake = FakeSync(truncated=True)
    did = sweep.apply_one(fake, ticket(), "LID")
    assert kinds(fake) == ["read", "label"] and "comment-skipped-truncated" in did


@needs_sweep
def test_refuses_apply_under_pytest():
    assert sweep.main(["--apply"]) == sweep.EXIT_REFUSED_FIXTURE


@needs_sweep
def test_evidence_is_written_atomically(tmp_path):
    path = tmp_path / "deep" / "last-run.json"
    sweep.write_evidence(path, {"a": 1})
    assert json.loads(path.read_text()) == {"a": 1}
    assert [p.name for p in path.parent.iterdir()] == ["last-run.json"]


# --- the wiring ---------------------------------------------------------------

@needs_sweep
def test_the_job_runs_the_sweep_with_apply_from_the_shared_checkout():
    """PR #654 review, major. The sweep reads instance-registry.json relative to its
    own tree (linear_registry.default_registry_path). Pinned, that tree is
    origin/main, whose registry lacked infohawk on 2026-11-08 while the shared
    checkout had it, so infohawk tickets were classed "outside" and never owned,
    exit 0. Its three registry-reading siblings are shared exceptions for the same
    reason; ASK-3967 moves all four once the registry stops drifting.
    """
    plist = (SCRIPTS / "com.kipi.linear-owner-sweep.plist").read_text()
    assert "q-system/.q-system/scripts/linear-owner-sweep.py --apply" in plist
    src = SWEEP_PATH.read_text()
    assert "linear_registry.default_registry_path()" in src, \
        "the sweep no longer reads the tree-relative registry; re-decide pinned vs shared"
    table = json.loads((HERE.parent / "job-checkouts.json").read_text())
    assert "com.kipi.linear-owner-sweep" not in table["pinned"]
    exc = table["shared_exceptions"]["com.kipi.linear-owner-sweep"]
    assert "instance-registry.json" in exc["reason"] and exc["ticket"] == "ASK-3967"
