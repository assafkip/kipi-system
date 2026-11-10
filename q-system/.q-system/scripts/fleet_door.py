#!/usr/bin/env python3
"""How a PYTHON fleet call site reaches `claude` (ASK-4311). The shell sites use
fleet-claude.sh; this is the same door for Python, over the same helper.

WHY A SECOND FRONT END AND NOT JUST fleet-claude.sh. A Python site resolves its
own binary (launchd's PATH is thin, so linear-alert-triage.py probes a login
shell and the drafter walks a list of install paths), and it needs a
`subprocess.run`-shaped answer back. Handing that resolved path to the shim would
throw the resolution away. So every Python site calls `run()` here, and `run()`
calls `fleet_api_key.py exec -- <the site's own argv>`. One helper still reads the
Keychain, picks the key and writes the spend ledger; nothing here does any of it.

TWO DOORS, BY WHO LAUNCHED THE RUN (founder, 2026-11-09: fleet work moves to the
API credit, his own session work stays on the plan):
  run()             always the key. For unattended jobs: launchd, the dispatcher.
  run_for_caller()  the key when the CALLER is a fleet run, the plan otherwise.
                    For tools that run inside whichever session called them (a
                    token-guard hook, an eval an agent starts by hand), so a tool
                    run in the founder's own session never changes what his
                    session bills. "A fleet run" is read from the environment the
                    parent left: the helper sets KIPI_FLEET_KEY_SLOT in every run
                    it starts, and a launchd fleet job that calls such a tool sets
                    KIPI_FLEET_RUN=1 for its children.

NO FALLBACK TO THE PLAN WHEN A KEY IS MISSING. The helper refuses (exit 4 no key
or paused, 5 the month's credit gone) and this module says so on the caller's
own stderr, because a silent fallback is the bug this whole change exists to end:
the run would succeed, the founder would pay, and nothing would say so.
KIPI_FLEET_API_KEYS=0 is the one deliberate way back to the plan, the same switch
fleet-claude.sh honours, and it is announced on every call.

A TIMEOUT STOPS THE WHOLE RUN, NOT ONLY THE HELPER. `subprocess.run(timeout=)`
SIGKILLs the direct child only. Through the door the direct child is the helper,
so the billed `claude` underneath would keep running as an orphan and its cost
would never reach the ledger. The run starts in its own session and a timeout
sends SIGTERM to the whole group first: the helper's handler records the run as
unmetered and kills its child, then a SIGKILL sweeps whatever is left.

A TEST NEVER REACHES THE REAL KEYCHAIN. The helper reads fake keys only under
KIPI_TEST=1, and most existing suites never set it (4 of them did on 2026-11-10).
So the door sets it itself when the run is plainly a test: KIPI_TEST=1 already,
pytest running, or a binary that resolves under the temp root (where every fake
`claude` in this repo lives; no real install does). In that mode an unset ledger
path is pointed at a temp dir too. A test with no fake key then gets exit 4, which
fails it loudly, instead of a real key handed to a fake that records its env.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(HERE, "fleet_api_key.py")
KEY = "ANTHROPIC_API_KEY"

#: The helper's refusal codes (fleet_api_key.py EXIT_NO_KEY / EXIT_CREDIT_GONE).
EXIT_NO_KEY = 4
EXIT_CREDIT_GONE = 5

#: SIGTERM first so the helper can record the killed run, then SIGKILL.
STOP_GRACE_SECONDS = 10

_LEDGER_VARS = ("KIPI_FLEET_SPEND_LEDGER", "KIPI_FLEET_EVENTS", "KIPI_FLEET_STATE")
_LEDGER_FILES = {"KIPI_FLEET_SPEND_LEDGER": "spend.jsonl",
                 "KIPI_FLEET_EVENTS": "events.jsonl",
                 "KIPI_FLEET_STATE": "state.json"}
_TEST_DIR = {}


def plan_env(env=None):
    """The environment minus the API key: what a plan-billed `claude` runs in."""
    src = os.environ if env is None else env
    return {k: v for k, v in src.items() if k != KEY}


def in_fleet_run(env=None):
    """Did a fleet run launch this one? (See run_for_caller.)"""
    src = os.environ if env is None else env
    return bool(src.get("KIPI_FLEET_KEY_SLOT")) or src.get("KIPI_FLEET_RUN") == "1"


def _temp_roots():
    roots = {tempfile.gettempdir(), "/tmp", "/private/tmp", "/var/folders",
             "/private/var/folders"}
    return {os.path.realpath(r) for r in roots}


def _resolve(binary, env):
    if not binary:
        return None
    if os.sep in binary:
        return os.path.realpath(binary)
    found = shutil.which(binary, path=env.get("PATH"))
    return os.path.realpath(found) if found else None


def in_test(cmd, env):
    if env.get("KIPI_TEST") == "1" or os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    path = _resolve(cmd[0] if cmd else None, env)
    return bool(path) and any(path == r or path.startswith(r + os.sep)
                              for r in _temp_roots())


def door_env(cmd, env=None):
    """The helper's environment. Never an inherited key: the helper injects its own."""
    out = plan_env(env)
    if in_test(cmd, out):
        out["KIPI_TEST"] = "1"
        if any(not out.get(k) for k in _LEDGER_VARS):
            d = _TEST_DIR.get("dir")
            if not d or not os.path.isdir(d):
                d = _TEST_DIR["dir"] = tempfile.mkdtemp(prefix="fleet-door-test-")
            for k in _LEDGER_VARS:
                if not out.get(k):
                    out[k] = os.path.join(d, _LEDGER_FILES[k])
    return out


def door_argv(cmd, actor):
    return [sys.executable, HELPER, "exec", "--actor", actor, "--"] + list(cmd)


def _stop(proc):
    """SIGTERM the run's whole process group, then SIGKILL what is left."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except OSError:
        return
    try:
        proc.wait(timeout=STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _spawn(argv, cmd, input=None, timeout=None, check=False, capture_output=False,
           env=None, **kw):
    """subprocess.run's contract, with the run in its own process group."""
    if input is not None:
        if kw.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used.")
        kw["stdin"] = subprocess.PIPE
    if capture_output:
        if kw.get("stdout") is not None or kw.get("stderr") is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output.")
        kw["stdout"] = kw["stderr"] = subprocess.PIPE
    proc = subprocess.Popen(argv, env=env, start_new_session=True, **kw)
    try:
        out, err = proc.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop(proc)
        try:
            out, err = proc.communicate(timeout=STOP_GRACE_SECONDS)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            out = err = None
        raise subprocess.TimeoutExpired(cmd, timeout, output=out, stderr=err)
    except BaseException:
        _stop(proc)
        raise
    rc = proc.poll()
    if check and rc:
        raise subprocess.CalledProcessError(rc, cmd, out, err)
    return subprocess.CompletedProcess(cmd, rc, out, err)


def _say_refusal(actor, res):
    if res.returncode not in (EXIT_NO_KEY, EXIT_CREDIT_GONE):
        return
    err = res.stderr
    if isinstance(err, bytes):
        err = err.decode("utf-8", "replace")
    lines = [ln for ln in (err or "").splitlines() if ln.startswith("fleet_api_key:")]
    if not lines:
        return  # the child's own exit code, or the helper's line already reached stderr
    sys.stderr.write("fleet_door: %s was refused by the fleet key door (exit %d) and did "
                     "NOT fall back to the plan: %s\n" % (actor, res.returncode, lines[-1]))
    sys.stderr.flush()


def run(cmd, actor, env=None, **kw):
    """`subprocess.run(cmd, ...)`, billed to a fleet API key. For unattended jobs."""
    src = os.environ if env is None else env
    if src.get("KIPI_FLEET_API_KEYS", "1") == "0":
        sys.stderr.write("fleet_door: KIPI_FLEET_API_KEYS=0 -- %s bills the PLAN, not the "
                         "API credit\n" % actor)
        sys.stderr.flush()
        return _spawn(list(cmd), list(cmd), env=plan_env(src), **kw)
    res = _spawn(door_argv(cmd, actor), list(cmd), env=door_env(cmd, src), **kw)
    _say_refusal(actor, res)
    return res


def run_for_caller(cmd, actor, env=None, **kw):
    """The key inside a fleet run, the plan (key stripped) inside anyone else's."""
    src = os.environ if env is None else env
    if in_fleet_run(src):
        return run(cmd, actor, env=env, **kw)
    return _spawn(list(cmd), list(cmd), env=plan_env(src), **kw)


def runner(actor):
    """run() as a drop-in for subprocess.run (lean_call.run(runner=), run_model(run=))."""
    def _run(cmd, **kw):
        return run(cmd, actor, **kw)
    _run.fleet_door = ("run", actor)  # what a site's test asserts it was handed
    return _run


def runner_for_caller(actor):
    def _run(cmd, **kw):
        return run_for_caller(cmd, actor, **kw)
    _run.fleet_door = ("run_for_caller", actor)
    return _run
