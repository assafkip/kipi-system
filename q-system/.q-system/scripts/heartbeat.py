#!/usr/bin/env python3
"""heartbeat.py -- every consumer reports in and done; a reader off this Mac checks it (ASK-3947).

WHY THIS EXISTS. Every watcher the fleet had ran on the same Mac, under the same
launchd, and was read by the same queue. Three scars:

  * The needs-triage promoter wrote 0 decisions on 16 nights running
    (2026-10-23 to 2026-11-07, "0 written, 0 skipped, 8 failed" every night)
    while its queue grew from 701 to 1269. The only record was its own .out file.
  * ASK-1146 (#281) defined liveness as "the job RAN". launchd-health-check.py saw
    a job exit 0 having done nothing, and called it alive.
  * linear-dor's failure reason said "63 chars of output" for 98 days. It was the
    weekly usage limit (measured 2026-11-07), and two diagnoses guessed login.

So a row carries what came IN and what got DONE, not "it ran". And the reader runs
on GitHub's runners, so a Mac that is off, a launchd that never fires, or a queue
nobody drains still raises an alarm.

WHO REPORTS. Only the consumers listed in q-system/.q-system/heartbeat-jobs.json,
each one calling `emit`. Today that is linear-dor alone (ASK-3947). The others,
the alert triage among them, are wired one by one (follow-up ticket), and a
listed job that never reports is itself a `missing` alarm.

TWO HALVES, ONE FILE, so the row's shape has exactly one definition:

  emit   (Mac)     append the row to <state>/<job>.jsonl and publish the latest row
                   to the repo variable KIPI_HB_<JOB>. One variable per job, so each
                   variable has one writer: the job itself.
  check  (GitHub)  .github/workflows/heartbeat.yml reads every KIPI_HB_* variable,
                   compares it with q-system/.q-system/heartbeat-jobs.json, and opens
                   or closes one `heartbeat-red` issue per (job, kind).
                   fleet-health-daily.py mirrors open `heartbeat-red` issues into
                   Linear, the same route `gates-red` already uses, so the alarm has
                   a machine reader (RULE-2026-11-06-B).

The kinds:
  missing     no row for more than 2 periods (or never, 2 periods after `since`)
  starved     done = 0 while work waited (in > 0, queue > 0, or the run errored),
              on 2 runs in a row
  unreadable  a KIPI_HB_* value that is not a row
  unlisted    a row for a job heartbeat-jobs.json does not list, so nobody checks it

`emit` never raises and always exits 0. A consumer must not die because GitHub was
unreachable, and a row that could not be published reads as `missing` from outside,
which is the true state as seen from outside.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
# parents[2] of q-system/.q-system/scripts is the repo root. A copy loaded from a
# shallow temp dir has fewer parents: the test's mutants live in /tmp/<dir> on the
# Linux runner, and an import-time IndexError there turned validate red on PR #631
# while macOS's deep /var/folders temp dir hid it. Fall back to HERE, never raise.
REPO_ROOT = HERE.parents[2] if len(HERE.parents) > 2 else HERE
JOBS_FILE = REPO_ROOT / "q-system" / ".q-system" / "heartbeat-jobs.json"
WORKFLOW = Path(".github") / "workflows" / "heartbeat.yml"
VAR_PREFIX = "KIPI_HB_"
LABEL = "heartbeat-red"
TITLE_PREFIX = f"{LABEL}: "
STARVED_RUNS = 2
MISSING_PERIODS = 2
JOB_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")

# launchd hands a job a PATH without Homebrew's bin, and gh lives there. Same list,
# same reason, as fleet-health-daily.py's GH_DIRS (#484 review).
GH_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(text: str) -> datetime:
    text = text.strip()
    if len(text) == 10:  # a bare date, as `since` is written
        text += "T00:00:00Z"
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def var_name(job: str) -> str:
    return VAR_PREFIX + job.upper().replace("-", "_")


def default_state_dir() -> Path:
    return Path(os.environ.get("KIPI_HEARTBEAT_DIR")
                or Path.home() / ".config" / "kipi" / "heartbeat")


def find_gh() -> str | None:
    """KIPI_HEARTBEAT_GH first (tests point it at a fake), then PATH, then GH_DIRS."""
    override = os.environ.get("KIPI_HEARTBEAT_GH")
    if override:
        return override
    dirs = [os.environ.get("PATH", "")] + list(GH_DIRS)
    return shutil.which("gh", path=os.pathsep.join(d for d in dirs if d))


def _last_row(path: Path) -> dict | None:
    try:
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    except OSError:
        return None
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            return row
    return None


# The reason classes a row may carry. A closed list, not a sanitizer: the value
# reaches a public repo's variable and a public issue body, and a sanitizer that
# keeps any 40 alphanumerics of caller text still publishes caller text
# ("Linear <b>down</b> token=abc" came out as "linearbdownbtokenabc", PR #631 R1).
ERROR_CLASSES = ("linear-unreachable",)


def is_starved(n_in: int, n_done: int, error: str | None, queue: int | None = None) -> bool:
    # Work waited if the run took some on, if some is still queued, or if the run
    # errored before it could count. Counting only in > 0 read a night that drafted
    # nothing with 32 issues queued as green (PR #631 R1, major), and counting only
    # in and queue would let "Linear unreachable at start" read as a quiet night.
    return n_done == 0 and (n_in > 0 or (queue or 0) > 0 or bool(error))


def emit(job: str, n_in: int, n_done: int, queue: int | None = None,
         error: str | None = None, state_dir: Path | None = None,
         repo_root: Path | None = None, publish: bool = True,
         run=subprocess.run, now: datetime | None = None) -> dict:
    """Record one run. Returns {"row": ..., "published": "<status>"}. Never raises."""
    try:
        return _emit(job, n_in, n_done, queue, error, state_dir, repo_root,
                     publish, run, now)
    except Exception as exc:  # noqa: BLE001 - a heartbeat must never kill its consumer
        print(f"heartbeat: emit for {job!r} failed ({type(exc).__name__}); "
              "the outside checker will read this job as missing", file=sys.stderr)
        return {"row": None, "published": f"error {type(exc).__name__}"}


def _emit(job, n_in, n_done, queue, error, state_dir, repo_root, publish, run, now):
    if not JOB_RE.match(job):
        raise ValueError(f"bad job name {job!r}")
    state = Path(state_dir) if state_dir else default_state_dir()
    state.mkdir(parents=True, exist_ok=True)
    ledger = state / f"{job}.jsonl"
    prev = _last_row(ledger) or {}
    # COERCED ONCE, BEFORE THE DECISION (PR #631 round 2, minor 1). A producer that
    # passes "32" must neither kill the emit nor publish a row whose queue
    # disagrees with the starved decision taken on it. Unreadable reads as unknown.
    try:
        queue = None if queue is None else int(queue)
    except (TypeError, ValueError):
        queue = None
    starved = is_starved(int(n_in), int(n_done), error, queue)
    streak = int(prev.get("starved_streak") or 0) + 1 if starved else 0
    row = {"job": job, "at": _iso(now or _now()), "in": int(n_in), "done": int(n_done),
           "queue": None if queue is None else int(queue), "starved_streak": streak}
    if error:
        # One of ERROR_CLASSES or "other", never caller text (ASK-204).
        row["error"] = error if error in ERROR_CLASSES else "other"
    # One writer per ledger: the consumer itself, and launchd runs one instance of
    # a job at a time. Append-only, so a crash mid-run loses one row, never history.
    with ledger.open("a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    status = _publish(row, Path(repo_root) if repo_root else REPO_ROOT, run) if publish \
        else "not asked"
    return {"row": row, "published": status}


def _publish(row: dict, root: Path, run) -> str:
    # Only the repo that carries the reader publishes. An instance copy of this
    # script (kipi update ships it everywhere) would otherwise write variables into
    # a repo where nothing reads them.
    if not (root / WORKFLOW).is_file():
        return "skipped: no heartbeat workflow in this repo"
    gh = find_gh()
    if not gh:
        print("heartbeat: gh not found; the outside checker will read "
              f"{row['job']} as missing", file=sys.stderr)
        return "failed: gh not found"
    try:
        proc = run([gh, "variable", "set", var_name(row["job"]),
                    "--body", json.dumps(row, sort_keys=True)],
                   capture_output=True, text=True, timeout=30, cwd=str(root))
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"heartbeat: publish failed ({type(exc).__name__}); the outside "
              f"checker will read {row['job']} as missing", file=sys.stderr)
        return f"failed: {type(exc).__name__}"
    if proc.returncode != 0:
        print(f"heartbeat: gh variable set exited {proc.returncode}; the outside "
              f"checker will read {row['job']} as missing", file=sys.stderr)
        return f"failed: exit {proc.returncode}"
    return "published"


# --- the reader (runs on GitHub) ---------------------------------------------

def rows_from_vars(variables: dict) -> tuple[dict, list]:
    """{job: row} from KIPI_HB_* values, plus `unreadable` violations.

    Every other variable is ignored and never printed: toJSON(vars) hands this
    script the whole set, and this is a public repo's workflow log.
    """
    rows, bad = {}, []
    for name in sorted(variables or {}):
        if not name.startswith(VAR_PREFIX):
            continue
        try:
            row = json.loads(variables[name])
            if not isinstance(row, dict) or not JOB_RE.match(str(row.get("job", ""))):
                raise ValueError("not a row")
            _parse_time(str(row["at"]))
        except (ValueError, KeyError, TypeError):
            bad.append({"job": name, "kind": "unreadable",
                        "detail": f"{name} does not hold a heartbeat row"})
            continue
        rows[row["job"]] = row
    return rows, bad


def evaluate(rows: dict, table: dict, now: datetime) -> list:
    """The violations, in a stable order. Pure: no I/O, so the test owns every input."""
    out = []
    jobs = (table or {}).get("jobs") or {}
    for job in sorted(jobs):
        period = timedelta(hours=float(jobs[job]["period_hours"]))
        limit = MISSING_PERIODS * period
        row = rows.get(job)
        if row is None:
            since = _parse_time(str(jobs[job]["since"]))
            if now - since > limit:
                out.append({"job": job, "kind": "missing",
                            "detail": f"no report ever, listed since {jobs[job]['since']}"})
            continue
        age = now - _parse_time(str(row["at"]))
        if age > limit:
            out.append({"job": job, "kind": "missing",
                        "detail": (f"last report {row['at']}, {age.total_seconds() / 3600:.0f}h ago; "
                                   f"period {period.total_seconds() / 3600:.0f}h")})
        streak = int(row.get("starved_streak") or 0)
        if streak >= STARVED_RUNS:
            out.append({"job": job, "kind": "starved",
                        "detail": (f"done 0 on {streak} runs in a row; last run in "
                                   f"{row.get('in')}, queue {row.get('queue')}"
                                   + (f", error {row['error']}" if row.get("error") else ""))})
    for job in sorted(set(rows) - set(jobs)):
        out.append({"job": job, "kind": "unlisted",
                    "detail": f"{var_name(job)} has a row, and heartbeat-jobs.json does not list {job}"})
    return out


def issue_title(v: dict) -> str:
    return f"{TITLE_PREFIX}{v['job']} {v['kind']}"


def issue_body(v: dict, table: dict) -> str:
    spec = (table.get("jobs") or {}).get(v["job"]) or {}
    producer = spec.get("producer", "(not listed)")
    label = spec.get("launchd") or f"com.kipi.{v['job']}"
    what = {
        "missing": "The job did not report. It did not run, or it ran and could not publish.",
        "starved": "The job ran and did nothing while work was waiting.",
        "unreadable": "A heartbeat variable holds something that is not a row.",
        "unlisted": "A job reports, and nothing checks it.",
    }[v["kind"]]
    action = {
        # A STALE INSTALLED PLIST IS A MISSING CAUSE (PR #643 round 1). install-plist.sh
        # --missing never rewrites an installed job, so a plist installed before its
        # --heartbeat flag runs green on the Mac and reads missing here, and launchctl
        # and the .out log both show a healthy job. The Action names the reinstall.
        # THE DIFF IS AGAINST A RENDERED COPY, NOT THE RAW TEMPLATE (ASK-3987, PR #643
        # round 2): a healthy pinned install differs from the raw template on 13
        # lines, so the one that matters, `--heartbeat` in the argv, was lost in the
        # noise. --render-only writes the plist install-plist.sh would install and
        # touches no live job; fleet-health plist drift compares the same render,
        # structurally. The Action compares ProgramArguments, because a raw diff of
        # the two files is 19 of 21 lines comment noise (PR #652 round 1).
        "missing": (f"Run `launchctl print gui/$(id -u)/{label}` on the Mac and read "
                    "its last exit, then the job's log under `~/.config/kipi/`. If it ran and "
                    f"exited 0, the installed `~/Library/LaunchAgents/{label}.plist` may predate "
                    "`--heartbeat`: from the primary checkout `~/projects/kipi-system` (a worktree "
                    "renders its own paths), render what would be installed with "
                    f"`bash q-system/.q-system/scripts/install-plist.sh {label} --render-only /tmp/{label}.plist`, "
                    "then compare the two argv, where `--heartbeat` lives: "
                    f"`plutil -extract ProgramArguments json -o - ~/Library/LaunchAgents/{label}.plist` "
                    f"against the same on `/tmp/{label}.plist` (a raw diff is mostly comment noise). "
                    f"Reinstall with `bash q-system/.q-system/scripts/install-plist.sh {label}`. "
                    f"Producer: `{producer}`."),
        "starved": (f"Read the failure lines of the job's last two runs in `~/.config/kipi/{v['job']}.out` "
                    f"and `.err`, and fix the cause. Producer: `{producer}`."),
        "unreadable": "Re-run the producer once; its next `heartbeat.py emit` overwrites the variable.",
        "unlisted": "Add the job to `q-system/.q-system/heartbeat-jobs.json` with its period and producer.",
    }[v["kind"]]
    return (f"{what}\n\n{v['detail']}\n\nOpened by `.github/workflows/heartbeat.yml` "
            "(`heartbeat.py check`, ASK-3947). The next run where this job is green closes it.\n\n"
            f"## Definition of Ready\n- **Outcome:** `{v['job']}` reports again with done > 0 "
            "when work is waiting.\n"
            f"- **Check:** this issue closes on the next heartbeat run.\n\n## Action\n{action}")


def file_issues(violations: list, table: dict, run=subprocess.run, now: datetime | None = None) -> int:
    """Open one issue per (job, kind) not already open; close open ones that went green.

    Returns 0, or 1 if gh failed. A check that could not file must not pass: the
    workflow goes red, and a red scheduled run emails the repo owner off this Mac.
    """
    gh = find_gh() or "gh"
    when = _iso(now or _now())
    try:
        proc = run([gh, "issue", "list", "--label", LABEL, "--state", "open",
                    "--limit", "100", "--json", "number,title"],
                   capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            print(f"heartbeat: gh issue list exited {proc.returncode}", file=sys.stderr)
            return 1
        open_issues = {i["title"]: i["number"] for i in json.loads(proc.stdout or "[]")}
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"heartbeat: could not read open {LABEL} issues ({type(exc).__name__})",
              file=sys.stderr)
        return 1
    rc = 0
    wanted = {issue_title(v): v for v in violations}
    for title, v in wanted.items():
        if title in open_issues:
            print(f"still red: {title} (#{open_issues[title]})")
            continue
        p = run([gh, "issue", "create", "--title", title, "--label", LABEL,
                 "--body", issue_body(v, table)], capture_output=True, text=True, timeout=60)
        print(f"opened: {title}" if p.returncode == 0 else f"FAILED to open: {title}")
        rc = rc or (0 if p.returncode == 0 else 1)
    for title, number in sorted(open_issues.items()):
        if not title.startswith(TITLE_PREFIX) or title in wanted:
            continue
        p = run([gh, "issue", "close", str(number), "--comment", f"Green again at {when}."],
                capture_output=True, text=True, timeout=60)
        print(f"closed: {title} (#{number})" if p.returncode == 0 else f"FAILED to close: #{number}")
        rc = rc or (0 if p.returncode == 0 else 1)
    return rc


def load_table(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("emit", help="record one run (the Mac side)")
    e.add_argument("--job", required=True)
    e.add_argument("--in", dest="n_in", type=int, required=True)
    e.add_argument("--done", type=int, required=True)
    e.add_argument("--queue", type=int)
    e.add_argument("--error")
    e.add_argument("--state-dir")
    e.add_argument("--no-publish", action="store_true")
    c = sub.add_parser("check", help="read the published rows (the GitHub side)")
    c.add_argument("--vars-env", default="KIPI_HB_VARS",
                   help="env var holding toJSON(vars) (default KIPI_HB_VARS)")
    c.add_argument("--jobs", default=str(JOBS_FILE))
    c.add_argument("--now")
    c.add_argument("--file-issues", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "emit":
        res = emit(args.job, args.n_in, args.done, args.queue, args.error,
                   Path(args.state_dir) if args.state_dir else None,
                   publish=not args.no_publish)
        print(f"heartbeat {args.job}: in {args.n_in}, done {args.done}, {res['published']}")
        return 0

    table = load_table(Path(args.jobs))
    try:
        variables = json.loads(os.environ.get(args.vars_env) or "{}")
    except ValueError:
        print(f"heartbeat: ${args.vars_env} is not JSON", file=sys.stderr)
        return 1
    now = _parse_time(args.now) if args.now else _now()
    rows, bad = rows_from_vars(variables)
    violations = bad + evaluate(rows, table, now)
    print(f"heartbeat check {_iso(now)}: {len(rows)} row(s), "
          f"{len((table.get('jobs') or {}))} listed job(s), {len(violations)} violation(s)")
    for v in violations:
        print(f"  {issue_title(v)}: {v['detail']}")
    if args.file_issues:
        return file_issues(violations, table, now=now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
