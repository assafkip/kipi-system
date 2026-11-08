#!/usr/bin/env python3
"""A Done ticket the worker held as NOT done goes back to Backlog (ASK-4020).

RED FIRST. The ASK-297 shape, with its real 2026-11-08 timestamps: PR linked
17:48:04Z, needs-scope added 17:48:26Z, merged 17:48:31Z, Done 17:48:33Z. On main
nothing reads it, so it stays Done and the case fails on behaviour.

NEGATIVE SELF-TESTS: a stale hold (added before the PR was linked, no NOT done
after it) stays Done; a NOT done superseded by a later run stays Done; a merge this
job already acted on stays Done; a refused state move writes no comment.

NEVER A LIVE PATH. The pure half and a fake transport; --apply refuses under pytest.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
QDIR = HERE.parent
SCRIPTS = QDIR / "scripts"
PATH = SCRIPTS / "linear-not-done-reopen.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load("not_done_reopen_under_test", PATH) if PATH.exists() else None
needs = pytest.mark.skipif(mod is None, reason="linear-not-done-reopen.py not on this tree")

PR = "https://github.com/assafkip/example-client/pull/20"
LID = "090411f4-a01b-43c7-a14a-29667ecd73d5"


def ask297(*, label_added="2026-11-08T17:48:26.931Z", state="completed", comments=(),
           labels=(("needs-scope", LID), ("owner:sana", "o1")), merged=True):
    meta = {"status": "merged" if merged else "open", "branch": "sana/ask-297",
            "mergedAt": "2026-11-08T17:48:31.000Z"}
    return {"id": "uuid-297", "identifier": "ASK-297", "state": {"type": state},
            "labels": {"nodes": [{"name": n, "id": i} for n, i in labels]},
            "attachments": {"nodes": [{"url": PR, "createdAt": "2026-11-08T17:48:04.475Z",
                                       "metadata": meta}]},
            "history": {"nodes": [{"createdAt": label_added, "addedLabelIds": [LID]},
                                  {"createdAt": "2026-11-08T17:48:33.570Z", "addedLabelIds": None}]},
            "comments": {"nodes": [{"body": b} for b in comments], "pageInfo": {"hasNextPage": False}}}


# --- red first ----------------------------------------------------------------------

def test_the_ask_297_shape_goes_back_to_backlog():
    assert mod is not None, "linear-not-done-reopen.py does not exist: ASK-297 stays Done with half its work open"
    d = mod.decide(ask297(), {})
    assert d["reopen"] and d["label"] == "needs-scope" and d["merge"]["url"] == PR


@needs
def test_the_window_is_the_pr_link_not_the_merge():
    """The label landed 4s BEFORE the merge. The DoR's "after the merge" rule misses it."""
    d = mod.decide(ask297(), {})
    assert d["reopen"] and "after the PR was linked" in d["why"]


# --- negative self-tests --------------------------------------------------------------

@needs
def test_a_stale_hold_from_before_the_pr_stays_done():
    d = mod.decide(ask297(label_added="2026-10-19T16:08:50.523Z"), {})
    assert not d["reopen"] and "stale hold" in d["why"]


LOG = [
    "2026-11-08T17:30:00Z start ASK-297 on sana/ask-297 in /t (attempt 1/3)",
    "2026-11-08T17:53:38Z ASK-297 is NOT done: held at needs-scope. Any PR above carries only the half",
    "2026-11-08T17:53:38Z ASK-297 is NOT done: held at needs-scope. Any PR above carries only the half",
]


@needs
def test_a_logged_not_done_after_the_pr_reopens_even_with_a_stale_label():
    """Measured: ASK-1739, ASK-894, ASK-3072 had the label land before the PR link."""
    d = mod.decide(ask297(label_added="2026-11-08T17:40:00Z"), mod.read_log(LOG))
    assert d["reopen"] and "logged NOT done" in d["why"]


@needs
def test_a_not_done_superseded_by_a_later_run_stays_done():
    log = mod.read_log(LOG + ["2026-11-08T19:00:00Z start ASK-297 on sana/ask-297 in /t (attempt 2/3)"])
    d = mod.decide(ask297(label_added="2026-11-08T17:40:00Z"), log)
    assert not d["reopen"]


@needs
def test_a_not_done_from_before_the_pr_stays_done():
    log = mod.read_log(["2026-11-08T17:00:00Z ASK-297 is NOT done: held at needs-scope."])
    d = mod.decide(ask297(label_added="2026-11-08T17:40:00Z"), log)
    assert not d["reopen"]


@needs
def test_a_merge_this_job_already_acted_on_stays_done():
    d = mod.decide(ask297(comments=[f"<!-- {mod.MARKER}: {PR} -->\nBack to Backlog"]), {})
    assert not d["reopen"] and "respected" in d["why"]


@needs
@pytest.mark.parametrize("issue,why", [
    (ask297(state="started"), "not completed"),
    (ask297(merged=False), "no merged PR"),
    (ask297(labels=(("owner:sana", "o1"),)), "no hold label"),
])
def test_other_shapes_stay(issue, why):
    d = mod.decide(issue, {})
    assert not d["reopen"] and why in d["why"]


@needs
def test_the_log_is_read_once_per_line_shape():
    log = mod.read_log(LOG + ["garbage line", "2026-11-08T18:00:00Z worker: something else"])
    assert len(log["ASK-297"]["not_done"]) == 2 and len(log["ASK-297"]["start"]) == 1


# --- the comment ------------------------------------------------------------------------

@needs
@pytest.mark.parametrize("label,named", [
    ("needs-scope", "linear-dor-drafter.py"),
    ("blocked:capability", "ASK-3960"),
    (None, "com.kipi.dispatch"),
])
def test_the_comment_names_the_next_consumer(label, named):
    d = mod.decide(ask297(), {})
    d["label"] = label
    body = mod.reopen_comment(d)
    assert body.startswith(f"<!-- {mod.MARKER}: {PR} -->") and named in body
    banned = ("someone", "a human", "a person", "manual", "operator")
    assert not [w for w in banned if w in body.lower()]


# --- the write path -----------------------------------------------------------------------

class Fake:
    def __init__(self, state_ok=True, comment_ok=True):
        self.calls, self.state_ok, self.comment_ok = [], state_ok, comment_ok

    def graphql(self, q, v):
        if "issueUpdate" in q:
            self.calls.append(("state", v["input"]["stateId"]))
            return {"issueUpdate": {"success": self.state_ok}}
        if "commentCreate" in q:
            self.calls.append(("comment", v["input"]["body"][:30]))
            return {"commentCreate": {"success": self.comment_ok}}
        raise AssertionError(q[:50])


@needs
def test_state_moves_first_then_one_comment():
    f = Fake()
    assert mod.apply_one(f, ask297(), mod.decide(ask297(), {}), "BACKLOG") == "reopened"
    assert [c[0] for c in f.calls] == ["state", "comment"] and f.calls[0][1] == "BACKLOG"


@needs
def test_a_refused_state_move_writes_no_comment():
    """A marker on a ticket that never moved would make every later run skip it."""
    f = Fake(state_ok=False)
    with pytest.raises(RuntimeError):
        mod.apply_one(f, ask297(), mod.decide(ask297(), {}), "BACKLOG")
    assert [c[0] for c in f.calls] == ["state"]


@needs
def test_refuses_apply_under_pytest():
    assert mod.main(["--apply"]) == mod.EXIT_REFUSED_FIXTURE


# --- the wiring ------------------------------------------------------------------------------

@needs
def test_the_job_runs_hourly_from_a_pinned_tree():
    """Pinned: it reads Linear and the worker log under ~/.config/kipi, never the registry."""
    import plistlib
    raw = (SCRIPTS / "com.kipi.linear-not-done-reopen.plist").read_text()
    assert "q-system/.q-system/scripts/linear-not-done-reopen.py --apply" in raw
    rendered = plistlib.loads(raw.replace("__KIPI_REPO__", "/r").replace("__HOME__", "/h").encode())
    assert rendered["StartInterval"] == 3600
    assert "instance-registry" not in PATH.read_text() and "linear_registry" not in PATH.read_text()
    table = json.loads((QDIR / "job-checkouts.json").read_text())
    assert "com.kipi.linear-not-done-reopen" in table["pinned"]
