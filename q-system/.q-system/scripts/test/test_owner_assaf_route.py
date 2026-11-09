#!/usr/bin/env python3
"""test_owner_assaf_route.py: an owner:assaf ticket never just stays (ASK-3961).

A recorded fake Linear (a module the script loads through OWNER_ROUTE_FIXTURE),
and fake cap-ladder and linear-sync commands that log their argv. Nothing
touches the live board. RED ON MAIN: owner-assaf-route.py does not exist.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "owner-assaf-route.py"
FAILS: list = []

FAKE_LINEAR = r'''
import json, os
W = os.environ["W"]
T = json.load(open(W + "/tickets.json"))
def graphql(q, v):
    open(W + "/linear.log", "a").write(json.dumps({"q": q.split("(")[0].split("{")[0].strip()[:40], "v": v}) + "\n")
    if "issues(" in q:
        return {"issues": {"pageInfo": {"hasNextPage": False}, "nodes": T}}
    if "issueLabels" in q:
        return {"issueLabels": {"nodes": [{"id": "L-" + v["n"]}]}}
    if "issueAddLabel" in q:
        return {"issueAddLabel": {"success": True}}
    if "issueRemoveLabel" in q:
        return {"issueRemoveLabel": {"success": True}}
    return {}
'''
LOG = "import json, sys, os\nopen(os.environ['W'] + '/%s.log', 'a').write(json.dumps(sys.argv[1:]) + '\\n')\nprint('ok')\n"


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else f"\n       {str(detail)[:400]}"))
    if not ok:
        FAILS.append(name)


def world(td: Path, script: Path = SCRIPT):
    (td / "fake_linear.py").write_text(FAKE_LINEAR)
    (td / "ladder.py").write_text(LOG % "ladder")
    (td / "sync.py").write_text(LOG % "sync")
    lab = lambda: [{"id": "L-owner:assaf", "name": "owner:assaf"}]
    (td / "tickets.json").write_text(json.dumps([
        {"id": "u1", "identifier": "ASK-1", "title": "the reviewer posts a status it did not earn",
         "description": "fix the guard", "labels": {"nodes": lab()}},
        {"id": "u2", "identifier": "ASK-2", "title": "renew the vendor subscription",
         "description": "costs $40 a month; should we keep it", "labels": {"nodes": lab()}}]))
    # HOME and CAP_LADDER_STATUS point into the temp dir: the script READS the
    # status file, and a test reads no live path either.
    return dict(os.environ, W=str(td), HOME=str(td), CAP_LADDER_STATUS=str(td / "status.jsonl"),
                OWNER_ROUTE_FIXTURE=str(td / "fake_linear.py"),
                OWNER_ROUTE_LADDER=f"{sys.executable} {td / 'ladder.py'}",
                OWNER_ROUTE_SYNC=f"{sys.executable} {td / 'sync.py'}")


def logged(td: Path, name: str) -> list:
    p = td / f"{name}.log"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def run(env, script: Path = SCRIPT, *a) -> str:
    p = subprocess.run([sys.executable, str(script), *a], env=env, capture_output=True, text=True, timeout=60)
    return p.stdout + p.stderr


def main() -> int:
    print("test_owner_assaf_route.py")
    if not SCRIPT.exists():
        check("owner-assaf-route.py exists", False, "no consumer: an owner:assaf ticket stays forever")
        return 1
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        env = world(td)
        out = run(env)
        check("dry: nothing is written", not any(e["q"].startswith("mutation") for e in logged(td, "linear"))
              and not logged(td, "ladder") and "would" in out, out)
        out = run(env, SCRIPT, "--apply")
        lin = logged(td, "linear")
        check("a plain ticket: owner:sana added, owner:assaf removed, one comment naming why",
              any("issueAddLabel" in json.dumps(e) or e["v"].get("l") == "L-owner:sana" for e in lin)
              and any(e["v"].get("l") == "L-owner:assaf" for e in lin)
              and any(c[:2] == ["progress", "ASK-1"] for c in logged(td, "sync")), (out, lin))
        check("a spend question: listed for the founder through cap-ladder.py --founder-ask, label kept",
              any(c[:2] == ["--founder-ask", "ASK-2"] for c in logged(td, "ladder"))
              and not any(c[:2] == ["progress", "ASK-2"] for c in logged(td, "sync")), out)
    # THE ANSWERED ASK (ASK-3961). The founder resolved the ask; the ticket was
    # still owner:assaf and still matched, so the next night filed the same ask
    # again, forever. Answered means the fleet works it now.
    for case, rows, want_answered in (
            ("resolved", [{"id": "ASK-2:a", "issue": "ASK-2", "kind": "founder-decision",
                           "ask": "ASK-2 asks: renew the vendor subscription: costs $40 a month; should we keep it", "resolved": True,
                           "note": "approved, keep it", "resolved_by": "founder"}], True),
            ("open", [{"id": "ASK-2:a", "issue": "ASK-2", "kind": "founder-decision",
                       "ask": "ASK-2 asks: renew the vendor subscription: costs $40 a month; should we keep it", "resolved": False}], False),
            ("another ask resolved", [{"id": "ASK-2:b", "issue": "ASK-2", "kind": "founder-decision",
                                       "ask": "spend: some other thing", "resolved": True}], False)):
        with tempfile.TemporaryDirectory() as t:
            td = Path(t)
            env = world(td)
            (td / "status.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
            out = run(env, SCRIPT, "--apply")
            asked = any(c[:2] == ["--founder-ask", "ASK-2"] for c in logged(td, "ladder"))
            note = [c for c in logged(td, "sync") if c[:2] == ["progress", "ASK-2"]]
            removed = any(e["v"].get("i") == "u2" and e["v"].get("l") == "L-owner:assaf" for e in logged(td, "linear"))
            if want_answered:
                ok = not asked and removed and note and "approved, keep it" in note[0][2]
            else:
                ok = asked and not removed and not note
            check(f"founder ask {case}: " + ("relabelled owner:sana with the answer, never asked again"
                                             if want_answered else "asked (deduped by the ladder), label kept"),
                  ok, (out, logged(td, "ladder"), note))
    # END TO END with the REAL cap-ladder.py: its --founder-ask writes the ask, its
    # --resolve answers it, and this script's answered() must find that exact row.
    # A fake ladder cannot catch the two disagreeing on the ask text.
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        env = world(td)
        env.pop("OWNER_ROUTE_LADDER")
        for v in ("CAP_LADDER_STATE", "CAP_LADDER_REPORT", "CAP_LADDER_BLOCKERS", "CAP_LADDER_ATTEMPTS",
                  "CAP_LADDER_LINEAR_LOG"):
            env[v] = str(td / f"{v.lower()}.json")
        for v in ("CAP_LADDER_GH", "CAP_LADDER_SYNC", "CAP_LADDER_FABLE", "CAP_LADDER_DRAFTER"):
            env[v] = "/usr/bin/false"
        env["CAP_LADDER_LINEAR_FIXTURE"] = str(td / "no-tickets.json")
        (td / "no-tickets.json").write_text("{}")
        run(env, SCRIPT, "--apply")
        rows = [json.loads(l) for l in (td / "status.jsonl").read_text().splitlines()] if (td / "status.jsonl").exists() else []
        ask_id = next((r["id"] for r in rows if r.get("issue") == "ASK-2"), "")
        p = subprocess.run([sys.executable, str(SCRIPT.parent / "cap-ladder.py"), "--resolve", ask_id or "none",
                            "--note", "keep it", "--by", "founder"], env=env, capture_output=True, text=True, timeout=60)
        (td / "sync.log").write_text("")
        out = run(env, SCRIPT, "--apply")
        note = [c for c in logged(td, "sync") if c[:2] == ["progress", "ASK-2"]]
        check("end to end: the real cap-ladder.py lists the ask, --resolve answers it, and the next run "
              "relabels the ticket with that answer",
              bool(ask_id) and p.returncode == 0 and note and "keep it" in note[0][2]
              and "relabelled owner:sana (the founder answered its ask)" in out, (rows, p.stdout + p.stderr, out))

    # Codex PR #670 findings, each pinned.
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        env = world(td)
        tk = json.loads((td / "tickets.json").read_text())
        tk.append({"id": "u3", "identifier": "ASK-3", "title": "Fix client synchronization",
                   "description": "the vendor webhook drops events; see the contract test", "labels": tk[0]["labels"]})
        tk.append({"id": "u4", "identifier": "ASK-4", "title": "Renew service",
                   "description": "It lapses Friday. Should we pay the $40 invoice? The old card expired.",
                   "labels": tk[0]["labels"]})
        (td / "tickets.json").write_text(json.dumps(tk))
        out = run(env, SCRIPT, "--apply")
        asks = {c[1]: c[3] for c in logged(td, "ladder") if c[:1] == ["--founder-ask"]}
        check("codex P2: a ticket that only names a client, vendor or contract asks nothing: it is relabelled",
              "ASK-3" not in asks and any(c[:2] == ["progress", "ASK-3"] for c in logged(td, "sync")), (out, asks))
        check("codex P2: a question only in the description reaches the ask, amount and all",
              "Should we pay the $40 invoice?" in asks.get("ASK-4", ""), asks)
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        env = world(td)
        (td / "fake_linear.py").write_text(FAKE_LINEAR.replace(
            'return {"issueRemoveLabel": {"success": True}}', 'return {"issueRemoveLabel": {"success": False}}'))
        out = run(env, SCRIPT, "--apply")
        check("codex P2: a refused owner:assaf removal is not reported as relabelled and posts no comment",
              "ASK-1: relabelled" not in out and "retries" in out
              and not any(c[:2] == ["progress", "ASK-1"] for c in logged(td, "sync")), out)
    with tempfile.TemporaryDirectory() as t:
        td = Path(t)
        mut = td / "owner-assaf-route.py"
        mut.write_text(SCRIPT.read_text().replace('m = QUESTION_RE.search(', 'm = None and QUESTION_RE.search(', 1))
        (td / "linear-sync.py").write_text("")
        env = world(td, mut)
        run(env, mut, "--apply")
        check("mutant: with the question match dropped, the spend ticket is relabelled (so the check can fail)",
              any(c[:2] == ["progress", "ASK-2"] for c in logged(td, "sync")))
    print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
