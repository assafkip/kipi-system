#!/usr/bin/env python3
"""Pins hook_envelope_audit.py AND the fleet-shared hooks it audits.

Scar (measured 2026-08-30, q-system/.q-system/scripts/probe_hook_envelope.py):
Claude Code DISCARDS a hook's additionalContext unless it is nested under
hookSpecificOutput WITH hookEventName. voice-dna-loader.py shipped the nameless
shape from birth, so the founder's voice DNA never once reached the model, and
every downstream gate stayed green because they all measure the OUTPUT and none
check that the INPUT arrived.

Two halves, both of which have to be able to go red:
  1. the audit still tells the three measured shapes apart (its own self-test,
     including the arms that must NOT be flagged);
  2. every live hook in this repo emits the delivering shape.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
AUDIT = os.path.join(REPO, "q-system", ".q-system", "scripts", "hook_envelope_audit.py")


def _load():
    spec = importlib.util.spec_from_file_location("hook_envelope_audit", AUDIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


audit = _load()


def test_self_test_passes():
    """The audit can still separate the three measured shapes."""
    assert audit.self_test(verbose=False) == []


@pytest.mark.parametrize("src,expected", [
    ('import json,sys\nsys.stdout.write(json.dumps({"hookSpecificOutput": '
     '{"hookEventName": "UserPromptSubmit", "additionalContext": "x"}}))\n', audit.OK),
    ('import json,sys\nsys.stdout.write(json.dumps({"hookSpecificOutput": '
     '{"additionalContext": "x"}}))\n', audit.NO_EVENT_NAME),
    ('import json,sys\nsys.stdout.write(json.dumps({"additionalContext": "x"}))\n',
     audit.TOP_LEVEL),
])
def test_classifies_the_three_measured_shapes(src, expected):
    got = [s.verdict for s in audit.audit_python("<probe>", source=src)]
    assert got == [expected]


def test_reads_and_assertions_are_not_emissions():
    """The false-positive class that would get this gate switched off.

    Before the text scanner learned that a '[' before the key means a subscript
    and a missing ':' after it means an operand, the audit reported ~700 defects
    in the very hook tests that assert the envelope is correct.
    """
    reads = (
        'python3 -c "import sys,json; a=json.load(sys.stdin)'
        "['hookSpecificOutput']['additionalContext']\"\n"
        'assert "additionalContext" not in out\n'
        '# Scar: warn() printed top-level {"additionalContext": ...}\n'
    )
    assert audit.audit_text("<reads>", source=reads) == []


# --------------------------------------------------------------------------
# The live hooks. A new hook added with the nameless envelope turns these red.
# --------------------------------------------------------------------------
LIVE_HOOK_DIRS = [
    os.path.join(REPO, "q-system", ".q-system", "scripts"),
    os.path.join(REPO, "q-system", "hooks"),
    os.path.join(REPO, "plugins"),
]


def test_every_live_hook_emits_the_delivering_shape():
    sites = []
    for root in LIVE_HOOK_DIRS:
        if not os.path.isdir(root):
            continue
        for path in audit.walk([root]):
            sites.extend(audit.audit_file(path))
    assert sites, "audited nothing -- the walk is broken, not the hooks"
    bad = [(s.path, s.line, s.verdict) for s in sites if s.verdict != audit.OK]
    assert bad == [], (
        "these hooks emit an envelope Claude Code discards: %r" % (bad,))


@pytest.mark.parametrize("script,prompt", [
    ("voice-dna-loader.py", "draft a linkedin post about hooks"),
    ("lessons-inject.py", "fix the token guard cache race"),
])
def test_userpromptsubmit_hooks_deliver_end_to_end(script, prompt):
    """Not the source shape -- the bytes the hook actually prints."""
    path = os.path.join(REPO, "q-system", ".q-system", "scripts", script)
    payload = json.dumps({"session_id": "pytest",
                          "hook_event_name": "UserPromptSubmit",
                          "prompt": prompt})
    env = dict(os.environ, CLAUDE_PROJECT_DIR=REPO)
    proc = subprocess.run([sys.executable, path], input=payload, env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        pytest.skip("%s emitted nothing for this prompt" % script)
    out = json.loads(proc.stdout)
    assert "additionalContext" not in out, "top-level additionalContext is discarded"
    hso = out["hookSpecificOutput"]
    assert hso.get("hookEventName") == "UserPromptSubmit", hso
    assert hso.get("additionalContext", "").strip(), "delivered an empty payload"
