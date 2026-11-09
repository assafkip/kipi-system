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

    PAGE = 2      # small, so a park comment on page 2 proves the cursor is walked

    def __init__(self, bodies):
        self.bodies = bodies

    def graphql(self, query, variables):
        # A body is a string (dated 2026-10-0N by position) or a (createdAt, body) pair.
        nodes = [{"body": b[1], "createdAt": b[0]} if isinstance(b, tuple)
                 else {"body": b, "createdAt": f"2026-10-0{n + 1}T00:00:00Z"}
                 for n, b in enumerate(self.bodies.get(variables["id"], []))]
        if "gte" in query:                      # the server-side createdAt filter
            nodes = [n for n in nodes if n["createdAt"] >= variables["s"]]
        if "$a" not in query:                   # no cursor asked for: the first page only
            return {"issue": {"comments": {"nodes": nodes[:self.PAGE]}}}
        start = int(variables.get("a") or 0)
        page = nodes[start:start + self.PAGE]
        more = start + self.PAGE < len(nodes)
        return {"issue": {"comments": {"nodes": page, "pageInfo": {
            "hasNextPage": more, "endCursor": str(start + self.PAGE) if more else None}}}}


def load(td: Path, ladder: bool = True):
    """A temp copy of the module beside the real ledger and a fake cap-ladder.py."""
    for f in ("capability_block_expiry.py", "attempts-ledger.py", "linear-sync.py"):
        shutil.copy(HERE / f, td / f)
    if ladder:
        (td / "cap-ladder.py").write_text(
            "import json, sys, os\n"
            "open(os.environ['W'] + '/ladder.log', 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "print('cap-ladder: ask added')\n")
    os.environ.update(W=str(td), KIPI_ATTEMPTS=str(td / "attempts.json"), CAP_LADDER_STATUS=str(td / "status.jsonl"),
                      CAPABILITY_EXPIRY_SEEN=str(td / "first-seen.json"))
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


def park_comment(sana: str, codex: str) -> str:
    """The park comment linear-worker.sh writes today, boilerplate and all."""
    return ("**Blocked on a missing capability, not on scope.** Labelled `blocked:capability`; the picker "
            "will not offer it again until the capability exists.\n\nBOTH runners were tried. Neither is "
            f"equipped:\n\n- **Sana (Claude Code):** {sana}\n- **Codex:** {codex}\n\n**The Definition of Ready "
            "is sound.** Do NOT re-scope this.\n\n**Next:** the capability above has to be granted or built. "
            "A harness permission is an authorization decision and belongs to whoever owns the config. "
            "Once it exists, the loop clears this itself.\n\n<!-- capability-probe: none -->")


def review_round1(td: Path) -> None:
    """PR #668 round 1 (claude) and the Codex inline findings, each pinned. Red on e1ff09db."""
    m, calls = load(td)
    # Codex P1: the boilerplate "A harness permission is an authorization decision"
    # sits in EVERY park comment, so every block classified as claude-write.
    cred = park_comment("the vendor API key is not set in this environment", "no token for the vendor")
    check("codex P1: a credential park, boilerplate included, classifies as credential", m.classify(cred) == "credential",
          m.classify(cred))
    check("codex P1: a .claude/ refusal in the runner line still classifies as claude-write",
          m.classify(park_comment("the Write tool refuses .claude/rules/x.md", "sandbox denies it")) == "claude-write")
    check("codex P1: a refusal naming neither is unknown, boilerplate or not",
          m.classify(park_comment("the build tool is not installed", "same")) == "unknown")

    # Codex P2: the one-shot flag is kept only after the unblock landed.
    ls = FakeLinear({"ASK-60": [park_comment("the Write tool refuses .claude/settings.json", "same")]})
    m._sync = lambda *a: (calls.append(list(a)) or ((1, "Linear said no") if a[0] == "unblock" else (0, "ok")))
    out = m.route_unprobeable(ls, "ASK-60", OLD, True, NOW)
    check("codex P2: a failed unblock claims no flag, posts no 'Unblocked' note, requeues nothing; it retries",
          not ledger(td).get("ASK-60", {}).get("capability_route_claude_write")
          and not any(c[0] in ("progress", "requeue") for c in calls) and "retries" in out, (out, calls))
    m._sync = lambda *a: (calls.append(list(a)) or (0, "ok"))

    # Codex P2 + round 1 minor: the park text is THIS park's, read past page 1.
    calls.clear()
    stale = FakeLinear({"ASK-61": [("2026-09-01T00:00:00Z", park_comment("the Write tool refuses .claude/x", "same"))]})
    out = m.route_unprobeable(stale, "ASK-61", OLD, True, NOW)
    check("codex P2: an older park's .claude/ text is not this park's: no claude-write route",
          "claude-write" not in out and not any(c[:1] == ["requeue"] for c in calls), out)
    chatty = FakeLinear({"ASK-62": [("2026-10-02T00:00:00Z", "review round"), ("2026-10-03T00:00:00Z", "reply"),
                                    ("2026-10-04T00:00:00Z", cred)]})
    out = m.route_unprobeable(chatty, "ASK-62", OLD, True, NOW)
    check("round 1 minor: the park comment on page 2 is read (the cursor is walked)",
          out.startswith("unprobeable credential"), out)

    # Round 1 major 2: an undated park never skips the 14 days.
    calls.clear()
    ls = FakeLinear({"ASK-63": [park_comment("nothing here can do it", "same")]})
    out = m.route_unprobeable(ls, "ASK-63", None, True, NOW)
    first = not calls and not ledger(td).get("ASK-63") and "2026-11-22" in out
    out2 = m.route_unprobeable(ls, "ASK-63", None, True, "2026-11-23T05:00:00+00:00")
    check("round 1 major 2: an undated park starts its 14 days the first night it is seen, then routes",
          first and ledger(td).get("ASK-63", {}).get("capout") is True, (out, out2))

    # Round 1 major 1: no cap-ladder.py on the tree, no capout and no unblock.
    with tempfile.TemporaryDirectory() as t2:
        m2, calls2 = load(Path(t2), ladder=False)
        out = m2.route_unprobeable(FakeLinear({"ASK-64": [park_comment("nothing", "same")]}), "ASK-64", OLD, True, NOW)
        check("round 1 major 1: with no cap-ladder.py to consume a capout, the unknown route writes nothing",
              not calls2 and not ledger(Path(t2)).get("ASK-64") and "cap-ladder.py" in out, (out, calls2))
    os.environ.update(W=str(td), KIPI_ATTEMPTS=str(td / "attempts.json"),
                      CAP_LADDER_STATUS=str(td / "status.jsonl"), CAPABILITY_EXPIRY_SEEN=str(td / "first-seen.json"))

    # The answered ask: a credential the founder granted is unblocked, never asked again.
    ask = m.credential_ask("ASK-65")
    # "answered before this park": an answer to an EARLIER park must not unblock
    # this one, or a ticket whose grant never arrived re-enters every 14 days.
    for case, resolved, at in (("answered", True, "2026-11-01T00:00:00+00:00"), ("open", False, ""),
                               ("answered before this park", True, "2026-09-01T00:00:00+00:00")):
        calls.clear()
        (td / "ladder.log").write_text("")
        (td / "status.jsonl").write_text(json.dumps({"id": "ASK-65:a", "issue": "ASK-65", "kind": "founder-decision",
                                                     "ask": ask, "resolved": resolved, "note": "token exported",
                                                     "resolved_at": at, "resolved_by": "founder"}) + "\n")
        out = m.route_unprobeable(FakeLinear({"ASK-65": [cred]}), "ASK-65", OLD, True, NOW)
        asked = any(a[:2] == ["--founder-ask", "ASK-65"] for a in lines(td, "ladder.log"))
        unblocked = ["unblock", "ASK-65", "blocked:capability"] in calls
        want = case == "answered"
        if want:
            ok = unblocked and not asked and any(c[0] == "progress" and "token exported" in c[2] for c in calls)
        else:
            ok = asked and not unblocked
        check(f"credential ask {case}: " + ("unblocked and requeued with the answer, never asked again"
                                            if want else "asked (the ladder dedupes it), label kept"),
              ok, (out, calls))


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
        src = (td / "capability_block_expiry.py").read_text()
        mut = src.replace("if now - start < timedelta(days=ROUTE_AFTER_DAYS):", "if False:", 1)
        # A renamed gate line made this mutant a silent no-op once (PR #668 round 2).
        check("mutant: the gate copy really differs from the module", mut != src)
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
    with tempfile.TemporaryDirectory() as t:
        review_round1(Path(t))
    print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
