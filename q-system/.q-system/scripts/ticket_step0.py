#!/usr/bin/env python3
"""ticket_step0.py -- step 0 of any ticket: should it exist at all (ASK-5802).

Founder, 2026-11-26, verbatim: "chekcing if the ticket should exist should be
step 0" and "improve_ground.py must be wired to run on its own before new
scripts or gates get built". And: "We dont need to parallel paths doing th
esame thing". So the verdict comes from improve_ground.py, unchanged, and
this file is the one place that turns it into stop or pass. Both callers
use it:
linear-worker.sh (before the build prompt, through the CLI) and cap-ladder.py
(rung 0, before the rung 1 RCA, through check()).

STOP only on basis "named-file". Measured 2026-11-26 on 35 real owner:sana
backlog tickets: 6 came back already-built, all on basis "lesson", and none of
the 6 was built (ASK-5779 "Reinstate X" matched a lesson about porting gates).
A lesson on the topic is advice for the build, not the build. Those are logged
as advisory and pass.

FAILS OPEN, LOUDLY. If improve_ground.py crashes, hangs past the timeout or
prints something that is not its JSON, the ticket proceeds and the line says
step 0 did NOT check. A gate that cannot run must not hold the whole fleet,
and its silence must never read as "checked, nothing found".

No model call, no network: improve_ground.py is offline by its own test.

CLI:  ticket_step0.py --issue ASK-n  < ticket title + description
      stdout: one JSON object {decision, checked, basis, cites, line, comment}
      exit 3 = stop, exit 0 = pass (every failure is a pass)
Env:  KIPI_STEP0_GROUND   another grounding script (tests point it at a broken one)
      KIPI_STEP0_TIMEOUT  seconds, default 30 (one call measured about 1.2 s)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]  # scripts -> .q-system -> q-system -> repo
GROUND = REPO / "plugins" / "kipi-core" / "skills" / "improve" / "scripts" / "improve_ground.py"
STOP_EXIT = 3
# A ticket body can be long; the verdict only needs what the ticket asks for.
MAX_TEXT = 4000


def _ground_path() -> Path:
    return Path(os.environ.get("KIPI_STEP0_GROUND") or GROUND)


def _timeout() -> float:
    try:
        return float(os.environ.get("KIPI_STEP0_TIMEOUT") or 30)
    except ValueError:
        return 30.0


def _not_checked(issue: str, why: str) -> dict:
    return {"decision": "pass", "checked": False, "basis": "", "cites": [], "comment": "",
            "line": f"step 0 {issue}: NOT CHECKED ({why}); the ticket proceeds unchecked"}


def run_ground(text: str) -> tuple[dict | None, str]:
    """(verdict, error). improve_ground exits 0 on already-built and adopt, 2 on
    skip; any other exit, a timeout or unparseable output is an error."""
    try:
        p = subprocess.run([sys.executable, str(_ground_path()), "--target", "script"],
                           input=text, capture_output=True, text=True, timeout=_timeout())
    except subprocess.TimeoutExpired:
        return None, f"improve_ground.py timed out after {_timeout():.0f}s"
    except OSError as exc:
        return None, f"improve_ground.py did not start: {exc}"
    if p.returncode not in (0, 2):
        return None, f"improve_ground.py exited {p.returncode}: {(p.stderr or p.stdout).strip()[-160:]}"
    try:
        out = json.loads(p.stdout)
        verdict = out["verdict"]
    except (ValueError, KeyError, TypeError):
        return None, f"improve_ground.py printed no verdict: {p.stdout.strip()[:160]!r}"
    return dict(out, verdict=verdict), ""


def stop_comment(issue: str, cites: list, reason: str) -> str:
    named = ", ".join(f"`{c}`" for c in cites)
    return (f"**Step 0 stopped {issue}: it is already built.** improve_ground.py names {named} "
            f"({reason}). No build session was spent on it.\n\n"
            "The check re-runs on the ticket's current title and description each time a worker "
            "or cap-ladder.py reaches it, so it re-enters on its own once the ticket says what it "
            "needs beyond that file. (ticket_step0.py, ASK-5802)")


def check(issue: str, text: str) -> dict:
    """The one decision. Never raises."""
    verdict, err = run_ground((text or "")[:MAX_TEXT])
    if verdict is None:
        return _not_checked(issue, err)
    cites = [str(c) for c in verdict.get("cites") or []]
    basis = verdict.get("basis") or ""
    if verdict["verdict"] == "already-built" and basis == "named-file":
        return {"decision": "stop", "checked": True, "basis": basis, "cites": cites,
                "comment": stop_comment(issue, cites, verdict.get("reason") or ""),
                "line": f"step 0 {issue}: STOP, already built: {', '.join(cites)}"}
    if verdict["verdict"] == "already-built":
        return {"decision": "pass", "checked": True, "basis": basis, "cites": cites, "comment": "",
                "line": f"step 0 {issue}: pass (advisory: a {basis or 'lesson'} covers the topic, "
                        f"not the deliverable: {', '.join(Path(c).name for c in cites)})"}
    return {"decision": "pass", "checked": True, "basis": basis, "cites": cites, "comment": "",
            "line": f"step 0 {issue}: pass ({verdict['verdict']})"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="step 0: should this ticket exist")
    ap.add_argument("--issue", required=True)
    args = ap.parse_args(argv)
    out = check(args.issue, sys.stdin.read())
    print(json.dumps(out))
    return STOP_EXIT if out["decision"] == "stop" else 0


if __name__ == "__main__":
    raise SystemExit(main())
