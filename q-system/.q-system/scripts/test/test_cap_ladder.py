#!/usr/bin/env python3
"""test_cap_ladder.py: every cap moves on, ends on a decision, or waits on a named event (ASK-3824).

Drives cap-ladder.py against a fixture world: a real attempts ledger in a temp
dir (written only through attempts-ledger.py, as in production), and fakes for
gh, linear-sync.py, the Linear writes, fable-escalate.py, the DoR drafter and the
process table. No live path is touched: every seam is set, and the script
refuses to run under pytest without CAP_LADDER_STATE.

Founder, 2026-11-08: "What's the point of timed retries? What's gonna change in
seven, fourteen or 28 days?" and "but what happens if nothing changed? the
ticket just stays?" So the cases below pin both answers: an unchanged held
ticket never re-enters by age, and every capped ticket either climbs, ends on a
recorded decision, or waits on an event the report names.

RED ON MAIN: point CAP_LADDER_TEST_ROOT at a main tree's scripts dir. The mutant
at the end proves the core assertion can fail.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPTS = Path(os.environ.get("CAP_LADDER_TEST_ROOT") or Path(__file__).resolve().parent.parent)
LADDER = SCRIPTS / "cap-ladder.py"
LEDGER = SCRIPTS / "attempts-ledger.py"
FAILS: list = []


def check(name: str, ok: bool, detail="") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else f"\n       {str(detail)[:600]}"))
    if not ok:
        FAILS.append(name)


FAKE_GH = r'''#!/usr/bin/env python3
import json, sys, os
world = os.environ["W"] + "/gh-world.json"
open(os.environ["W"] + "/gh.log", "a").write(json.dumps(sys.argv[1:]) + "\n")
w = json.load(open(world))
a = sys.argv[1:]
slug = a[a.index("-R") + 1] if "-R" in a else ""
def save(): json.dump(w, open(world, "w"))
if a[:2] == ["pr", "list"]:
    print(json.dumps([p for p in w.get(slug, []) if p["state"] == "OPEN"]))
elif a[:2] == ["pr", "view"]:
    p = [p for p in w.get(slug, []) if str(p["number"]) == a[2]]
    print(p[0]["state"] if p else "CLOSED")
elif a[:2] == ["pr", "close"]:
    for p in w.get(slug, []):
        if str(p["number"]) == a[2]:
            p["state"] = "CLOSED"
    save()
elif a[:1] == ["api"]:
    path, jq = a[1], a[-1]
    if path.endswith("/commits/main"):
        print(w.get("main_sha", "m1"))
    elif "/compare/main..." in path:
        b = path.split("/compare/main...", 1)[1]
        if w.get("compare_fails"):
            sys.stderr.write("HTTP 502: Bad Gateway\n"); sys.exit(1)
        if b not in w.get("branches", {}):
            sys.stderr.write("gh: Not Found (HTTP 404)\n"); sys.exit(1)
        print(w["branches"][b] if jq == ".ahead_by" else json.dumps(w.get("branch_files", [])))
    elif "/compare/" in path:
        print(json.dumps(w.get("changed", [])))
elif a[:2] == ["pr", "create"]:
    if w.get("create_fails"):
        sys.exit(1)
    head = a[a.index("--head") + 1]
    prs = w.setdefault(slug, [])
    n = max([p["number"] for p in prs] + [0]) + 1
    prs.append({"number": n, "headRefName": head, "headRefOid": "b" * 40, "title": "t",
                "baseRefName": "main", "url": "u/%d" % n, "state": "OPEN"})
    save()
    print("https://github.com/%s/pull/%d" % (slug, n))
'''

# The fake RCA agent: each call pops the next answer queued for its issue, writes
# it as the RCA file and prints the contract JSON. An empty answer is "no RCA".
FAKE_FABLE = r'''#!/usr/bin/env python3
import json, sys, os
W = os.environ["W"]
open(W + "/fable.log", "a").write(json.dumps(sys.argv[1:]) + "\n")
issue = sys.argv[sys.argv.index("--issue") + 1]
lane = os.environ.get("FAKE_FABLE_LANE")    # a lane-mark.py start landing mid-RCA (ASK-4395 round 1)
if lane:
    spec = json.loads(lane)
    open(spec["path"], "w").write(json.dumps(spec["marker"]))
w = json.load(open(W + "/gh-world.json"))
q = w.setdefault("fable", {}).setdefault(issue, [])
text = q.pop(0) if q else "SURFACE: s\nSTRUCTURAL: t\nSTOP: u\nNEXT: do the thing in q-system/x.py\nREFUTE: run y\n"
json.dump(w, open(W + "/gh-world.json", "w"))
if not text:
    print("{}"); sys.exit(0)
n = sum(1 for _ in open(W + "/fable.log"))
p = "%s/rca-%s-%d.md" % (W, issue, n)
open(p, "w").write(text)
print(json.dumps({"rca_path": p}))
'''

FAKE_LOG = r'''#!/usr/bin/env python3
import json, sys, os
open(os.environ["W"] + "/%s.log", "a").write(json.dumps(sys.argv[1:]) + "\n")
'''

RCA = "SURFACE: s\nSTRUCTURAL: t\nSTOP: u\nNEXT: do the thing in q-system/x.py\nREFUTE: run y\n"


def make_world(tmp: Path) -> dict:
    (tmp / "bin").mkdir()
    (tmp / "reviews").mkdir()
    (tmp / "bin/gh").write_text(FAKE_GH)
    (tmp / "bin/fable").write_text(FAKE_FABLE)
    (tmp / "bin/sync").write_text(FAKE_LOG % "sync")
    (tmp / "bin/drafter").write_text(FAKE_LOG % "drafter")
    (tmp / "bin/ps").write_text("#!/bin/sh\ncat \"$W/ps.txt\" 2>/dev/null\nexit 0\n")
    for f in (tmp / "bin").iterdir():
        f.chmod(0o755)
    (tmp / "gh-world.json").write_text(json.dumps({"o/r": [
        {"number": 10, "headRefName": "sana/ask-1", "headRefOid": "a" * 40, "title": "fix (ASK-1)",
         "baseRefName": "main", "url": "u/10", "state": "OPEN"}],
        "branches": {"sana/ask-1": 2}, "branch_files": ["q-system/a.py"], "main_sha": "m1"}))

    def tk(st, labels, project="kipi-system"):
        return {"state_type": st, "labels": labels, "project": project, "title": "t", "description": "d"}
    (tmp / "linear.json").write_text(json.dumps({
        "ASK-1": tk("started", ["owner:sana"]), "ASK-2": tk("backlog", ["owner:sana"]),
        "ASK-3": tk("completed", ["owner:sana"]), "ASK-4": tk("backlog", ["owner:sana"], "elsewhere"),
        "ASK-50": tk("backlog", ["owner:sana"]), "ASK-51": tk("backlog", []),
    }))
    (tmp / "attempts.json").write_text("{}")
    py = sys.executable
    return {
        "W": str(tmp), "PATH": os.environ.get("PATH", ""), "HOME": str(tmp),
        "CAP_LADDER_STATE": str(tmp / "state/state.json"),
        "CAP_LADDER_REPORT": str(tmp / "state/report.json"),
        "CAP_LADDER_BLOCKERS": str(tmp / "kipi/cap-ladder-blockers.json"),
        "CAP_LADDER_STATUS": str(tmp / "state/morning-status.jsonl"),
        "CAP_LADDER_LINEAR_LOG": str(tmp / "linear-writes.log"),
        "CAP_LADDER_ATTEMPTS": str(tmp / "attempts.json"),
        "CAP_LADDER_REVIEWS": str(tmp / "reviews"),
        "CAP_LADDER_GH": f"{py} {tmp}/bin/gh",
        "CAP_LADDER_SYNC": f"{py} {tmp}/bin/sync",
        "CAP_LADDER_FABLE": f"{py} {tmp}/bin/fable",
        "CAP_LADDER_DRAFTER": f"{py} {tmp}/bin/drafter",
        "CAP_LADDER_PS": f"{tmp}/bin/ps",
        "CAP_LADDER_LINEAR_FIXTURE": str(tmp / "linear.json"),
        "KIPI_LANES_DIR": str(tmp / "lanes"),
        "CAP_LADDER_TARGETS": json.dumps([{"slug": "o/r", "project": "kipi-system"}]),
        "CAP_LADDER_MODEL_FP": "fp1",
        "CAP_LADDER_NOW": "2026-11-09T04:40:00+00:00",
    }


def ladder(env: dict, *args, script: Path = LADDER) -> str:
    p = subprocess.run([sys.executable, str(script), *args], env=env, capture_output=True, text=True, timeout=60)
    return p.stdout + p.stderr


def led(env: dict, *op) -> None:
    subprocess.run([sys.executable, str(LEDGER), env["CAP_LADDER_ATTEMPTS"], *op],
                   env=env, capture_output=True, text=True, check=False)


def ledger_row(env: dict, issue: str) -> dict:
    return json.loads(Path(env["CAP_LADDER_ATTEMPTS"]).read_text()).get(issue) or {}


def log(env: dict, name: str) -> list:
    p = Path(env["W"]) / f"{name}.log"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def writes(env: dict) -> list:
    p = Path(env["CAP_LADDER_LINEAR_LOG"])
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def reset(env: dict) -> None:
    for name in ("gh", "sync", "fable", "drafter"):
        (Path(env["W"]) / f"{name}.log").unlink(missing_ok=True)
    Path(env["CAP_LADDER_LINEAR_LOG"]).unlink(missing_ok=True)


def world(env: dict, **kw) -> None:
    p = Path(env["W"]) / "gh-world.json"
    w = json.loads(p.read_text())
    for k, v in kw.items():
        if k == "fable":
            w.setdefault("fable", {}).update(v)
        else:
            w[k] = v
    p.write_text(json.dumps(w))


def edit_ticket(env: dict, issue: str, **kw) -> None:
    p = Path(env["CAP_LADDER_LINEAR_FIXTURE"])
    d = json.loads(p.read_text())
    d[issue].update(kw)
    p.write_text(json.dumps(d))


def at(env: dict, day: int) -> None:
    from datetime import datetime, timedelta, timezone
    env["CAP_LADDER_NOW"] = (datetime(2026, 11, 9, 4, 40, tzinfo=timezone.utc) + timedelta(days=day)).isoformat()


def three_rungs(env: dict) -> None:
    """Rungs 1 to 3, one cap each, so the next cap is rung 4."""
    for day in (0, 1, 2):
        at(env, day)
        led(env, "record-capout", "ASK-1", f"cap {day}")
        ladder(env, "--apply")


def case_rungs(script: Path = LADDER) -> bool:
    """Rungs 1 to 3 on one ticket. Returns whether rung 1's clear held."""
    with tempfile.TemporaryDirectory() as td:
        env = make_world(Path(td))
        led(env, "record-capout", "ASK-1", "hit the 3-round cap still at 'REQUEST CHANGES' on PR #10")
        ladder(env, "--apply", script=script)
        a_clear = not ledger_row(env, "ASK-1").get("capout")
        if script != LADDER:
            return a_clear
        gh = log(env, "gh")
        check("rung 1: the capped PR is closed, branch kept (no --delete-branch)",
              any(c[:3] == ["pr", "close", "10"] for c in gh) and not any("--delete-branch" in c for c in gh), gh)
        check("rung 1: a new PR opens on the same branch",
              any(c[:2] == ["pr", "create"] and "sana/ask-1" in c for c in gh), gh)
        check("rung 1: the capout record is cleared, so the redrives re-enter it", a_clear, ledger_row(env, "ASK-1"))
        check("rung 1: Fable writes an RCA (--kind rca) before the work continues",
              any(c[:2] == ["--kind", "rca"] for c in log(env, "fable")), log(env, "fable"))
        check("rung 1: the ticket is requeued and the comment names the next rung",
              any(c[:2] == ["requeue", "ASK-1"] for c in log(env, "sync"))
              and any(c[0] == "progress" and "rung 2" in c[2] for c in log(env, "sync")), log(env, "sync"))
        reset(env)
        ladder(env, "--apply")
        check("idempotent: a second run with no new cap writes nothing",
              not log(env, "sync") and not writes(env), log(env, "sync"))
        at(env, 1)
        led(env, "record-capout", "ASK-1", "again")
        ladder(env, "--apply")
        check("rung 2: the next attempt runs on Codex (ledger flag the worker reads)",
              ledger_row(env, "ASK-1").get("ladder_runner_codex") is True)
        at(env, 2)
        reset(env)
        led(env, "record-capout", "ASK-1", "again")
        ladder(env, "--apply")
        check("rung 3: needs-scope goes on and the drafter rewrites this one issue",
              ["label", "ASK-1", "needs-scope"] in log(env, "sync")
              and any("--issue" in c and "ASK-1" in c for c in log(env, "drafter")), log(env, "sync"))
        check("rung 3: the comment says the next step is a decision, never a timed retry",
              any(c[0] == "progress" and "never a timed retry" in c[2] for c in log(env, "sync")))
        return a_clear


def decision_world(answers: list):
    td = tempfile.TemporaryDirectory()
    env = make_world(Path(td.name))
    three_rungs(env)
    reset(env)
    world(env, fable={"ASK-1": answers})
    at(env, 3)
    led(env, "record-capout", "ASK-1", "fourth cap")
    return td, env


def case_decisions() -> None:
    td, env = decision_world([RCA + "DECISION: SPLIT\nSUBTICKET: part one :: one works\nSUBTICKET: part two :: two works\n"])
    out = ladder(env, "--apply")
    w = writes(env)
    check("SPLIT: two sub-tickets filed, each with a DoR, and the parent closes Done",
          sum(1 for x in w if x["op"] == "create" and "Definition of Ready" in x["description"]) == 2
          and {"op": "state", "issue": "ASK-1", "type": "completed"} in w
          and any(c[0] == "progress" and "Split into" in c[2] for c in log(env, "sync")), (w, out))
    td.cleanup()

    td, env = decision_world([RCA + "DECISION: CLOSE\n"])
    ladder(env, "--apply")
    check("CLOSE: Canceled, one comment that carries the RCA path",
          {"op": "state", "issue": "ASK-1", "type": "canceled"} in writes(env)
          and any(c[0] == "progress" and "rca-ASK-1" in c[2] for c in log(env, "sync")), writes(env))
    td.cleanup()

    td, env = decision_world([RCA + "DECISION: BLOCKED-ON ASK-50\n"])
    ladder(env, "--apply")
    bpath = Path(env["CAP_LADDER_BLOCKERS"])
    blockers = json.loads(bpath.read_text()) if bpath.exists() else {}
    check("BLOCKED-ON an owned ticket: a blocks relation, the hold flag, the blocker counted",
          {"op": "relate", "blocker": "ASK-50", "blocked": "ASK-1"} in writes(env)
          and ledger_row(env, "ASK-1").get("ladder_hold") is True and blockers == {"ASK-50": 1},
          (writes(env), blockers))
    quiet, out = True, ""
    for day in (10, 17, 31):
        reset(env)
        at(env, day)
        out = ladder(env, "--apply")
        quiet = quiet and not log(env, "sync") and "waiting for it to close" in out
    check("an unchanged held ticket does NOT re-enter after 7, 14 or 28 days, and says what it waits on",
          quiet and ledger_row(env, "ASK-1").get("ladder_hold") is True, out)
    edit_ticket(env, "ASK-50", labels=[])
    ladder(env, "--apply")
    rep = json.loads(Path(env["CAP_LADDER_REPORT"]).read_text())["rows"]
    check("a blocker that lost its owner is RED in the report (a dead end the sweep flags)",
          any(r["issue"] == "ASK-1" and r.get("red") for r in rep), rep)
    # PR #662 round 4, minor: unreadable is not ownerless. linear-owner-sweep.py,
    # the consumer the docstring names for a red row, cannot fix a failed read.
    fx = Path(env["CAP_LADDER_LINEAR_FIXTURE"])
    tickets = json.loads(fx.read_text())
    tickets.pop("ASK-50")
    fx.write_text(json.dumps(tickets))
    out = ladder(env, "--apply")
    rep = json.loads(Path(env["CAP_LADDER_REPORT"]).read_text())["rows"]
    check("an unreadable blocker is NOT red as ownerless; the hold stays and the next run reads it again",
          not any(r["issue"] == "ASK-1" and r.get("red") for r in rep) and "no owner" not in out
          and ledger_row(env, "ASK-1").get("ladder_hold") is True, (out, rep))
    td.cleanup()

    td, env = decision_world([RCA + "DECISION: BLOCKED-ON waiting for the vendor to answer\n",
                              RCA + "DECISION: SPLIT\nSUBTICKET: a :: b\n"])
    out = ladder(env, "--apply")
    check("a free-text BLOCKED-ON is refused and the agent is asked again for SPLIT or CLOSE only",
          "free text" in out and any("split-close" in c for c in log(env, "fable"))
          and any(x["op"] == "create" for x in writes(env)), out)
    td.cleanup()

    td, env = decision_world([RCA + "DECISION: BLOCKED-ON ASK-51\n", RCA + "no decision here\n"])
    out = ladder(env, "--apply")
    w = writes(env)
    made = [x for x in w if x["op"] == "create"]
    check("a blocker with no owner is refused; two invalid answers default to SPLIT on the RCA's findings",
          "no owner" in out and len(made) == 1 and "do the thing" in made[0]["description"], (out, w))
    td.cleanup()

    td, env = decision_world([RCA + "DECISION: BLOCKED-ON FOUNDER-DECISION: spend: approve the vendor plan\n"])
    ladder(env, "--apply")
    st = Path(env["CAP_LADDER_STATUS"])
    rows = [json.loads(l) for l in st.read_text().splitlines()] if st.exists() else []
    check("FOUNDER-DECISION lands in the morning status file and pages nobody",
          any(r["issue"] == "ASK-1" and "vendor" in r["ask"] for r in rows)
          and ledger_row(env, "ASK-1").get("ladder_hold") is True, rows)
    td.cleanup()

    td, env = decision_world([""])
    ladder(env, "--apply")
    rep = json.loads(Path(env["CAP_LADDER_REPORT"]).read_text())["rows"]
    check("a capped ticket with no decision record is RED in the report, never silent",
          any(r["issue"] == "ASK-1" and r.get("red") and r.get("decision") is None for r in rep)
          and ledger_row(env, "ASK-1").get("capout") is True, rep)
    td.cleanup()


def case_events() -> None:
    for name, poke in (
            ("(a) the blocker ticket closed", lambda e: edit_ticket(e, "ASK-50", state_type="completed")),
            ("(b) a file the last attempt touched changed on main", lambda e: world(e, changed=["q-system/a.py"])),
            ("(b) a file the RCA names changed on main", lambda e: world(e, changed=["q-system/x.py"])),
            ("(c) the description was edited", lambda e: edit_ticket(e, "ASK-1", description="rewritten")),
            ("(d) the model config changed", lambda e: e.update(CAP_LADDER_MODEL_FP="fp2"))):
        td, env = decision_world([RCA + "DECISION: BLOCKED-ON ASK-50\n"])
        ladder(env, "--apply")
        reset(env)
        at(env, 4)
        poke(env)
        out = ladder(env, "--apply")
        check(f"event {name} re-enters the held ticket",
              ledger_row(env, "ASK-1").get("ladder_hold") is not True
              and any(c[:2] == ["requeue", "ASK-1"] for c in log(env, "sync")) and "re-entered" in out, out)
        td.cleanup()
    td, env = decision_world([RCA + "DECISION: BLOCKED-ON ASK-50\n"])
    ladder(env, "--apply")
    reset(env)
    at(env, 4)
    world(env, changed=["some/unrelated.py"])
    ladder(env, "--apply")
    check("a change on main to an unrelated file is not an event", not log(env, "sync"))
    td.cleanup()


def case_edges() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = make_world(Path(td))
        for _ in range(3):
            led(env, "bump-attempt", "ASK-2", "no PR opened")
            led(env, "bump-attempt", "ASK-4", "no PR opened")
        led(env, "record-capout", "ASK-3", "closed ticket")
        out = ladder(env)
        check("dry: without --apply nothing is written",
              not log(env, "sync") and not log(env, "fable") and "[dry]" in out, out)
        ladder(env, "--apply")
        check("attempts spent, no PR, no branch: count cleared and requeued, no PR opened",
              "count" not in ledger_row(env, "ASK-2") and any(c[:2] == ["requeue", "ASK-2"] for c in log(env, "sync"))
              and not any(c[:2] == ["pr", "create"] and "sana/ask-2" in c for c in log(env, "gh")))
        check("a closed ticket is left alone", not any("ASK-3" in c for c in log(env, "sync")))
        out = ladder(env, "--apply")
        check("a ticket with no dispatch target names the router tickets and writes nothing",
              not any("ASK-4" in c for c in log(env, "sync")) and "ASK-3959" in out, out)
    with tempfile.TemporaryDirectory() as td:
        env = make_world(Path(td))
        world(env, branches={"sana/ask-1": 2, "sana/ask-2": 2})
        for _ in range(3):
            led(env, "bump-attempt", "ASK-2", "no PR opened")
        ladder(env, "--apply")
        check("no open PR but the branch holds commits: a PR opens from it, so the worker resumes there",
              any(c[:2] == ["pr", "create"] and "sana/ask-2" in c for c in log(env, "gh")))
    with tempfile.TemporaryDirectory() as td:
        env = make_world(Path(td))
        world(env, create_fails=True)
        led(env, "record-capout", "ASK-1", "x")
        out = ladder(env, "--apply")
        check("a successor PR that cannot open keeps the cap record, so the next run retries",
              ledger_row(env, "ASK-1").get("capout") is True and "retries" in out, out)
    with tempfile.TemporaryDirectory() as td:
        env = make_world(Path(td))
        (Path(td) / "reviews" / ".round-cap-o_r-pr-10").write_text("")
        ladder(env, "--apply")
        check("a review-capped open PR moves to a new PR", any(c[:2] == ["pr", "create"] for c in log(env, "gh")))
    with tempfile.TemporaryDirectory() as td:
        env = make_world(Path(td))
        led(env, "record-capout", "ASK-1", "x")
        (Path(td) / "ps.txt").write_text("bash converge.sh --issue ASK-1 --max-rounds 4\n")
        ladder(env, "--apply")
        check("a live converge on the issue holds the ladder off", not log(env, "sync"))


def case_worker() -> None:
    src = (SCRIPTS / "linear-worker.sh").read_text()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    hold, dry = code.find('get "$ISSUE" ladder_hold'), code.find('[dry] would work $ISSUE')
    check("worker: skips a ticket holding ladder_hold before the dry pick", hold != -1 and hold < dry)
    m = re.search(r"^ladder_runner_for\(\) \{.*?^\}", src, re.S | re.M)
    check("worker: ladder_runner_for exists and the primary launch branches on it",
          bool(m) and "primary_run()" in code and 'ladder_runner_for "$ISSUE")" = "codex"' in code
          and "if primary_run; then" in code)
    if m:
        with tempfile.TemporaryDirectory() as td:
            led_path = Path(td) / "a.json"
            led_path.write_text(json.dumps({"ASK-9": {"ladder_runner_codex": True}}))
            sh = f'LEDGER="{LEDGER}"; ATTEMPTS="{led_path}"\n{m.group(0)}\n' \
                 'printf "[%s][%s]" "$(ladder_runner_for ASK-9)" "$(ladder_runner_for ASK-8)"'
            got = subprocess.run(["bash", "-c", sh], capture_output=True, text=True).stdout
            check("worker: the flag set means codex, unset means the default runner", got == "[codex][]", got)
    s, e = src.find("PRIORITY_RANK = {"), src.find("pool.sort(key=pick_order_key)")
    check("worker: the pick order reads cap-ladder-blockers.json", s != -1 and e != -1)
    if s != -1 and e != -1:
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "cap-ladder-blockers.json").write_text(json.dumps({"ASK-B": 2}))
            pool = [{"identifier": "ASK-A", "priority": 2, "createdAt": "2026-01-01"},
                    {"identifier": "ASK-B", "priority": 2, "createdAt": "2026-06-01"},
                    {"identifier": "ASK-U", "priority": 1, "createdAt": "2026-09-01"}]
            ns = {"pool": pool, "state_dir": td, "json": json, "os": os, "expired_park": lambda i: False}
            exec(src[s:e + len("pool.sort(key=pick_order_key)")], ns)
            got = [i["identifier"] for i in ns["pool"]]
            check("worker: a ticket blocking 2 others is picked before an equal-priority ticket blocking 0, "
                  "and never ahead of a higher band", got == ["ASK-U", "ASK-B", "ASK-A"], got)


def case_sites() -> None:
    def code(path: Path) -> str:
        return "\n".join(l for l in path.read_text().splitlines() if not l.lstrip().startswith("#"))
    worker = code(SCRIPTS / "linear-worker.sh")
    check("site: linear-worker.sh no longer asks for 'Human action needed'", "Human action needed" not in worker)
    check("site: linear-worker.sh no longer pages 'needs a human' at its attempts cap",
          "stuck after $MAX_ATTEMPTS attempts - needs a human" not in worker)
    check("site: converge.sh no longer parks 'until you clear it'", "until you clear it" not in code(SCRIPTS / "converge.sh"))
    check("site: pr-review-agent.sh no longer asks for 'a human decision' or files the cap ticket",
          "needs a human decision" not in code(SCRIPTS / "pr-review-agent.sh")
          and "decide merge, rework or close" not in code(SCRIPTS / "pr-review-agent.sh"))
    check("site: ci-redrive.py no longer waits 'until a human clears'",
          "until a human clears" not in (SCRIPTS / "ci-redrive.py").read_text())
    for f in ("linear-worker.sh", "converge.sh", "pr-review-agent.sh", "ci-redrive.py", "review-redrive.py"):
        check(f"site: {f} names cap-ladder.py as the next step", "cap-ladder.py" in (SCRIPTS / f).read_text())
    check("ladder: no timed re-entry is left in the code",
          LADDER.exists() and not re.search(r"COOLDOWN|cooldown_days", LADDER.read_text()))


def case_review_fixes() -> None:
    """PR #662 review round 1, each major pinned."""
    # major 2: a gh fault on the compare is not "no branch".
    with tempfile.TemporaryDirectory() as td:
        env = make_world(Path(td))
        world(env, compare_fails=True)
        for _ in range(3):
            led(env, "bump-attempt", "ASK-2", "no PR opened")
        out = ladder(env, "--apply")
        check("review: a gh fault on the branch compare keeps the cap and retries, never clears it",
              ledger_row(env, "ASK-2").get("count") == 3 and "retries" in out
              and not any(c[:2] == ["requeue", "ASK-2"] for c in log(env, "sync")), out)
    # nonblocking major: unattended sub-tickets are marked needs-triage.
    td, env = decision_world([RCA + "DECISION: SPLIT\nSUBTICKET: a :: b\n"])
    ladder(env, "--apply")
    made = [x for x in writes(env) if x["op"] == "create"]
    check("review: a SPLIT sub-ticket carries owner:sana and needs-triage",
          made and set(made[0].get("labels") or []) >= {"owner:sana", "needs-triage"}, made)
    td.cleanup()
    # major 3: the founder ask has a reader, a resolve command, and resolving releases the hold.
    td, env = decision_world([RCA + "DECISION: BLOCKED-ON FOUNDER-DECISION: access: grant the repo token\n"])
    ladder(env, "--apply")
    import importlib.util
    spec = importlib.util.spec_from_file_location("fa", str(SCRIPTS / "founder_asks.py"))
    fa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fa)
    rows, err = fa.collect(None, {}, status=Path(env["CAP_LADDER_STATUS"]))
    check("review: founder_asks.py renders the ask with the command that resolves it",
          err is None and any("ASK-1" in r and "--resolve ASK-1" in r for r in rows), (rows, err))
    out = ladder(env, "--resolve", "ASK-1", "--note", "token granted")
    rows2 = (fa.collect(None, {}, status=Path(env["CAP_LADDER_STATUS"])) or ([], None))[0]   # None is OFF: nothing open
    reset(env)
    at(env, 4)
    out2 = ladder(env, "--apply")
    check("review: --resolve marks it resolved, the brief drops it, and the held ticket re-enters",
          "1 ask for" in out and not rows2 and "founder decision is resolved" in out2
          and ledger_row(env, "ASK-1").get("ladder_hold") is not True, (out, rows2, out2))
    td.cleanup()
    src = (SCRIPTS / "morning-brief.py").read_text()
    check("review: the morning brief registers founder_asks.py", '"founder_asks.py"' in src)


def case_review_round2() -> None:
    """PR #662 review round 2, each finding pinned."""
    td, env = decision_world([RCA + "DECISION: BLOCKED-ON FOUNDER-DECISION: access: grant token A\n",
                              RCA + "DECISION: BLOCKED-ON FOUNDER-DECISION: spend: approve plan B\n"])
    ladder(env, "--apply")                                  # hold 1, ask A
    ladder(env, "--resolve", "ASK-1")                       # A resolved
    at(env, 4)
    ladder(env, "--apply")                                  # re-enters on A
    at(env, 5)
    led(env, "record-capout", "ASK-1", "fifth cap")
    ladder(env, "--apply")                                  # hold 2, ask B
    reset(env)
    at(env, 6)
    out = ladder(env, "--apply")
    check("round 2 major: a resolved earlier ask does NOT release a later founder hold on the same issue",
          ledger_row(env, "ASK-1").get("ladder_hold") is True and not log(env, "sync"), out)
    rows = [json.loads(l) for l in Path(env["CAP_LADDER_STATUS"]).read_text().splitlines()]
    check("round 2 minor: two distinct asks on one issue are both listed, each with its own id",
          len({r["id"] for r in rows}) == 2 and sum(1 for r in rows if not r["resolved"]) == 1, rows)
    ladder(env, "--founder-ask", "ASK-1", "founder-decision", "access: a third thing")
    ladder(env, "--resolve", "ASK-1", "--note", "only the newest")
    rows = [json.loads(l) for l in Path(env["CAP_LADDER_STATUS"]).read_text().splitlines()]
    check("round 2 minor: --resolve ISSUE resolves only its newest open ask",
          sum(1 for r in rows if not r["resolved"]) == 1 and [r["note"] for r in rows if r.get("note")] == ["only the newest"] or
          sum(1 for r in rows if r.get("note") == "only the newest") == 1, rows)
    td.cleanup()


def case_pytest_refusal() -> None:
    """PR #662 round 2, minor: the live-path refusal runs before every verb.

    HOME and every seam point at a temp world, so even a broken refusal reaches
    no live path; only CAP_LADDER_STATE is unset, which is what the refusal keys
    on. (This check once ran with the real HOME: a regression in the refusal
    would have written the real morning status file.)
    """
    for verb in (["--apply"], ["--resolve", "ASK-1"], ["--founder-ask", "ASK-1", "founder-decision", "spend: x"]):
        with tempfile.TemporaryDirectory() as td:
            env = make_world(Path(td))
            env.pop("CAP_LADDER_STATE")
            env["PYTEST_CURRENT_TEST"] = "x"
            p = subprocess.run([sys.executable, str(LADDER), *verb], env=env, capture_output=True, text=True)
            check(f"under pytest without CAP_LADDER_STATE, {verb[0]} is refused (exit 4) before it reads or writes",
                  p.returncode == 4 and not log(env, "gh") and not Path(env["CAP_LADDER_STATUS"]).exists()
                  and not (Path(td) / ".local").exists(), p.stdout + p.stderr)


def case_ask_lifecycle() -> None:
    """ONE founder ask, its whole life, through the real CLI (ASK-4069).

    PR #662 spent three review rounds on this channel and each fix caused the
    next round's major, because each round pinned only the scenario the reviewer
    named. Round 3's bug was the "re-cap with the same ask" step below: the
    dedupe returned "", the hold stored it, and no resolve could release it.
    So this case walks every step in order, against the real writer
    (--apply, --founder-ask, --resolve) and the real reader (founder_asks.collect).
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("fa_life", str(SCRIPTS / "founder_asks.py"))
    fa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fa)
    A = "access: grant the repo token"
    td, env = decision_world([RCA + f"DECISION: BLOCKED-ON FOUNDER-DECISION: {A}\n",
                              RCA + f"DECISION: BLOCKED-ON FOUNDER-DECISION: {A}\n",
                              RCA + "DECISION: BLOCKED-ON FOUNDER-DECISION: spend: approve plan B\n"])
    status = Path(env["CAP_LADDER_STATUS"])

    def rows():
        return [json.loads(l) for l in status.read_text().splitlines()] if status.exists() else []

    def held_on():
        st = json.loads(Path(env["CAP_LADDER_STATE"]).read_text()).get("ASK-1") or {}
        return st.get("held"), (st.get("decision") or {}).get("ask_id")

    def hold_flag():
        return ledger_row(env, "ASK-1").get("ladder_hold") is True

    try:
        ladder(env, "--apply")                                    # 1. create + hold
        held, x = held_on()
        check("lifecycle 1: a FOUNDER-DECISION holds the ticket on the id of its one open ask",
              held is True and hold_flag() and bool(x) and [r["id"] for r in rows()] == [x], (held, x, rows()))
        out = ladder(env, "--founder-ask", "ASK-1", "founder-decision", A)   # 2. dedupe
        check("lifecycle 2: the same ask again is not a second row, and the CLI names the open id",
              len(rows()) == 1 and x in out, (out, rows()))
        fa_rows, err = fa.collect(None, {}, status=status)
        check("lifecycle 2: the brief lists it once, with the command that resolves that id",
              err is None and len(fa_rows) == 1 and f"--resolve {x}" in fa_rows[0], (fa_rows, err))
        at(env, 4)                                                # 3. release on event (b)
        world(env, changed=["q-system/a.py"])
        out = ladder(env, "--apply")
        world(env, changed=[])
        check("lifecycle 3: event (b) releases the hold while the ask is still open",
              "re-entered" in out and not hold_flag() and held_on()[0] is False, out)
        at(env, 5)                                                # 4. re-cap, same ask
        led(env, "record-capout", "ASK-1", "fifth cap")
        ladder(env, "--apply")
        held, x2 = held_on()
        check("lifecycle 4: re-capped on the same ask, the hold waits on the SAME open id (round 3 major)",
              held is True and hold_flag() and x2 == x and len(rows()) == 1, (held, x, x2, rows()))
        at(env, 6)                                                # 5. resolve by id
        out = ladder(env, "--resolve", x, "--note", "token granted")
        check("lifecycle 5: --resolve <id> resolves exactly that ask and says so",
              "1 ask" in out and [r["resolved"] for r in rows()] == [True], (out, rows()))
        reset(env)
        at(env, 7)
        out = ladder(env, "--apply")
        check("lifecycle 5: the next run releases the hold that waited on it",
              "founder decision is resolved" in out and not hold_flag() and held_on()[0] is False, out)
        at(env, 8)                                                # 6. a second, distinct ask
        led(env, "record-capout", "ASK-1", "sixth cap")
        ladder(env, "--apply")
        held, y = held_on()
        ladder(env, "--founder-ask", "ASK-1", "founder-decision", "outside: a third thing")
        out = ladder(env, "--resolve", "ASK-1")                   # by issue: the newest open, not y
        reset(env)
        at(env, 9)
        ladder(env, "--apply")
        check("lifecycle 6: a distinct ask gets its own id, and --resolve ISSUE resolves the newest, "
              "so the hold on the other ask stays",
              held is True and y and y != x and hold_flag() and held_on() == (True, y)
              and sum(1 for r in rows() if not r["resolved"]) == 1
              and next(r for r in rows() if r["id"] == y)["resolved"] is False, (y, out, rows()))
        p = subprocess.run([sys.executable, str(LADDER), "--resolve", "ASK-404"], env=env,
                           capture_output=True, text=True, timeout=60)
        check("lifecycle 7: --resolve with no open match says so and exits non-zero, never 'resolved'",
              p.returncode != 0 and "no open ask" in p.stdout + p.stderr and "resolved;" not in p.stdout,
              (p.returncode, p.stdout + p.stderr))
    finally:
        td.cleanup()


def _status_rows(env: dict) -> list:
    st = Path(env["CAP_LADDER_STATUS"])
    return [json.loads(l) for l in st.read_text().splitlines() if l.strip()] if st.exists() else []


def _founder_asks():
    import importlib.util
    spec = importlib.util.spec_from_file_location("fa_687", str(SCRIPTS / "founder_asks.py"))
    fa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fa)
    return fa


# Every live path and outside writer cap-ladder.py can reach. Kept HERE, apart
# from the script's own list, so a script that drops one from its guard goes red.
LIVE_VARS = ("CAP_LADDER_STATE", "CAP_LADDER_STATUS", "CAP_LADDER_REPORT", "CAP_LADDER_BLOCKERS",
             "CAP_LADDER_ATTEMPTS", "CAP_LADDER_LINEAR_LOG", "CAP_LADDER_GH", "CAP_LADDER_SYNC",
             "CAP_LADDER_FABLE", "CAP_LADDER_DRAFTER", "KIPI_LANES_DIR")


def case_review_687() -> None:
    """PR #687 review round 1 (ASK-4069), each finding pinned. Red on f5e58a54."""
    fa = _founder_asks()
    # major 1: a FOUNDER-DECISION with one sentence of reasoning past 300 chars.
    ask = ("spend: a paid seat on the vendor dashboard is required before this ticket can "
           "proceed, because the endpoint the Definition of Ready names is gated behind the paid tier "
           "and the free tier refuses it outright, so no attempt can verify the acceptance check "
           "without the seat, and three attempts have now failed for that single reason")
    line = f"DECISION: BLOCKED-ON FOUNDER-DECISION: {ask}\n"
    td, env = decision_world([RCA + line, RCA + line])
    out = ladder(env, "--apply")
    w = writes(env)
    rows = _status_rows(env)
    check("687 major 1: a 347-char FOUNDER-DECISION is accepted, never refused as free text",
          len(ask) > 301 and "free text" not in out and "refused" not in out, out)
    check("687 major 1: no sub-ticket is filed and the parent is not closed",
          not any(x["op"] in ("create", "state") for x in w), w)
    check("687 major 1: the whole ask reaches the status file and the hold is set",
          [r["ask"] for r in rows] == [ask] and ledger_row(env, "ASK-1").get("ladder_hold") is True, rows)
    td.cleanup()
    # The bound that remains: a runaway ask is clipped in storage, MARKED, and still
    # dedupes on its clipped text, so a re-cap never opens a second row.
    td, env = decision_world([RCA + "DECISION: BLOCKED-ON FOUNDER-DECISION: access: " + "x" * 3000 + "\n"])
    ladder(env, "--apply")
    rows = _status_rows(env)
    rendered, _ = fa.collect(None, {}, status=Path(env["CAP_LADDER_STATUS"]))
    out = ladder(env, "--founder-ask", "ASK-1", "founder-decision", "access: " + "x" * 3000)
    check("687 major 1: a runaway ask is held, clipped in storage, marked in the brief with its RCA, and dedupes",
          len(rows) == 1 and rows[0].get("clipped") is True and len(rows[0]["ask"]) < 3000
          and rendered and "[clipped" in rendered[0] and "rca-ASK-1" in rendered[0]
          and "already listed" in out and len(_status_rows(env)) == 1, (rows, rendered, out))
    td.cleanup()
    td, env = decision_world([RCA + "DECISION: BLOCKED-ON FOUNDER-DECISION: legal: sign the NDA\n",
                              RCA + "DECISION: SPLIT\nSUBTICKET: a :: b\n"])
    out = ladder(env, "--apply")
    check("687 major 1: a FOUNDER-DECISION of the wrong kind is refused by name, not as free text",
          "spend, access or outside" in out and "free text" not in out, out)
    td.cleanup()

    # major 2 (nonblocking): a held ticket closed in Linear takes its ask with it.
    for door in ("held loop", "caps loop"):
        td, env = decision_world([RCA + "DECISION: BLOCKED-ON FOUNDER-DECISION: spend: approve the 900 dollar plan\n"])
        ladder(env, "--apply")
        at(env, 4)
        edit_ticket(env, "ASK-1", state_type="canceled")
        if door == "caps loop":
            led(env, "record-capout", "ASK-1", "capped again, then canceled")
        ladder(env)                                                  # dry: writes nothing
        dry_open = [r for r in _status_rows(env) if not r["resolved"]]
        ladder(env, "--apply")
        rows = _status_rows(env)
        rendered = (fa.collect(None, {}, status=Path(env["CAP_LADDER_STATUS"])) or ([], None))[0]   # None is OFF: nothing open
        check(f"687 major 2 ({door}): a canceled held ticket's ask is resolved as moot, by the ladder, "
              "and the brief drops it; a dry run resolves nothing",
              len(dry_open) == 1 and len(rows) == 1 and rows[0]["resolved"] is True
              and "canceled" in rows[0].get("note", "") and "cap-ladder" in rows[0].get("resolved_by", "")
              and rendered == [], (dry_open, rows, rendered))
        td.cleanup()

    # Round 2 major (nonblocking): the third door. Event (b) releases a founder
    # hold with the ask still open (lifecycle 3 pins that), and the ticket then
    # closes. The held loop skipped the released row, so the ask outlived it.
    td, env = decision_world([RCA + "DECISION: BLOCKED-ON FOUNDER-DECISION: spend: approve the 900 dollar seat\n"])
    ladder(env, "--apply")
    at(env, 4)
    world(env, main_sha="m2", changed=["q-system/a.py"])
    released = "re-entered" in ladder(env, "--apply")
    world(env, changed=[])
    still_open = [r for r in _status_rows(env) if not r["resolved"]]
    edit_ticket(env, "ASK-1", state_type="completed")
    at(env, 5)
    ladder(env, "--apply")
    rows = _status_rows(env)
    rendered = (fa.collect(None, {}, status=Path(env["CAP_LADDER_STATUS"])) or ([], None))[0]   # None is OFF: nothing open
    check("687 round 2 major: a released founder hold keeps its ask while the ticket lives, "
          "and the ask is resolved as moot when the ticket closes",
          released and len(still_open) == 1 and len(rows) == 1 and rows[0]["resolved"] is True
          and "completed" in rows[0].get("note", "") and rendered == [], (released, still_open, rows, rendered))
    td.cleanup()
    # Round 3 major, and the class behind rounds 1 to 3 (RCA
    # rca-founder-ask-outlives-ticket-three-rounds-2026-11-09.md): a released row
    # re-caps, rung 5 answers SPLIT, the ladder closes the ticket itself, and the
    # new decision row carries no ask_id. And an ask the ladder never made
    # (--founder-ask, as #668 and #670 file them) whose ticket is canceled.
    td, env = decision_world([RCA + "DECISION: BLOCKED-ON FOUNDER-DECISION: spend: approve the 900 dollar seat\n",
                              RCA + "DECISION: SPLIT\nSUBTICKET: part one :: it works\n"])
    ladder(env, "--apply")
    at(env, 4)
    world(env, main_sha="m2", changed=["q-system/a.py"])
    ladder(env, "--apply")
    world(env, changed=[])
    at(env, 5)
    led(env, "record-capout", "ASK-1", "fifth cap")
    split = "SPLIT into" in ladder(env, "--apply")
    edit_ticket(env, "ASK-1", state_type="completed")
    ladder(env, "--founder-ask", "ASK-2", "founder-decision", "access: grant the vendor seat")
    edit_ticket(env, "ASK-2", state_type="canceled")
    at(env, 6)
    ladder(env, "--apply")
    rows = _status_rows(env)
    rendered = fa.collect(None, {}, status=Path(env["CAP_LADDER_STATUS"]))
    check("687 round 3 major: an ask dies with its ticket on every path: SPLIT after a release, "
          "and an ask the ladder never made",
          split and len(rows) == 2 and all(r["resolved"] for r in rows)
          and {r["issue"]: r.get("note", "") for r in rows} == {"ASK-1": "moot: ASK-1 is completed in Linear",
                                                                 "ASK-2": "moot: ASK-2 is canceled in Linear"}
          and rendered is None, (split, rows, rendered))
    td.cleanup()

    # Round 4 (approved with nits), each pinned.
    td, env = decision_world([RCA + "DECISION: BLOCKED-ON FOUNDER-DECISION: spend: approve the 900 dollar seat\n"])
    p = subprocess.run([sys.executable, str(LADDER), "--founder-ask", "ASK-3", "founder-decision", "spend: x"],
                       env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    check("687 round 4 major: --founder-ask on a closed ticket is refused (exit 1) and lists nothing",
          p.returncode == 1 and "completed" in p.stderr and not _status_rows(env), (p.returncode, p.stdout + p.stderr))
    ladder(env, "--apply")
    at(env, 4)
    world(env, main_sha="m2", changed=["q-system/a.py"])
    ladder(env, "--apply")                                       # released, ask open
    world(env, changed=[])
    edit_ticket(env, "ASK-1", state_type="completed")
    at(env, 5)
    out = ladder(env, "--apply")
    st = json.loads(Path(env["CAP_LADDER_STATE"]).read_text())
    check("687 round 4 minor: a released row whose ticket closed leaves the state file",
          "ASK-1" not in st, st)
    check("687 round 4 nit: the run summary counts the asks the sweep resolved",
          "1 ask resolved as moot" in out, out)
    td.cleanup()

    # Round 2 minor: a FOUNDER-DECISION that names its kind but no ask says THAT.
    td, env = decision_world([RCA + "DECISION: BLOCKED-ON FOUNDER-DECISION: spend:\n",
                              RCA + "DECISION: SPLIT\nSUBTICKET: a :: b\n"])
    out = ladder(env, "--apply")
    td.cleanup()
    td, env = decision_world([RCA + "DECISION: BLOCKED-ON FOUNDER-DECISION: spend approve the seat\n",
                              RCA + "DECISION: SPLIT\nSUBTICKET: a :: b\n"])
    out2 = ladder(env, "--apply")
    td.cleanup()
    td, env = decision_world([RCA + "DECISION: BLOCKED-ON FOUNDER-DECISION: outside reach: email the vendor\n",
                              RCA + "DECISION: SPLIT\nSUBTICKET: a :: b\n"])
    out3 = ladder(env, "--apply")
    td.cleanup()
    check("687 rounds 2 and 3 minor: an allowed kind in the wrong form is refused for its form, "
          "never as 'no allowed kind' or 'no ask'",
          all("not in the form" in o for o in (out, out2, out3))
          and "no allowed kind" not in out + out2 + out3 and "but no ask" not in out + out2 + out3, (out, out2, out3))

    # minor 3: an absent status file is the registry's OFF signal, not an empty section.
    with tempfile.TemporaryDirectory() as td:
        got = fa.collect(None, {}, status=Path(td) / "never-written.jsonl")
        (Path(td) / "all-resolved.jsonl").write_text(json.dumps({"id": "A:1", "resolved": True}) + "\n")
        got2 = fa.collect(None, {}, status=Path(td) / "all-resolved.jsonl")
    check("687 minor 3 and round 3 minor: no status file, or nothing open, returns None (OFF)",
          got is None and got2 is None, (got, got2))

    # minor 4: the pytest guard keys on EVERY live path, not on CAP_LADDER_STATE alone.
    for var in LIVE_VARS:
        for verb in (["--founder-ask", "ASK-7", "founder-decision", "spend: x"], ["--apply"]):
            with tempfile.TemporaryDirectory() as td:
                env = make_world(Path(td))
                env.pop(var)
                env["PYTEST_CURRENT_TEST"] = "x"
                p = subprocess.run([sys.executable, str(LADDER), *verb], env=env, capture_output=True,
                                   text=True, timeout=60, stdin=subprocess.DEVNULL)
                touched = [str(x) for x in (Path(td) / ".local", Path(td) / ".config") if x.exists()]
                check(f"687 minor 4: under pytest with {var} unset, {verb[0]} is refused and writes no default path",
                      p.returncode == 4 and var in p.stderr and not touched and not log(env, "gh"),
                      (p.returncode, p.stdout + p.stderr, touched))
    with tempfile.TemporaryDirectory() as td:
        env = make_world(Path(td))
        env["PYTEST_CURRENT_TEST"] = "x"
        p = subprocess.run([sys.executable, str(LADDER), "--founder-ask", "ASK-7", "founder-decision", "spend: x"],
                           env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        check("687 minor 4: with every live path redirected the guard lets the run through (it can pass)",
              p.returncode == 0 and "ask added" in p.stdout, p.stdout + p.stderr)

    # minor 5: --resolve records who answered, and the process context it ran in.
    with tempfile.TemporaryDirectory() as td:
        env = make_world(Path(td))
        env.pop("CLAUDECODE", None)
        ladder(env, "--founder-ask", "ASK-1", "founder-decision", "spend: one")
        ladder(env, "--founder-ask", "ASK-2", "founder-decision", "spend: two")
        p1 = subprocess.run([sys.executable, str(LADDER), "--resolve", "ASK-1", "--by", "founder"], env=env,
                            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        p2 = subprocess.run([sys.executable, str(LADDER), "--resolve", "ASK-2"], env=dict(env, CLAUDECODE="1"),
                            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        by = {r["issue"]: r for r in _status_rows(env)}
        a, b = by.get("ASK-1", {}), by.get("ASK-2", {})
        check("687 minor 5: --resolve records --by and the context; an agent session is marked, a plain one is not",
              p1.returncode == 0 and p2.returncode == 0
              and a.get("resolved_by") == "founder" and (a.get("resolved_ctx") or {}).get("agent_env") == []
              and (a.get("resolved_ctx") or {}).get("tty") is False
              and b.get("resolved_by") == "unnamed" and "CLAUDECODE" in (b.get("resolved_ctx") or {}).get("agent_env", []),
              (a, b))


def case_owns() -> None:
    """ladder_owns() is the one rule pr-owner.py asks (ASK-3962), so it is pinned here."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("cl", str(LADDER))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "pr-reviews" / "codex").mkdir(parents=True)
        (Path(td) / "linear-worker-attempts.json").write_text(json.dumps({
            "ASK-1": {"capout": True}, "ASK-2": {"review_escalated_rework_pr7_abc": True},
            "ASK-5": {"ladder_hold": True}, "ASK-6": {"count": 1}}))
        (Path(td) / "pr-reviews" / "codex" / ".round-cap-o_r-pr-9").write_text("")
        got = {
            "capout": m.ladder_owns("o/r", 3, "sana/ask-1", td),
            "escalated on this PR": m.ladder_owns("o/r", 7, "sana/ask-2", td),
            "escalated on another PR": m.ladder_owns("o/r", 8, "sana/ask-2", td),
            "review cap (codex engine)": m.ladder_owns("o/r", 9, "sana/ask-7", td),
            "held": m.ladder_owns("o/r", 4, "sana/ask-5", td),
            "uncapped": m.ladder_owns("o/r", 5, "sana/ask-6", td),
            "lane branch": m.ladder_owns("o/r", 3, "sana/ask-1-slug", td),
            "human branch": m.ladder_owns("o/r", 3, "fix/thing", td),
        }
    want_owned = {"capout", "escalated on this PR", "review cap (codex engine)", "held"}
    check("ladder_owns: owned exactly when a cap record or hold names this PR, never a lane or human branch",
          {k for k, v in got.items() if v} == want_owned and all(v.startswith("cap-ladder owns it") for k, v in got.items() if v),
          got)


def lane(env: dict, issue: str, until: str, agent: str = "sana-lane1") -> None:
    """A lane-mark.py marker, in the shape lane-mark.py start writes."""
    d = Path(env["KIPI_LANES_DIR"])
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{issue}.json").write_text(json.dumps(
        {"issue": issue, "agent": agent, "since": "2026-11-08T20:00:00Z", "pr": "10", "until": until}, indent=1))


def lane_world(td: str) -> dict:
    env = make_world(Path(td))
    env["KIPI_LANES_DIR"] = str(Path(td) / "lanes")
    led(env, "record-capout", "ASK-1", "hit the 3-round cap on PR #10")
    return env


def expired_lane_climbs(script: Path) -> bool:
    """An EXPIRED marker on a capped issue: rung 1 runs exactly as with no marker."""
    with tempfile.TemporaryDirectory() as td:
        if script != LADDER:
            shutil.copy(LEDGER, script.parent / "attempts-ledger.py")
            shutil.copy(SCRIPTS / "linear-sync.py", script.parent / "linear-sync.py")
        env = lane_world(td)
        lane(env, "ASK-1", "2026-11-09T04:00:00Z")          # 40 minutes before CAP_LADDER_NOW
        out = ladder(env, "--apply", script=script)
        gh, st = log(env, "gh"), json.loads(Path(env["CAP_LADDER_STATE"]).read_text())
        return (any(c[:3] == ["pr", "close", "10"] for c in gh)
                and any(c[:2] == ["pr", "create"] and "sana/ask-1" in c for c in gh)
                and any(c[:2] == ["requeue", "ASK-1"] for c in log(env, "sync"))
                and not ledger_row(env, "ASK-1").get("capout")
                and (st.get("ASK-1") or {}).get("rung") == 1 and "lane marker" not in out)


def case_lane_marker() -> None:
    # ASK-4395. 2026-11-10 12:40Z: ASK-4311 was capped and queued for rung 1, which
    # closes the PR on sana/<id>, opens a successor and requeues the ticket. Lane A
    # (sana-ask4311) held a live marker and was merging that PR (#717) with
    # --match-head-commit, so rung 1 would have broken the merge and stranded its
    # review history on a closed PR. The worker, the WIP release and ci-redrive read
    # the marker; the ladder did not.
    with tempfile.TemporaryDirectory() as td:
        env = lane_world(td)
        lane(env, "ASK-1", "2026-11-10T04:40:00Z")          # live: a day past CAP_LADDER_NOW
        for _ in range(3):
            led(env, "bump-attempt", "ASK-2", "no PR opened")
        dry = ladder(env, "--limit", "1")
        check("lane, dry: a live marker shows as the lane line, not as a planned rung",
              "sana-lane1" in dry and "[dry] ASK-1: would take rung" not in dry, dry)
        out = ladder(env, "--apply", "--limit", "1")
        gh, sync = log(env, "gh"), log(env, "sync")
        st = json.loads(Path(env["CAP_LADDER_STATE"]).read_text())
        w = json.loads((Path(td) / "gh-world.json").read_text())
        check("lane, live marker: the lane's PR is not closed and no successor opens",
              not any(c[:2] == ["pr", "close"] for c in gh)
              and not any(c[:2] == ["pr", "create"] and "sana/ask-1" in c for c in gh)
              and any(p["number"] == 10 and p["state"] == "OPEN" for p in w["o/r"]), gh)
        check("lane, live marker: no requeue, no comment, no RCA, the cap record is kept",
              not any("ASK-1" in c for c in sync) and not any("ASK-1" in c for c in log(env, "fable"))
              and ledger_row(env, "ASK-1").get("capout") is True, (sync, ledger_row(env, "ASK-1")))
        check("lane, live marker: the rung is not spent",
              (st.get("ASK-1") or {}).get("rung", 0) == 0 and not (st.get("ASK-1") or {}).get("handled"), st)
        lines = [l for l in out.splitlines() if "ASK-1" in l and "sana-lane1" in l]
        check("lane, live marker: exactly one log line, naming the lane agent and the marker's until",
              len(lines) == 1 and "2026-11-10T04:40:00Z" in lines[0], out)
        check("lane, live marker: a skipped issue does not use the run's limit (ASK-2 climbs at --limit 1)",
              any(c[:2] == ["requeue", "ASK-2"] for c in sync), out)

    check("lane, expired marker: rung 1 closes, reopens, clears, requeues and is spent, as with no marker",
          expired_lane_climbs(LADDER))
    # NEGATIVE SELF-TEST: a ladder that skips on the marker FILE, ignoring its
    # until, must turn the expired case red, or the case above proves nothing.
    with tempfile.TemporaryDirectory() as td:
        mut = Path(td) / "cap-ladder.py"
        src = LADDER.read_text()
        anchor = "return _sync().lane_marker(issue, now=now())"
        mut.write_text(src.replace(anchor, 'return "lane marker file" if (Path(os.environ["KIPI_LANES_DIR"]) '
                                           '/ (issue + ".json")).exists() else ""', 1))
        check("lane mutant: the file-exists copy really differs from the ladder", anchor in src and mut.read_text() != src)
        check("lane mutant: a ladder that ignores the marker's until turns the expired case red",
              expired_lane_climbs(mut) is False)

    # PR #732 round 1, major: the marker was read once, then climb() spent up to
    # 600s in Fable before closing the PR. A lane started in that window lost it.
    with tempfile.TemporaryDirectory() as td:
        env = lane_world(td)
        Path(env["KIPI_LANES_DIR"]).mkdir()
        env["FAKE_FABLE_LANE"] = json.dumps({"path": str(Path(td) / "lanes/ASK-1.json"), "marker": {
            "issue": "ASK-1", "agent": "sana-late", "until": "2026-11-10T04:40:00Z"}})
        out = ladder(env, "--apply")
        gh, st = log(env, "gh"), json.loads(Path(env["CAP_LADDER_STATE"]).read_text())
        check("lane, marker lands mid-RCA (rung 1): the PR is not closed, nothing opens or requeues, rung unspent",
              log(env, "fable") and not any(c[:2] in (["pr", "close"], ["pr", "create"]) for c in gh)
              and not any(c[:2] == ["requeue", "ASK-1"] for c in log(env, "sync"))
              and ledger_row(env, "ASK-1").get("capout") is True and not (st.get("ASK-1") or {}).get("rung")
              and "sana-late" in out, (out, gh))
    td, env = decision_world([RCA + "DECISION: SPLIT\nSUBTICKET: a :: b\n"])
    try:
        env["KIPI_LANES_DIR"] = str(Path(td.name) / "lanes")
        Path(env["KIPI_LANES_DIR"]).mkdir()
        env["FAKE_FABLE_LANE"] = json.dumps({"path": str(Path(td.name) / "lanes/ASK-1.json"), "marker": {
            "issue": "ASK-1", "agent": "sana-late", "until": "2026-11-14T04:40:00Z"}})
        out = ladder(env, "--apply")
        st = json.loads(Path(env["CAP_LADDER_STATE"]).read_text())
        check("lane, marker lands mid-decision (rung 4): no sub-tickets, no state change, rung unspent",
              log(env, "fable") and not writes(env) and not log(env, "sync")
              and (st.get("ASK-1") or {}).get("rung") == 3 and "sana-late" in out, (out, writes(env)))
    finally:
        td.cleanup()

    # A held ticket's re-entry opens a PR and requeues too: same rule.
    td, env = decision_world([RCA + "DECISION: BLOCKED-ON ASK-50\n"])
    try:
        env["KIPI_LANES_DIR"] = str(Path(td.name) / "lanes")
        ladder(env, "--apply")
        reset(env)
        at(env, 4)
        edit_ticket(env, "ASK-50", state_type="completed")
        lane(env, "ASK-1", "2026-11-14T04:40:00Z")          # live through day 4, expired by day 6
        out = ladder(env, "--apply")
        check("lane, held ticket: its event does not re-enter it while a lane holds it",
              not any(c[:2] == ["requeue", "ASK-1"] for c in log(env, "sync"))
              and not any(c[:2] == ["pr", "create"] for c in log(env, "gh"))
              and ledger_row(env, "ASK-1").get("ladder_hold") is True and "sana-lane1" in out, out)
        at(env, 6)
        out = ladder(env, "--apply")
        check("lane, held ticket: once the marker expires the same event re-enters it",
              any(c[:2] == ["requeue", "ASK-1"] for c in log(env, "sync")) and "re-entered" in out, out)
    finally:
        td.cleanup()


def held_stays_quiet(script: Path) -> bool:
    """A BLOCKED-ON ticket with nothing changed, 7 days later: quiet or not."""
    td, env = decision_world([RCA + "DECISION: BLOCKED-ON ASK-50\n"])
    try:
        if script != LADDER:
            # The ladder loads linear-sync.py from its own dir for the lane rule (ASK-4395).
            shutil.copy(LEDGER, script.parent / "attempts-ledger.py")
            shutil.copy(SCRIPTS / "linear-sync.py", script.parent / "linear-sync.py")
        ladder(env, "--apply", script=script)
        reset(env)
        at(env, 10)
        ladder(env, "--apply", script=script)
        return not log(env, "sync")
    finally:
        td.cleanup()


def case_mutant() -> None:
    with tempfile.TemporaryDirectory() as td:
        mut = Path(td) / "cap-ladder.py"
        src = LADDER.read_text()
        mut.write_text(src.replace('(["clear-capout", issue], ', '(', 1))
        check("mutant: the copy really differs from the ladder", mut.read_text() != src)
        shutil.copy(LEDGER, Path(td) / "attempts-ledger.py")
        shutil.copy(SCRIPTS / "linear-sync.py", Path(td) / "linear-sync.py")   # the lane rule, ASK-4395
        check("mutant: a ladder that skips clear-capout turns rung 1 red", case_rungs(script=mut) is False)
    with tempfile.TemporaryDirectory() as td:
        mut = Path(td) / "cap-ladder.py"
        src = LADDER.read_text()
        anchor = '        return "(d) the worker\'s model config changed"\n    return ""'
        mut.write_text(src.replace(anchor, anchor[:-len('return ""')] + 'return "(t) seven days passed"', 1))
        check("mutant 2: the time-based copy really differs", mut.read_text() != src)
        check("mutant 2: a ladder that re-enters by age turns the no-timed-retry case red",
              held_stays_quiet(LADDER) is True and held_stays_quiet(mut) is False)


# Runtime bound (ASK-4264). The file spawns about 400 child pythons (171 of them
# cap-ladder.py --apply, each with its own fake gh/sync/fable), one after the
# other. It outgrew the gate's 60 s default (72 s serial on a laptop; CI timed
# out), and #703 gave it timeout_s 180 in its manifest entry. Every case builds
# its own temp world and shares nothing, so the cases now run in threads: 29 to
# 44 s cold-to-warm on an idle 10-core laptop. Wall time now tracks the longest
# single case, so this bound does NOT see suite growth; it only guards against
# the threading being lost (serial is 72 s+). It sits at 120 s so normal CI
# variance cannot trip it and it stays under the manifest's 180 s ceiling, which
# is the real limit. CAP_LADDER_RUNTIME_BOUND_S shows the red side.
RUNTIME_BOUND_S = float(os.environ.get("CAP_LADDER_RUNTIME_BOUND_S", "120"))


def main() -> int:
    t0 = time.monotonic()
    print("test_cap_ladder.py")
    cases = [case_worker, case_sites]
    if not LADDER.exists():
        check("cap-ladder.py exists", False, f"no {LADDER}: every cap still ends in a page and a park")
    else:
        cases = [case_rungs, case_decisions, case_events, case_edges, case_owns, case_review_fixes,
                 case_review_round2, case_ask_lifecycle, case_pytest_refusal, case_review_687,
                 case_mutant, case_lane_marker] + cases
    # list() re-raises any exception a case threw, so a crash still fails the file.
    with ThreadPoolExecutor(max_workers=len(cases)) as pool:
        list(pool.map(lambda f: f(), cases))
    took = time.monotonic() - t0
    check(f"runtime: whole file in {took:.0f}s, bound {RUNTIME_BOUND_S:.0f}s", took <= RUNTIME_BOUND_S)
    print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
