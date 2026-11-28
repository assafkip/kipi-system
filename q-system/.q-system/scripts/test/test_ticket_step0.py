#!/usr/bin/env python3
"""ticket_step0.py, the one should-exist decision (ASK-5802).

Fixtures come from the producer: the named-file case is improve_ground's own
("risk-scored auto-merge" -> review-tier.py), and the lesson case reuses the
three-lesson corpus from test_improve_ground.py::test_a_covered_idea_cites_the_lesson_path.
Corpora are tmp dirs through KIPI_LESSONS_CORPORA, never the live lessons dir.

Run: python3 q-system/.q-system/scripts/test/test_ticket_step0.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEP0 = Path(os.environ.get("KIPI_STEP0_UNDER_TEST") or HERE.parent / "ticket_step0.py")
FAILS: list = []


def check(name: str, ok: bool, detail="") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    if not ok:
        FAILS.append(name)
        print(f"       {str(detail)[:400]}")


def corpus(root: Path, lessons: dict) -> Path:
    d = root / "corpus"
    d.mkdir(exist_ok=True)
    for slug, (title, body) in lessons.items():
        (d / f"{slug}.md").write_text(f"---\nid: {slug}\nkind: pattern\ntitle: {title}\ndate: 2026-09-01\n---\n\n{body}\n")
    return d


LESSONS = {
    "every-stage-needs-its-own-trigger": (
        "Every stage needs its own trigger",
        "a stage with no registered trigger is dead; list triggers, list stages, diff the two lists; launchd plist scheduler"),
    "a-scheduled-job-runs-in-a-bare-environment": (
        "A scheduled job runs in a bare environment",
        "a launchd plist trigger starts a job with no shell profile; test the stages under a stripped environment"),
    "verify-the-copy-the-reader-actually-reads": (
        "Verify the copy the reader actually reads",
        "the running system may load a different clone; grep the loaded copy, marketplace cache, plugin version"),
}


def step0(text: str, **env) -> tuple[int, dict]:
    p = subprocess.run([sys.executable, str(STEP0), "--issue", "ASK-1"], input=text, capture_output=True,
                       text=True, env=dict(os.environ, **env), timeout=60)
    try:
        return p.returncode, json.loads(p.stdout)
    except ValueError:
        return p.returncode, {"raw": p.stdout + p.stderr}


def main() -> int:
    print(f"test_ticket_step0.py (under test: {STEP0})")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        empty = root / "empty"
        empty.mkdir()
        full = corpus(root, LESSONS)

        # WHAT STOPS: a title that proposes building the cited file itself. The
        # stop is a label, never a cancel (rca-ask5802-five-rounds-step0-cancel-
        # 2026-11-27.md); the key-in-title rule labelled 24 real tickets on the
        # board, so the object of the build verb must be the file.
        for title, why in (
                ("Build review-tier.py for risk-scored auto-merge\n\nbuild it", "build + the file"),
                ("add a review-tier script for risk-scored auto-merge", "add + article + the stem"),
                ("Create the new REVIEW-TIER.PY gate for risk-scored auto-merge", "any case, two articles")):
            rc, out = step0(title, KIPI_LESSONS_CORPORA=str(empty))
            check(f"a stop (exit 3) names the file: {why}",
                  rc == 3 and out.get("decision") == "stop" and out.get("checked") is True
                  and "q-system/.q-system/scripts/review-tier.py" in out.get("cites", [])
                  and "review-tier.py" in out.get("comment", "")
                  and "step0:already-built" in out.get("comment", "")
                  and "Nothing is canceled" in out.get("comment", ""), (rc, out))
        for title, why in (
                # The titles PR #903 round 5 named: all were labelled by the key rule.
                ("launchd job is dark: com.kipi.browser-session-deadman", "a broken-thing report (ASK-1199)"),
                ("handoff-provenance-lint: widen the scan root to session handoffs and auto-memory", "ASK-1953"),
                ("session handoff for the fleet-wide Linear rollout", "key in the title, no build of the file"),
                ("Add a deadman to the cap-ladder nightly run", "adds a part TO another thing"),
                ("Make the morning brief read the ledger instead of the log", "make = change"),
                ("Add a friction note capture to the lane runner", "adds a part TO another thing"),
                ("Add a self-review pass to pr-owner.py", "adds a part TO another thing"),
                ("Make a handoff's \"every branch is pushed\" claim come from the disk, not a static list "
                 "of branches.", "verbatim RCA action item"),
                ("Add friction counts on the morning brief", "key in the title, file not built"),
                ("Add a deadman for the pr-review-agent queue", "key in the title, file not built"),
                ("Build a morning brief section for consulting", "build verb + key, the object is a section"),
                ("Add a friction note capture on the lane runner", "'on' for 'to'"),
                ("Create a handoff index page", "the object is a page"),
                ("add risk-scored auto-merge for low-risk PRs", "the old known-answer case: no file named"),
                # PR #910 round 1, major 1: a title that CHANGES the cited file.
                ("Make review-tier.py skip draft PRs when self-review is on", "make X.py do Y"),
                ("Add review-tier.py coverage for the auto merge path", "add X.py coverage"),
                ("Add friction-note.sh to the lane runner so a note is captured", "add X.py to Y"),
                ("Write morning-brief.py output to the state card as well as the morning brief log",
                 "write X.py output to Y"),
                ("Make friction-note.sh retry when the repo is mid-rebase (friction)", "make X.sh retry"),
                ("Add capability_manifest.py rows for the four CRM jobs to the capability manifest",
                 "add X.py rows"),
                # Round 4's titles, keyed to the cited file.
                ("friction-note.sh drops the note when the repo is mid-rebase", "a bug in the cited file"),
                ("review-tier.py: widen the self-review tier to lane PRs", "a change to the cited file"),
                ("Add a self-review pass to review-tier.py", "add Y TO the cited file"),
                ("Fix review-tier.py mislabelling a 2000-line PR", "fix the cited file"),
                # Real board titles from the 2026-11-27 census (24 labelled by the key rule).
                ("Handoff gate: \"every branch is pushed\" must come from git worktree list on disk", "ASK-4135"),
                ("The morning brief reads the state card 30 minutes before it is written", "ASK-1405"),
                ("Declare the four CRM Run Control rows in control.JOBS so the deadman can see them", "ASK-1187"),
                ("fix the reviewer\n\nadd a deadman to the morning brief", "the key only in the description"),
                ("morning-brief.py crashes on an empty ledger", "a bug report with no key (round 4)")):
            rc, out = step0(title, KIPI_LESSONS_CORPORA=str(empty))
            check(f"no stop: {why}",
                  rc == 0 and out.get("decision") == "pass" and out.get("checked") is True, (rc, out))
        rc, out = step0("   \n\n", KIPI_LESSONS_CORPORA=str(empty))
        check("empty ticket text is NOT CHECKED, never a checked pass (it would clear the step-0 flags)",
              rc == 0 and out.get("checked") is False and "NOT CHECKED" in out.get("line", ""), (rc, out))

        # THE WRITE PATH: --attempts + --apply, with the Linear writer stubbed.
        # The stub logs every call; a cancel or a PR close would show as a call
        # that is not progress or label.
        led = root / "attempts.json"
        synclog = root / "sync.log"
        stub = root / "sync_stub.py"
        stub.write_text("import json, sys\n"
                        f"open({str(synclog)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n")
        ledger_py = STEP0.parent / "attempts-ledger.py"

        def apply(text: str) -> tuple[int, dict, list]:
            synclog.unlink(missing_ok=True)
            p = subprocess.run([sys.executable, str(STEP0), "--issue", "ASK-1", "--attempts", str(led), "--apply"],
                               input=text, capture_output=True, text=True, timeout=60,
                               env=dict(os.environ, KIPI_LESSONS_CORPORA=str(empty),
                                        KIPI_STEP0_SYNC=f"{sys.executable} {stub}"))
            calls = [json.loads(x) for x in synclog.read_text().splitlines()] if synclog.exists() else []
            try:
                return p.returncode, json.loads(p.stdout), calls
            except ValueError:
                return p.returncode, {"raw": p.stdout + p.stderr}, calls

        def flag(name: str) -> str:
            return subprocess.run([sys.executable, str(ledger_py), str(led), "get", "ASK-1", name, ""],
                                  capture_output=True, text=True).stdout.strip()

        led.write_text("{}")
        built = "Build review-tier.py for risk-scored auto-merge"
        rc, out, calls = apply(built)
        check("--apply on a match: one comment naming the file, then the label, and nothing else",
              rc == 3 and [c[0] for c in calls] == ["progress", "label"]
              and calls[1] == ["label", "ASK-1", "step0:already-built"]
              and "review-tier.py" in calls[0][2] and out.get("labelled") is True, (rc, out, calls))
        check("--apply on a match records step0_labelled", flag("step0_labelled") == "True", led.read_text())
        rc, out, calls = apply(built)
        check("a removed label lets the ticket pass: step 0 stands down, writes nothing",
              rc == 0 and out.get("decision") == "pass" and "stands down" in out.get("line", "")
              and not calls, (rc, out, calls))
        rc, out, calls = apply("usage-pacer.py usage_pct() crashes on TimeoutExpired instead of returning None")
        check("--apply on no match passes, writes nothing to Linear, and clears the step-0 flags",
              rc == 0 and not calls and flag("step0_labelled") == "" and flag("step0_comment_posted") == "",
              (rc, out, calls, led.read_text()))
        rc, out, calls = apply(built)
        check("after a checked pass cleared the flags, a later match labels again",
              rc == 3 and [c[0] for c in calls] == ["progress", "label"], (rc, calls))
        badled = root / "badledger.py"
        badled.write_text("import subprocess, sys\n"
                          "if sys.argv[2:4] == ['claim-flag', 'ASK-1'] and sys.argv[4] == 'step0_labelled':\n"
                          "    sys.exit(9)\n"
                          f"sys.exit(subprocess.run([sys.executable, {str(ledger_py)!r}] + sys.argv[1:]).returncode)\n")
        spec = importlib.util.spec_from_file_location("t0_under_test", str(STEP0))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        led.write_text("{}")
        synclog.unlink(missing_ok=True)
        ok, note = mod.label_stop("ASK-1", {"comment": "c", "cites": ["x.py"]},
                                  [sys.executable, str(badled), str(led)], [sys.executable, str(stub)])
        check("a step0_labelled flag that does not record is RED, not a silent success",
              ok is False and "did not record" in note, note)
        led.write_text("{}")
        synclog.unlink(missing_ok=True)
        p = subprocess.run([sys.executable, str(STEP0), "--issue", "ASK-1", "--attempts", str(led)],
                           input=built, capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, KIPI_LESSONS_CORPORA=str(empty),
                                    KIPI_STEP0_SYNC=f"{sys.executable} {stub}"))
        check("without --apply a match stops (exit 3) and writes nothing (the dry pick)",
              p.returncode == 3 and not synclog.exists() and flag("step0_labelled") == "", (p.returncode, p.stdout))

        rc, out = step0("usage-pacer.py usage_pct() crashes on TimeoutExpired instead of returning None",
                        KIPI_LESSONS_CORPORA=str(empty))
        check("a ticket for something new passes (exit 0), checked, no comment",
              rc == 0 and out.get("decision") == "pass" and out.get("checked") is True
              and not out.get("comment"), (rc, out))

        rc, out = step0("list every launchd plist trigger and diff it against the stages that should run",
                        KIPI_LESSONS_CORPORA=str(full))
        check("a lesson-only match passes, and the line says advisory (a lesson is not the build)",
              rc == 0 and out.get("decision") == "pass" and out.get("basis") == "lesson"
              and "advisory" in out.get("line", ""), (rc, out))

        ghost = root / "ghost.py"
        ghost.write_text("import json\nprint(json.dumps({'verdict': 'already-built', 'basis': 'named-file', "
                         "'matched': 'deadman', 'cites': ['q-system/no-such-file.py'], 'reason': 'x'}))\n")
        rc, out = step0("add no-such-file.py, a deadman for the sweep", KIPI_STEP0_GROUND=str(ghost))
        check("a named-file verdict citing a file that does not exist passes (no cancel on a ghost)",
              rc == 0 and out.get("decision") == "pass" and out.get("checked") is True, (rc, out))

        broken = root / "broken.py"
        broken.write_text("import sys\nsys.stderr.write('boom')\nsys.exit(1)\n")
        rc, out = step0("add risk-scored auto-merge for low-risk PRs", KIPI_STEP0_GROUND=str(broken))
        check("a crashing improve_ground passes, and the line says NOT CHECKED",
              rc == 0 and out.get("checked") is False and "NOT CHECKED" in out.get("line", ""), (rc, out))

        garbage = root / "garbage.py"
        garbage.write_text("print('not json')\n")
        rc, out = step0("risk-scored auto-merge for low-risk PRs", KIPI_STEP0_GROUND=str(garbage))
        check("output that is not a verdict passes as NOT CHECKED",
              rc == 0 and out.get("checked") is False and "NOT CHECKED" in out.get("line", ""), (rc, out))

        hang = root / "hang.py"
        hang.write_text("import time\ntime.sleep(30)\n")
        rc, out = step0("risk-scored auto-merge for low-risk PRs", KIPI_STEP0_GROUND=str(hang), KIPI_STEP0_TIMEOUT="1")
        check("a hung improve_ground passes after the timeout, NOT CHECKED, timed out",
              rc == 0 and out.get("checked") is False and "timed out" in out.get("line", ""), (rc, out))

    src = STEP0.read_text()
    check("step 0 spends no model call (no claude, no network in the source)",
          not any(b in src for b in ("claude -p", "anthropic", "urllib", "requests")), "")
    print(f"\n{'FAIL' if FAILS else 'PASS'}: {len(FAILS)} failed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
