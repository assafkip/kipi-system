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
    return dict(os.environ, W=str(td), OWNER_ROUTE_FIXTURE=str(td / "fake_linear.py"),
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
