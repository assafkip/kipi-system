#!/usr/bin/env python3
"""Pins the ONE property linear-alert-triage.py exists to create: after a
promotion, BOTH refusing readers accept the issue.

The readers are not reimplemented here. linear-worker.sh's is_fleet_alert lives
inside a bash heredoc and cannot be imported, so its Python text is EXTRACTED
FROM THE SHIPPED FILE and exec'd. A hand-written copy of that predicate would
pass this test forever while the real one drifted -- which is precisely the
"two substring tests in two places is how they drift" failure the drafter's own
docstring names.
"""
import importlib.util
import re
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


triage = _load("triage", "linear-alert-triage.py")
drafter = _load("drafter", "linear-dor-drafter.py")


def worker_is_fleet_alert():
    """is_fleet_alert, lifted verbatim out of linear-worker.sh."""
    src = (SCRIPTS / "linear-worker.sh").read_text(encoding="utf-8")
    m = re.search(r"^ALERT_MARKER = .*?^def is_fleet_alert\(i\):.*?^    return False$",
                  src, re.S | re.M)
    if not m:
        raise AssertionError(
            "could not locate is_fleet_alert in linear-worker.sh -- the extraction "
            "anchor moved, so this test is no longer reading the shipped predicate")
    ns = {}
    exec(compile(m.group(0), "linear-worker.sh:is_fleet_alert", "exec"), ns)
    return ns["is_fleet_alert"]


IS_FLEET_ALERT = worker_is_fleet_alert()

ALERT_DESC = (
    "Filed automatically by the fleet alert path.\n\n"
    "```\nmain is RED and the auto-merge lane is still live\n```\n\n"
    "<!-- kipi-alert-fingerprint: 6f1a2b3c4d5e -->"
)


def as_issue(desc, labels=("owner:sana", "needs-triage"), project="kipi-system"):
    return {"identifier": "ASK-9999", "description": desc,
            "state": {"type": "backlog"}, "project": {"name": project},
            "labels": {"nodes": [{"id": f"id-{n}", "name": n} for n in labels]}}


def worker_ready(issue):
    """ready() from linear-worker.sh, in its decisive part: the alert exclusion
    sits ABOVE the DoR test, which is why emitting a DoR from the filer is inert."""
    labels = {l["name"] for l in issue["labels"]["nodes"]}
    if "owner:assaf" in labels: return False
    if "owner:sana" not in labels: return False
    if "needs-scope" in labels: return False
    if issue["state"]["type"] not in ("backlog", "unstarted"): return False
    if IS_FLEET_ALERT(issue): return False
    d = issue.get("description") or ""
    return "## Definition of Ready" in d or "Definition of Ready" in d


DOR = "## Definition of Ready\n\n- Reproducer: `gh pr checks`\n- Done: main is green\n"


class TestPromotionUnblocksBothReaders(unittest.TestCase):

    def test_negative_self_test_alert_is_refused_by_both(self):
        """The bad case must be RED first, or nothing below proves anything."""
        self.assertTrue(IS_FLEET_ALERT(as_issue(ALERT_DESC)),
                        "worker predicate did not see the alert marker")
        self.assertTrue(drafter.is_alert_ticket(ALERT_DESC),
                        "drafter predicate did not see the alert marker")
        self.assertIsNone(drafter.selection_mode(as_issue(ALERT_DESC)),
                          "drafter would have drafted an alert ticket")
        self.assertFalse(worker_ready(as_issue(ALERT_DESC)),
                         "worker would have picked an alert ticket")

    def test_a_dor_alone_does_not_unblock_it(self):
        """The founder's proposed fix, tested rather than argued: emitting a DoR
        from alert-to-linear.py changes NOTHING, because is_fleet_alert is
        evaluated before the DoR is ever looked at."""
        with_dor = ALERT_DESC + "\n\n" + DOR
        self.assertIn("Definition of Ready", with_dor)
        self.assertFalse(worker_ready(as_issue(with_dor)),
                         "a DoR on a still-marked alert must remain refused")
        self.assertIsNone(drafter.selection_mode(as_issue(with_dor)))

    def test_promotion_makes_both_readers_accept(self):
        body = triage.promote_body(ALERT_DESC, DOR, "6f1a2b3c4d5e", "real, scoped.")
        self.assertFalse(IS_FLEET_ALERT(as_issue(body)),
                         "worker still refuses a promoted issue")
        self.assertFalse(drafter.is_alert_ticket(body),
                         "drafter still refuses a promoted issue")
        self.assertTrue(worker_ready(as_issue(body, labels=("owner:sana",))),
                        "promoted issue is not in the worker ready set")

    def test_audit_marker_does_not_retrip_either_reader(self):
        body = triage.promote_body(ALERT_DESC, DOR, "6f1a2b3c4d5e", "")
        self.assertIn("kipi-alert-promoted", body,
                      "provenance was dropped; promotion must stay auditable")
        self.assertFalse(IS_FLEET_ALERT(as_issue(body)))
        self.assertFalse(drafter.is_alert_ticket(body))

    def test_strip_removes_every_marker_not_just_the_first(self):
        two = ALERT_DESC + "\n<!-- kipi-alert-fingerprint: second -->\n"
        self.assertFalse(triage.is_alert_ticket(triage.strip_alert_marker(two)),
                         "a second marker survived the strip")

    def test_strip_does_not_eat_text_between_two_comments(self):
        d = ("<!-- kipi-alert-fingerprint: aa -->\nKEEP THIS LINE\n"
             "<!-- something-else: bb -->")
        out = triage.strip_alert_marker(d)
        self.assertIn("KEEP THIS LINE", out)
        self.assertIn("something-else", out)

    def test_fingerprint_is_recovered_for_the_audit_line(self):
        self.assertEqual(triage.alert_fingerprint(ALERT_DESC), "6f1a2b3c4d5e")


class FakeLinear:
    """Records every mutation so a test can assert what was NOT sent."""

    def __init__(self, comment_ok=True, update_ok=True):
        self.calls = []
        self.comment_ok = comment_ok
        self.update_ok = update_ok

    def graphql(self, query, variables):
        self.calls.append((query, variables))
        if "commentCreate" in query:
            return {"commentCreate": {"success": self.comment_ok}}
        if "teams(" in query:
            return {"teams": {"nodes": [{"states": {"nodes": [
                {"id": "cancel-id", "name": "Canceled", "type": "canceled"}]}}]}}
        if "issueLabels" in query:
            return {"issueLabels": {"nodes": [{"id": "held-id", "name": "triage:held"}]}}
        if "issueUpdate" in query:
            return {"issueUpdate": {"success": self.update_ok,
                                    "issue": {"identifier": "ASK-9"}}}
        if "issue(" in query:
            return {"issue": {"id": "issue-id", "identifier": "ASK-9",
                              "description": ALERT_DESC,
                              "labels": {"nodes": []}}}
        return {}

    def sent(self, needle):
        return any(needle in q for q, _ in self.calls)


class TestCloseIsNeverSilent(unittest.TestCase):
    """codex review of PR #268, major 2. do_close sent the rationale comment and
    discarded the result, so commentCreate.success=false still fell through to the
    close and printed CLOSED. Getting the ORDER right is not enough; the first
    write's result has to be read."""

    def test_close_refuses_when_the_rationale_comment_fails(self):
        f = FakeLinear(comment_ok=False)
        with self.assertRaises(RuntimeError) as cm:
            triage.do_close(f, {"id": "issue-id", "identifier": "ASK-9"},
                            "duplicate noise", True)
        self.assertIn("refusing to close", str(cm.exception))
        self.assertFalse(f.sent("issueUpdate"),
                         "the close mutation was sent despite the comment failing")

    def test_close_still_works_when_the_comment_lands(self):
        """Negative control: the guard must not block the good path."""
        f = FakeLinear(comment_ok=True)
        out = triage.do_close(f, {"id": "issue-id", "identifier": "ASK-9"},
                              "duplicate noise", True)
        self.assertIn("CLOSED", out.line)
        self.assertTrue(out.wrote)
        self.assertTrue(f.sent("issueUpdate"))


class TestPromotedIssuesAreActuallySelectable(unittest.TestCase):
    """codex round 4, major 1. Promotion strips the alert marker BEFORE the body is
    validated, so a promotion that omits the DoR heading leaves the issue out of the
    triage pool and still refused by the worker: promoted and unselectable."""

    def test_a_model_body_opening_with_another_heading_still_gets_a_dor(self):
        body = triage.promote_body(ALERT_DESC, "## Problem\n\nthe parser stalls",
                                   "fp", "")
        self.assertIn("Definition of Ready", body,
                      "a body starting with '## Problem' shipped no DoR")
        self.assertTrue(worker_ready(as_issue(body, labels=("owner:sana",))),
                        "promoted issue is not selectable by the worker")

    def test_a_body_that_already_has_the_heading_is_not_doubled(self):
        body = triage.promote_body(ALERT_DESC, DOR, "fp", "")
        self.assertEqual(body.count("Definition of Ready"), 1,
                         "the DoR heading was duplicated")
        self.assertTrue(worker_ready(as_issue(body, labels=("owner:sana",))))

    def test_a_lower_level_heading_counts(self):
        """### Definition of Ready is still a DoR; only structure matters."""
        body = triage.promote_body(ALERT_DESC, "### Definition of Ready\n\n- x",
                                   "fp", "")
        self.assertEqual(body.count("Definition of Ready"), 1)



class TestPromotionRequiresASelectableOwner(unittest.TestCase):
    """codex round 9. linear-worker.sh refuses on `owner:sana not in labels`
    BEFORE it reads the description, and alert-to-linear.py tolerates a failed
    label resolution. Promoting such an alert strips the marker (removing it from
    this tool's pool) while the worker still refuses it."""

    def _fake(self, labels):
        class L:
            def __init__(s): s.calls = []
            def graphql(s, q, v):
                s.calls.append((q, v))
                if "issue(" in q:
                    return {"issue": {"id": "u", "identifier": "ASK-1",
                            "description": ALERT_DESC,
                            "labels": {"nodes": [{"id": f"i{n}", "name": n}
                                                 for n in labels]}}}
                if "issueUpdate" in q:
                    return {"issueUpdate": {"success": True, "issue": {"identifier": "ASK-1"}}}
                return {}
            def wrote(s): return [q for q, _ in s.calls if "issueUpdate" in q]
        return L()

    def test_an_alert_without_owner_sana_is_not_promoted(self):
        f = self._fake(("needs-triage",))
        out = triage.do_promote(f, {"identifier": "ASK-1"}, DOR, "why", True)
        self.assertFalse(out.wrote)
        self.assertIn("owner:sana", out.line)
        self.assertEqual(f.wrote(), [],
                         "an unselectable issue was promoted out of the pool")

    def test_a_normal_alert_still_promotes(self):
        """Negative control: the guard must not block the ordinary path."""
        f = self._fake(("owner:sana", "needs-triage"))
        out = triage.do_promote(f, {"identifier": "ASK-1"}, DOR, "why", True)
        self.assertTrue(out.wrote)
        self.assertEqual(len(f.wrote()), 1)


class TestCloseOnlyTouchesAlerts(unittest.TestCase):
    """codex review of PR #275. do_promote always re-read and checked; do_close
    never did, so a mistyped identifier could CANCEL unrelated founder work. Both
    functions looked equally careful and only one was."""

    def _fake(self, desc, comments=(), close_ok=True):
        class L:
            def __init__(s): s.calls = []
            def graphql(s, q, v):
                s.calls.append((q, v))
                if "comments(first" in q:
                    return {"issue": {"comments": {"nodes": [{"body": b} for b in comments]}}}
                if "issue(" in q:
                    return {"issue": {"id": "u", "identifier": "ASK-9",
                                      "description": desc, "labels": {"nodes": []}}}
                if "commentCreate" in q:
                    return {"commentCreate": {"success": True}}
                if "teams(" in q:
                    return {"teams": {"nodes": [{"states": {"nodes": [
                        {"id": "c", "name": "Canceled", "type": "canceled"}]}}]}}
                if "issueUpdate" in q:
                    return {"issueUpdate": {"success": close_ok}}
                return {}
            def sent(s, n): return any(n in q for q, _ in s.calls)
            def comments_posted(s):
                return [v for q, v in s.calls if "commentCreate" in q]
        return L()

    def test_close_refuses_anything_that_is_not_an_alert(self):
        f = self._fake("A real founder issue with no alert marker at all.")
        out = triage.do_close(f, {"id": "u", "identifier": "ASK-9"}, "typo", True)
        self.assertFalse(out.wrote)
        self.assertIn("not an alert", out.line)
        self.assertFalse(f.sent("issueUpdate"), "unrelated work was cancelled")
        self.assertFalse(f.sent("commentCreate"), "it commented on unrelated work")

    def test_close_still_works_on_a_real_alert(self):
        """Negative control: the guard must not block the ordinary path."""
        f = self._fake(ALERT_DESC)
        out = triage.do_close(f, {"id": "u", "identifier": "ASK-9"}, "noise", True)
        self.assertTrue(out.wrote)
        self.assertIn("CLOSED", out.line)

    def test_a_retry_does_not_post_a_second_rationale(self):
        """The close can fail after the comment lands, leaving the rationale on an
        open issue. A retry used to add another identical copy."""
        prior = triage.CLOSE_MARKER + "\nTriage decision ... earlier attempt"
        f = self._fake(ALERT_DESC, comments=(prior,))
        triage.do_close(f, {"id": "u", "identifier": "ASK-9"}, "noise", True)
        self.assertEqual(f.comments_posted(), [],
                         "a second identical rationale was posted on retry")

    def test_the_rationale_is_worded_as_a_decision_not_a_finished_close(self):
        """It may end up sitting on an issue that is still open, so it must not
        assert a state that did not happen."""
        f = self._fake(ALERT_DESC)
        triage.do_close(f, {"id": "u", "identifier": "ASK-9"}, "noise", True)
        body = f.comments_posted()[0]["input"]["body"]
        self.assertIn(triage.CLOSE_MARKER, body, "the retry key is missing")
        self.assertIn("Triage decision", body)
        self.assertIn("still open", body,
                      "the note does not tell a reader what an open issue means")


class TestCliHelpMatchesReality(unittest.TestCase):
    def test_the_cli_does_not_advertise_a_verb_it_lacks(self):
        """codex review of PR #275, minor. The usage line still promised 'hold the
        rest' after the unattended lane was split out to ASK-1133."""
        cli = (SCRIPTS.parent.parent.parent / "kipi").read_text(encoding="utf-8")
        usage = [l for l in cli.split("\n") if "kipi alert-triage" in l and "echo" in l]
        self.assertTrue(usage, "the verb is no longer documented at all")
        self.assertNotIn("hold", usage[0].lower(),
                         "the CLI advertises a hold operation that does not exist")


if __name__ == "__main__":
    unittest.main(verbosity=2)
