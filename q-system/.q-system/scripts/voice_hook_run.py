#!/usr/bin/env python3
"""Runs one voice hook script and turns every fault into a block (ASK-4969 part 2).

    voice_hook_run.py [--timeout S] [--stop-hook] <script> [args...]    (payload on stdin)

A hook exit of 2 blocks; any other nonzero is a NON-BLOCKING error to the harness, and the
harness's own timeout is also non-blocking. Both read as a pass. So here:
  - script missing, payload not JSON (or empty), script exit other than 0 or 2, and a
    script that runs past --timeout are all exit 2;
  - --timeout is chosen BELOW the harness timeout on the same hook (a test reads
    settings-template.json and holds that), so this runner always speaks first;
  - on timeout the whole process group is killed. why (ASK-3515): a `uv run` grandchild
    survived its killed parent and held the uv cache lock.
--stop-hook: a Stop hook that holds forever never ends the turn, so when the payload says
stop_hook_active the FAULT exit is 0 (the second pass). A script's own exit 2 still blocks.

Every run appends one row to the timing log (KIPI_VOICE_HOOK_LOG, default
~/.local/state/kipi/voice-hook-timing.jsonl), so the bounds are measured, not guessed.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

LOG_ENV = "KIPI_VOICE_HOOK_LOG"
DEFAULT_LOG = Path.home() / ".local" / "state" / "kipi" / "voice-hook-timing.jsonl"
DRAIN_S = 5


def _log(script: str, rc: int, seconds: float, why: str = "") -> None:
    path = Path(os.environ.get(LOG_ENV) or DEFAULT_LOG)
    row = json.dumps({"ts": int(time.time()), "script": Path(script).name, "rc": rc,
                      "seconds": round(seconds, 3), "why": why})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # One short O_APPEND write is atomic across concurrent hooks; this file has no other writer.
        fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (row + "\n").encode())
        finally:
            os.close(fd)
    except OSError:
        pass  # the log is a measurement, never a reason to change the verdict


def main(argv: list[str]) -> int:
    timeout, stop_hook, rest = 25.0, False, list(argv)
    while rest and rest[0].startswith("--"):
        flag = rest.pop(0)
        if flag == "--timeout" and rest:
            timeout = float(rest.pop(0))
        elif flag == "--stop-hook":
            stop_hook = True
        else:
            print("voice_hook_run: unknown flag %s" % flag, file=sys.stderr)
            return 2
    if not rest:
        print("voice_hook_run: no script given", file=sys.stderr)
        return 2
    script, args = rest[0], rest[1:]
    payload = sys.stdin.read()
    try:
        parsed = json.loads(payload)
    except ValueError:
        parsed = None
    # why the parsed value first: a message that QUOTES "stop_hook_active": true is escaped
    # JSON, not the field. The regex is only for a payload that does not parse at all.
    if isinstance(parsed, dict):
        active = parsed.get("stop_hook_active") is True
    else:
        active = bool(re.search(r'"stop_hook_active"\s*:\s*true', payload))
    fault_rc = 0 if (stop_hook and active) else 2

    def fault(msg: str, seconds: float = 0.0) -> int:
        tail = msg.split("|")[1] if "|" in msg else ""
        print("%s %s: the gate cannot run%s" % (script, msg.split("|")[0], tail), file=sys.stderr)
        _log(script, fault_rc, seconds, msg)
        return fault_rc

    if not Path(script).is_file():
        return fault("missing|. Restore it: kipi " + "update")
    if not isinstance(parsed, dict):
        return fault("got a hook payload that did not parse as a JSON object")
    t0 = time.time()
    interp = os.environ.get("KIPI_VOICE_PYTHON") or sys.executable
    cmd = [interp, script, *args] if script.endswith(".py") else [script, *args]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as exc:
        return fault("could not start (%s)" % exc)
    try:
        out, err = proc.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            proc.communicate(timeout=DRAIN_S)
        except subprocess.TimeoutExpired:
            pass
        return fault("timed out after %ss" % timeout, time.time() - t0)
    secs = time.time() - t0
    if proc.returncode not in (0, 2):
        sys.stderr.write(err or "")
        return fault("crashed (exit %s)" % proc.returncode, secs)
    sys.stdout.write(out or "")
    sys.stderr.write(err or "")
    _log(script, proc.returncode, secs)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
