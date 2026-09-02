#!/usr/bin/env python3
"""The two headless `claude -p` jobs fixed for C-1 / C-2 must name their model.

WHY THIS TEST EXISTS

Scar 2026-08-01: headless jobs that passed no model inherited the interactive
default, rode Fable, and burned 3% of the weekly budget in an hour. The fleet
answer was "pin every headless job to claude-opus-5", but the pin was put in
launchd plists and shell wrappers -- and a wrapper is not a chokepoint. Both
scripts here are normally started BY HAND, so the wrapper never loads and the
pin never applies. C-1 (`linear-triage.py`) had no --model at any layer at all;
C-2 (`granola-voice-synthesize.py`) had an `if MODEL:` branch whose default was
the empty string, so it emitted no --model on exactly the run a human starts.

So the pin now lives in each script's own argv, and this file asserts THE ARGV,
not the constant. Asserting the constant would pass against a script that
computes the right model and then forgets to put it on the command line.

WHY IT CAN BE POINTED AT A COPY

PIN_TEST_TRIAGE / PIN_TEST_GRANOLA override the script paths. That is the hatch
for the negative self-test: point them at a mutated copy with the pin removed
and watch these cases go RED. A regression test that has never been watched fail
is a decoration. Do not delete the hatch to "simplify".

Run: python3 -m pytest q-system/.q-system/tests/test_headless_model_pin.py -v
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "q-system" / ".q-system" / "scripts"

TRIAGE_PATH = Path(os.environ.get("PIN_TEST_TRIAGE") or (SCRIPTS / "linear-triage.py"))
GRANOLA_PATH = Path(
    os.environ.get("PIN_TEST_GRANOLA") or (SCRIPTS / "granola-voice-synthesize.py")
)

PIN = "claude-opus-5"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeCompleted:
    def __init__(self, stdout: str):
        self.returncode = 0
        self.stdout = stdout
        self.stderr = ""


class _FakeSubprocess:
    """Stands in for the `subprocess` module INSIDE the script under test.

    Set on the module object, not on the real subprocess module, so a failure
    here cannot leak into any other test in the same session.
    """

    DEVNULL = -3
    PIPE = -1

    class TimeoutExpired(Exception):
        pass

    def __init__(self, stdout: str = ""):
        self.calls: list[list[str]] = []
        self._stdout = stdout

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        return _FakeCompleted(self._stdout)


def _model_flag(argv: list[str]) -> str | None:
    """The value the CLI would actually use, read the way the CLI reads it."""
    for i, tok in enumerate(argv):
        if tok == "--model" and i + 1 < len(argv):
            return argv[i + 1]
        if tok.startswith("--model="):
            return tok.split("=", 1)[1]
    return None


# --- linear-triage.py (C-1) ------------------------------------------------


def _triage_argv(monkeypatch, env: dict) -> list[str]:
    for key in ("KIPI_TRIAGE_MODEL", "ANTHROPIC_MODEL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    mod = _load(TRIAGE_PATH, "triage_under_test")
    fake = _FakeSubprocess(stdout="")
    monkeypatch.setattr(mod, "subprocess", fake)
    # The real resolver imports a sibling script off disk; the model pin does not
    # depend on which binary it finds, and a real resolve makes this test slow
    # and machine-dependent.
    monkeypatch.setattr(mod, "claude_binary", lambda: "/nonexistent/claude")
    # Fields copied from the script's OWN GraphQL selection set (ISSUES_QUERY,
    # `nodes{id identifier title description createdAt state{name type}
    # project{name} labels{nodes{name}} comments{nodes{id body}}}`) rather than
    # invented. An invented fixture tests my guess at the producer, and the
    # first draft of this one omitted `comments` and blew up inside
    # structural_flags instead of reaching the argv.
    issue = {
        "id": "uuid-1",
        "identifier": "ASK-1",
        "title": "t",
        "description": "body",
        "createdAt": "2026-09-01T00:00:00.000Z",
        "state": {"name": "Backlog", "type": "backlog"},
        "project": None,
        "labels": {"nodes": []},
        "comments": {"nodes": []},
    }
    mod.judge_batch([issue], 5)
    assert fake.calls, "judge_batch never invoked subprocess.run"
    return fake.calls[0]


def test_triage_pins_model_by_default(monkeypatch):
    argv = _triage_argv(monkeypatch, {})
    assert _model_flag(argv) == PIN, f"linear-triage argv is unpinned: {argv}"


def test_triage_env_override_wins(monkeypatch):
    argv = _triage_argv(monkeypatch, {"KIPI_TRIAGE_MODEL": "claude-sonnet-5"})
    assert _model_flag(argv) == "claude-sonnet-5"


def test_triage_empty_env_falls_back_to_pin(monkeypatch):
    """An exported-but-empty var is the shape that silently unpinned C-2."""
    argv = _triage_argv(monkeypatch, {"KIPI_TRIAGE_MODEL": ""})
    assert _model_flag(argv) == PIN, f"empty env var dropped the pin: {argv}"


def test_triage_still_sends_the_prompt(monkeypatch):
    """Guards the fix itself: inserting a flag must not displace the prompt."""
    argv = _triage_argv(monkeypatch, {})
    assert argv[1] == "-p"
    body = [a for a in argv if "senior staff engineer" in a]
    assert body, f"prompt text is no longer in argv: {argv}"


# --- granola-voice-synthesize.py (C-2) -------------------------------------


def _granola_argv(monkeypatch, env: dict) -> list[str]:
    for key in ("VOICE_SYNTH_MODEL", "ANTHROPIC_MODEL"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    mod = _load(GRANOLA_PATH, "granola_under_test")
    fake = _FakeSubprocess(stdout="[]")
    monkeypatch.setattr(mod, "subprocess", fake)
    mod.run_claude("corpus text")
    assert fake.calls, "run_claude never invoked subprocess.run"
    return fake.calls[0]


def test_granola_pins_model_by_default(monkeypatch):
    argv = _granola_argv(monkeypatch, {})
    assert _model_flag(argv) == PIN, f"granola argv is unpinned: {argv}"


def test_granola_env_override_wins(monkeypatch):
    argv = _granola_argv(monkeypatch, {"VOICE_SYNTH_MODEL": "claude-sonnet-5"})
    assert _model_flag(argv) == "claude-sonnet-5"


def test_granola_empty_env_falls_back_to_pin(monkeypatch):
    """The literal C-2 defect: MODEL defaulted to "" and --model was dropped."""
    argv = _granola_argv(monkeypatch, {"VOICE_SYNTH_MODEL": ""})
    assert _model_flag(argv) == PIN, f"empty env var dropped the pin: {argv}"


def test_granola_still_sends_its_instruction(monkeypatch):
    argv = _granola_argv(monkeypatch, {})
    assert argv[1] == "-p"
    assert any("raw JSON array" in a for a in argv), f"instruction lost: {argv}"


# --- the pin is a real model id -------------------------------------------


@pytest.mark.parametrize("path,attr", [("triage", "TRIAGE_MODEL"), ("granola", "DEFAULT_MODEL")])
def test_pin_constant_matches_argv(monkeypatch, path, attr):
    """Catches a split where the constant is updated and the argv is not."""
    if path == "triage":
        mod = _load(TRIAGE_PATH, "triage_const")
        argv = _triage_argv(monkeypatch, {})
    else:
        mod = _load(GRANOLA_PATH, "granola_const")
        argv = _granola_argv(monkeypatch, {})
    assert getattr(mod, attr) == _model_flag(argv)
