#!/usr/bin/env python3
"""knowledge-inject: put the instance's OWN facts about what the prompt names in
front of the model, before it reasons, with path and line and a coverage verdict.

UserPromptSubmit hook. Never blocks: exit 0 always, empty stdout on any error.
The read side of kb-graph-guard.py (the Stop hook that keeps graph.jsonl fresh).
Engine: knowledge_supply.py. Tests: test_knowledge_supply.py.

WHY (knowledge-supply plan, 2026-09-04): the two prompt-conditioned injectors
this repo had served fleet lessons and voice exemplars. A prompt naming a
client, a person, a promise or a capability got zero instance facts unless the
model decided to grep. That makes retrieval quality a property of the transient
session, which is the thesis violation the whole repo is built against.

WHY ZERO BYTES WHEN NOTHING MATCHES: voice-dna-loader.py carries the measured
result of a fixed 40 KB dump: output got WORSE. This fires only when the prompt
names something the index knows, and it says so in its first line.

Kill switch: KNOWLEDGE_INJECT_OFF=1 (the miyo-session-pull shape).

Envelope: hookSpecificOutput with hookEventName. Claude Code silently DISCARDS
a payload without hookEventName (measured 2026-08-30, probe_hook_envelope.py);
hook_envelope_audit.py holds that contract on every hook in this directory.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


def main() -> int:
    if os.environ.get("KNOWLEDGE_INJECT_OFF") == "1":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    prompt = payload.get("prompt") or ""
    if not prompt.strip():
        return 0
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd())
    session_id = str(payload.get("session_id") or "unknown-session")
    try:
        lib = Path(__file__).resolve().parent / "knowledge_supply.py"
        spec = importlib.util.spec_from_file_location("knowledge_supply", lib)
        ks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ks)
        bundle = ks.supply(root, prompt, session_id=session_id)
        if not bundle:
            return 0
        text = ks.render(bundle)
    except Exception:
        return 0
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": text,
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
