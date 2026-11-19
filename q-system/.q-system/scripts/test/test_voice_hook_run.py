#!/usr/bin/env python3
"""Pins the voice hooks' ONE launcher, voice-hook-run.sh (ASK-4969 parts 1 and 2).

What it must hold:
  (1) no voice hook in settings-template.json runs a bare `python3`; the interpreter is
      resolved in one place (the launcher);
  (2) a voice hook fails CLOSED (exit 2) on a missing script, a payload that does not
      parse, a crash and a timeout; and the launcher's own bound is shorter than the
      harness timeout on the same hook, because the harness treats ITS timeout as a
      non-blocking error, which is a pass.

TEST ISOLATION: every run uses a temp script dir and a temp timing log. Nothing reads a
live corpus or ledger. CONTROL FIRST: test_clean_script_passes_through is the
verified-good control; without it every refusal below could come from a launcher that
refuses everything.
"""
import json
import os
import re
import stat
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
LAUNCHER = REPO / "q-system" / ".q-system" / "scripts" / "voice-hook-run.sh"
TEMPLATE = REPO / "settings-template.json"
GOOD_PAYLOAD = json.dumps({"tool_input": {"file_path": "x.md"}})


def _script(tmp_path, body, name="hook.py"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(body))
    return p


def _run(tmp_path, script, *, stdin=GOOD_PAYLOAD, timeout="5", extra=(), env=None):
    e = dict(os.environ, KIPI_VOICE_HOOK_LOG=str(tmp_path / "timing.jsonl"))
    e.pop("KIPI_VOICE_PYTHON", None)
    e.update(env or {})
    return subprocess.run(["bash", str(LAUNCHER), "--timeout", timeout, *extra, str(script)],
                          input=stdin, capture_output=True, text=True, env=e, timeout=60)


def _voice_hooks():
    data = json.loads(TEMPLATE.read_text())
    out = []
    for event, groups in data["hooks"].items():
        for g in groups:
            for h in g["hooks"]:
                if re.search(r"voice-(lint|substance-lint|stop-gate)|voiceloop-band-lint|"
                             r"voice-send|voice_send", h.get("command", "")):
                    out.append((event, h))
    return out


# ---- the control ----------------------------------------------------------------------

def test_clean_script_passes_through(tmp_path):
    s = _script(tmp_path, "import sys; sys.stdout.write(sys.stdin.read()); sys.exit(0)")
    r = _run(tmp_path, s)
    assert r.returncode == 0 and r.stdout == GOOD_PAYLOAD, (r.returncode, r.stderr)


def test_a_script_refusal_passes_through_as_2(tmp_path):
    s = _script(tmp_path, "import sys; print('no', file=sys.stderr); sys.exit(2)")
    r = _run(tmp_path, s)
    assert r.returncode == 2 and "no" in r.stderr


# ---- (2) fail closed ------------------------------------------------------------------

def test_missing_script_fails_closed(tmp_path):
    r = _run(tmp_path, tmp_path / "absent.py")
    assert r.returncode == 2 and "missing" in r.stderr


def test_crash_fails_closed(tmp_path):
    s = _script(tmp_path, "raise SystemExit(1)")
    r = _run(tmp_path, s)
    assert r.returncode == 2 and "crashed" in r.stderr


def test_unparseable_payload_fails_closed(tmp_path):
    s = _script(tmp_path, "import sys; sys.exit(0)")
    r = _run(tmp_path, s, stdin="{not json")
    assert r.returncode == 2 and "payload" in r.stderr


def test_empty_payload_fails_closed(tmp_path):
    s = _script(tmp_path, "import sys; sys.exit(0)")
    assert _run(tmp_path, s, stdin="").returncode == 2


def test_timeout_fails_closed_and_is_bounded(tmp_path):
    s = _script(tmp_path, "import time; time.sleep(30)")
    t0 = time.time()
    r = _run(tmp_path, s, timeout="1")
    assert r.returncode == 2 and "timed out" in r.stderr, r.stderr
    assert time.time() - t0 < 10


def test_timeout_kills_the_grandchild(tmp_path):
    """why: the ASK-3515 scar. A hook that spawned `uv run` left it holding the cache lock
    after its parent was killed. The whole process group goes."""
    marker = tmp_path / "alive"
    s = _script(tmp_path, """\
        import subprocess, sys, time
        subprocess.Popen([sys.executable, "-c",
            "import time, pathlib; time.sleep(3); pathlib.Path(%r).write_text('x')"])
        time.sleep(30)
        """ % str(marker))
    _run(tmp_path, s, timeout="1")
    time.sleep(4)
    assert not marker.exists(), "the grandchild outlived the timeout"


def test_stop_hook_active_fault_is_the_loop_breaker_not_a_pass_of_the_gate(tmp_path):
    """A Stop hook that holds forever never ends the turn. With stop_hook_active the
    FAULT exit is 0 (--stop-hook); a normal exit 2 from the script still passes through."""
    crash = _script(tmp_path, "raise SystemExit(1)", "crash.py")
    again = json.dumps({"stop_hook_active": True})
    first = json.dumps({"stop_hook_active": False})
    assert _run(tmp_path, crash, stdin=again, extra=["--stop-hook"]).returncode == 0
    assert _run(tmp_path, crash, stdin=first, extra=["--stop-hook"]).returncode == 2
    refuse = _script(tmp_path, "raise SystemExit(2)", "refuse.py")
    assert _run(tmp_path, refuse, stdin=again, extra=["--stop-hook"]).returncode == 2


def test_duration_is_measured(tmp_path):
    s = _script(tmp_path, "import sys; sys.exit(0)")
    _run(tmp_path, s)
    row = json.loads((tmp_path / "timing.jsonl").read_text().splitlines()[-1])
    assert row["script"] == "hook.py" and row["rc"] == 0 and row["seconds"] >= 0


# ---- (1) one pinned interpreter -------------------------------------------------------

def test_env_pin_wins(tmp_path):
    s = _script(tmp_path, "import sys; print(sys.executable)")
    pin = Path(os.popen("command -v python3").read().strip()).resolve()
    shim = tmp_path / "mypy"
    shim.write_text('#!/bin/sh\nexec %s "$@"\n' % pin)
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    r = _run(tmp_path, s, env={"KIPI_VOICE_PYTHON": str(shim)})
    assert r.returncode == 0, r.stderr


def test_a_broken_pin_fails_closed_not_to_another_python(tmp_path):
    """why: falling back past a bad pin is how two hooks end up on two interpreters."""
    s = _script(tmp_path, "import sys; sys.exit(0)")
    r = _run(tmp_path, s, env={"KIPI_VOICE_PYTHON": str(tmp_path / "nope")})
    assert r.returncode == 2 and "interpreter" in r.stderr


def test_the_script_runs_under_the_pinned_interpreter(tmp_path):
    s = _script(tmp_path, "import os, sys; sys.stdout.write(os.environ['KIPI_VOICE_PYTHON'])")
    shim = tmp_path / "pinned"
    real = Path(os.popen("command -v python3").read().strip())
    shim.write_text('#!/bin/sh\nexec %s "$@"\n' % real)
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    r = _run(tmp_path, s, env={"KIPI_VOICE_PYTHON": str(shim)})
    assert r.stdout == str(shim), r.stderr


# ---- the settings template ------------------------------------------------------------

def test_there_are_voice_hooks_to_check():
    assert len(_voice_hooks()) >= 5


def test_no_voice_hook_uses_a_bare_python3():
    bad = [h["command"][:90] for _, h in _voice_hooks()
           if re.search(r"(^|[\s;&|(])python3?\s", h["command"])]
    assert not bad, bad


def test_every_voice_hook_goes_through_the_launcher_with_a_shorter_bound():
    for event, h in _voice_hooks():
        cmd = h["command"]
        assert "voice-hook-run." in cmd, (event, cmd[:90])
        inner = float(re.search(r"--timeout\s+(\d+(?:\.\d+)?)", cmd).group(1))
        harness = h.get("timeout")
        assert harness is not None, ("no harness timeout set", cmd[:90])
        assert inner < harness, ("launcher bound must be below the harness timeout", inner, harness)


def test_a_missing_launcher_still_exits_2_in_the_hook_command():
    """The hook command is the only thing that runs when the launcher file is gone."""
    for event, h in _voice_hooks():
        if "voice-hook-run." not in h["command"]:
            continue
        env = dict(os.environ, CLAUDE_PROJECT_DIR="/nonexistent-instance")
        r = subprocess.run(["bash", "-c", h["command"]], input=GOOD_PAYLOAD, env=env,
                           capture_output=True, text=True, timeout=30)
        assert r.returncode == 2, (event, r.returncode, r.stderr[:200])
