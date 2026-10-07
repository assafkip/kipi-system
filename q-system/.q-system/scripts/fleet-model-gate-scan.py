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
       command position is the door, not `claude`. A door wrapping a `bash -c`
       body whose string holds `claude -p` IS still detected (the detector reads
       -c strings), so that shape reads ungated: an over-count, the safe side.
  .py  a site counts as gated only when its CODE, read as an AST, holds a
       string literal ending in `model-gate.sh` or a call to `model_gate.check`.
       A comment or a docstring naming the door does not count (PR #506 review:
       a TODO comment marked a direct caller gated). Still a file-level answer:
       a file with one gated and one direct call reads gated, which is printed
       below as an unscanned class, never hidden. The voiceloop wrapper
       (prompt_render.py) gets NO exemption by path: it was trusted as gated on
       trees where it never called the gate, so "0 ungated" was reachable with the
       chokepoint unmetered (PR #506 review round 2). It earns the exclusion per
       run, like every other file, by calling model_gate.check.

LINKED WORKTREES in that population are skipped: a per-session worktree is a
copy of a checkout already counted, and opening or removing one flipped the
fingerprint and filed a ticket for no code change (PR #506 review, ASK-2400).

EXCEPT THE TREES LAUNCHD RUNS FROM (ASK-2540, RCA token-burn-recurs-after-gate
2026-10-06). The live runner trees are linked worktrees, so the skip above hid
exactly the code that runs on a schedule: "357 ungated" never included it. The
executing trees are read from the LOADED jobs (`launchctl list` labels, then
each plist's WorkingDirectory and ProgramArguments paths, then git toplevel),
never from a hardcoded runner path. A loaded job's tree is stable, so it does
not reopen the per-session fingerprint flap.

WHAT IT CANNOT SEE is printed in every report as `unscanned`, so its silence is
never read as coverage (PRD review finding 6).

THE ALERT: one line to slack-notify.sh (Sana's queue) on a STATE CHANGE only.
SINGLE WRITER of ~/.config/kipi/fleet-model-gate-scan/state.json, written only
after the alert was delivered or none was due.

THE DRAIN (ASK-2540). The count sat at 357 for four runs and nothing failed: a
detector with no consumer reads as coverage. Once per ISO week the scan files
ONE line through the same alert path with the count and the delta, and every
run exits 4 while this week's count is not lower than last week's. The first
week with no prior is recorded only. SINGLE WRITER of weekly.json beside
state.json (write_weekly), written only after the weekly line was delivered.

EXIT: 0 a completed scan (ungated sites are the alert's job; with
--fail-on-ungated, 1 when any exist), 2 no checkout could be read (an empty
population is a failure, never an all-clear), 3 an alert that was not delivered,
4 the ungated count did not fall week over week.

Test seams: KIPI_ALERT_CMD, KIPI_LAUNCHCTL (the launchctl command),
KIPI_LAUNCHAGENTS_DIR, KIPI_SCAN_TODAY (YYYY-MM-DD), --state-dir,
--projects-root, --registry.

STABLE NAMES for importers: loaded_launchd_labels, launchd_job_paths,
executing_trees, checkouts_to_scan.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import plistlib
import shlex
import subprocess
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # scripts -> .q-system -> q-system -> repo root
sys.path.insert(0, str(ROOT / "plugins" / "kipi-core"))
from voiceloop import call_sites as cs  # noqa: E402

_spec = importlib.util.spec_from_file_location("ffss", HERE / "fleet-full-suite-scan.py")
ffss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ffss)

def _py_names_the_door(text: str) -> bool:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False  # unreadable reads ungated: the safe side
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
                and node.value.rstrip().endswith("model-gate.sh")):
            return True
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "check"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "model_gate"):
            return True
    return False
UNSCANNED = [
    "cloud routines (they run off this machine)",
    "binaries not named claude (opencode, codex exec, the anthropic SDK)",
    "claude -p assembled inside a shell string in Python",
    "a .py file with both a gated and a direct call (the gated check is per file)",
    "test directories and untracked files (call_sites skips them)",
]


def ungated_in(top: Path) -> tuple[list[str], int]:
    """(ungated sites, all detected sites) for one checkout, as repo-relative paths."""
    sites = cs.call_sites(top)
    out = []
    for rel in sorted(sites):
        if rel.endswith(".py"):
            try:
                text = (top / rel).read_text(errors="replace")
            except OSError:
                text = ""
            if _py_names_the_door(text):
                continue
        out.append(rel)
    return out, len(sites)


def is_linked_worktree(top: Path) -> bool:
    git_dir = ffss._git(top, "rev-parse", "--absolute-git-dir")
    common = ffss._git(top, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return bool(git_dir and common) and Path(git_dir).resolve() != Path(common).resolve()


def loaded_launchd_labels(launchctl_cmd: list[str] | None = None) -> set[str] | None:
    """Labels of the jobs launchd has LOADED, or None when launchctl could not be
    read (a host with no launchd). None is reported, never read as "no jobs"."""
    cmd = launchctl_cmd or shlex.split(os.environ.get("KIPI_LAUNCHCTL", "launchctl"))
    try:
        p = subprocess.run(cmd + ["list"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    labels = set()
    for line in p.stdout.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2].strip():
            labels.add(parts[2].strip())
    return labels


def _abs_paths(args: list) -> list[str]:
    out = []
    for a in args:
        if not isinstance(a, str):
            continue
        # `bash -lc "python3 /x/y.py"`: the path lives inside one argument.
        try:
            toks = shlex.split(a)
        except ValueError:
            toks = a.split()
        out += [t for t in toks if t.startswith("/")]
    return out


def launchd_job_paths(plist_dir: Path, labels: set[str]) -> list[tuple[str, str]]:
    """(label, path) for every loaded job's WorkingDirectory and absolute
    ProgramArguments paths. Keyed on the plist's Label, not its filename."""
    out = []
    if not plist_dir.is_dir():
        return out
    for f in sorted(plist_dir.glob("*.plist")):
        try:
            with open(f, "rb") as fh:
                d = plistlib.load(fh)
        except Exception:
            continue  # an unreadable plist is not a job we can place
        label = d.get("Label") if isinstance(d, dict) else None
        if label not in labels:
            continue
        if isinstance(d.get("WorkingDirectory"), str):
            out.append((label, d["WorkingDirectory"]))
        out += [(label, p) for p in _abs_paths(d.get("ProgramArguments") or [])]
    return out


def executing_trees(plist_dir: Path | None = None,
                    launchctl_cmd: list[str] | None = None) -> tuple[list[Path], bool]:
    """(git toplevels a loaded launchd job runs from, launchd_readable).
    Linked worktrees INCLUDED: that is the point (ASK-2540)."""
    labels = loaded_launchd_labels(launchctl_cmd)
    if labels is None:
        return [], False
    if plist_dir is None:
        env_dir = os.environ.get("KIPI_LAUNCHAGENTS_DIR")
        plist_dir = Path(env_dir) if env_dir else Path.home() / "Library" / "LaunchAgents"
    home = Path.home().resolve()
    seen, out = set(), []
    for _label, raw in launchd_job_paths(plist_dir, labels):
        p = Path(raw)
        d = p if p.is_dir() else p.parent
        if not d.is_dir():
            continue
        top = ffss._git(d, "rev-parse", "--show-toplevel")
        # Fleet code lives under $HOME. A vendor prefix can itself be a git repo:
        # the first live run counted /opt/homebrew, the WorkingDirectory of a
        # Homebrew postgres agent, as a checkout.
        if top and not Path(top).resolve().is_relative_to(home):
            continue
        if top and str(Path(top).resolve()) not in seen:
            seen.add(str(Path(top).resolve()))
            out.append(Path(top))
    return out, True


def checkouts_to_scan(registry: Path, projects: Path, plist_dir: Path | None = None,
                      launchctl_cmd: list[str] | None = None) -> tuple[list[Path], int, bool]:
    """(checkouts, how many came ONLY from launchd, launchd_readable). The
    registry/projects population minus per-session worktrees, plus every tree a
    loaded job runs from, deduped on the resolved path."""
    base = [c for c in ffss.local_checkouts(registry, projects) if not is_linked_worktree(c)]
    seen = {str(c.resolve()) for c in base}
    runners, readable = executing_trees(plist_dir, launchctl_cmd)
    added = [t for t in runners if str(t.resolve()) not in seen]
    return base + added, len(added), readable


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def read_weekly(state_dir: Path) -> dict:
    f = state_dir / "weekly.json"
    try:
        data = json.loads(f.read_text())
        return data if isinstance(data.get("weeks"), dict) else {"weeks": {}}
    except (OSError, ValueError, AttributeError):
        return {"weeks": {}}


def write_weekly(state_dir: Path, data: dict) -> None:
    """The ONE writer of weekly.json. Called only after the weekly line was
    delivered or none was due, so a failed filing is retried next run."""
    state_dir.mkdir(parents=True, exist_ok=True)
    weeks = data["weeks"]
    keep = dict(sorted(weeks.items())[-12:])  # a quarter of history is enough
    f = state_dir / "weekly.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"weeks": keep}, indent=1, sort_keys=True))
    os.replace(tmp, f)


def weekly_verdict(weekly: dict, week: str, count: int) -> dict:
    """What this run owes the drain: file this week's line or not, and whether
    the count failed to fall against the latest EARLIER week on record."""
    prior = sorted(k for k in weekly["weeks"] if k < week)
    prev = weekly["weeks"][prior[-1]]["ungated"] if prior else None
    filed = bool(weekly["weeks"].get(week, {}).get("filed"))
    return {"week": week, "ungated": count, "prev_week": prior[-1] if prior else None,
            "prev": prev, "delta": None if prev is None else count - prev,
            "not_falling": prev is not None and count >= prev, "file": not filed}


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
    # A checkout that could not be read is part of the state, or a scan that
    # read nothing would look like a clean, quiet day forever (PR #506 review).
    keys += sorted(f"error|{e['checkout']}" for e in report["errors"])
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
    # Same default as the sibling scan, so the two read one population.
    projects = Path(a.projects_root) if a.projects_root else home / "projects"
    checkouts, runner_trees, launchd_ok = checkouts_to_scan(registry, projects)
    if not checkouts:
        print("fleet-model-gate-scan: no checkout could be read; refusing to report zero", file=sys.stderr)
        return 2
    report = scan(checkouts)
    report["fingerprint"] = fingerprint(report)
    report["runner_trees"] = runner_trees
    report["launchd_readable"] = launchd_ok
    today = date.fromisoformat(os.environ["KIPI_SCAN_TODAY"]) if os.environ.get("KIPI_SCAN_TODAY") else date.today()
    weekly = read_weekly(state_dir)
    verdict = weekly_verdict(weekly, iso_week(today), len(report["ungated"]))
    report["weekly"] = verdict
    if report["errors"] and len(report["errors"]) == len(checkouts):
        print("fleet-model-gate-scan: every checkout failed to read; refusing to report zero", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(report, indent=1))
    else:
        print(f"checkouts {report['checkouts']} (launchd runner trees {runner_trees}"
              f"{'' if launchd_ok else ', launchd UNREADABLE'})  call sites {report['sites']}  "
              f"ungated {len(report['ungated'])}  errors {len(report['errors'])}  "
              f"week {verdict['week']} last week {verdict['prev'] if verdict['prev'] is not None else 'none'}")
        for u in report["ungated"]:
            print(f"  UNGATED {u['checkout']}  {u['path']}")
        for s in UNSCANNED:
            print(f"  unscanned: {s}")
    prev = ffss.read_state(state_dir)
    if not a.no_alert and (prev or {}).get("fingerprint") != report["fingerprint"]:
        was = len(prev.get("ungated", [])) if prev else "unknown"
        line = (f"fleet-model-gate-scan: {len(report['ungated'])} model call sites not behind "
                f"the model gate across {report['checkouts']} checkouts (was {was}), "
                f"{len(report['errors'])} checkouts unreadable; "
                f"run fleet-model-gate-scan.py for the list")
        if not ffss.alert(line):
            print("fleet-model-gate-scan: alert not delivered; state left unchanged", file=sys.stderr)
            return 3
    if not a.no_alert:
        ffss.write_state(state_dir, report)
        if verdict["file"]:
            delta = "first week, no prior" if verdict["delta"] is None else f"delta {verdict['delta']:+d}"
            line = (f"fleet-model-gate-scan weekly: {verdict['week']} {verdict['ungated']} ungated "
                    f"model call sites across {report['checkouts']} checkouts "
                    f"({runner_trees} launchd runner trees), last week "
                    f"{verdict['prev'] if verdict['prev'] is not None else 'none'}, {delta}"
                    f"{'; NOT FALLING, the scan exits 4 until it does' if verdict['not_falling'] else ''}")
            if not ffss.alert(line):
                print("fleet-model-gate-scan: weekly filing not delivered; week left unfiled", file=sys.stderr)
                return 3
        weekly["weeks"][verdict["week"]] = {"ungated": verdict["ungated"], "filed": True}
        write_weekly(state_dir, weekly)
    if verdict["not_falling"]:
        print(f"fleet-model-gate-scan: ungated {verdict['ungated']} is not lower than "
              f"{verdict['prev_week']} ({verdict['prev']})", file=sys.stderr)
        return 4
    return 1 if (a.fail_on_ungated and report["ungated"]) else 0


if __name__ == "__main__":
    sys.exit(main())
