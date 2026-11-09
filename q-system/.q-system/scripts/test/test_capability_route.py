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
        # The fake carries the REAL ladder's JOB, DEAD_TYPES and FOUNDER_RESOLVE_CTX
        # lines, copied from the real file, because the module reads them from
        # cap-ladder.py's source (PR #668 rounds 2 and 3). A hand-typed copy here
        # would test the copy.
        consts = "".join(l + "\n" for l in (HERE / "cap-ladder.py").read_text().splitlines()
                         if l.startswith(("JOB = ", "DEAD_TYPES = ", "FOUNDER_RESOLVE_CTX = ")))
        (td / "cap-ladder.py").write_text(
            consts +
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


# What cap-ladder.py resolve_ctx() records for a --resolve typed into the
# founder's own terminal: stdin is a tty and no agent runner's marker is set.
TERMINAL_CTX = {"tty": True, "agent_env": [], "launchd": "", "user": "founder"}

# One park per route, for the round-3 races (two real processes per site).
RACE_PARKS = {
    "route-claude": park_comment("the Write tool refuses .claude/settings.json", "same"),
    "route-cred": park_comment("the vendor API key is not set in this environment", "no token for the vendor"),
    "route-capout": park_comment("the build tool is not installed", "same"),
}


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
        # resolved_ctx is what cap-ladder.py's resolve_ctx() records for a run in
        # the founder's own terminal; review_round3 makes that row through the
        # real writer under a pty (PR #668 round 3, finding 2).
        (td / "status.jsonl").write_text(json.dumps({"id": "ASK-65:a", "issue": "ASK-65", "kind": "founder-decision",
                                                     "ask": ask, "resolved": resolved, "note": "token exported",
                                                     "resolved_at": at, "resolved_by": "founder",
                                                     "resolved_ctx": TERMINAL_CTX}) + "\n")
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


def real_ladder(td: Path):
    """The REAL cap-ladder.py, imported in-process, every path it writes inside td.
    Its Linear read goes through its own CAP_LADDER_LINEAR_FIXTURE seam."""
    for v, f in (("CAP_LADDER_STATE", "ladder-state.json"), ("CAP_LADDER_REPORT", "ladder-report.json"),
                 ("CAP_LADDER_BLOCKERS", "ladder-blockers.json"), ("CAP_LADDER_ATTEMPTS", "attempts.json"),
                 ("CAP_LADDER_LINEAR_LOG", "ladder-linear.log"), ("CAP_LADDER_LINEAR_FIXTURE", "linear.json")):
        os.environ[v] = str(td / f)
    os.environ["CAP_LADDER_NOW"] = "2026-11-08T04:40:00+00:00"
    spec = importlib.util.spec_from_file_location("cap_ladder_real", str(HERE / "cap-ladder.py"))
    lad = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lad)
    return lad


def resolve_cli(lad, aid: str, note: str, terminal: bool, agent: bool = False) -> dict:
    """`cap-ladder.py --resolve`, the REAL writer as its own process, so the row
    carries the context its resolve_ctx() really sees (PR #668 round 3, finding 2).
    terminal: stdin is a pty, as when the founder types it in his own terminal.
    agent: CLAUDECODE is set, as in every Claude Code tool shell. --by is "assaf"
    either way: it is free text, so it must not be what decides. Returns the row."""
    import subprocess
    env = {k: v for k, v in os.environ.items() if k not in lad.AGENT_ENV}
    env["CAP_LADDER_NOW"] = "2026-11-08T04:40:00+00:00"
    if agent:
        env["CLAUDECODE"] = "1"
    fds = os.openpty() if terminal else ()
    try:
        p = subprocess.run([sys.executable, str(HERE / "cap-ladder.py"), "--resolve", aid, "--note", note,
                            "--by", "assaf"], env=env, stdin=fds[1] if fds else subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60)
    finally:
        for fd in fds:
            os.close(fd)
    status = Path(os.environ["CAP_LADDER_STATUS"])
    row = next((r for r in lines(status.parent, status.name) if r.get("id") == aid), {})
    check(f"setup: the real --resolve wrote the row (terminal={terminal}, agent={agent})",
          p.returncode == 0 and bool(row.get("resolved")), p.stdout + p.stderr)
    return row


class MainFake(FakeLinear):
    """Enough of Linear for main(): the team, the board, the park history, the comments."""
    EXIT_NOOP = 4

    def __init__(self, bodies, board):
        super().__init__(bodies)
        self.board = board

    def graphql(self, query, variables):
        if "teams(" in query:
            return {"teams": {"nodes": [{"id": "t"}]}}
        if "issues(filter" in query:
            return {"issues": {"nodes": self.board, "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        if "history(" in query:
            return {"issue": {"history": {"nodes": [{"createdAt": OLD, "addedLabelIds": ["l-b"]}]}}}
        return super().graphql(query, variables)


RACE_CHILD = r'''
import importlib.util, json, os, sys, time
def mod(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m); return m
td, op, ident = sys.argv[1], sys.argv[2], sys.argv[3]
t = mod("trt", os.environ["ROUTE_TEST"])
m = mod("cbe_child", os.environ["ROUTE_MODULE"])
if op == "route":
    def sync(*a):
        if a[0] == "unblock":
            time.sleep(0.6)               # the unblock's network round-trip
        with open(td + "/race.log", "a") as fh:
            fh.write(json.dumps(list(a)) + "\n")
        return 0, "ok"
    m._sync = sync
    body = t.park_comment("the Write tool refuses .claude/settings.json", "same")
    print(m.route_unprobeable(t.FakeLinear({ident: [body]}), ident, t.OLD, True, t.NOW))
else:
    import json as _j
    class Slow:
        def __getattr__(self, n):
            return getattr(_j, n)
        def load(self, fh):
            d = _j.load(fh); time.sleep(1.0); return d   # widen read-to-write
    m.json = Slow()
    from datetime import datetime, timezone
    m._seen(ident, datetime(2026, 11, 8, tzinfo=timezone.utc), True)
'''


def race(td: Path, module: Path, op: str, idents) -> list:
    """Run one child per ident AT ONCE, each a real process. Returns their stdout."""
    import subprocess
    (td / "race_child.py").write_text(RACE_CHILD)
    env = dict(os.environ, ROUTE_TEST=str(Path(__file__).resolve()), ROUTE_MODULE=str(module))
    procs = [subprocess.Popen([sys.executable, str(td / "race_child.py"), str(td), op, i], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) for i in idents]
    return [p.communicate(timeout=60)[0].strip() for p in procs]


def review_round2(td: Path) -> None:
    """PR #668 round 2, each finding in the reviewer's reproducer shape. Red at 798279fb."""
    from datetime import datetime, timezone
    m, calls = load(td)
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    cred = park_comment("the vendor API key is not set in this environment", "no token for the vendor")

    # FINDING 1 (major). The REAL producers: cap-ladder's status_add files the
    # ask, its sweep_dead_asks resolves it as moot because the ticket closed.
    lad = real_ladder(td)
    ask = m.credential_ask("ASK-66")
    (td / "linear.json").write_text(json.dumps({"ASK-66": {"state_type": "completed"}}))
    (td / "status.jsonl").write_text("")
    lad.status_add("ASK-66", "founder-decision", ask, source="cap-ladder.py --founder-ask")
    # The sweep run BY HAND FROM A TERMINAL: its moot row then carries a terminal
    # context, and the JOB check is the only thing that refuses it. Without this
    # the row's context is whatever shell runs the test, and an agent shell would
    # refuse it on context alone, so mutant 1 below could not go red (round 3).
    real_ctx = lad.resolve_ctx
    lad.resolve_ctx = lambda: dict(TERMINAL_CTX)
    swept = lad.sweep_dead_asks(True)
    lad.resolve_ctx = real_ctx
    row = lines(td, "status.jsonl")[-1]
    check("finding 1 setup: the real sweep resolved the ask as moot, by its own job name",
          swept == 1 and row.get("resolved") and row.get("resolved_by") == lad.JOB
          and str(row.get("note")).startswith("moot:"), row)
    got = m.answered("ASK-66", ask, start)
    check("finding 1: answered() does not read cap-ladder's own moot resolution as the founder's answer",
          got is None, got)
    # The ticket was reopened and is still parked: the moot row must not unblock
    # it, and must not sign the founder's name to a permanent comment.
    calls.clear()
    (td / "ladder.log").write_text("")
    out = m.route_unprobeable(FakeLinear({"ASK-66": [cred]}), "ASK-66", OLD, True, NOW)
    asked = any(a[:2] == ["--founder-ask", "ASK-66"] for a in lines(td, "ladder.log"))
    check("finding 1: a moot ask unblocks nothing, posts no 'founder answered' note, and a fresh ask is filed",
          not any(c[0] in ("unblock", "progress", "requeue") for c in calls) and asked, (out, calls))
    # Control: the founder's own --resolve, through the real writer, still counts.
    (td / "linear.json").write_text(json.dumps({"ASK-67": {"state_type": "started"}}))
    aid = lad.status_add("ASK-67", "founder-decision", m.credential_ask("ASK-67"))
    resolve_cli(lad, aid, "token exported to the runner env", terminal=True)
    got = m.answered("ASK-67", m.credential_ask("ASK-67"), start)
    check("finding 1 control: the founder's own --resolve is still his answer",
          bool(got) and got.get("id") == aid, got)

    # PR #695 (merged as 11548797): `cap-ladder.py --founder-ask` exits 1 on a
    # closed ticket. A closed ticket is not routed at all, so it never reads as
    # a failed ask. Proven through main(), which must pass the state through.
    for ident, body, kind in (("ASK-68", cred, "credential"),
                              ("ASK-69", park_comment("the Write tool refuses .claude/x.md", "same"), "claude-write"),
                              ("ASK-71", park_comment("the build tool is not installed", "same"), "unknown")):
        calls.clear()
        (td / "ladder.log").write_text("")
        board = [{"id": ident, "identifier": ident, "title": "t", "state": {"name": "Done", "type": "completed"},
                  "project": {"name": "kipi-system"},
                  "labels": {"nodes": [{"id": "l-b", "name": "blocked:capability"}]}}]
        fake = MainFake({ident: [body]}, board)
        m._load_linear_sync = lambda fake=fake: fake
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = m.main(["--repo-project", "kipi-system", "--apply"])
        said = buf.getvalue()
        check(f"closed ticket ({kind}) through main(): not routed; no ask, no unblock, no note, no capout",
              rc == 0 and not calls and not lines(td, "ladder.log") and not ledger(td).get(ident)
              and "completed" in said and "not routed" in said, (said, calls, lines(td, "ladder.log")))

    # FINDING 2 (major). Two real processes, one claude-write park, a 0.6s
    # unblock. Exactly one permanent "Unblocked" comment and one requeue.
    (td / "race.log").write_text("")
    outs = race(td, td / "capability_block_expiry.py", "route", ["ASK-70", "ASK-70"])
    log = lines(td, "race.log")
    posted = [c for c in log if c[0] == "progress" and "Unblocked by" in c[2]]
    requeued = [c for c in log if c[0] == "requeue"]
    check("finding 2: two concurrent runs post ONE permanent 'Unblocked' comment and requeue once",
          len(posted) == 1 and len(requeued) == 1, (outs, len(posted), len(requeued)))
    check("finding 2: the run that lost the claim says so", any("concurrent run" in o for o in outs), outs)

    # FINDING 3 (minor). The sentinel is up to 1500 bytes of agent text.
    two = park_comment("the deploy step stopped.\nIt needs the vendor API key, which is not set here", "same")
    para = park_comment("the deploy step stopped.\n\nIt needs the vendor API key, which is not set here", "same")
    check("finding 3: a credential named on line 2 of the runner's sentinel is credential",
          m.classify(two) == "credential", m.classify(two))
    check("finding 3: a credential named in paragraph 2 of the runner's sentinel is credential",
          m.classify(para) == "credential", m.classify(para))
    check("finding 3: a multi-line runner block still stops before the boilerplate",
          m.classify(park_comment("the build tool\n\nis not installed", "nor here")) == "unknown")

    # FINDING 4 (minor). Two concurrent first sights, a slowed read.
    (td / "first-seen.json").write_text("{}")
    race(td, td / "capability_block_expiry.py", "seen", ["ASK-801", "ASK-802"])
    stamps = json.loads((td / "first-seen.json").read_text())
    check("finding 4: two concurrent first sights keep both stamps",
          "ASK-801" in stamps and "ASK-802" in stamps, stamps)

    # MUTANTS, one per major: restore the old behavior in a copy, and the same
    # assertion must go red, or the test above could not fail.
    src = (td / "capability_block_expiry.py").read_text()
    mut1 = src.replace('if (r.get("resolved_by") or "") == job[:80]:', "if False:", 1)
    # Discards the claim's exit code, as 798279fb did: crc is forced to 0, so
    # the `crc != 0` branch cannot catch the loser either.
    mut2 = src.replace("if crc == 1:", "if (crc := 0):", 1)
    check("mutant: both mutant copies really differ from the module", mut1 != src and mut2 != src)
    (td / "mut1.py").write_text(mut1)
    spec = importlib.util.spec_from_file_location("cbe_mut1", str(td / "mut1.py"))
    mm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mm)
    mm.LADDER_SCRIPT = m.LADDER_SCRIPT
    check("mutant 1: an answered() that counts the ladder's moot row returns it (finding 1 can fail)",
          mm.answered("ASK-66", ask, start) is not None)
    (td / "mut2.py").write_text(mut2)
    (td / "race.log").write_text("")
    race(td, td / "mut2.py", "route", ["ASK-72", "ASK-72"])
    posted = [c for c in lines(td, "race.log") if c[0] == "progress" and "Unblocked by" in c[2]]
    check("mutant 2: a claude-write route that ignores the claim's verdict posts twice (finding 2 can fail)",
          len(posted) == 2, len(posted))


# PR #668 ROUND 3: ONE CHOKEPOINT FOR "UNBLOCK, THEN THE PERMANENT NOTE"
# RCA q-system/output/rca/rca-capability-expiry-round-3-2026-11-09.md. Rounds 2
# and 3 each found the duplicate-comment race at ONE site, and each fix went to
# that site. So the sites are counted from the source, not from memory, and each
# one gets its own two-process race.
HELPER = "unblock_then_post"
# Every call of the helper in capability_block_expiry.py: the function that makes
# it, the verbs it posts (each one a comment Linear cannot delete), its one-shot
# claim as written in the source, the race op that drives it, and how many
# permanent comments the WINNER of two concurrent runs posts. census() compares
# the source against this table, so a new site is red until it has a row, and a
# row has a race because the race loop below runs every row.
SITES = (
    ("clear_block", ("progress",), "", "clear", 1),
    ("route_unprobeable", ("progress", "requeue"), "flag", "route-claude", 2),
    ("route_unprobeable", ("progress", "requeue"), "", "route-cred", 2),
    ("route_unprobeable", (), "", "route-capout", 0),
)
# What the module may touch on the linear-sync module object: reads only.
LS_READS = ("graphql", "LinearAPIError", "EXIT_NOOP")


def census(src: str) -> list:
    """Every way the module can write to Linear outside the SITES table. [] when clean."""
    import ast
    import re
    tree = ast.parse(src)
    owner = {}
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef):
            for n in ast.walk(fn):
                owner[id(n)] = fn.name
    # A bare string statement is a docstring: prose about linear-sync, not a call.
    prose = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    bad, found = [], []
    for n in ast.walk(tree):
        where = owner.get(id(n), "<module>")
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_sync" and where != HELPER:
            bad.append(f"_sync called in {where} line {n.lineno}: a Linear write outside {HELPER}")
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == HELPER:
            posts = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == "posts"), None)
            claim = next((k.value for k in n.keywords if k.arg == "claim"), None)
            if not (isinstance(posts, ast.List) and all(
                    isinstance(e, ast.Tuple) and e.elts and isinstance(e.elts[0], ast.Constant) for e in posts.elts)):
                bad.append(f"{HELPER} in {where} line {n.lineno}: posts is not a literal list of (verb, ...) tuples")
                continue
            found.append((where, tuple(e.elts[0].value for e in posts.elts), ast.unparse(claim) if claim else ""))
        if (isinstance(n, ast.Attribute) and n.attr not in LS_READS
                and ((isinstance(n.value, ast.Name) and n.value.id == "ls")
                     or (isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "_load_linear_sync"))):
            bad.append(f"linear-sync's {n.attr} used in {where} line {n.lineno}: only {LS_READS} are reads")
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in prose:
            if re.match(r"\s*mutation\b", n.value):
                bad.append(f"a GraphQL mutation in {where} line {n.lineno}")
            if "linear-sync.py" in n.value and where not in ("_sync", "_load_linear_sync"):
                bad.append(f"linear-sync.py named in {where} line {n.lineno}: a second way to run its verbs")
    want = sorted(r[:3] for r in SITES)
    if sorted(found) != want:
        bad.append(f"{HELPER} call sites {sorted(found)} are not SITES {want}")
    return bad


class LoopLinear:
    """A loopback Linear for the REAL linear-sync.py, label state and comments kept.

    The round-2 race swapped _sync for a function that answered 0 to both
    unblocks, which is not what production does: linear-sync holds a host lock
    and answers EXIT_NOOP to the run that finds the label gone. This serves the
    queries linear-sync's unblock, progress and requeue send, and holds the label
    read for half a second so the two runs are in flight together."""

    def __init__(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.lock = threading.Lock()
        self.issues, self.comments, self.removals = {}, {}, {}
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                out = json.dumps({"data": outer.answer(body["query"], body.get("variables") or {})}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}/graphql"

    def issue(self, ident):
        with self.lock:
            i = self.issues.setdefault(ident, {"labels": {"owner:sana", BLOCK}, "state": "started"})
            return {"id": ident, "identifier": ident, "title": "t", "team": {"id": "t"},
                    "state": {"id": "s-" + i["state"], "name": i["state"], "type": i["state"]},
                    "labels": {"nodes": [{"id": "l-" + n, "name": n} for n in sorted(i["labels"])]}}

    def answer(self, q, v):
        import time
        if "issueRemoveLabel" in q:
            with self.lock:
                self.issues[v["id"]]["labels"].discard(v["labelId"][2:])
                self.removals[v["id"]] = self.removals.get(v["id"], 0) + 1
            return {"issueRemoveLabel": {"success": True}}
        if "commentCreate" in q:
            with self.lock:
                self.comments.setdefault(v["input"]["issueId"], []).append(v["input"]["body"])
            return {"commentCreate": {"success": True, "comment": {"id": "c"}}}
        if "issueUpdate" in q:
            with self.lock:
                self.issues[v["id"]]["state"] = "backlog"
            return {"issueUpdate": {"success": True, "issue": {"id": v["id"], "identifier": v["id"]}}}
        if "states(" in q:
            return {"team": {"states": {"nodes": [{"id": "s-backlog", "name": "backlog", "type": "backlog",
                                                   "position": 0}]}}}
        if "issue(" in q:
            if "labels" in q:
                time.sleep(0.5)
            return {"issue": self.issue(v["id"])}
        return {}


BLOCK = "blocked:capability"
RACE3_CHILD = r'''
import importlib.util, os, sys
def mod(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m); return m
op, ident = sys.argv[1], sys.argv[2]
t = mod("trt3", os.environ["ROUTE_TEST"])
m = mod("cbe_r3", os.environ["ROUTE_MODULE"])
if op == "clear":
    print(m.clear_block(ident, "path:/fixture", "fixture evidence"))
else:
    print(m.route_unprobeable(t.FakeLinear({ident: [t.RACE_PARKS[op]]}), ident, t.OLD, True, t.NOW))
'''


def race3(td: Path, module: Path, op: str, ident: str, loop: LoopLinear) -> list:
    """Two real processes on one site at once, each running the REAL linear-sync.py."""
    import subprocess
    (td / "race3_child.py").write_text(RACE3_CHILD)
    env = dict(os.environ, ROUTE_TEST=str(Path(__file__).resolve()), ROUTE_MODULE=str(module),
               KIPI_LINEAR_API_URL=loop.url, KIPI_LINEAR_API_KEY="fixture-key-not-a-secret",
               KIPI_LOCK_DIR=str(td / "locks"), PYTHONDONTWRITEBYTECODE="1")
    procs = [subprocess.Popen([sys.executable, str(td / "race3_child.py"), op, ident], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) for _ in range(2)]
    return [p.communicate(timeout=120)[0].strip() for p in procs]


def mutant(td: Path, src: str, name: str, edits) -> Path | None:
    """A copy of the module with each (anchor, replacement) applied. An anchor that
    does not match exactly once is a FAILED experiment, reported red, never run."""
    out = src
    for anchor, repl in edits:
        if out.count(anchor) != 1:
            check(f"mutant {name}: its anchor matches exactly once", False, f"{out.count(anchor)}: {anchor[:120]}")
            return None
        out = out.replace(anchor, repl, 1)
    check(f"mutant {name}: the copy really differs from the module", out != src)
    path = td / f"{name}.py"
    path.write_text(out)
    return path


def load_copy(path: Path, ladder_script: str):
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    mm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mm)
    mm.LADDER_SCRIPT = ladder_script
    calls = []
    mm._sync = lambda *a: (calls.append(list(a)) or (0, "ok"))
    return mm, calls


def review_round3(td: Path) -> None:
    """PR #668 round 3, the class not the site. Red at 9df54729."""
    from datetime import datetime, timezone
    m, calls = load(td)
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    src = (td / "capability_block_expiry.py").read_text()

    # FINDING 1 (major), THE CLASS. Every Linear write goes through one helper,
    # and its call sites are exactly the SITES table.
    got = census(src)
    check(f"census: every Linear write goes through {HELPER}; its call sites are SITES "
          f"({len(SITES)} rows, {sum(1 for r in SITES if r[1])} that post)", not got, got)
    for name, extra, want in (
            ("a _sync('progress') outside the helper", '\ndef _rogue(i):\n    return _sync("progress", i, "x")\n',
             "_sync called in _rogue"),
            ("a helper call with no SITES row", '\ndef _rogue(i):\n    return unblock_then_post(i, [("progress", "x")])\n',
             "('_rogue', ('progress',), '')"),
            ("a write through the linear-sync module", '\ndef _rogue(ls, i):\n    return ls.requeue_issue(i, "x")\n',
             "requeue_issue"),
            ("a subprocess straight to linear-sync.py",
             '\ndef _rogue(i):\n    return subprocess.run(["python3", "linear-sync.py", "progress", i, "x"])\n',
             "linear-sync.py named in _rogue")):
        got = census(src + extra)
        check(f"census can fail: {name} is reported", any(want in g for g in got), got)

    # FINDING 1, ONE RACE PER SITE: two real processes, the real linear-sync.py.
    loop = LoopLinear()
    lad = real_ladder(td)

    def answered_row(ident):
        aid = lad.status_add(ident, "founder-decision", m.credential_ask(ident))
        resolve_cli(lad, aid, "token exported to the runner env", terminal=True)

    def run_race(module, op, ident):
        if op == "route-cred":
            answered_row(ident)
        return race3(td, module, op, ident, loop), loop.comments.get(ident, [])

    for n, (fn, _verbs, _claim, op, posts) in enumerate(SITES):
        ident = f"ASK-95{n}"
        outs, said = run_race(td / "capability_block_expiry.py", op, ident)
        check(f"race {op} ({fn}): two concurrent runs remove the label once and post {posts} permanent "
              "comment(s), the winner's only", loop.removals.get(ident) == 1 and len(said) == posts, (outs, said))
        loser = "'noop'" if op == "clear" else "concurrent run"
        check(f"race {op}: the run that lost says so", sum(loser in o for o in outs) == 1, outs)

    # MUTANT M1: the helper posts on EXIT_NOOP, the round-1 `_landed` rule. The
    # credential race and the clear race must post twice, or they could not fail.
    m1 = mutant(td, src, "mut_landed", (
        ("    if rc == ls_exit_noop():\n        return NOOP, rc, detail\n", ""),
        ("    if rc != 0:\n        return FAILED, rc, detail\n",
         "    if rc not in (0, ls_exit_noop()):\n        return FAILED, rc, detail\n")))
    if m1:
        for ident, op, posts in (("ASK-960", "route-cred", 2), ("ASK-961", "clear", 1)):
            outs, said = run_race(m1, op, ident)
            check(f"mutant M1: a helper that posts on EXIT_NOOP makes the {op} race post twice (it can fail)",
                  len(said) > posts, (outs, said))
    loop.srv.shutdown()

    # FINDING 2 (major, nonblocking). Who may answer a founder ask, through the
    # REAL writer: only a resolve run in a terminal with no agent marker counts.
    cases = (("an agent shell with no terminal (the reviewer's repro)", False, True, False),
             ("an agent shell inside a pty", True, True, False),
             ("a terminal with no agent marker", True, False, True))
    for n, (name, terminal, agent, counts) in enumerate(cases):
        ident = f"ASK-97{n}"
        aid = lad.status_add(ident, "founder-decision", m.credential_ask(ident))
        row = resolve_cli(lad, aid, "token exported", terminal=terminal, agent=agent)
        got = m.answered(ident, m.credential_ask(ident), start)
        check(f"finding 2: a resolve from {name} {'counts' if counts else 'does NOT count'} as the founder's answer",
              bool(got) == counts, (got, row.get("resolved_ctx")))
    calls.clear()
    (td / "ladder.log").write_text("")
    out = m.route_unprobeable(FakeLinear({"ASK-970": [RACE_PARKS["route-cred"]]}), "ASK-970", OLD, True, NOW)
    asked = any(a[:2] == ["--founder-ask", "ASK-970"] for a in lines(td, "ladder.log"))
    check("finding 2: an agent-shell resolve un-parks nothing, posts nothing, asks again and says why",
          not any(c[0] in ("unblock", "progress", "requeue") for c in calls) and asked and "terminal" in out,
          (out, calls))
    with open(td / "status.jsonl", "a") as fh:
        fh.write(json.dumps({"id": "ASK-975:a", "issue": "ASK-975", "kind": "founder-decision",
                             "ask": m.credential_ask("ASK-975"), "resolved": True, "note": "x",
                             "resolved_at": "2026-11-01T00:00:00+00:00", "resolved_by": "founder"}) + "\n")
    check("finding 2: a resolve that recorded no context does not count (fail closed)",
          m.answered("ASK-975", m.credential_ask("ASK-975"), start) is None)
    m2 = mutant(td, src, "mut_anyctx", (('if not _founder_ctx(r.get("resolved_ctx"), want):', "if False:"),))
    if m2:
        mm, _ = load_copy(m2, m.LADDER_SCRIPT)
        check("mutant M2: an answered() that ignores the context counts the agent resolve (finding 2 can fail)",
              mm.answered("ASK-970", m.credential_ask("ASK-970"), start) is not None)

    # FINDING 3 (minor). No readable cap-ladder.py means no closed-ticket guard,
    # so nothing routes this run, open or closed, and the line says why.
    for name, ladder_src in (("missing", None), ("unparsable", "JOB = (\n")):
        with tempfile.TemporaryDirectory() as t3:
            m3, calls3 = load(Path(t3), ladder=False)
            if ladder_src is not None:
                (Path(t3) / "cap-ladder.py").write_text(ladder_src)
            outs = [m3.route_unprobeable(FakeLinear({"ASK-980": [RACE_PARKS["route-claude"]]}), "ASK-980", OLD, True,
                                         NOW, state_type=st) for st in ("completed", "started")]
            check(f"finding 3: cap-ladder.py {name}: a completed and a started ticket both take no route, and say why",
                  not calls3 and not ledger(Path(t3)).get("ASK-980") and all("fail closed" in o for o in outs),
                  (outs, calls3))
            m3m = mutant(Path(t3), (Path(t3) / "capability_block_expiry.py").read_text(), "mut_open", (
                ("    if not (isinstance(dead, (tuple, list)) and dead and all(isinstance(s, str) for s in dead)):",
                 "    if False:"),
                ("if state_type and state_type in dead:", "if state_type and state_type in (dead or ()):")))
            if m3m:
                mm, c3 = load_copy(m3m, str(Path(t3) / "cap-ladder.py"))
                mm.route_unprobeable(FakeLinear({"ASK-981": [RACE_PARKS["route-claude"]]}), "ASK-981", OLD, True,
                                     NOW, state_type="completed")
                check(f"mutant M3 ({name}): a guard that fails open routes the completed ticket (finding 3 can fail)",
                      any(c[0] == "unblock" for c in c3), c3)


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
    with tempfile.TemporaryDirectory() as t:
        review_round2(Path(t))
    with tempfile.TemporaryDirectory() as t:
        review_round3(Path(t))
    print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
