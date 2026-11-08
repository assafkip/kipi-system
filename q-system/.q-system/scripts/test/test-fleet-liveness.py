#!/usr/bin/env python3
"""test-fleet-liveness.py -- every board state has an exit by age, or a dated debt (RULE-2026-11-07-B, ASK-3953).

THE INVARIANT. Every open ticket and PR, in every state, is younger than its
state's max age or has had its state's coded exit fire. This file holds the half a
test can hold in CI: every state a ticket can sit in has a row in
terminal-states.json `ticket_states`, and every row has either a consumer that takes
items out BY AGE (a file, a literal marker in it, and a declared test that proves it
fires) or an open debt (the ticket that builds that exit, expiring at most 30 days
after it was written). The dates are read daily, with a real clock, by
fleet-health-daily.py's liveness-debt-expired detector, never here: a wall clock in
a PR gate is the calendar bomb PR #465 shipped.

WHY. The 08-16 meter chose "IT FLAGS, IT NEVER CLOSES", and until 11-06 no ticket
state had an exit by age. The per-site registry (ASK-353) let a written rationale
stand in for a coded exit, so 31 of its 53 rows name no consumer and every half-port
passed it (P5 in stuck-work-synthesis-2026-11-07.md).

COVERAGE. Every `states` row of a ticket-holding class (durable-queue,
selection-filter, exhausted-counter, error-path) is covered by a ticket_states row
or listed in `not_a_state` with its reason. test-terminal-states.sh already forces
every exit site in the drivers to have a `states` row, so together a new stop in a
driver cannot land without a dated exit.

RED FIRST. On main at 5d281a28 the table has no ticket_states, so this prints RED and
exits 1, naming every ticket-holding row with no exit by age.

MUTANTS, on in-memory copies (the repo file is never written): a row deleted, a debt
of 31 days, a consumer marker that is not in its file, a new holding state with no
row, a state whose only exit drains by order, and a by-age exit removed.

Run: python3 q-system/.q-system/scripts/test/test-fleet-liveness.py   (exit 0 = pass)
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
REPO = SCRIPTS.parents[2] if len(SCRIPTS.parents) > 2 else SCRIPTS
TABLE = Path(os.environ.get("KIPI_LIVENESS_TABLE") or REPO / "q-system" / ".q-system" / "terminal-states.json")
FRAGMENTS = REPO / "q-system" / ".q-system" / "capability" / "expected_tests"
HOLDING = ("durable-queue", "selection-filter", "exhausted-counter", "error-path")
MAX_DEBT_DAYS = 30
TICKET = re.compile(r"^ASK-\d+$")

FAILS: list[str] = []


def check(name, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(name)


def _day(text):
    return datetime.strptime(str(text), "%Y-%m-%d").date()


def violations(data: dict, repo: Path = REPO) -> list[str]:
    """Every way the table fails the invariant. Pure apart from reading the files it names."""
    out: list[str] = []
    states = {s["id"]: s for s in data.get("states") or []}
    ts = data.get("ticket_states")
    holding = sorted(sid for sid, s in states.items() if s.get("class") in HOLDING)
    if not ts:
        return [f"no ticket_states table: {len(holding)} ticket-holding states have no exit by age "
                f"({', '.join(holding)})"]
    covered: set[str] = set()
    for rid, row in sorted((ts.get("rows") or {}).items()):
        age = row.get("max_age_days")
        if not isinstance(age, int) or isinstance(age, bool) or age <= 0:
            out.append(f"{rid}: max_age_days must be a positive integer, got {age!r}")
        live = False
        exits = row.get("exits") or []
        if not exits:
            out.append(f"{rid}: no exit at all")
        for i, e in enumerate(exits):
            where = f"{rid} exit {i}"
            kind = e.get("kind")
            if kind == "consumer":
                path, marker, test = repo / str(e.get("path", "")), str(e.get("marker", "")), str(e.get("test", ""))
                fires = e.get("fires")
                ok = True
                if fires not in ("by-age", "by-order"):
                    out.append(f"{where}: fires must be by-age or by-order, got {fires!r}")
                    ok = False
                if not path.is_file():
                    out.append(f"{where}: consumer {e.get('path')!r} is not a file on this tree")
                    ok = False
                elif not marker or marker not in path.read_text(errors="replace"):
                    out.append(f"{where}: marker {marker!r} is not in {e.get('path')}")
                    ok = False
                if not (repo / test).is_file():
                    out.append(f"{where}: test {test!r} is not a file on this tree")
                    ok = False
                elif not (repo / FRAGMENTS.relative_to(REPO) / (test.replace("/", "__") + ".json")).is_file():
                    out.append(f"{where}: test {test!r} has no expected_tests fragment, so CI never runs it")
                    ok = False
                if ok and fires == "by-age":
                    live = True
            elif kind == "debt":
                ok = True
                if not TICKET.match(str(e.get("ticket", ""))):
                    out.append(f"{where}: a debt names its ticket as ASK-<n>, got {e.get('ticket')!r}")
                    ok = False
                try:
                    days = (_day(e.get("expires")) - _day(e.get("since"))).days
                    if not 0 < days <= MAX_DEBT_DAYS:
                        out.append(f"{where}: a debt runs 1 to {MAX_DEBT_DAYS} days, this one {days}")
                        ok = False
                except ValueError:
                    out.append(f"{where}: since and expires must be YYYY-MM-DD")
                    ok = False
                live = live or ok
            else:
                out.append(f"{where}: kind must be consumer or debt, got {kind!r}")
        if not live:
            out.append(f"{rid}: no by-age consumer and no open debt, so nothing takes items out by age")
        for c in row.get("covers") or []:
            if c not in states:
                out.append(f"{rid}: covers {c!r}, which is not a states row")
            covered.add(c)
    nas = ts.get("not_a_state") or {}
    for sid, why in sorted(nas.items()):
        if sid not in states:
            out.append(f"not_a_state {sid!r} is not a states row")
        if not str(why).strip():
            out.append(f"not_a_state {sid!r} gives no reason")
    for sid in holding:
        if sid not in covered and sid not in nas:
            out.append(f"{sid} ({states[sid]['class']}) holds tickets and no ticket_states row covers it")
    return out


print("test-fleet-liveness.py")
data = json.loads(TABLE.read_text())
if not data.get("ticket_states"):
    print("RED: " + violations(data)[0])
    sys.exit(1)

print("-- the table on this tree")
found = violations(data)
for v in found:
    print(f"  FAIL {v}")
check("every board state has a by-age exit or an open, bounded debt", found, [])
rows = data["ticket_states"]["rows"]
check("the section 5 states are all present", set(rows) >= set([
    "needs-triage-alert", "no-project", "no-checkout", "repo-refused", "blocked-capability",
    "attempts-exhausted", "ready-over-cap", "started-dormant", "owner-assaf", "open-pr"]), True)
by_age = sorted(r for r, row in rows.items()
                if any(e.get("kind") == "consumer" and e.get("fires") == "by-age" for e in row["exits"]))
print(f"  (states with a by-age exit built: {', '.join(by_age)}; the rest carry dated debts)")


def mutant(label, change, expect):
    m = copy.deepcopy(data)
    change(m)
    got = violations(m)
    hit = [v for v in got if expect in v]
    check(f"mutant goes red: {label}", bool(hit), True)


print("-- mutants: each must go red")
mutant("a row deleted", lambda m: m["ticket_states"]["rows"].pop("blocked-capability"),
       "blocked-capability (durable-queue) holds tickets")
mutant("a debt of 31 days",
       lambda m: m["ticket_states"]["rows"]["owner-assaf"]["exits"][0].update(expires="2026-12-09"),
       "this one 31")
mutant("a consumer marker that is not in its file",
       lambda m: m["ticket_states"]["rows"]["started-dormant"]["exits"][0].update(marker="def no_such_function"),
       "is not in")
mutant("a new ticket-holding stop with no row",
       lambda m: m["states"].append({"id": "new-stop", "class": "durable-queue"}),
       "new-stop (durable-queue) holds tickets")
mutant("a state whose only exit drains by order",
       lambda m: m["ticket_states"]["rows"]["needs-triage-alert"].update(
           exits=m["ticket_states"]["rows"]["needs-triage-alert"]["exits"][:1]),
       "needs-triage-alert: no by-age consumer and no open debt")
mutant("a by-age exit removed",
       lambda m: m["ticket_states"]["rows"]["started-dormant"].update(exits=[]),
       "started-dormant: no exit at all")
mutant("a consumer test with no fragment",
       lambda m: m["ticket_states"]["rows"]["started-dormant"]["exits"][0].update(
           test="q-system/.q-system/scripts/test/no-such-test.py"),
       "is not a file on this tree")

print("-- the dated reader: fleet-health-daily.py liveness-debt-expired")
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("fh_liveness", SCRIPTS / "fleet-health-daily.py")
fh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fh)
debts = sum(1 for row in rows.values() for e in row["exits"] if e.get("kind") == "debt")
latest = max(_day(e["expires"]) for row in rows.values() for e in row["exits"] if e.get("kind") == "debt")
check("no finding while every debt is open",
      fh.liveness_debt_findings(TABLE, today=min(_day(e["since"]) for row in rows.values()
                                                 for e in row["exits"] if e.get("kind") == "debt")), [])
late = fh.liveness_debt_findings(TABLE, today=date.fromordinal(latest.toordinal() + 1))
check("the day after the last expiry, one finding per debt", len(late), debts)
check("each finding names its state and ticket", all("Liveness debt expired" in f["title"] for f in late), True)
check("an unreadable table is a finding, never zero",
      [f["subject"] for f in fh.liveness_debt_findings(SCRIPTS / "no-such-table.json")], ["liveness-debt-blind"])
check("the detector is registered to file",
      {d["id"]: d for d in fh.DETECTORS}.get("liveness-debt-expired", {}).get("action"), "file_issue")

print()
if FAILS:
    print(f"FAIL: {len(FAILS)} check(s): " + "; ".join(FAILS))
    sys.exit(1)
print("PASS")
