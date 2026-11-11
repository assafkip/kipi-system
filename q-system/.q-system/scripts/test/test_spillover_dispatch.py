"""K9 (ASK-4410, RULE-2026-11-09-B part 3): a spillover ticket with a Definition
of Ready and owner:sana is dispatch work, not a fleet alert.

Pairs with linear-worker.sh is_fleet_alert / ready. Both are lifted VERBATIM out
of the shipped file, because a test carrying its own copy of the predicate cannot
see a condition the real one gained or lost (the same lesson
test_linear_alert_triage.py records).

Scar: spillover tickets are filed through the fleet-alert path, so they carry the
alert marker and ready() skipped every one. Only the nightly triage promoted them,
about 60 a night against about 1,094 queued, so a lane waiting on one waited weeks.
The exemption is narrow on purpose: test_linear_alert_triage.py pins that a DoR on
an ordinary alert must stay refused (ASK-839), and that test is not edited here.
"""
import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
SRC = (SCRIPTS / "linear-worker.sh").read_text(encoding="utf-8")


def _lift():
    m = re.search(r"^ALERT_MARKER = .*?^def is_fleet_alert\(i\):.*?^    return False$",
                  SRC, re.S | re.M)
    assert m, "could not locate is_fleet_alert in linear-worker.sh"
    ns = {}
    exec(compile(m.group(0), "linear-worker.sh:is_fleet_alert", "exec"), ns)
    r = re.search(r"^def ready\(i\):.*?^    return \"## Definition of Ready\" in d "
                  r"or \"Definition of Ready\" in d$", SRC, re.S | re.M)
    assert r, "could not locate ready() in linear-worker.sh"
    ns.update({"repo_project": "kipi-system",
               "project_of": lambda i: ((i.get("project") or {}).get("name") or "")})
    exec(compile("def in_this_repo(i):\n    return project_of(i) == repo_project\n",
                 "in_this_repo", "exec"), ns)
    exec(compile(r.group(0), "linear-worker.sh:ready", "exec"), ns)
    return ns["is_fleet_alert"], ns["ready"]


IS_FLEET_ALERT, READY = _lift()

MARKER = "<!-- kipi-alert-fingerprint: 490d50309e0facdc -->"
# The exact shape spillover-linear-check.py:message_for writes.
SPILL = ("Filed automatically by the fleet alert path.\n\n```\n"
         "spillover defer-prd-x-finding-1 (major) from prd-x: some finding"
         " | owner sana | resolve with prd_runner spillover resolve"
         " defer-prd-x-finding-1 | key juptpkjppito\n```\n\n" + MARKER)
DOR = "\n\n## Definition of Ready\n\n- Reproducer: a test\n- Done: green\n"
PLAIN_ALERT = ("Filed automatically by the fleet alert path.\n\n```\n"
               "main is RED and the auto-merge lane is still live\n```\n\n" + MARKER)


def issue(desc, labels=("owner:sana",)):
    return {"identifier": "ASK-9999", "description": desc,
            "state": {"type": "backlog"}, "project": {"name": "kipi-system"},
            "labels": {"nodes": [{"name": n} for n in labels]}}


def test_spillover_with_dor_and_owner_sana_is_picked():
    i = issue(SPILL + DOR)
    assert IS_FLEET_ALERT(i) is False
    assert READY(i) is True


def test_same_spillover_without_a_dor_is_still_an_alert():
    i = issue(SPILL)
    assert IS_FLEET_ALERT(i) is True
    assert not READY(i)


def test_spillover_with_dor_but_not_owner_sana_is_not_picked():
    i = issue(SPILL + DOR, labels=("owner:assaf",))
    assert not READY(i)
    i = issue(SPILL + DOR, labels=("needs-triage",))
    assert not READY(i)


def test_a_non_spillover_alert_with_a_dor_stays_refused():
    i = issue(PLAIN_ALERT + DOR)
    assert IS_FLEET_ALERT(i) is True
    assert not READY(i)


def test_a_spillover_phrase_in_prose_without_the_marker_is_not_special():
    # No marker: not an alert at all, so ready() decides on the DoR as before.
    i = issue("Discussing spillover resolve flow." + DOR)
    assert IS_FLEET_ALERT(i) is False
