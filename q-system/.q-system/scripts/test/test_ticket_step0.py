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

        rc, out = step0("risk-scored auto-merge for low-risk PRs\n\nbuild it", KIPI_LESSONS_CORPORA=str(empty))
        check("a ticket for a named file that exists STOPS (exit 3) and names the file",
              rc == 3 and out.get("decision") == "stop" and out.get("checked") is True
              and "q-system/.q-system/scripts/review-tier.py" in out.get("cites", [])
              and "review-tier.py" in out.get("comment", ""), (rc, out))

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

        broken = root / "broken.py"
        broken.write_text("import sys\nsys.stderr.write('boom')\nsys.exit(1)\n")
        rc, out = step0("risk-scored auto-merge for low-risk PRs", KIPI_STEP0_GROUND=str(broken))
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
