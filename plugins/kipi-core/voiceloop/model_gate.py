"""model_gate -- a call-count gate in front of every headless model call.

why this shape: the dollar-based gate (PR #504) kept growing new defects every
review round: cost estimates, in-flight settlement, torn lines, alert retries.
A count needs none of that. One line per admitted call, two limits, one alert.

    check(job, item=None) -> {"admit": bool, "mode": str, "reason": str|None}

* Counts admitted calls per job (the usage ledger's `job`) per UTC day, and across the fleet per day.
* Ledger: one JSON line per admitted call, in one append-only file per UTC day
  under KIPI_MODEL_GATE_DIR (default ~/.config/kipi/model-gate/). Sharded by
  day so a check reads one day of lines, not the whole history. File-locked.
* Mode: report (log + alert, admit anyway) until ENFORCE_FROM, then enforce.
  KIPI_MODEL_GATE_MODE overrides; an unknown value means enforce.
* Alert: at most one per (job, day) through slack-notify.sh. The "alerted" line
  is written BEFORE the send, so a failed send is logged and never retried.
* A ledger check() cannot read or write: _ledger_error() admits in report
  mode, refuses otherwise, one alert per day through an O_EXCL marker file.

CLI, run by model-gate.sh: `python3 -m voiceloop.model_gate check --job J
[--item I]` exits 0 on admit, 3 on refuse. Tests: tests/test_model_gate.py.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fcntl
import json
import os
import subprocess
import sys
import tempfile

# why these numbers: the first defaults (2486 / 2519) were x1.5 of the busiest
# day in the window, and that day, 2026-10-01, WAS the runaway (critic.judge()
# 1180 calls, revise 271, fleet 1679). A cap derived from the incident cannot stop
# it. The second try (150 / 300) sat BELOW an ordinary day once voiceloop calls
# were logged (PR #509 review): it would have refused normal work.
# Derived 2026-10-03 from usage-ledger.jsonl, normal days since voiceloop logging
# began, 2026-10-01 excluded: 09-30 (279), 10-02 (412), 10-03 (115, partial).
#   per job: normal max 213 (one caller, 09-30) -> 2x, rounded down = 400
#   fleet:   normal max 412 (10-02)             -> 2x, rounded down = 800
# Both sit at or under half the runaway (1180 / 1679). A "job" is the usage
# ledger's `job` field (CHIEF_JOB or the caller name, e.g. critic.judge()), not
# the bot, so one looping caller stops without starving the rest of its bot.
PER_JOB_DEFAULT = 400
FLEET_DEFAULT = 800
ENFORCE_FROM = "2026-10-10"
REFUSE = 3


def _today(now=None) -> str:
    return (now or _dt.datetime.now(_dt.timezone.utc)).strftime("%Y-%m-%d")


def mode(day: str | None = None) -> str:
    raw = os.environ.get("KIPI_MODEL_GATE_MODE", "").strip()
    if not raw:
        return "report" if (day or _today()) < ENFORCE_FROM else "enforce"
    # A typo must not quietly switch enforcement off.
    return raw if raw in ("report", "enforce") else "enforce"


def _limit(env: str, default: int) -> int:
    raw = os.environ.get(env, "").strip()
    return int(raw) if raw.isdigit() else default


def _under_pytest() -> bool:
    # sys.modules, not PYTEST_CURRENT_TEST: the usage-ledger suites delete that
    # variable to drive run_model with a stub binary, which reaches this gate.
    return "pytest" in sys.modules


def gate_dir() -> str:
    explicit = os.environ.get("KIPI_MODEL_GATE_DIR")
    if explicit:
        return explicit
    # A suite that did not name a gate dir must never count in the live ledger
    # and eat the fleet's real budget: give it a throwaway one per process.
    if _under_pytest():
        return os.path.join(tempfile.gettempdir(), f"kipi-model-gate-pytest-{os.getpid()}")
    return os.path.join(os.path.expanduser("~"), ".config", "kipi", "model-gate")


def _notify(text: str) -> None:
    """One send, never retried. The caller already recorded that it alerted."""
    if not os.environ.get("KIPI_NOTIFY") and _under_pytest():
        return  # a suite never files a real ticket
    script = os.environ.get("KIPI_NOTIFY") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
        "q-system", ".q-system", "scripts", "slack-notify.sh")
    try:
        rc = subprocess.run(["bash", script, text], capture_output=True, timeout=30).returncode
    except (OSError, subprocess.SubprocessError) as exc:
        rc = repr(exc)
    if rc != 0:
        print(f"model_gate: alert not sent ({rc}); not retried: {text}", file=sys.stderr)


def _ledger_error(job: str, day: str, m: str, exc: Exception) -> dict:
    admit = m == "report"
    print(f"model_gate: ledger unusable ({exc}); {'admitting' if admit else 'refusing'} {job}",
          file=sys.stderr)
    # One alert per day. The marker lives outside the ledger dir, since that dir
    # is the thing that just failed; if the marker cannot be made, stay quiet
    # rather than alert on every call.
    marker = os.path.join(os.environ.get("KIPI_MODEL_GATE_MARKER_DIR") or tempfile.gettempdir(),
                          f"kipi-model-gate-ledger-error-{day}")
    try:
        os.close(os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
    except OSError:
        return {"admit": admit, "mode": m, "reason": "ledger-error"}
    _notify(f"model gate: ledger unusable ({type(exc).__name__}); mode {m}, "
            f"{'admitting' if admit else 'refusing'} calls until it is fixed")
    return {"admit": admit, "mode": m, "reason": "ledger-error"}


def check(job: str, item: str | None = None, now=None) -> dict:
    day = _today(now)
    m = mode(day)
    per_job = _limit("KIPI_MODEL_GATE_PER_JOB", PER_JOB_DEFAULT)
    fleet = _limit("KIPI_MODEL_GATE_FLEET", FLEET_DEFAULT)
    path = os.path.join(gate_dir(), f"{day}.jsonl")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            job_n = fleet_n = 0
            alerted = False
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue  # a torn line is skipped, never fatal
                if row.get("kind") == "call":
                    fleet_n += 1
                    job_n += row.get("job") == job
                elif row.get("kind") == "alerted" and row.get("job") == job:
                    alerted = True
            reason = None
            if job_n >= per_job:
                reason = f"job {job} at {job_n}/{per_job} calls today"
            elif fleet_n >= fleet:
                reason = f"fleet at {fleet_n}/{fleet} calls today"
            admit = reason is None or m == "report"
            stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            out = []
            if reason and not alerted:
                out.append({"kind": "alerted", "job": job, "ts": stamp, "reason": reason})
            if admit:
                out.append({"kind": "call", "job": job, "item": item, "ts": stamp})
            fh.write("".join(json.dumps(r) + "\n" for r in out))
            fh.flush()
    except OSError as exc:
        return _ledger_error(job, day, m, exc)
    if reason and not alerted:
        _notify(f"model gate ({m}): {reason}; "
                f"{'admitted, report-only until ' + ENFORCE_FROM if admit else 'calls refused'}")
    return {"admit": admit, "mode": m, "reason": reason}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="model_gate")
    ap.add_argument("cmd", choices=["check"])
    ap.add_argument("--job", required=True)
    ap.add_argument("--item")
    a = ap.parse_args(argv)
    row = check(a.job, a.item)
    print(json.dumps(row))
    return 0 if row["admit"] else REFUSE


if __name__ == "__main__":
    sys.exit(main())
