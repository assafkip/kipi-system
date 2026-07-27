#!/usr/bin/env python3
"""File one Linear issue per scheduled job, to migrate it onto Linear-tracked execution.

WHY EACH JOB NEEDS AN ISSUE

Founder, 2026-07-26: the 26 paused com.cole.* jobs "are coming back... I only
paused for now until we move them and make sure they do the correct work." That
is a two-part bar per job -- migrated AND verified -- and a bar with 34 subjects
needs 34 records, not one heroic sweep. Enumerated 2026-07-26: 34 job plists on
disk, 8 loaded, 26 paused, plus whatever crontab holds.

WHY THE DoR IS BAKED IN AT CREATION

linear-dor-drafter.py fills DoRs in nightly at 8/night, so a fresh batch of 34
would take a month to become workable. These are all the SAME shape of task, so
their DoR is knowable up front and is written at creation. The worker can start
on them the same night.

WHAT "MIGRATED" MEANS, and it is the same four things for every job:
  1. It runs under launchd, never cron (ASK-150: cron has no keychain, so any
     job that shells `claude` fails auth there).
  2. Its failures and findings reach LINEAR, not just a log file. A log nobody
     opens is where work goes to hang.
  3. It is in the paused ledger or it is live -- never dark with no record.
  4. It is verified to still do correct work, by running it once and reading
     the output. "It is scheduled" is not "it works".

Dry by default; --apply files. Deduped on `job-migration/<label>`, so re-running
is a no-op and this is safe to run after adding a new job.
"""

from __future__ import annotations

import argparse
import importlib.util
import plistlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
TEAM_KEY = "ASK"
PROJECT = "kipi-system"


def _linear():
    spec = importlib.util.spec_from_file_location("ls", HERE / "linear-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _paused() -> set:
    spec = importlib.util.spec_from_file_location("wd", HERE / "launchd-health-check.py")
    wd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wd)
    return wd.load_paused_labels()


def _loaded() -> set:
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return {l.split("\t")[2].strip() for l in out.splitlines()[1:] if len(l.split("\t")) >= 3}


def _schedule(info: dict) -> str:
    if "StartInterval" in info:
        return f"every {info['StartInterval']}s"
    cal = info.get("StartCalendarInterval")
    if isinstance(cal, dict):
        cal = [cal]
    if isinstance(cal, list):
        parts = []
        for c in cal:
            wd = c.get("Weekday")
            parts.append(f"{c.get('Hour', 0):02d}:{c.get('Minute', 0):02d}"
                         + (f" (weekday {wd})" if wd is not None else " daily"))
        return ", ".join(parts)
    return "on demand / at load"


def inventory() -> list:
    paused, loaded = _paused(), _loaded()
    jobs = []
    for plist in sorted(LAUNCH_AGENTS.glob("*.plist")):
        label = plist.stem
        if not label.startswith(("com.kipi.", "com.cole.", "com.ask.", "com.assaf.",
                                 "com.claudedaddy.", "com.purespectrum.", "com.personal.")):
            continue
        try:
            info = plistlib.loads(plist.read_bytes())
        except Exception:  # noqa: BLE001
            info = {}
        argv = info.get("ProgramArguments") or []
        state = "loaded" if label in loaded else ("paused" if label in paused else "DARK")
        jobs.append({
            "label": label,
            "state": state,
            "schedule": _schedule(info),
            "program": " ".join(str(a) for a in argv)[:300],
            "owner": ("cole" if label.startswith("com.cole.") else
                      "kipi" if label.startswith("com.kipi.") else "other"),
        })
    return jobs


def build_issue(job: dict) -> dict:
    label = job["label"]
    key = f"job-migration/{label.replace('.', '-')}"
    state_note = {
        "paused": ("Currently **paused** on purpose (in the pause ledger). It is coming "
                   "back — the founder paused it pending exactly this migration."),
        "loaded": "Currently **loaded and running**. Migrating must not interrupt it.",
        "DARK": ("Currently **dark**: on disk, not loaded, and NOT in the pause ledger. "
                 "Nothing recorded a decision to stop it."),
    }[job["state"]]

    body = f"""<!-- kipi-key: {key} -->

Migrate `{label}` onto Linear-tracked execution.

| Field | Value |
| -- | -- |
| State | {job['state']} |
| Schedule | {job['schedule']} |
| Runs | `{job['program']}` |

{state_note}

## Definition of Ready

- **Outcome:** `{label}` runs under launchd on a known schedule, its failures and
  findings arrive as Linear issues rather than dying in a log, its state is
  recorded (live or in the pause ledger), and it has been run once and observed
  to do correct work.
- **Files:** `~/Library/LaunchAgents/{label}.plist`, and the script it invokes
  (see the Runs row above). No skeleton file changes for the migration itself.
- **Check:** run the job's script once by hand and read the output. Then confirm
  it is visible to the watchdog:
  ```bash
  python3 q-system/.q-system/scripts/launchd-health-check.py --dry-run | grep {label}
  ./kipi health
  ```
  A pass means: the job produced real output, and it shows as loaded or
  explicitly paused — never DARK.
- **Blast radius:** machine-local. LaunchAgents and crontab do not propagate via
  `kipi update`. If the job writes into a synced path, say so here.
- **Not doing:** rewriting what the job does. This is a migration of how it is
  scheduled, reported and verified — not a rewrite of its logic. If the job turns
  out to be obsolete, say so on this issue and stop; retiring it is a founder call.

**Energy:** Admin · **Time Est:** 20-40 min

## The four bars (same for every job)

1. launchd, never cron — cron has no keychain, so anything shelling `claude`
   fails auth there (ASK-150).
2. Failures and findings reach Linear, not only a log.
3. Live or in the pause ledger. Never dark with no record.
4. Verified by running it, not by reading it.
"""
    return {"key": key, "title": f"Migrate {label} to Linear-tracked execution",
            "body": body}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--owner", choices=("cole", "kipi", "other"), help="only this family")
    args = ap.parse_args()

    jobs = inventory()
    if args.owner:
        jobs = [j for j in jobs if j["owner"] == args.owner]

    ls = _linear()
    try:
        team_id, project, remote = ls.fetch_remote_state(TEAM_KEY, PROJECT)
    except Exception as exc:  # noqa: BLE001
        print(f"BLOCK: linear unreachable: {exc}", file=sys.stderr)
        return 1
    known = set(ls.read_ledger()) | set(remote)

    by_state = {}
    for j in jobs:
        by_state[j["state"]] = by_state.get(j["state"], 0) + 1
    print(f"{len(jobs)} job(s): " + ", ".join(f"{v} {k}" for k, v in sorted(by_state.items())))

    made = skipped = 0
    for job in jobs:
        issue = build_issue(job)
        if issue["key"] in known:
            skipped += 1
            continue
        if not args.apply:
            print(f"  would file: {issue['title']}")
            made += 1
            continue
        payload = {"title": issue["title"][:250], "description": issue["body"],
                   "teamId": team_id}
        if project:
            payload["projectId"] = project["id"]
        data = ls.graphql(ls.ISSUE_CREATE, {"input": payload})
        node = (data.get("issueCreate") or {}).get("issue") or {}
        if not node.get("id"):
            print(f"BLOCK: create returned nothing for {issue['key']}", file=sys.stderr)
            return 1
        ls.append_ledger([{"key": issue["key"], "kind": "issue",
                           "linear_id": node["id"], "identifier": node.get("identifier"),
                           "source": "job-migration"}])
        made += 1
        print(f"  {node.get('identifier')}  {issue['title'][:66]}")

    print(f"{'filed' if args.apply else 'would file'} {made}, already tracked {skipped}")
    if not args.apply:
        print("dry run. --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
