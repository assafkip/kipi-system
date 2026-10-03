"""The model gate: one admission check in front of every headless model call.

why (RCA token-waste-loops-capped-per-path, 2026-10-02). One automation day spent
most of a week's subscription usage: fleet spend in the usage ledger went from
under $18 a day to $582.76, and PR reviews ran 4 to 7 rounds each. Every cap
that existed was LOCAL to one path (converge rounds, redrive per head sha,
dispatch per day), so any caller that reached the model another way passed all
of them. This module is the cap at the choke point instead of on the path.

Three limits, all read here and nowhere else:
  * a daily budget per job (the usage ledger's `bot`), in USD the CLI reported
  * a fleet daily ceiling over every row of the day
  * a round cap per work item (PR number, issue id), keyed on the ITEM. The
    redrive cap was keyed on the head sha and every fix commit reset it; that
    is how one PR took 16 rounds.

Spend is MEASURED, never estimated: it is summed from `usage_ledger` rows, the
meter `--output-format json` already feeds. This module never writes spend.
It is the SINGLE WRITER of its own ledger (`model-gate.jsonl`, beside the usage
ledger), and every read-decide-append happens under one exclusive lock, so two
concurrent callers cannot both take the last round.

Over a limit: in `enforce` mode the call is refused; in `report` mode it is
admitted and logged as a would-refuse. Either way ONE alert per (job, limit,
UTC day) goes to slack-notify.sh, which files it in Sana's queue. A gate that
cannot read its own ledger fails CLOSED in enforce mode and alerts once.

REPORT-ONLY UNTIL ENFORCE_FROM. A wrong default budget must not darken live bots
on the day it ships, so the default mode is `report` until that date and
`enforce` after it. The flip is a constant, not a calendar reminder.

CLI (the shell door, q-system/.q-system/scripts/model-gate.sh, calls these):
  python3 -m voiceloop.model_gate check --job J [--item K]   exit 0 admit, 3 refuse
  python3 -m voiceloop.model_gate record --job J --stdout-file F [--exit N]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fcntl
import json
import os
import re
import subprocess
import sys

from . import usage_ledger

LEDGER_ENV = "KIPI_MODEL_GATE_LEDGER"
MODE_ENV = "KIPI_MODEL_GATE_MODE"
NOTIFY_ENV = "KIPI_MODEL_GATE_NOTIFY"
JOB_USD_ENV = "KIPI_MODEL_GATE_JOB_USD"
FLEET_USD_ENV = "KIPI_MODEL_GATE_FLEET_USD"
ROUNDS_ENV = "KIPI_MODEL_GATE_ROUNDS"
PER_JOB_PREFIX = "KIPI_MODEL_GATE_USD_"

#: The first UTC day the default mode is `enforce` (7 days of report-only).
ENFORCE_FROM = "2026-10-09"
#: Measured 2026-09-23..10-01 from the usage ledger: the highest normal bot day
#: was $14.11 and the highest normal fleet day $17.99. The days this exists for
#: were $99.42 and $582.76, so the ceiling sits BELOW the first of them: $100
#: admitted an exact repeat of it (PR #502 review).
DEFAULT_JOB_USD = 25.0
DEFAULT_FLEET_USD = 75.0
#: Same number as the reviewer's own per-PR cap (PR #501).
DEFAULT_ROUNDS = 3
#: What a call with no settled cost is charged: one still in flight, a timeout,
#: an unmetered provider. Reading those as $0 is how a bot stuck in a timeout
#: loop, or N calls admitted in parallel, would never trip its budget (PRD
#: review finding 1 and 3).
UNSETTLED_USD_ENV = "KIPI_MODEL_GATE_UNSETTLED_USD"
DEFAULT_UNSETTLED_USD = 1.0
#: Rows KNOWN to have cost nothing: the binary was never started, or a provider
#: that reports no usage by design. Charging them the estimate locked a job out
#: after 25 free calls and filed a ticket claiming $25 spent (PR #504 review).
#: EXACT subtypes, never a prefix: "unmetered:" also matched cli:no-json-flag, a
#: real billed call whose cost is only unknown, and pinned a job at $0.00 after 40
#: calls (PR #504 review round 2).
_FREE_SUBTYPES = frozenset({"failed:no-binary", "unmetered:opencode", "failed:opencode"})
#: The OpenCode branch's exception rows, `failed:opencode:<ExceptionName>`. That
#: branch never starts claude, so none of its three row shapes is claude spend;
#: listing only the success row charged 25 empty OpenCode runs $25 at $0 real
#: spend (PR #504 review round 3). The colon keeps it to that producer's rows.
_FREE_PREFIX = "failed:opencode:"
#: The round cap counts calls on one item over this many UTC days. A cap with no
#: window refuses a long-lived item (ASK-45) forever after its 3rd call (PR #503
#: review); a day window, unlike the old per-sha key, cannot be reset by a commit.
ROUND_DAYS_ENV = "KIPI_MODEL_GATE_ROUND_DAYS"
DEFAULT_ROUND_DAYS = 7
SCHEMA = 1
PRODUCER = "voiceloop.model_gate"
ALERT_RETRIES = 3
REFUSED_EXIT = 3
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_NOTIFY = os.path.normpath(os.path.join(
    _HERE, "..", "..", "..", "q-system", ".q-system", "scripts", "slack-notify.sh"))


class GateError(RuntimeError):
    pass


def ledger_path() -> str:
    """The gate ledger lives BESIDE the usage ledger unless named.

    So a test (or a job) that points the meter at a temp file moves the gate with
    it: a test that isolates one and leaks the other is how the live usage ledger
    collected 125 rows from a suite on 2026-09-22.
    """
    explicit = os.environ.get(LEDGER_ENV)
    if explicit:
        return explicit
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(usage_ledger.LEDGER_ENV):
        raise GateError("model_gate: refusing the live gate ledger from inside a test; "
                        f"set {LEDGER_ENV} or {usage_ledger.LEDGER_ENV}")
    return os.path.join(os.path.dirname(usage_ledger.ledger_path()), "model-gate.jsonl")


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def mode(now: _dt.datetime | None = None) -> str:
    val = (os.environ.get(MODE_ENV) or "").strip().lower()
    if val in ("report", "enforce"):
        return val
    # An unknown value falls to the date default, never to report: a typo must
    # not quietly switch the gate off after the flip.
    return "enforce" if (now or _now()).strftime("%Y-%m-%d") >= ENFORCE_FROM else "report"


def _env_number(name: str, default: float) -> float:
    try:
        val = float(os.environ.get(name, ""))
        return val if val >= 0 else default
    except ValueError:
        return default


def job_budget(job: str) -> float:
    key = PER_JOB_PREFIX + re.sub(r"[^A-Z0-9]", "_", job.upper())
    if key in os.environ:
        return _env_number(key, _env_number(JOB_USD_ENV, DEFAULT_JOB_USD))
    return _env_number(JOB_USD_ENV, DEFAULT_JOB_USD)


def spend(day: str, gate_rows: list[dict] = ()) -> tuple[dict, float]:
    """({bot: usd}, fleet_usd) for one UTC day, from the usage ledger only.

    A usage row with no cost is charged the unsettled estimate, and so is every
    admitted gate call not yet settled (admitted calls today minus `settle` rows
    today, per job): the cost of a call lands only when it finishes, and the gate
    must not admit the tenth parallel call on the same pre-call total.

    Settlement is the gate's OWN row, written by the gated caller when its call
    returns. It used to be the count of usage rows for the bot, and any row the bot
    wrote on another path cancelled one in-flight charge each: 120 parallel calls
    passed a $25 budget (PR #503 review round 2). A call that crashes before it
    settles stays charged for its day, which is the safe direction.
    """
    est = _env_number(UNSETTLED_USD_ENV, DEFAULT_UNSETTLED_USD)
    per: dict[str, float] = {}
    settled: dict[str, int] = {}
    for row in usage_ledger.read():
        if not str(row.get("ts") or "").startswith(day):
            continue
        bot = str(row.get("bot"))
        cost = row.get("total_cost_usd")
        ok = isinstance(cost, (int, float)) and not isinstance(cost, bool)
        subtype = str(row.get("subtype") or "")
        # A non-zero exit with no result document and no tokens shows no spend at
        # all: the CLI died before the model ran (bad auth, bad flag). Charging it
        # the estimate let 75 instant failures refuse the whole fleet (PR #503 round
        # 3). A timeout keeps the estimate: it burns tokens and prints nothing. 124
        # and 137 are what a CALLER's own `timeout` wrapper (or a KILL) exits with;
        # model-gate.sh sets no timeout and the gate never bounds call duration.
        # Round 4 found such a timeout loop through the door read as $0.
        instant_fail = (subtype.startswith("failed:exit ")
                        and subtype not in ("failed:exit 124", "failed:exit 137")
                        and row.get("tokens_in") is None and row.get("tokens_out") is None)
        free = subtype in _FREE_SUBTYPES or subtype.startswith(_FREE_PREFIX) or instant_fail
        per[bot] = per.get(bot, 0.0) + (float(cost) if ok else 0.0 if free else est)
    admitted: dict[str, int] = {}
    for r in gate_rows:
        if r.get("day") != day:
            continue
        if r.get("kind") == "call":
            admitted[str(r.get("job"))] = admitted.get(str(r.get("job")), 0) + 1
        elif r.get("kind") == "settle":
            settled[str(r.get("job"))] = settled.get(str(r.get("job")), 0) + 1
    for job, n in admitted.items():
        per[job] = per.get(job, 0.0) + max(0, n - settled.get(job, 0)) * est
    return per, sum(per.values())


def _read_locked(fh) -> list[dict]:
    """Every gate row. A torn LAST line is a crash mid-append and is skipped; a bad
    line anywhere else means the ledger is not ours to trust, and reading it as
    fewer rounds would be a fail-open, so it raises."""
    _cut_torn_tail(fh)
    fh.seek(0)
    content = fh.read()
    lines = [ln for ln in content.splitlines() if ln.strip()]
    rows = []
    for i, line in enumerate(lines):
        try:
            rows.append(json.loads(line))
        except ValueError:
            if i == len(lines) - 1:
                continue
            raise GateError(f"model_gate: unreadable row {i + 1} in the gate ledger")
    return rows


def _alerted(rows: list[dict], job: str, reason: str, day: str) -> bool:
    sent = sum(1 for r in rows if r.get("kind") == "alert" and r.get("job") == job
               and r.get("reason") == reason and r.get("day") == day)
    failed = sum(1 for r in rows if r.get("kind") == "alert-failed" and r.get("job") == job
                 and r.get("reason") == reason and r.get("day") == day)
    # A send that keeps failing is retried at most ALERT_RETRIES times a day, then
    # dropped: retrying on every gated call when the notifier can never work turned
    # one breach into a send attempt per call (PR #503 round 3).
    return sent - failed > 0 or failed >= ALERT_RETRIES


def notify(line: str) -> bool:
    cmd = os.environ.get(NOTIFY_ENV)
    if not cmd and os.environ.get("PYTEST_CURRENT_TEST"):
        raise GateError(f"model_gate: refusing the live alert path from inside a test; set {NOTIFY_ENV}")
    argv = cmd.split() if cmd else ["bash", DEFAULT_NOTIFY]
    try:
        return subprocess.run(argv + [line], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _cut_torn_tail(fh) -> None:
    """Cut a partial last row (a crash mid-append) under the caller's lock, and
    record the cut.

    The ONE place a torn line is handled, and every writer passes through it via
    _append. Round 2 cut it in the reader only and terminated it in the writer;
    settle() writes first in the ordinary case, so the torn text was welded
    mid-file and every later check() raised: in enforce, every job refused until a
    human deleted the ledger (PR #503 and #504 reviews, rounds 1 to 3).
    """
    fh.seek(0, os.SEEK_END)
    size = fh.tell()
    if size == 0:
        return
    fh.seek(size - 1)
    if fh.read(1) == "\n":
        return
    fh.seek(0)
    content = fh.read()
    keep = content[:content.rfind("\n") + 1]
    fh.truncate(len(keep.encode("utf-8")))
    fh.seek(0, os.SEEK_END)
    fh.write(json.dumps({"schema": SCHEMA, "kind": "repair", "dropped_bytes":
                         len(content.encode("utf-8")) - len(keep.encode("utf-8")),
                         "ts": _now().strftime("%Y-%m-%dT%H:%M:%SZ")}, sort_keys=True) + "\n")
    fh.flush()


def _append(fh, row: dict) -> None:
    _cut_torn_tail(fh)
    fh.seek(0, os.SEEK_END)
    fh.write(json.dumps(row, sort_keys=True) + "\n")
    fh.flush()


def check(job: str, item: str | None = None, now: _dt.datetime | None = None) -> dict:
    """Decide one call. Returns the decision row; `admit` says whether to call."""
    if not job or not str(job).strip():
        raise ValueError("model_gate.check needs a job name")
    now = now or _now()
    day = now.strftime("%Y-%m-%d")
    gate_mode = mode(now)
    try:
        path = ledger_path()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        pending_alerts = []
        with open(path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            rows = _read_locked(fh)
            per, fleet = spend(day, rows)
            spent_job = per.get(job, 0.0)
            # Rounds count only calls admitted in the CURRENT mode: report-week history
            # must not refuse every busy PR on the morning enforce starts (finding 5).
            # Keyed on the ITEM alone, across jobs: three job names on one PR must not
            # get three caps (PR #503 review). Windowed by UTC day, never by sha.
            since = (now - _dt.timedelta(days=max(1, int(_env_number(ROUND_DAYS_ENV, DEFAULT_ROUND_DAYS))) - 1)
                     ).strftime("%Y-%m-%d")
            rounds = sum(1 for r in rows if r.get("kind") == "call"
                         and item is not None and r.get("item") == item
                         and r.get("mode") == gate_mode and str(r.get("day") or "") >= since)
            limits = {"job_budget": job_budget(job), "fleet_ceiling": _env_number(FLEET_USD_ENV, DEFAULT_FLEET_USD),
                      "round_cap": _env_number(ROUNDS_ENV, DEFAULT_ROUNDS)}
            reasons = []
            if spent_job >= limits["job_budget"]:
                reasons.append("job_budget")
            if fleet >= limits["fleet_ceiling"]:
                reasons.append("fleet_ceiling")
            if item is not None and rounds >= limits["round_cap"]:
                reasons.append("round_cap")
            admit = not reasons or gate_mode == "report"
            row = {"schema": SCHEMA, "producer": PRODUCER, "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "day": day, "kind": "call" if admit else "refusal", "job": job, "item": item,
                   "mode": gate_mode, "reasons": reasons, "spent_job_usd": round(spent_job, 4),
                   "spent_fleet_usd": round(fleet, 4), "rounds_before": rounds, "limits": limits,
                   "admit": admit}
            _append(fh, row)
            for reason in reasons:
                # The fleet ceiling is ONE fact, so it is alerted once for the fleet,
                # not once per job that asks (PR #504 review: 9 tickets for 1 breach).
                key = "*fleet*" if reason == "fleet_ceiling" else job
                if not _alerted(rows, key, reason, day):
                    # Claimed UNDER the lock, so two racing callers send one alert.
                    _append(fh, {"schema": SCHEMA, "kind": "alert", "job": key, "reason": reason,
                                 "day": day, "ts": row["ts"]})
                    pending_alerts.append(reason)
        for reason in pending_alerts:
            verb = "refused" if not admit else "would refuse (report-only until %s)" % ENFORCE_FROM
            line = (f"model-gate: {verb} job={job} item={item} limit={reason} "
                    f"spent_job=${spent_job:.2f} spent_fleet=${fleet:.2f} rounds={rounds} limits={limits}")
            if not notify(line):
                # "a+", not "a": _append reads the last byte, and on a write-only
                # handle that raised, check() swallowed it as a gate error, and the
                # failed alert was never retried (PR #503 review round 2).
                with open(path, "a+", encoding="utf-8") as fh:
                    fcntl.flock(fh, fcntl.LOCK_EX)
                    _append(fh, {"schema": SCHEMA, "kind": "alert-failed",
                                 "job": "*fleet*" if reason == "fleet_ceiling" else job,
                                 "reason": reason, "day": day, "ts": row["ts"]})
        return row
    except (GateError, OSError) as exc:
        if os.environ.get("PYTEST_CURRENT_TEST") and not (
                os.environ.get(LEDGER_ENV) or os.environ.get(usage_ledger.LEDGER_ENV)):
            raise
        admit = gate_mode == "report"
        _error_alert_once(job, day, str(exc))
        return {"schema": SCHEMA, "kind": "gate-error", "job": job, "item": item, "day": day,
                "mode": gate_mode, "reasons": ["gate_error"], "error": str(exc)[:300], "admit": admit}


def _error_alert_once(job: str, day: str, err: str) -> None:
    """One alert per UTC day for a gate that cannot read its own ledger. The ledger
    is the broken thing, so the claim is a marker file, created exclusively."""
    try:
        marker = os.path.join(os.path.dirname(ledger_path()), f".model-gate-error-{day}")
        os.close(os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return
    except Exception:  # noqa: BLE001 - cannot claim: alert anyway, the disk is the news
        pass
    notify(f"model-gate: gate error, failing closed for job={job}: {err[:200]}")


def settle(job: str, now: _dt.datetime | None = None) -> bool:
    """Mark one admitted call on `job` as finished, so its in-flight charge drops.

    Called by the gated caller after the call returns, on every exit path, and
    only for a decision whose kind was `call`. Never raises: a missed settle
    over-charges one estimate, which is the safe direction.
    """
    try:
        now = now or _now()
        path = ledger_path()
        with open(path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            _append(fh, {"schema": SCHEMA, "producer": PRODUCER, "kind": "settle", "job": job,
                         "day": now.strftime("%Y-%m-%d"), "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
        return True
    except Exception:  # noqa: BLE001
        return False


def record(job: str, stdout: str, exit_code: int = 0, no_binary: bool = False,
           admitted_call: bool = False) -> bool:
    """Append the cost row for a call made through the shell door. Never raises."""
    try:
        if admitted_call:
            settle(job)
        if no_binary:
            # The door found no binary and never started it. Bash would report
            # exit 127, and "failed:exit 127" is charged the estimate: 25 free
            # calls locked the job out and filed a $25 ticket (PR #503 round 2).
            return usage_ledger.append(usage_ledger.failure_row("no-binary", bot=job, job=job))
        if exit_code == 0 and usage_ledger._result_document(stdout) is not None:
            _text, row = usage_ledger.finish(stdout, bot=job, job=job)
        else:
            row = usage_ledger.failure_row("model-gate:unmetered" if exit_code == 0 else f"exit {exit_code}",
                                           bot=job, job=job, stdout=stdout, ok=exit_code == 0)
        return usage_ledger.append(row)
    except Exception:  # noqa: BLE001 - the meter never fails the run
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="model_gate", description="admission check for a model call")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--job", required=True)
    c.add_argument("--item")
    r = sub.add_parser("record")
    r.add_argument("--job", required=True)
    r.add_argument("--stdout-file", required=True)
    r.add_argument("--exit", type=int, default=0)
    r.add_argument("--no-binary", action="store_true")
    r.add_argument("--call", action="store_true", help="the decision was an admitted call; settle it")
    args = ap.parse_args(argv)
    if args.cmd == "check":
        row = check(args.job, args.item)
        print(json.dumps(row, sort_keys=True))
        return 0 if row["admit"] else REFUSED_EXIT
    try:
        text = open(args.stdout_file, encoding="utf-8", errors="replace").read()
    except OSError:
        text = ""
    record(args.job, text, args.exit, no_binary=args.no_binary, admitted_call=args.call)
    return 0


if __name__ == "__main__":
    sys.exit(main())
