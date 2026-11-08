#!/usr/bin/env python3
"""test_cap_ladder.py: every cap moves on, and none of them ends (ASK-3824).

Drives cap-ladder.py against a fixture world: a real attempts ledger in a temp
dir (written only through attempts-ledger.py, as in production), and fakes for
gh, linear-sync.py, fable-escalate.py, the DoR drafter and the process table.
No live path is touched: every seam is set, and the script refuses to run under
pytest without CAP_LADDER_STATE.

RED ON MAIN, and that is the point: on main cap-ladder.py does not exist, the
cap sites still say "needs a human decision" and "until you clear it", and the
worker never reads a runner flag. Point CAP_LADDER_TEST_ROOT at a main tree's
scripts dir to see it red.

The mutant at the end proves the main assertion can fail: a copy of the ladder
with its clear-capout step removed must turn case A red.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(os.environ.get("CAP_LADDER_TEST_ROOT") or Path(__file__).resolve().parent.parent)
LADDER = SCRIPTS / "cap-ladder.py"
LEDGER = SCRIPTS / "attempts-ledger.py"
FAILS: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else f"\n       {detail}"))
    if not ok:
        FAILS.append(name)


FAKE_GH = r'''#!/usr/bin/env python3
import json, sys, os
world = os.environ["W"] + "/gh-world.json"
open(os.environ["W"] + "/gh.log", "a").write(json.dumps(sys.argv[1:]) + "\n")
w = json.load(open(world))
a = sys.argv[1:]
slug = a[a.index("-R") + 1] if "-R" in a else ""
if a[:2] == ["pr", "list"]:
    print(json.dumps([p for p in w.get(slug, []) if p["state"] == "OPEN"]))
elif a[:2] == ["pr", "close"]:
    for p in w.get(slug, []):
        if str(p["number"]) == a[2]:
            p["state"] = "CLOSED"
    json.dump(w, open(world, "w"))
elif a[:1] == ["api"]:
    m = a[1].split("compare/main...", 1)
    ahead = w.get("branches", {}).get(m[1]) if len(m) == 2 else None
    if ahead is None:
        sys.exit(1)
    print(ahead)
elif a[:2] == ["pr", "create"]:
    if w.get("create_fails"):
        sys.exit(1)
    head = a[a.index("--head") + 1]
    prs = w.setdefault(slug, [])
    n = max([p["number"] for p in prs] + [0]) + 1
    prs.append({"number": n, "headRefName": head, "headRefOid": "b" * 40, "title": "t",
                "baseRefName": "main", "url": "u/%d" % n, "state": "OPEN"})
    json.dump(w, open(world, "w"))
    print("https://github.com/%s/pull/%d" % (slug, n))
'''

FAKE_LOG = r'''#!/usr/bin/env python3
import json, sys, os
open(os.environ["W"] + "/%s.log", "a").write(json.dumps(sys.argv[1:]) + "\n")
%s
'''


def make_world(tmp: Path) -> dict:
    (tmp / "bin").mkdir()
    (tmp / "reviews").mkdir()
    (tmp / "bin/gh").write_text(FAKE_GH)
    (tmp / "bin/sync").write_text(FAKE_LOG % ("sync", ""))
    (tmp / "bin/fable").write_text(FAKE_LOG % ("fable", 'print(json.dumps({"rca_path": os.environ["W"] + "/rca.md"}))'))
    (tmp / "bin/drafter").write_text(FAKE_LOG % ("drafter", ""))
    (tmp / "bin/ps").write_text("#!/bin/sh\ncat \"$W/ps.txt\" 2>/dev/null\nexit 0\n")
    for f in (tmp / "bin").iterdir():
        f.chmod(0o755)
    (tmp / "gh-world.json").write_text(json.dumps({"o/r": [
        {"number": 10, "headRefName": "sana/ask-1", "headRefOid": "a" * 40, "title": "fix (ASK-1)",
         "baseRefName": "main", "url": "u/10", "state": "OPEN"}]}))
    (tmp / "linear.json").write_text(json.dumps({
        "ASK-1": {"state_type": "started", "labels": ["owner:sana"], "project": "kipi-system", "title": "t"},
        "ASK-2": {"state_type": "backlog", "labels": ["owner:sana"], "project": "kipi-system", "title": "t"},
        "ASK-3": {"state_type": "completed", "labels": ["owner:sana"], "project": "kipi-system", "title": "t"},
        "ASK-4": {"state_type": "backlog", "labels": ["owner:sana"], "project": "elsewhere", "title": "t"},
    }))
    (tmp / "attempts.json").write_text("{}")
    py = sys.executable
    return {
        "W": str(tmp), "PATH": os.environ.get("PATH", ""), "HOME": str(tmp),
        "CAP_LADDER_STATE": str(tmp / "state/state.json"),
        "CAP_LADDER_ATTEMPTS": str(tmp / "attempts.json"),
        "CAP_LADDER_REVIEWS": str(tmp / "reviews"),
        "CAP_LADDER_GH": f"{py} {tmp}/bin/gh",
        "CAP_LADDER_SYNC": f"{py} {tmp}/bin/sync",
        "CAP_LADDER_FABLE": f"{py} {tmp}/bin/fable",
        "CAP_LADDER_DRAFTER": f"{py} {tmp}/bin/drafter",
        "CAP_LADDER_PS": f"{tmp}/bin/ps",
        "CAP_LADDER_LINEAR_FIXTURE": str(tmp / "linear.json"),
        "CAP_LADDER_TARGETS": json.dumps([{"slug": "o/r", "project": "kipi-system"}]),
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


def reset_logs(env: dict) -> None:
    for name in ("gh", "sync", "fable", "drafter"):
        (Path(env["W"]) / f"{name}.log").unlink(missing_ok=True)


def case_a_to_e(script: Path = LADDER) -> bool:
    """The whole ladder on one ticket. Returns whether case A's clear held."""
    with tempfile.TemporaryDirectory() as td:
        env = make_world(Path(td))
        led(env, "record-capout", "ASK-1", "hit the 3-round cap still at 'REQUEST CHANGES' on PR #10")
        out = ladder(env, "--apply", script=script)
        gh = log(env, "gh")
        a_clear = not ledger_row(env, "ASK-1").get("capout")
        if script != LADDER:
            return a_clear
        check("A: the capped PR is closed, branch kept (no --delete-branch)",
              any(c[:3] == ["pr", "close", "10"] for c in gh) and not any("--delete-branch" in c for c in gh), str(gh))
        check("A: a new PR opens on the same branch",
              any(c[:2] == ["pr", "create"] and "sana/ask-1" in c for c in gh), str(gh))
        check("A: the capout record is cleared, so the redrives re-enter it", a_clear, str(ledger_row(env, "ASK-1")))
        check("A: Fable writes an RCA (--kind rca) before the work continues",
              any(c[:2] == ["--kind", "rca"] for c in log(env, "fable")), str(log(env, "fable")))
        sync = log(env, "sync")
        check("A: the ticket is requeued and the comment names the next rung",
              any(c[:2] == ["requeue", "ASK-1"] for c in sync)
              and any(c[0] == "progress" and "rung 1" in c[2] and "rung 2" in c[2] for c in sync), str(sync))
        check("A: rung 1 runs the default runner", not ledger_row(env, "ASK-1").get("ladder_runner_codex"))

        reset_logs(env)
        ladder(env, "--apply")
        check("B: a second run with no new cap writes nothing", not log(env, "gh")[1:] and not log(env, "sync"),
              str(log(env, "sync")))

        reset_logs(env)
        env["CAP_LADDER_NOW"] = "2026-11-10T04:40:00+00:00"
        led(env, "record-capout", "ASK-1", "capped again on the new PR")
        ladder(env, "--apply")
        check("C: the second cap takes rung 2 and asks the worker for the other runner",
              ledger_row(env, "ASK-1").get("ladder_runner_codex") is True
              and any(c[0] == "progress" and "Codex" in c[2] for c in log(env, "sync")), str(ledger_row(env, "ASK-1")))

        reset_logs(env)
        env["CAP_LADDER_NOW"] = "2026-11-11T04:40:00+00:00"
        led(env, "record-capout", "ASK-1", "capped a third time")
        ladder(env, "--apply")
        sync = log(env, "sync")
        check("D: the third cap re-scopes: needs-scope goes on and the drafter rewrites this one issue",
              ["label", "ASK-1", "needs-scope"] in sync
              and any("--issue" in c and "ASK-1" in c for c in log(env, "drafter")), str(sync))
        check("D: rung 3 goes back to the default runner", not ledger_row(env, "ASK-1").get("ladder_runner_codex"))

        reset_logs(env)
        env["CAP_LADDER_NOW"] = "2026-11-12T04:40:00+00:00"
        led(env, "record-capout", "ASK-1", "capped a fourth time")
        out = ladder(env, "--apply")
        check("E: the fourth cap waits out its 7-day cooldown and says when",
              not log(env, "sync") and "2026-11-18" in out, out)
        env["CAP_LADDER_NOW"] = "2026-11-19T04:40:00+00:00"
        ladder(env, "--apply")
        st = json.loads(Path(env["CAP_LADDER_STATE"]).read_text())["ASK-1"]
        check("E: after the cooldown it re-enters at rung 4, counter kept, never terminal",
              st["rung"] == 4 and any(c[:2] == ["requeue", "ASK-1"] for c in log(env, "sync")), str(st))
        return a_clear


def case_f_to_k() -> None:
    with tempfile.TemporaryDirectory() as td:
        env = make_world(Path(td))
        for _ in range(3):
            led(env, "bump-attempt", "ASK-2", "no PR opened")
        led(env, "record-capout", "ASK-3", "closed ticket")
        for _ in range(3):
            led(env, "bump-attempt", "ASK-4", "no PR opened")
        out = ladder(env)
        check("K: without --apply nothing is written", not log(env, "sync") and not log(env, "fable") and "[dry]" in out, out)
        ladder(env, "--apply")
        check("F: attempts spent with no PR: count cleared and requeued, no PR opened",
              "count" not in ledger_row(env, "ASK-2")
              and any(c[:2] == ["requeue", "ASK-2"] for c in log(env, "sync"))
              and not any(c[:2] == ["pr", "create"] and "sana/ask-2" in c for c in log(env, "gh")))
        check("H: a closed ticket is left alone", not any("ASK-3" in c for c in log(env, "sync")))
        out = ladder(env, "--apply")
        check("J: a ticket with no dispatch target names the router tickets, writes nothing",
              not any("ASK-4" in c for c in log(env, "sync")) and "ASK-3959" in out, out)

    with tempfile.TemporaryDirectory() as td:
        env = make_world(Path(td))
        w = json.loads((Path(td) / "gh-world.json").read_text())
        w["branches"] = {"sana/ask-2": 2}
        (Path(td) / "gh-world.json").write_text(json.dumps(w))
        for _ in range(3):
            led(env, "bump-attempt", "ASK-2", "no PR opened")
        ladder(env, "--apply")
        check("F2: no open PR but the branch holds commits: a PR opens from it, so the worker resumes there",
              any(c[:2] == ["pr", "create"] and "sana/ask-2" in c for c in log(env, "gh")), str(log(env, "gh")))

    with tempfile.TemporaryDirectory() as td:
        env = make_world(Path(td))
        w = json.loads((Path(td) / "gh-world.json").read_text())
        w["create_fails"] = True
        (Path(td) / "gh-world.json").write_text(json.dumps(w))
        led(env, "record-capout", "ASK-1", "x")
        out = ladder(env, "--apply")
        check("F3: a new PR that cannot open keeps the cap record, so the next run retries",
              ledger_row(env, "ASK-1").get("capout") is True and "retries" in out
              and not any(c[:2] == ["requeue", "ASK-1"] for c in log(env, "sync")), out)

    with tempfile.TemporaryDirectory() as td:
        env = make_world(Path(td))
        (Path(td) / "reviews" / ".round-cap-o_r-pr-10").write_text("")
        ladder(env, "--apply")
        check("G: a review-capped open PR moves to a new PR",
              any(c[:2] == ["pr", "create"] for c in log(env, "gh")), str(log(env, "gh")))

    with tempfile.TemporaryDirectory() as td:
        env = make_world(Path(td))
        led(env, "record-capout", "ASK-1", "x")
        (Path(td) / "ps.txt").write_text("bash converge.sh --issue ASK-1 --max-rounds 4\n")
        ladder(env, "--apply")
        check("I: a live converge on the issue holds the ladder off", not log(env, "sync"))


def case_sites() -> None:
    """The cap sites hand off to the ladder; none asks a person, none pages."""
    def code(path: Path) -> str:
        return "\n".join(l for l in path.read_text().splitlines() if not l.lstrip().startswith("#"))
    worker = code(SCRIPTS / "linear-worker.sh")
    for phrase in ("Human action needed", "stuck after $MAX_ATTEMPTS attempts - needs a human",
                   "a human resolves this one.\"\n        if page_once \"$ISSUE\" conflict_paged"):
        check(f"site: linear-worker.sh no longer says {phrase[:40]!r}", phrase not in worker)
    check("site: converge.sh no longer parks 'until you clear it'",
          "until you clear it" not in code(SCRIPTS / "converge.sh"))
    check("site: pr-review-agent.sh no longer asks for 'a human decision' or files the cap ticket",
          "needs a human decision" not in code(SCRIPTS / "pr-review-agent.sh")
          and "decide merge, rework or close" not in code(SCRIPTS / "pr-review-agent.sh"))
    check("site: ci-redrive.py no longer waits 'until a human clears'",
          "until a human clears" not in (SCRIPTS / "ci-redrive.py").read_text())
    for f in ("linear-worker.sh", "converge.sh", "pr-review-agent.sh", "ci-redrive.py", "review-redrive.py"):
        check(f"site: {f} names cap-ladder.py as the next step", "cap-ladder.py" in (SCRIPTS / f).read_text())
    m = re.search(r"^ladder_runner_for\(\) \{.*?^\}", (SCRIPTS / "linear-worker.sh").read_text(), re.S | re.M)
    check("worker: ladder_runner_for exists and the launch uses PRIMARY_CMD",
          bool(m) and "$PRIMARY_CMD </dev/null" in worker)
    if m:
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "a.json"
            ledger.write_text(json.dumps({"ASK-9": {"ladder_runner_codex": True}}))
            sh = f'LEDGER="{LEDGER}"; ATTEMPTS="{ledger}"\n{m.group(0)}\n' \
                 'printf "[%s][%s]" "$(ladder_runner_for ASK-9)" "$(ladder_runner_for ASK-8)"'
            got = subprocess.run(["bash", "-c", sh], capture_output=True, text=True).stdout
            check("worker: the flag set means codex, the flag unset means the default runner",
                  got == "[codex][]", got)


def case_mutant() -> None:
    if not LADDER.exists():
        return
    with tempfile.TemporaryDirectory() as td:
        mut = Path(td) / "cap-ladder.py"
        src = LADDER.read_text()
        mut.write_text(src.replace('(["clear-capout", issue], ', '(', 1))
        check("mutant: the copy really differs from the ladder", mut.read_text() != src)
        shutil.copy(LEDGER, Path(td) / "attempts-ledger.py")
        check("mutant: a ladder that skips clear-capout turns case A red", case_a_to_e(script=mut) is False)


def main() -> int:
    print("test_cap_ladder.py")
    if not LADDER.exists():
        check("cap-ladder.py exists", False, f"no {LADDER}: every cap still ends in a page and a park")
    else:
        case_a_to_e()
        case_f_to_k()
        case_mutant()
    case_sites()
    print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
