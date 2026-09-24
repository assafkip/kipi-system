#!/usr/bin/env python3
"""ASK-1144: `git push origin +main` is a force push and the hook allowed it.

PR #279 codex major. The push arm checked only FLAGS -- every spelling of
--force, --force-with-lease and a short f cluster -- and missed the form that
needs no flag at all. A leading-plus refspec rewrites remote history exactly as
a forced push does. Measured before the fix: three of these cases came back
`allow`.

Same shape ASK-1131 already found once: a rule that reads how the dangerous
thing is usually WRITTEN rather than what it DOES.

The allow-cases are not padding. A push guard that denies every push is an
outage, and `echo a+b` pins that a `+` outside refspec position does not trip it.

WHY THIS IS A unittest AND NOT A SCRIPT. The first version ran its probe at
module level and ended in sys.exit(). pytest COLLECTS this directory, so it
imported the module, the probe ran during collection, and the exit crashed the
whole run with INTERNALERROR -- one file taking down the suite it was added to.
That is the zero-execution class of ASK-1145 inverted: module-level work in a
file a collector imports. The work now lives inside test methods.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.environ.get(
    "KIPI_HOOK_UNDER_TEST",
    os.path.join(os.path.dirname(HERE), "hooks", "destructive-op-deny.sh"))

MUST_DENY = (
    "git push origin +main",
    "git push origin +refs/heads/main:refs/heads/main",
    "git push --atomic origin +main",
    "git push origin " + "--force",
)
MUST_ALLOW = (
    "git push origin main",
    "git push -u origin feature/x",
    "git push origin HEAD:branch",
    "echo a+b",
)


def decision_for(command):
    home = tempfile.mkdtemp(prefix="pushprobe-")
    try:
        os.makedirs(os.path.join(home, ".claude", "audit"), exist_ok=True)
        env = dict(os.environ)
        env["HOME"] = home
        env.pop("ALLOW_DESTRUCTIVE", None)
        payload = {"tool_name": "Bash", "tool_input": {"command": command},
                   "cwd": "/tmp"}
        proc = subprocess.run(["bash", HOOK], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=30)
        if proc.returncode == 2:
            return "deny"
        out = (proc.stdout or "").strip()
        if not out:
            return "allow"
        try:
            return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
        except (ValueError, KeyError):
            return "error"
    finally:
        shutil.rmtree(home, ignore_errors=True)


@unittest.skipUnless(shutil.which("jq"), "the hook parses its payload with jq")
@unittest.skipUnless(os.path.isfile(HOOK), "no hook to drive at %s" % HOOK)
class PushRefspecCase(unittest.TestCase):
    """A missing jq is skipped rather than failed: without it the hook cannot
    read any payload, so every case would come back `allow` and the suite would
    report a security hole that is really a missing dependency."""

    def test_leading_plus_refspecs_are_denied(self):
        for command in MUST_DENY:
            with self.subTest(command=command):
                self.assertEqual(decision_for(command), "deny")

    def test_ordinary_pushes_stay_allowed(self):
        for command in MUST_ALLOW:
            with self.subTest(command=command):
                self.assertEqual(decision_for(command), "allow")


if __name__ == "__main__":
    unittest.main(verbosity=2)
