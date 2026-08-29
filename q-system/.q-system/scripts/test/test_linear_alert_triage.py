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


class TestUnattendedLaneExists(unittest.TestCase):
    """codex review of PR #268, major 1: nothing invoked this script, so the
    consumer did not exist operationally."""

    def test_a_scheduled_caller_references_this_script(self):
        import plistlib
        plist = SCRIPTS / "com.kipi.linear-alert-triage.plist"
        self.assertTrue(plist.exists(), "no scheduled caller ships with the script")
        d = plistlib.loads(plist.read_bytes())
        cmd = " ".join(d["ProgramArguments"])
        self.assertIn("alert-triage", cmd, "the scheduled job must run the triage verb")
        self.assertIn("--apply", cmd, "a scheduled pass that never writes is a no-op")
        # The FULL chain, because the plist alone is not enough: a .plist is not
        # one of capability-gate's WIRING_SURFACES, so a script reachable only
        # from a plist still reports inert-engine. `kipi*` IS a surface, which is
        # why the dor lane is wired as a CLI verb and scheduled through it.
        cli = (SCRIPTS.parent.parent.parent / "kipi").read_text(encoding="utf-8")
        self.assertIn("alert-triage)", cli, "no kipi CLI verb, so the gate sees it inert")
        self.assertIn("linear-alert-triage.py", cli,
                      "the kipi verb must reference the script by path")

    def test_triage_promotes_on_promote_and_holds_on_hold(self):
        issues = [dict(as_issue(ALERT_DESC), identifier="ASK-9", id="issue-id",
                       createdAt="2026-01-01", title="t")]
        for verdict, expect_marker_gone in (("PROMOTE", True), ("HOLD", False)):
            f = FakeLinear()
            orig_fetch, orig_decide = triage.fetch_open, triage.decide
            triage.fetch_open = lambda ls, proj: issues
            triage.decide = lambda i, timeout=300: (verdict, "## Definition of Ready\n\n- x")
            try:
                triage.run_triage(f, "kipi-system", 5, True)
            finally:
                triage.fetch_open, triage.decide = orig_fetch, orig_decide
            self.assertFalse(f.sent("stateId"),
                             "the unattended lane must NEVER close an issue")
            payload = [v for q, v in f.calls if "issueUpdate" in q][0]["input"]
            if expect_marker_gone:   # PROMOTE rewrites the body, marker stripped
                self.assertFalse(triage.is_alert_ticket(payload["description"]))
            else:                    # HOLD is a label delta and touches no body
                self.assertNotIn("description", payload)
                self.assertIn("addedLabelIds", payload)

    def test_held_issues_leave_the_nightly_pool(self):
        self.assertTrue(triage.is_held(as_issue(ALERT_DESC, labels=("triage:held",))))
        self.assertFalse(triage.is_held(as_issue(ALERT_DESC, labels=("owner:sana",))),
                         "an unheld alert must stay in the pool")

    def test_a_held_ticket_is_still_an_alert(self):
        """Holding records a triage decision; only PROMOTION clears alert-ness.
        A held ticket the worker could pick up would be the ASK-839 regression."""
        held = as_issue(ALERT_DESC, labels=("owner:sana", "triage:held"))
        self.assertTrue(triage.is_alert_ticket(held["description"]))
        self.assertTrue(IS_FLEET_ALERT(held),
                        "a held ticket became worker-eligible")


class TestHoldIsNeverSilentOrStale(unittest.TestCase):
    """codex rounds 2 and 3. Hold accumulated three defects of one class, so it
    stopped being guarded and became a label delta instead."""

    def _fake(self, fresh, comment_ok=True, labels=()):
        class L:
            def __init__(s):
                s.calls = []
            def graphql(s, q, v):
                s.calls.append((q, v))
                if "issueLabels" in q:
                    return {"issueLabels": {"nodes": [
                        {"id": "held-id", "name": "triage:held"}]}}
                if "issue(" in q:
                    return {"issue": {"id": "uuid", "identifier": "ASK-1",
                                      "description": fresh,
                                      "labels": {"nodes": [{"id": f"i{n}", "name": n}
                                                           for n in labels]}}}
                if "commentCreate" in q:
                    return {"commentCreate": {"success": comment_ok}}
                if "issueUpdate" in q:
                    return {"issueUpdate": {"success": True,
                                            "issue": {"identifier": "ASK-1"}}}
                return {}
            def updates(s):
                return [v["input"] for q, v in s.calls if "issueUpdate" in q]
        return L()

    def test_hold_never_writes_a_description(self):
        """THE anti-clobber property (round 3, major 1). A hold that rewrites the
        body from a stale read deletes a DoR written during the model call. A label
        is a server-side delta, so it cannot."""
        f = self._fake(ALERT_DESC)
        triage.do_hold(f, {"identifier": "ASK-1"}, "why", True)
        for payload in f.updates():
            self.assertNotIn("description", payload,
                             "hold wrote a description and can clobber a promotion")
        self.assertIn("addedLabelIds", f.updates()[0])

    def test_hold_refuses_when_the_rationale_comment_fails(self):
        f = self._fake(ALERT_DESC, comment_ok=False)
        with self.assertRaises(RuntimeError) as cm:
            triage.do_hold(f, {"identifier": "ASK-1"}, "model rationale", True)
        self.assertIn("refusing to hold", str(cm.exception))
        self.assertEqual(f.updates(), [], "the hold landed despite no rationale")

    def test_hold_skips_an_issue_promoted_while_the_model_ran(self):
        promoted = triage.promote_body(ALERT_DESC, DOR, "fp", "")
        f = self._fake(promoted)
        res = triage.do_hold(f, {"identifier": "ASK-1"}, "x", True)
        self.assertIn("SKIPPED", res.line)
        self.assertFalse(res.wrote, "a skip was reported as a write")
        self.assertEqual(f.updates(), [])

    def test_hold_still_works_on_a_real_alert(self):
        """Negative control: no guard may block the good path."""
        f = self._fake(ALERT_DESC)
        res = triage.do_hold(f, {"identifier": "ASK-1"}, "why", True)
        self.assertIn("HELD", res.line)
        self.assertTrue(res.wrote)

    def test_held_ness_is_read_from_labels_only(self):
        self.assertTrue(triage.is_held(as_issue(ALERT_DESC, labels=("triage:held",))))
        self.assertFalse(triage.is_held(as_issue(ALERT_DESC, labels=("owner:sana",))))

    def test_missing_hold_label_raises_rather_than_no_ops(self):
        class NoLabel:
            def graphql(s, q, v):
                return {"issueLabels": {"nodes": []}}
        with self.assertRaises(RuntimeError):
            triage.held_label_id(NoLabel())

    def test_every_write_path_reads_its_comment_result(self):
        """THE CLASS, not the instances. A new write path that comments and ignores
        the result would pass every test above and reintroduce the bug."""
        import inspect
        src = inspect.getsource(triage)
        for fn in ("do_close", "do_hold"):
            body = src.split(f"def {fn}(")[1].split("\ndef ")[0]
            self.assertIn("COMMENT_M", body, f"{fn} no longer comments")
            self.assertIn("commentCreate", body,
                          f"{fn} sends a comment and never reads whether it landed")

    def test_only_one_description_writer_remains(self):
        """Fable's refutation condition, kept executable. Two full-replace writers
        is the condition under which patching one relocates the race instead of
        closing it."""
        import inspect
        writers = inspect.getsource(triage).count('"description":')
        self.assertEqual(writers, 1,
                         f"{writers} description writers; a second one revives the "
                         "clobber class that hold was just redesigned to escape")


class TestUnattendedRunReportsTotalFailure(unittest.TestCase):
    """codex round 3, major 2: exit 0 on a night where nothing worked."""

    def _run(self, decide_result, n=2):
        issues = [dict(as_issue(ALERT_DESC), identifier=f"ASK-{i}", id=f"u{i}",
                       createdAt="2026-01-01", title="t") for i in range(n)]
        class L:
            def graphql(s, q, v):
                if "issueLabels" in q:
                    return {"issueLabels": {"nodes": [{"id": "h", "name": "triage:held"}]}}
                if "issue(" in q:
                    return {"issue": {"id": "u", "identifier": "ASK-0",
                                      "description": ALERT_DESC, "labels": {"nodes": []}}}
                if "commentCreate" in q:
                    return {"commentCreate": {"success": True}}
                if "issueUpdate" in q:
                    return {"issueUpdate": {"success": True, "issue": {"identifier": "ASK-0"}}}
                return {}
        of, od = triage.fetch_open, triage.decide
        triage.fetch_open = lambda ls, proj: issues
        triage.decide = lambda i, timeout=300: decide_result
        try:
            return triage.run_triage(L(), "kipi-system", 5, True)
        finally:
            triage.fetch_open, triage.decide = of, od

    def test_total_failure_exits_nonzero(self):
        self.assertEqual(self._run(None), 1,
                         "a night where every decision failed reported success")

    def test_a_working_night_exits_zero(self):
        """Negative control: the new exit code must not fire on a good run."""
        self.assertEqual(self._run(("HOLD", "not executable")), 0)

    def test_an_empty_batch_exits_zero(self):
        self.assertEqual(self._run(None, n=0), 0,
                         "nothing to triage is success, not an outage")


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


class TestNothingWrittenIsNotAQuietNight(unittest.TestCase):
    """codex round 5. A refuse path counted as a success made a fully-skipped
    batch exit 0, the same silent-success class as the total-model-failure fix one
    round earlier. Fixed at the class: the write status is now typed data."""

    def _run(self, desc, n=2, project="kipi-system", fresh=None):
        """`desc` is what SELECTION sees; `fresh` is what the re-read returns.
        They differ exactly when a rival promotion lands during the model call,
        which is the only way every write legitimately refuses."""
        fresh = desc if fresh is None else fresh
        issues = [dict(as_issue(desc), identifier=f"ASK-{i}", id=f"u{i}",
                       createdAt="2026-01-01", title="t",
                       project={"name": project} if project else None)
                  for i in range(n)]
        class L:
            def graphql(s, q, v):
                if "issueLabels" in q:
                    return {"issueLabels": {"nodes": [{"id": "h", "name": "triage:held"}]}}
                if "issue(" in q:
                    return {"issue": {"id": "u", "identifier": "ASK-0",
                                      "description": fresh, "labels": {"nodes": []}}}
                if "commentCreate" in q:
                    return {"commentCreate": {"success": True}}
                if "issueUpdate" in q:
                    return {"issueUpdate": {"success": True, "issue": {"identifier": "ASK-0"}}}
                return {}
        of, od = triage.fetch_open, triage.decide
        triage.fetch_open = lambda ls, proj: issues
        triage.decide = lambda i, timeout=300: ("HOLD", "not executable")
        try:
            return triage.run_triage(L(), None, 5, True)
        finally:
            triage.fetch_open, triage.decide = of, od

    def test_a_batch_that_writes_nothing_exits_nonzero(self):
        """Every issue is already promoted, so every do_hold refuses. Nothing is
        written, and the old code called that a successful night."""
        promoted = triage.promote_body(ALERT_DESC, DOR, "fp", "")
        self.assertEqual(self._run(ALERT_DESC, fresh=promoted), 1,
                         "a pass that wrote nothing reported success")

    def test_a_batch_that_writes_exits_zero(self):
        """Negative control."""
        self.assertEqual(self._run(ALERT_DESC), 0)

    def test_an_issue_with_no_project_is_never_promoted(self):
        """ASK-839's measured harm: promoting an unroutable issue moves it from
        'not ready' to 'ready and reachable by nobody'."""
        self.assertEqual(self._run(ALERT_DESC, project=None), 0,
                         "an empty pool is success, not an outage")


class TestSchedulerCoversTheWholeFleet(unittest.TestCase):
    def test_the_nightly_pass_is_not_pinned_to_one_project(self):
        """codex round 5, major 2. 151 open alert tickets, 55 in kipi-system: a
        single-project scheduler left two thirds of the bucket as inert as before."""
        import plistlib
        d = plistlib.loads((SCRIPTS / "com.kipi.linear-alert-triage.plist").read_bytes())
        cmd = " ".join(d["ProgramArguments"])
        self.assertNotIn("--project", cmd,
                         "the scheduled pass is pinned to one project")
        self.assertIn("--apply", cmd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
