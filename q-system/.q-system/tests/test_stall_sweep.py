#!/usr/bin/env python3
"""Every work item idle 24h names its next consumer, or the sweep turns red (ASK-4019).

RED FIRST. On main stall-sweep.py does not exist, so the first case, a ticket idle
25 hours with no consumer, is reported by nothing: the case fails on behaviour.

NEGATIVE SELF-TESTS (the DoR's): the same ticket with a registry consumer is green;
a 23-hour ticket is not listed; a second run files no second ticket. Added here: an
unchanged set is not rewritten as its hours tick; a failed started read is never a
gap; a Canceled gap ticket is respected; the new-ticket cap holds.

NEVER A LIVE PATH. The pure half, plus a fake transport. --apply refuses under
pytest, and test_refuses_apply_under_pytest proves the rail is real.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

HERE = pathlib.Path(__file__).resolve().parent
QDIR = HERE.parent
SCRIPTS = QDIR / "scripts"
SWEEP_PATH = SCRIPTS / "stall-sweep.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sweep = _load("stall_sweep_under_test", SWEEP_PATH) if SWEEP_PATH.exists() else None
needs_sweep = pytest.mark.skipif(sweep is None, reason="stall-sweep.py not on this tree")

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
DOR = "## Definition of Ready\n\n* **Outcome:** x.\n"
HOLD = json.loads((QDIR / "hold-label-consumers.json").read_text())["labels"]


def ago(hours):
    return (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def ticket(ident="ASK-9001", *, hours=25, labels=("owner:sana",), project="kipi-system",
           state="unstarted", desc=DOR):
    return {"id": f"uuid-{ident}", "identifier": ident, "title": "t", "description": desc,
            "updatedAt": ago(hours), "startedAt": ago(hours), "state": {"type": state},
            "project": ({"name": project} if project else None),
            "labels": {"nodes": [{"name": n} for n in labels]}}


def ctx(**over):
    base = {"rows": HOLD, "fleet": {"kipi-system", "brag", "ktlyst"}, "home": "kipi-system",
            "refusal": {"brag": "", "ktlyst": "preflight refuses: remote"}, "started": {}}
    base.update(over)
    return base


def pr(number=7, *, hours=25, repo="assafkip/brag"):
    return {"repo": repo, "number": number, "headRefName": "sana/ask-1", "createdAt": ago(400),
            "commits": [{"committedDate": ago(hours)}], "reviews": [], "statusCheckRollup": []}


# --- red first: an idle ticket nothing moves -----------------------------------

def test_an_idle_ticket_with_no_consumer_turns_the_sweep_red():
    """blocked:capability has no consumer (hold-label-consumers.json `missing`)."""
    assert sweep is not None, "stall-sweep.py does not exist: an idle unowned ticket is reported by nothing"
    p = sweep.plan([ticket(labels=("owner:sana", "blocked:capability"))], [], ctx(), NOW)
    assert p["status"] == "red"
    g = p["gaps"]["label-blocked-capability"]
    assert g["refs"] == ["ticket ASK-9001"] and g["builder"] == HOLD["blocked:capability"]["missing"]["ticket"]


@needs_sweep
def test_the_same_ticket_with_a_registry_consumer_is_green():
    p = sweep.plan([ticket(labels=("owner:sana", "needs-scope"))], [], ctx(), NOW)
    assert p["status"] == "green" and p["gaps"] == {}
    assert "linear-dor-drafter.py" in p["named"][0]


@needs_sweep
def test_a_23_hour_ticket_is_not_listed():
    p = sweep.plan([ticket(hours=23, labels=("owner:sana", "blocked:capability"))], [], ctx(), NOW)
    assert p["status"] == "green" and p["fresh"] == 1 and not p["named"]


# --- the consumer, in ready()'s order -------------------------------------------

@needs_sweep
@pytest.mark.parametrize("t,want", [
    (ticket(), ("consumer", "linear-worker.sh ready()")),
    (ticket(desc="plain"), ("consumer", "linear-dor-drafter.py")),
    (ticket(labels=()), ("consumer", "linear-owner-sweep.py")),
    (ticket(labels=("owner:assaf",)), ("gap", "label-owner-assaf")),
    (ticket(labels=("owner:cole",)), ("gap", "other-owner")),
    (ticket(project=None, desc="plain"), ("gap", "no-project")),
    (ticket(project=None), ("consumer", "linear-route.py")),
    (ticket(project="ktlyst"), ("gap", "unreachable-project")),
    (ticket(project="brag"), ("consumer", "linear-worker.sh ready()")),
    (ticket(desc="<!-- kipi-alert-fingerprint: ab -->"), ("consumer", "linear-alert-triage.py")),
    (ticket(desc="<!-- kipi-alert-fingerprint: ab -->", labels=("owner:sana", "triage:held")),
     ("gap", "label-triage-held")),
    (ticket(desc="<!-- kipi-alert-fingerprint: ab -->", project=None), ("gap", "alert-lane-refused")),
    (ticket(project="Chief"), ("skip", "chief rebuild")),
    (ticket(project="somewhere-else"), ("gap", "outside-fleet-project")),
])
def test_each_reason_names_its_consumer_or_its_gap(t, want):
    kind, val = sweep.classify_ticket(t, ctx())
    assert kind == want[0]
    text = val["reason"] if kind == "gap" else val
    assert want[1] in text


@needs_sweep
def test_the_home_project_is_never_preflighted():
    """The skeleton row pins no remote, so preflight would refuse it and mark all 87
    kipi-system Todo tickets unreachable. The worker never preflights its own repo."""
    assert sweep.classify_ticket(ticket(), ctx(refusal={}))[0] == "consumer"


@needs_sweep
@pytest.mark.parametrize("cls,want", [
    (("released", ""), ("consumer", "started_open")),
    (("claim", "a live claim by x"), ("consumer", "live worker run")),
    (("pr", "https://github.com/a/b/pull/1 on sana/ask-1"), ("consumer", "open PR")),
    (("history", "no worker history"), ("gap", "started-no-history")),
    (("held", "something new"), ("gap", "started-held")),
])
def test_a_started_ticket_follows_started_hold_reason(cls, want):
    c = ctx(started={"ASK-9001": cls})
    kind, val = sweep.classify_ticket(ticket(state="started"), c)
    assert kind == want[0]
    assert want[1] in (val["reason"] if kind == "gap" else val)


@needs_sweep
def test_a_started_ticket_that_was_not_read_is_never_a_gap():
    assert sweep.classify_ticket(ticket(state="started"), ctx(started={}))[0] == "skip"


@needs_sweep
def test_started_classes_read_by_equality_with_the_modules_own_answers():
    class S:
        def __init__(self, why): self.why = why
        def started_hold_reason(self, i, state_dir=""): return self.why
        def worker_history(self, d, ident): return "no worker history: x"
        def live_claim(self, d, ident): return "a live claim by y"
    t = [ticket(state="started")]
    assert sweep.started_classes(S(""), t, "/nowhere")["ASK-9001"][0] == "released"
    assert sweep.started_classes(S("no worker history: x"), t, "/nowhere")["ASK-9001"][0] == "history"
    assert sweep.started_classes(S("a live claim by y"), t, "/nowhere")["ASK-9001"][0] == "claim"
    assert sweep.started_classes(S("open PR u on b"), t, "/nowhere")["ASK-9001"] == ("pr", "u on b")
    assert sweep.started_classes(S("Linear gave no startedAt"), t, "/nowhere")["ASK-9001"][0] == "held"


# --- PRs ------------------------------------------------------------------------

@needs_sweep
def test_an_idle_pr_is_a_gap_and_a_fresh_signal_clears_it():
    assert sweep.plan([], [pr()], ctx(), NOW)["gaps"]["pr-no-owner"]["refs"] == ["PR assafkip/brag#7"]
    fresh_review = dict(pr(), reviews=[{"submittedAt": ago(2)}])
    fresh_check = dict(pr(), statusCheckRollup=[{"completedAt": ago(3)}])
    for p in (pr(hours=5), fresh_review, fresh_check):
        assert sweep.plan([], [p], ctx(), NOW)["status"] == "green"


@needs_sweep
def test_a_comment_is_not_progress():
    noisy = dict(pr(), comments=[{"createdAt": ago(1)}], updatedAt=ago(1))
    assert sweep.plan([], [noisy], ctx(), NOW)["status"] == "red"


@needs_sweep
def test_slugs_and_preflight_words():
    assert sweep.repo_slug("https://github.com/assafkip/brag.git") == "assafkip/brag"
    assert sweep.repo_slug("git@github.com:assafkip/kipi-system.git") == "assafkip/kipi-system"
    assert sweep.repo_slug("https://bitbucket.org/x/y.git") is None
    out = "PASS hooks\nFAIL remote: no pin\nFAIL credentials: no slug\n"
    assert sweep.preflight_refusal(1, out) == "preflight refuses: remote,credentials"
    assert sweep.preflight_refusal(0, out) == ""


@needs_sweep
def test_chief_is_not_listed():
    class R:
        def __call__(self, cmd, **kw):
            raise AssertionError("pinned remotes need no git call")
    facts = {"local_repos": [{"project": "brag", "path": "/x", "remote": "https://github.com/assafkip/brag.git"},
                             {"project": "chief", "path": "/y", "remote": "https://github.com/assafkip/chief.git"}]}
    assert sweep.fleet_repos(facts, run=R()) == (["assafkip/brag"], [])


# --- the archived engagement and pr-owner.py ----------------------------------------

@needs_sweep
def test_the_archived_engagement_is_skipped_not_a_gap():
    """RULE-2026-10-23-B. A gap ticket listing its work would steer an agent at it."""
    c = ctx(archived={"archived-x"}, fleet={"kipi-system", "archived-x"})
    kind, why = sweep.classify_ticket(ticket(project="archived-x"), c)
    assert kind == "skip" and "RULE-2026-10-23-B" in why


def _hook(tmp_path, monkeypatch, body):
    hooks = tmp_path / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "ps-archive-deny.sh").write_text(body)
    monkeypatch.setenv("HOME", str(tmp_path))


@needs_sweep
def test_the_hook_is_asked_and_its_deny_is_obeyed(tmp_path, monkeypatch):
    _hook(tmp_path, monkeypatch,
          'read -r x; case "$x" in *archived-x*) echo \'{"permissionDecision": "deny"}\';; esac\n')
    assert sweep.archived("/p/archived-x", "archived-x") is True
    assert sweep.archived("/p/brag", "brag") is False


@needs_sweep
def test_a_missing_hook_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(sweep.ArchiveGuardMissing):
        sweep.archived("/p/brag", "brag")


@needs_sweep
def test_an_archived_repo_is_never_listed():
    facts = {"local_repos": [{"project": "archived-x", "path": "/x", "remote": "https://github.com/a/x.git"},
                             {"project": "brag", "path": "/y", "remote": "https://github.com/assafkip/brag.git"}]}
    got = sweep.fleet_repos(facts, run=None, is_archived=lambda path, label: label == "archived-x")
    assert got == (["assafkip/brag"], [])


@needs_sweep
def test_a_pr_names_pr_owner_once_it_is_on_the_tree():
    assert sweep.classify_pr(pr(), None)[1]["reason"] == "pr-no-owner"
    assert "pr-owner.py" in sweep.classify_pr(pr(), {"assafkip/brag"})[1]
    assert sweep.classify_pr(pr(repo="assafkip/other"), {"assafkip/brag"})[1]["reason"] == "pr-outside-pr-owner"
    p = sweep.plan([], [pr()], ctx(pr_owned={"assafkip/brag"}), NOW)
    assert p["status"] == "green" and "pr-owner.py" in p["named"][0]


# --- the write path, against a fake transport ------------------------------------

class FakeSync:
    ISSUE_CREATE = "mutation($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { id identifier } } }"

    def __init__(self, *, keyed=(), builders=None, comment_ok=True):
        self.keyed = list(keyed)          # issues carrying a stall-sweep kipi-key
        self.builders = builders or {}    # identifier -> state type
        self.comments = {}                # identifier -> [{"id","body"}]
        self.created = []
        self.writes = []
        self.comment_ok = comment_ok
        self.n = 100

    def graphql(self, q, v):
        if "description:{contains" in q:
            return {"issues": {"nodes": [k for k in self.keyed if v["k"] in k["_desc"]]}}
        if "team(id:$t){labels" in q:
            return {"team": {"labels": {"nodes": [{"id": "L1", "name": "owner:sana"},
                                                   {"id": "L2", "name": "needs-triage"}]}}}
        if "projects(filter" in q:
            return {"projects": {"nodes": [{"id": "P1", "name": "kipi-system"}]}}
        if "issueCreate" in q:
            self.n += 1
            ident = f"ASK-{self.n}"
            self.created.append(v["input"])
            self.keyed.append({"id": ident, "identifier": ident, "state": {"type": "backlog"},
                               "createdAt": "z", "_desc": v["input"]["description"]})
            self.builders[ident] = "backlog"
            return {"issueCreate": {"success": True, "issue": {"id": ident, "identifier": ident}}}
        if "issue(id:$id)" in q:
            ident = v["id"]
            if ident not in self.builders:
                return {"issue": None}
            return {"issue": {"id": ident, "identifier": ident, "state": {"type": self.builders[ident]},
                              "comments": {"nodes": self.comments.get(ident, []),
                                           "pageInfo": {"hasNextPage": False}}}}
        if "commentCreate" in q:
            self.writes.append("create")
            self.comments.setdefault(v["input"]["issueId"], []).append(
                {"id": f"c{len(self.writes)}", "body": v["input"]["body"]})
            return {"commentCreate": {"success": self.comment_ok}}
        if "commentUpdate" in q:
            self.writes.append("update")
            for nodes in self.comments.values():
                for n in nodes:
                    if n["id"] == v["id"]:
                        n["body"] = v["input"]["body"]
            return {"commentUpdate": {"success": True}}
        raise AssertionError(f"unexpected query: {q[:60]}")


def run_apply(sync, plan_):
    budget = {"new": sweep.MAX_NEW_TICKETS, "comments": sweep.MAX_COMMENT_WRITES}
    ids, out = {}, {}
    for reason, g in sorted(plan_["gaps"].items()):
        t, how = sweep.gap_ticket(sync, "team", reason, g, budget, ids)
        out[reason] = (t, how, sweep.upsert_comment(sync, t, reason, g, budget) if t else "")
    return out


@needs_sweep
def test_a_second_run_files_no_second_ticket():
    fake = FakeSync()
    p = sweep.plan([ticket(labels=("owner:cole",))], [], ctx(), NOW)
    first = run_apply(fake, p)
    assert first["other-owner"][1] == "filed" and len(fake.created) == 1
    second = run_apply(fake, p)
    assert second["other-owner"][1] == "keyed" and len(fake.created) == 1
    assert second["other-owner"][2] == "unchanged"


@needs_sweep
def test_the_filed_ticket_is_marked_and_routed():
    fake = FakeSync()
    run_apply(fake, sweep.plan([ticket(labels=("owner:cole",))], [], ctx(), NOW))
    body = fake.created[0]
    assert "<!-- kipi-key: stall-sweep/other-owner -->" in body["description"]
    assert body["labelIds"] == ["L1", "L2"] and body["projectId"] == "P1"
    assert "linear-dor-drafter.py" in body["description"]


@needs_sweep
def test_an_unchanged_set_is_not_rewritten_as_its_hours_tick():
    fake = FakeSync()
    run_apply(fake, sweep.plan([ticket(labels=("owner:cole",))], [], ctx(), NOW))
    later = sweep.plan([ticket(hours=30, labels=("owner:cole",))], [], ctx(), NOW)
    assert run_apply(fake, later)["other-owner"][2] == "unchanged"
    assert fake.writes == ["create"]


@needs_sweep
def test_a_changed_set_rewrites_the_one_comment():
    fake = FakeSync()
    run_apply(fake, sweep.plan([ticket(labels=("owner:cole",))], [], ctx(), NOW))
    two = sweep.plan([ticket(labels=("owner:cole",)), ticket("ASK-9002", labels=("owner:cole",))],
                     [], ctx(), NOW)
    assert run_apply(fake, two)["other-owner"][2] == "comment written"
    assert fake.writes == ["create", "update"]
    assert len(fake.comments["ASK-101"]) == 1


@needs_sweep
def test_an_open_builder_gets_the_comment_and_nothing_is_filed():
    builder = HOLD["blocked:capability"]["missing"]["ticket"]
    fake = FakeSync(builders={builder: "backlog"})
    out = run_apply(fake, sweep.plan([ticket(labels=("owner:sana", "blocked:capability"))], [], ctx(), NOW))
    assert out["label-blocked-capability"][:2] == (builder, "builder") and not fake.created
    assert "ticket ASK-9001" in fake.comments[builder][0]["body"]


@needs_sweep
def test_a_closed_builder_hands_the_gap_to_a_filed_ticket():
    builder = HOLD["blocked:capability"]["missing"]["ticket"]
    fake = FakeSync(builders={builder: "completed"})
    out = run_apply(fake, sweep.plan([ticket(labels=("owner:sana", "blocked:capability"))], [], ctx(), NOW))
    assert out["label-blocked-capability"][1] == "filed"


@needs_sweep
def test_a_canceled_gap_ticket_is_respected():
    fake = FakeSync(keyed=[{"id": "x", "identifier": "ASK-50", "state": {"type": "canceled"},
                            "createdAt": "a", "_desc": "<!-- kipi-key: stall-sweep/other-owner -->"}])
    out = run_apply(fake, sweep.plan([ticket(labels=("owner:cole",))], [], ctx(), NOW))
    assert out["other-owner"][0] == "" and "declined" in out["other-owner"][1] and not fake.created


@needs_sweep
def test_the_new_ticket_cap_holds():
    fake = FakeSync()
    budget = {"new": 1, "comments": 9}
    g = {"builder": None, "what": "w", "items": ["x"], "refs": ["x"]}
    assert sweep.gap_ticket(fake, "t", "a", g, budget, {})[1] == "filed"
    assert "not filed" in sweep.gap_ticket(fake, "t", "b", g, budget, {})[1]


@needs_sweep
def test_a_key_is_never_a_prefix_of_another():
    fake = FakeSync(keyed=[{"id": "x", "identifier": "ASK-50", "state": {"type": "backlog"},
                            "createdAt": "a", "_desc": "<!-- kipi-key: stall-sweep/started-held-x -->"}])
    g = {"builder": None, "what": "w", "items": ["x"], "refs": ["x"]}
    assert sweep.gap_ticket(fake, "t", "started-held", g, {"new": 1, "comments": 1}, {})[1] == "filed"


@needs_sweep
def test_refuses_apply_under_pytest():
    assert sweep.main(["--apply"]) == sweep.EXIT_REFUSED_FIXTURE


# --- the wiring -------------------------------------------------------------------

@needs_sweep
def test_the_job_runs_hourly_from_the_shared_checkout():
    """Shared, not pinned: it reads instance-registry.json relative to its own tree,
    and origin's copy lags the shared one (PR #654 review, major; ASK-3967)."""
    import plistlib
    raw = (SCRIPTS / "com.kipi.stall-sweep.plist").read_text()
    assert "q-system/.q-system/scripts/stall-sweep.py --apply" in raw
    rendered = plistlib.loads(raw.replace("__KIPI_REPO__", "/r").replace("__HOME__", "/h").encode())
    assert rendered["StartInterval"] == 3600
    table = json.loads((QDIR / "job-checkouts.json").read_text())
    assert "com.kipi.stall-sweep" not in table["pinned"]
    exc = table["shared_exceptions"]["com.kipi.stall-sweep"]
    assert "instance-registry.json" in exc["reason"] and exc["ticket"] == "ASK-3967"


@needs_sweep
def test_every_named_builder_is_a_ticket_id():
    for reason, row in sweep.REASONS.items():
        assert row["builder"] is None or row["builder"].startswith("ASK-"), reason
        assert row["what"], reason
