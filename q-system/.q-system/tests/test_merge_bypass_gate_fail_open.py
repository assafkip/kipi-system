#!/usr/bin/env python3
"""merge-bypass-gate must DENY when it cannot classify (ASK-1179).

## The defect this pins

`_merge_verdict` was declared `(seg, note=None)` and its body called
`_receipt_missing(rest, cwd)`. NameError. `classify()` was called OUTSIDE
main()'s try/except, and every path in main() returns 0, so the deny travels by
`print(json.dumps(...))` and never by an exit code. An exception before that
print emitted no deny JSON and blocked nothing.

Measured 2026-08-30 through this hook's own stdin, before the fix:

    EXIT=1
    stdout: (empty -- no deny)
    stderr: NameError: name 'cwd' is not defined

The crashing input is a merge with no auto flag: an immediate merge that waits
for no check. That is the single form this gate exists to refuse, so the gate
was open on precisely its own subject while denying every neighbouring form.

## Why these cases run the HOOK and not the function

Every existing suite for this gate imports `classify()` and calls it. That is
how a crash in the layer ABOVE classify stayed invisible: calling the function
raises where the test can see it, while the real hook swallows the same crash
into an exit code nobody reads. These cases feed JSON on stdin and read stdout,
which is the only interface Claude Code actually uses.

## Why these live in tests/ and not beside the others in scripts/

The five existing suites are in `q-system/.q-system/scripts/`. lefthook's
pre-commit `verify.sh` runs `pytest` against `q-system/.q-system/tests`, so it
never ran any of them; only the FULL `capability-gate.py` run does, and
`--check-only` skips test execution entirely. That is why a red suite sat red
without blocking a commit. This file is in the directory the commit gate reads.

## No live data path

Every case passes a `cwd` of tmp_path. `_receipt_missing` shells out to `gh`
only when a receipt file already exists; under an empty tmp_path it returns
"no green receipt" and the gate never touches the network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"

# THE REF HATCH. A regression case written after its fix has never been watched
# fail, so it is an assertion about the author's intent rather than evidence.
# Point this at a pre-fix copy of the gate and the suite must go RED:
#
#   git show <pre-fix-sha>:q-system/.q-system/scripts/merge-bypass-gate.py > /tmp/old.py
#   KIPI_MBG_GATE=/tmp/old.py python3 -m pytest <this file>
#
# Measured 2026-08-30 against the pre-ASK-1179 file: 5 failed, 4 passed. All four
# survivors describe behaviour the outage did not change: the sanctioned merge
# form is allowed, an ordinary command is allowed, the crash-injection control
# fires, and a crashed classifier lets an UNRELATED command through (which the
# broken gate also did, for the wrong reason -- it let everything through).
# Those four are guards against over-blocking, not regression cover.
GATE = Path(os.environ.get("KIPI_MBG_GATE") or (SCRIPTS / "merge-bypass-gate.py"))

# The production input. Named as a constant because three cases refer to it and
# the whole point is that THIS string is the one that reached the crash.
NO_AUTO_MERGE = "gh pr merge 155 --squash"
SAFE_MERGE = "gh pr merge --auto --squash 155"


def _run(gate: Path, command: str, cwd: Path):
    payload = json.dumps({"tool_name": "Bash", "cwd": str(cwd),
                          "tool_input": {"command": command}})
    return subprocess.run([sys.executable, str(gate)], input=payload,
                          capture_output=True, text=True, timeout=60)


def _decision(proc):
    """The hook's real contract: a deny is JSON on stdout, not an exit code."""
    out = proc.stdout.strip()
    if not out:
        return None
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


def _crashing_copy(tmp_path: Path) -> Path:
    """A copy of the gate whose classifier raises immediately.

    A COPY, never the live file. The gate under test is the same hook that
    inspects this session's own Bash calls; mutating it in place would disarm
    the guard for every command while the test ran.
    """
    src = GATE.read_text(encoding="utf-8")
    anchor = "def classify(command: str, cwd: str, _depth: int = 0) -> tuple[str, str]:"
    assert src.count(anchor) == 1, "classify signature moved; this injection is stale"
    mutated = src.replace(
        anchor, anchor + '\n    raise RuntimeError("injected classifier crash")')
    dst = tmp_path / "gate-crashing.py"
    dst.write_text(mutated, encoding="utf-8")
    return dst


# ---------------------------------------------------------------------------
# The regression itself
# ---------------------------------------------------------------------------

def test_plain_no_auto_merge_is_denied_through_the_hook_interface(tmp_path):
    """The exact production input that used to crash the classifier."""
    proc = _run(GATE, NO_AUTO_MERGE, tmp_path)
    assert _decision(proc) == "deny", (
        f"the no-auto merge was not blocked. stdout={proc.stdout!r} "
        f"stderr={proc.stderr[-400:]!r}")
    assert "NameError" not in proc.stderr


def test_the_no_auto_refusal_names_what_is_missing(tmp_path):
    """A deny that explains nothing teaches the operator nothing."""
    proc = _run(GATE, NO_AUTO_MERGE, tmp_path)
    reason = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "no green receipt" in reason


def test_the_safe_shape_is_still_allowed(tmp_path):
    """The other direction. A gate that denies everything is not a fixed gate.

    Without this, denying unconditionally would satisfy every case above.
    """
    proc = _run(GATE, SAFE_MERGE, tmp_path)
    assert _decision(proc) is None, f"the sanctioned form was blocked: {proc.stdout!r}"


def test_an_ordinary_command_is_untouched(tmp_path):
    proc = _run(GATE, "ls -la", tmp_path)
    assert _decision(proc) is None


# ---------------------------------------------------------------------------
# The SHAPE: what happens when the classifier raises at all
# ---------------------------------------------------------------------------

def test_the_crash_injection_actually_crashes(tmp_path):
    """Negative control for the two cases below.

    Without this, an injection that silently failed to apply would leave those
    cases passing against the ordinary code path and proving nothing about the
    crash path at all.
    """
    gate = _crashing_copy(tmp_path)
    proc = _run(gate, NO_AUTO_MERGE, tmp_path)
    assert "injected classifier crash" in proc.stderr, (
        "the mutation did not fire, so the crash-path cases below are vacuous")


def test_a_crashing_classifier_denies_a_command_it_governs(tmp_path):
    """Fail CLOSED inside the gate's jurisdiction.

    "I could not tell" and "it is safe" are different answers, and the old shape
    returned the second when it meant the first.
    """
    gate = _crashing_copy(tmp_path)
    proc = _run(gate, NO_AUTO_MERGE, tmp_path)
    assert _decision(proc) == "deny", (
        f"a crashed classifier let a merge through. stdout={proc.stdout!r}")
    reason = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "CRASHED" in reason, "the refusal hides that the gate itself broke"


def test_a_crashing_classifier_also_denies_a_push(tmp_path):
    """The gate governs pushes too, so the crash path must cover both subjects.

    Asserting only the merge half would let a jurisdiction test that checks for
    'merge' alone pass while every push sailed through a crashed classifier.
    """
    gate = _crashing_copy(tmp_path)
    proc = _run(gate, "git push --force origin main", tmp_path)
    assert _decision(proc) == "deny"


def test_a_crashing_classifier_allows_an_unrelated_command_but_is_loud(tmp_path):
    """Fail OPEN outside the jurisdiction, deliberately, and never silently.

    The PreToolUse matcher is Bash, so this hook sees every shell command. A
    blanket deny on any exception would let one classifier bug brick every
    command in the session, including the ones needed to fix it. The traceback
    still goes to stderr, because the failure being repaired here is a gate that
    broke quietly.
    """
    gate = _crashing_copy(tmp_path)
    proc = _run(gate, "ls -la", tmp_path)
    assert _decision(proc) is None, "an unrelated command was blocked by a gate bug"
    assert "injected classifier crash" in proc.stderr, "the crash was swallowed silently"


# ---------------------------------------------------------------------------
# The signature, pinned directly
# ---------------------------------------------------------------------------

def test_merge_verdict_takes_the_cwd_it_uses(tmp_path):
    """The narrow fact underneath the outage, asserted where a reader finds it.

    _merge_verdict's body reads `cwd`; before ASK-1179 nothing supplied it.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("mbg_sig", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import inspect
    params = list(inspect.signature(mod._merge_verdict).parameters)
    assert "cwd" in params, f"_merge_verdict still cannot see a cwd: {params}"
    # And it runs rather than raising, on the input that used to raise.
    reason = mod._merge_verdict(["gh", "pr", "merge", "155", "--squash"], str(tmp_path))
    assert reason and "no green receipt" in reason
