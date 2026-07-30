#!/usr/bin/env python3
"""Contract test for `linear-sync.py delegate` and `agent-verdict` (ASK-253).

These two verbs are how the autonomous loop hands a PR to the native Codex Linear
agent and reads its verdict back. What refuses on their output is coded elsewhere:
`converge.sh:161` reads the verdict record, `pr-receipt-gate.py` is a required CI
step, and this file is the check that `capability-gate.py` runs. Both failure
directions matter: a delegation that silently does not happen means the loop waits
forever for a review nobody is producing, and a verdict derived from an errored or
truncated session means an unread PR reaches those gates looking approved.

NO LIVE LINEAR. `graphql` is monkeypatched. A test that writes to a Linear object
cannot be undone, and one that reads a live issue fails whenever that issue moves.
Fixtures are copied from real captured payloads (see the SHAPES note below), not
invented -- two green-but-wrong tests shipped in one day from invented fixtures.
"""
import contextlib
import importlib.util
import io
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
TARGET = HERE / "linear-sync.py"
FAILURES, PASSES = [], []


def ok(m):
    PASSES.append(m); print(f"  PASS {m}")


def fail(m):
    FAILURES.append(m); print(f"  FAIL {m}")


def load():
    spec = importlib.util.spec_from_file_location("linear_sync_agent_under_test", TARGET)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# SHAPES captured live from ASK-221 on 2026-07-30, not guessed:
#   issue.agentSessions.nodes[] -> {id, status, createdAt, appUser{name}}
#   agentSession.activities.nodes[].content -> {type: 'response', body: '...'}
# status is a Linear enum: pending|active|error|awaitingInput|complete|stale.
REAL_BODY = """## Verdict: REQUEST CHANGES

### Finding 1 — something

**Severity: minor**

FINDINGS:
minor|the filter still accepts prose|linear-sync.py:744
major|no tree-versus-PR-head check|pr-review-agent.sh:178
END FINDINGS
"""

# TWO SEPARATE FIXTURES, because the first cut conflated them and one of the two
# assertions was decoration. Caught by this file's own mutation check: switching the
# parser to read EVERY block still passed, since the allowlist alone neutralized the
# template line, so nothing actually tested last-block-only.
#
# 1. The prompt template echoed back. Rejected by the severity allowlist, i.e. the
#    `parts[0].strip().lower() in SEVERITY_RANK` test in verdict_from_findings_text.
TEMPLATE_ECHO = """FINDINGS:
severity|one-sentence claim|file:line
END FINDINGS
"""

# 2. A REVIEWED DIFF THAT ITSELF CONTAINS A VALID SEVERITY, then the reviewer's own
#    block. This is the only shape that separates last-block from all-blocks: the
#    earlier `major` is real syntax the allowlist cannot filter, so an all-blocks
#    parse derives REQUEST CHANGES while the reviewer actually said only a minor.
#    Copied from the live 313KB review of PR #35 on 2026-07-29, whose diff carried
#    `major|the fallback fills the slot without marking it degraded|q-system/x.sh:40`
#    as test-fixture text. That is sp-c0a9dac3 in its real form.
DIFF_FIXTURE_THEN_REAL = """Reviewing a diff that adds reviewer tests. It contains:

+FINDINGS:
+major|the fallback fills the slot without marking it degraded|q-system/x.sh:40
+END FINDINGS

FINDINGS:
major|the fallback fills the slot without marking it degraded|q-system/x.sh:40
END FINDINGS

Now my actual review.

FINDINGS:
minor|only a nit survived|x.py:1
END FINDINGS
"""


class DArgs:
    def __init__(self, issue="ASK-221", agent="Codex", clear=False):
        self.issue, self.agent, self.clear = issue, agent, clear


class VArgs:
    def __init__(self, issue="ASK-221", agent="Codex", body=False, since=None, session=None):
        self.issue, self.agent, self.body = issue, agent, body
        self.since, self.session = since, session


def run(mod, fn, args, router):
    mod.graphql = router
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fn(args)
    return rc, out.getvalue(), err.getvalue()


def sessions_payload(status="complete", agent="Codex", nodes=None):
    if nodes is None:
        nodes = [{"id": "s-old", "status": "error", "createdAt": "2026-07-30T00:02:07Z",
                  "appUser": {"name": agent}},
                 {"id": "s-new", "status": status, "createdAt": "2026-07-30T00:27:59Z",
                  "appUser": {"name": agent}}]
    return {"issue": {"identifier": "ASK-221", "agentSessions": {"nodes": nodes}}}


def acts_payload(body=REAL_BODY, atype="response"):
    return {"agentSession": {"id": "s-new", "status": "complete", "activities": {"nodes": [
        {"id": "a1", "createdAt": "2026-07-30T00:30:56Z",
         "content": {"type": atype, "body": body}}]}}}


def verdict_router(sessions=None, acts=None):
    def r(q, _v):
        if "agentSessions" in q:
            return sessions if sessions is not None else sessions_payload()
        if "agentSession(" in q:
            return acts if acts is not None else acts_payload()
        raise AssertionError("unexpected query")
    return r


def main():
    if not TARGET.exists():
        print(f"FAIL: {TARGET} missing"); return 1
    m = load()

    for name in ("cmd_delegate", "cmd_agent_verdict", "verdict_from_findings_text"):
        if not hasattr(m, name):
            print(f"FAIL: linear-sync.py has no {name}; the loop cannot delegate to the "
                  f"native agent or read its verdict back")
            return 1
    ok("delegate, agent-verdict and the verdict deriver all exist")

    # ================= verdict_from_findings_text =================
    # THE ONLY SHAPE THAT SEPARATES last-block FROM all-blocks: a VALID major in the
    # reviewed diff's own fixture text, and only a minor in the reviewer's real block.
    # An all-blocks parse derives REQUEST CHANGES here and wedges a PR the reviewer
    # actually approved-with-nits.
    v, f = m.verdict_from_findings_text(DIFF_FIXTURE_THEN_REAL)
    if v != "APPROVE WITH NITS":
        fail(f"THE sp-c0a9dac3 DEFECT: findings-shaped text inside the REVIEWED DIFF "
             f"contributed to the real verdict. The reviewer's own block (last) holds only "
             f"a minor, so this must be APPROVE WITH NITS; got {v!r} from {f}")
    elif len(f) != 1 or f[0][0] != "minor":
        fail(f"parsed {f} from the last block; expected exactly one minor")
    else:
        ok("only the LAST closed block counts, even when an earlier block is valid syntax")

    # THE MAJOR THE CLAUDE REVIEWER FOUND ON PR #45. Every review request in this repo
    # ENDS with the FINDINGS template, whose one line the allowlist rejects, leaving an
    # empty trailing block. A flat blocks[-1] read that block, found nothing, and
    # derived APPROVE -- discarding a real blocker and posting codex-approved=success.
    # This is the highest-consequence case in the file: it converts a refusal into an
    # approval, which is the one direction that must never happen silently.
    BLOCKER_THEN_TEMPLATE = """FINDINGS:
blocker|publishes a credential to a permanent Linear object|a.py:1
END FINDINGS

For reference, the format I asked for was:

FINDINGS:
severity|one-sentence claim|file:line
END FINDINGS
"""
    v, f = m.verdict_from_findings_text(BLOCKER_THEN_TEMPLATE)
    if v != "BLOCK":
        fail(f"THE MAJOR: a trailing template block discarded a real BLOCKER and derived "
             f"{v!r}. Every review request here ends with that template, so an agent that "
             f"echoes it back turns a refusal into an approval. Findings seen: {f}")
    else:
        ok("a trailing template block does not discard an earlier real blocker")

    # ...and a reviewer that genuinely closed an EMPTY block still means APPROVE, so
    # the fix must not turn "nothing survived reproduction" into UNSTATED.
    v, _ = m.verdict_from_findings_text("Nothing survived.\n\nFINDINGS:\nEND FINDINGS\n")
    if v != "APPROVE":
        fail(f"a genuinely empty closed block stopped deriving APPROVE (got {v!r}); every "
             f"clean review would now wedge")
    else:
        ok("a genuinely empty closed block still derives APPROVE")

    if any(s == "severity" for s, _ in m.verdict_from_findings_text(TEMPLATE_ECHO)[1]):
        fail("the literal word 'severity' was accepted as a severity label")
    else:
        ok("the severity allowlist rejects the prompt template's placeholder line")

    for text, want in [
        ("FINDINGS:\nblocker|permanent|a:1\nEND FINDINGS", "BLOCK"),
        ("FINDINGS:\nmajor|unattended|a:1\nEND FINDINGS", "REQUEST CHANGES"),
        ("FINDINGS:\nnit|style|a:1\nEND FINDINGS", "APPROVE WITH NITS"),
        ("FINDINGS:\nEND FINDINGS", "APPROVE"),
    ]:
        got, _ = m.verdict_from_findings_text(text)
        if got != want:
            fail(f"severity mapping wrong: {text!r} -> {got!r}, expected {want!r}"); break
    else:
        ok("blocker/major/minor-nit/empty map to BLOCK/REQUEST CHANGES/NITS/APPROVE")

    # AN UNCLOSED BLOCK IS NOT AN EMPTY ONE. This is the truncated-stream defect that
    # green-lit a PR on the shell side: an empty finding list derives APPROVE.
    got, _ = m.verdict_from_findings_text("## VERDICT: APPROVE\n\nFINDINGS:\nmajor|cut off")
    if got:
        fail(f"an UNCLOSED FINDINGS block derived {got!r}. A truncated review must be "
             f"UNSTATED, never a verdict -- especially not APPROVE.")
    else:
        ok("an unclosed FINDINGS block derives no verdict (truncation is not consent)")

    # ================= cmd_agent_verdict =================
    rc, out, _ = run(m, m.cmd_agent_verdict, VArgs(), verdict_router())
    if rc != 0:
        fail(f"a complete session with findings exited {rc}, expected 0. Out: {out}")
    elif "verdict=REQUEST CHANGES" not in out:
        fail(f"did not derive REQUEST CHANGES from a major. Out: {out}")
    elif "findings=2" not in out:
        fail(f"did not report both findings. Out: {out}")
    else:
        ok("a complete session derives the verdict and exits 0")

    # NEWEST SESSION WINS, and the fixture's newest is the complete one while an
    # OLDER errored session exists -- the real ASK-221 shape after two environment
    # failures. Picking the wrong one reports an error for a finished review.
    if "s-new" not in out:
        fail(f"did not select the NEWEST session; an older errored session would mask a "
             f"finished review. Out: {out}")
    else:
        ok("the newest session is selected, not an older errored one")

    rc, out, err = run(m, m.cmd_agent_verdict, VArgs(),
                       verdict_router(sessions=sessions_payload(status="error")))
    if rc == 0:
        fail("an ERRORED session exited 0. 'The agent crashed' would be indistinguishable "
             "from 'the agent approved', which is the whole reason to read status.")
    elif "UNSTATED" not in (out + err):
        fail(f"an errored session did not say UNSTATED. out={out} err={err}")
    else:
        ok("status=error is UNSTATED and exits non-zero")

    rc, out, err = run(m, m.cmd_agent_verdict, VArgs(),
                       verdict_router(sessions=sessions_payload(nodes=[])))
    if rc == 0:
        fail("no session at all exited 0; the loop would gate on a review that never ran")
    else:
        ok("no agent session is UNSTATED and exits non-zero")

    rc, out, err = run(m, m.cmd_agent_verdict, VArgs(),
                       verdict_router(acts=acts_payload(atype="thought")))
    if rc == 0:
        fail("a session with only a 'thought' activity and no 'response' exited 0")
    else:
        ok("a complete session with no response activity is UNSTATED")

    rc, out, err = run(m, m.cmd_agent_verdict, VArgs(),
                       verdict_router(acts=acts_payload(body="no block here at all")))
    if rc == 0:
        fail("a response with no FINDINGS block exited 0")
    else:
        ok("a response with no FINDINGS block is UNSTATED")

    # ================= --since binds the verdict to the request =================
    # THE MAJOR CODEX FOUND reviewing its own intake path, 2026-07-30. Without a
    # binding, a read straight after delegating returns the newest COMPLETE session,
    # which is a PRIOR review of an OLDER head, and the caller posts it on the
    # CURRENT sha. Stale approval on unread code -- the ASK-216 class.
    #
    # The fixture is the real ASK-221 shape: an older session that COMPLETED, and no
    # session at all since the delegation. The pre-fix code returns the old verdict.
    STALE_ONLY = {"issue": {"identifier": "ASK-221", "agentSessions": {"nodes": [
        {"id": "s-stale", "status": "complete", "createdAt": "2026-07-30T00:10:00Z",
         "appUser": {"name": "Codex"}}]}}}

    rc, out, err = run(m, m.cmd_agent_verdict,
                       VArgs(since="2026-07-30T01:00:00Z"),
                       verdict_router(sessions=STALE_ONLY))
    if rc == 0:
        fail("THE MAJOR CODEX FOUND: a session that COMPLETED BEFORE the delegation "
             f"still produced a verdict. --since must refuse it, or the caller posts a "
             f"stale approval on a sha nobody reviewed. Out: {out}")
    elif "UNSTATED" not in (out + err):
        fail(f"a pre-delegation session was refused without saying UNSTATED. err={err}")
    else:
        ok("--since refuses a session older than the delegation that asked for it")

    # ...and it still WORKS when a session did arrive after the request, otherwise the
    # fix would just wedge every review permanently.
    rc, out, _ = run(m, m.cmd_agent_verdict,
                     VArgs(since="2026-07-30T00:20:00Z"),
                     verdict_router())
    if rc != 0 or "verdict=REQUEST CHANGES" not in out:
        fail(f"--since refused a session created AFTER it, so no verdict would ever be "
             f"read and every PR waits forever. rc={rc} out={out}")
    else:
        ok("--since accepts a session created at or after the delegation")

    # boundary: a session created EXACTLY at the delegation timestamp counts. The
    # worker stamps the marker and delegates in the same second, so an exclusive
    # comparison would drop the real session.
    rc, out, _ = run(m, m.cmd_agent_verdict,
                     VArgs(since="2026-07-30T00:27:59Z"),
                     verdict_router())
    if rc != 0:
        fail("--since is EXCLUSIVE at the boundary; the worker stamps the marker and "
             "delegates within the same second, so the real session gets dropped")
    else:
        ok("--since is inclusive at the boundary second")

    rc, out, err = run(m, m.cmd_agent_verdict, VArgs(session="s-nope"), verdict_router())
    if rc == 0:
        fail("--session accepted a verdict from a session id that does not exist")
    else:
        ok("--session refuses an unknown session id")

    # ================= cmd_delegate =================
    def del_router(success=True, name="Codex", users=(("u-codex", "Codex"),)):
        def r(q, v):
            if "users(" in q:
                return {"users": {"nodes": [{"id": i, "name": n} for i, n in users]}}
            if "issueUpdate" in q:
                d = {"id": "u-codex", "name": name} if name else None
                return {"issueUpdate": {"success": success,
                                        "issue": {"id": "x", "identifier": "ASK-221",
                                                  "delegate": d}}}
            raise AssertionError("unexpected query")
        return r

    rc, out, err = run(m, m.cmd_delegate, DArgs(), del_router())
    if rc != 0:
        fail(f"delegating to a known agent exited {rc}. err={err}")
    elif "delegated to Codex" not in out:
        fail(f"delegate did not confirm the agent. Out: {out}")
    else:
        ok("delegate resolves the agent and confirms the read-back")

    rc, out, err = run(m, m.cmd_delegate, DArgs(agent="NotAnAgent"),
                       del_router(users=()))
    if rc == 0:
        fail("an UNKNOWN agent name exited 0. The issue stays undelegated while the loop "
             "believes a review was requested, and it waits forever.")
    elif "BLOCK" not in err:
        fail(f"unknown agent did not say BLOCK. err={err}")
    else:
        ok("an unknown agent name BLOCKs and exits non-zero")

    rc, out, err = run(m, m.cmd_delegate, DArgs(), del_router(success=False))
    if rc == 0:
        fail("a mutation returning success=false exited 0 -- the commentCreate defect class")
    else:
        ok("success=false BLOCKs and exits non-zero")

    # THE READ-BACK CHECK, not just `success`. A mutation can report success while
    # the object is unchanged; codex found exactly that in commentCreate on 07-29.
    rc, out, err = run(m, m.cmd_delegate, DArgs(), del_router(name="SomeoneElse"))
    if rc == 0:
        fail("delegate accepted a read-back naming a DIFFERENT delegate than requested")
    else:
        ok("a read-back naming the wrong delegate BLOCKs")

    rc, out, err = run(m, m.cmd_delegate, DArgs(clear=True), del_router(name=None))
    if rc != 0:
        fail(f"--clear on a cleared delegate exited {rc}. err={err}")
    else:
        ok("--clear removes the delegation")

    rc, out, err = run(m, m.cmd_delegate, DArgs(clear=True), del_router(name="Codex"))
    if rc == 0:
        fail("--clear reported success while the delegate was still set")
    else:
        ok("--clear BLOCKs if the delegate survives")

    # registered on the CLI, not merely defined
    src = TARGET.read_text()
    missing = [n for n in ('add_parser("delegate"', 'add_parser("agent-verdict"',
                           "func=cmd_delegate", "func=cmd_agent_verdict") if n not in src]
    if missing:
        fail(f"not wired to the CLI, so the worker cannot call them: {missing}")
    else:
        ok("both verbs are registered on the CLI")

    print(f"\n== {len(PASSES)} passed, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
