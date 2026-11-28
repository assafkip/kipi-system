#!/usr/bin/env python3
"""ticket_step0.py, the one should-exist decision (ASK-5802).

Fixtures come from the producer: the named-file case is improve_ground's own
("risk-scored auto-merge" -> review-tier.py), and the lesson case reuses the
three-lesson corpus from test_improve_ground.py::test_a_covered_idea_cites_the_lesson_path.
Corpora are tmp dirs through KIPI_LESSONS_CORPORA, never the live lessons dir.

Run: python3 q-system/.q-system/scripts/test/test_ticket_step0.py
"""
from __future__ import annotations

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

        # WHAT STOPS: the matched key in the TITLE (a stop is now a label, never
        # a cancel, so the old precision carve-outs are gone on purpose:
        # rca-ask5802-five-rounds-step0-cancel-2026-11-27.md).
        for title, why in (
                ("Build review-tier.py for risk-scored auto-merge\n\nbuild it", "key and file in the title"),
                ("add risk-scored auto-merge for low-risk PRs", "the known-answer case: key in the title"),
                ("Add a RISK-SCORED AUTO-MERGE pass", "key in the title, any case")):
            rc, out = step0(title, KIPI_LESSONS_CORPORA=str(empty))
            check(f"a stop (exit 3) names the file: {why}",
                  rc == 3 and out.get("decision") == "stop" and out.get("checked") is True
                  and "q-system/.q-system/scripts/review-tier.py" in out.get("cites", [])
                  and "review-tier.py" in out.get("comment", "")
                  and "step0:already-built" in out.get("comment", "")
                  and "Nothing is canceled" in out.get("comment", ""), (rc, out))
        for title, why in (
                ("fix the reviewer\n\nadd a deadman to the morning brief", "the key only in the description"),
                ("add a reviewer fallback\n\nthe deadman keeps paging", "build verb, key only in the description"),
                ("Add risk-scored auto-merges-plus to the queue\n\nrisk-scored auto-merge", "a longer word is not the key"),
                ("morning-brief.py crashes on an empty ledger", "a bug report with no key (round 4)"),
                ("Add a dry-run flag to review-tier.py", "the cited file named, no key (round 4)")):
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
        built = "add risk-scored auto-merge for low-risk PRs"
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
