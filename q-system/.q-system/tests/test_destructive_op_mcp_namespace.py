#!/usr/bin/env python3
"""ASK-1144: the MCP half of destructive-op-deny names servers that are not loaded.

READ-ONLY on ~/.claude. Every case drives a COPY of the hook in a tmp dir, the
same discipline test_destructive_op_deny_anchor.py established: an agent that can
write destructive-op-deny.sh can disable its own gates, and claude-path-write-guard
is right to refuse it. The fix lands through apply-claude-changes, never from here.

THE DEFECT, measured 2026-08-29
-------------------------------
The founder's CLAUDE.md lists, as NON-NEGOTIABLE and hook-blocked:

    Notion `move-pages`/`delete*`, Gmail `delete_label`,
    Linear `*delete*`, Vercel mutating ops

The hook's MCP case names `mcp__plugin_linear_linear__*`. The LOADED Linear
server is `mcp__linear__*`. `grep -c mcp__linear__` on the live hook returns 0,
and so does `grep -c supabase` while `mcp__supabase__delete_branch` sits in the
live tool roster. The rule is stated, the gate is wired, the pattern matches
nothing. A check that runs, passes, and is structurally blind to what it exists
to catch.

WHY OPERATION-KEYED AND NOT A WIDER WILDCARD
--------------------------------------------
Adding `mcp__linear__*` and `mcp__supabase__*` would close these two and re-open
the defect on the next server whose name nobody guessed -- and it would deny
`mcp__linear__list_issues`, which is the over-block major already open on PR #274.
The stable half of an MCP tool name is the OPERATION, not the vendor: every
server that deletes spells it `delete`. So the deny keys on the operation
segment, and the vendor segment stops mattering.

The `un` guard is load-bearing and has live subjects: `untrash_message` and
`untrash_thread` RESTORE a message and both contain `trash`. A verb list without
it turns the recovery path into a blocked path.

THE SECOND HALF
---------------
Operation-keying makes a MISSING namespace harmless. It does not make a DEAD
namespace visible, and a dead entry is what let this survive: someone read
`mcp__plugin_linear_linear__*` and saw Linear covered. So
`mcp-denylist-namespace-check.py` compares every namespace the hook names against
the servers actually registered, and goes red on one that matches nothing.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
QROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
REPO = os.path.abspath(os.path.join(QROOT, ".."))
HOOK = os.path.join(QROOT, ".q-system", "hooks", "destructive-op-deny.sh")
NS_CHECK = os.path.join(
    QROOT, ".q-system", "scripts", "mcp-denylist-namespace-check.py"
)


def drive(hook_path, tool_name, tool_input=None, command=""):
    """Run the hook with an MCP tool payload. Returns (rc, decision).

    decision is "deny", "allow", or "malformed". A PreToolUse hook denies by
    writing JSON at exit 0 -- there is no non-zero exit to read, which is exactly
    why exit-code mutation cannot reach this class of hook (the 30 "unmeasurable"
    subjects in the mutation sweep are this shape).
    """
    payload = {
        "tool_name": tool_name,
        "tool_input": tool_input if tool_input is not None else {},
        "cwd": "/tmp",
    }
    if command:
        payload["tool_input"]["command"] = command
    env = dict(os.environ)
    env.pop("ALLOW_DESTRUCTIVE", None)
    # A HOME the hook can write its audit log into, so the real one is untouched.
    env["HOME"] = os.path.dirname(hook_path)
    proc = subprocess.run(
        ["bash", hook_path],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    out = proc.stdout.strip()
    if not out:
        return proc.returncode, "allow"
    try:
        parsed = json.loads(out)
    except ValueError:
        return proc.returncode, "malformed"
    decision = (
        parsed.get("hookSpecificOutput", {}).get("permissionDecision", "")
    )
    return proc.returncode, decision or "allow"


class MCPNamespaceCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="mcp-ns-")
        os.makedirs(os.path.join(cls.tmp, ".claude", "audit"), exist_ok=True)
        cls.hook = os.path.join(cls.tmp, "hook.sh")
        shutil.copy2(HOOK, cls.hook)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- the hole the founder's CLAUDE.md says cannot exist ----

    def test_linear_delete_on_the_loaded_server_is_denied(self):
        """CLAUDE.md: Linear `*delete*` is hook-blocked, NON-NEGOTIABLE."""
        _, decision = drive(self.hook, "mcp__linear__delete_issue")
        self.assertEqual(decision, "deny", "mcp__linear__delete_issue was allowed")

    def test_supabase_delete_branch_is_denied(self):
        """In the live tool roster; named by no pattern in the hook."""
        _, decision = drive(self.hook, "mcp__supabase__delete_branch")
        self.assertEqual(decision, "deny", "mcp__supabase__delete_branch was allowed")

    def test_supabase_reset_branch_is_denied(self):
        _, decision = drive(self.hook, "mcp__supabase__reset_branch")
        self.assertEqual(decision, "deny", "mcp__supabase__reset_branch was allowed")

    def test_gmail_trash_thread_is_denied(self):
        _, decision = drive(self.hook, "mcp__claude_ai_Gmail__trash_thread")
        self.assertEqual(decision, "deny")

    def test_drive_trash_file_is_denied(self):
        _, decision = drive(self.hook, "mcp__claude_ai_Google_Drive__trash_file")
        self.assertEqual(decision, "deny")

    def test_notion_move_pages_stays_denied(self):
        """Regression: the one Notion entry that already matched a live name."""
        _, decision = drive(self.hook, "mcp__claude_ai_Notion__notion-move-pages")
        self.assertEqual(decision, "deny")

    def test_gmail_delete_label_stays_denied(self):
        _, decision = drive(self.hook, "mcp__claude_ai_Gmail__delete_label")
        self.assertEqual(decision, "deny")

    def test_calendar_delete_event_stays_denied(self):
        _, decision = drive(self.hook, "mcp__claude_ai_Google_Calendar__delete_event")
        self.assertEqual(decision, "deny")

    # ---- the other half: a gate that blocks reads is a gate someone switches off ----

    def test_linear_read_is_allowed(self):
        """The over-block major open on PR #274. A read is not a mutation."""
        _, decision = drive(self.hook, "mcp__linear__list_issues")
        self.assertEqual(decision, "allow", "a Linear read was denied")

    def test_supabase_read_is_allowed(self):
        _, decision = drive(self.hook, "mcp__supabase__list_tables")
        self.assertEqual(decision, "allow")

    def test_untrash_is_allowed(self):
        """`untrash_message` contains `trash` and RESTORES. Live tool, live risk."""
        _, decision = drive(self.hook, "mcp__claude_ai_Gmail__untrash_message")
        self.assertEqual(decision, "allow", "the recovery path was blocked")

    def test_untrash_thread_is_allowed(self):
        _, decision = drive(self.hook, "mcp__claude_ai_Gmail__untrash_thread")
        self.assertEqual(decision, "allow")

    def test_playwright_browser_drop_is_allowed(self):
        """A drag-drop gesture, not a DROP TABLE. Live tool in the roster."""
        _, decision = drive(self.hook, "mcp__playwright__browser_drop")
        self.assertEqual(decision, "allow")

    def test_authenticate_stays_allowed(self):
        _, decision = drive(self.hook, "mcp__plugin_vercel_vercel__authenticate")
        self.assertEqual(decision, "allow")

    def test_ordinary_bash_still_passes(self):
        """The MCP change must not disturb the Bash half."""
        _, decision = drive(self.hook, "Bash", command="ls -la")
        self.assertEqual(decision, "allow")

    def test_bash_rm_rf_still_denied(self):
        """The negative self-test: if this goes green-by-accident, nothing works."""
        _, decision = drive(self.hook, "Bash", command="rm -rf /tmp/some-dir")
        self.assertEqual(decision, "deny")

    def test_a_session_reset_is_allowed(self):
        """PR #279 minor. `reset_session` matched the `reset` verb and came back
        with a destructive-operation message and an approval-token instruction.
        Clearing chat history destroys nothing, and a gate that blocks routine
        work with a scary message is a gate someone switches off.

        This also pins the ORDERING: the carve-out is evaluated before the verb
        rules, and placed after them it never runs. My first attempt did exactly
        that, so this case is what keeps it reachable."""
        self.assertEqual(
            drive(self.hook,
                  "mcp__plugin_kipi-notebooklm_notebooklm__reset_session")[1],
            "allow")

    def test_a_branch_reset_is_still_denied(self):
        """The carve-out is the session word, not the reset verb. reset_branch
        discards a database branch's state."""
        self.assertEqual(
            drive(self.hook, "mcp__supabase__reset_branch")[1], "deny")

    # ---- camelCase compounds (PR #279 minor) ----

    def test_camelcase_compound_deletions_are_denied(self):
        """`batchDelete` lowercases to `batchdelete`, where `delete` sits behind
        a letter, so the anchored verb rule missed it. MCP servers name
        operations both ways, so the boundary has to cover both."""
        for tool in ("mcp__linear__batchDelete",
                     "mcp__linear__deleteIssue",
                     "mcp__supabase__deleteBranch",
                     "mcp__linear__bulkRemoveItems"):
            with self.subTest(tool=tool):
                self.assertEqual(drive(self.hook, tool)[1], "deny")

    def test_camelcase_reads_and_un_forms_stay_allowed(self):
        """The `un` guard has to survive the new boundary: `untrashMessage`
        RESTORES, and turning the recovery path into a blocked path is worse
        than the hole it closed."""
        for tool in ("mcp__linear__listIssues",
                     "mcp__claude_ai_Gmail__untrashMessage",
                     "mcp__claude_ai_Gmail__untrash_message"):
            with self.subTest(tool=tool):
                self.assertEqual(drive(self.hook, tool)[1], "allow")

    # ---- the dead-namespace detector ----

    def test_namespace_check_exists(self):
        self.assertTrue(
            os.path.isfile(NS_CHECK), "mcp-denylist-namespace-check.py is missing"
        )

    def test_namespace_check_is_green_on_the_repo_hook(self):
        proc = subprocess.run(
            [sys.executable, NS_CHECK, "--hook", HOOK],
            capture_output=True,
            text=True,
            cwd=REPO,
            timeout=60,
        )
        self.assertEqual(
            proc.returncode, 0, "dead namespace(s):\n%s%s" % (proc.stdout, proc.stderr)
        )

    def test_namespace_check_is_green_with_a_clean_HOME(self):
        """The verdict must not move with which plugins this box has installed.

        PR #279 codex major, verbatim reproducer. The first cut discovered
        plugin servers by walking ~/.claude/plugins, so on a clean CI runner
        `mcp__plugin_vercel_vercel__` read DEAD and the check failed on a rule
        nobody had touched. A gate whose answer depends on the developer's
        machine is not measuring the hook.
        """
        env = dict(os.environ)
        env["HOME"] = os.path.join(self.tmp, "clean-home")
        proc = subprocess.run(
            [sys.executable, NS_CHECK, "--hook", HOOK],
            capture_output=True, text=True, cwd=REPO, env=env, timeout=60,
        )
        self.assertEqual(
            proc.returncode, 0,
            "the checker is machine-dependent:\n%s%s" % (proc.stdout, proc.stderr))

    def test_every_declared_namespace_carries_a_real_reason(self):
        """A bare allowlist is a place to hide a dead entry.

        The reason is what makes hiding one a visible act, the same shape
        test-propagation-entrypoints.py already uses for its EXEMPT list.
        """
        spec = importlib.util.spec_from_file_location("ns_check", NS_CHECK)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(mod.DECLARED_NAMESPACES, "the declaration list is empty")
        for ns, reason in mod.DECLARED_NAMESPACES.items():
            self.assertGreaterEqual(
                len(str(reason).split()), 8,
                "%s is declared with no real reason" % ns)

    def test_namespace_check_goes_red_on_a_planted_dead_namespace(self):
        """Every measurement needs a case whose answer you already know."""
        planted = os.path.join(self.tmp, "planted-hook.sh")
        with open(HOOK) as fh:
            body = fh.read()
        anchor = "        mcp__plugin_vercel_vercel__*)"
        self.assertIn(anchor, body, "the plant anchor moved; the plant is a no-op")
        body = body.replace(
            anchor,
            "        mcp__no_such_server_at_all__delete_everything|"
            "mcp__plugin_vercel_vercel__*)",
            1,
        )
        with open(planted, "w") as fh:
            fh.write(body)
        proc = subprocess.run(
            [sys.executable, NS_CHECK, "--hook", planted],
            capture_output=True,
            text=True,
            cwd=REPO,
            timeout=60,
        )
        self.assertNotEqual(
            proc.returncode, 0, "the checker passed a namespace naming no server"
        )
        self.assertIn("no_such_server_at_all", proc.stdout + proc.stderr)

    def test_the_verdict_does_not_move_with_the_machine(self):
        """A namespace installed HERE but declared nowhere must still read DEAD.

        The earlier version widened the known set with the local box's servers.
        That closed one direction -- nothing read DEAD merely because this
        machine lacked a plugin -- and left the other open: an undeclared
        namespace that happened to be installed here PASSED here and would fail
        on a clean runner. Either way the answer moved with the machine, which
        is what a gate must not do.

        So this plants a server in a fake $HOME, which is exactly the state that
        used to confer a pass, and demands the verdict be unchanged.
        """
        import json as _json
        import tempfile as _tempfile

        planted = os.path.join(self.tmp, "hook-machine-local.sh")
        with open(HOOK) as fh:
            body = fh.read()
        anchor = "        mcp__plugin_vercel_vercel__*)"
        self.assertIn(anchor, body, "the plant anchor moved; the plant is a no-op")
        with open(planted, "w") as fh:
            fh.write(body.replace(
                anchor,
                "        mcp__only_on_this_box__delete_everything|"
                "mcp__plugin_vercel_vercel__*)", 1))

        fake_home = _tempfile.mkdtemp(prefix="nsmachine-")
        with open(os.path.join(fake_home, ".claude.json"), "w") as fh:
            _json.dump({"mcpServers": {"only_on_this_box": {"command": "true"}}}, fh)

        env = dict(os.environ)
        env["HOME"] = fake_home
        proc = subprocess.run(
            [sys.executable, NS_CHECK, "--hook", planted],
            capture_output=True, text=True, cwd=REPO, timeout=60, env=env,
        )
        self.assertNotEqual(
            proc.returncode, 0,
            "a namespace installed only on this box conferred a PASS, so the "
            "verdict still moves with the machine")
        self.assertIn("only_on_this_box", proc.stdout + proc.stderr)

        # And the escape hatch still reports what a local install WOULD add.
        proc2 = subprocess.run(
            [sys.executable, NS_CHECK, "--hook", planted, "--include-machine-local"],
            capture_output=True, text=True, cwd=REPO, timeout=60, env=env,
        )
        self.assertEqual(proc2.returncode, 0,
                         "--include-machine-local should see the planted server")


if __name__ == "__main__":
    unittest.main(verbosity=2)
