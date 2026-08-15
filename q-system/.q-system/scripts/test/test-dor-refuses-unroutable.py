#!/usr/bin/env python3
"""The DoR drafter refuses the two issue shapes a DoR cannot help (ASK-839).

THE DEFECT. linear-dor-drafter.py selected on state + description alone. It
therefore drafted a Definition of Ready onto:

  1. fleet alert tickets filed by alert-to-linear.py, whose body is a raw alert
     line ("auto-commit left 3 file(s) uncommitted") that nobody scoped, and
  2. issues with no project at all, which linear-worker.sh cannot route to any
     checkout because in_this_repo() is false for them in every repo at once.

Writing a DoR onto either does not make it executable. It makes it READY-SHAPED,
and ready-shaped is the only thing the worker queue checks. So the drip was
manufacturing permanently-unreachable work, one batch a night.

MEASURED against the live ASK board 2026-08-15: 81 open alert tickets, 19 of
them already drafted onto, and all 19 sat in the UNREACHABLE bucket -- 43% of it.
62 more were still queued for the same treatment.

This is the second question ASK-839 asked in so many words ("should the DoR
drafter refuse to draft onto a project-unset issue?"). The answer is yes, and
this file is the answer in a form that can fail.

Run: python3 q-system/.q-system/scripts/test/test-dor-refuses-unroutable.py
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# REF HATCH, copied from test-worker-project-scope.sh. Points the suite at a
# different copy of the drafter so the PRE-FIX one can be checked out of a git
# ref and watched to FAIL. A regression case added after its own fix has never
# been observed red, and an unobserved-red case asserts nothing.
#
#   git show <ref>:q-system/.q-system/scripts/linear-dor-drafter.py > /tmp/old.py
#   KIPI_DRAFTER_UNDER_TEST=/tmp/old.py python3 test-dor-refuses-unroutable.py
DRAFTER = os.environ.get("KIPI_DRAFTER_UNDER_TEST") or os.path.join(
    HERE, "..", "linear-dor-drafter.py")

PASS, FAIL = 0, 0


def ok(name):
    global PASS
    PASS += 1
    print(f"  ok   {name}")


def bad(name, detail=""):
    global FAIL
    FAIL += 1
    print(f"  FAIL {name}\n     {detail}")


def load(path):
    spec = importlib.util.spec_from_file_location("dor_drafter_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def issue(ident, project=None, desc="", labels=(), state="backlog"):
    """The shape ISSUES_Q returns. Fields copied from that query, not invented:
    a fixture built from a guess tests the guess (feedback_fixtures_from_producers)."""
    return {
        "id": ident, "identifier": ident, "title": "fixture " + ident,
        "description": desc,
        "project": ({"name": project} if project else None),
        "state": {"name": state, "type": state},
        "labels": {"nodes": [{"id": n, "name": n} for n in labels]},
    }


ALERT_BODY = (
    "Filed automatically by the fleet alert path.\n\n"
    "```\n[consulting] auto-commit left 3 file(s) uncommitted\n```\n\n"
    "<!-- kipi-alert-fingerprint: deadbeefdeadbeef -->"
)


def run(mod, label):
    print(f"== DoR drafter selection ({label})")

    # The control. Without it every assertion below is satisfied by a
    # selection_mode() that returns None for everything.
    normal = issue("ASK-800", project="kipi-system", desc="just a description")
    if mod.selection_mode(normal) == "draft":
        ok("still drafts an ordinary routable issue (ASK-800)")
    else:
        bad("still drafts an ordinary routable issue (ASK-800)",
            f"selection_mode returned {mod.selection_mode(normal)!r}")

    alert_routed = issue("ASK-801", project="kipi-system", desc=ALERT_BODY)
    if mod.selection_mode(alert_routed) is None:
        ok("refuses a fleet alert ticket even when it HAS a project (ASK-801)")
    else:
        bad("refuses a fleet alert ticket even when it HAS a project (ASK-801)",
            f"selection_mode returned {mod.selection_mode(alert_routed)!r} -- "
            "an alert is not dispatch work whether or not it is routable")

    alert_unset = issue("ASK-802", project=None, desc=ALERT_BODY)
    if mod.selection_mode(alert_unset) is None:
        ok("refuses a project-unset fleet alert ticket (ASK-802)")
    else:
        bad("refuses a project-unset fleet alert ticket (ASK-802)",
            f"selection_mode returned {mod.selection_mode(alert_unset)!r}")

    unset = issue("ASK-803", project=None, desc="a real engineering issue, no project")
    if mod.selection_mode(unset) is None:
        ok("refuses a project-unset issue: a DoR would make it ready and "
           "unreachable (ASK-803)")
    else:
        bad("refuses a project-unset issue (ASK-803)",
            f"selection_mode returned {mod.selection_mode(unset)!r} -- drafting "
            "onto an unroutable ticket promotes it into a queue nothing serves")

    # The redrive path runs BEFORE the project test in selection_mode, so it has
    # its own case: an issue Sana refused is re-scoped by this job, and losing
    # that path would silently strand every needs-scope issue.
    redrive = issue("ASK-804", project="kipi-system",
                    desc="## Definition of Ready\nOutcome: x",
                    labels=(mod.NEEDS_SCOPE_LABEL,))
    if mod.selection_mode(redrive) == "redraft":
        ok("the needs-scope redrive still works (ASK-804)")
    else:
        bad("the needs-scope redrive still works (ASK-804)",
            f"selection_mode returned {mod.selection_mode(redrive)!r}")


run(load(DRAFTER), os.path.basename(DRAFTER))
print()
print(f"  {PASS} passed, {FAIL} failed")
sys.exit(0 if FAIL == 0 else 1)
