#!/usr/bin/env python3
"""Pins alert-to-linear.py: the flood collapses, and a test can never file live.

Every message string below is a REAL line copied out of #general on 2026-08-10,
the day the founder said "I dont want to see any of these." The fixtures are the
evidence, not an invention -- an invented fixture would let the dedup pass here
and still flood Linear on the first real run.
"""
import importlib.util
import json
import os
import sys
import time

import pytest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")


def _load():
    path = os.path.join(SCRIPTS, "alert-to-linear.py")
    spec = importlib.util.spec_from_file_location("alert_to_linear", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


# --- the 51 auto-commit messages are ONE alert -------------------------------

AUTOCOMMIT = [
    "[consulting] auto-commit left 3 file(s) uncommitted in consulting: .prd-os/issues/lane-h-presented-is-not-contacted.md, .prd-os/judgments-tip.json, q-consult/pipeline/tests/test_hiring_harvest.py [2026-08-10 14:06:41 PDT]",
    "[consulting] auto-commit left 2 file(s) uncommitted in consulting: .prd-os/issues/lane-h-presented-is-not-contacted.md, .prd-os/judgments-tip.json [2026-08-10 13:45:18 PDT]",
    "[consulting] auto-commit left 6 file(s) uncommitted in consulting: .prd-os/issues/lane-h-presented-is-not-contacted.md, .prd-os/judgments-tip.json, q-consult/pipeline/apify_sync.py (+3 more) [2026-08-10 13:44:41 PDT]",
    "[consulting] auto-commit left 9 file(s) uncommitted in consulting: .prd-os/issues/lane-h-presented-is-not-contacted.md, .prd-os/judgments-tip.json, q-consult/.q-system/apify-rules.md (+6 more) [2026-08-10 12:35:45 PDT]",
]

# The home directory is a PLACEHOLDER, and it has to stay one. This repo is
# public, and validate-separation.py's full skeleton sweep fails on the founder's
# real home prefix appearing anywhere under q-system/. What these two strings
# need to exercise is the SHAPE -- two path-shaped tokens that differ only by
# timestamp -- because fingerprint() scrubs any `\S*/\S*` token before hashing.
# The real username was never load-bearing; it was just what got pasted in.
#
# This comment does not spell that prefix out, and that is the point: the first
# version of it did, so the comment explaining the ban tripped the ban. A text
# rule that scans comments as well as code has to be written about the data
# class, never with a sample of the data.
CARVEOUT = [
    "[cole-gtm] Daily X tool post (2026-07-17): CARVE-OUT ACTIVE: /Users/founder/.config/kipi/cole.OFF is ON (the fleet is paused) but /Users/founder/.config/kipi/podcast-social.ON opts THIS lane back in. [2026-08-10 14:05:24 PDT]",
    "[cole-gtm] Daily X tool post (2026-07-17): CARVE-OUT ACTIVE: /Users/founder/.config/kipi/cole.OFF is ON (the fleet is paused) but /Users/founder/.config/kipi/podcast-social.ON opts THIS lane back in. [2026-08-10 13:48:02 PDT]",
]


def test_every_autocommit_message_shares_one_fingerprint():
    """51 tickets would be the same defect with a worse surface."""
    prints = {mod.fingerprint(m) for m in AUTOCOMMIT}
    assert len(prints) == 1, f"auto-commit split into {len(prints)} tickets"


def test_every_carveout_message_shares_one_fingerprint():
    prints = {mod.fingerprint(m) for m in CARVEOUT}
    assert len(prints) == 1, f"carve-out split into {len(prints)} tickets"


def test_different_alerts_do_not_collapse_together():
    """The negative self-test. A fingerprint that maps everything to one bucket
    would pass both tests above and silently swallow every real alert."""
    distinct = [
        AUTOCOMMIT[0],
        CARVEOUT[0],
        "[ask-317] SECURITY: unsanctioned .claude/ change -- 2 modified, 4 added, 0 removed",
        "[/] Meeting loop could not run: NOTION_TOKEN_ASK is not in the launchd environment.",
        "[example_instance] repo sync BLOCKED: /path/to/repo is not a git repo",
    ]
    prints = {mod.fingerprint(m) for m in distinct}
    assert len(prints) == len(distinct), "distinct alerts collapsed into one ticket"


def test_security_alerts_naming_different_files_stay_one_ticket():
    """Same condition, different file list -> still one ticket."""
    a = "[ask-317] SECURITY: q-system/.q-system/scripts/claude-integrity-tripwire.py was deleted; restored from git"
    b = "[ask-317] SECURITY: q-system/.q-system/scripts/claude-path-write-guard.py was deleted; restored from git"
    assert mod.fingerprint(a) == mod.fingerprint(b)


# --- the guard that matters most ---------------------------------------------

def test_pytest_can_never_file_a_real_ticket():
    """PYTEST_CURRENT_TEST is set by pytest itself for every test, so this holds
    for tests nobody has written yet. That is the point: the 2026-08-01 scar was
    a test paging the founder from a branch that carried no stub."""
    assert os.environ.get("PYTEST_CURRENT_TEST"), "pytest must set its own marker"
    rc = mod.main(["alert-to-linear.py", AUTOCOMMIT[0]])
    assert rc == mod.EXIT_REFUSED_FIXTURE


def test_empty_message_is_a_no_op():
    assert mod.main(["alert-to-linear.py", ""]) == mod.EXIT_OK
    assert mod.main(["alert-to-linear.py"]) == mod.EXIT_OK


# --- dedup behaviour against a stubbed Linear --------------------------------

class FakeLinear:
    """Records calls. Stands in for linear-sync.py's module surface."""

    def __init__(self, state_type="unstarted"):
        self.calls = []
        self.state_type = state_type
        self.created = 0
        self.comments = 0
        # The payload the last issueCreate actually sent. ASK-839 is a defect in
        # a FIELD OF THE PAYLOAD, so the fixture has to keep the payload; a test
        # that only reads the returned identifier cannot see the field at all.
        self.create_input = None
        self.projects = [{"id": "proj-kipi", "name": "kipi-system",
                          "description": ""}]

    def linear_api_key(self):
        return "stub"

    def graphql(self, query, variables):
        self.calls.append(query)
        if "teams(filter" in query:
            return {"teams": {"nodes": [{"id": "team-1", "key": "ASK"}]}}
        if "labels(first" in query:
            return {"team": {"labels": {"nodes": [
                {"id": "lab-1", "name": "owner:sana"}]}}}
        if "projects(first" in query:
            return {"team": {"projects": {"nodes": self.projects}}}
        if "issueCreate" in query:
            self.created += 1
            self.create_input = variables["input"]
            return {"issueCreate": {"success": True, "issue": {
                "id": f"iss-{self.created}", "identifier": f"ASK-{100 + self.created}",
                "url": "https://linear.app/x"}}}
        if "issue(id" in query:
            return {"issue": {"id": "iss-1", "identifier": "ASK-101",
                              "url": "https://linear.app/x",
                              "state": {"type": self.state_type}}}
        if "commentCreate" in query:
            self.comments += 1
            return {"commentCreate": {"success": True}}
        return {}


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_state_dir", lambda: str(tmp_path))
    return tmp_path


def test_repeat_updates_one_ticket_instead_of_creating_more(isolated_state, monkeypatch):
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)

    code, line = mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    assert code == mod.EXIT_OK and "filed ASK-101" in line
    assert fake.created == 1

    # Same shape, different file list and count. Must NOT create a second ticket.
    for msg in AUTOCOMMIT[1:]:
        code, line = mod.file_alert(msg, now=1001.0)
        assert code == mod.EXIT_OK
    assert fake.created == 1, "a repeating alert opened more than one ticket"
    assert "repeat #4" in line


def test_repeat_inside_the_window_counts_without_commenting(isolated_state, monkeypatch):
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    mod.file_alert(AUTOCOMMIT[1], now=1000.0 + 60)
    assert fake.comments == 0, "commented on a repeat inside the quiet window"


def test_repeat_after_the_window_comments_once(isolated_state, monkeypatch):
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    later = 1000.0 + mod.REPEAT_COMMENT_AFTER_HOURS * 3600 + 1
    code, line = mod.file_alert(AUTOCOMMIT[1], now=later)
    assert fake.comments == 1 and "commented" in line


def test_recurrence_after_close_opens_a_fresh_ticket(isolated_state, monkeypatch):
    """Reopening a closed ticket would hide the recurrence, which is the signal."""
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    fake.state_type = "completed"
    code, line = mod.file_alert(AUTOCOMMIT[1], now=2000.0)
    assert code == mod.EXIT_OK and fake.created == 2, "closed ticket was not re-raised"


def test_missing_key_is_reported_not_swallowed(isolated_state, monkeypatch):
    class NoKey(FakeLinear):
        def linear_api_key(self):
            raise RuntimeError("no Linear API key")

    monkeypatch.setattr(mod, "_load_linear", lambda: NoKey())
    code, line = mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    assert code == mod.EXIT_NO_KEY
    assert AUTOCOMMIT[0] in line, "the undelivered message must stay readable"


def test_create_failure_preserves_the_message(isolated_state, monkeypatch):
    class Broken(FakeLinear):
        def graphql(self, query, variables):
            if "issueCreate" in query:
                raise RuntimeError("HTTP 500")
            return FakeLinear.graphql(self, query, variables)

    monkeypatch.setattr(mod, "_load_linear", lambda: Broken())
    code, line = mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    assert code == mod.EXIT_FAILED and AUTOCOMMIT[0] in line


def test_label_failure_still_files_the_ticket(isolated_state, monkeypatch):
    """A missing label must never cost the alert."""
    class NoLabels(FakeLinear):
        def graphql(self, query, variables):
            if "labels(first" in query or "issueLabelCreate" in query:
                raise RuntimeError("no label perms")
            return FakeLinear.graphql(self, query, variables)

    monkeypatch.setattr(mod, "_load_linear", lambda: NoLabels())
    code, _ = mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    assert code == mod.EXIT_OK and _  # filed anyway


def test_title_is_one_bounded_line():
    long_msg = "[x] " + ("word " * 80)
    title = mod.title_for(long_msg)
    assert "\n" not in title and len(title) <= 113


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# --- the live-check regression -----------------------------------------------

def test_bare_filenames_without_a_directory_still_collapse():
    """Found by a LIVE check, not by this suite, which is the point of keeping it.

    Every fixture above names paths with slashes, and the path rule is greedy
    enough to swallow a trailing comma with the token. So separator residue was
    invisible here and split real tickets: with two files the ", " survived,
    with one file it did not, and one condition opened two tickets."""
    a = "[consulting] auto-commit left 3 file(s) uncommitted in consulting: a.md, b.json"
    b = "[consulting] auto-commit left 9 file(s) uncommitted in consulting: c.py (+6 more)"
    assert mod.fingerprint(a) == mod.fingerprint(b)


def test_punctuation_alone_never_decides_a_ticket():
    """Trailing punctuation, quoting and separators are formatting, not identity."""
    base = "[x] huntkit sync BLOCKED: not a git repo"
    for variant in (base + ".", base + "!", base.replace(":", " --"),
                    base.replace("BLOCKED:", "BLOCKED --"), '"' + base + '"'):
        assert mod.fingerprint(variant) == mod.fingerprint(base), variant


# --- ASK-839: every filed ticket carries a project ---------------------------
#
# THE DEFECT. issueCreate was built with teamId + labelIds and no projectId, so
# every alert landed project-unset. Measured against the live board 2026-08-15:
# 81 open alert tickets, all unset; the DoR drafter had already promoted 19 of
# them into ready-shaped work, and an unset project cannot route to any checkout,
# so those 19 were 43% of the worker's permanently-UNREACHABLE bucket.
#
# Asserted on the PAYLOAD, not on the returned identifier. The old fixture read
# only the identifier back, which is why a suite of 15 cases could not see a
# missing field in the input it never inspected.

def test_a_filed_ticket_carries_the_project_of_the_alerting_repo(isolated_state, monkeypatch, tmp_path):
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    repo = tmp_path / "some-checkout"
    repo.mkdir()
    reg = tmp_path / "instance-registry.json"
    reg.write_text(json.dumps([{"name": "kipi-system", "path": str(repo)}]))
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY", str(reg))
    monkeypatch.setenv("KIPI_ALERT_REPO_PATH", str(repo))

    code, _ = mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    assert code == mod.EXIT_OK
    assert fake.create_input.get("projectId") == "proj-kipi", (
        "the ticket was filed with no project, so no checkout can ever route it")


def test_the_registry_alias_decides_the_project_not_the_directory_name(
        isolated_state, monkeypatch, tmp_path):
    """A registry row's board name and its directory routinely differ (ASK-840).

    Measured on the live board: of 81 unset alert tickets, only 33 carried a
    `[label]` prefix that is an exact project name. `consulting` lives on the
    board as another name entirely, so deriving from the directory would file
    those into nothing."""
    fake = FakeLinear()
    fake.projects = [{"id": "proj-cons", "name": "ASK Consulting", "description": ""}]
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    repo = tmp_path / "consulting"
    repo.mkdir()
    reg = tmp_path / "instance-registry.json"
    reg.write_text(json.dumps(
        [{"name": "consulting", "linear_project": "ASK Consulting", "path": str(repo)}]))
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY", str(reg))
    monkeypatch.setenv("KIPI_ALERT_REPO_PATH", str(repo))

    mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    assert fake.create_input.get("projectId") == "proj-cons"


def test_an_unresolvable_repo_still_gets_a_project_and_still_files(
        isolated_state, monkeypatch, tmp_path):
    """22 of the 81 were raised from a cwd of `/` with no repo at all.

    They must not go back to being unset, and they must never be dropped: losing
    an alert is the failure this whole path exists to prevent. The fallback is
    the checkout this script itself runs from, which is a derivation, not a guess.
    """
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    reg = tmp_path / "instance-registry.json"
    reg.write_text(json.dumps([]))
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY", str(reg))
    monkeypatch.delenv("KIPI_ALERT_REPO_PATH", raising=False)
    monkeypatch.setenv("KIPI_ALERT_FALLBACK_PROJECT", "kipi-system")

    code, _ = mod.file_alert("[/] Meeting loop could not run: token missing", now=1000.0)
    assert code == mod.EXIT_OK
    assert fake.create_input.get("projectId") == "proj-kipi"


def test_a_broken_project_lookup_never_costs_the_alert(isolated_state, monkeypatch):
    """Same posture as the label: a ticket with no project is worth far more than
    a dropped alert, so a lookup failure degrades rather than raises."""
    class NoProjects(FakeLinear):
        def graphql(self, query, variables):
            if "projects(first" in query:
                raise RuntimeError("no project read perms")
            return FakeLinear.graphql(self, query, variables)

    fake = NoProjects()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    code, _ = mod.file_alert(AUTOCOMMIT[0], now=1000.0)
    assert code == mod.EXIT_OK and fake.created == 1


# --- the skeleton is a registry row too (ASK-839, PR #191 review round 3) ----
#
# `_registry_rows()` read only `reg["instances"]`, and the skeleton -- the
# checkout this script itself lives in and the single biggest alert producer on
# the board -- is NOT an instances row. It is the registry's own top-level
# `skeleton` key. So the skeleton was absent from the rows that rung 2 (repo
# path) and rung 5 (own checkout) both search, and both rungs were dead for it.
#
# Measured on the live board 2026-08-15, 82 open alert tickets: 22 carry the
# label `/` (a cwd with no repo, so no path is exported and no label resolves --
# rung 5 is their ONLY cover) and 18 carry a kipi-system worktree directory
# (`.wt-ask791`, `kipi-wt-ask729`, `cleanmain`, `dispatch-checkout`, ...), whose
# --git-common-dir path is the skeleton -- rung 2. 40 of 82 had no live rung at
# all.
#
# The registry fixture below carries the REAL file's shape, top-level `skeleton`
# alongside `instances`, because that shape IS the defect. A fixture shaped as a
# bare list -- which is what every earlier case in this file uses -- cannot see
# it, which is how a 21-case suite stayed green over a dead production path.

SKELETON_REGISTRY_SHAPE = {
    "skeleton": {"path": "/tmp/skel", "remote": "https://example.invalid/x.git",
                 "linear_project": "kipi-system"},
    "instances": [{"name": "consulting", "linear_project": "ASK Consulting",
                   "path": "/tmp/consulting"}],
}


def _registry_with_skeleton(tmp_path, skel_path, **skel_extra):
    reg = tmp_path / "instance-registry.json"
    body = json.loads(json.dumps(SKELETON_REGISTRY_SHAPE))
    body["skeleton"]["path"] = str(skel_path)
    body["skeleton"].update(skel_extra)
    reg.write_text(json.dumps(body))
    return reg


def test_the_skeleton_is_one_of_the_registry_rows(monkeypatch, tmp_path):
    """Rungs 2 and 5 both search `_registry_rows()`. A skeleton missing from that
    list is a skeleton neither rung can ever resolve."""
    reg = _registry_with_skeleton(tmp_path, tmp_path / "skel")
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY", str(reg))

    paths = {r.get("path") for r in mod._registry_rows()}
    assert str(tmp_path / "skel") in paths, (
        "the skeleton is absent from the rows, so an alert raised from it "
        "resolves to no project at all")


def test_an_alert_raised_from_the_skeleton_carries_the_skeleton_project(
        isolated_state, monkeypatch, tmp_path):
    """Rung 2, for the 18 worktree-labelled tickets.

    slack-notify.sh exports --git-common-dir, so a worktree alert arrives with
    the SKELETON path and a label (`.wt-ask791`) that names no project. Rung 2 is
    the whole answer for that shape."""
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    skel = tmp_path / "kipi-system"
    skel.mkdir()
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY",
                       str(_registry_with_skeleton(tmp_path, skel)))
    monkeypatch.setenv("KIPI_ALERT_REPO_PATH", str(skel))
    monkeypatch.delenv("KIPI_ALERT_FALLBACK_PROJECT", raising=False)

    code, _ = mod.file_alert(
        "[.wt-ask791] auto-commit left 3 file(s) uncommitted", now=1000.0)
    assert code == mod.EXIT_OK
    assert fake.create_input.get("projectId") == "proj-kipi"


def test_the_last_resort_rung_works_without_an_env_production_never_sets(
        isolated_state, monkeypatch, tmp_path):
    """Rung 5, for the 22 `[/]` tickets.

    The existing `[/]` case sets KIPI_ALERT_FALLBACK_PROJECT by hand, and NOTHING
    in this repo sets it -- grep finds one reader and no writer. So that case was
    passing on an invented fixture while the rung it claims to cover returned "".
    This one removes the env and leaves rung 5 to do the work it documents."""
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    # Through _common_repo_root, so this case reads the same root the rung does
    # whether the suite runs in the skeleton or in a worktree of it. Hardcoding
    # SCRIPTS/../../.. passed only in the skeleton and is a false RED elsewhere.
    own_root = os.path.realpath(mod._common_repo_root(mod._own_checkout_root()))
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY",
                       str(_registry_with_skeleton(tmp_path, own_root)))
    monkeypatch.delenv("KIPI_ALERT_REPO_PATH", raising=False)
    monkeypatch.delenv("KIPI_ALERT_FALLBACK_PROJECT", raising=False)

    code, _ = mod.file_alert("[/] Meeting loop could not run: token missing",
                             now=1000.0)
    assert code == mod.EXIT_OK
    assert fake.create_input.get("projectId") == "proj-kipi"


def test_a_skeleton_row_with_no_alias_offers_nothing_rather_than_a_guess(
        monkeypatch, tmp_path):
    """The negative self-test. Including the skeleton row must not smuggle in a
    basename derivation -- that is the ASK-840 defect this file's own docstring
    refuses. A skeleton with no `linear_project` contributes no candidate."""
    reg = tmp_path / "instance-registry.json"
    reg.write_text(json.dumps({
        "skeleton": {"path": str(tmp_path / "kipi-system"),
                     "remote": "https://example.invalid/x.git"},
        "instances": []}))
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY", str(reg))
    monkeypatch.setenv("KIPI_ALERT_REPO_PATH", str(tmp_path / "kipi-system"))
    monkeypatch.delenv("KIPI_ALERT_PROJECT", raising=False)
    monkeypatch.delenv("KIPI_ALERT_FALLBACK_PROJECT", raising=False)

    assert "kipi-system" not in mod.project_candidates("[x] something broke")


def test_rung_five_survives_running_out_of_a_worktree(
        isolated_state, monkeypatch, tmp_path):
    """A worktree is never its own registry row, and the fleet's agents all run
    in one -- 18 of the 82 live alert tickets are labelled with a worktree
    directory. The last-resort rung has to reach the common repo root, the same
    fact slack-notify.sh resolves with --git-common-dir, or it is dead in exactly
    the checkouts that raise the most alerts."""
    fake = FakeLinear()
    monkeypatch.setattr(mod, "_load_linear", lambda: fake)
    skel = tmp_path / "kipi-system"
    (skel / ".git" / "worktrees" / "wt").mkdir(parents=True)
    wt = tmp_path / "wt-ask999"
    wt.mkdir()
    # The real shape git writes for a linked worktree: .git is a FILE naming the
    # common dir, and the common dir's parent is the skeleton.
    (wt / ".git").write_text(f"gitdir: {skel}/.git/worktrees/wt\n")
    monkeypatch.setenv("KIPI_INSTANCE_REGISTRY",
                       str(_registry_with_skeleton(tmp_path, skel)))
    monkeypatch.setattr(mod, "_own_checkout_root", lambda: str(wt))
    monkeypatch.delenv("KIPI_ALERT_REPO_PATH", raising=False)
    monkeypatch.delenv("KIPI_ALERT_FALLBACK_PROJECT", raising=False)

    code, _ = mod.file_alert("[/] Meeting loop could not run: token missing",
                             now=1000.0)
    assert code == mod.EXIT_OK
    assert fake.create_input.get("projectId") == "proj-kipi"


def test_the_shipped_registry_states_its_own_board_name(monkeypatch):
    """The data half, which the code half cannot supply.

    The board alias is a FIELD, never derived (ASK-840), so the skeleton row has
    to carry one or the rung stays dead with the code correct. Reading the real
    file on purpose: a fixture would pass while the shipped registry drifted.

    Asserted on the SKELETON row, not on "the checkout this test runs from" --
    the first draft did the latter and it is false by construction in a worktree,
    which is where the fleet's agents run."""
    monkeypatch.delenv("KIPI_INSTANCE_REGISTRY", raising=False)
    skel = [r for r in mod._registry_rows() if r.get("is_skeleton")]
    assert skel, "the shipped registry contributes no skeleton row"
    assert mod._linear_project_of(skel[0]), (
        "the skeleton row names no board project, so rungs 2 and 5 resolve "
        "nothing for the checkout this script lives in")


def test_the_punctuation_strip_did_not_collapse_everything():
    """Re-guards the negative case at the new, more aggressive normalization."""
    distinct = [
        "[a] auto-commit left 2 file(s) uncommitted",
        "[a] SECURITY: unsanctioned .claude/ change",
        "[a] Meeting loop could not run: NOTION_TOKEN_ASK missing",
        "[a] huntkit sync BLOCKED: not a git repo",
    ]
    assert len({mod.fingerprint(m) for m in distinct}) == len(distinct)
