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

HOW A REFUSAL IS RECOGNISED, and the boundary that is left. Three signals, two of
them structural, because the first build read only Anthropic's prose on stdout
and `claude -p` rewrites an API error into its own short string (PR #717 review
round 1, finding 3 -- a missed refusal means no failover, no pause and no event):

  1. `api_error_status` from the CLI's own result envelope. 402 is Payment
     Required and reads as exhausted on its own, whatever the text says. 400 and
     429 deliberately do not: failing over on a bad request or a rate limit would
     burn key 2 on a bug.
  2. `is_error` / `subtype` from the same envelope decide whether the turn FAILED.
     Gating on the process exit code alone let an `is_error: true` run that
     exited 0 skip the check entirely.
  3. `_EXHAUSTED_PATTERNS` over the text, now stdout AND the child's stderr,
     overridable with KIPI_FLEET_EXHAUSTED_PATTERNS (newline-separated) so a real
     observation becomes a config change rather than a code change.

STILL {{UNVERIFIED}} against a live exhausted key: producing one costs $250. The
envelope field names are measured, not guessed -- they come from a captured real
response (plugins/kipi-core/voiceloop/tests/fixtures/claude-p-capture-2026-09-22
.json). If a live refusal still matches nothing, it degrades to an ordinary
failed run: the fleet keeps using key 1, the cost rows stop growing because
nothing is charged, and the daily report shows spend flat against an unchanged
credit. Visible, not silent, and the reason the report carries per-key credit.
Every spend row also records the `api_error_status` and `subtype` the CLI
reported, so the first real refusal is readable afterwards instead of lost.

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
import collections
import fcntl
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading

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


#: `claude -p --output-format json` reports an API refusal in its OWN envelope:
#: `is_error`, `subtype` and `api_error_status` are top-level fields of the result
#: object (measured, not guessed -- they are in the captured real response at
#: plugins/kipi-core/voiceloop/tests/fixtures/claude-p-capture-2026-09-22.json).
#: HTTP 402 is Payment Required and means exactly one thing, so it is read
#: structurally and needs no prose match at all. 400 and 429 are NOT here: a bad
#: request and a rate limit are not an exhausted credit, and failing over on them
#: would burn key 2 on a bug.
EXHAUSTED_STATUSES = (402,)


def reads_as_exhausted(text, envelope=None):
    """Does this refusal mean "this key's credit is gone"?

    TWO SURFACES, because the prose alone was not enough (PR #717 review round 1,
    finding 3). The CLI rewrites an API error into its own short UI string, so a
    substring match against Anthropic's wording can miss a refusal entirely --
    and a missed refusal means no failover, no pause and no event: the fleet
    keeps hammering a dead key and the daily report shows spend flat.

      1. STRUCTURAL, and trusted first: `api_error_status` in EXHAUSTED_STATUSES.
         A field the CLI sets itself cannot be reworded.
      2. PROSE, as before: the pattern list over the text, which now includes the
         child's STDERR as well as its stdout (`_run_once` captures both).

    Still {{UNVERIFIED}} against a live exhausted key -- producing one costs $250.
    What changed is the size of the hole: a 402 is caught whatever it says, and
    the spend row records `api_error_status` so the first real refusal turns the
    guess into a measurement.
    """
    if isinstance(envelope, dict):
        status = envelope.get("api_error_status")
        try:
            if status is not None and int(status) in EXHAUSTED_STATUSES:
                return True
        except (TypeError, ValueError):
            pass
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


def key_present(slot):
    """Is there key MATERIAL for `slot`? Presence only -- never the secret.

    THE QUESTION `probe` WAS NOT ASKING (PR #717 review round 2, finding 1).
    `usable_slot()` answers from the credit ledger and the pause state; it knows
    nothing about whether the Keychain item exists. Nothing in this change
    creates the two items, so on merge day probe read `key 1`, the dispatcher
    gate went green, and every run it launched died at `read_key` with exit 4 --
    no spend row, no event, no ticket, and a daily report that read as a quiet
    day.

    `find-generic-password` WITHOUT `-w` returns the item's attributes and not
    its password, so this asks the Keychain the yes/no question and the secret
    never enters this process. A presence check that pulled the key in would be
    one more place it could be logged.
    """
    if in_test_mode():
        return bool(os.environ.get("KIPI_FLEET_FAKE_KEY_%d" % slot))
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", service_name(slot)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        # `security` itself not running is a RED answer, not a green one: the
        # per-run path reads the key through the same binary, so a run launched
        # now would fail anyway. Saying "no key" here stops the tick instead of
        # spending it on runs that cannot work.
        sys.stderr.write("fleet_api_key: cannot run `security` (%s)\n" % exc)
        return False
    return out.returncode == 0


def missing_slots():
    """Slots with no key material, in failover order."""
    return tuple(s for s in SLOTS if not key_present(s))


def note_missing_key(slots):
    """One `no_key` event per budget day, whoever noticed.

    Both the dispatcher's 15-minute probe and a run that got through reach this,
    and `spend.event_once` is what keeps the timer from turning one condition
    into 96 rows. It writes the EVENTS ledger and never the key state, so a
    reader stays a reader (see `usable_slot`).
    """
    spend.event_once("no_key",
                     "no Keychain item for key %s; every fleet run refuses "
                     "(exit %d) until it is created. Nothing here can create it."
                     % (", ".join(str(s) for s in slots), EXIT_NO_KEY))


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


def envelope_of(stdout):
    """The `claude -p --output-format json` result object, or None.

    Separate from _parse_run because the FAILURE path needs it: a refusal still
    prints the envelope, and its `is_error` / `api_error_status` fields are the
    only signals that survive the CLI rewording an API error.
    """
    try:
        doc = json.loads(stdout if stdout is not None else "")
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def declared_error(envelope):
    """True when the CLI says the turn failed, whatever the process exit code was.

    WHY THE EXIT CODE IS NOT ENOUGH (PR #717 round 1, finding 3). The failover was
    gated on `rc != 0`. `claude -p` reports a failed turn inside the envelope --
    `is_error: true`, `subtype` naming the kind -- and a build that exits 0 while
    saying so would skip the detector entirely: no failover, no pause, no event.
    Reading both means the exit code can only ADD a failure, never hide one.

    ONE READING OF THIS ENVELOPE IN THE FLEET, not two. `voiceloop/usage_ledger.py
    ._failed()` already answers this exact question for the usage ledger --
    `is_error`, or a `subtype` that STARTS WITH "error" -- and two readers of one
    input with different semantics is a defect even when each is defensible on
    its own. So this is that rule, deliberately not a stricter one: a future
    subtype like "max_turns" is not an API refusal, and treating every non-success
    subtype as a failure here would have the two files disagree about the same
    run.
    """
    if not isinstance(envelope, dict):
        return False
    if envelope.get("is_error") is True:
        return True
    return str(envelope.get("subtype") or "").startswith("error")


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


#: How much of a child's stderr the detector reads. The whole stream is handed
#: back to the caller line by line as it arrives; only the SCAN is bounded, so a
#: run that printed megabytes of progress cannot be held in memory to find one
#: sentence.
STDERR_SCAN_BYTES = 65536
STDERR_SCAN_LINES = 400


def _pump_stderr(stream, keep):
    """Copy the child's stderr to ours AS IT ARRIVES, keeping a bounded tail.

    WHY A PUMP AND NOT A BUFFER. Before the detector needed this text, stderr was
    inherited, so a long run's progress reached the caller's log live. Holding it
    until the child exits would lose it exactly when it matters most:
    linear-worker.sh kills a hung run by process GROUP at 1800s, and anything
    still sitting in this process at that moment dies with it. The log is where a
    hang is read afterwards, so the bytes go out first and the tail is kept for
    the scan second.
    """
    for line in iter(stream.readline, ""):
        sys.stderr.write(line)
        sys.stderr.flush()
        keep.append(line)


#: The run this process is in the middle of, for the watchdog handler below.
#: Empty whenever nothing is in flight, and cleared the moment the normal path
#: has recorded, so a kill arriving late cannot write a second row.
_IN_FLIGHT = {}


def _record_in_flight_as_unmetered(signum):
    """Record the run a watchdog is killing, then let the kill land.

    WHY THIS EXISTS (PR #717 review round 2, finding 2). `linear-worker.sh` kills
    a hung run by process GROUP at 1800s -- the rc=143 in this issue's own worker
    log -- and `spend.record` sits after `proc.communicate()`. The default
    SIGTERM action therefore took this process down before the row was written,
    so a timed-out Opus turn that Anthropic really charged was simply absent
    from the ledger the day's allowance is divided out of: the meter read the day
    as cheaper than it was, and read it that way every time the watchdog fired.

    The cost cannot be recovered -- `claude -p` prints `total_cost_usd` only at
    the end -- so this does not invent one. It writes the row with cost 0 and
    `unmetered: True`, which `spend.unmetered_today()` counts and the daily
    report turns into "today's spend is a floor, not a total". A visible gap
    beats a silent zero.

    ONE APPEND, THEN OUT OF THE WAY. The handler does not drain the child or
    parse anything: the whole process group is going down, and a handler that
    blocked would turn a watchdog kill into a hang.
    """
    run = _IN_FLIGHT.pop("run", None)
    if run:
        try:
            name = signal.Signals(signum).name
        except (ValueError, AttributeError):
            name = str(signum)
        proc = run.get("proc")
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
        spend.record(run["slot"], 0.0, actor=run.get("actor"), ok=False,
                     unmetered=True,
                     note="killed by %s before its cost was read" % name)
    # Die BY the signal, not by a tidy exit 0: converge.sh and the worker read
    # the status, and a swallowed SIGTERM would read as a run that succeeded.
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def _arm_watchdog_handler():
    """SIGTERM and SIGINT only, and only where a handler can be installed.

    SIGKILL cannot be caught, so a `kill -9` still loses the row; that is stated
    rather than papered over. The worker's watchdog sends TERM first, which is
    the case this covers. Off the main thread `signal.signal` raises, and this
    module is imported as a library in the suites, so the failure is swallowed
    rather than made into an error at import time.
    """
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, lambda s, _f: _record_in_flight_as_unmetered(s))
        except (ValueError, OSError):
            pass


def _run_once(slot, argv, actor):
    """Run argv with slot's key in the child env.

    Returns (rc, text, cost, scanned_text, envelope). `scanned_text` is stdout
    PLUS stderr: a credit refusal from the CLI can land on either, and the
    detector that only read stdout was half blind (PR #717 round 1, finding 3).
    The child writes stderr straight into a temp file, so the bytes are not
    reordered and nothing is buffered in this process; the file is then copied to
    our own stderr, which is where every caller's log already points.
    """
    key = read_key(slot)
    if not key:
        return None, "", 0.0, "", None
    env = dict(os.environ)
    # THE LINE THE WHOLE CHANGE EXISTS FOR. Dropping it sends the run back to the
    # founder's plan and every call still succeeds, so nothing downstream
    # notices. Mutation-checked 2026-11-09: removing it turns 12 of 25 cases red,
    # test_child_is_handed_the_key first.
    env["ANTHROPIC_API_KEY"] = key
    # The slot is safe to pass on; the key is not. A child that wants to know
    # which account it is billing reads this.
    env["KIPI_FLEET_KEY_SLOT"] = str(slot)
    keep = collections.deque(maxlen=STDERR_SCAN_LINES)
    _arm_watchdog_handler()
    _IN_FLIGHT["run"] = {"slot": slot, "actor": actor, "proc": None}
    try:
        proc = subprocess.Popen(_with_json_flags(argv), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True,
                                env=env)
    except OSError as exc:
        _IN_FLIGHT.pop("run", None)
        sys.stderr.write("fleet_api_key: cannot run %r (%s)\n" % (argv[0], exc))
        return 127, "", 0.0, "", None
    _IN_FLIGHT["run"]["proc"] = proc
    pump = threading.Thread(target=_pump_stderr, args=(proc.stderr, keep))
    pump.daemon = True
    pump.start()
    stdout, _ = proc.communicate()
    pump.join(timeout=5)
    err_text = "".join(keep)[-STDERR_SCAN_BYTES:]

    text, cost, note = _parse_run(stdout)
    envelope = envelope_of(stdout)
    # THE REFUSAL'S OWN FIELDS GO IN THE LEDGER. The pattern list is
    # {{UNVERIFIED}} against a live exhausted key, and this is what makes the
    # first real one readable afterwards instead of lost: the row carries the
    # status and subtype the CLI reported.
    if isinstance(envelope, dict):
        bits = [b for b in (note,
                            ("api_error_status=%s" % envelope["api_error_status"])
                            if envelope.get("api_error_status") is not None else None,
                            ("subtype=%s" % envelope["subtype"])
                            if declared_error(envelope) else None) if b]
        note = " ".join(bits) or None
    ok = proc.returncode == 0 and not declared_error(envelope)
    # CLEARED BEFORE THE ROW, so a SIGTERM arriving between these two lines
    # cannot add a second, unmetered row for a run that was already measured.
    _IN_FLIGHT.pop("run", None)
    spend.record(slot, cost, actor=actor, ok=ok, note=note)
    raw = (stdout or "") + ("\n" + err_text if err_text else "")
    return proc.returncode, text, cost, raw, envelope


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

    rc, text, _cost, raw, env1 = _run_once(slot, argv, actor)
    if rc is None:
        # THE SAME TRACE THE GATE LEAVES. A run can reach here with the gate
        # bypassed (a direct fleet-claude.sh call, a one-off), and a refusal with
        # no event is exactly the "quiet day" the review named. event_once keeps
        # it at one row a budget day however many runs hit it.
        note_missing_key([slot])
        sys.stderr.write("fleet_api_key: no key for slot %d; refusing to fall back "
                         "to the plan login\n" % slot)
        return EXIT_NO_KEY

    # A FAILED TURN IS A FAILED TURN WHETHER OR NOT THE PROCESS SAID SO. `rc != 0`
    # alone let an `is_error: true` envelope with exit 0 skip the detector
    # entirely (PR #717 round 1, finding 3).
    if (rc != 0 or declared_error(env1)) and reads_as_exhausted(raw, env1):
        nxt = mark_exhausted(slot)
        if nxt is None:
            sys.stderr.write("fleet_api_key: both credits read as exhausted; "
                             "dispatch pauses until the next budget day\n")
            return EXIT_NO_KEY
        rc2, text2, _c2, raw2, env2 = _run_once(nxt, argv, actor)
        if rc2 is None:
            sys.stderr.write("fleet_api_key: no key for slot %d\n" % nxt)
            return EXIT_NO_KEY
        if (rc2 != 0 or declared_error(env2)) and reads_as_exhausted(raw2, env2):
            mark_exhausted(nxt)
            sys.stderr.write("fleet_api_key: both credits read as exhausted; "
                             "dispatch pauses until the next budget day\n")
            return EXIT_NO_KEY
        # A PAUSE IS LIFTED BY A TURN THAT WORKED, not by one that merely exited
        # 0 while reporting its own failure.
        if rc2 == 0 and not declared_error(env2):
            clear_pause()
        sys.stdout.write(text2)
        return rc2

    if rc == 0 and not declared_error(env1):
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
        # KEY MATERIAL FIRST, CREDIT SECOND. They are different questions and the
        # gate needs them apart: "paused" means both credits read as exhausted
        # and the next budget day re-probes by itself, while "no key" means
        # nothing will ever run until an item is created. Pre-fix this branch
        # asked only the second question and answered GREEN for the first (PR
        # #717 review round 2, finding 1).
        #
        # The words `no key` and `paused` are a contract with kipi-dispatch.sh,
        # which pages a different line for each. test-dispatch-api-key-gate.sh
        # runs THIS helper through the real gate rather than a stub, so the two
        # halves cannot drift.
        missing = missing_slots()
        if missing:
            note_missing_key(missing)
            print("no key %s" % ",".join(str(s) for s in missing))
            return EXIT_NO_KEY
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
