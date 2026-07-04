#!/usr/bin/env python3
"""Validator for the /voice-refresh command (issue voice-refresh-command).

Runnable directly (`python3 automation/test_voice_refresh_command.py`): asserts
the command file has frontmatter, is discoverable in the kipi-core commands dir
(that is how kipi slash commands register), invokes harvest + the orchestrator,
and NEVER instructs an unattended write to voice-dna.md. Exits non-zero on fail.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CMD = os.path.join(ROOT, "plugins", "kipi-core", "commands", "voice-refresh.md")


def test_command_exists_and_has_frontmatter():
    assert os.path.exists(CMD), f"command not in the kipi-core commands dir: {CMD}"
    body = open(CMD).read()
    assert body.startswith("---"), "command must open with YAML frontmatter"
    assert "description:" in body.split("---", 2)[1], "frontmatter needs a description"


def test_command_wires_pipeline():
    body = open(CMD).read()
    assert "granola-voice-harvest.py" in body, "must run Stage 1 harvest"
    assert "automation/voice_refresh.py" in body, "must run the orchestrator"


def test_command_never_auto_writes_voice_dna():
    body = open(CMD).read().lower()
    # It must name voice-dna.md only in the context of a founder-gated / never-write rule.
    assert "founder-gated" in body or "founder approves" in body, "merge must be founder-gated"
    assert "never" in body and "voice-dna.md" in body, "must state it never writes voice-dna.md directly"


def _main():
    failures = []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                failures.append(f"FAIL {name}: {e}")
    for f in failures:
        print(f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    _main()
