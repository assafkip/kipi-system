"""linear-route-decide.py: the no-project backlog gets ROUTE, CLOSE or SPLIT (ASK-3959 stage 2).

Every model answer here is a fixture string and every Linear call goes to FakeSync,
which records the order. Nothing reaches the live board or the live state dir: the
state dir is tmp_path, and main() --apply refuses under pytest by itself.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


decide = _load("linear_route_decide", "linear-route-decide.py")
route = decide.route

TARGETS = [{"slug": "assafkip/kipi-system", "project": "kipi-system"},
           {"slug": "assafkip/ASK_AI_consultant", "project": "ASK Consulting"},
           {"slug": "assafkip/brag", "project": "brag"}]
# cole-GTM is a registry project ON the board but not a dispatch target, the case
# a validation that only checks "is it a project" lets through.
BOARD = {"kipi-system": "p-kipi", "ask consulting": "p-ask", "cole-gtm": "p-gtm"}


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUTE_DECIDE_STATE", str(tmp_path / "state"))


@pytest.fixture()
def facts(tmp_path):
    skel = tmp_path / "kipi-system"
    (skel / "q-system" / ".q-system" / "scripts").mkdir(parents=True)
    (skel / "q-system" / ".q-system" / "scripts" / "x.py").write_text("#\n")
    consulting = tmp_path / "consulting"
    (consulting / "q-consult" / "canonical").mkdir(parents=True)
    (consulting / "q-consult" / "canonical" / "crm.md").write_text("#\n")
    gtm = tmp_path / "cole-gtm"
    gtm.mkdir()
    reg = tmp_path / "instance-registry.json"
    reg.write_text(json.dumps({
        "skeleton": {"path": str(skel), "linear_project": "kipi-system"},
        "instances": [
            {"name": "ASK_AI_consultant", "linear_project": "ASK Consulting",
             "path": str(consulting), "instance_q_dir": "q-consult"},
            {"name": "cole-gtm", "linear_project": "cole-GTM", "path": str(gtm),
             "instance_q_dir": None}]}))
    updater = tmp_path / "kipi-update.sh"
    updater.write_text("#!/bin/bash\nINSTANCE_OWNED_SUBTREES=(\n  canonical\n  memory\n)\n")
    f = route.RoutingFacts.load(str(reg), str(updater))
    assert f.ok
    return f


def ticket(ident="ASK-7", body="Fix `q-system/.q-system/scripts/x.py` so it stops failing.",
           state="backlog", labels=("owner:sana",), comments=(), title=None):
    return {"id": f"uuid-{ident}", "identifier": ident, "title": title or f"title {ident}",
            "description": body, "state": {"name": state.title(), "type": state},
            "project": None, "labels": {"nodes": [{"id": f"l-{n}", "name": n} for n in labels]},
            "comments": {"nodes": [{"body": b} for b in comments], "pageInfo": {"hasNextPage": False}}}


def names():
    return decide.target_names(TARGETS, set(BOARD))


class Asker:
    """A model that answers from a queue and keeps every prompt it was sent."""

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else ""


class FakeSync:
    """Linear by query shape. Records (kind, variables) for every write, in order."""

    def __init__(self, fail_on=None, fail_times=None):
        self.writes, self.fail_on, self.fail_times = [], fail_on, fail_times
        self.children = []   # what issueCreate filed, so the children query can see it

    def graphql(self, query, variables):
        if "children(" in query:
            by_id = {v: k for k, v in BOARD.items()}
            return {"issue": {"children": {"nodes": [
                {"identifier": c["id"], "title": c["title"], "description": c["description"],
                 "project": {"name": by_id.get(c["projectId"], "")}}
                for c in self.children if c["parentId"] == variables["id"]]}}}
        if "projects(first" in query:
            return {"team": {"projects": {"nodes": [{"id": v, "name": k} for k, v in BOARD.items()]}}}
        if "labels(first" in query:
            return {"team": {"labels": {"nodes": [{"id": "l-owner", "name": "owner:sana"},
                                                  {"id": "l-triage", "name": "needs-triage"}]}}}
        if "states{" in query:
            return {"team": {"states": {"nodes": [{"id": "s-dup", "name": "Duplicate", "type": "canceled"},
                                                  {"id": "s-can", "name": "Canceled", "type": "canceled"}]}}}
        kind = ("comment" if "commentCreate" in query else "create" if "issueCreate" in query
                else "update")
        if self.fail_on == kind and (self.fail_times is None or self.fail_times > 0):
            if self.fail_times is not None:
                self.fail_times -= 1
            # The transport raises on a 429, as linear-sync.graphql does.
            raise RuntimeError("HTTP 429: rate limited")
        self.writes.append((kind, variables))
        if kind == "comment":
            return {"commentCreate": {"success": True}}
        if kind == "create":
            ident = f"ASK-90{len(self.children)}"
            self.children.append({"id": ident, **variables["input"]})
            return {"issueCreate": {"success": True, "issue": {"identifier": ident}}}
        return {"issueUpdate": {"success": True, "issue": {"identifier": "x"}}}


# ---------------------------------------------------------------------------
# who is asked
# ---------------------------------------------------------------------------

def test_a_ticket_the_rules_can_route_is_never_put_to_the_model(facts, tmp_path):
    """Deterministic rules first: an absolute path inside a checkout is R1's, and
    linear-route.py --apply writes it. The model is not asked about it."""
    path = facts.rows_by_project["ASK Consulting"]["path"] + "/q-consult/canonical/crm.md"
    routed = ticket("ASK-1", body=f"Broken: `{path}`")
    left = ticket("ASK-2")
    pop = decide.population([routed, left], facts)
    assert [i["identifier"] for i in pop] == ["ASK-2"]


def test_a_route_the_rules_name_off_the_board_falls_to_the_model(facts):
    """linear-route.py refuses a deterministic route to a project the board does
    not have (ASK-4089, #679). That ticket is then routed by nothing, so this
    pass has to be its consumer, which it is only if it hands the router the
    board. Without the board, the router's plan still says "routed"."""
    t = ticket("ASK-8", body="no paths here", title="[cole-GTM] the site footer is broken")
    on_board = {"kipi-system", "ask consulting"}
    assert decide.population([t], facts, on_board) == [t]


def test_todo_comes_first_then_oldest_and_last_time_failures_go_last():
    pop = [ticket("ASK-30"), ticket("ASK-12"), ticket("ASK-50", state="unstarted"),
           ticket("ASK-5")]
    got = [i["identifier"] for i in decide.order(pop, failed={"ASK-5"})]
    assert got == ["ASK-50", "ASK-12", "ASK-30", "ASK-5"]


def test_a_failed_ask_is_remembered_and_a_later_success_clears_it(tmp_path):
    decide.record([{"id": "ASK-5", "outcome": "model-failed", "applied": False},
                   {"id": "ASK-6", "outcome": "write-failed", "applied": False},
                   {"id": "ASK-6", "outcome": "applied", "applied": True}])
    assert decide.failed_before() == {"ASK-5"}


# ---------------------------------------------------------------------------
# the vocabulary
# ---------------------------------------------------------------------------

def test_a_backlog_ticket_naming_a_repo_path_gets_routed(facts):
    """The design's case: the text names a skeleton path, which free-text R1/R2
    cannot place, so it falls to the model, and a valid ROUTE comes back."""
    t = ticket("ASK-7")
    assert decide.population([t], facts) == [t]
    ask = Asker("DECISION: ROUTE kipi-system\nREASON: x.py is a fleet script.")
    d = decide.decide_one(t, names(), facts, ask=ask)
    assert (d["kind"], d["project"], d["refused"]) == ("ROUTE", "kipi-system", [])
    assert "q-system/.q-system/scripts/x.py" in ask.prompts[0]


def test_an_invalid_route_is_refused_and_asked_again(facts):
    """cole-GTM is a real board project but not a dispatch target. A ROUTE there
    would send the ticket where no worker ever goes, so it is refused, and the
    second ask carries the refusal and the allowed names."""
    ask = Asker("DECISION: ROUTE cole-GTM\nREASON: site copy.",
                "DECISION: ROUTE kipi-system\nREASON: fleet script.")
    d = decide.decide_one(ticket(), names(), facts, ask=ask)
    assert len(ask.prompts) == 2
    assert "refused" in ask.prompts[1] and "cole-GTM" in ask.prompts[1]
    assert "kipi-system" in ask.prompts[1].split("refused", 1)[1]
    assert (d["kind"], d["project"]) == ("ROUTE", "kipi-system")
    assert len(d["refused"]) == 1


def test_two_refusals_default_to_close_no_fleet_repo_owns_this(facts):
    ask = Asker("DECISION: ROUTE cole-GTM", "I think it belongs to marketing.")
    d = decide.decide_one(ticket(), names(), facts, ask=ask)
    assert (d["kind"], d["reason"], d["defaulted"]) == ("CLOSE", decide.NO_OWNER_REASON, True)
    assert len(d["refused"]) == 2


def test_no_answer_at_all_is_a_failed_call_not_a_decision(facts):
    assert decide.decide_one(ticket(), names(), facts, ask=Asker("")) is None


def test_a_target_that_is_not_on_the_board_is_not_a_valid_route():
    """The ASK-4089 failure, pre-empted: brag is a dispatch target with no board
    project, so a ROUTE to it is a write that can never land."""
    assert "brag" not in decide.target_names(TARGETS, set(BOARD))
    parse = decide.make_parse(names())
    assert parse("DECISION: ROUTE brag", 1)[0] is None


def test_split_needs_two_children_each_naming_a_target(facts):
    parse = decide.make_parse(names())
    one = "DECISION: SPLIT\nSUBTICKET: kipi-system :: a :: b\n"
    bad = one + "SUBTICKET: cole-GTM :: c :: d\n"
    good = one + "SUBTICKET: ASK Consulting :: c :: d\n"
    assert parse(one, 1)[0] is None
    assert parse(bad, 1)[0] is None and "cole-GTM" in parse(bad, 1)[1]
    d, why = parse(good, 1)
    assert why == "" and [c["project"] for c in d["children"]] == ["kipi-system", "ASK Consulting"]


def test_the_prompt_carries_this_pass_s_earlier_record(facts):
    """A split that failed halfway leaves the parent open with its children filed.
    The next ask must see that record, or it splits the ticket a second time."""
    earlier = decide.decision_comment({"kind": "SPLIT", "reason": "two repos (PARTIAL)"}, ["ASK-901"])
    t = ticket(comments=["an unrelated comment", earlier])
    prompt = decide.build_prompt(t, names(), facts, [])
    assert "ASK-901" in prompt and "an unrelated comment" not in prompt


# ---------------------------------------------------------------------------
# the writes
# ---------------------------------------------------------------------------

def test_route_sets_the_target_project_and_the_owner_label_then_records_why(facts):
    sync = FakeSync()
    board = decide.Board(sync, "team-1")
    t = ticket(labels=())
    decide.apply_decision(board, t, {"kind": "ROUTE", "project": "kipi-system", "reason": "r"})
    kinds = [k for k, _ in sync.writes]
    assert kinds == ["update", "update", "comment"]
    assert sync.writes[0][1]["input"] == {"projectId": "p-kipi"}
    assert "l-owner" in sync.writes[1][1]["input"]["labelIds"]
    assert "Routed to kipi-system" in sync.writes[2][1]["input"]["body"]


def test_close_writes_the_reason_before_the_cancel_and_picks_canceled_not_duplicate(facts):
    sync = FakeSync()
    board = decide.Board(sync, "team-1")
    decide.apply_decision(board, ticket(), {"kind": "CLOSE", "reason": decide.NO_OWNER_REASON,
                                            "defaulted": True, "refused": ["a", "b"]})
    assert [k for k, _ in sync.writes] == ["comment", "update"]
    assert decide.NO_OWNER_REASON in sync.writes[0][1]["input"]["body"]
    assert sync.writes[1][1]["input"] == {"stateId": "s-can"}


def test_a_cancel_that_does_not_land_raises_so_the_run_counts_a_failure(facts):
    sync = FakeSync(fail_on="update")
    board = decide.Board(sync, "team-1")
    with pytest.raises(RuntimeError):
        decide.apply_decision(board, ticket(), {"kind": "CLOSE", "reason": "r"})


def test_split_files_each_child_in_its_own_project_then_cancels_the_parent(facts):
    sync = FakeSync()
    board = decide.Board(sync, "team-1")
    d = {"kind": "SPLIT", "reason": "two repos",
         "children": [{"project": "kipi-system", "title": "a", "outcome": "b"},
                      {"project": "ASK Consulting", "title": "c", "outcome": "d"}]}
    done = decide.apply_decision(board, ticket(), d)
    creates = [v["input"] for k, v in sync.writes if k == "create"]
    assert [c["projectId"] for c in creates] == ["p-kipi", "p-ask"]
    assert all(c["parentId"] == "uuid-ASK-7" and "l-triage" in c["labelIds"] for c in creates)
    assert [k for k, _ in sync.writes][-2:] == ["comment", "update"]
    assert done[-1] == "canceled"


SPLIT = {"kind": "SPLIT", "reason": "two repos",
         "children": [{"project": "kipi-system", "title": "a", "outcome": "b"},
                      {"project": "ASK Consulting", "title": "c", "outcome": "d"}]}


def test_a_split_whose_record_failed_files_no_second_set_of_children(facts):
    """PR #690 rounds 1 and 2, major. Night 1: both children land, then the record
    comment raises (a 429). Night 2 answers with REWORDED titles and a different
    project for one child. Any marked child means the split already happened, so
    nothing new is filed. Linear issues cannot be deleted."""
    sync = FakeSync(fail_on="comment", fail_times=1)
    board = decide.Board(sync, "team-1")
    with pytest.raises(RuntimeError):
        decide.apply_decision(board, ticket(), SPLIT)
    assert len(sync.children) == 2
    reworded = dict(SPLIT, children=[
        {"project": "ASK Consulting", "title": "a, reworded", "outcome": "b"},
        {"project": "ASK Consulting", "title": "c, reworded", "outcome": "d"}])
    done = decide.apply_decision(board, ticket(), reworded)
    assert len(sync.children) == 2, [c["title"] for c in sync.children]
    assert done[-1] == "canceled" and "child=ASK-900" in done and "child=ASK-901" in done
    record = [v["input"]["body"] for k, v in sync.writes if k == "comment"][-1]
    # Round 2 minor: the record names what is on the board, projects included,
    # not the new answer's children.
    assert "filed on an earlier run" in record and "kipi-system" in record


def test_a_ticket_with_filed_children_is_finished_without_asking_the_model(facts):
    t = dict(ticket(), split_children=[{"identifier": "ASK-900", "title": "a", "project": "kipi-system"}])
    ask = Asker("DECISION: CLOSE")
    d = decide.resume_decision(t) or decide.decide_one(t, names(), facts, ask=ask)
    assert d["kind"] == "SPLIT" and d.get("resumed") and ask.prompts == []
    assert decide.resume_decision(ticket()) is None


def test_a_split_child_carries_the_marker_that_finds_it_again(facts):
    sync = FakeSync()
    decide.apply_decision(decide.Board(sync, "team-1"), ticket(), SPLIT)
    assert all("<!-- kipi-route-split-of: ASK-7 -->" in c["description"] for c in sync.children)


def test_the_prompt_lists_the_children_already_filed(facts):
    t = dict(ticket(), split_children=[{"identifier": "ASK-900", "title": "a"}])
    prompt = decide.build_prompt(t, names(), facts, [])
    assert "ASK-900" in prompt and "do not file them again" in prompt


def test_a_truncated_comment_page_is_said_not_read_as_none(facts):
    """PR #690 round 1, minor: 50 comments is a page, not the thread."""
    t = ticket(comments=["x"] * 3)
    t["comments"]["pageInfo"]["hasNextPage"] = True
    assert "not read" in decide.history(t)


def test_apply_under_pytest_is_refused_before_any_read(monkeypatch):
    monkeypatch.setattr(decide.route, "_load_sync", lambda: pytest.fail("reached the network"))
    assert decide.main(["--apply"]) == decide.EXIT_REFUSED_FIXTURE


def test_a_bare_binary_name_becomes_the_path_the_wrapper_can_check(tmp_path, monkeypatch):
    """run_model refuses a binary that os.path.exists cannot see, and the shared
    lookup returns a bare "claude". The first live run lost every answer to it."""
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake.parent))
    assert decide.absolute_binary("claude") == str(fake)
    assert decide.absolute_binary(str(fake)) == str(fake)
    assert decide.absolute_binary(str(tmp_path / "nope")) is None
    assert decide.absolute_binary(None) is None


def test_the_model_comes_from_the_routing_table_not_a_literal():
    assert decide.MODEL == decide.model_route.pick("fleet-triage")
