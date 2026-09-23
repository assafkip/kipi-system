"""ASK-1923: the MCP denylist, watched flipping in both directions.

The guard's MCP block matches SERVER-NAME wildcards. Read it as two defects that
hide each other, and note that neither is visible from the other's side:

  OVER-BROAD   the wildcards deny read-only queries on the namespaces they name.
  UNDER-BROAD  the namespaces they name are not the ones that load, so the
               destructive operations on the REGISTERED namespaces walk through.
               This is the serious half, and it reads exactly like protection.

These cases drive the CURRENT guard and a CANDIDATE built by applying
`proposals/mcp-denylist-operation-split.json` to a copy of it. Every case is
observed RED on the current guard and GREEN on the candidate, so nothing here is
a test that has never been seen failing.

READ-ONLY ON ~/.claude, like test_destructive_op_deny_anchor.py. The guard is
copied into tmp, the copy is patched, and both copies are driven with HOME
redirected. Nothing here writes the live hook, and nothing proposes that an
agent apply the patch: the founder applies it. This delivers the diff and the
measurement.

The case list and the denylist parser both live in
`scripts/mcp-denylist-namespace-check.py` and are READ from there, never
restated -- a second copy of either would agree with itself on the day it was
written and stop describing the system on the day one changed.
"""
import json
import pathlib
import sys

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import importlib.util

# The script's filename carries hyphens (folder-structure.md's convention for
# scripts/), so it cannot be reached by `import`. Loaded by path instead.
_spec = importlib.util.spec_from_file_location(
    "mcp_denylist_namespace_check", SCRIPTS / "mcp-denylist-namespace-check.py")
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)

PROPOSAL = (pathlib.Path(__file__).resolve().parents[1]
            / "proposals" / "mcp-denylist-operation-split.json")

HOOK = checker.resolve_hook()

pytestmark = pytest.mark.skipif(
    not HOOK.is_file(),
    reason="destructive-op-deny.sh is machine-local and the repo fixture is "
           "missing too; there is no guard here to measure")


def proposal_edit():
    proposal = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    (edit,) = proposal["edits"]
    assert edit["file"] == ".claude/hooks/destructive-op-deny.sh"
    assert edit["op"] == "insert_before"
    return edit


def strip_insert(text, insert):
    """The guard WITHOUT this proposal's insert, applied or not."""
    return text.replace(insert, "", 1)


def baseline():
    """(guard text with the insert removed, the edit).

    The founder APPLIES this proposal to the live guard. Once they do, `HOOK` is
    the patched guard, and a suite that treated it as the `current` baseline
    measured the patch against itself: 6 of these 55 cases went red, the
    negative control and two mutants included (PR #390 review round 3, major).
    Stripping first makes every case below say the same thing before and after
    application, which is the only way this suite survives its own fix landing.
    """
    edit = proposal_edit()
    text = strip_insert(HOOK.read_text(encoding="utf-8"), edit["insert"])
    assert edit["insert"] not in text, (
        "the guard carries the insert more than once; stripping one copy left "
        "another, and the baseline is not a baseline")
    assert text.count(edit["anchor"]) == 1, (
        "the proposal's anchor does not hit the guard exactly once; "
        "applying it would land in the wrong place or not at all")
    return text, edit


def variants(tmp_path):
    """(current copy, candidate copy). The guard is READ, never written."""
    text, edit = baseline()
    tmp_path = pathlib.Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    current = tmp_path / "current.sh"
    current.write_text(text, encoding="utf-8")
    candidate = tmp_path / "candidate.sh"
    candidate.write_text(
        text.replace(edit["anchor"], edit["insert"] + edit["anchor"], 1),
        encoding="utf-8")
    return current, candidate


DESTRUCTIVE = [c for c in checker.CASES if c["expect"] == "deny"]
SAFE = [c for c in checker.CASES if c["expect"] == "allow"]


def test_the_derivations_returned_something():
    """A parse that came back empty would turn every case below into a no-op."""
    assert len(DESTRUCTIVE) >= 10
    assert len(SAFE) >= 10
    assert checker.denylist_namespaces(HOOK.read_text(encoding="utf-8")), (
        "no mcp__ patterns parsed out of the guard's MCP block: the block was "
        "restructured and this suite is measuring nothing")


def test_this_suite_says_the_same_thing_after_the_founder_applies_the_patch(
        tmp_path, monkeypatch):
    """The whole variants() pair, not the strip in isolation.

    Built from a guard that ALREADY carries the insert, the pair must equal the
    pair built from one that does not. Before this, applying the proposal turned
    the negative control and two mutants red, because `current` silently became
    the patched guard (PR #390 review round 3, major).
    """
    text, edit = baseline()
    applied = tmp_path / "applied.sh"
    applied.write_text(
        text.replace(edit["anchor"], edit["insert"] + edit["anchor"], 1),
        encoding="utf-8")

    before = [p.read_text(encoding="utf-8") for p in variants(tmp_path / "before")]
    monkeypatch.setattr(sys.modules[__name__], "HOOK", applied)
    after = [p.read_text(encoding="utf-8") for p in variants(tmp_path / "after")]
    assert before == after


# ---------------------------------------------------------------- RED (current)
class TestTheGuardIsWrongInBothDirectionsToday:
    """Observed failing. If one of these goes green, the defect is gone: delete
    the case and say so, do not quietly relax it."""

    def test_a_destructive_op_on_a_registered_namespace_is_allowed(self, tmp_path):
        current, _ = variants(tmp_path)
        allowed = [c["tool"] for c in DESTRUCTIVE
                   if checker.decide(current, c["tool"], tmp_path,
                                     c.get("input")) == "allow"]
        assert allowed, (
            "every destructive MCP tool is already denied; the under-broad half "
            "of ASK-1923 is fixed and this case has outlived it")
        assert "mcp__linear__delete_issue" in allowed, (
            "the founder's global CLAUDE.md names Linear *delete* as hook-blocked "
            "regardless of mode, and it is the case this issue was filed on")

    def test_a_read_only_query_is_denied(self, tmp_path):
        current, _ = variants(tmp_path)
        denied = [c["tool"] for c in SAFE
                  if checker.decide(current, c["tool"], tmp_path,
                                    c.get("input")) == "deny"]
        assert denied, (
            "no read-only MCP query is denied any more; the over-broad half of "
            "ASK-1923 is fixed and this case has outlived it")

    def test_one_mcp_approval_token_unlocks_a_different_destructive_op(self, tmp_path):
        """The widest of the four, and invisible to every case above.

        `emit_deny` scopes its capability-token grant to `$COMMAND` + `$CWD`. An
        MCP payload has no `.tool_input.command`, so every MCP denial in one cwd
        hashes the EMPTY STRING and they all share one grant: approving a Gmail
        `delete_label` once hands over the next Calendar `delete_event`. That is
        the ambient authority the token exists to remove (PocketOS 2026-05-17).

        The REAL capability-token.sh is copied into the throwaway HOME. A stub
        would encode this test's idea of how a grant is scoped, and how a grant
        is scoped is the thing under measurement.
        """
        current, _ = variants(tmp_path)
        verdict = checker.grant_leak(current, tmp_path)
        if verdict == "no-token-script":
            pytest.skip("no capability-token.sh on this machine to measure with")
        assert verdict == "LEAK", (
            "one MCP approval no longer unlocks another; that half of ASK-1923 "
            "is fixed and this case has outlived it")

    def test_the_denylist_wildcards_name_namespaces_nothing_registers(self, tmp_path):
        """The mechanism behind the under-broad half, not just its symptom."""
        current, _ = variants(tmp_path)
        registered = checker.registered_namespaces(
            checker.default_configs(), checker.CASES)
        dead = checker.dead_wildcards(
            current.read_text(encoding="utf-8"), registered)
        assert dead, (
            "every denylist wildcard now names a registered namespace; the "
            "premise of this issue no longer holds")


# ------------------------------------------------------------ GREEN (candidate)
class TestTheOperationKeyedSplitFixesBothDirections:

    @pytest.mark.parametrize("case", DESTRUCTIVE, ids=lambda c: c["tool"])
    def test_every_destructive_operation_is_denied(self, tmp_path, case):
        _, candidate = variants(tmp_path)
        assert checker.decide(candidate, case["tool"], tmp_path,
                              case.get("input")) == "deny", (
            "%s still runs unguarded after the patch%s"
            % (case["tool"], " -- " + case["why"] if case.get("why") else ""))

    @pytest.mark.parametrize("case", SAFE, ids=lambda c: c["tool"])
    def test_every_read_only_operation_is_allowed(self, tmp_path, case):
        _, candidate = variants(tmp_path)
        assert checker.decide(candidate, case["tool"], tmp_path,
                              case.get("input")) == "allow", (
            "the patch blocks a read: %s. A gate that blocks reads is a gate "
            "someone switches off." % case["tool"])

    def test_the_deny_message_claims_only_what_the_gate_knows(self, tmp_path):
        """A local plugin's `loop_force_close` was refused with a message saying
        it deletes state AT THE VENDOR SIDE. Same shape as the `browser_drop`
        minor one round earlier, so the fix is the message rather than another
        verb coming off the list: the gate cannot place the state, and now says
        so (PR #390 review round 3, minor)."""
        _, candidate = variants(tmp_path)
        reason = checker.deny_reason(
            candidate, "mcp__plugin_kipi-core_kipi__loop_force_close", tmp_path)
        assert reason is not None, "the verb no longer matches; this case is stale"
        assert "vendor side" not in reason
        assert "cannot see whether the state it removes is at the vendor" in reason

    def test_the_audit_log_keeps_a_digest_and_not_the_payload(self, tmp_path):
        """Binding the grant to the verbatim tool_input also wrote every MCP
        argument into $HOME/.claude/audit/destructive-op-deny.log in plaintext
        (PR #390 review round 3, minor)."""
        _, candidate = variants(tmp_path)
        assert checker.payload_in_audit_log(candidate, tmp_path) == "digest"

    def test_the_digest_still_binds_the_grant_to_the_exact_payload(self, tmp_path):
        """A digest is only worth having if two payloads still earn two grants."""
        _, candidate = variants(tmp_path)
        if checker.token_home(tmp_path) is None:
            pytest.skip("no capability-token.sh on this machine to hash with")
        tool = "mcp__linear__delete_issue"
        first = checker.deny_hash(candidate, tool, tmp_path, {"id": "ASK-1"})
        second = checker.deny_hash(candidate, tool, tmp_path, {"id": "ASK-2"})
        if not first or not second:
            pytest.skip("no capability-token.sh on this machine to hash with")
        assert first != second

    def test_an_approval_token_is_scoped_to_the_call_that_earned_it(self, tmp_path):
        _, candidate = variants(tmp_path)
        verdict = checker.grant_leak(candidate, tmp_path)
        if verdict == "no-token-script":
            pytest.skip("no capability-token.sh on this machine to measure with")
        assert verdict == "scoped", (
            "a grant minted for one MCP denial was consumed by a different one; "
            "the patch scopes $COMMAND to the tool name plus its tool_input, so "
            "either that assignment is gone or it lands after the first deny")

    def test_a_read_verb_does_not_let_a_write_past_the_wildcard(self, tmp_path):
        """The inserted comment claims the read list reaches no write on the
        namespaces the block below wildcards. `resolve` was on it, and
        `resolve_diff_thread` WRITES -- it resolves a review thread at the vendor
        side (PR #390 review). The probe composes a real wildcarded namespace
        with that real operation; it is a probe of the matcher, not a claim that
        this exact tool is registered."""
        _, candidate = variants(tmp_path)
        probe = "mcp__plugin_linear_linear__resolve_diff_thread"
        assert checker.decide(candidate, probe, tmp_path) == "deny", (
            "a write on a wildcarded namespace took the read-only exit")

    def test_the_proposal_json_is_what_its_generator_builds(self):
        """The insert is shell inside a JSON string; a hand edit there is how a
        quoting defect reaches a security gate. One writer: build-mcp-proposal.py."""
        import subprocess
        builder = SCRIPTS / "build-mcp-proposal.py"
        proc = subprocess.run([sys.executable, str(builder), "--check"],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr or proc.stdout

    def test_the_checker_agrees_end_to_end(self, tmp_path):
        """The script the founder will run, run the way they will run it."""
        _, candidate = variants(tmp_path)
        assert checker.failures(candidate) == []

    def test_the_checker_fails_on_the_unpatched_guard(self, tmp_path):
        """Negative control for the case above. A checker that passed both would
        be measuring nothing -- this is the mutation that proves it can go red."""
        current, _ = variants(tmp_path)
        assert checker.failures(current) != []


class TestEachFixCanGoRed:
    """One mutant per decision point the PR #390 review added.

    A check that has never been seen failing is decoration. Each case below
    breaks exactly one clause of the insert and watches the corresponding
    decision flip back to what the reviewer found.
    """

    def mutant(self, tmp_path, old, new):
        text, edit = baseline()
        assert edit["insert"].count(old) == 1, (
            "the mutation target moved; this mutant is no longer breaking what "
            "it claims to break: %r" % old)
        insert = edit["insert"].replace(old, new, 1)
        broken = tmp_path / "mutant.sh"
        broken.write_text(
            text.replace(edit["anchor"], insert + edit["anchor"], 1),
            encoding="utf-8")
        return broken

    def test_without_the_payload_check_a_drop_table_walks_through(self, tmp_path):
        broken = self.mutant(tmp_path, 'grep -Eqi "$MCP_DESTRUCTIVE_SQL"',
                             'grep -Eqi "zzz-this-mutation-matches-nothing"')
        assert checker.decide(broken, "mcp__supabase__execute_sql", tmp_path,
                              {"query": "DROP TABLE users;"}) == "allow"

    def test_without_the_digest_the_payload_lands_in_the_audit_log(self, tmp_path):
        broken = self.mutant(tmp_path, 'COMMAND="$TOOL_NAME $_mcp_scope"',
                             'COMMAND="$TOOL_NAME ${TOOL_INPUT:-}"')
        assert checker.payload_in_audit_log(broken, tmp_path) == "LEAK"

    def test_without_the_command_scoping_the_token_leaks_again(self, tmp_path):
        broken = self.mutant(tmp_path,
                             'COMMAND="$TOOL_NAME $_mcp_scope"',
                             '_mcp_scoping_removed_by_mutation=1')
        if checker.grant_leak(broken, tmp_path) == "no-token-script":
            pytest.skip("no capability-token.sh on this machine to measure with")
        assert checker.grant_leak(broken, tmp_path) == "LEAK"

    def test_with_resolve_back_on_the_read_list_a_write_walks_through(self, tmp_path):
        broken = self.mutant(tmp_path, "|show|count|suggest)", "|show|count|resolve|suggest)")
        probe = "mcp__plugin_linear_linear__resolve_diff_thread"
        assert checker.decide(broken, probe, tmp_path) == "allow"

    def test_with_drop_back_on_the_destructive_list_a_mouse_gesture_is_denied(self, tmp_path):
        broken = self.mutant(tmp_path, "(delete|destroy|purge", "(delete|destroy|drop|purge")
        assert checker.decide(broken, "mcp__playwright__browser_drop", tmp_path) == "deny"

    def test_a_case_sensitive_server_match_misses_the_capital_v_connector(self, tmp_path):
        broken = self.mutant(tmp_path,
                             'grep -Eqi "$MCP_MUTATION_SCOPED_SERVER"',
                             'grep -Eq "$MCP_MUTATION_SCOPED_SERVER"')
        assert checker.decide(broken, "mcp__claude_ai_Vercel__update_project",
                              tmp_path) == "allow"


class TestThePatchDoesNotReachOutsideTheMcpBlock:

    @pytest.mark.parametrize("command", [
        "rm -rf /tmp/whatever", "git reset --hard", "git push --force",
        "git clean -fd", "rm -v -rf /tmp/canary"])
    def test_the_bash_denials_are_untouched(self, tmp_path, command):
        _, candidate = variants(tmp_path)
        payload = {"tool_name": "Bash", "tool_input": {"command": command}}
        assert _bash_decision(candidate, payload, tmp_path) == "deny", command

    @pytest.mark.parametrize("command", ["rm /tmp/one-file.txt", "git push origin main"])
    def test_an_ordinary_command_still_runs(self, tmp_path, command):
        _, candidate = variants(tmp_path)
        payload = {"tool_name": "Bash", "tool_input": {"command": command}}
        assert _bash_decision(candidate, payload, tmp_path) == "allow", command

    def test_a_non_mcp_tool_is_not_touched(self, tmp_path):
        """Write/Edit must not start routing through the MCP branch."""
        _, candidate = variants(tmp_path)
        assert checker.decide(candidate, "Write", tmp_path) == "allow"


def _bash_decision(hook, payload, home):
    import os
    import shutil
    import subprocess
    copy = pathlib.Path(home) / "bash-under-test.sh"
    shutil.copy(hook, copy)
    payload = dict(payload, cwd=str(home))
    env = dict(os.environ)
    env["HOME"] = str(home)
    env.pop("ALLOW_DESTRUCTIVE", None)
    proc = subprocess.run(["bash", str(copy)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env)
    out = proc.stdout.strip()
    if not out:
        return "allow"
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
