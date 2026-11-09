"""ASK-1923: the MCP denylist, watched flipping in both directions.

The guard's MCP block matched SERVER-NAME wildcards. Read it as two defects that
hide each other, and note that neither is visible from the other's side:

Both halves are measured by running the matcher, never read off its source: the
executable is q-system/.q-system/scripts/mcp-denylist-namespace-check.py and
every case below drives it.

  OVER-BROAD   a wildcard refuses read-only queries on the namespace it names.
  UNDER-BROAD  the namespaces those wildcards name are not the ones that load,
               so destructive operations on the REGISTERED namespaces walk
               through. The serious half, and it reads exactly like protection.

THREE GUARDS, AND WHICH ONE EACH CASE MEASURES IS THE POINT OF THIS HEADER.

  REFERENCE  `checker.fixture_hook()` -- the FROZEN pre-fix guard committed at
             tests/fixtures/destructive-op-deny.reference.sh. Every negative
             control and most mutants read this one.
  CURRENT    `checker.current_fixture()` -- a committed copy of the CURRENT
             generation, tests/fixtures/destructive-op-deny.current.sh. The
             reference predates ASK-1144 (which made the guard's own MCP block
             operation-keyed), PR #279 and ASK-3361, and it was also what
             `resolve_hook()` fell back to, so a runner with no installed guard
             measured a two-generations-old shape and reported green through all
             three (PR #686 review round 5, major). The fallback is this file
             now, and test_the_current_fixture_still_matches_the_installed_guard
             fails LOUDLY when the founder's guard moves past it.
  HOOK       `checker.resolve_hook()` -- the guard INSTALLED on this machine,
             falling back to CURRENT. The oracle cases and the apply-time
             controls read this one, because this is the file the founder
             patches.

THE INSERT RUNS FIRST, SO EVERY RULING BELOW IT IS ITS TO HONOR. Two were
overturned -- Gmail trash (founder, 2026-10-29, ASK-3361) and reset_session (PR
#279) -- while the oracle pinned the reversal as correct, so nothing went red.
`test_the_patch_honors_every_ruling_the_guard_makes_below_it` DERIVES the rulings
out of the guard at run time (`checker.ruled_allow_probes`) rather than restating
them, so a ruling added below the anchor later turns that case red instead of
being discovered when a founder's bot stops working.

They were one thing until PR #686's review. Cases written as "observed red on
the guard today" were asserted against the INSTALLED guard, and between
2026-09-20 and 2026-11-08 that guard changed underneath them: it lost its
server-name wildcards and scoped its approval token. So six cases claiming a
defect existed went red as TESTS when the defect was actually gone -- the suite
reported good news by failing, and was green only where the installed guard was
absent and the fixture stood in for it. A negative control has to show the
oracle can go red, which needs a guard that cannot move; tracking the installed
guard is a different job. The blocker for that job is one executable case in
this file -- q-system/.q-system/tests/test_destructive_op_mcp_namespace.py
::TestTheInstalledGuardToday::test_the_installed_guard_still_needs_this_proposal
-- which goes red, with instructions in its own message, the day the installed
guard stops needing this proposal.

READ-ONLY ON ~/.claude, like test_destructive_op_deny_anchor.py. The guard is
copied into tmp, the copy is patched, and both copies are driven with HOME
redirected. Nothing here writes the live hook, and nothing proposes that an
agent apply the patch: the founder applies it. This delivers the diff and the
measurement.

The case list, the denylist parser AND the strip/apply pair all live in
`scripts/mcp-denylist-namespace-check.py` and are READ from there, never
restated -- a second copy of any of them would agree with itself on the day it
was written and stop describing the system on the day one changed. That is not
hypothetical here: mcp-candidate-measure.py kept its own apply, skipped the
strip this file did, and measured a doubly-patched guard (PR #686 review, minor).
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
REFERENCE = checker.fixture_hook()
CURRENT = checker.current_fixture()

pytestmark = pytest.mark.skipif(
    not HOOK.is_file(),
    reason="destructive-op-deny.sh is machine-local and the repo fixture is "
           "missing too; there is no guard here to measure")

needs_reference = pytest.mark.skipif(
    not REFERENCE.is_file(),
    reason="the committed pre-fix reference guard is missing; the negative "
           "controls have no guard with the ASK-1923 defects to measure")


def proposal_edit():
    return checker.proposal_edit(PROPOSAL)


def variants(tmp_path, hook=None):
    """(current copy, candidate copy) for one guard. The guard is READ, never written.

    `current` is the guard with this proposal's insert STRIPPED, applied or not.
    The founder APPLIES this proposal to the live guard; once they do, `HOOK` is
    the patched guard, and a suite that treated it as the `current` baseline
    measured the patch against itself: 6 of 55 cases went red, the negative
    control and two mutants included (PR #390 review round 3, major).
    """
    edit = proposal_edit()
    text = checker.baseline_text(hook or HOOK, edit)
    tmp_path = pathlib.Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    current = tmp_path / "current.sh"
    current.write_text(text, encoding="utf-8")
    candidate = tmp_path / "candidate.sh"
    candidate.write_text(checker.apply_insert(text, edit), encoding="utf-8")
    return current, candidate


DESTRUCTIVE = [c for c in checker.CASES if c["expect"] == "deny"]
SAFE = [c for c in checker.CASES if c["expect"] == "allow"]


def test_the_derivations_returned_something():
    """A parse that came back empty would turn every case below into a no-op."""
    assert len(DESTRUCTIVE) >= 10
    assert len(SAFE) >= 10
    # The installed guard has to be readable and the anchor has to hit it once,
    # or nothing below measures anything. baseline_text raises on either.
    assert checker.baseline_text(HOOK)
    # The ruling derivation has the same floor: an empty parse would turn
    # test_the_patch_honors_every_ruling_the_guard_makes_below_it green while
    # checking nothing, which is the shape of the defect it exists for.
    assert checker.ruled_allow_probes(
        CURRENT.read_text(encoding="utf-8")), (
        "no ALLOW rulings parsed out of the current-generation guard; the "
        "ruling case below would then assert nothing")


def test_the_current_fixture_is_the_post_ask_1144_generation():
    """The fallback guard for a machine with none installed, checked IN CI.

    `resolve_hook()` used to fall back to the pre-fix reference, so a runner
    with no installed guard measured a two-generations-old shape and reported
    green through ASK-1144, PR #279 and ASK-3361 (PR #686 review round 5,
    major). The marker is the operation-keyed block ASK-1144 introduced.
    """
    assert CURRENT.is_file(), (
        "the current-generation fixture is missing, so every runner without an "
        "installed guard falls back to the pre-fix reference")
    text = CURRENT.read_text(encoding="utf-8")
    assert "MCP_OP_LOWER" in text, (
        "the current fixture does not carry ASK-1144's operation-keyed MCP "
        "block, so it is not the current generation")
    assert "ASK-3361" in text, (
        "the current fixture predates the Gmail-trash founder ruling")


def test_the_current_fixture_still_matches_the_installed_guard():
    """A LOUD divergence check, which is the honest second best.

    The fixture is a copy of a file this repo does not own, so it cannot be
    derived at run time -- the founder's guard is the owner and it moves. A copy
    that silently goes stale is exactly what round 5 found, so the staleness
    fails here with the refresh command rather than being read as agreement.
    Skipped where no guard is installed, which is every CI runner.
    """
    if not checker.LIVE.is_file():
        pytest.skip("no installed guard here to compare the fixture against")
    installed = checker.LIVE.read_text(encoding="utf-8")
    if CURRENT.read_text(encoding="utf-8") == installed:
        return
    pytest.fail(
        "the installed guard has moved since %s was captured. Refresh it and "
        "re-run the oracle:\n"
        "  python3 -c \"import importlib.util as u, pathlib; "
        "s=u.spec_from_file_location('c', "
        "'q-system/.q-system/scripts/mcp-denylist-namespace-check.py'); "
        "m=u.module_from_spec(s); s.loader.exec_module(m); "
        "m.CURRENT.write_text(m.LIVE.read_text())\"\n"
        "Then read the diff before trusting any case in this file: a ruling "
        "added below the anchor is a ruling this proposal's insert runs ahead "
        "of." % CURRENT.name)


@needs_reference
def test_the_reference_guard_still_carries_the_wildcards():
    """The negative controls below rest on this, so it is asserted, not assumed.

    If someone regenerates the fixture from a fixed guard, every control turns
    into decoration and this is the case that says so first.
    """
    assert checker.denylist_namespaces(REFERENCE.read_text(encoding="utf-8")), (
        "no mcp__ patterns parsed out of the reference guard's MCP block: the "
        "frozen pre-fix guard no longer carries the defect this suite controls "
        "against, so the controls are measuring nothing")


@pytest.mark.parametrize("hook_name", ["installed", "reference"])
def test_this_suite_says_the_same_thing_after_the_founder_applies_the_patch(
        tmp_path, hook_name):
    """The whole variants() pair, not the strip in isolation.

    Built from a guard that ALREADY carries the insert, the pair must equal the
    pair built from one that does not. Before this, applying the proposal turned
    the negative control and two mutants red, because `current` silently became
    the patched guard (PR #390 review round 3, major).
    """
    hook = HOOK if hook_name == "installed" else REFERENCE
    if not hook.is_file():
        pytest.skip("no %s guard here" % hook_name)
    edit = proposal_edit()
    applied = tmp_path / "applied.sh"
    applied.write_text(
        checker.apply_insert(checker.baseline_text(hook, edit), edit),
        encoding="utf-8")

    before = [p.read_text(encoding="utf-8")
              for p in variants(tmp_path / "before", hook)]
    after = [p.read_text(encoding="utf-8")
             for p in variants(tmp_path / "after", applied)]
    assert before == after


# -------------------------------------------------- RED (the frozen pre-fix guard)
@needs_reference
class TestTheGuardTheIssueWasFiledAgainst:
    """Observed failing against the FROZEN reference guard, never the installed
    one. These prove the oracle discriminates: a guard carrying the ASK-1923
    defects must fail these cases. They cannot report what is installed today --
    that is `TestTheInstalledGuardToday` below, deliberately separated after the
    PR #686 review found these six asserting defects the live guard had already
    lost."""

    def test_a_destructive_op_on_a_registered_namespace_is_allowed(self, tmp_path):
        current, _ = variants(tmp_path, REFERENCE)
        allowed = [c["tool"] for c in DESTRUCTIVE
                   if checker.decide(current, c["tool"], tmp_path,
                                     c.get("input")) == "allow"]
        assert allowed
        assert "mcp__linear__delete_issue" in allowed, (
            "the founder's global CLAUDE.md names Linear *delete* as hook-blocked "
            "regardless of mode, and it is the case this issue was filed on")

    def test_a_read_only_query_is_denied(self, tmp_path):
        current, _ = variants(tmp_path, REFERENCE)
        denied = [c["tool"] for c in SAFE
                  if checker.decide(current, c["tool"], tmp_path,
                                    c.get("input")) == "deny"]
        assert denied, "the over-broad half is not visible in the reference guard"

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
        current, _ = variants(tmp_path, REFERENCE)
        verdict = checker.grant_leak(current, tmp_path)
        if verdict == "no-token-script":
            pytest.skip("no capability-token.sh on this machine to measure with")
        assert verdict == "LEAK"

    def test_the_denylist_wildcards_name_namespaces_nothing_registers(self, tmp_path):
        """The mechanism behind the under-broad half, not just its symptom."""
        current, _ = variants(tmp_path, REFERENCE)
        registered = checker.registered_namespaces(
            checker.default_configs(), checker.CASES)
        dead = checker.dead_wildcards(
            current.read_text(encoding="utf-8"), registered)
        assert dead

    def test_a_read_verb_does_not_let_a_write_past_the_wildcard(self, tmp_path):
        """The inserted comment claims the read list reaches no write on the
        namespaces the block below wildcards. `resolve` was on it, and
        `resolve_diff_thread` WRITES -- it resolves a review thread at the vendor
        side (PR #390 review). Pinned to the reference guard because the probe
        needs a wildcard to get past, and the installed guard has none left."""
        _, candidate = variants(tmp_path, REFERENCE)
        probe = "mcp__plugin_linear_linear__resolve_diff_thread"
        assert checker.decide(candidate, probe, tmp_path) == "deny", (
            "a write on a wildcarded namespace took the read-only exit")

    def test_the_checker_fails_on_the_unpatched_reference_guard(self, tmp_path):
        """Negative control for `test_the_checker_agrees_end_to_end`. A checker
        that passed both would be measuring nothing."""
        current, _ = variants(tmp_path, REFERENCE)
        assert checker.failures(current) != []


# ------------------------------------------------ the guard installed right now
class TestTheInstalledGuardToday:
    """The one place this suite talks about the machine it runs on.

    Kept to two cases on purpose. Everything else here is pinned to a frozen
    artifact, so this is the only part that can change when the guard changes --
    and when it does, these say which way.
    """

    def test_the_installed_guard_still_needs_this_proposal(self, tmp_path):
        current, _ = variants(tmp_path)
        assert checker.failures(current) != [], (
            "the INSTALLED guard already satisfies every oracle case. This "
            "proposal is obsolete: do not relax a case to make this pass. "
            "Close ASK-1923, delete the proposal and this suite, and say in the "
            "closeout which change fixed it.")

    def test_the_patch_fixes_every_oracle_case_on_the_installed_guard(self, tmp_path):
        """The script the founder will run, on the guard they will run it on."""
        _, candidate = variants(tmp_path)
        assert checker.failures(candidate) == []


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

    @pytest.mark.parametrize("hook_name", ["installed", "current-fixture"])
    def test_the_patch_honors_every_ruling_the_guard_makes_below_it(
            self, tmp_path, hook_name):
        """The insert runs FIRST, so a ruling further down is its to honor.

        Two were overturned: Gmail trash, allowed by the FOUNDER on 2026-10-29
        (ASK-3361, so his inbox bots work), and reset_session, allowed by PR
        #279 because clearing a conversation destroys no data. The insert's
        `trash` and `reset` verbs denied both, and this PR's oracle pinned the
        reversal as correct, so nothing went red (PR #686 review round 5,
        major).

        The ruling list is DERIVED from the guard here, never restated: a
        restated copy agrees with itself on the day it is written and stops
        describing the guard the day someone adds a ruling.
        """
        hook = HOOK if hook_name == "installed" else CURRENT
        if not hook.is_file():
            pytest.skip("no %s guard here" % hook_name)
        rulings = checker.ruled_allow_probes(hook.read_text(encoding="utf-8"))
        if not rulings:
            # The PRE-FIX guard makes no ALLOW rulings at all -- its only
            # carve-out was a `*authenticate*` wildcard, which names a class and
            # not a callable name. A guard with no rulings has none to reverse,
            # so this arm has nothing to say; the `current-fixture` arm is where
            # the coverage lives and its floor is in
            # test_the_derivations_returned_something.
            pytest.skip("the %s guard makes no ALLOW rulings to honor" % hook_name)
        _, candidate = variants(tmp_path, hook)
        overturned = [p for p in rulings
                      if checker.decide(candidate, p, tmp_path) == "deny"]
        assert overturned == [], (
            "the patch reverses %d ruling(s) the guard makes below the insert: "
            "%s. The insert runs first, so each of these needs an entry in its "
            "MCP_RULED_ALLOW_TOOL / MCP_RULED_ALLOW_OP carve-out -- not a "
            "relaxed case here." % (len(overturned), ", ".join(overturned)))

    def test_the_checker_claims_only_the_properties_it_measured(self, tmp_path,
                                                                monkeypatch):
        """The OK line printed "the approval token is scoped, and the audit log
        keeps no payload" on runs where DIRECTION 3 and 4 had both printed n/a
        two lines above (PR #686 review round 5, minor). Driven with no
        capability-token.sh reachable, which is the state that produced it.

        One case covers both consumers: mcp-candidate-measure.py prints no
        summary of its own, it returns `checker.main`, so the claim has one
        writer and this is it.
        """
        import contextlib
        import io
        _, candidate = variants(tmp_path)
        monkeypatch.setenv("KIPI_CAPABILITY_TOKEN",
                           str(tmp_path / "no-such-capability-token.sh"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = checker.main(["--hook", str(candidate)])
        out = buf.getvalue()
        assert code == 0, out
        assert "no capability-token.sh on this machine" in out, (
            "this case needs the unmeasurable state to exercise the claim")
        ok = [l for l in out.splitlines() if l.startswith("OK:")]
        assert len(ok) == 1, out
        assert "the approval token is scoped" not in ok[0], ok[0]
        assert "the approval token was NOT measured" in ok[0], ok[0]

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

    def test_the_sql_deny_message_does_not_claim_it_parsed_the_statement(self, tmp_path):
        """The object-keyword list came back wrong twice, so the rule now keys on
        the keyword alone and OVER-refuses. The message has to say that rather
        than imply the gate understood the SQL (PR #686 review, major)."""
        _, candidate = variants(tmp_path)
        reason = checker.deny_reason(candidate, "mcp__supabase__execute_sql",
                                     tmp_path, {"query": "TRUNCATE users;"})
        assert reason is not None
        assert "does not parse SQL" in reason
        assert "refused on the keyword" in reason

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

    def test_the_proposal_json_is_what_its_generator_builds(self):
        """The insert is shell inside a JSON string; a hand edit there is how a
        quoting defect reaches a security gate. One writer: build-mcp-proposal.py."""
        import subprocess
        builder = SCRIPTS / "build-mcp-proposal.py"
        proc = subprocess.run([sys.executable, str(builder), "--check"],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr or proc.stdout

    def test_the_checker_agrees_end_to_end(self, tmp_path):
        """On the reference guard, where the result cannot move under us."""
        if not REFERENCE.is_file():
            pytest.skip("no reference guard here")
        _, candidate = variants(tmp_path, REFERENCE)
        assert checker.failures(candidate) == []

    def test_the_candidate_measure_script_applies_the_insert_exactly_once(
            self, tmp_path, monkeypatch):
        """mcp-candidate-measure.py built its candidate from the guard AS FOUND,
        so once the founder applies the proposal it measured a guard carrying
        the insert twice (PR #686 review, minor). Driven here against an
        already-applied guard, which is the state that broke it."""
        import importlib.util as _util
        edit = proposal_edit()
        applied = tmp_path / "applied.sh"
        applied.write_text(
            checker.apply_insert(checker.baseline_text(HOOK, edit), edit),
            encoding="utf-8")
        monkeypatch.setenv("KIPI_DESTRUCTIVE_HOOK", str(applied))

        spec = _util.spec_from_file_location(
            "mcp_candidate_measure", SCRIPTS / "mcp-candidate-measure.py")
        measure = _util.module_from_spec(spec)
        spec.loader.exec_module(measure)
        out = measure.candidate(tmp_path)
        assert out.read_text(encoding="utf-8").count(edit["insert"]) == 1


class TestEachFixCanGoRed:
    """One mutant per decision point the reviews added, all against the FROZEN
    reference guard so a mutant's verdict cannot move with the machine.

    A check that has never been seen failing is decoration. Each case below
    breaks exactly one clause of the insert and watches the corresponding
    decision flip back to what the reviewer found.
    """

    def mutant(self, tmp_path, old, new, hook=None, occurrences=1):
        """Break exactly one clause of the insert, `occurrences` copies of it.

        The count is DECLARED rather than assumed. One clause legitimately
        appears twice: the destructive SQL verb group, once for a statement that
        starts with the verb and once for a verb reached through an ALTER. A
        mutant that silently patched one of two would leave the other enforcing
        and report the mutation as survived.
        """
        edit = proposal_edit()
        text = checker.baseline_text(hook or REFERENCE, edit)
        assert edit["insert"].count(old) == occurrences, (
            "the mutation target moved; this mutant is no longer breaking what "
            "it claims to break: %r appears %d time(s), expected %d"
            % (old, edit["insert"].count(old), occurrences))
        insert = edit["insert"].replace(old, new, occurrences)
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

    def test_with_the_object_keyword_list_back_a_truncate_walks_through(self, tmp_path):
        """An object keyword list allows `TRUNCATE users;`, `DROP CONSTRAINT`
        and `DROP TRIGGER` (PR #686 review round 4, major; the same defect in a
        different spelling one round earlier). Two copies of the verb group now,
        so the mutation declares both."""
        broken = self.mutant(tmp_path, r"(drop|truncate)([[:space:]]|\\n)",
                             "(drop|truncate)([[:space:]])+(table|column)",
                             occurrences=2)
        for statement in ("TRUNCATE users;",
                          "DROP TRIGGER audit_trigger ON users;",
                          "ALTER TABLE users DROP CONSTRAINT users_email_key;"):
            assert checker.decide(broken, "mcp__supabase__execute_sql", tmp_path,
                                  {"query": statement}) == "allow", statement
        # Narrow mutation: the statement the object list DOES cover still
        # denies, so this breaks the list's shape and not the whole rule.
        assert checker.decide(broken, "mcp__supabase__execute_sql", tmp_path,
                              {"query": "DROP TABLE users;"}) == "deny"

    def test_with_the_operation_name_gate_back_a_notebook_walks_through(self, tmp_path):
        """The round-5 regression: the payload rule was gated on an
        operation-NAME list (execute_sql / apply_migration / run_sql), which is
        the object list's defect one layer out. `run_notebook` was not on it, so
        its DROP TABLE ran (PR #686 review round 5, minor)."""
        broken = self.mutant(
            tmp_path,
            'if echo "${TOOL_INPUT:-}" | grep -Eqi "$MCP_DESTRUCTIVE_SQL"; then',
            'if echo "$_mcp_op" | grep -Eqi '
            "'(^|[_-])(execute[_-]?sql|apply[_-]?migration|run[_-]?sql|sql)([_-]|$)'"
            ' && echo "${TOOL_INPUT:-}" | grep -Eqi "$MCP_DESTRUCTIVE_SQL"; then')
        assert checker.decide(broken, "mcp__supabase__run_notebook", tmp_path,
                              {"cells": ["DROP TABLE users;"]}) == "allow"
        # The listed operation still denies, which is why the hole read as safe.
        assert checker.decide(broken, "mcp__supabase__execute_sql", tmp_path,
                              {"query": "DROP TABLE users;"}) == "deny"

    @pytest.mark.parametrize("probe", [
        "mcp__claude_ai_Gmail__trash_thread",
        "mcp__claude_ai_Gmail__trash_message",
        "mcp__plugin_kipi-notebooklm_notebooklm__reset_session"])
    def test_without_the_ruling_carve_out_the_insert_reverses_a_founder_ruling(
            self, tmp_path, probe):
        """Gmail trash is a FOUNDER ruling (2026-10-29, ASK-3361) and a session
        reset is a review ruling (PR #279). The insert runs before both, so with
        its carve-out removed its `trash` and `reset` verbs overturn them (PR
        #686 review round 5, major).

        Driven against the CURRENT-generation guard, because the pre-fix
        reference carries no rulings to overturn -- which is the other half of
        the same finding.
        """
        if not CURRENT.is_file():
            pytest.skip("no current-generation guard here")
        broken = self.mutant(
            tmp_path,
            'if echo "$TOOL_NAME" | grep -Eq "$MCP_RULED_ALLOW_TOOL" \\\n'
            '       || echo "$_mcp_op" | grep -Eqi "$MCP_RULED_ALLOW_OP"; then',
            "if false; then", hook=CURRENT)
        assert checker.decide(broken, probe, tmp_path) == "deny"

    def test_with_the_auth_carve_out_unanchored_a_mutating_op_walks_through(self, tmp_path):
        """`*authenticate*` matched the whole tool name, so any operation whose
        name carried `auth` skipped every rule after it (PR #390 review round 4,
        minor)."""
        broken = self.mutant(tmp_path, "notion-complete-mcp-setup)$'",
                             "notion-complete-mcp-setup)$|auth'")
        assert checker.decide(broken, "mcp__claude_ai_Vercel__update_auth_settings",
                              tmp_path) == "allow"

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
