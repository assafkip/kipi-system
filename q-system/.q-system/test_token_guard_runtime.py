#!/usr/bin/env python3
"""Test the token-guard runtime guard (scar sp-28bf75a4).

token-guard is a Claude Code circuit breaker. Foreign runtimes that load the kipi
plugins (Codex via its own marketplace clone) must NOT run it -- a UserPromptSubmit
block killed an in-repo `codex exec` review. The guard no-ops when CLAUDECODE is
unset. This test proves BOTH: it no-ops outside Claude Code, and the breaker still
blocks under Claude Code (no regression).

Uses a sensitive-file Write payload, which blocks deterministically with no cache
state. Run: python3 q-system/.q-system/test_token_guard_runtime.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "token-guard.py")

# PreToolUse Write to a sensitive file -> check_sensitive_file blocks (exit 2),
# before any cache-dependent logic. Unique session id avoids touching real cache.
PAYLOAD = json.dumps({
    "hook_event_name": "PreToolUse",
    "session_id": "test-token-guard-runtime-fixture",
    "tool_name": "Write",
    "tool_input": {"file_path": "/tmp/fixture/.env"},
})


def run(claudecode):
    env = dict(os.environ)
    env.pop("CLAUDECODE", None)
    if claudecode:
        env["CLAUDECODE"] = "1"
    return subprocess.run([sys.executable, GUARD], input=PAYLOAD,
                          capture_output=True, text=True, env=env).returncode


def main():
    failures = []

    def check(label, ok):
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            failures.append(label)

    no_cc = run(claudecode=False)
    with_cc = run(claudecode=True)

    # Outside Claude Code: guard no-ops, sensitive-file block does NOT fire.
    check("CLAUDECODE unset -> exit 0 (guard no-ops, Codex-safe)", no_cc == 0)
    # Under Claude Code: the breaker still blocks the sensitive write.
    check("CLAUDECODE=1 -> exit 2 (breaker still enforces, no regression)", with_cc == 2)

    # clean up the fixture cache file if the guarded run wrote one
    for sid in ("test-token-guard-runtime-fixture",):
        p = f"/tmp/claude-guard-{sid}.json"
        if os.path.exists(p):
            os.remove(p)

    if failures:
        print(f"\nFAILED: {failures}")
        sys.exit(1)
    print("\nOK: runtime guard works both directions")
    sys.exit(0)


if __name__ == "__main__":
    main()
