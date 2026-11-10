#!/usr/bin/env python3
"""THE one place a fleet `claude -p` run gets its API key (ASK-4311).

WHY ONE PLACE AND NOT 17. On origin/main, 17 fleet scripts run
`env -u ANTHROPIC_API_KEY claude -p` on purpose, so every fleet run bills the
founder's plan. Moving them onto the two Ultra Console credits means a key, a
failover order, a spend meter and a pause, and 17 copies of that is 17 places a
failover can drift. So: one module reads the Keychain, one module decides which
key is active, one module records what a run cost. Every call site invokes
`exec` and gets back exactly the bytes a plain `claude -p` printed.

WHY IT EXECS RATHER THAN PRINTING A KEY. Founder's constraint: a key never
appears in a chat, a log, a repo or a command line. A `key` subcommand that
printed one would put it in any caller's shell history, log file or `set -x`
trace. Instead the key is read into this process, placed in the child's
environment, and never written anywhere. There is deliberately no subcommand
that prints a key.

WHY IT REFUSES RATHER THAN FALLING BACK TO THE PLAN. A silent fallback is the
whole bug this file exists to fix: the run would succeed, the founder would pay,
and nothing would say so. No key, no run. `test_fleet_api_credit.py` pins that
the child's environment actually carries the key, so a mutant that drops the
injection turns red instead of quietly re-billing the plan.

THE FAILOVER. Key 1 until Anthropic refuses a run for an exhausted credit, then
key 2. Both refused: the fleet PAUSES, and re-probes once at the start of each
budget day; the first success resumes it. No path here ever buys credit, raises a
limit, or touches billing.

WHAT THE DAY'S BUDGET GATES AND WHAT IT DOES NOT. This module refuses on the
MONTH's hard ceiling (both credits gone), never on the day's allowance. The
day's allowance stops NEW work in `kipi-dispatch.sh`, where stopping is free. A
refusal here would kill a run already in flight, which spends the credit that
produced the partial work and throws the work away.

HONEST BOUNDARY on the refusal text. `_EXHAUSTED_PATTERNS` is the set of phrases
read as "this key's credit is gone". It is {{UNVERIFIED}}: an exhausted credit
has not been observed on a live key, because producing one costs $250. The
patterns are overridable with KIPI_FLEET_EXHAUSTED_PATTERNS (newline-separated)
so a real observation becomes a config change, not a code change. If the live
wording matches none of them, the failure degrades to an ordinary failed run:
the fleet keeps using key 1, the cost rows stop growing because nothing is
charged, and the daily report shows spend flat against an unchanged credit. That
is visible, not silent, and it is the reason the report carries per-key credit.

Usage:
  fleet_api_key.py exec [--actor NAME] -- <command> [args...]
  fleet_api_key.py status [--json]     # active slot, per-key credit, paused state
  fleet_api_key.py probe               # the daily re-probe; exit 0 if the fleet may run

Exit codes: the child's code on a run. 2 usage. 4 no key available (paused, or
nothing in the Keychain). 5 the month's credit is gone on both keys.

Env:
  KIPI_FLEET_KEYCHAIN_SERVICE_1/_2  Keychain service names
                                    (default kipi-fleet-api-key-1 / -2)
  KIPI_FLEET_STATE                  state path (default ~/.local/state/kipi/fleet-api-state.json)
  KIPI_FLEET_EXHAUSTED_PATTERNS     newline-separated refusal phrases
  KIPI_TEST=1                       fixtures only: the Keychain is never read;
                                    keys come from KIPI_FLEET_FAKE_KEY_1/_2
  KIPI_FLEET_NOW                    epoch seconds; the test clock (shared with
                                    fleet_api_spend.py)
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fleet_api_spend as spend  # noqa: E402  (same directory, single ledger owner)

SLOTS = spend.SLOTS

DEFAULT_STATE = os.path.join(
    os.path.expanduser("~"), ".local", "state", "kipi", "fleet-api-state.json")

EXIT_USAGE = 2
EXIT_NO_KEY = 4
EXIT_CREDIT_GONE = 5

#: See the HONEST BOUNDARY note above: {{UNVERIFIED}} against a live exhausted key.
_EXHAUSTED_PATTERNS = (
    "credit balance is too low",
    "insufficient credit",
    "insufficient_quota",
    "out of credits",
    "credits required",
    "billing_error",
    "your account has run out of credit",
)

#: Appended to a `claude` call so the run reports its own cost. The literal is
#: pinned by the test rather than read from here: a test comparing the subject to
#: itself passes when the flag is mutated and the meter becomes a no-op. Same
#: reasoning as voiceloop/usage_ledger.py JSON_FLAGS.
JSON_FLAGS = ("--output-format", "json")


def state_path():
    return os.environ.get("KIPI_FLEET_STATE") or DEFAULT_STATE


def in_test_mode():
    return os.environ.get("KIPI_TEST") == "1"


def service_name(slot):
    env = os.environ.get("KIPI_FLEET_KEYCHAIN_SERVICE_%d" % slot)
    return env or ("kipi-fleet-api-key-%d" % slot)


def exhausted_patterns():
    raw = os.environ.get("KIPI_FLEET_EXHAUSTED_PATTERNS", "")
    if raw.strip():
        return tuple(p.strip().lower() for p in raw.splitlines() if p.strip())
    return _EXHAUSTED_PATTERNS


def reads_as_exhausted(text):
    low = (text or "").lower()
    return any(p in low for p in exhausted_patterns())


# --- state ------------------------------------------------------------------
def _blank_state():
    return {"active_slot": SLOTS[0], "exhausted": {}, "paused": False,
            "paused_since": None, "last_probe_day": None}


def read_state():
    path = state_path()
    if not os.path.exists(path):
        return _blank_state()
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        # A state file that cannot be read is treated as a fresh one on purpose.
        # Guessing "paused" from an unreadable file would wedge the fleet on a
        # disk hiccup; guessing "key 1" costs at most one refused run, which
        # re-derives the real state from the refusal itself.
        sys.stderr.write("fleet_api_key: cannot read %s (%s); starting fresh\n"
                         % (path, exc))
        return _blank_state()
    if not isinstance(data, dict):
        return _blank_state()
    base = _blank_state()
    base.update(data)
    if base.get("active_slot") not in SLOTS:
        base["active_slot"] = SLOTS[0]
    if not isinstance(base.get("exhausted"), dict):
        base["exhausted"] = {}
    return base


def write_state(state):
    """Atomic replace under an advisory lock, so two runs cannot interleave."""
    path = state_path()
    parent = os.path.dirname(path)
    try:
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        lock = os.path.join(parent, ".fleet-api-state.lock") if parent else None
        lock_fh = open(lock, "a") if lock else None
        try:
            if lock_fh:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            fd, tmp = tempfile.mkstemp(dir=parent or None, prefix=".fleet-api-state.")
            with os.fdopen(fd, "w") as fh:
                json.dump(state, fh, sort_keys=True, indent=2)
                fh.write("\n")
            os.replace(tmp, path)
        finally:
            if lock_fh:
                lock_fh.close()
    except OSError as exc:
        sys.stderr.write("fleet_api_key: cannot write %s (%s)\n" % (path, exc))
        return False
    return True


def mark_exhausted(slot, at=None):
    state = read_state()
    state["exhausted"][str(slot)] = spend.month_key(at)
    nxt = next_slot(slot, state, at)
    if nxt is None:
        state["paused"] = True
        state["paused_since"] = (at or spend.now()).isoformat(timespec="seconds")
        state["active_slot"] = slot
        # THE PAUSE CONSUMES TODAY'S PROBE. Without this line usable_slot() sees
        # `paused` with a last_probe_day that is not today, treats the pause as
        # unprobed, and hands key 1 straight back -- so the pause lasted exactly
        # zero runs and every call re-ran against a dead credit. Observed RED by
        # test_both_exhausted_pauses_the_fleet before this line existed. The
        # refusal that CREATED the pause IS the day's probe; the next one is
        # tomorrow's.
        state["last_probe_day"] = spend.budget_day(at)
        write_state(state)
        spend.event("pause", "both API credits read as exhausted; dispatch pauses "
                             "until the next budget day re-probes")
        return None
    state["active_slot"] = nxt
    write_state(state)
    spend.event("failover", "key %d read as exhausted; switching to key %d"
                            % (slot, nxt))
    return nxt


def next_slot(after, state=None, at=None):
    """The next slot that is not marked exhausted THIS month, or None."""
    state = state if state is not None else read_state()
    month = spend.month_key(at)
    for slot in SLOTS:
        if slot == after:
            continue
        if state.get("exhausted", {}).get(str(slot)) == month:
            continue
        if spend.credit_left(slot, at) <= 0.0:
            continue
        return slot
    return None


def usable_slot(at=None, consume=False):
    """Which key may run now, or None.

    READERS DEGRADE, WRITERS CONSUME (`consume=False` is the default on purpose).
    A paused fleet gets ONE re-probe per budget day, and spending that probe is a
    mutation. Before this split the function wrote state on every call, so
    `status` and `probe` -- both pure inspections, and the dispatcher calls one of
    them every 15 minutes -- each burned the day's only probe and left the fleet
    paused until tomorrow. Observed RED by
    test_a_paused_fleet_re_probes_once_on_the_next_budget_day, where the reader
    consumed the probe and the run that followed it got no key at all.

    So: `consume=True` only on the path that is about to actually run something
    (`cmd_exec`). Every other caller sees the same answer and changes nothing.

    A pause is lifted by a DAY changing, never by a timer: the re-probe is the
    first RUN of the new budget day, and if it refuses again the pause returns. A
    new calendar month clears every exhausted mark, because the credit itself is
    granted monthly.
    """
    at = at or spend.now()
    state = read_state()
    month = spend.month_key(at)
    day = spend.budget_day(at)

    # A new month hands back both credits. Heal the view in memory; persist the
    # heal only on the writing path, so a reader stays a reader.
    stale = [k for k, v in state.get("exhausted", {}).items() if v != month]
    if stale:
        for k in stale:
            state["exhausted"].pop(k, None)
        state["paused"] = False
        state["paused_since"] = None
        state["active_slot"] = SLOTS[0]
        if consume:
            write_state(state)

    if state.get("paused"):
        if state.get("last_probe_day") == day:
            return None
        if consume:
            state["last_probe_day"] = day
            state["active_slot"] = SLOTS[0]
            state["exhausted"] = {}
            write_state(state)
            spend.event("probe", "new budget day %s: re-probing key %d"
                                 % (day, SLOTS[0]))
        return SLOTS[0]

    active = state.get("active_slot", SLOTS[0])
    if state.get("exhausted", {}).get(str(active)) == month or \
            spend.credit_left(active, at) <= 0.0:
        return next_slot(active, state, at)
    return active


def clear_pause(at=None):
    state = read_state()
    if not state.get("paused"):
        return False
    state["paused"] = False
    state["paused_since"] = None
    write_state(state)
    spend.event("resume", "a run succeeded on key %d; dispatch resumes"
                          % state.get("active_slot", SLOTS[0]))
    return True


# --- the key ----------------------------------------------------------------
def read_key(slot):
    """The key for `slot`, or None. Never logged, never printed, never returned
    to a caller outside this process."""
    if in_test_mode():
        return os.environ.get("KIPI_FLEET_FAKE_KEY_%d" % slot) or None
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", service_name(slot), "-w"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    except OSError as exc:
        sys.stderr.write("fleet_api_key: cannot run `security` (%s)\n" % exc)
        return None
    if out.returncode != 0:
        # stderr from `security` names the service, never the secret.
        sys.stderr.write("fleet_api_key: no Keychain item for service %s\n"
                         % service_name(slot))
        return None
    key = (out.stdout or "").strip()
    return key or None


# --- the run ----------------------------------------------------------------
def _with_json_flags(argv):
    """Add --output-format json to a `claude` call that has no format flag yet."""
    if not argv:
        return argv
    if os.path.basename(argv[0]) != "claude":
        return argv
    if "--output-format" in argv:
        return argv
    return list(argv) + list(JSON_FLAGS)


def _parse_run(stdout):
    """(text_for_the_caller, cost_usd, note).

    `claude -p --output-format json` prints one object. Turned back into EXACTLY
    the bytes a plain `-p` call printed: `result` plus one trailing newline
    (measured 2026-09-22, voiceloop/usage_ledger.py fixture). Anything that is
    not that object is handed back untouched and charged 0 with a note, because
    a meter must never change what a caller reads.
    """
    raw = stdout if stdout is not None else ""
    try:
        doc = json.loads(raw)
    except ValueError:
        return raw, 0.0, "parse_error"
    if not isinstance(doc, dict) or "result" not in doc:
        return raw, 0.0, "parse_error"
    try:
        cost = float(doc.get("total_cost_usd") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    text = doc.get("result")
    if not isinstance(text, str):
        return raw, cost, "parse_error"
    return text + "\n", cost, None


def _run_once(slot, argv, actor):
    """Run argv with slot's key in the child env. Returns (rc, text, cost, raw)."""
    key = read_key(slot)
    if not key:
        return None, "", 0.0, ""
    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = key
    # The slot is safe to pass on; the key is not. A child that wants to know
    # which account it is billing reads this.
    env["KIPI_FLEET_KEY_SLOT"] = str(slot)
    try:
        proc = subprocess.run(_with_json_flags(argv), stdout=subprocess.PIPE,
                              stderr=None, universal_newlines=True, env=env)
    except OSError as exc:
        sys.stderr.write("fleet_api_key: cannot run %r (%s)\n" % (argv[0], exc))
        return 127, "", 0.0, ""
    text, cost, note = _parse_run(proc.stdout)
    spend.record(slot, cost, actor=actor, ok=(proc.returncode == 0), note=note)
    return proc.returncode, text, cost, proc.stdout or ""


def cmd_exec(argv, actor=None):
    if not argv:
        sys.stderr.write("fleet_api_key: exec needs a command after `--`\n")
        return EXIT_USAGE

    if spend.credit(None)["total_left_usd"] <= 0.0:
        sys.stderr.write("fleet_api_key: both API credits are spent for %s; "
                         "no run. Nothing here buys credit.\n" % spend.month_key())
        spend.event("pause", "month %s: both credits spent" % spend.month_key())
        return EXIT_CREDIT_GONE

    # The only consuming caller: this is the path that actually runs something,
    # so this is the one allowed to spend the day's re-probe.
    slot = usable_slot(consume=True)
    if slot is None:
        sys.stderr.write("fleet_api_key: paused (both credits read as exhausted); "
                         "the next budget day re-probes\n")
        return EXIT_NO_KEY

    rc, text, _cost, raw = _run_once(slot, argv, actor)
    if rc is None:
        sys.stderr.write("fleet_api_key: no key for slot %d; refusing to fall back "
                         "to the plan login\n" % slot)
        return EXIT_NO_KEY

    if rc != 0 and reads_as_exhausted(raw):
        nxt = mark_exhausted(slot)
        if nxt is None:
            sys.stderr.write("fleet_api_key: both credits read as exhausted; "
                             "dispatch pauses until the next budget day\n")
            return EXIT_NO_KEY
        rc2, text2, _c2, raw2 = _run_once(nxt, argv, actor)
        if rc2 is None:
            sys.stderr.write("fleet_api_key: no key for slot %d\n" % nxt)
            return EXIT_NO_KEY
        if rc2 != 0 and reads_as_exhausted(raw2):
            mark_exhausted(nxt)
            sys.stderr.write("fleet_api_key: both credits read as exhausted; "
                             "dispatch pauses until the next budget day\n")
            return EXIT_NO_KEY
        if rc2 == 0:
            clear_pause()
        sys.stdout.write(text2)
        return rc2

    if rc == 0:
        clear_pause()
    sys.stdout.write(text)
    return rc


def status(at=None):
    state = read_state()
    out = spend.credit(at)
    out.update({
        "active_slot": state.get("active_slot", SLOTS[0]),
        "paused": bool(state.get("paused")),
        "paused_since": state.get("paused_since"),
        "last_probe_day": state.get("last_probe_day"),
        "exhausted_marks": state.get("exhausted", {}),
        "budget": spend.budget(at),
    })
    return out


def _main(argv):
    ap = argparse.ArgumentParser(prog="fleet_api_key.py", description=__doc__)
    sub = ap.add_subparsers(dest="cmd")

    p_exec = sub.add_parser("exec", help="run a command with a fleet API key")
    p_exec.add_argument("--actor")
    p_exec.add_argument("rest", nargs=argparse.REMAINDER)

    p_st = sub.add_parser("status", help="active slot, credit left, paused state")
    p_st.add_argument("--json", action="store_true")

    sub.add_parser("probe", help="the daily re-probe; exit 0 if the fleet may run")

    args = ap.parse_args(argv)

    if args.cmd == "exec":
        rest = list(args.rest)
        if rest and rest[0] == "--":
            rest = rest[1:]
        return cmd_exec(rest, actor=args.actor)

    if args.cmd == "status":
        state = status()
        if args.json:
            print(json.dumps(state, sort_keys=True))
        else:
            print("active key: %d%s" % (state["active_slot"],
                                        " (PAUSED)" if state["paused"] else ""))
            for slot in SLOTS:
                print("key %d: $%.2f left" % (slot, state["per_key_usd"][slot]))
            b = state["budget"]
            print("today (%s): spent $%.2f of $%.2f"
                  % (b["day"], b["spent_usd"], b["allowance_usd"]))
        return 0

    if args.cmd == "probe":
        slot = usable_slot()
        if slot is None:
            print("paused")
            return EXIT_NO_KEY
        print("key %d" % slot)
        return 0

    ap.print_usage(sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
