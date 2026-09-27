"""Tests for the shared mutation harness (plugins/prd-os/scripts/mutate.py).

Scar (ASK-1936, rca-injection-boundary-2026-09-20): across six review rounds of
PR #386, two independent sessions used five bad instruments and every one failed
in the reassuring direction. Two of them produced a wrong DIAGNOSIS from a
mutation run:

  * a stale `__pycache__` measured the unmutated MODULE, so mutants read KILLED;
  * a mutation anchor that no longer matched measured the unmutated FILE -- the
    edit never applied, the run printed a clean 248 green, and that is byte-for-byte
    what a well-defended site looks like on the terminal.

A mutation result is TWO claims. "The mutant was killed" is meaningless until
"the mutant was applied" is proven. These tests pin the second claim.

Every case runs against tmp_path. Nothing here touches a live data path.
"""

import hashlib
import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1] / "scripts" / "mutate.py"

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
    assert "2" in (r.stdout + r.stderr), "the match count is not reported"
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


def test_unrestorable_tree_is_failed_experiment(tmp_path, subject):
    """A mutant left on disk poisons every run after it, so it is not a result.

    Reachable branch, unlike the two digest compares noted in
    mutants_of_mutate.py: the run's own command strips write permission from the
    subject FILE, so the restore write genuinely raises. The harness must report
    FAILED-TO-APPLY and name the file rather than hand back a KILLED/SURVIVED
    verdict computed on a dirty tree.

    Not the directory: on this platform a read-only directory still permits
    rewriting an existing file (dir write governs create/delete/rename), so the
    first version of this test passed the restore and failed for the wrong reason.
    """
    src, check = subject
    r = run_harness(
        "--file", str(src),
        "--anchor", "VALUE = 1",
        "--replacement", "VALUE = 2",
        "--", sys.executable, "-c",
        f"import os; os.chmod({str(src)!r}, 0o400)",
    )
    os.chmod(src, 0o600)  # so tmp_path teardown can clean up
    assert r.returncode == FAILED_EXPERIMENT, r.stdout + r.stderr
    assert "FAILED-TO-APPLY" in (r.stdout + r.stderr)
    assert "still on disk" in (r.stdout + r.stderr)


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
