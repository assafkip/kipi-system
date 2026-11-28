#!/usr/bin/env python3
"""ticket_step0.py -- step 0 of any ticket: should it exist at all (ASK-5802).

Founder, 2026-11-26, verbatim: "chekcing if the ticket should exist should be
step 0" and "improve_ground.py must be wired to run on its own before new
scripts or gates get built". And: "We dont need to parallel paths doing th
esame thing". So the verdict comes from improve_ground.py, unchanged, and
this file is the one place that turns it into stop or pass. Both callers
use it:
linear-worker.sh (before the build prompt, through the CLI) and cap-ladder.py
(rung 0, before the rung 1 RCA, through gate() and label_stop()).

A STOP IS A LABEL, NEVER A CANCEL (founder decision on ASK-5802, 2026-11-27).
On a stop the caller runs label_stop(): one comment naming the cited file, then
the label `step0:already-built`. linear-worker.sh ready() skips that label, so
the label is the only stop: removing it lets the ticket through on the next
pick (the ledger flag step0_labelled makes step 0 stand down for it). Step 0
never cancels a ticket and never closes a PR.
Why: PR #893, #899 and #903 ran five review rounds on one finding class. Every
matcher tried (phrase key, build verb, verb minus "to", the literal file name)
canceled some real ticket, because a text matcher has false positives at any
setting and a cancel made each one cost live work
(rca-ask5802-five-rounds-step0-cancel-2026-11-27.md). A label makes a false
stop cost one click, so precision stops being the lever.

WHAT STOPS: improve_ground.py says already-built on a named-file basis, the
cited file exists in this checkout, and the matched key is in the TITLE as a
whole word, case-insensitive. Anything else is an advisory line and passes: a
lesson-only match, or a key found only in the description. ("add risk-scored
auto-merge for low-risk PRs" stops on review-tier.py; "fix the reviewer" with
"add a deadman" in the body passes.)

FAILS OPEN, LOUDLY. If improve_ground.py crashes, hangs past the timeout or
prints something that is not its JSON, the ticket proceeds and the line says
step 0 did NOT check. A gate that cannot run must not hold the whole fleet,
and its silence must never read as "checked, nothing found".

No model call, no network: improve_ground.py is offline by its own test.

CLI:  ticket_step0.py --issue ASK-n [--attempts LEDGER [--apply]]  < title + description
      stdout: one JSON object {decision, checked, basis, cites, line, comment}
      exit 3 = stop, exit 0 = pass (every failure is a pass)
      --attempts reads the worker ledger, so a ticket whose label was removed
      stands down; --apply also writes: a stop is labelled and commented, a
      checked pass clears the step-0 flags.
Env:  KIPI_STEP0_SYNC     the Linear writer argv, default python3 linear-sync.py (tests stub it)
      KIPI_STEP0_GROUND   another grounding script (tests point it at a broken one)
      KIPI_STEP0_TIMEOUT  seconds, default 30 (one call measured about 1.2 s)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]  # scripts -> .q-system -> q-system -> repo
GROUND = REPO / "plugins" / "kipi-core" / "skills" / "improve" / "scripts" / "improve_ground.py"
STOP_EXIT = 3
LABEL = "step0:already-built"
# Set once the label lands. Seeing it on a ticket that no longer carries the
# label means the label was removed on purpose, so step 0 stands down.
LABELLED_FLAG = "step0_labelled"
# Claimed before the comment posts: a failed label write retries next tick
# without a second comment.
COMMENT_FLAG = "step0_comment_posted"
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


def stop_comment(issue: str, cites: list, reason: str, matched: str) -> str:
    """The one comment a stop posts, before the label."""
    named = ", ".join(f"`{c}`" for c in cites)
    return (f"**Step 0: {issue} looks already built.** improve_ground.py names {named} ({reason}); "
            f"the title matches `{matched}`. Labelled `{LABEL}`, so the worker skips it. "
            "Nothing is canceled. Remove the label and the next pick takes the ticket as written. "
            "(ticket_step0.py, ASK-5802)")


def title_has_key(title: str, matched: str) -> bool:
    """The matched KNOWN_BUILT key in the title as a whole word. A key only in
    the description is advice, not a stop."""
    return bool(matched) and re.search(rf"(?<![\w-]){re.escape(matched)}(?![\w-])",
                                       title, re.IGNORECASE) is not None


def cited_file_exists(cites: list) -> bool:
    return any((REPO / Path(c)).is_file() for c in cites)


def check(issue: str, text: str) -> dict:
    """The one decision. Never raises. `text` is the title, a blank line, then
    the description (both callers build it that way)."""
    if not (text or "").strip():
        # PR #903 round 1, minor 3: the worker's WIP rework rows carry no text,
        # and a "checked" pass on nothing cleared the step-0 flags.
        return _not_checked(issue, "no ticket text to check")
    verdict, err = run_ground((text or "")[:MAX_TEXT])
    if verdict is None:
        return _not_checked(issue, err)
    cites = [str(c) for c in verdict.get("cites") or []]
    basis = verdict.get("basis") or ""
    title = (text or "").split("\n", 1)[0]
    matched = str(verdict.get("matched") or "")
    if (verdict["verdict"] == "already-built" and basis == "named-file"
            and cited_file_exists(cites) and title_has_key(title, matched)):
        return {"decision": "stop", "checked": True, "basis": basis, "cites": cites,
                "comment": stop_comment(issue, cites, verdict.get("reason") or "", matched),
                "line": f"step 0 {issue}: STOP, already built: {', '.join(cites)}"}
    if verdict["verdict"] == "already-built":
        return {"decision": "pass", "checked": True, "basis": basis, "cites": cites, "comment": "",
                "line": f"step 0 {issue}: pass (advisory: already-built on a {basis or 'lesson'} match "
                        f"outside the title: {', '.join(Path(c).name for c in cites)})"}
    return {"decision": "pass", "checked": True, "basis": basis, "cites": cites, "comment": "",
            "line": f"step 0 {issue}: pass ({verdict['verdict']})"}


def _run(argv: list) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        return p.returncode, (p.stdout or p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 99, str(exc)


def gate(issue: str, text: str, ledger: list | None, apply: bool) -> dict:
    """check() plus the label's undo. A stop on a ticket that was labelled
    before stands down: it reached here, so the label is gone, and removing
    the label is how a person says "work it" (the label is the only stop).
    A checked pass on --apply clears both flags, so a later rewrite of the
    ticket is checked fresh. A NOT CHECKED fail-open clears nothing."""
    res = check(issue, text)
    if not ledger:
        return res
    if res["decision"] == "stop":
        rc, val = _run(ledger + ["get", issue, LABELLED_FLAG, ""])
        if rc == 0 and val == "True":
            return dict(res, decision="pass", comment="",
                        line=f"step 0 {issue}: stands down, its {LABEL} label was removed; the ticket proceeds")
    elif apply and res["checked"]:
        _run(ledger + ["clear-flag", issue, LABELLED_FLAG])
        _run(ledger + ["clear-flag", issue, COMMENT_FLAG])
    return res


def _sync_cmd() -> list:
    raw = os.environ.get("KIPI_STEP0_SYNC")
    return shlex.split(raw) if raw else [sys.executable, str(HERE / "linear-sync.py")]


def label_stop(issue: str, res: dict, ledger: list, sync: list | None = None) -> tuple[bool, str]:
    """The one writer of a step-0 stop: comment once, then the label, then the
    flag. Both callers use it (linear-worker.sh through --apply, cap-ladder.py
    rung 0 directly). Any failure leaves the ticket unlabelled, so the next
    tick stops it again and retries; the comment flag keeps it to one post."""
    sync = sync or _sync_cmd()
    rc, out = _run(ledger + ["claim-flag", issue, COMMENT_FLAG])
    if rc not in (0, 1):
        return False, f"could not claim the comment flag ({out[-120:]}); nothing written"
    if rc == 0:
        prc, pout = _run(sync + ["progress", issue, res["comment"], "--agent", "sana"])
        if prc != 0:
            _run(ledger + ["clear-flag", issue, COMMENT_FLAG])
            return False, f"could not post the step-0 comment ({pout[-120:]}); nothing labelled"
    lrc, lout = _run(sync + ["label", issue, LABEL])
    if lrc != 0:
        return False, f"comment posted, but the {LABEL} label did not land ({lout[-120:]})"
    _run(ledger + ["claim-flag", issue, LABELLED_FLAG])
    return True, f"labelled {LABEL}, comment names {', '.join(res['cites'])}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="step 0: should this ticket exist")
    ap.add_argument("--issue", required=True)
    ap.add_argument("--attempts", help="the worker attempts ledger (step-0 flags)")
    ap.add_argument("--apply", action="store_true", help="label a stop; clear the flags on a checked pass")
    args = ap.parse_args(argv)
    ledger = [sys.executable, str(HERE / "attempts-ledger.py"), args.attempts] if args.attempts else None
    out = gate(args.issue, sys.stdin.read(), ledger, args.apply)
    if out["decision"] == "stop" and args.apply and ledger:
        ok, note = label_stop(args.issue, out, ledger)
        out = dict(out, labelled=ok, line=f"{out['line']}; {note}" if ok
                   else f"{out['line']}; WARN {note}, the next tick retries")
    print(json.dumps(out))
    return STOP_EXIT if out["decision"] == "stop" else 0


if __name__ == "__main__":
    raise SystemExit(main())
