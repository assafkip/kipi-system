#!/usr/bin/env python3
"""Pins voice-dna-loader.py as advisory supply (inventory row H-voice-dna-loader, ASK-5398 ruling).

why this exists: the 2026-11-16 voice-loop inventory listed this hook next to the exits.
It is not one. It adds the voice corpus to context and must never block a prompt: a
loader that refused would hold up every turn that says "post", and a loader that claimed
to check would read as coverage (the ASK-4637 census, "checked means some check ran").
So two things are pinned: it exits 0 and never emits a block decision on any input, and
its docstring names it advisory and says no exit counts it.

CONTROL FIRST: test_the_block_detector_can_fire proves the checker catches a block.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "voice-dna-loader.py"


def run(stdin, tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_PROJECT_DIR")}
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)  # an empty instance: no corpus, no plugins
    env["HOME"] = str(tmp_path)
    return subprocess.run([sys.executable, str(SCRIPT)], input=stdin, capture_output=True,
                          text=True, env=env, cwd=str(tmp_path), timeout=60)


def blocks(stdout):
    try:
        out = json.loads(stdout) if stdout.strip() else {}
    except ValueError:
        return False
    return out.get("decision") == "block" or out.get("continue") is False


def test_the_block_detector_can_fire():
    assert blocks('{"decision": "block"}')
    assert not blocks('{"hookSpecificOutput": {"additionalContext": "x"}}')


def test_it_exits_zero_and_never_blocks_on_any_input(tmp_path):
    inputs = [
        "not json",
        json.dumps({"prompt": ""}),
        json.dumps({"prompt": "what time is it"}),
        json.dumps({"prompt": "draft a linkedin post about detection debt"}),
    ]
    for stdin in inputs:
        r = run(stdin, tmp_path)
        assert r.returncode == 0, (stdin, r.returncode, r.stderr[-400:])
        assert not blocks(r.stdout), stdin


def test_it_says_it_is_advisory_and_not_the_voice_loop():
    head = SCRIPT.read_text()[:2500]
    assert "Advisory supply, not the voice loop" in head
    assert "no exit counts it" in head
