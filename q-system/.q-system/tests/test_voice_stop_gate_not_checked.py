"""A missing lint must report NOT CHECKED, never a pass.

`run_check` returned `(0, "")` when its script was absent, and 0 is the same
value a clean draft produces. So a voice-stop-gate run on a machine where
`voice-lint.py` had moved was byte-for-byte indistinguishable from a run that
graded the draft and found nothing wrong. The turn completed, nothing was
written to stderr, and the founder got a post that no gate had read.

This is the precondition for making the Stop gate the bypass recorder. A
recorder that scores a missing check as a pass fails in exactly the shape it
exists to record.

The file already knows this. `resolve_reporter` at lines 125-140 was written
against the same defect and its comment says so: "A probe that cannot fail is
indistinguishable from one that works, which is why resolve_reporter returns the
NAMED path even when it is missing and lets the caller decide." That shape was
never carried the twenty lines down to `run_check`.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
GATE = os.path.join(REPO, "q-system", ".q-system", "scripts", "voice-stop-gate.py")
VOICE_LINT = os.path.join(REPO, "q-system", ".q-system", "scripts", "voice-lint.py")


def _load_gate():
    spec = importlib.util.spec_from_file_location("voice_stop_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load_gate()


def _draft(text):
    fh = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False,
                                     encoding="utf-8")
    fh.write(text)
    fh.close()
    return fh.name


class TestAMissingLintIsNotAPass:

    def test_run_check_reports_not_checked_when_the_script_is_absent(self):
        """The defect. Before the fix this returns (0, "") and reads as clean."""
        from pathlib import Path
        path = _draft("anything at all\n")
        try:
            code, out = gate.run_check(Path("/nonexistent/voice-lint.py"), path)
        finally:
            os.unlink(path)
        assert code == gate.NOT_CHECKED, (
            "a missing lint returned %r, which the caller cannot tell from a "
            "clean draft" % (code,))

    def test_the_not_checked_state_is_not_equal_to_the_pass_state(self):
        """Guards against someone defining NOT_CHECKED as 0 and calling it done.

        Without this, the case above passes for an implementation that changed
        nothing. NOT_CHECKED has to be a value a clean run cannot also produce.
        """
        assert gate.NOT_CHECKED != 0

    def test_the_report_names_the_script_it_could_not_run(self):
        """So the reader fixes the path instead of hunting the draft."""
        from pathlib import Path
        path = _draft("anything at all\n")
        try:
            _, out = gate.run_check(Path("/nonexistent/voice-lint.py"), path)
        finally:
            os.unlink(path)
        assert "voice-lint.py" in out and "/nonexistent" in out, out


class TestTheNormalPathStillWorks:
    """The negative controls. Run these before trusting the arms above.

    Without them, deleting the whole check body would satisfy every assertion in
    the class above.
    """

    def test_a_real_violation_is_still_surfaced(self):
        from pathlib import Path
        if not os.path.exists(VOICE_LINT):
            pytest.skip("voice-lint.py absent in this checkout")
        path = _draft("This sentence carries an em dash — which voice-lint bans.\n")
        try:
            code, out = gate.run_check(Path(VOICE_LINT), path)
        finally:
            os.unlink(path)
        assert code == 2, (code, out)
        assert out.strip(), "a violation was found and reported nothing"

    def test_a_clean_draft_still_passes(self):
        from pathlib import Path
        if not os.path.exists(VOICE_LINT):
            pytest.skip("voice-lint.py absent in this checkout")
        path = _draft("Short line. Nothing banned here.\n")
        try:
            code, _ = gate.run_check(Path(VOICE_LINT), path)
        finally:
            os.unlink(path)
        assert code == 0, "a clean draft must still be a plain pass"


# The capability gate's only runners are `bash` and `python3`; there is no pytest
# runner. Declared as python3, a bare pytest file would execute as a script,
# collect nothing, exit 0, and be counted as a passing declared test -- the same
# defect this file exists to close, one layer up. This block makes the declared
# invocation actually run the assertions.
if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "--no-header"]))


class TestTheWarningIsActuallyDelivered:
    """Codex major, PR #290. The first fix returned the right VALUE and delivered
    it on a channel nobody reads.

    stderr from a Stop hook is fed back when it exits 2. This path exits 0, so
    the NOT CHECKED line went nowhere. Every test above passed, because they all
    asserted the return value and none asserted delivery -- the same
    output-versus-input blindness the whole change exists to close, reproduced
    inside the fix for it.

    ASK-1303 corrected the destination this class asserts. It used to require the
    line on BARE stdout, which the measurement in `MEASURED_STOP_HOOK_SINKS`
    proves is the one exit-0 channel that is discarded.
    """

    def test_the_line_is_queued_for_the_surfacing_channel(self):
        """The arm that matters: the line is held for the systemMessage flush."""
        import io
        err = io.StringIO()
        gate.reset_pending_surface()
        gate.report_not_checked(["voice-stop-gate: X is MISSING"], err=err)
        assert "X is MISSING" in "\n".join(gate.pending_surface()), (
            "the line was not queued for the channel that survives exit 0")

    def test_the_line_also_reaches_stderr(self):
        """Kept for the blocking path, where stderr IS fed back (measured)."""
        import io
        err = io.StringIO()
        gate.reset_pending_surface()
        gate.report_not_checked(["voice-stop-gate: X is MISSING"], err=err)
        assert "X is MISSING" in err.getvalue()

    def test_nothing_is_written_when_every_lint_ran(self):
        """The control. A gate that always shouts is a gate that gets muted."""
        import io
        err = io.StringIO()
        gate.reset_pending_surface()
        gate.report_not_checked([], err=err)
        assert err.getvalue() == "" and gate.pending_surface() == []


# --- the reproducer for ASK-1303 ---------------------------------------------
#
# WHAT THIS CAN AND CANNOT PROVE, stated up front because the defect it guards
# was born of exactly this confusion. A test in this process cannot observe what
# the Claude Code harness renders. What it CAN do is assert that the bytes the
# gate puts on its own stdout match the SHAPE that was measured to survive.
#
# The measurement is recorded in voice-stop-gate.py's `MEASURED_STOP_HOOK_SINKS`
# block (three `claude -p` runs, 2026-09-12). Its load-bearing results:
#   - a bare line on stdout at exit 0 is DISCARDED;
#   - `{"systemMessage": ...}` on stdout at exit 0 surfaces as a `system` event;
#   - a bare line PRECEDING that JSON destroys the JSON too -- both are lost.
#
# So the shape contract is: at exit 0, this process's stdout is either empty or
# exactly one JSON object. A bare NOT CHECKED line anywhere in it is the defect.
_DRIVER = r"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location("voice_stop_gate", %r)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.report_not_checked(["voice-stop-gate: SENTINELLINT is MISSING"])
mod.authorship_page = lambda: None
mod.authorship_drain = lambda: ""
mod.finish_ok()
"""


def _run_driver():
    """Run the real functions in a real process and return its real stdout."""
    r = subprocess.run([sys.executable, "-c", _DRIVER % GATE],
                       capture_output=True, text=True, timeout=60)
    return r


class TestTheNotCheckedLineUsesASinkTheMeasurementSaysSurvives:

    def test_stdout_is_empty_or_exactly_one_json_object(self):
        """RED before the fix: stdout is 'line\\n{...}', which parses as nothing.

        This is the arm that goes red the moment any caller is pointed back at
        bare stdout, which is the mutation this test exists to kill.
        """
        r = _run_driver()
        blob = r.stdout.strip()
        assert blob, "the NOT CHECKED line reached no surviving channel at all"
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError as exc:
            raise AssertionError(
                "stdout is not one JSON object, so the harness parses none of "
                "it and the whole line is discarded: %r (%s)" % (blob, exc))
        assert isinstance(parsed, dict), parsed

    def test_the_line_rides_the_systemMessage_field(self):
        """Not merely present in stdout: present in the field that surfaces."""
        r = _run_driver()
        parsed = json.loads(r.stdout.strip())
        assert "SENTINELLINT" in parsed.get("systemMessage", ""), parsed

    def test_no_bare_copy_of_the_line_precedes_the_json(self):
        """The specific mutation: writing the line to stdout as well as queueing
        it looks harmless and destroys the JSON that carries it."""
        r = _run_driver()
        first = r.stdout.lstrip()[:1]
        assert first == "{", (
            "stdout begins with %r, so something bare was written before the "
            "JSON object; measured, that discards both" % (r.stdout[:60],))

    def test_the_line_is_still_on_stderr_for_the_blocking_path(self):
        """The negative control for the change: exit-2 delivery must not regress.

        report_not_checked runs BEFORE the gate knows whether it will exit 2, and
        stderr is the measured channel there. Without this arm, deleting the
        stderr write entirely would pass every assertion above.
        """
        r = _run_driver()
        assert "SENTINELLINT" in r.stderr, r.stderr
