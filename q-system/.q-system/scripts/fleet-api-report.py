#!/usr/bin/env python3
"""The daily API-credit report, sent to chief as a priority alert (ASK-4311).

WHY IT GOES TO CHIEF AND NOT TO SLACK OR THE FOUNDER. Founder, 2026-11-09: every
alert for him goes to the chief bot as a priority alert. `slack-notify.sh` is the
ENGINEERING sink -- it files a Linear ticket for Sana and pages nobody
(`founder-notifications.md`) -- which is the wrong door for a report the founder
asked to receive. So this writes through chief's own alert path.

WHAT IT SAYS, and the founder named every line of it:

  - spent today, against today's allowance
  - credit left per key, in each key's own billing cycle
  - a key whose credit is unknown, by name, every day until it is set
  - tickets closed today
  - TICKETS LEFT TO BE DONE, per reachable project ("have the report to chief
    also include How many tickets are left to be done every day")
  - any pause, resume or failover since the last report

WHERE "TICKETS LEFT" COMES FROM. `linear-worker.sh --ready-json`, which is the
picker itself. Not a second query with the same filters: the worker's own file
warns that a second reader of the pick rules drifts from ready(), and a report
that drifts tells the founder a queue nobody is working. If the worker cannot
answer, the line says COULD NOT READ and names why. It never says zero on a
failure, because zero is the one answer that looks like success.

ONE MESSAGE A DAY PLUS ONE PER STATE CHANGE. A receipt under
~/.local/state/kipi/ holds the last digest sent. The daily run sends once; a
state change (a pause, a resume, a failover) sends an extra message immediately
and records it, so a 15-minute job calling this cannot turn one event into 96
alerts.

Usage:
  fleet-api-report.py              # send if due (the daily job's call)
  fleet-api-report.py --dry        # print it, send nothing
  fleet-api-report.py --force      # send regardless of the receipt

Exit 0 whenever the report was produced, sent or not. A reporter that fails the
job it reports on is worse than a late report.

Env:
  KIPI_CHIEF_ALERT     the alert command (default: python3 <chief>/chief/telegram_out.py alert)
  KIPI_CHIEF_ROOT      chief's checkout (default ~/projects/chief)
  KIPI_FLEET_REPORT_RECEIPT  receipt path
  KIPI_WORKER_READY_CMD      override the ready-count command (tests)
  KIPI_FLEET_NOW       epoch seconds; the test clock
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fleet_api_spend as spend  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RECEIPT = os.path.join(
    os.path.expanduser("~"), ".local", "state", "kipi", "fleet-api-report.json")
DEFAULT_CHIEF_ROOT = os.path.join(os.path.expanduser("~"), "projects", "chief")

#: Kinds that earn their own message the moment they happen, not tomorrow.
#:
#: `no_key` IS ONE OF THEM (PR #717 review round 2, finding 1). With nothing in
#: the Keychain every fleet run refuses, spend stays at $0, credit stays whole
#: and no pause is recorded, so the day read EXACTLY like a quiet, cheap day --
#: the fix had to land on the REPORT and not only on the detector. The condition
#: is filed once a budget day by `fleet_api_key.note_missing_key`, so putting it
#: here costs one message, not 96.
#: `unconfirmed` too: a key whose auto-reload is not confirmed off runs nothing,
#: which also reads as a quiet day unless it is said.
STATE_CHANGE_KINDS = ("pause", "resume", "failover", "no_key", "unconfirmed")


def receipt_path():
    return os.environ.get("KIPI_FLEET_REPORT_RECEIPT") or DEFAULT_RECEIPT


def chief_alert_argv():
    raw = os.environ.get("KIPI_CHIEF_ALERT")
    if raw:
        return shlex.split(raw)
    root = os.environ.get("KIPI_CHIEF_ROOT") or DEFAULT_CHIEF_ROOT
    return ["python3", os.path.join(root, "chief", "telegram_out.py"), "alert"]


def ready_counts():
    """(per_project, total, error). Never (anything, 0, None) on a failure."""
    raw_cmd = os.environ.get("KIPI_WORKER_READY_CMD")
    argv = shlex.split(raw_cmd) if raw_cmd else \
        ["bash", os.path.join(HERE, "linear-worker.sh"), "--ready-json"]
    try:
        out = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        return {}, None, "could not run the worker (%s)" % exc
    if out.returncode != 0:
        # NEVER (…, 0, None) ON A FAILURE. Zero reads as a finished queue, which
        # is the one wrong answer that looks like success. Mutation-checked
        # 2026-11-09: returning 0 here turns
        # test_a_failed_ready_read_says_so_and_never_says_zero red.
        tail = (out.stderr or "").strip().splitlines()[-1:] or ["no stderr"]
        return {}, None, "the worker exited %d (%s)" % (out.returncode, tail[0])
    try:
        doc = json.loads(out.stdout or "")
    except ValueError:
        return {}, None, "the worker printed something that is not its pick list"
    if not isinstance(doc, dict) or "ready" not in doc:
        return {}, None, "the worker's output carries no `ready` list"
    if doc.get("infra_error"):
        return {}, None, "Linear unreachable (%s)" % doc["infra_error"]
    per = {}
    for row in doc.get("ready") or []:
        per[row.get("project") or "(no project)"] = \
            per.get(row.get("project") or "(no project)", 0) + 1
    return per, sum(per.values()), None


#: The "tickets closed today" query, as a module constant so a test can read the
#: document the report actually sends rather than a copy of it.
#:
#: TWO DEFECTS LIVED IN ONE LINE (PR #717 review round 1, findings 1 and 4). The
#: document was brace-unbalanced and put `state:` OUTSIDE `filter:`, so Linear
#: rejected every call and the line could only ever say COULD NOT READ -- and no
#: test saw it, because every test stubbed closed_today() whole. And the window
#: started at the budget-day LABEL plus "T00:00:00Z", which in a UTC-8 zone is 15
#: hours before the day it names. Both bounds now come from
#: spend.budget_day_window_utc().
CLOSED_QUERY = (
    "query($after:DateTimeOrDuration!,$before:DateTimeOrDuration!){"
    " issues(filter:{completedAt:{gte:$after,lt:$before}"
    ",state:{type:{eq:\"completed\"}}}){"
    " nodes{ identifier completedAt } } }"
)


def closed_today():
    """(count, error). Issues completed inside the current budget day.

    Every issue the account can see, not one team: the query carries no team
    filter, and claiming otherwise in this docstring would be a scope the code
    does not have.
    """
    try:
        import importlib.util
        # KIPI_LINEAR_SYNC is the test seam, and it is the load path itself
        # rather than a patched function: the shipped document went out broken
        # because no test ever drove the real call. A fake linear-sync.py here
        # records the query the report actually sends.
        path = os.environ.get("KIPI_LINEAR_SYNC") or os.path.join(HERE, "linear-sync.py")
        spec = importlib.util.spec_from_file_location("ls_report", path)
        ls = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ls)
    except Exception as exc:                      # noqa: BLE001 - reporter never raises
        return None, "could not load linear-sync.py (%s)" % exc
    after, before = spend.budget_day_window_utc()
    try:
        doc = ls.graphql(CLOSED_QUERY, {"after": after, "before": before})
    except Exception as exc:                      # noqa: BLE001
        return None, "Linear would not answer (%s)" % exc
    nodes = ((doc or {}).get("issues") or {}).get("nodes") or []
    return len(nodes), None


def build():
    """The report as a dict plus its one-message text."""
    budget = spend.budget()
    credit = spend.credit()
    unmetered = spend.unmetered_today()
    per_project, ready_total, ready_err = ready_counts()
    closed, closed_err = closed_today()
    todays_events = [e for e in spend.events()
                     if e.get("kind") in STATE_CHANGE_KINDS]

    lines = ["FLEET API CREDIT, budget day %s" % budget["day"]]
    lines.append("spent today: $%.2f of $%.2f (remaining $%.2f)"
                 % (budget["spent_usd"], budget["allowance_usd"],
                    budget["remaining_usd"]))
    # One line per key, worded by the same function `credit` prints with. An
    # unknown credit says NOT USED and names the file to fix: the founder reads
    # this message, and a key the fleet silently skips is a key he thinks is
    # carrying half the load.
    for slot in spend.SLOTS:
        lines.append(spend.describe_key(credit, slot))
    # A RUN WAS CHARGED AND NEVER PRICED (review round 2 finding 2, round 3
    # minor 3). Said out loud, because the allowance is divided out of the line
    # above: with unmetered runs in the day, "spent today" is a floor and not a
    # total. No dollar estimate, because there is no honest one: a killed run
    # never printed total_cost_usd, and a run whose output was not the JSON
    # envelope printed none we could read.
    if unmetered:
        lines.append("spend is a FLOOR, not a total: %d run(s) had a cost nobody "
                     "could read (killed by the watchdog, or no cost in their "
                     "output)" % unmetered)
    lines.append("tickets closed today: %s"
                 % (closed if closed_err is None else "COULD NOT READ (%s)" % closed_err))

    if ready_err:
        lines.append("tickets left to be done: COULD NOT READ (%s)" % ready_err)
    else:
        lines.append("tickets left to be done: %d" % ready_total)
        for project, count in sorted(per_project.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append("  %s: %d" % (project, count))

    if todays_events:
        lines.append("state changes today:")
        for ev in todays_events:
            lines.append("  %s: %s" % (ev.get("kind"), ev.get("text")))

    report = {
        "day": budget["day"],
        "budget": budget,
        "credit": credit,
        "ready_total": ready_total,
        "ready_by_project": per_project,
        "ready_error": ready_err,
        "closed_today": closed,
        "closed_error": closed_err,
        "unmetered_runs": unmetered,
        "state_changes": len(todays_events),
        "text": "\n".join(lines),
    }
    return report


def read_receipt():
    try:
        with open(receipt_path(), "r") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_receipt(day, state_changes):
    path = receipt_path()
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"day": day, "state_changes": state_changes}, fh, sort_keys=True)
        return True
    except OSError as exc:
        sys.stderr.write("fleet-api-report: cannot write %s (%s)\n" % (path, exc))
        return False


def due(report):
    """One a day, plus one per state change since the last send.

    Comparing the COUNT, not a flag: a second failover on the same day is a new
    event and earns its own message, while a re-run with nothing new sends
    nothing. A 15-minute caller therefore cannot turn one pause into 96 alerts.
    """
    last = read_receipt()
    if last.get("day") != report["day"]:
        return True, "first report of %s" % report["day"]
    try:
        seen = int(last.get("state_changes") or 0)
    except (TypeError, ValueError):
        seen = 0
    if report["state_changes"] > seen:
        return True, "%d new state change(s)" % (report["state_changes"] - seen)
    return False, "already sent for %s with nothing new" % report["day"]


def send(text):
    argv = chief_alert_argv() + [text]
    try:
        out = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write("fleet-api-report: chief alert path failed (%s)\n" % exc)
        return False
    if out.returncode != 0:
        sys.stderr.write("fleet-api-report: chief alert exited %d: %s\n"
                         % (out.returncode, (out.stderr or "").strip()[:200]))
        return False
    return True


def main(argv):
    ap = argparse.ArgumentParser(prog="fleet-api-report.py", description=__doc__)
    ap.add_argument("--dry", action="store_true", help="print it, send nothing")
    ap.add_argument("--force", action="store_true", help="send regardless of the receipt")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)

    report = build()
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(report["text"])

    if args.dry:
        return 0

    is_due, why = due(report)
    if not is_due and not args.force:
        sys.stderr.write("fleet-api-report: not sending (%s)\n" % why)
        return 0

    if send(report["text"]):
        write_receipt(report["day"], report["state_changes"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
