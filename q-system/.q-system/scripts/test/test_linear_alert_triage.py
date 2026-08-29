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
        rest' after the unattended lane was split out to ASK-1133."""
        cli = (SCRIPTS.parent.parent.parent / "kipi").read_text(encoding="utf-8")
        usage = [l for l in cli.split("\n") if "kipi alert-triage" in l and "echo" in l]
        self.assertTrue(usage, "the verb is no longer documented at all")
        self.assertNotIn("hold", usage[0].lower(),
                         "the CLI advertises a hold operation that does not exist")


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
