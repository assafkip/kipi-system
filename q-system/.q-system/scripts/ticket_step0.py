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

A STOP NEEDS FOUR THINGS, because a stop ends in cap-ladder.py canceling the
ticket. (1) basis "named-file", (2) the KNOWN_BUILT key it matched is a whole
word in the TITLE, (3) the title opens with a build verb, (4) the cited file
exists in this checkout. Anything short of that is logged as advisory and
passes. Why so narrow, measured 2026-11-27 on every open owner:sana ticket:
- a lesson match is advice for the build, not the build: 6 of 35 sampled
  tickets matched a lesson and none was built (ASK-5779 "Reinstate X" matched
  a lesson about porting gates);
- the named-file table is substring keys written for pasted outside ideas.
  Over title + description it stopped 45+ real tickets, all false: "handoff"
  hit any ticket mentioning a handoff, "deadman" hit every launchd deadman
  bug (ASK-1199 "launchd job is dark: ...-deadman"). A ticket reporting that
  something is broken is about code that exists, so it is never a duplicate
  build, and only a title that proposes building is a build proposal.
  (PR #893 round 1, finding 1; the producer's own precision is ASK-5805.)

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
import re
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
    """Posted by cap-ladder.py rung 0 when it cancels the ticket."""
    named = ", ".join(f"`{c}`" for c in cites)
    return (f"**Canceled at step 0: {issue} asks to build something that exists.** improve_ground.py "
            f"names {named} ({reason}), and the title proposes building it. No build session or RCA "
            "was spent on it. Reopen to undo: step 0 then stands down for this ticket and the worker "
            "takes it as written. (ticket_step0.py, ASK-5802)")


BUILD_VERB = re.compile(r"^\W*(add|build|create|implement|introduce|write|make|ship|new)\b", re.IGNORECASE)


def build_proposal_of(title: str, key: str, cites: list) -> bool:
    """True only when the title proposes building the thing the key names and
    the cited file is really here. See the module docstring for the measurement."""
    in_title = bool(key) and re.search(rf"(?<![\w-]){re.escape(key)}(?![\w-])", title, re.IGNORECASE)
    exists = bool(cites) and all((REPO / c).is_file() for c in cites)
    return bool(in_title and BUILD_VERB.match(title) and exists)


def check(issue: str, text: str) -> dict:
    """The one decision. Never raises. `text` is the title, a blank line, then
    the description (both callers build it that way)."""
    verdict, err = run_ground((text or "")[:MAX_TEXT])
    if verdict is None:
        return _not_checked(issue, err)
    cites = [str(c) for c in verdict.get("cites") or []]
    basis = verdict.get("basis") or ""
    title = (text or "").split("\n", 1)[0]
    if (verdict["verdict"] == "already-built" and basis == "named-file"
            and build_proposal_of(title, verdict.get("matched") or "", cites)):
        return {"decision": "stop", "checked": True, "basis": basis, "cites": cites,
                "comment": stop_comment(issue, cites, verdict.get("reason") or ""),
                "line": f"step 0 {issue}: STOP, already built: {', '.join(cites)}"}
    if verdict["verdict"] == "already-built":
        return {"decision": "pass", "checked": True, "basis": basis, "cites": cites, "comment": "",
                "line": f"step 0 {issue}: pass (advisory: already-built on a {basis or 'lesson'} match, "
                        f"but the title is not a build proposal for it: {', '.join(Path(c).name for c in cites)})"}
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
