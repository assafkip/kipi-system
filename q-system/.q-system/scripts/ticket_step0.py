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

A STOP NEEDS THE TITLE TO NAME THE CITED FILE, because a stop ends in
cap-ladder.py canceling the ticket. (1) basis "named-file", (2) the ticket
TITLE contains the basename of a cited file, with or without its extension, as
a whole word, case-insensitive ("capability-gate.py" or "capability-gate"),
(3) that file exists in this checkout. Every other already-built match (a key
in the title, anything in the description, a lesson) is an advisory line and
passes. Losing a stop is the safe direction: a missed duplicate costs one
build session, a false stop cancels live work unattended.
Why file identity and not wording: PR #899 and #903 spent four review rounds
tuning verb and preposition lists ("add Y to X" passed, "add Y on X" was
canceled), and each round found a new synonym. A title that names the exact
file is the one signal no synonym moves
(rca-pr899-step0-precision-three-rounds-2026-11-27.md).
Measured 2026-11-27 on every open owner:sana ticket, before that:
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
            f"names {named} ({reason}), and the ticket title names that file. Reopen to undo: step 0 then stands down for this ticket and the worker "
            "takes it as written. (ticket_step0.py, ASK-5802)")


def title_names_cited_file(title: str, cites: list) -> bool:
    """True only when the title names a cited file by its basename, with or
    without the extension, and that file is really here. Nothing else stops:
    a cancel runs unattended, so every doubt passes the ticket."""
    for cite in cites:
        path = Path(cite)
        if not (REPO / path).is_file():
            continue
        for name in {path.name, path.stem}:
            if name and re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", title, re.IGNORECASE):
                return True
    return False


def check(issue: str, text: str) -> dict:
    """The one decision. Never raises. `text` is the title, a blank line, then
    the description (both callers build it that way)."""
    if not (text or "").strip():
        # PR #903 round 1, minor 3: the worker's WIP rework rows carry no text,
        # and a "checked" pass on nothing cleared the step0_canceled flag.
        return _not_checked(issue, "no ticket text to check")
    verdict, err = run_ground((text or "")[:MAX_TEXT])
    if verdict is None:
        return _not_checked(issue, err)
    cites = [str(c) for c in verdict.get("cites") or []]
    basis = verdict.get("basis") or ""
    title = (text or "").split("\n", 1)[0]
    if (verdict["verdict"] == "already-built" and basis == "named-file"
            and title_names_cited_file(title, cites)):
        return {"decision": "stop", "checked": True, "basis": basis, "cites": cites,
                "comment": stop_comment(issue, cites, verdict.get("reason") or ""),
                "line": f"step 0 {issue}: STOP, already built: {', '.join(cites)}"}
    if verdict["verdict"] == "already-built":
        return {"decision": "pass", "checked": True, "basis": basis, "cites": cites, "comment": "",
                "line": f"step 0 {issue}: pass (advisory: already-built on a {basis or 'lesson'} match, "
                        f"but the title does not name the file: {', '.join(Path(c).name for c in cites)})"}
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
