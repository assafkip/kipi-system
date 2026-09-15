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


def as_issue(desc, labels=("owner:sana", "needs-triage"), project="kipi-system",
             state="backlog"):
    return {"identifier": "ASK-9999", "id": "u", "description": desc,
            "state": {"type": state},
            "project": {"name": project} if project else None,
            "labels": {"nodes": [{"id": f"id-{n}", "name": n} for n in labels]}}


def _worker_ready(repo_project="kipi-system"):
    """ready(), lifted VERBATIM out of linear-worker.sh.

    The first version of this helper was hand-written and omitted
    blocked:capability and the project check, which is the same subset bug codex
    found in promotion_refusal. A test carrying its own copy of the predicate
    cannot detect that the real one has a condition the code under test lacks."""
    src = (SCRIPTS / "linear-worker.sh").read_text(encoding="utf-8")
    m = re.search(r"^def ready\(i\):.*?^    return \"## Definition of Ready\" in d "
                  r"or \"Definition of Ready\" in d$", src, re.S | re.M)
    if not m:
        raise AssertionError("could not locate ready() in linear-worker.sh")
    ns = {"is_fleet_alert": IS_FLEET_ALERT, "repo_project": repo_project,
          "project_of": lambda i: ((i.get("project") or {}).get("name") or "")}
    exec(compile("def in_this_repo(i):\n    return project_of(i) == repo_project\n",
                 "worker:in_this_repo", "exec"), ns)
    exec(compile(m.group(0), "linear-worker.sh:ready", "exec"), ns)
    return ns["ready"]


worker_ready = _worker_ready()


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
                            "project": {"name": "kipi-system"},
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
        rest' after the unattended lane was split out to ASK-1133.

        The verbs are READ FROM THE PARSER that owns them, not restated here: a
        literal list in this test would agree on the day it was written and then
        keep asserting the old contract."""
        cli = (SCRIPTS.parent.parent.parent / "kipi").read_text(encoding="utf-8")
        usage = [l for l in cli.split("\n") if "kipi alert-triage" in l and "echo" in l]
        self.assertTrue(usage, "the verb is no longer documented at all")
        m = re.search(r"alert-triage <([^>]+)>", usage[0])
        self.assertTrue(m, "the usage line no longer names its verbs")
        advertised = set(m.group(1).split("|"))
        real = set(next(a for a in triage.build_parser()._actions
                        if a.dest == "verb").choices or ())
        self.assertTrue(real, "derived an empty verb set from the parser")
        self.assertEqual(advertised, real,
                         "the CLI usage and the script's parser disagree on the verbs")


class TestCloseRacingAPromotion(unittest.TestCase):
    """codex review of PR #275 round 2. Linear has no CAS, so no ordering of
    checks closes the window between the last alert check and the close. ASK-1126
    already says a point-in-time check cannot make a shared mutable resource safe.
    So the act is verified AFTERWARDS and compensated."""

    def _fake(self, descs, reopen_ok=True):
        """`descs` is consumed one per reread, so the issue can change mid-flight."""
        seq = list(descs)
        class L:
            def __init__(s): s.calls = []; s.state = []
            def graphql(s, q, v):
                s.calls.append((q, v))
                if "comments(first" in q:
                    return {"issue": {"comments": {"nodes": []}}}
                if "issue(" in q:
                    d = seq.pop(0) if seq else ALERT_DESC
                    return {"issue": {"id": "u", "identifier": "ASK-9",
                                      "description": d, "labels": {"nodes": []}}}
                if "commentCreate" in q:
                    return {"commentCreate": {"success": True}}
                if "teams(" in q:
                    return {"teams": {"nodes": [{"states": {"nodes": [
                        {"id": "c", "name": "Canceled", "type": "canceled"},
                        {"id": "b", "name": "Backlog", "type": "backlog"}]}}]}}
                if "issueUpdate" in q:
                    s.state.append(v["input"].get("stateId"))
                    return {"issueUpdate": {"success": reopen_ok or
                                            v["input"].get("stateId") == "c"}}
                return {}
        return L()

    def test_a_promotion_landing_before_the_close_stops_it(self):
        promoted = triage.promote_body(ALERT_DESC, DOR, "fp", "")
        # reread #1 (alert gate) sees an alert; reread #2 (final check) sees a promotion
        f = self._fake([ALERT_DESC, promoted])
        out = triage.do_close(f, {"id": "u", "identifier": "ASK-9"}, "noise", True)
        self.assertFalse(out.wrote)
        self.assertIn("promoted", out.line)
        self.assertEqual(f.state, [], "executable work was cancelled")

    def test_a_promotion_landing_after_the_close_is_undone(self):
        promoted = triage.promote_body(ALERT_DESC, DOR, "fp", "")
        # gate ok, final check ok, and only the POST-close read sees the promotion
        f = self._fake([ALERT_DESC, ALERT_DESC, promoted])
        out = triage.do_close(f, {"id": "u", "identifier": "ASK-9"}, "noise", True)
        self.assertFalse(out.wrote)
        self.assertIn("UNDONE", out.line)
        self.assertIn("b", f.state, "the close was not compensated with a reopen")

    def test_an_ordinary_close_still_works(self):
        """Negative control: three clean reads must still close, once."""
        f = self._fake([ALERT_DESC, ALERT_DESC, ALERT_DESC])
        out = triage.do_close(f, {"id": "u", "identifier": "ASK-9"}, "noise", True)
        self.assertTrue(out.wrote)
        self.assertEqual(f.state, ["c"], "it closed more than once or not at all")


class TestExplicitVerbsReportSkips(unittest.TestCase):
    """codex review of PR #275 round 2. main() is run_triage's sibling and kept the
    identical skip-as-success defect after run_triage was fixed for it."""

    def test_main_exit_contract_is_covered_behaviourally(self):
        """Replaced by TestMainExitCodeBehaviour, which drives main() instead of
        grepping its source (codex r5 minor: the source test stayed green when
        the contract was deleted)."""
        self.assertTrue(hasattr(triage, "main"))


class TestUnverifiedCloseSaysSo(unittest.TestCase):
    """codex review of PR #275 round 3. A failed post-close re-read fell through
    to CLOSED, so the safety check was skipped and its success reported anyway."""

    def _fake(self, reads):
        seq = list(reads)
        class L:
            def __init__(s): s.calls = []
            def graphql(s, q, v):
                s.calls.append((q, v))
                if "comments(first" in q:
                    return {"issue": {"comments": {"nodes": []}}}
                if "issue(" in q:
                    d = seq.pop(0) if seq else ALERT_DESC
                    if d is None:
                        raise RuntimeError("transport failure on the verify read")
                    return {"issue": {"id": "u", "identifier": "ASK-9",
                                      "description": d, "labels": {"nodes": []}}}
                if "commentCreate" in q:
                    return {"commentCreate": {"success": True}}
                if "teams(" in q:
                    return {"teams": {"nodes": [{"states": {"nodes": [
                        {"id": "c", "name": "Canceled", "type": "canceled"},
                        {"id": "b", "name": "Backlog", "type": "backlog"}]}}]}}
                if "issueUpdate" in q:
                    return {"issueUpdate": {"success": True}}
                return {}
        return L()

    def test_a_failed_verify_read_is_reported_not_swallowed(self):
        # gate ok, final check ok, POST-close read fails
        f = self._fake([ALERT_DESC, ALERT_DESC, None])
        out = triage.do_close(f, {"id": "u", "identifier": "ASK-9"}, "noise", True)
        self.assertTrue(out.wrote, "the close did happen, so it must not claim otherwise")
        self.assertIn("UNVERIFIED", out.line,
                      "a skipped verification was reported as a verified close")

    def test_a_clean_close_does_not_say_unverified(self):
        """Negative control."""
        f = self._fake([ALERT_DESC, ALERT_DESC, ALERT_DESC])
        out = triage.do_close(f, {"id": "u", "identifier": "ASK-9"}, "noise", True)
        self.assertTrue(out.wrote)
        self.assertNotIn("UNVERIFIED", out.line)

    def test_promotion_comment_matches_the_mutation_it_makes(self):
        """The stale 'drop the hold too' comment survived the split while the
        payload reverted to needs-triage only. A comment describing a mutation
        the code does not make teaches a reader to distrust the comments."""
        import inspect
        body = inspect.getsource(triage).split("def do_promote(")[1].split("\ndef ")[0]
        if "HELD_LABEL" not in body:
            self.assertNotIn("triage:held", body,
                             "the comment promises to clear a label the payload leaves")


class TestPromotionRefusesUnroutableWork(unittest.TestCase):
    """codex review of PR #275 round 4. The project check lived in the unattended
    pool filter and never in do_promote, so a hand promotion still stripped the
    alert marker off an issue no checkout can ever serve."""

    def _issue(self, project, labels=("owner:sana",)):
        return {"identifier": "ASK-1", "id": "u", "description": ALERT_DESC,
                "project": {"name": project} if project else None,
                "labels": {"nodes": [{"id": "x", "name": n} for n in labels]}}

    def test_a_projectless_alert_is_refused(self):
        r = triage.promotion_refusal(self._issue(None))
        self.assertIsNotNone(r)
        self.assertIn("no project", r)

    def test_an_empty_project_name_is_refused(self):
        self.assertIsNotNone(triage.promotion_refusal(self._issue("   ")))

    def test_a_routable_alert_passes(self):
        """Negative control: all three preconditions satisfied."""
        self.assertIsNone(triage.promotion_refusal(self._issue("kipi-system")))

    def test_every_precondition_lives_in_one_function(self):
        """The reason this class of defect kept recurring: preconditions were
        open-coded per verb, so each new one landed in whichever function the
        reviewer named. do_promote must not grow its own."""
        import inspect
        body = inspect.getsource(triage).split("def do_promote(")[1].split("\ndef ")[0]
        self.assertIn("promotion_refusal(", body)
        for leaked in ("OWNER_LABEL not in", 'get("project")'):
            self.assertNotIn(leaked, body,
                             "a precondition is open-coded in do_promote instead of "
                             "promotion_refusal, where its sibling cannot see it")


class TestCloseRefusesOnAFailedFreshnessRead(unittest.TestCase):
    """codex review of PR #275 round 4. Round 3 fixed this on the POST-close read
    and I left the PRE-close read alone: the sibling pattern, again."""

    def test_a_failed_pre_close_read_does_not_permit_the_close(self):
        seq = [ALERT_DESC, None]
        class L:
            def __init__(s): s.calls = []
            def graphql(s, q, v):
                s.calls.append((q, v))
                if "comments(first" in q:
                    return {"issue": {"comments": {"nodes": []}}}
                if "issue(" in q:
                    d = seq.pop(0) if seq else ALERT_DESC
                    if d is None:
                        raise RuntimeError("transport failure on the freshness read")
                    return {"issue": {"id": "u", "identifier": "ASK-9",
                                      "description": d, "labels": {"nodes": []}}}
                if "commentCreate" in q:
                    return {"commentCreate": {"success": True}}
                if "teams(" in q:
                    return {"teams": {"nodes": [{"states": {"nodes": [
                        {"id": "c", "name": "Canceled", "type": "canceled"}]}}]}}
                if "issueUpdate" in q:
                    return {"issueUpdate": {"success": True}}
                return {}
        f = L()
        out = triage.do_close(f, {"id": "u", "identifier": "ASK-9"}, "noise", True)
        self.assertFalse(out.wrote)
        self.assertFalse(any("issueUpdate" in q for q, _ in f.calls),
                         "it closed without confirming the issue was still an alert")


class TestRefusalAgreesWithTheRealWorker(unittest.TestCase):
    """codex review of PR #275 round 5, major. Centralising the preconditions was
    only half the fix: the list itself was the SUBSET that had come up in review,
    missing owner:assaf, needs-scope, blocked:capability and the state type. So
    promote reported PROMOTED, stripped the alert marker, and left an issue the
    worker still refuses.

    This test does not re-list the conditions. It asserts the PROPERTY: anything
    promotion_refusal lets through must be accepted by linear-worker.sh's own
    ready(), extracted from the shipped file. A condition added to the worker, or
    dropped from here, breaks it."""

    SHAPES = [
        ("ordinary alert", {}),
        ("founder-owned", {"labels": ("owner:assaf", "owner:sana")}),
        ("no owner", {"labels": ("needs-triage",)}),
        ("needs-scope", {"labels": ("owner:sana", "needs-scope")}),
        ("blocked:capability", {"labels": ("owner:sana", "blocked:capability")}),
        ("started state", {"state": "started"}),
        ("completed state", {"state": "completed"}),
        ("no project", {"project": None}),
        ("wrong project", {"project": "some-other-repo"}),
    ]

    def test_anything_allowed_is_accepted_by_the_worker(self):
        allowed = 0
        for name, kw in self.SHAPES:
            issue = as_issue(ALERT_DESC, **kw)
            if triage.promotion_refusal(issue) is not None:
                continue
            allowed += 1
            promoted = dict(issue, description=triage.promote_body(
                issue["description"], DOR, "fp", ""))
            # ready() against the checkout that OWNS this issue's project.
            # in_this_repo() is per-checkout, not a global validity condition:
            # this tool is fleet-wide by design (--project is optional), so an
            # issue in another repo's project is legitimately promotable and a
            # dispatcher there picks it up. Pinning every shape to kipi-system
            # would assert something the system does not claim. What must hold
            # is that SOME checkout can serve it, which is why a projectless
            # issue is still refused: no checkout can ever match an empty name.
            ready = _worker_ready((issue.get("project") or {}).get("name") or "")
            self.assertTrue(ready(promoted),
                            f"promotion_refusal allowed {name!r}, but the worker's "
                            "own ready() still refuses it after promotion")
        self.assertGreater(allowed, 0,
                           "no shape was allowed, so this test proved nothing")

    def test_the_refusals_are_not_blanket(self):
        """Negative control: an ordinary alert must pass, or the check above is
        satisfied trivially by refusing everything."""
        self.assertIsNone(triage.promotion_refusal(as_issue(ALERT_DESC)))


class TestMainExitCodeBehaviour(unittest.TestCase):
    """codex r5 minor: the only test for main's exit contract asserted SOURCE
    substrings and stayed green when the contract was deleted. This drives main()
    and reads the code it returns."""

    def _main(self, argv, refusal_desc):
        import io, contextlib
        class LS:
            def graphql(s, q, v):
                if "comments(first" in q:
                    return {"issue": {"comments": {"nodes": []}}}
                if "issue(" in q:
                    return {"issue": {"id": "u", "identifier": "ASK-1",
                                      "description": refusal_desc,
                                      "state": {"type": "backlog"},
                                      "project": {"name": "kipi-system"},
                                      "labels": {"nodes": [
                                          {"id": "o", "name": "owner:sana"}]}}}
                if "issueUpdate" in q:
                    return {"issueUpdate": {"success": True, "issue": {"identifier": "ASK-1"}}}
                return {}
            def linear_api_key(s): return "k"
        orig_load, orig_ev = triage._load, triage.write_run_evidence
        triage._load = lambda n, f: LS()
        triage.write_run_evidence = lambda line: None
        argv_backup = sys.argv[:]
        sys.argv = ["linear-alert-triage.py"] + argv
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                return triage.main()
        finally:
            triage._load, triage.write_run_evidence = orig_load, orig_ev
            sys.argv = argv_backup

    def test_an_apply_that_writes_nothing_exits_nonzero(self):
        promoted = triage.promote_body(ALERT_DESC, DOR, "fp", "")
        rc = self._main(["promote", "ASK-1", "--dor", DOR, "--apply"], promoted)
        self.assertEqual(rc, 1, "promote --apply wrote nothing and reported success")

    def test_an_apply_that_writes_exits_zero(self):
        """Negative control."""
        rc = self._main(["promote", "ASK-1", "--dor", DOR, "--apply"], ALERT_DESC)
        self.assertEqual(rc, 0)


class TestFencedDorDoesNotCount(unittest.TestCase):
    """codex r5 minor. DOR_HEADING_RE claimed to mirror the drafter's
    find_dor_heading, which skips code fences, and did not. A DoR shown as an
    EXAMPLE inside a fence satisfied the bare regex, so promote_body added no
    real heading.

    Written because the first mutation run SURVIVED: reverting the fence fix left
    every test green, which means the fix was decoration until this existed."""

    FENCED = ("Here is the shape we want:\n\n"
              "```markdown\n## Definition of Ready\n\n- not a real one\n```\n\n"
              "That is only an example.")

    def test_a_fenced_dor_still_gets_a_real_heading(self):
        body = triage.promote_body(ALERT_DESC, self.FENCED, "fp", "")
        outside = triage._outside_fences(body)
        self.assertTrue(triage.DOR_HEADING_RE.search(outside),
                        "the only DoR heading is inside a code fence")

    def test_the_promoted_issue_is_still_worker_ready(self):
        body = triage.promote_body(ALERT_DESC, self.FENCED, "fp", "")
        self.assertTrue(worker_ready(as_issue(body, labels=("owner:sana",))))

    def test_an_unfenced_heading_is_not_duplicated(self):
        """Negative control: the fence skip must not make it add a second one."""
        body = triage.promote_body(ALERT_DESC, DOR, "fp", "")
        self.assertEqual(body.count("Definition of Ready"), 1)

    def test_outside_fences_blanks_only_the_fenced_span(self):
        out = triage._outside_fences("keep me\n```\nhide me\n```\nkeep me too")
        self.assertIn("keep me", out)
        self.assertIn("keep me too", out)
        self.assertNotIn("hide me", out)


# ---------------------------------------------------------------------------
# THE UNATTENDED LANE (ASK-1133).
#
# PR #268 took nine codex rounds and put seven of its eight majors in this lane.
# The ten defects it found are listed in ASK-1133, and each class below is named
# for the one it pins (D1..D10). Every one of them was shown RED against a build
# with that single fix reverted; `alert_triage_mutants.py` next to this file
# re-runs that proof.
# ---------------------------------------------------------------------------
import copy
import io
import plistlib
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HAND_DOR = "## Definition of Ready\n\n- Promoted BY HAND while the lane ran\n"


def alert(ident, project="kipi-system", labels=("owner:sana", "needs-triage"),
          created="2026-08-01T00:00:00Z", desc=None):
    return {"id": f"uuid-{ident}", "identifier": ident, "title": f"alert {ident}",
            "url": "", "createdAt": created,
            "description": desc if desc is not None
            else ALERT_DESC.replace("6f1a2b3c4d5e", f"fp-{ident}"),
            "state": {"name": "Backlog", "type": "backlog"},
            "project": {"name": project} if project else None,
            "labels": {"nodes": [{"id": f"lid-{n}", "name": n} for n in labels]}}


class Board:
    """The ASK team held in memory, mutated the way Linear mutates it.

    A label write is applied as a server-side DELTA (addedLabelIds /
    removedLabelIds); a description write replaces the whole body. The
    hold-versus-promotion race turns on exactly that difference, so a fake that
    applied them any other way would test nothing.

    `before[needle] = fn` runs fn(board) once, immediately before the first
    request whose text contains needle: that is how a concurrent promotion is
    landed inside a specific window.
    """

    def __init__(self, issues, team_labels=("owner:sana", "needs-triage"),
                 comment_ok=True, label_create_ok=True, update_ok=True):
        self.issues = {i["identifier"]: i for i in issues}
        self.team_labels = {n: f"lid-{n}" for n in team_labels}
        self.comments = {}
        self.calls = []
        self.before = {}
        self.comment_ok = comment_ok
        self.label_create_ok = label_create_ok
        self.update_ok = update_ok

    def _find(self, key):
        return next((i for i in self.issues.values()
                     if key in (i["identifier"], i["id"])), None)

    def _update(self, v):
        if not self.update_ok:
            return {"issueUpdate": {"success": False}}
        i, inp = self._find(v["id"]), v["input"]
        if "description" in inp:
            i["description"] = inp["description"]
        removed = set(inp.get("removedLabelIds") or [])
        nodes = [l for l in i["labels"]["nodes"] if l["id"] not in removed]
        names = {lid: n for n, lid in self.team_labels.items()}
        for lid in inp.get("addedLabelIds") or []:
            if lid not in {l["id"] for l in nodes}:
                nodes.append({"id": lid, "name": names[lid]})
        i["labels"]["nodes"] = nodes
        return {"issueUpdate": {"success": True,
                                "issue": {"identifier": i["identifier"]}}}

    def graphql(self, q, v):
        self.calls.append((q, copy.deepcopy(v)))
        for needle in [n for n in self.before if n in q]:
            self.before.pop(needle)(self)
        if "issueLabelCreate" in q:
            if not self.label_create_ok:
                return {"issueLabelCreate": {"success": False, "issueLabel": None}}
            name = v["input"]["name"]
            self.team_labels[name] = f"lid-{name}"
            return {"issueLabelCreate": {"success": True, "issueLabel": {
                "id": f"lid-{name}", "name": name}}}
        if "issueLabels(" in q:
            return {"issueLabels": {"nodes": [
                {"id": lid, "name": n, "team": {"key": "ASK"}}
                for n, lid in self.team_labels.items() if n == v["n"]]}}
        if "commentCreate" in q:
            if self.comment_ok:
                self.comments.setdefault(v["input"]["issueId"], []).append(
                    v["input"]["body"])
            return {"commentCreate": {"success": self.comment_ok}}
        if "comments(first" in q:
            i = self._find(v["id"])
            return {"issue": {"comments": {"nodes": [
                {"body": b} for b in self.comments.get(i["id"], [])]}}}
        if "issueUpdate" in q:
            return self._update(v)
        if "issues(" in q:
            return {"issues": {"pageInfo": {"hasNextPage": False},
                               "nodes": [copy.deepcopy(i) for i in self.issues.values()]}}
        if "issue(" in q:
            i = self._find(v["id"])
            return {"issue": copy.deepcopy(i) if i else None}
        if "teams(" in q:
            return {"teams": {"nodes": [{"id": "team-id", "states": {"nodes": [
                {"id": "c", "name": "Canceled", "type": "canceled"},
                {"id": "b", "name": "Backlog", "type": "backlog"}]}}]}}
        return {}

    # -- what the tests read back -------------------------------------------
    def reread(self, ident):
        """The issue as the board holds it NOW, through the same query the script uses."""
        return self.graphql(triage.ISSUE_Q, {"id": ident})["issue"]

    def labels_of(self, ident):
        return {l["name"] for l in self.issues[ident]["labels"]["nodes"]}

    def mutations(self):
        return [(q, v) for q, v in self.calls
                if "mutation" in q]


def run_lane(board, decider, apply=True, limit=8):
    out, err = io.StringIO(), io.StringIO()
    with patch.object(triage, "write_run_evidence", lambda line: None), \
         redirect_stdout(out), redirect_stderr(err):
        rc = triage.run_triage(board, limit=limit, apply=apply, decider=decider)
    return rc, out.getvalue(), err.getvalue()


def says(verdict, body):
    return lambda issue: (verdict, body)


def promotes_by_hand_during_the_call(board, verdict, body):
    """A decider that lets a person promote the issue while the model is thinking."""
    def decide(issue):
        cur = board.issues[issue["identifier"]]
        cur["description"] = triage.promote_body(cur["description"], HAND_DOR,
                                                 "fp", "by hand")
        return verdict, body
    return decide


def lane_plists():
    found = []
    for p in sorted(SCRIPTS.glob("com.kipi.*.plist")):
        # Only the lane's own template is parsed: several sibling templates are
        # not well-formed XML until install-plist.sh materializes them.
        if "alert-triage" not in p.read_text(encoding="utf-8"):
            continue
        d = plistlib.loads(p.read_bytes())
        cmd = " ".join(d.get("ProgramArguments") or [])
        if "alert-triage" in cmd:
            found.append((p, d, cmd))
    return found


class TestD1LaneHasAScheduledCaller(unittest.TestCase):
    """R1: the lane shipped with no scheduled caller, so the consumer did not
    exist operationally -- the defect the whole script was written to fix."""

    def test_a_launchd_template_runs_the_lane_with_apply(self):
        plists = lane_plists()
        self.assertEqual(len(plists), 1, f"expected one lane template, got {plists}")
        path, d, cmd = plists[0]
        self.assertIn("alert-triage run", cmd)
        self.assertIn("--apply", cmd)
        self.assertEqual(d["Label"], path.stem, "label and filename disagree")
        self.assertIn("StartCalendarInterval", d)

    def test_the_template_is_portable(self):
        """install-plist.sh materializes __KIPI_REPO__/__HOME__; a hardcoded home
        fails validate-separation's skeleton sweep (ASK-113 / ASK-191)."""
        path, _, cmd = lane_plists()[0]
        text = path.read_text(encoding="utf-8")
        self.assertIn("__KIPI_REPO__", cmd)
        self.assertNotIn("/Users/", text)

    def test_the_cli_parses_the_scheduled_command(self):
        a = triage.build_parser().parse_args(["run", "--limit", "8", "--apply"])
        self.assertEqual((a.verb, a.limit, a.apply), ("run", 8, True))


class TestD2HoldHasNoneOfClosesOldDefects(unittest.TestCase):
    """R2: the hold path was written in the commit that fixed do_close, and had
    both of do_close's defects: no still-an-alert re-check, and a rationale
    comment whose result was never read."""

    def test_hold_refuses_when_the_rationale_comment_fails(self):
        b = Board([alert("ASK-1")], comment_ok=False)
        with self.assertRaises(RuntimeError):
            triage.do_hold(b, b.reread("ASK-1"), "not scoped", True)
        self.assertFalse([q for q, _ in b.mutations() if "issueUpdate" in q],
                         "the hold label was written although the rationale did not land")
        self.assertNotIn(triage.HELD_LABEL, b.labels_of("ASK-1"))

    def test_hold_skips_an_issue_that_is_no_longer_an_alert(self):
        b = Board([alert("ASK-1")])
        stale = b.reread("ASK-1")
        b.issues["ASK-1"]["description"] = triage.promote_body(
            ALERT_DESC, HAND_DOR, "fp", "")
        out = triage.do_hold(b, stale, "not scoped", True)
        self.assertFalse(out.wrote)
        self.assertIn("SKIPPED", out.line)
        self.assertEqual(b.mutations(), [], "a promoted issue was held")

    def test_hold_still_works_on_a_real_alert(self):
        """Negative control."""
        b = Board([alert("ASK-1")])
        out = triage.do_hold(b, b.reread("ASK-1"), "not scoped", True)
        self.assertTrue(out.wrote, out.line)
        self.assertIn(triage.HELD_LABEL, b.labels_of("ASK-1"))
        self.assertIn("not scoped", b.comments["uuid-ASK-1"][0])


class TestD3HoldCannotClobberAPromotion(unittest.TestCase):
    """R3: hold re-read, checked, then wrote description = stale body + marker. A
    promotion landing in that window was CLOBBERED and its DoR deleted. Linear
    has no CAS, so the fix is structural: hold writes NO description at all."""

    def test_a_promotion_inside_the_hold_window_survives(self):
        b = Board([alert("ASK-1")])
        promoted = triage.promote_body(b.issues["ASK-1"]["description"], HAND_DOR,
                                       "fp", "by hand")

        def land(board):
            board.issues["ASK-1"]["description"] = promoted
        # After hold's own re-read and still-an-alert check, before its writes.
        b.before["commentCreate"] = land
        triage.do_hold(b, b.reread("ASK-1"), "not scoped", True)
        self.assertEqual(b.reread("ASK-1")["description"], promoted,
                         "the hold clobbered a promotion that landed mid-flight")

    def test_hold_never_sends_a_description(self):
        b = Board([alert("ASK-1")])
        triage.do_hold(b, b.reread("ASK-1"), "not scoped", True)
        self.assertTrue(b.mutations())
        updates = [v for q, v in b.mutations() if "issueUpdate" in q]
        self.assertTrue(updates, "hold wrote no label at all")
        for v in updates:
            self.assertNotIn("description", v["input"], "hold sent a description write")

    def test_a_hold_that_raced_a_promotion_does_not_leave_the_label(self):
        """The label delta cannot clobber the body, but it can still land on an
        issue that is now executable work. Verified after the write and undone,
        the way do_close compensates."""
        b = Board([alert("ASK-1")])
        b.before["issueUpdate"] = lambda board: board.issues["ASK-1"].update(
            description=triage.promote_body(ALERT_DESC, HAND_DOR, "fp", ""))
        out = triage.do_hold(b, b.reread("ASK-1"), "not scoped", True)
        self.assertFalse(out.wrote, out.line)
        self.assertNotIn(triage.HELD_LABEL, b.labels_of("ASK-1"))

    def test_lane_hold_during_the_model_call_is_never_a_clobber(self):
        """Acceptance: a promotion landing DURING THE MODEL CALL, re-read after."""
        b = Board([alert("ASK-1")])
        rc, out, _ = run_lane(b, promotes_by_hand_during_the_call(b, "HOLD", "noise"))
        body = b.reread("ASK-1")["description"]
        self.assertIn("Promoted BY HAND", body)
        self.assertFalse(triage.is_alert_ticket(body))
        self.assertNotIn(triage.HELD_LABEL, b.labels_of("ASK-1"))

    def test_lane_promote_during_the_model_call_is_never_a_clobber(self):
        b = Board([alert("ASK-1")])
        run_lane(b, promotes_by_hand_during_the_call(b, "PROMOTE", DOR))
        body = b.reread("ASK-1")["description"]
        self.assertIn("Promoted BY HAND", body)
        self.assertNotIn("gh pr checks", body, "the model's DoR overwrote the hand one")


class TestD4TotalModelFailureIsNotAQuietNight(unittest.TestCase):
    """R3: exit 0 when every model decision failed, so an outage read as a quiet
    night forever."""

    def test_every_decision_failing_exits_nonzero(self):
        b = Board([alert("ASK-1"), alert("ASK-2")])
        rc, out, _ = run_lane(b, lambda issue: None)
        self.assertNotEqual(rc, 0)
        self.assertEqual(b.mutations(), [])

    def test_a_dry_run_whose_decisions_all_failed_is_not_green_either(self):
        rc, _, _ = run_lane(Board([alert("ASK-1")]), lambda issue: None, apply=False)
        self.assertNotEqual(rc, 0)

    def test_a_working_night_exits_zero(self):
        """Negative control."""
        b = Board([alert("ASK-1", created="2026-08-01"), alert("ASK-2", created="2026-08-02")])
        verdicts = {"ASK-1": ("PROMOTE", DOR), "ASK-2": ("HOLD", "noise")}
        rc, out, err = run_lane(b, lambda i: verdicts[i["identifier"]])
        self.assertEqual(rc, 0, err)
        self.assertFalse(triage.is_alert_ticket(b.issues["ASK-1"]["description"]))
        self.assertIn(triage.HELD_LABEL, b.labels_of("ASK-2"))
        self.assertIn("2 written", out)

    def test_an_empty_pool_exits_zero(self):
        rc, _, _ = run_lane(Board([]), says("HOLD", "x"))
        self.assertEqual(rc, 0)


class TestD5SkippedWritesAreNotSuccesses(unittest.TestCase):
    """R5: a skipped write counted as a success, so a fully-skipped batch exited 0."""

    def test_a_fully_skipped_pass_exits_nonzero(self):
        b = Board([alert("ASK-1"), alert("ASK-2")])
        rc, out, _ = run_lane(b, promotes_by_hand_during_the_call(b, "PROMOTE", DOR))
        self.assertNotEqual(rc, 0, out)
        self.assertIn("0 written", out)
        self.assertIn("2 skipped", out)


class TestD6TheLaneIsFleetWide(unittest.TestCase):
    """R5: the scheduler was pinned to one project and covered 55 of 151 tickets."""

    def test_the_schedule_is_not_pinned_to_a_project(self):
        _, _, cmd = lane_plists()[0]
        self.assertNotIn("--project", cmd)

    def test_the_pass_takes_alerts_from_every_project(self):
        b = Board([alert("ASK-1", project="kipi-system"),
                   alert("ASK-2", project="consulting")])
        seen = []
        run_lane(b, lambda i: (seen.append(i["identifier"]), None)[1])
        self.assertEqual(sorted(seen), ["ASK-1", "ASK-2"])

    def test_a_projectless_alert_never_reaches_the_model(self):
        b = Board([alert("ASK-1", project=None), alert("ASK-2")])
        seen = []
        rc, out, _ = run_lane(b, lambda i: (seen.append(i["identifier"]), ("PROMOTE", DOR))[1])
        self.assertEqual(seen, ["ASK-2"])
        self.assertTrue(triage.is_alert_ticket(b.issues["ASK-1"]["description"]))
        self.assertIn("1 refused", out, "a refused alert vanished from the run line")


class TestD7TheModelGetsNoTools(unittest.TestCase):
    """R6: untrusted alert text was passed to a model holding filesystem edit
    permission (ASK-1132 is the same defect in the drafter). A capability bound,
    not a filter: no built-in tools, no MCP servers, and not inside the repo."""

    def _call(self, stdout="HOLD\nnot scoped", rc=0, env=None):
        seen = {}

        def fake_run(argv, **kw):
            seen["argv"], seen["kw"] = list(argv), kw
            return subprocess.CompletedProcess(argv, rc, stdout=stdout, stderr="")
        with patch.object(triage, "claude_binary", lambda: "claude"), \
             patch.object(triage.subprocess, "run", fake_run), \
             patch.dict(triage.os.environ, env or {}):
            result = triage.decide(alert("ASK-1"))
        return seen, result

    def test_no_built_in_tools(self):
        argv = self._call()[0]["argv"]
        self.assertIn("--tools", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")

    def test_no_mcp_servers(self):
        self.assertIn("--strict-mcp-config", self._call()[0]["argv"])
        self.assertNotIn("--mcp-config", self._call()[0]["argv"])

    def test_never_any_permission_grant(self):
        joined = " ".join(self._call()[0]["argv"])
        for grant in ("--permission-mode", "acceptEdits", "--allowedTools",
                      "--allowed-tools", "--dangerously-skip-permissions", "--add-dir"):
            self.assertNotIn(grant, joined)

    def test_the_prompt_is_not_swallowed_by_the_variadic_tools_flag(self):
        """`--tools <tools...>` is variadic: a prompt placed after it becomes a
        tool name and the model gets no prompt."""
        argv = self._call()[0]["argv"]
        prompt_at = next(n for n, a in enumerate(argv) if "fleet alert" in a)
        self.assertLess(prompt_at, argv.index("--tools"))

    def test_the_model_is_pinned_even_when_the_caller_sets_another(self):
        seen = self._call(env={"ANTHROPIC_MODEL": "claude-fable-5"})[0]
        argv = seen["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], triage.TRIAGE_MODEL)
        self.assertEqual(seen["kw"]["env"]["ANTHROPIC_MODEL"], triage.TRIAGE_MODEL)

    def test_the_model_does_not_run_inside_the_repo(self):
        cwd = self._call()[0]["kw"].get("cwd")
        self.assertTrue(cwd, "no cwd: the model inherits the repo and its settings")
        self.assertFalse(str(Path(cwd).resolve()).startswith(
            str(SCRIPTS.parent.parent.parent.resolve())))

    def test_a_failed_call_is_no_decision(self):
        self.assertIsNone(self._call(rc=1)[1])
        self.assertIsNone(self._call(stdout="I think this is probably fine")[1])


class TestD8FreshWorkspaceNeedsNoHandMadeLabel(unittest.TestCase):
    """R7: the hold label existed only because it had been created by hand. On a
    fresh workspace every night raised AFTER the comment had posted, so one
    duplicate rationale per night, forever."""

    def test_a_fresh_workspace_run_creates_the_label_and_holds(self):
        b = Board([alert("ASK-1")])          # no triage:held on this team
        rc, out, err = run_lane(b, says("HOLD", "noise"))
        self.assertEqual(rc, 0, err)
        self.assertIn(triage.HELD_LABEL, b.labels_of("ASK-1"))

    def test_the_label_is_resolved_before_anything_is_written(self):
        b = Board([alert("ASK-1")], label_create_ok=False)
        with self.assertRaises(RuntimeError):
            triage.do_hold(b, b.reread("ASK-1"), "noise", True)
        self.assertEqual(b.comments, {}, "a rationale posted for a hold that cannot land")

    def test_a_retry_after_a_failed_label_write_posts_no_second_rationale(self):
        b = Board([alert("ASK-1")], update_ok=False)
        with self.assertRaises(RuntimeError):
            triage.do_hold(b, b.reread("ASK-1"), "noise", True)
        b.update_ok = True
        triage.do_hold(b, b.reread("ASK-1"), "noise", True)
        self.assertEqual(len(b.comments["uuid-ASK-1"]), 1, "one rationale per retry")


class TestD9ABodylessPromoteIsNeverAHold(unittest.TestCase):
    """R8: `if PROMOTE and body: promote else: hold` sent a PROMOTE with an empty
    body into the HOLD arm -- inverting the verdict and removing real work."""

    def test_a_bodyless_promote_is_a_failure_not_a_decision(self):
        self.assertIsNone(triage.parse_verdict("PROMOTE"))
        self.assertIsNone(triage.parse_verdict("PROMOTE\n\n   \n"))

    def test_the_lane_leaves_it_untouched_for_tomorrow(self):
        b = Board([alert("ASK-1")])
        rc, _, _ = run_lane(b, lambda i: triage.parse_verdict("PROMOTE\n"))
        self.assertNotEqual(rc, 0)
        self.assertTrue(triage.is_alert_ticket(b.issues["ASK-1"]["description"]))
        self.assertNotIn(triage.HELD_LABEL, b.labels_of("ASK-1"))
        self.assertEqual(b.mutations(), [])

    def test_an_unknown_verdict_writes_nothing(self):
        b = Board([alert("ASK-1")])
        run_lane(b, says("CLOSE", "it is noise"))
        self.assertEqual(b.mutations(), [])

    def test_a_bodyless_hold_has_no_rationale_so_it_is_no_decision_either(self):
        self.assertIsNone(triage.parse_verdict("HOLD"))

    def test_real_verdicts_parse(self):
        """Negative control."""
        self.assertEqual(triage.parse_verdict("PROMOTE\n" + DOR), ("PROMOTE", DOR.strip()))
        self.assertEqual(triage.parse_verdict("```\nHOLD\nnoise\n```"), ("HOLD", "noise"))


class TestD10TheLaneNeverPromotesAnUnroutableAlert(unittest.TestCase):
    """R9: an alert without owner:sana was promoted out of triage and left
    permanently worker-ineligible. #275 fixed the manual path; the lane has to
    go through the same single precondition function."""

    def test_an_alert_without_owner_sana_stays_an_alert(self):
        b = Board([alert("ASK-1", labels=("needs-triage",))])
        run_lane(b, says("PROMOTE", DOR))
        self.assertTrue(triage.is_alert_ticket(b.issues["ASK-1"]["description"]))
        self.assertFalse([v for q, v in b.mutations()
                          if "description" in (v.get("input") or {})])


class TestLaneBookkeeping(unittest.TestCase):

    def test_a_dry_run_exits_zero_and_claims_no_writes(self):
        b = Board([alert("ASK-1", created="2026-08-01"), alert("ASK-2", created="2026-08-02")])
        verdicts = {"ASK-1": ("PROMOTE", DOR), "ASK-2": ("HOLD", "noise")}
        rc, out, _ = run_lane(b, lambda i: verdicts[i["identifier"]], apply=False)
        self.assertEqual(rc, 0)
        self.assertEqual(b.mutations(), [])
        self.assertIn("0 written", out)
        self.assertIn("WOULD PROMOTE", out)
        self.assertIn("WOULD HOLD", out)

    def test_held_alerts_leave_the_pool(self):
        b = Board([alert("ASK-1", labels=("owner:sana", "needs-triage", "triage:held")),
                   alert("ASK-2")], team_labels=("owner:sana", "needs-triage", "triage:held"))
        seen = []
        run_lane(b, lambda i: (seen.append(i["identifier"]), None)[1])
        self.assertEqual(seen, ["ASK-2"])

    def test_the_limit_bounds_the_batch_oldest_first(self):
        b = Board([alert("ASK-3", created="2026-08-03"), alert("ASK-1", created="2026-08-01"),
                   alert("ASK-2", created="2026-08-02")])
        seen = []
        rc, out, _ = run_lane(b, lambda i: (seen.append(i["identifier"]), None)[1], limit=2)
        self.assertEqual(seen, ["ASK-1", "ASK-2"])
        self.assertIn("1 still queued", out)

    def test_promotion_clears_a_previous_hold(self):
        b = Board([alert("ASK-1", labels=("owner:sana", "needs-triage", "triage:held"))],
                  team_labels=("owner:sana", "needs-triage", "triage:held"))
        out = triage.do_promote(b, b.reread("ASK-1"), DOR, "by hand", True)
        self.assertTrue(out.wrote, out.line)
        self.assertNotIn(triage.HELD_LABEL, b.labels_of("ASK-1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
