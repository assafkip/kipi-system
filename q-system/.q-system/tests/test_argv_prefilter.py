#!/usr/bin/env python3
"""ASK-1144: the every-position argv scan blew the hook's 5s timeout.

PR #279 major. The scan called argv_deny_reason once per token, and each call is
a command substitution -- a subshell fork -- that re-parses the remaining tokens.
Measured on one `git` stage before the fix:

    120 tokens   0.64s
    230 tokens   3.83s
    400 tokens  19.43s

settings.json wires this hook at timeout 5, and a hook that overruns its timeout
is KILLED with its verdict DISCARDED (already measured in this repo: a 0s hook
exiting 2 blocks, an 8s hook exiting 2 runs). So a long enough command line was a
bypass requiring no cleverness -- and the slow path is the BENIGN one, which is
every call the hook ever sees.

A pre-filter now skips positions that provably cannot deny. These cases exist
because that filter is a change to SECURITY behaviour, not just to speed: the
denies that could plausibly have been lost are the ones behind transparent
prefixes, so they are pinned here explicitly.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.environ.get(
    "KIPI_HOOK_UNDER_TEST",
    os.path.join(os.path.dirname(HERE), "hooks", "destructive-op-deny.sh"))

RM = "".join(["r", "m"])
RF = "-" + "".join(["r", "f"])
DANGER = "%s %s /tmp/probe" % (RM, RF)

# The hook's wired PreToolUse timeout. Anything slower is a discarded verdict.
HOOK_TIMEOUT_S = 5.0


def decision_for(command, timeout=120):
    home = tempfile.mkdtemp(prefix="argvprobe-")
    try:
        os.makedirs(os.path.join(home, ".claude", "audit"), exist_ok=True)
        env = dict(os.environ)
        env["HOME"] = home
        env.pop("ALLOW_DESTRUCTIVE", None)
        payload = {"tool_name": "Bash", "tool_input": {"command": command},
                   "cwd": "/tmp"}
        t0 = time.time()
        proc = subprocess.run(["bash", HOOK], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=timeout)
        elapsed = time.time() - t0
        if proc.returncode == 2:
            return "deny", elapsed
        out = (proc.stdout or "").strip()
        if not out:
            return "allow", elapsed
        try:
            return (json.loads(out)["hookSpecificOutput"]["permissionDecision"],
                    elapsed)
        except (ValueError, KeyError):
            return "error", elapsed
    finally:
        shutil.rmtree(home, ignore_errors=True)


@unittest.skipUnless(shutil.which("jq"), "the hook parses its payload with jq")
@unittest.skipUnless(os.path.isfile(HOOK), "no hook to drive at %s" % HOOK)
class ArgvPrefilterCase(unittest.TestCase):

    def test_a_long_benign_command_stays_well_under_the_timeout(self):
        """The bypass itself. 400 tokens took 19.43s before the pre-filter."""
        command = "git log --oneline " + " ".join(
            "--grep=w%d" % i for i in range(400))
        decision, elapsed = decision_for(command)
        self.assertEqual(decision, "allow")
        self.assertLess(elapsed, HOOK_TIMEOUT_S,
                        "the hook took %.2fs against a %.0fs timeout; an "
                        "overrunning hook is killed and its deny discarded"
                        % (elapsed, HOOK_TIMEOUT_S))

    def test_transparent_prefixes_still_deny(self):
        """What the pre-filter could plausibly have broken. Each of these has a
        head token that is NOT a recognised program, so each depends on the
        filter still letting that position through."""
        for prefix in ("sudo", "command", "nohup", "nice", "time", "env"):
            with self.subTest(prefix=prefix):
                self.assertEqual(decision_for("%s %s" % (prefix, DANGER))[0],
                                 "deny")

    def test_an_env_assignment_prefix_still_denies(self):
        """`FOO=bar rm -rf x`. The filter keeps `[!-]*=*` precisely for this."""
        self.assertEqual(decision_for("FOO=bar %s" % DANGER)[0], "deny")
        self.assertEqual(decision_for("A=1 B=2 %s" % DANGER)[0], "deny")

    def test_a_flag_shaped_assignment_does_not_hide_a_deny(self):
        """`--grep=x` is excluded from the filter for speed. Any deny after it is
        still reachable from the program token, which is always scanned -- so
        excluding it must not lose the verdict."""
        self.assertEqual(decision_for("--grep=x %s" % DANGER)[0], "deny")
        self.assertEqual(
            decision_for("git log --grep=x ; %s" % DANGER)[0], "deny")

    def test_a_deny_buried_after_many_flags_is_still_found(self):
        pad = " ".join("--grep=w%d" % i for i in range(200))
        decision, elapsed = decision_for("git log %s ; %s" % (pad, DANGER))
        self.assertEqual(decision, "deny")
        self.assertLess(elapsed, HOOK_TIMEOUT_S)

    def test_ordinary_commands_are_still_allowed(self):
        for command in ("ls -la", "git status", "echo hello"):
            with self.subTest(command=command):
                self.assertEqual(decision_for(command)[0], "allow")


if __name__ == "__main__":
    unittest.main(verbosity=2)
