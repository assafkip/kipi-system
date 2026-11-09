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
    """Linear by query shape, with state. Records (kind, variables) for every write,
    in order, AND applies it to `issues`, so a second night reads what the first
    one left on the board, the way the job does."""

    def __init__(self, fail_on=None, fail_times=None, fail_when=None):
        self.writes, self.fail_on, self.fail_times = [], fail_on, fail_times
        # fail_when(kind, variables) -> bool, for "only the label write fails".
        self.fail_when = fail_when
        self.issues = {}     # id -> the ticket dict the board walk would return

    def put(self, t: dict) -> dict:
        self.issues[t["id"]] = t
        return t

    def view(self, ident: str) -> dict:
        """The ticket as the next night's board walk reads it: a fresh copy."""
        t = next(i for i in self.issues.values() if i["identifier"] == ident)
        return json.loads(json.dumps(t))

    def graphql(self, query, variables):
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
        failing = (self.fail_when(kind, variables) if self.fail_when
                   else self.fail_on == kind)
        if failing and (self.fail_times is None or self.fail_times > 0):
            if self.fail_times is not None:
                self.fail_times -= 1
            # The transport raises on a 429, as linear-sync.graphql does.
            raise RuntimeError("HTTP 429: rate limited")
        self.writes.append((kind, variables))
        if kind == "create":
            pytest.fail("this pass filed a ticket; it files none (ASK-4133)")
        if kind == "comment":
            t = self.issues.get(variables["input"]["issueId"])
            if t is not None:
                t["comments"]["nodes"].append({"body": variables["input"]["body"]})
            return {"commentCreate": {"success": True}}
        t = self.issues.get(variables["id"])
        inp = variables["input"]
        if t is not None:
            if "stateId" in inp:
                t["state"] = {"name": "Canceled", "type": "canceled"}
            if "projectId" in inp:
                name = next(k for k, v in BOARD.items() if v == inp["projectId"])
                t["project"] = {"name": name}
            if "labelIds" in inp:
                t["labels"]["nodes"] = [{"id": i, "name": i[2:]} for i in inp["labelIds"]]
        return {"issueUpdate": {"success": True, "issue": {"identifier": "x"}}}


def writes_of(sync, kind, key=None):
    return [v for k, v in sync.writes if k == kind and (key is None or key in v.get("input", {}))]


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
    """The next ask sees this pass's own record, and only that."""
    earlier = decide.decision_comment({"kind": "CLOSE", "reason": "obsolete since ASK-901"})
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
    decide.apply_decision(board, t, {"kind": "ROUTE", "project": "kipi-system", "reason": "r"}, set())
    kinds = [k for k, _ in sync.writes]
    assert kinds == ["update", "update", "comment"]
    assert sync.writes[0][1]["input"] == {"projectId": "p-kipi"}
    assert "l-owner" in sync.writes[1][1]["input"]["labelIds"]
    assert "Routed to kipi-system" in sync.writes[2][1]["input"]["body"]


def test_close_writes_the_reason_before_the_cancel_and_picks_canceled_not_duplicate(facts):
    sync = FakeSync()
    board = decide.Board(sync, "team-1")
    decide.apply_decision(board, ticket(), {"kind": "CLOSE", "reason": decide.NO_OWNER_REASON,
                                            "defaulted": True, "refused": ["a", "b"]}, set())
    assert [k for k, _ in sync.writes] == ["comment", "update"]
    assert decide.NO_OWNER_REASON in sync.writes[0][1]["input"]["body"]
    assert sync.writes[1][1]["input"] == {"stateId": "s-can"}


def test_a_cancel_that_does_not_land_raises_so_the_run_counts_a_failure(facts):
    sync = FakeSync(fail_on="update")
    board = decide.Board(sync, "team-1")
    with pytest.raises(RuntimeError):
        decide.apply_decision(board, ticket(), {"kind": "CLOSE", "reason": "r"}, set())


SPLIT_ANSWER = ("DECISION: SPLIT\nSUBTICKET: kipi-system :: fix the hook :: the hook stops failing\n"
                "SUBTICKET: ASK Consulting :: fix the crm :: the crm loads\nREASON: two repos.")


def test_a_split_routes_to_its_first_part_and_names_every_part_in_the_record(facts):
    """ASK-4133, decided by measuring: a SPLIT files no ticket. It is a route to
    its first part, and every part goes in the record for that repo's worker."""
    d, _ = decide.make_parse(names())(SPLIT_ANSWER, 1)
    sync = FakeSync()
    t = sync.put(ticket(labels=()))
    decide.apply_decision(decide.Board(sync, "team-1"), t, d, set())
    assert [k for k, _ in sync.writes] == ["update", "update", "comment"]
    assert sync.writes[0][1]["input"] == {"projectId": "p-kipi"}
    body = sync.writes[2][1]["input"]["body"]
    assert "fix the hook" in body and "fix the crm" in body and "files none" in body
    assert not writes_of(sync, "update", "stateId")


# ---------------------------------------------------------------------------
# across nights: every write this pass can make, run again on a later night
# ---------------------------------------------------------------------------
# PR #690 rounds 1 to 3 each found a second night that repeated a write
# (rca-pr-690-split-idempotency-rounds-2026-11-08.md). One-night tests proved
# one-night code. These run the job's own per-ticket path, one_ticket(), against
# a board that keeps state, with a human's undo in between.

QUIET = "The nightly digest stops early; no file named."


def night(sync, facts, *answers, ident="ASK-7", mangle=None):
    """One night of the job for one ticket: walk, population, decide, write, log.
    Returns (row, asker), or (None, None) when the ticket is not in the population."""
    t = sync.view(ident)
    if mangle:
        mangle(t)
    pop = decide.population([t], facts, set(BOARD))
    if not pop:
        return None, None
    ask = Asker(*answers)
    rec = decide.one_ticket(pop[0], names(), facts, decide.Board(sync, "team-1"),
                            decide.landed_writes(decide.ledger_rows()), ask=ask)
    decide.record([rec])
    return rec, ask


def reopen(sync, ident="ASK-7"):
    next(i for i in sync.issues.values() if i["identifier"] == ident)["state"] = {
        "name": "Backlog", "type": "backlog"}


def unset_project(sync, ident="ASK-7"):
    next(i for i in sync.issues.values() if i["identifier"] == ident)["project"] = None


def test_a_close_reopened_on_purpose_is_never_canceled_again_over_three_nights(facts):
    """The round 3 major, on the branch it was NOT found on. Night 1 cancels. A
    human reopens. Night 2's model says CLOSE twice: both refused, and the
    default is a route to the fleet, not a second cancel. Night 3 sees a ticket
    with a project and leaves it."""
    sync = FakeSync()
    sync.put(ticket(body=QUIET))
    rec1, _ = night(sync, facts, "DECISION: CLOSE\nREASON: obsolete.")
    assert rec1["outcome"] == "applied" and len(writes_of(sync, "update", "stateId")) == 1
    reopen(sync)
    rec2, ask2 = night(sync, facts, "DECISION: CLOSE\nREASON: still obsolete.",
                       "DECISION: CLOSE\nREASON: really obsolete.")
    assert len(writes_of(sync, "update", "stateId")) == 1, "a reopened ticket was canceled again"
    assert decide.CLOSE_LINE not in ask2.prompts[0] and "CLOSE is not allowed" in ask2.prompts[1]
    assert (rec2["kind"], rec2["project"], rec2["defaulted"]) == ("ROUTE", "kipi-system", True)
    assert sync.view("ASK-7")["project"] == {"name": "kipi-system"}
    assert night(sync, facts, "DECISION: CLOSE") == (None, None)


def test_a_route_whose_project_was_removed_is_never_routed_there_again(facts):
    sync = FakeSync()
    sync.put(ticket(body=QUIET))
    night(sync, facts, "DECISION: ROUTE kipi-system\nREASON: fleet.")
    unset_project(sync)
    rec2, ask2 = night(sync, facts, "DECISION: ROUTE kipi-system\nREASON: fleet.",
                       "DECISION: ROUTE ASK Consulting\nREASON: the crm.")
    assert "undone" in rec2["refused"][0]
    assert [v["input"]["projectId"] for v in writes_of(sync, "update", "projectId")] == ["p-kipi", "p-ask"]
    assert night(sync, facts, "DECISION: ROUTE kipi-system") == (None, None)


def test_split_then_failed_record_then_undo_files_nothing_and_repeats_nothing_over_three_nights(facts):
    """ASK-4133's done-when, in the shape v1 ships. Night 1: SPLIT, the project
    lands, the record comment 429s, so the board has no record and only
    the log knows. The human undoes it (project removed, ticket reopened). Night
    2 repeats the same split: refused, from the log alone. Its second answer
    splits with the other repo first. Night 3 leaves it. No ticket is filed and
    nothing is canceled on any night."""
    sync = FakeSync(fail_on="comment", fail_times=1)
    sync.put(ticket(body=QUIET))
    rec1, _ = night(sync, facts, SPLIT_ANSWER)
    assert rec1["outcome"] == "write-failed"
    assert rec1["writes"] == ["project=kipi-system"]
    assert not [c for c in sync.view("ASK-7")["comments"]["nodes"]]
    unset_project(sync)
    reopen(sync)
    other_first = SPLIT_ANSWER.replace("SUBTICKET: kipi-system", "SUBTICKET: X").replace(
        "SUBTICKET: ASK Consulting", "SUBTICKET: kipi-system").replace("SUBTICKET: X", "SUBTICKET: ASK Consulting")
    rec2, _ = night(sync, facts, SPLIT_ANSWER, other_first)
    assert "undone" in rec2["refused"][0] and rec2["project"] == "ASK Consulting"
    assert night(sync, facts, SPLIT_ANSWER) == (None, None)
    assert not writes_of(sync, "create") and not writes_of(sync, "update", "stateId")
    assert [v["input"]["projectId"] for v in writes_of(sync, "update", "projectId")] == ["p-kipi", "p-ask"]


def test_a_project_that_landed_before_its_label_failed_is_still_known(facts):
    """Why set_project is two apply_row calls: apply_row drops its own list when
    it raises, so a project that landed before the label 429'd was invisible to
    the log, and an undo of it was repeated."""
    sync = FakeSync(fail_when=lambda k, v: k == "update" and "labelIds" in v["input"], fail_times=1)
    sync.put(ticket(body=QUIET, labels=()))
    rec1, _ = night(sync, facts, "DECISION: ROUTE kipi-system\nREASON: fleet.")
    assert rec1["outcome"] == "write-failed" and rec1["writes"] == ["project=kipi-system"]
    unset_project(sync)
    rec2, _ = night(sync, facts, "DECISION: ROUTE kipi-system", "DECISION: ROUTE ASK Consulting")
    assert rec2["project"] == "ASK Consulting"


def test_a_route_write_that_never_landed_does_not_block_that_route(facts):
    """The guard is about writes that LANDED. A project write that 429'd itself
    undid nothing, so the same route is allowed the next night."""
    sync = FakeSync(fail_when=lambda k, v: k == "update" and "projectId" in v["input"], fail_times=1)
    sync.put(ticket(body=QUIET))
    rec1, _ = night(sync, facts, "DECISION: ROUTE kipi-system\nREASON: fleet.")
    assert (rec1["outcome"], rec1["writes"]) == ("write-failed", [])
    rec2, _ = night(sync, facts, "DECISION: ROUTE kipi-system\nREASON: fleet.")
    assert rec2["outcome"] == "applied" and rec2["refused"] == []


def test_the_board_record_alone_is_enough_when_the_log_is_gone(facts):
    sync = FakeSync()
    sync.put(ticket(body=QUIET))
    night(sync, facts, "DECISION: CLOSE\nREASON: obsolete.")
    (decide.state_dir() / "decisions.jsonl").unlink()
    reopen(sync)
    night(sync, facts, "DECISION: CLOSE", "DECISION: CLOSE")
    assert len(writes_of(sync, "update", "stateId")) == 1


def test_a_record_past_the_comment_page_is_known_from_the_log(facts):
    """The board walk reads 50 comments. A record past them is not on the page
    this pass reads, and the log is what still knows."""
    def past_the_page(t):
        t["comments"] = {"nodes": [{"body": "chatter"}] * 3, "pageInfo": {"hasNextPage": True}}
    sync = FakeSync()
    sync.put(ticket(body=QUIET))
    night(sync, facts, "DECISION: CLOSE\nREASON: obsolete.")
    reopen(sync)
    night(sync, facts, "DECISION: CLOSE", "DECISION: CLOSE", mangle=past_the_page)
    assert len(writes_of(sync, "update", "stateId")) == 1


def test_when_every_write_was_undone_the_model_is_not_asked_and_nothing_is_written(facts):
    records = [decide.decision_comment({"kind": "CLOSE", "reason": "x"}),
               decide.decision_comment({"kind": "ROUTE", "project": "kipi-system", "reason": "x"}),
               decide.decision_comment({"kind": "ROUTE", "project": "ASK Consulting", "reason": "x"})]
    sync = FakeSync()
    sync.put(ticket(body=QUIET, comments=records))
    rec, ask = night(sync, facts, "DECISION: ROUTE kipi-system")
    assert (rec["outcome"], ask.prompts, sync.writes) == (decide.NOTHING_LEFT, [], [])
    assert decide.failed_before() == {"ASK-7"}


def test_the_write_chokepoint_refuses_an_undone_write_without_the_parse(facts):
    sync = FakeSync()
    board = decide.Board(sync, "team-1")
    with pytest.raises(decide.WriteFailed):
        decide.apply_decision(board, ticket(), {"kind": "CLOSE", "reason": "r"}, {decide.CLOSE_KEY})
    with pytest.raises(decide.WriteFailed):
        decide.apply_decision(board, ticket(), {"kind": "ROUTE", "project": "kipi-system"},
                              {decide.project_key("kipi-system")})
    assert sync.writes == []


@pytest.mark.parametrize("d", [{"kind": "CLOSE", "reason": "r"},
                               {"kind": "ROUTE", "project": "ASK Consulting", "reason": "r"},
                               {"kind": "SPLIT", "project": "kipi-system", "reason": "r",
                                "children": [{"project": "kipi-system", "title": "a", "outcome": "b"},
                                             {"project": "ASK Consulting", "title": "c", "outcome": "d"}]}])
def test_the_record_names_its_write_so_a_later_night_reads_it_back(d):
    """The board half of undone(): each record's first line round-trips to the
    write it made, a project name with a space included."""
    t = ticket(comments=[decide.decision_comment(d)])
    assert decide.undone(t, {}) == {decide.write_key(d)}


def test_this_pass_has_no_path_that_files_a_ticket():
    """ASK-4133: the create path is gone, not guarded. A later edit that brings
    one back has to delete this test in the open."""
    src = (SCRIPTS / "linear-route-decide.py").read_text()
    assert "issueCreate" not in src and "parentId" not in src


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
