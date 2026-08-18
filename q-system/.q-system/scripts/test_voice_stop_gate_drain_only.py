#!/usr/bin/env python3
"""The last post of a session surfaces its score (ASK-902, sp-08c34cf1).

The Stop-hook drain runs on the NEXT Stop event, and an idle session has no next
Stop -- confirmed against the hooks documentation rather than assumed. So the
score for the last post he wrote reached him only if he happened to write
another one.

`--drain-only` is the surface-only mode the SessionEnd and SessionStart hooks
call. What this file holds:

  - it surfaces a pending line as `systemMessage`, the one hook field that puts
    text in front of HIM rather than the model, and exits 0
  - it NEVER runs the voice lint, whatever the payload says. That half exists to
    block a turn, and there is no turn to block at session start or session end
  - it costs nothing and never blocks when there is nothing pending

The mode is driven by argv, not by sniffing `hook_event_name` off the payload:
keying the lint's safety on a schema field nobody in this repo controls is how a
gate ends up firing on an event it was never meant to see.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

STOP_GATE = Path(__file__).resolve().parent / "voice-stop-gate.py"


def _run(argv, payload="", env=None):
    return subprocess.run(
        [sys.executable, str(STOP_GATE)] + argv,
        input=payload, capture_output=True, text=True, timeout=60,
        env=dict(os.environ, **(env or {})))


def test_drain_only_exits_zero_with_nothing_pending():
    """The common case by far. It must be free and it must never block."""
    started = time.time()
    r = _run(["--drain-only"], payload=json.dumps({"hook_event_name": "SessionEnd"}))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", r.stdout
    assert time.time() - started < 5.0


def test_drain_only_ignores_a_payload_it_cannot_parse():
    """SessionStart and SessionEnd payloads are not this file's schema. A mode
    whose job is to surface a number must not fail on the envelope."""
    r = _run(["--drain-only"], payload="not json at all")
    assert r.returncode == 0, r.stderr


def test_drain_only_never_runs_the_voice_lint():
    """THE property that makes this safe to wire on two more events.

    A draft-shaped message with a voice violation exits 2 on the Stop path. On
    this path there is no turn to re-draft, so blocking would strand the session
    with no way forward.
    """
    bad = "here's the post for linkedin\n\n```\n" + ("lowercase opener. " * 40) + "\n```\n"
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps({"message": {"role": "user", "content": [
            {"type": "text", "text": "write me a post"}]}}) + "\n")
        fh.write(json.dumps({"message": {"role": "assistant", "content": [
            {"type": "text", "text": bad}]}}) + "\n")
    try:
        r = _run(["--drain-only"], payload=json.dumps({"transcript_path": path}))
        assert r.returncode == 0, (
            "the surface-only mode ran the lint and blocked; there is no turn "
            "to re-draft at session start or session end")
        assert "violation" not in r.stderr.lower(), r.stderr
    finally:
        os.unlink(path)


def test_the_stop_path_still_reaches_the_lint():
    """The paired half. Without it the test above passes on a file that stopped
    linting entirely, and the Stop gate is the thing protecting his drafts."""
    bad = "here's the post for linkedin\n\n```\n" + ("lowercase opener. " * 40) + "\n```\n"
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps({"message": {"role": "user", "content": [
            {"type": "text", "text": "write me a post"}]}}) + "\n")
        fh.write(json.dumps({"message": {"role": "assistant", "content": [
            {"type": "text", "text": bad}]}}) + "\n")
    try:
        r = _run([], payload=json.dumps({"transcript_path": path}))
    finally:
        os.unlink(path)
    assert r.returncode == 2, (
        "the Stop path no longer blocks a voice violation; the drain-only test "
        "above is asserting nothing")


@pytest.mark.parametrize("event", ["SessionEnd", "SessionStart"])
def test_a_pending_line_reaches_him_as_a_system_message(event, tmp_path):
    """END TO END through the deployed file, both events.

    KIPI_STATE_HOME aims the reporter at tmp, so this never reads or deletes the
    founder's live spool.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("_vsg_drain", STOP_GATE)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    reporter = gate.resolve_reporter(gate.INSTANCE_ROOT)
    if reporter is None or not Path(reporter).is_file():
        pytest.skip("no corpus-similarity reporter resolves from this repo")

    state_home = tmp_path / "state"
    env = {"KIPI_STATE_HOME": str(state_home)}
    line = "corpus similarity 0.4220 -- mid band, 78 words, n=18"
    published = subprocess.run(
        [sys.executable, "-c",
         "import sys;sys.path.insert(0,%r);"
         "import importlib.util as u;"
         "s=u.spec_from_file_location('r',%r);m=u.module_from_spec(s);"
         "s.loader.exec_module(m);"
         "m._publish(%r, m.state_dir_for(%r))"
         % (str(Path(reporter).parent.parent), str(reporter), line,
            str(gate.INSTANCE_ROOT))],
        capture_output=True, text=True,
        env=dict(os.environ, **env), timeout=60)
    assert published.returncode == 0, published.stderr

    r = _run(["--drain-only"], payload=json.dumps({"hook_event_name": event}),
             env=env)
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout.strip())
    assert payload["systemMessage"].startswith(line), payload
    # Drained means consumed. A line surfaced twice reads as two scores.
    again = _run(["--drain-only"], payload="{}", env=env)
    assert again.stdout.strip() == "", again.stdout


if __name__ == "__main__":
    # The capability gate runs this file as `python3 <file>` (runner=python3).
    # Without this block that invocation executes ZERO assertions and exits 0 --
    # a test that cannot fail (Codex major on PR #217). pytest.main returns its
    # own exit code, so a gutted feature now reds the gate.
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, "-q"]))
