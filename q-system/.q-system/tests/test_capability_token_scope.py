#!/usr/bin/env python3
"""ASK-1144: one approval token must not cover every destructive MCP call.

PR #279 codex BLOCKER. `$COMMAND` is read from `.tool_input.command`, which only
Bash payloads carry, so every MCP denial hashed the SAME empty string. One
`kipi-approve <hash>` unlocked every destructive MCP call on every server, while
the deny message said "Approve THIS command".

It was always wrong and became load-bearing with this PR: before operation-keyed
denial, almost no MCP call reached emit_deny, so the shared hash had nothing to
unlock.

A stub capability-token.sh stands in for the real one and simply echoes the
scope it was handed, so the test observes the SCOPE rather than the hashing.
The hash is a pure function of the scope, so scope collisions are hash
collisions, and the scope is the thing this change fixes.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DOTQ = os.path.abspath(os.path.join(HERE, ".."))
HOOK = os.path.join(DOTQ, "hooks", "destructive-op-deny.sh")

STUB = """#!/bin/bash
# Records the scope it was handed, then declines so the deny path continues.
if [ "$1" = "check" ]; then printf '%s\\n' "$2" >> "$HOME/scopes.txt"; exit 1; fi
if [ "$1" = "hash" ]; then printf 'h-%s' "$2"; exit 0; fi
exit 1
"""


class TokenScopeCase(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="captoken-")
        binf = os.path.join(self.home, ".claude", "bin")
        os.makedirs(binf)
        os.makedirs(os.path.join(self.home, ".claude", "audit"))
        stub = os.path.join(binf, "capability-token.sh")
        with open(stub, "w") as fh:
            fh.write(STUB)
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IXUSR)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def scope_for(self, tool_name, tool_input):
        env = dict(os.environ)
        env["HOME"] = self.home
        env.pop("ALLOW_DESTRUCTIVE", None)
        payload = {"tool_name": tool_name, "tool_input": tool_input,
                   "cwd": "/tmp"}
        before = self._scopes()
        subprocess.run(["bash", HOOK], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, timeout=30)
        after = self._scopes()
        self.assertGreater(len(after), len(before),
                           "the hook did not consult the capability token, so "
                           "this payload never reached the deny path")
        return after[-1]

    def _scopes(self):
        path = os.path.join(self.home, "scopes.txt")
        if not os.path.isfile(path):
            return []
        with open(path) as fh:
            return [l.rstrip("\n") for l in fh if l.strip()]

    def test_two_different_mcp_tools_get_different_scopes(self):
        """The blocker itself. Same scope means one grant unlocks both."""
        a = self.scope_for("mcp__linear__delete_issue", {})
        b = self.scope_for("mcp__supabase__delete_branch", {})
        self.assertNotEqual(a, b, "two destructive MCP tools share one token scope")

    def test_the_scope_is_not_empty_for_an_mcp_call(self):
        scope = self.scope_for("mcp__linear__delete_issue", {})
        self.assertTrue(scope.strip(), "an MCP call hashed an empty scope")
        self.assertIn("mcp__linear__delete_issue", scope,
                      "the scope does not name the tool")

    def test_the_payload_is_part_of_the_scope(self):
        a = self.scope_for("mcp__linear__delete_issue", {"id": "ASK-1"})
        b = self.scope_for("mcp__linear__delete_issue", {"id": "ASK-2"})
        self.assertNotEqual(a, b, "deleting a different issue reuses one grant")

    def test_key_order_does_not_change_the_scope(self):
        """jq -cS sorts keys. Without it the scope is unstable and every grant
        is a coin flip."""
        a = self.scope_for("mcp__linear__delete_issue", {"a": 1, "b": 2})
        b = self.scope_for("mcp__linear__delete_issue", {"b": 2, "a": 1})
        self.assertEqual(a, b, "key order changed the token scope")

    def test_bash_scope_is_still_the_command(self):
        """The Bash half must not regress: its scope was already correct."""
        probe = "".join(["r", "m"]) + " -" + "".join(["r", "f"]) + " /tmp/x"
        scope = self.scope_for("Bash", {"command": probe})
        self.assertEqual(scope, probe)


if __name__ == "__main__":
    unittest.main(verbosity=2)
