#!/usr/bin/env python3
"""The single mechanism that migrates the ASK-151 roster onto Linear-tracked execution.

WHAT "MIGRATED" MEANS -- four bars, the same four for every job, from the per-job
contract linear-job-migration.py wrote into the 32 issues ASK-151 collapsed:

  1. It runs under launchd, never cron. Cron has no keychain, so any job that
     shells `claude` fails auth there (ASK-150).
  2. Its failures and findings reach LINEAR, not just a log file. Deterministically:
     the label is covered by launchd-health-check.py's watched prefixes, which is
     exactly the set whose failures become `launchd-failing` / `launchd-dark`
     Linear issues. Unwatched means a failure reaches nobody.
  3. It is loaded, or it is in the pause ledger. Never dark with no record.
  4. It is verified -- by a run and its real output, not by reading the plist.

WHY A WRITTEN ROSTER AND NOT A GLOB

  The machine holds 38 job plists today. Globbing LaunchAgents would let the
  denominator drift under the gate, and a roster that quietly shrinks reports a
  clean pass over work that vanished. ASK-151: "a partial pass that reports
  success is the failure mode." The roster is data, in
  q-system/.q-system/config/job-migration-roster.json, and changing it is an edit
  somebody reviews.

WHY THIS DOES NOT RUN ALL 32 JOBS

  26 of the roster are PAUSED ON PURPOSE, pending exactly this migration. ASK-151's
  Not-doing line is binding: no retiring, no un-pausing, no changing what a job
  does. Firing a paused Substack producer or `git push` from inside an audit IS
  un-pausing it for one cycle. So `AUTO_RUN` is False and a run is opt-in per
  label (`run <label>`). Bar 4 is satisfied three ways, and the mode is recorded
  on every receipt so the gate can never launder one into another:

    run            this mechanism executed the job's program and read the output
    scheduler      launchd's own record: loaded, last exit decoded, log non-empty
    paused-ledger  paused on purpose; running it is out of ASK-151's scope. The
                   job is TRACKED (bars 1-3) and explicitly NOT run-verified. The
                   gate counts these out loud and never folds them into green.

WHAT IT ACTUALLY FIXES

  Bar 2 is the one bar with an auto-fix: a roster label under no watched prefix is
  invisible to the watchdog, and the fix is to add its family to the instance-local
  EXTRA_PREFIXES_FILE that launchd-health-check.py already reads. Found live on
  2026-07-29: `com.personal.` was watched by nothing, so com.personal.story-podcast
  could fail or go dark with no ping and no issue.

  Bar 3 has NO auto-fix on purpose. A dark job could be un-paused with one
  `launchctl bootstrap`, and that is the founder's call, not an audit's.

Dry by default. `--apply` writes. Receipts live at ~/.config/kipi/ because
LaunchAgents are machine-local and do not propagate through `kipi update`.

Usage:
  job-migration.py status                 per-job bar table, writes nothing
  job-migration.py migrate [--apply]      fix bar 2, write receipts, print the count
  job-migration.py run <label> [--apply]  run ONE job once, record a `run` receipt
  job-migration.py gate [--expect 32]     exit 0 only if every roster job is migrated
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import plistlib
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
QROOT = HERE.parent.parent
ROSTER_PATH = QROOT / ".q-system" / "config" / "job-migration-roster.json"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
RECEIPTS = Path.home() / ".config" / "kipi" / "job-migration-receipts.json"
EXTRA_PREFIXES_FILE = Path.home() / ".config" / "kipi" / "launchd-watch-prefixes.txt"

# A run is never a side effect of an audit. See the module docstring: 26 of the 32
# are paused on purpose and firing one is un-pausing it, which ASK-151 forbids.
AUTO_RUN = False

RUN_TIMEOUT_SECONDS = 900
OUTPUT_HEAD_CHARS = 2000
# A scheduler log older than this is not evidence the job still works.
SCHEDULER_LOG_MAX_AGE_SECONDS = 14 * 24 * 3600


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the four bars, pure so the test can drive them without a live machine ----


def bar_launchd(label: str, plist_exists: bool, cron_text):
    """Bar 1. `cron_text` is None when `crontab -l` could not be READ, which is not
    the same as an empty crontab and must never be scored as one."""
    if not plist_exists:
        return False, f"no plist at {LAUNCH_AGENTS}/{label}.plist"
    if cron_text is None:
        return False, "crontab unreadable -- cannot prove the job is not also on cron"
    for line in cron_text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped and label in stripped:
            return False, "also scheduled in cron (cron has no keychain, ASK-150)"
    return True, "launchd only"


def missing_prefix(label: str, watched):
    """The watch prefix that would cover `label`, or None if one already does.

    Derived from the label rather than taken from a list, so a family nobody
    anticipated still gets a correct fix. `com.personal.story-podcast` ->
    `com.personal.` -- the family, never the bare label, because
    launchd-health-check globs `<prefix>*.plist` and a whole-label 'prefix' would
    cover exactly one job and go stale the next time that family grows."""
    if any(label.startswith(prefix) for prefix in watched):
        return None
    parts = label.split(".")
    return ".".join(parts[:2]) + "." if len(parts) >= 2 else label


def bar_linear(label: str, watched):
    """Bar 2. Watched by launchd-health-check == its failures become Linear issues."""
    prefix = missing_prefix(label, watched)
    if prefix is None:
        return True, "watched -> failures file launchd-failing / launchd-dark"
    return False, f"no watched prefix covers it; failures reach nobody (add {prefix})"


def bar_state(label: str, status_kind: str, paused: bool):
    """Bar 3. Loaded, or recorded in the pause ledger. Never dark."""
    if status_kind in ("ok", "failing"):
        return True, f"loaded ({status_kind})"
    if status_kind == "not_loaded":
        if paused:
            return True, "not loaded, recorded in the pause ledger"
        return False, "DARK: on disk, not loaded, not in the pause ledger"
    # 'unknown' means launchctl did not answer. Scoring that as a pass is how a
    # gate goes green on a machine it could not actually inspect.
    return False, f"state undetermined ({status_kind})"


def bar_verified(receipt):
    """Bar 4 -> (satisfies_run_verification, mode, detail).

    `paused-ledger` returns False on purpose. It is a legitimate receipt and the
    gate accepts it, but it is NOT run verification and this function refuses to
    say otherwise -- that distinction is the whole reason the mode is recorded."""
    if not receipt:
        return False, "none", "no receipt"
    mode = receipt.get("mode", "none")
    if mode == "paused-ledger":
        return False, mode, receipt.get("reason", "paused on purpose; not run")
    if mode in ("run", "scheduler"):
        exit_code = receipt.get("exit_code")
        if exit_code != 0:
            return False, mode, f"last run exited {exit_code}"
        # exit 0 alone is not proof of correct work -- a job whose script was
        # rsync --delete'd out from under it can still exit 0 through a wrapper,
        # which is the silent-death class this whole migration exists for. The
        # run has to have LEFT something: output on the wire, or a changed file
        # on the paths the plist itself declares. `com.kipi.audit-rotate` is the
        # honest case for the second one: a log rotator that succeeds says
        # nothing and rotates a file.
        if (receipt.get("output_head") or "").strip():
            return True, mode, receipt.get("detail", f"{mode}-verified")
        effect = receipt.get("effect")
        if effect:
            return True, mode, f"silent exit 0, observable effect: {effect}"
        return False, mode, ("ran, exit 0, but printed nothing and changed nothing "
                             "it declares -- not proof of correct work")
    return False, mode, f"unrecognized receipt mode {mode!r}"


def is_runnable(label: str, jobs) -> bool:
    """`run` only accepts a roster label. Anything else is a typo or a job nobody
    reviewed, and this mechanism executes founder automation."""
    return any(job["label"] == label for job in jobs)


# --- live facts ---------------------------------------------------------------


def load_roster(path: Path = ROSTER_PATH) -> dict:
    return json.loads(path.read_text())


def load_receipts() -> dict:
    try:
        return json.loads(RECEIPTS.read_text())
    except (OSError, ValueError):
        return {}


def write_receipts(receipts: dict) -> None:
    RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
    RECEIPTS.write_text(json.dumps(receipts, indent=2, sort_keys=True) + "\n")


def watchdog():
    return _load("launchd_health_check", HERE / "launchd-health-check.py")


def crontab_text():
    """None when `crontab -l` could not be read. Reuses fleet-health-daily.py's
    reader so 'the crontab' has ONE definition in this fleet."""
    try:
        fleet_health = _load("fleet_health_daily", HERE / "fleet-health-daily.py")
        return fleet_health._crontab_text()
    except Exception:  # noqa: BLE001
        return None


def plist_info(label: str) -> dict:
    path = LAUNCH_AGENTS / f"{label}.plist"
    if not path.exists():
        return {}
    try:
        return plistlib.loads(path.read_bytes())
    except Exception:  # noqa: BLE001
        return {}


def declared_paths(info: dict) -> list:
    """The paths a plist itself says the job touches. Used to tell a silent
    success from a silent no-op -- and derived from the plist rather than guessed,
    so this mechanism never has to know what any individual job does (ASK-151's
    Not-doing line)."""
    paths = []
    for key in ("StandardOutPath", "StandardErrorPath", "WorkingDirectory"):
        value = info.get(key)
        if value:
            paths.append(Path(str(value)).expanduser())
    return paths


def path_fingerprint(paths) -> dict:
    """mtime+size per declared path. A missing path records as None so its
    APPEARANCE counts as an effect too."""
    out = {}
    for path in paths:
        try:
            stat = path.stat()
            out[str(path)] = [stat.st_mtime, stat.st_size]
        except OSError:
            out[str(path)] = None
    return out


def describe_effect(before: dict, after: dict):
    """Which declared paths the run changed, as one short string, or None."""
    changed = [key for key in after if before.get(key) != after[key]]
    return ", ".join(sorted(changed)) if changed else None


def scheduler_receipt(label: str, status_kind: str, info: dict):
    """Bar 4 from launchd's own record: the scheduler ran it and it wrote a log.

    Only offered for a LOADED job. A paused job cannot have a fresh run by
    definition, and reading its months-old log as verification would be exactly
    the paper pass ASK-151 calls the failure mode."""
    if status_kind != "ok":
        return None
    log = info.get("StandardOutPath") or info.get("StandardErrorPath")
    if not log:
        return None
    path = Path(str(log)).expanduser()
    try:
        stat = path.stat()
        head = path.read_text(errors="replace")[-OUTPUT_HEAD_CHARS:]
    except OSError:
        return None
    age = time.time() - stat.st_mtime
    if age > SCHEDULER_LOG_MAX_AGE_SECONDS or not head.strip():
        return None
    return {
        "mode": "scheduler",
        "exit_code": 0,
        "output_head": head,
        "detail": f"launchd log {path} written {int(age // 3600)}h ago",
        "recorded_at": _now(),
    }


def collect(jobs, watched, cron, paused, receipts) -> list:
    wd = watchdog()
    rows = []
    for job in jobs:
        label = job["label"]
        info = plist_info(label)
        plist_exists = bool((LAUNCH_AGENTS / f"{label}.plist").exists())
        status_kind, _ = wd.job_status(label) if plist_exists else ("not_loaded", None)

        ok_launchd, d1 = bar_launchd(label, plist_exists, cron)
        ok_linear, d2 = bar_linear(label, watched)
        ok_state, d3 = bar_state(label, status_kind, label in paused)

        receipt = receipts.get(label) or scheduler_receipt(label, status_kind, info)
        run_verified, mode, d4 = bar_verified(receipt)
        rows.append({
            "label": label,
            "status": status_kind,
            "bar_launchd": ok_launchd,
            "bar_linear": ok_linear,
            "bar_state": ok_state,
            "verified": run_verified,
            "verify_mode": mode,
            "receipt": receipt,
            "detail": " | ".join((d1, d2, d3, d4)),
        })
    return rows


# --- the gate -----------------------------------------------------------------


def gate_result(rows, expect: int):
    """(exit_code, lines). Exit 0 only when every roster job clears bars 1-3 AND
    carries a receipt, and the row count equals `expect`.

    A `paused-ledger` receipt clears the gate and is counted separately in the
    breakdown. It never disappears into a total."""
    lines = []
    blocking = []
    for row in rows:
        problems = []
        if not row["bar_launchd"]:
            problems.append("bar1-launchd")
        if not row["bar_linear"]:
            problems.append("bar2-linear")
        if not row["bar_state"]:
            problems.append("bar3-state")
        if row["verify_mode"] == "none":
            problems.append("bar4-no-receipt")
        if problems:
            blocking.append((row["label"], problems, row.get("detail", "")))

    modes = {}
    for row in rows:
        modes[row["verify_mode"]] = modes.get(row["verify_mode"], 0) + 1
    breakdown = ", ".join(f"{count} {mode}" for mode, count in sorted(modes.items()))
    lines.append(f"roster {len(rows)} / expected {expect}")
    lines.append(f"verification modes: {breakdown}")
    # Itemized by mode on purpose. "28 not run-verified" reads as one problem; it
    # is two very different ones -- jobs nobody may run (paused, out of ASK-151's
    # scope) and jobs that ran and proved nothing (silent exit 0). Collapsing them
    # into one number is the partial pass wearing a total.
    unrun = {}
    for row in rows:
        if not row["verified"]:
            unrun[row["verify_mode"]] = unrun.get(row["verify_mode"], 0) + 1
    if unrun:
        detail = ", ".join(f"{count} {mode}" for mode, count in sorted(unrun.items()))
        lines.append(
            f"NOT run-verified: {sum(unrun.values())} ({detail}). These clear bars "
            f"1-3 and carry a receipt. `paused-ledger` = running it is un-pausing, "
            f"out of ASK-151's scope. `run` here = exit 0 with no output and no "
            f"observable effect, which is recorded, not scored as proof.")

    exit_code = 0
    if len(rows) != expect:
        lines.append(f"BLOCK: roster holds {len(rows)} job(s), expected {expect}")
        exit_code = 1
    for label, problems, detail in blocking:
        lines.append(f"BLOCK: {label} -- {', '.join(problems)} :: {detail}")
        exit_code = 1
    if exit_code == 0:
        lines.append(f"OK: {len(rows)}/{expect} roster jobs are on Linear-tracked "
                     f"execution (bars 1-3 green, every job carries a receipt)")
    return exit_code, lines


# --- commands -----------------------------------------------------------------


def add_watch_prefix(prefix: str, apply: bool) -> str:
    """Bar 2's auto-fix. Appends to the instance-local file launchd-health-check.py
    already reads. Never edits WATCHED_PREFIXES: that constant ships fleet-wide via
    `kipi update` and must carry no single machine's job families."""
    if not apply:
        return f"would add watch prefix {prefix} to {EXTRA_PREFIXES_FILE}"
    EXTRA_PREFIXES_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if EXTRA_PREFIXES_FILE.exists():
        existing = EXTRA_PREFIXES_FILE.read_text()
        if not existing.endswith("\n"):
            existing += "\n"
    line = f"{prefix}  # added by job-migration.py (ASK-151) {_now()}\n"
    EXTRA_PREFIXES_FILE.write_text(existing + line)
    return f"added watch prefix {prefix} to {EXTRA_PREFIXES_FILE}"


def cmd_status(args) -> int:
    roster = load_roster()
    wd = watchdog()
    rows = collect(roster["jobs"], wd.load_watched_prefixes(), crontab_text(),
                   wd.load_paused_labels(), load_receipts())
    for row in rows:
        bars = "".join("1" if row[k] else "." for k in
                       ("bar_launchd", "bar_linear", "bar_state"))
        print(f"{row['label']:44s} bars={bars} verify={row['verify_mode']:14s} "
              f"{row['status']}")
        if not all(row[k] for k in ("bar_launchd", "bar_linear", "bar_state")):
            print(f"{'':44s} {row['detail']}")
    code, lines = gate_result(rows, roster["expected_count"])
    print()
    print("\n".join(lines))
    return 0  # status reports; `gate` is the thing that fails


def select(jobs, only):
    """The jobs this pass acts on. `--only` narrows to one label so ASK-151's
    "demonstrated on ONE job end to end ... then the remaining 31 driven by the
    same mechanism" is a real invocation and not a story told about one."""
    if not only:
        return list(jobs), None
    picked = [job for job in jobs if job["label"] == only]
    if not picked:
        return [], f"BLOCK: {only} is not in {ROSTER_PATH.name}"
    return picked, None


def cmd_migrate(args) -> int:
    roster = load_roster()
    jobs, error = select(roster["jobs"], args.only)
    if error:
        print(error, file=sys.stderr)
        return 1
    wd = watchdog()
    watched = list(wd.load_watched_prefixes())
    paused = wd.load_paused_labels()
    receipts = load_receipts()
    cron = crontab_text()

    # Bar 2 first: fixing coverage changes the answer for every job in that family.
    needed = []
    for job in jobs:
        prefix = missing_prefix(job["label"], watched)
        if prefix and prefix not in needed:
            needed.append(prefix)
    for prefix in needed:
        print(add_watch_prefix(prefix, args.apply))
        if args.apply:
            watched.append(prefix)

    rows = collect(jobs, tuple(watched), cron, paused, receipts)

    # Bar 4: record the receipt each job has EARNED. A loaded job gets its
    # scheduler receipt; a paused one gets a paused-ledger receipt naming why it
    # was not run. Neither is invented -- both are what the machine actually shows.
    written = 0
    for row in rows:
        label = row["label"]
        if label in receipts and receipts[label].get("mode") == "run":
            continue  # a real run outranks anything derived
        receipt = row["receipt"]
        if receipt is None and label in paused:
            receipt = {
                "mode": "paused-ledger",
                "reason": ("paused on purpose pending this migration; running it "
                           "would be un-pausing, which ASK-151 puts out of scope"),
                "recorded_at": _now(),
            }
        if receipt is None:
            continue
        if args.apply:
            receipts[label] = receipt
        written += 1
    if args.apply:
        write_receipts(receipts)
        rows = collect(jobs, tuple(watched), cron, paused, receipts)

    verb = "wrote" if args.apply else "would write"
    print(f"{verb} {written} receipt(s) to {RECEIPTS}")
    # A scoped pass is scored against its OWN size, and says so. Scoring one job
    # against expected_count 32 would print a BLOCK that means nothing, and the
    # next reader would learn to skim past BLOCK lines.
    if args.only:
        print(f"scoped pass: {args.only} only. Run without --only for the roster, "
              f"and `gate` for the 32-job assertion.")
    code, lines = gate_result(rows, len(jobs) if args.only
                              else roster["expected_count"])
    print("\n".join(lines))
    if not args.apply:
        print("dry run. --apply to write.")
    return code


def cmd_run(args) -> int:
    roster = load_roster()
    if not is_runnable(args.label, roster["jobs"]):
        print(f"BLOCK: {args.label} is not in {ROSTER_PATH.name}", file=sys.stderr)
        return 1
    info = plist_info(args.label)
    argv = [str(a) for a in (info.get("ProgramArguments") or [])]
    if not argv:
        print(f"BLOCK: {args.label} declares no ProgramArguments", file=sys.stderr)
        return 1
    print(f"running: {shlex.join(argv)}")
    if not args.apply:
        print("dry run. --apply to actually run it.")
        return 0
    started = time.time()
    watched_paths = declared_paths(info)
    before = path_fingerprint(watched_paths)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=args.timeout,
                              cwd=info.get("WorkingDirectory") or None)
        exit_code, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        output = f"timed out after {args.timeout}s\n{exc.stdout or ''}"
    except OSError as exc:
        exit_code = 127
        output = f"could not execute: {exc}"
    effect = describe_effect(before, path_fingerprint(watched_paths))
    receipts = load_receipts()
    receipts[args.label] = {
        "mode": "run",
        "exit_code": exit_code,
        "output_head": output[:OUTPUT_HEAD_CHARS],
        "effect": effect,
        "detail": f"ran by job-migration.py in {int(time.time() - started)}s",
        "recorded_at": _now(),
    }
    write_receipts(receipts)
    print(f"exit={exit_code}  {len(output)} chars of output  "
          f"effect={effect or 'none'}  -> receipt written")
    print(output[:OUTPUT_HEAD_CHARS])
    return 0 if exit_code == 0 else 1


def cmd_gate(args) -> int:
    roster = load_roster()
    wd = watchdog()
    rows = collect(roster["jobs"], wd.load_watched_prefixes(), crontab_text(),
                   wd.load_paused_labels(), load_receipts())
    expect = args.expect if args.expect is not None else roster["expected_count"]
    code, lines = gate_result(rows, expect)
    print("\n".join(lines))
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="per-job bar table; writes nothing")

    migrate = sub.add_parser("migrate", help="fix bar 2, write receipts")
    migrate.add_argument("--apply", action="store_true")
    migrate.add_argument("--only", help="migrate this one roster label")

    run = sub.add_parser("run", help="run ONE roster job once and record a receipt")
    run.add_argument("label")
    run.add_argument("--apply", action="store_true")
    run.add_argument("--timeout", type=int, default=RUN_TIMEOUT_SECONDS)

    gate = sub.add_parser("gate", help="exit 0 only if every roster job is migrated")
    gate.add_argument("--expect", type=int, default=None)

    args = parser.parse_args(argv)
    return {"status": cmd_status, "migrate": cmd_migrate,
            "run": cmd_run, "gate": cmd_gate}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
