#!/usr/bin/env python3
"""fleet-model-gate-scan.py -- every model call site in every local checkout that
does NOT pass through the model gate (ASK-2395, PRD prd-model-gate-2026-10-02).

WHY. One day spent most of a week's subscription usage (RCA token-waste-loops,
2026-10-02). Every cap was local to one path, and the paths were listed from
memory. The gate (plugins/kipi-core/voiceloop/model_gate.py) only caps what
passes through it, so this scan reads the population of call sites FROM SOURCE,
daily, the same way fleet-full-suite-scan reads the population of test doors.

POPULATION. The checkouts come from fleet-full-suite-scan.local_checkouts: the
registry's skeleton, instances and standalone repos, plus every git repo one
level under the projects root. The call sites come from the existing detector,
voiceloop/call_sites.py, so there is ONE definition of "a model call" in this
repo, not two that drift.

WHAT COUNTS AS GATED:
  .sh  a line run through model-gate.sh never reaches the detector: the token in
       command position is the door, not `claude`. So a detected .sh site is an
       ungated one.
  .py  the voiceloop wrapper (prompt_render.py) is the gate's own caller. Any
       other .py site counts as gated only when the FILE names the door
       (`model-gate.sh`) or calls `model_gate.check(`. That is a file-level
       proxy: a file with one gated and one direct call reads gated. It is
       printed below as an unscanned class, never hidden.

WHAT IT CANNOT SEE is printed in every report as `unscanned`, so its silence is
never read as coverage (PRD review finding 6).

THE ALERT: one line to slack-notify.sh (Sana's queue) on a STATE CHANGE only.
SINGLE WRITER of ~/.config/kipi/fleet-model-gate-scan/state.json, written only
after the alert was delivered or none was due.

EXIT: 0 a completed scan (ungated sites are the alert's job; with
--fail-on-ungated, 1 when any exist), 2 no checkout could be read (an empty
population is a failure, never an all-clear), 3 an alert that was not delivered.

Test seams: KIPI_ALERT_CMD, --state-dir, --projects-root, --registry.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # scripts -> .q-system -> q-system -> repo root
sys.path.insert(0, str(ROOT / "plugins" / "kipi-core"))
from voiceloop import call_sites as cs  # noqa: E402

_spec = importlib.util.spec_from_file_location("ffss", HERE / "fleet-full-suite-scan.py")
ffss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ffss)

WRAPPERS = {"plugins/kipi-core/voiceloop/prompt_render.py"}
DOOR_MARKERS = ("model-gate.sh", "model_gate.check(")
UNSCANNED = [
    "cloud routines (they run off this machine)",
    "binaries not named claude (opencode, codex exec, the anthropic SDK)",
    "claude -p assembled inside a shell string in Python",
    "a .py file with both a gated and a direct call (the gated check is per file)",
    "test directories and untracked files (call_sites skips them)",
]


def ungated_in(top: Path) -> tuple[list[str], int]:
    """(ungated sites, all detected sites) for one checkout, as repo-relative paths."""
    sites = cs.call_sites(top) - WRAPPERS
    out = []
    for rel in sorted(sites):
        if rel.endswith(".py"):
            try:
                text = (top / rel).read_text(errors="replace")
            except OSError:
                text = ""
            if any(m in text for m in DOOR_MARKERS):
                continue
        out.append(rel)
    return out, len(sites)


def scan(checkouts: list[Path]) -> dict:
    ungated, total, errors = [], 0, []
    for top in checkouts:
        try:
            sites, n = ungated_in(top)
        except RuntimeError as exc:
            errors.append({"checkout": str(top), "error": str(exc)[:200]})
            continue
        total += n
        ungated += [{"checkout": str(top), "path": p} for p in sites]
    return {"checkouts": len(checkouts), "sites": total, "ungated": ungated,
            "errors": errors, "unscanned": UNSCANNED}


def fingerprint(report: dict) -> str:
    keys = sorted(f"{u['checkout']}|{u['path']}" for u in report["ungated"])
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-alert", action="store_true")
    ap.add_argument("--fail-on-ungated", action="store_true")
    ap.add_argument("--state-dir", default="")
    ap.add_argument("--projects-root", default="")
    ap.add_argument("--registry", default="")
    a = ap.parse_args(argv)
    home = Path(os.path.expanduser("~"))
    state_dir = Path(a.state_dir) if a.state_dir else home / ".config" / "kipi" / "fleet-model-gate-scan"
    registry = Path(a.registry) if a.registry else ROOT / "instance-registry.json"
    projects = Path(a.projects_root) if a.projects_root else ROOT.parent
    checkouts = ffss.local_checkouts(registry, projects)
    if not checkouts:
        print("fleet-model-gate-scan: no checkout could be read; refusing to report zero", file=sys.stderr)
        return 2
    report = scan(checkouts)
    report["fingerprint"] = fingerprint(report)
    if a.json:
        print(json.dumps(report, indent=1))
    else:
        print(f"checkouts {report['checkouts']}  call sites {report['sites']}  "
              f"ungated {len(report['ungated'])}  errors {len(report['errors'])}")
        for u in report["ungated"]:
            print(f"  UNGATED {u['checkout']}  {u['path']}")
        for s in UNSCANNED:
            print(f"  unscanned: {s}")
    prev = ffss.read_state(state_dir)
    if not a.no_alert and (prev or {}).get("fingerprint") != report["fingerprint"]:
        was = len(prev.get("ungated", [])) if prev else "unknown"
        line = (f"fleet-model-gate-scan: {len(report['ungated'])} model call sites not behind "
                f"the model gate across {report['checkouts']} checkouts (was {was}); "
                f"run fleet-model-gate-scan.py for the list")
        if not ffss.alert(line):
            print("fleet-model-gate-scan: alert not delivered; state left unchanged", file=sys.stderr)
            return 3
    if not a.no_alert:
        ffss.write_state(state_dir, report)
    return 1 if (a.fail_on_ungated and report["ungated"]) else 0


if __name__ == "__main__":
    sys.exit(main())
