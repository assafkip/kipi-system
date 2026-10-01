"""Tests for the shared mutation harness (plugins/prd-os/scripts/mutate.py).

Scar (ASK-1936, rca-injection-boundary-2026-09-20): across six review rounds of
PR #386, two independent sessions used five bad instruments and every one failed
in the reassuring direction. Two of them produced a wrong DIAGNOSIS from a
mutation run:

  * a stale `__pycache__` measured the unmutated MODULE, so mutants read KILLED;
  * a mutation anchor that no longer matched measured the unmutated FILE -- the
    edit never applied, the run printed a clean 248 green, and that is byte-for-byte
    what a well-defended site looks like on the terminal.

A mutation result is FOUR claims. "The mutant was killed" is meaningless until
the mutant was APPLIED, the check was GREEN first, and the redness is
ATTRIBUTABLE to the mutant rather than to the harness having run the check
twice. These tests pin the three that are not the verdict.

Every case runs against tmp_path. Nothing here touches a live data path.
"""

import ast
import fcntl
import hashlib
import importlib.util
import inspect
import json
import os
import py_compile
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1] / "scripts" / "mutate.py"


def load_harness():
    """Import the harness as a module so a test can DERIVE a value it owns.

    Used for the lock handle and the refusal-tag list. Restating either here
    would create a second source of truth that agrees on the day it is written
    and stops agreeing silently (lessons: derive-a-value-from-its-owner).
    """
    spec = importlib.util.spec_from_file_location("mutate_harness", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# Exit-code contract, restated here only so a reader of this file sees it; the
# harness is the owner and cmd_main() is the single place that decides.
KILLED = 0
SURVIVED = 1
FAILED_EXPERIMENT = 2


def run_harness(*args, cwd=None):
    """Invoke the harness as a subprocess. Returns CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(HARNESS), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def subject(tmp_path):
    """A module with one decision point plus a checker that can actually fail.

    `check.py` exits non-zero when VALUE is not 1, so a mutation of VALUE is
    KILLED and a mutation of the unused constant SURVIVES. Both directions are
    needed: a harness that always reports KILLED is as useless as one that
    always reports SURVIVED.
    """
    src = tmp_path / "subject.py"
    src.write_text("VALUE = 1\nSPARE = 9\n")
    check = tmp_path / "check.py"
    check.write_text(
        "import sys, pathlib\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).parent))\n"
        "import subject\n"
        "sys.exit(0 if subject.VALUE == 1 else 1)\n"
    )
    return src, check


# --------------------------------------------------------------------------
# Claim 2: the mutant was APPLIED. An unapplied mutant is a FAILED EXPERIMENT,
# never a result, and the run must not happen at all.
# --------------------------------------------------------------------------


def test_dead_anchor_is_failed_experiment(tmp_path, subject):
    """The scar in its pure form: the anchor no longer matches the file.

    A harness that falls through to the run here prints a clean green that reads
    exactly like a defended site. It must instead refuse, name FAILED-TO-APPLY,
    and leave the file untouched.
    """
    src, check = subject
    before = digest(src)
    sentinel = tmp_path / "ran"
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 41",  # never present
        "--replacement", "VALUE = 2",
        "--", sys.executable, "-c", f"open({str(sentinel)!r}, 'w').write('x')",
    )
    assert r.returncode == FAILED_EXPERIMENT, r.stdout + r.stderr
    assert "FAILED-TO-APPLY" in (r.stdout + r.stderr)
    assert not sentinel.exists(), "the run executed against an unmutated file"
    assert digest(src) == before


def test_anchor_matching_twice_is_failed_experiment(tmp_path):
    """Two matches means the edit is ambiguous; which site got mutated is unknown.

    Exactly-once is the rule, not at-least-once: a mutation whose location is
    unknown cannot be attributed to the check that killed or survived it.
    """
    src = tmp_path / "twice.py"
    src.write_text("x = 1\ny = 1\n")
    before = digest(src)
    sentinel = tmp_path / "ran"
    r = run_harness(
        "--file", str(src),
        "--anchor", "= 1",
        "--replacement", "= 2",
        "--", sys.executable, "-c", f"open({str(sentinel)!r}, 'w').write('x')",
    )
    assert r.returncode == FAILED_EXPERIMENT, r.stdout + r.stderr
    assert "FAILED-TO-APPLY" in (r.stdout + r.stderr)
    # Not `"2" in output`: the tmp path printed alongside carries digits, so that
    # assertion passes whatever the harness reports and the match count could
    # vanish entirely while the test stayed green (PR #455 review, nit).
    assert "matched 2 times" in (r.stdout + r.stderr), "the match count is not reported"
    assert not sentinel.exists()
    assert digest(src) == before


def test_noop_replacement_is_failed_experiment(tmp_path, subject):
    """Replacement identical to the anchor mutates nothing and always reads green."""
    src, check = subject
    sentinel = tmp_path / "ran"
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 1",
        "--", sys.executable, "-c", f"open({str(sentinel)!r}, 'w').write('x')",
    )
    assert r.returncode == FAILED_EXPERIMENT, r.stdout + r.stderr
    assert "FAILED-TO-APPLY" in (r.stdout + r.stderr)
    assert not sentinel.exists()


# --------------------------------------------------------------------------
# Claim 0: the check was GREEN before the mutant. Without it, "the command went
# red" is not evidence the mutant did anything -- an already-red command reports
# KILLED for every mutant and blesses a guard that is pure decoration.
# --------------------------------------------------------------------------


def test_already_red_command_is_failed_experiment(tmp_path, subject):
    """A command that fails on the unmutated file cannot produce a verdict.

    This is the reassuring-direction failure again: KILLED is exactly what a
    well-defended site looks like, and an already-red suite hands back KILLED for
    every row in a mutation table (PR #455 review, major).
    """
    src, _check = subject
    before = digest(src)
    broken = tmp_path / "broken.py"
    broken.write_text("import sys\nsys.exit(3)\n")
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 2",
        "--", sys.executable, str(broken),
    )
    assert r.returncode == FAILED_EXPERIMENT, r.stdout + r.stderr
    assert "BASELINE-NOT-GREEN" in (r.stdout + r.stderr)
    assert digest(src) == before


def test_baseline_runs_against_the_unmutated_file(tmp_path, subject):
    """The baseline pass must see the ORIGINAL bytes, not the mutant.

    The command logs the subject's content on every invocation, so the log is the
    receipt: two entries, the first unmutated and the second mutated.
    """
    src, _check = subject
    log = tmp_path / "seen.log"
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 2",
        "--", sys.executable, "-c",
        f"open({str(log)!r}, 'a').write(open({str(src)!r}).read() + '===\\n')",
    )
    assert r.returncode == SURVIVED, r.stdout + r.stderr
    seen = [chunk for chunk in log.read_text().split("===\n") if chunk.strip()]
    assert len(seen) == 2, f"expected a baseline pass and a mutant pass, got {len(seen)}"
    assert "VALUE = 1" in seen[0], "the baseline ran against the mutant"
    assert "VALUE = 2" in seen[1], "the mutant pass ran against the original"


def test_baseline_side_effects_are_undone_before_the_mutant(tmp_path, subject):
    """A baseline run that disturbs the subject must not poison the mutant write.

    The command strips write permission. Undone after the baseline, the mutant
    write succeeds; left in place, the harness would refuse with a write error
    and report a fault it caused itself.
    """
    src, _check = subject
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 2",
        "--", sys.executable, "-c",
        f"import os; os.chmod({str(src)!r}, 0o400)",
    )
    os.chmod(src, 0o600)  # so tmp_path teardown can clean up
    assert "cannot write mutant" not in (r.stdout + r.stderr), r.stdout + r.stderr
    assert "applied: yes" in r.stdout, r.stdout + r.stderr


# --------------------------------------------------------------------------
# Claim 3: the redness is ATTRIBUTABLE to the mutant. Measuring a baseline made
# the harness run the check TWICE, so a check that is green once and red after
# (a leftover file, a port, a row in a table) hands back KILLED for a mutant it
# never saw -- the baseline guard's own side effect (PR #455 review round 2).
# --------------------------------------------------------------------------


def nonhermetic_command(counter: Path) -> list:
    """A check that passes on its first invocation and fails on every one after.

    The commonest real shape: the check leaves state behind (a created row, a
    written file, a bound port) and the second run trips over it. Nothing here
    reads the subject, so any red it produces is the harness's own doing.
    """
    return [
        sys.executable, "-c",
        "import pathlib, sys; "
        f"p = pathlib.Path({str(counter)!r}); "
        "n = int(p.read_text()) if p.exists() else 0; "
        "p.write_text(str(n + 1)); "
        "sys.exit(0 if n == 0 else 1)",
    ]


def test_nonhermetic_check_is_failed_experiment_not_killed(tmp_path, subject):
    """Green-then-red from run count alone must never read as KILLED.

    The mutant is on SPARE, which the command does not read, so the only thing
    that could turn the second pass red is the command itself. Before the
    attribution pass existed this printed exit 0 / KILLED and credited a guard
    that does not exist.
    """
    src, _check = subject
    before = digest(src)
    counter = tmp_path / "invocations"
    r = run_harness(
        "--file", str(src),
        "--anchor", "SPARE = 9",
        "--replacement", "SPARE = 8",
        "--", *nonhermetic_command(counter),
    )
    assert r.returncode == FAILED_EXPERIMENT, r.stdout + r.stderr
    assert "NON-HERMETIC-CHECK" in (r.stdout + r.stderr)
    assert digest(src) == before


def test_attribution_pass_runs_against_the_restored_original(tmp_path, subject):
    """The confirming pass must see the ORIGINAL bytes, or it proves nothing.

    The command logs what it read on every invocation. A KILLED verdict must
    therefore leave three entries: unmutated, mutated, unmutated again.
    """
    src, _check = subject
    log = tmp_path / "seen.log"
    reader = (
        f"open({str(log)!r}, 'a').write(open({str(src)!r}).read() + '===\\n'); "
        f"__import__('sys').exit(0 if 'VALUE = 1' in open({str(src)!r}).read() else 1)"
    )
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 2",
        "--", sys.executable, "-c", reader,
    )
    assert r.returncode == KILLED, r.stdout + r.stderr
    seen = [chunk for chunk in log.read_text().split("===\n") if chunk.strip()]
    assert len(seen) == 3, f"expected baseline, mutant and attribution passes, got {len(seen)}"
    assert "VALUE = 1" in seen[0]
    assert "VALUE = 2" in seen[1]
    assert "VALUE = 1" in seen[2], "the attribution pass ran against the mutant"


def test_survived_costs_no_attribution_pass(tmp_path, subject):
    """A SURVIVED verdict claims the mutant caused nothing, so it needs no proof.

    Only a KILLED verdict asserts causation, and only that assertion can be
    manufactured by the extra baseline run. Spending a third pass on every
    SURVIVED row would add 50% to a mutation table's cost for no claim.
    """
    src, check = subject
    counter = tmp_path / "invocations"
    r = run_harness(
        "--file", str(src),
        "--anchor", "SPARE = 9",
        "--replacement", "SPARE = 8",
        "--", sys.executable, "-c",
        "import pathlib; "
        f"p = pathlib.Path({str(counter)!r}); "
        "n = int(p.read_text()) if p.exists() else 0; "
        "p.write_text(str(n + 1))",
    )
    assert r.returncode == SURVIVED, r.stdout + r.stderr
    assert counter.read_text() == "2", "a SURVIVED verdict paid for an attribution pass"


# --------------------------------------------------------------------------
# The mutant window is closed on every exit path, not just the happy one.
# --------------------------------------------------------------------------


def hangs_on_the_mutant_pass(counter: Path) -> str:
    """Command source that returns green on the baseline pass and then hangs.

    The baseline pass has to complete, or the interrupt lands while the subject
    is still original and proves nothing about the mutant window.
    """
    return (
        "import pathlib, time; "
        f"p = pathlib.Path({str(counter)!r}); "
        "n = int(p.read_text()) if p.exists() else 0; "
        "p.write_text(str(n + 1)); "
        "n and time.sleep(30)"
    )


def test_sigint_during_the_run_still_restores_the_subject(tmp_path, subject):
    """Ctrl-C inside the mutant window must not leave the mutant on disk.

    The docstring promises the subject is ALWAYS restored. Without a handler and
    a finally, an interrupt during the run left the mutated file in the working
    tree, which then poisons every later run and every later diff.
    """
    src, _check = subject
    before = src.read_bytes()
    counter = tmp_path / "invocations"
    proc = subprocess.Popen(
        [sys.executable, str(HARNESS),
         "--file", str(src),
         "--anchor", "VALUE = 1",
         "--replacement", "VALUE = 2",
         "--", sys.executable, "-c", hangs_on_the_mutant_pass(counter)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    # Wait for the SECOND invocation: the first is the baseline pass, when the
    # subject is still original and an interrupt would prove nothing.
    deadline = time.time() + 20
    while time.time() < deadline:
        if counter.exists() and counter.read_text() == "2":
            break
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    assert counter.exists() and counter.read_text() == "2", "never reached the mutant window"
    assert src.read_bytes() != before, "the subject was not mutated yet"
    proc.send_signal(signal.SIGINT)
    out, err = proc.communicate(timeout=30)
    assert src.read_bytes() == before, "the interrupt left the mutant on disk: " + out + err
    assert proc.returncode == FAILED_EXPERIMENT, out + err


def test_timeout_is_a_failed_experiment_not_a_verdict(tmp_path, subject):
    """A command that never returns produced no measurement, so it has no verdict.

    Unattended (a CI job, a mutation table left running), a hang holds the
    subject's lock forever and the mutant stays on disk. --timeout turns that
    into a refusal that restores.
    """
    src, _check = subject
    before = src.read_bytes()
    counter = tmp_path / "invocations"
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 2",
        "--timeout", "2",
        "--", sys.executable, "-c", hangs_on_the_mutant_pass(counter),
    )
    assert r.returncode == FAILED_EXPERIMENT, r.stdout + r.stderr
    assert "TIMEOUT" in (r.stdout + r.stderr)
    assert counter.read_text() == "2", "the hang was not in the mutant window"
    assert src.read_bytes() == before


# --------------------------------------------------------------------------
# One writer at a time: two concurrent runs on one subject each read the
# other's mutant as "the original" and each restore it, so the mutant stays on
# disk while both print "restored: yes" (PR #455 review, minor).
# --------------------------------------------------------------------------


def test_the_lock_leaves_no_file_behind(tmp_path, subject):
    """A per-run lock FILE in the temp dir accumulates without bound.

    18 per suite run, unbounded in run count, on a fleet that already has an open
    disk item (PR #455 review round 2). Unlinking one is racy -- the next process
    opens the path, gets a fresh inode and locks nothing -- so the subject's own
    inode is the lock and no file is created at all.
    """
    src, check = subject
    tmpdir = Path(tempfile.gettempdir())
    before = set(os.listdir(tmpdir))
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 2",
        "--", sys.executable, str(check),
    )
    assert r.returncode == KILLED, r.stdout + r.stderr
    added = [n for n in set(os.listdir(tmpdir)) - before if "mutate" in n]
    assert not added, f"the run left lock litter in the temp dir: {added}"


def test_a_second_run_on_the_same_subject_is_refused(tmp_path, subject):
    src, _check = subject
    before = digest(src)
    harness = load_harness()
    held = harness.open_lock(str(src))
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    sentinel = tmp_path / "ran"
    try:
        r = run_harness(
            "--file", str(src),
            "--anchor", "VALUE = 1",
            "--replacement", "VALUE = 2",
            "--", sys.executable, "-c", f"open({str(sentinel)!r}, 'w').write('x')",
        )
    finally:
        fcntl.flock(held, fcntl.LOCK_UN)
        held.close()
    assert r.returncode == FAILED_EXPERIMENT, r.stdout + r.stderr
    assert "already running" in (r.stdout + r.stderr).lower()
    assert not sentinel.exists(), "the second run measured a tree it did not own"
    assert digest(src) == before


def test_the_lock_is_released_so_a_later_run_is_not_blocked(tmp_path, subject):
    """A refusal that never released would turn one run into a permanent block."""
    src, check = subject
    for _ in range(2):
        r = run_harness(
            "--file", str(src),
            "--anchor", "VALUE = 1",
            "--replacement", "VALUE = 2",
            "--", sys.executable, str(check),
        )
        assert r.returncode == KILLED, r.stdout + r.stderr


def test_json_flag_emits_json_on_the_failure_path(tmp_path, subject):
    """--json promises one JSON object on stdout; a refusal is still an answer.

    Plain text here breaks any consumer that parses the stream, and the failure
    path is exactly the one a consumer must be able to read (PR #455 review).
    """
    src, _check = subject
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 41",  # never present
        "--replacement", "VALUE = 2",
        "--label", "dead anchor",
        "--json",
        "--", sys.executable, "-c", "pass",
    )
    assert r.returncode == FAILED_EXPERIMENT, r.stdout + r.stderr
    receipt = json.loads(r.stdout)
    assert receipt["applied"] is False
    assert receipt["verdict"] == "FAILED-TO-APPLY"
    assert receipt["label"] == "dead anchor"
    assert receipt["reason"]


def test_receipt_proves_the_bytes_moved(tmp_path, subject):
    """The receipt carries the applied-claim evidence, not just the verdict.

    Digest before != digest after is the honest form of "the byte count moved":
    a length-preserving mutant is legitimate (it isolates a hash or a comparison)
    and a byte-count assertion would refuse it.
    """
    src, check = subject
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 2",
        "--json",
        "--", sys.executable, str(check),
    )
    receipt = json.loads(r.stdout)
    assert receipt["applied"] is True
    assert receipt["anchor_matches"] == 1
    assert receipt["digest_before"] != receipt["digest_after"]
    assert receipt["bytes_before"] == receipt["bytes_after"], "this mutant is length-preserving"
    assert receipt["verdict"] == "KILLED"


# --------------------------------------------------------------------------
# Claim 1: killed vs survived. Both directions must be reachable.
# --------------------------------------------------------------------------


def test_killed_mutant_exits_zero_and_restores(tmp_path, subject):
    src, check = subject
    before = digest(src)
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 2",
        "--", sys.executable, str(check),
    )
    assert r.returncode == KILLED, r.stdout + r.stderr
    assert "KILLED" in r.stdout
    assert digest(src) == before, "the harness left the mutant on disk"


def test_surviving_mutant_exits_one(tmp_path, subject):
    """A site the checker does not read must report SURVIVED, not KILLED."""
    src, check = subject
    r = run_harness(
        "--file", str(src),
        "--anchor", "SPARE = 9",
        "--replacement", "SPARE = 8",
        "--", sys.executable, str(check),
    )
    assert r.returncode == SURVIVED, r.stdout + r.stderr
    assert "SURVIVED" in r.stdout


def test_file_restored_when_the_run_deletes_it(tmp_path, subject):
    """Restore is unconditional and verified, not best-effort."""
    src, check = subject
    before = src.read_bytes()
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 2",
        "--", sys.executable, "-c", f"import os; os.remove({str(src)!r})",
    )
    assert r.returncode in (KILLED, SURVIVED), r.stdout + r.stderr
    assert src.read_bytes() == before


# --------------------------------------------------------------------------
# The other half of the scar: a bytecode cache measuring the unmutated MODULE.
# --------------------------------------------------------------------------


def test_child_runs_with_bytecode_writing_off(tmp_path, subject):
    """PYTHONDONTWRITEBYTECODE=1 on every run, and a cache prefix off the tree.

    DONTWRITEBYTECODE only stops WRITING. The read side is PYTHONPYCACHEPREFIX,
    pointed at a fresh directory so no pre-existing cache in the source tree can
    be consulted. Both halves or the read scar survives.
    """
    src, check = subject
    dump = tmp_path / "env.json"
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 2",
        "--", sys.executable, "-c",
        f"import os, json; json.dump(dict(os.environ), open({str(dump)!r}, 'w'))",
    )
    env = json.loads(dump.read_text())
    assert env.get("PYTHONDONTWRITEBYTECODE") == "1"
    prefix = env.get("PYTHONPYCACHEPREFIX")
    assert prefix, "no read-side cache defense"
    assert not Path(prefix).is_relative_to(tmp_path), "cache prefix sits inside the source tree"
    assert not (tmp_path / "__pycache__").exists()


def test_poisoned_cache_cannot_fake_a_result(tmp_path, subject):
    """A cache that ignores the source must not decide the verdict.

    Built with an UNCHECKED_HASH pyc: CPython trusts it without validating the
    source at all, which is the deterministic form of the stale-cache scar. The
    poisoned cache holds VALUE = 1, so an undefended run imports the UNMUTATED
    module, the checker passes, and the harness reports SURVIVED -- a wrong
    diagnosis, not just a wrong number. With the cache prefix moved off the tree
    the source is compiled and the verdict is KILLED.
    """
    src, check = subject
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    tag = sys.implementation.cache_tag
    py_compile.compile(
        str(src),
        cfile=str(cache / f"subject.{tag}.pyc"),
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
        doraise=True,
    )
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 2",
        "--", sys.executable, str(check),
    )
    assert r.returncode == KILLED, (
        "the poisoned cache decided the verdict: " + r.stdout + r.stderr
    )


def test_unrestorable_tree_after_the_mutant_run_is_failed_experiment(tmp_path, subject):
    """The same refusal, but reached from the MUTANT restore rather than the baseline.

    Two restores exist now and each needs its own case: the baseline one below,
    and this one. A command that destroys the subject on EVERY invocation only
    ever reaches the first, which left the second guard with no test and its
    mutant surviving (D3 in mutants_of_mutate.py, caught 2026-09-27). This
    command counts its invocations and destroys the subject only on the second,
    so the baseline passes cleanly and the mutant restore is the one that fails.
    """
    src, _check = subject
    counter = tmp_path / "invocations"
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 2",
        "--", sys.executable, "-c",
        "import os, pathlib; "
        f"p = pathlib.Path({str(counter)!r}); "
        "n = int(p.read_text()) if p.exists() else 0; "
        "p.write_text(str(n + 1)); "
        f"n and (os.remove({str(src)!r}), os.mkdir({str(src)!r}))",
    )
    assert counter.read_text() == "2", "the command did not run twice"
    assert r.returncode == FAILED_EXPERIMENT, r.stdout + r.stderr
    assert "FAILED-TO-APPLY" in (r.stdout + r.stderr)
    assert "could not be verified" in (r.stdout + r.stderr)


def test_unrestorable_tree_is_failed_experiment(tmp_path, subject):
    """A mutant left on disk poisons every run after it, so it is not a result.

    Reachable branch, unlike the two digest compares noted in
    mutants_of_mutate.py: the run's own command replaces the subject with a
    DIRECTORY, so the restore write genuinely raises. The harness must report
    FAILED-TO-APPLY and name the file rather than hand back a KILLED/SURVIVED
    verdict computed on a dirty tree.

    Two levers ruled out, so the next reader does not retry them. A read-only
    parent directory still permits rewriting an existing file on this platform
    (dir write governs create/delete/rename). Stripping write permission from the
    file no longer works either, because the restore now puts the original MODE
    back as well -- an owner may always chmod, so that path is recoverable by
    design and is covered by test_baseline_side_effects_are_undone_before_the_mutant.
    """
    src, check = subject
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 2",
        "--", sys.executable, "-c",
        f"import os; os.remove({str(src)!r}); os.mkdir({str(src)!r})",
    )
    assert r.returncode == FAILED_EXPERIMENT, r.stdout + r.stderr
    assert "FAILED-TO-APPLY" in (r.stdout + r.stderr)
    assert "could not be verified" in (r.stdout + r.stderr)


def test_unrestorable_tree_after_the_attribution_run_is_failed_experiment(tmp_path, subject):
    """Three passes now means THREE restores, and the third needs its own case.

    The first two are covered above. A command that destroys the subject on
    every invocation only ever reaches the first restore, which is exactly how
    the mutant restore went untested and its guard survived (D3, 2026-09-27).
    This command counts: green, then red so the attribution pass is reached,
    then destructive.
    """
    src, _check = subject
    counter = tmp_path / "invocations"
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 2",
        "--", sys.executable, "-c",
        "import os, pathlib, sys; "
        f"p = pathlib.Path({str(counter)!r}); "
        "n = int(p.read_text()) if p.exists() else 0; "
        "p.write_text(str(n + 1)); "
        f"n == 2 and (os.remove({str(src)!r}), os.mkdir({str(src)!r})); "
        "sys.exit(1 if n == 1 else 0)",
    )
    assert counter.read_text() == "3", "the attribution pass did not run"
    assert r.returncode == FAILED_EXPERIMENT, r.stdout + r.stderr
    assert "could not be verified" in (r.stdout + r.stderr)


def test_every_refusal_tag_is_declared_and_documented():
    """--json emits the TAG, so the tag list is part of the caller's contract.

    The contract named only "FAILED EXPERIMENT" while the receipts carried
    FAILED-TO-APPLY and BASELINE-NOT-GREEN, so a consumer switching on verdict
    met strings no document mentions (PR #455 review round 2). Both sets are
    DERIVED -- the used set by parsing the source, the declared set by importing
    it -- so adding a tag without declaring or documenting it goes red.
    """
    harness = load_harness()
    tree = ast.parse(HARNESS.read_text())
    default_tag = inspect.signature(harness.refuse).parameters["tag"].default
    used = {default_tag}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "refuse":
            continue
        for kw in node.keywords:
            if kw.arg == "tag" and isinstance(kw.value, ast.Constant):
                used.add(kw.value.value)
    assert len(used) > 1, "the tag parse found nothing; the derivation is broken"
    assert used == set(harness.REFUSAL_TAGS), (
        f"REFUSAL_TAGS does not match the tags the code emits: "
        f"declared-not-used={set(harness.REFUSAL_TAGS) - used}, "
        f"used-not-declared={used - set(harness.REFUSAL_TAGS)}"
    )
    doc = harness.__doc__ or ""
    undocumented = [tag for tag in harness.REFUSAL_TAGS if tag not in doc]
    assert not undocumented, f"exit-2 tags missing from the module contract: {undocumented}"


def test_missing_file_is_failed_experiment(tmp_path):
    """A subject path that does not exist is an experiment fault, not a result."""
    r = run_harness(
        "--file", str(tmp_path / "absent.py"),
        "--anchor", "a",
        "--replacement", "b",
        "--", sys.executable, "-c", "pass",
    )
    assert r.returncode == FAILED_EXPERIMENT, r.stdout + r.stderr
    assert "FAILED-TO-APPLY" in (r.stdout + r.stderr)
