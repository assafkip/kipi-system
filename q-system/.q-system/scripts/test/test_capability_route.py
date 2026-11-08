#!/usr/bin/env python3
"""test_capability_route.py: an unprobeable blocked:capability ticket never just stays (ASK-3960).

Measured 2026-11-08: 50 parked across the dispatch targets, 50 unprobeable, 0
clearable. Founder, 2026-11-08: "but what happens if nothing changed? the ticket
just stays?" So at day 14 each unprobeable block takes a route by the capability
its park comment names, and this pins every route.

Drives route_unprobeable() in-process with a fake Linear (comments only), a
recorded linear-sync (_sync swapped), a REAL attempts ledger in a temp dir, and
a fake cap-ladder.py beside a temp copy of the module so --founder-ask is
recorded rather than written. No live path is touched: KIPI_ATTEMPTS and
CAP_LADDER_STATUS point into the temp dir before the module is imported.

RED ON MAIN: capability_block_expiry.py is not on main at all.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SRC = HERE / "capability_block_expiry.py"
FAILS: list = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else f"\n       {str(detail)[:500]}"))
    if not ok:
        FAILS.append(name)


class FakeLinear:
    class LinearAPIError(Exception):
        pass

    def __init__(self, bodies):
        self.bodies = bodies

    def graphql(self, query, variables):
        nodes = [{"body": b, "createdAt": f"2026-10-0{n + 1}T00:00:00Z"}
                 for n, b in enumerate(self.bodies.get(variables["id"], []))]
        return {"issue": {"comments": {"nodes": nodes}}}


def load(td: Path):
    """A temp copy of the module beside the real ledger and a fake cap-ladder.py."""
    for f in ("capability_block_expiry.py", "attempts-ledger.py", "linear-sync.py"):
        shutil.copy(HERE / f, td / f)
    (td / "cap-ladder.py").write_text(
        "import json, sys, os\n"
        "open(os.environ['W'] + '/ladder.log', 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "print('cap-ladder: ask added')\n")
    os.environ.update(W=str(td), KIPI_ATTEMPTS=str(td / "attempts.json"), CAP_LADDER_STATUS=str(td / "status.jsonl"))
    (td / "attempts.json").write_text("{}")
    spec = importlib.util.spec_from_file_location("cbe_t", str(td / "capability_block_expiry.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    calls = []
    m._sync = lambda *a: (calls.append(list(a)) or (0, "ok"))
    return m, calls


def ledger(td: Path) -> dict:
    return json.loads((td / "attempts.json").read_text())


def lines(td: Path, name: str) -> list:
    p = td / name
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


PARK = "**Blocked on a missing capability, not on scope.** Labelled `blocked:capability`.\n"
OLD, NOW = "2026-10-01T00:00:00Z", "2026-11-08T21:00:00+00:00"


def main() -> int:
    print("test_capability_route.py")
    if not SRC.exists():
        check("capability_block_expiry.py exists", False, "no probe runner: every block stays forever")
        return 1
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        m, calls = load(td)
        check("classify: a .claude/ write is claude-write",
              m.classify(PARK + "Sana: the Write tool refuses .claude/rules/x.md") == "claude-write")
        check("classify: a missing token is credential", m.classify(PARK + "Codex: no API key for the vendor") == "credential")
        check("classify: anything else is unknown", m.classify(PARK + "Sana: the build tool is not installed") == "unknown")

        ls = FakeLinear({"ASK-570": [PARK + "Sana: the Write tool refuses .claude/settings.json"],
                         "ASK-148": [PARK + "Sana: the vendor login is missing for this account"],
                         "ASK-7": [PARK + "Sana: nothing here can do it"]})
        out = m.route_unprobeable(ls, "ASK-7", "2026-11-01T00:00:00Z", True, NOW)
        check("under 14 days: no writes, and the line names the route date",
              not calls and "2026-11-15" in out and not ledger(td).get("ASK-7"), out)

        out = m.route_unprobeable(ls, "ASK-570", OLD, True, NOW)
        check("claude-write at day 14: unblocked, told the apply-claude-changes.sh path, requeued",
              ["unblock", "ASK-570", "blocked:capability"] in calls
              and any(c[0] == "progress" and "apply-claude-changes.sh" in c[2] for c in calls)
              and any(c[:2] == ["requeue", "ASK-570"] for c in calls), (out, calls))
        calls.clear()
        out = m.route_unprobeable(ls, "ASK-570", "2026-10-02T00:00:00Z", True, NOW)
        check("claude-write parked AGAIN: no second requeue; handed to cap-ladder.py as a capout",
              ledger(td).get("ASK-570", {}).get("capout") is True
              and not any(c[:1] == ["requeue"] for c in calls), (out, calls, ledger(td)))

        out = m.route_unprobeable(ls, "ASK-148", OLD, True, NOW)
        asks = lines(td, "ladder.log")
        check("credential at day 14: one ask through cap-ladder.py --founder-ask, the label stays",
              any(a[:2] == ["--founder-ask", "ASK-148"] for a in asks)
              and not any(c[:2] == ["unblock", "ASK-148"] for c in calls), (out, asks))
        check("credential: the module never writes the status file itself (one writer)",
              not (td / "status.jsonl").exists())

        calls.clear()
        out = m.route_unprobeable(ls, "ASK-7", OLD, True, NOW)
        check("unknown at day 14: handed to cap-ladder.py as a capout, and unblocked",
              ledger(td).get("ASK-7", {}).get("capout") is True
              and ["unblock", "ASK-7", "blocked:capability"] in calls, (out, calls))

        before = json.dumps(ledger(td))
        dry = m.route_unprobeable(ls, "ASK-999", OLD, False, NOW)
        check("dry: says what it would do and writes nothing",
              "would" in dry and json.dumps(ledger(td)) == before, dry)

        os.environ["KIPI_LINEAR_API_URL"] = "http://127.0.0.1:9/graphql"
        del os.environ["CAP_LADDER_STATUS"]
        out = m.route_unprobeable(ls, "ASK-7", OLD, True, NOW)
        check("a fixture Linear without its own ledger and status paths refuses to route",
              "REFUSED" in out, out)
        del os.environ["KIPI_LINEAR_API_URL"]

        # MUTANT: a route that ignores the 14-day gate must turn the first case red.
        mut = (td / "capability_block_expiry.py").read_text().replace(
            "if parked and now - parked < timedelta(days=ROUTE_AFTER_DAYS):", "if False:", 1)
        (td / "mut.py").write_text(mut)
        spec = importlib.util.spec_from_file_location("cbe_mut", str(td / "mut.py"))
        mm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mm)
        mm._sync = lambda *a: (0, "ok")
        os.environ["CAP_LADDER_STATUS"] = str(td / "status.jsonl")
        out = mm.route_unprobeable(FakeLinear({"ASK-8": [PARK + "nothing"]}), "ASK-8",
                                   "2026-11-01T00:00:00Z", True, NOW)
        check("mutant: a route with no 14-day gate acts on a 7-day park (so the gate case can fail)",
              "2026-11-15" not in out, out)
    print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
