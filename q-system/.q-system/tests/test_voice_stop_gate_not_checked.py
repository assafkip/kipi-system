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
