#!/usr/bin/env python3
"""Pins alert-to-linear.py: the flood collapses, and a test can never file live.

Every message string below is a REAL line copied out of #general on 2026-08-10,
the day the founder said "I dont want to see any of these." The fixtures are the
evidence, not an invention -- an invented fixture would let the dedup pass here
and still flood Linear on the first real run.
"""
import importlib.util
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

    def linear_api_key(self):
        return "stub"

    def graphql(self, query, variables):
        self.calls.append(query)
        if "teams(filter" in query:
            return {"teams": {"nodes": [{"id": "team-1", "key": "ASK"}]}}
        if "labels(first" in query:
            return {"team": {"labels": {"nodes": [
                {"id": "lab-1", "name": "owner:sana"}]}}}
        if "issueCreate" in query:
            self.created += 1
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


def test_the_punctuation_strip_did_not_collapse_everything():
    """Re-guards the negative case at the new, more aggressive normalization."""
    distinct = [
        "[a] auto-commit left 2 file(s) uncommitted",
        "[a] SECURITY: unsanctioned .claude/ change",
        "[a] Meeting loop could not run: NOTION_TOKEN_ASK missing",
        "[a] huntkit sync BLOCKED: not a git repo",
    ]
    assert len({mod.fingerprint(m) for m in distinct}) == len(distinct)
