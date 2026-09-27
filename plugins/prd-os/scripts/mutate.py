#!/usr/bin/env python3
"""mutate.py -- the shared mutation harness for this fleet.

A mutation result is FOUR claims and usually only one of them gets checked:

    0. the check was GREEN before the mutant (the baseline)
    1. the mutant was KILLED (the check under test went red)
    2. the mutant was APPLIED (the bytes the check ran against actually moved)
    3. the redness is ATTRIBUTABLE to the mutant, not to the run count

Claim 1 is meaningless until 0, 2 and 3 are proven. An unapplied mutant and a
well-defended one are identical bytes on the terminal; so are a killed mutant
and a command that was already red before anything was mutated; and so is a
check that simply fails the second time it runs. This script proves 0, 2 and 3
before it will report 1, and refuses with an exit-2 FAILED EXPERIMENT when it
cannot.

Scar (ASK-1936, rca-injection-boundary-2026-09-20): across six review rounds of
PR assafkip/kipi-system#386, two independent sessions used five bad instruments
and every one failed in the reassuring direction. The two that killed this
script into existence:

  * A stale `__pycache__` measured the unmutated MODULE. Mutants read as KILLED.
  * A mutation anchor that no longer matched measured the unmutated FILE. The
    edit never applied and the run printed a clean 248 green. That happened
    while verifying the RCA's own fix, because the fix had spanned the anchored
    call across two lines.

The baseline guard comes from the same family, hit live 2026-09-27 while
building this script: one broken test turned a 7-row mutation table all-KILLED,
including two rows that had SURVIVED minutes earlier. A command that is already
red kills every mutant, so the table blesses guards that are pure decoration.

Claim 3 is the baseline guard's OWN side effect, and it is the reason the claims
are listed rather than patched one at a time: measuring a baseline made the
harness run the check twice, so a check that is green once and red after -- a
leftover file, a bound port, a row it inserted -- now hands back a KILLED for a
mutant it never saw. Every claim here is the same defect wearing a new surface:
something other than the mutant decided the verdict.

Usage:

    python3 plugins/prd-os/scripts/mutate.py \
        --file path/to/subject.py \
        --anchor 'exact text, matching exactly once' \
        --replacement 'what it becomes' \
        -- pytest -q path/to/test_subject.py

Exit codes (the caller's contract; a CI job wants 0):

    0  KILLED            the mutant applied AND the command went red BECAUSE OF IT
    1  SURVIVED          the mutant applied AND the command stayed green
    2  FAILED EXPERIMENT nothing was measured -- never read this as a result

Exit 2 always carries a TAG, on stderr and as the `verdict` of the --json
receipt, so the tags are part of the caller's contract rather than incidental
text. They are declared once in REFUSAL_TAGS below and named here:

    FAILED-TO-APPLY     the anchor missed or was ambiguous, the replacement
                        mutated nothing, the subject could not be read or
                        written, the restore could not be verified, or a signal
                        arrived while the mutant was on disk
    BASELINE-NOT-GREEN  the command was already red against the UNMUTATED file
    NON-HERMETIC-CHECK  the command went red again against the RESTORED file,
                        so its redness is not attributable to the mutant
    TIMEOUT             the command did not return inside --timeout

`test_every_refusal_tag_is_declared_and_documented` derives the used set from
this file's syntax tree and the declared set by importing it, so a tag added
without a declaration or without a line above goes red.

The subject file is always restored, and the restore is verified by digest
rather than assumed. "Always" covers a failing command, a command that deletes
or chmods the subject, an unexpected exception, and SIGINT/SIGTERM. It does NOT
cover SIGKILL or a power cut: no in-process handler runs for those and the
mutant survives on disk, which is why a mutation run belongs on a tree whose
`git diff` you can read afterwards.
"""

import argparse
import collections
import fcntl
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile

FAILED_EXPERIMENT = 2

# Every tag exit 2 can carry. Declared in one place because --json publishes it
# as `verdict`, so a consumer switching on the value needs a closed set to
# switch over (PR #455 review round 2). Documented in the module docstring
# above; a test derives both sides and fails when they part company.
REFUSAL_TAGS = (
    "FAILED-TO-APPLY",
    "BASELINE-NOT-GREEN",
    "NON-HERMETIC-CHECK",
    "TIMEOUT",
)

# One pass of the check under test.
Pass = collections.namedtuple("Pass", "exit error prefix timed_out")


class _Interrupted(Exception):
    """A signal arrived while the mutant was on disk."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def refuse(reason: str, args, tag: str = "FAILED-TO-APPLY") -> int:
    """Refuse loudly. An anchor miss must never fall through to the run.

    Printed to stderr AND on stdout so a caller grepping either stream sees it:
    the scar was a human reading a terminal and taking a green at face value.

    The stdout half honours --json. A refusal is still an answer, and the failure
    path is exactly the one a machine consumer has to be able to parse; emitting
    plain text here while --json promised an object broke that consumer silently
    (PR #455 review).
    """
    print(f"{tag}: {reason}", file=sys.stderr)
    if getattr(args, "as_json", False):
        print(json.dumps({
            "label": getattr(args, "label", ""),
            "file": getattr(args, "file", ""),
            "applied": False,
            "verdict": tag,
            "reason": reason,
        }))
    else:
        print(f"verdict: {tag} (nothing was measured)")
    return FAILED_EXPERIMENT


def open_lock(subject: str):
    """The lock handle for one subject: the SUBJECT'S OWN file descriptor.

    Not a lock FILE in the temp dir. That file was never removed -- 18 per suite
    run, unbounded in run count, on a fleet with an open disk item (PR #455
    review round 2) -- and removing it is worse than leaving it: the holder
    unlinks, the next process opens the path, gets a FRESH inode, locks that,
    and two runs proceed against one subject.

    flock is per-inode, so the subject is its own lock. Nothing accumulates,
    there is no unlink race, and two callers naming the file by different paths
    or through a hard link collide rather than both proceeding -- which the
    realpath key only covered for symlinks.

    HONEST BOUNDARY: a command that UNLINKS the subject orphans this inode, and
    the restore then creates one this handle does not cover. That window runs
    from the unlink to the end of the experiment, and it is strictly smaller
    than the unlink race a temp-file lock would have carried.
    """
    return open(subject, "rb")


def acquire(lock_fh) -> bool:
    """Take the subject's lock, or report that someone else holds it.

    Non-blocking on purpose. Two concurrent runs on one subject each read the
    other's mutant as "the original" and each restore it, so the mutant stays on
    disk while both print "restored: yes" -- a wrong tree AND two wrong verdicts
    (PR #455 review). Refusing surfaces that; queueing would hide it.
    """
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def child_env(cache_prefix: str) -> dict:
    """The environment every mutation run gets.

    PYTHONDONTWRITEBYTECODE=1 stops the run from LEAVING a cache behind.
    It does not stop the run from READING one that is already there, which is
    the half the 2026-09-20 scar actually tripped over -- so the read side is
    pinned too, by pointing the cache tree at a fresh empty directory outside
    the source. Both halves, or the stale-module diagnosis comes back.
    """
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = cache_prefix
    return env


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="mutate.py",
        description="Run one mutation experiment, proving the mutant applied before reporting whether it was killed.",
    )
    p.add_argument("--file", required=True, help="the subject file to mutate")
    p.add_argument("--anchor", required=True, help="exact text; must match EXACTLY ONCE")
    p.add_argument("--replacement", required=True, help="what the anchor becomes (may be empty)")
    p.add_argument("--label", default="", help="free-text name for this experiment, echoed in the receipt")
    p.add_argument("--json", action="store_true", dest="as_json", help="emit the receipt as one JSON object on stdout")
    p.add_argument("--timeout", type=float, default=0.0,
                   help="seconds before a pass of the command is a TIMEOUT refusal (0 = no limit)")
    p.add_argument("cmd", nargs="+", help="the command to run against the mutated file")
    args = p.parse_args(argv)

    # One writer per subject, for the whole experiment. Held across the baseline
    # run, the mutant write, the mutant run, the attribution run and every
    # restore -- every window in which another run would read a mutated file as
    # its original.
    try:
        lock_fh = open_lock(args.file)
    except OSError as exc:
        return refuse(f"cannot read subject {args.file}: {exc}", args)
    try:
        if not acquire(lock_fh):
            return refuse(
                f"another mutation run is already running against {args.file}. "
                "Concurrent runs restore each other's mutants and both report a clean tree.",
                args,
            )
        return _experiment(args)
    finally:
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()


def _experiment(args) -> int:
    path = args.file

    # --- claim 2, step 1: the subject exists and the anchor is unambiguous ----
    try:
        with open(path, "rb") as fh:
            original = fh.read()
        original_mode = stat.S_IMODE(os.stat(path).st_mode)
    except OSError as exc:
        return refuse(f"cannot read subject {path}: {exc}", args)

    anchor = args.anchor.encode()
    replacement = args.replacement.encode()

    if anchor == replacement:
        return refuse(
            "anchor and replacement are identical; this experiment mutates nothing "
            "and would report a green that means nothing",
            args,
        )

    matches = original.count(anchor)
    if matches != 1:
        # Exactly-once, not at-least-once. Zero is the anchor-drift scar. Two or
        # more means the mutated site is unknown, so no verdict can be attributed
        # to the check that produced it.
        return refuse(
            f"anchor matched {matches} times in {path}, expected exactly 1. "
            "Re-read the file and re-anchor; do not loosen the anchor.",
            args,
        )

    # --- claim 0: the check is GREEN before anything is mutated --------------
    # Cheapest place to spend the extra run: after the anchor checks, so an
    # experiment that was going to refuse anyway never pays for it.
    baseline = _run(args.cmd, "mutate-baseline-", args.timeout)
    if not _restore(path, original, original_mode):
        return _dirty_tree(path, args)
    bad = _pass_fault(baseline, "baseline", path, args)
    if bad is not None:
        return bad
    if baseline.exit != 0:
        return refuse(
            f"the command exits {baseline.exit} against the UNMUTATED {path}. "
            "An already-red check reports KILLED for every mutant, which blesses "
            "guards that are decoration. Make it green, then mutate.",
            args,
            tag="BASELINE-NOT-GREEN",
        )

    mutated = original.replace(anchor, replacement, 1)

    # --- claim 2, step 2: the bytes on disk actually moved -------------------
    # Digest, not length. A length-preserving mutant is legitimate -- it is how
    # you isolate a hash or a comparison from everything else -- so a byte-count
    # assertion would refuse a whole class of honest experiments.
    #
    # There is deliberately no in-memory "did the content change" check here:
    # given anchor != replacement and exactly one match, it cannot fail, and a
    # predicate whose false branch is unreachable reports success forever while
    # looking like a guard. The reachable check is the READ-BACK below.
    digest_before = sha256(original)
    digest_after = sha256(mutated)

    # --- claims 1 and 3, inside a window that closes on EVERY exit path ------
    # Handlers installed before the write and removed after the last restore.
    # Turning a signal into an exception is what lets one `except` own the
    # restore; without it, Ctrl-C during the run left the mutant on disk, which
    # poisons every later run and every later diff (PR #455 review round 2).
    previous = _guard_window()
    try:
        return _mutant_pass(args, path, original, original_mode, mutated,
                            matches, digest_before, digest_after, baseline.exit)
    except _Interrupted as exc:
        _restore(path, original, original_mode)
        return refuse(
            f"{exc} arrived while the mutant was on disk in {path}. The subject "
            "was restored and nothing was measured.",
            args,
        )
    except BaseException:
        # Anything else that escapes -- an OSError nobody anticipated, an
        # interrupt racing the handler install -- still closes the window. The
        # traceback is the caller's to see; the dirty tree is not.
        _restore(path, original, original_mode)
        raise
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _mutant_pass(args, path, original, original_mode, mutated,
                 matches, digest_before, digest_after, baseline_exit) -> int:
    """Write the mutant, run the check, restore, and confirm the attribution."""
    try:
        with open(path, "wb") as fh:
            fh.write(mutated)
    except OSError as exc:
        return refuse(f"cannot write mutant to {path}: {exc}", args)

    with open(path, "rb") as fh:
        on_disk = sha256(fh.read())
    if on_disk != digest_after:
        _restore(path, original, original_mode)
        return refuse(
            f"read-back of {path} does not match the intended mutant "
            f"({on_disk[:12]} != {digest_after[:12]})",
            args,
        )

    run = _run(args.cmd, "mutate-mutant-", args.timeout)
    if not _restore(path, original, original_mode):
        return _dirty_tree(path, args)
    bad = _pass_fault(run, "mutant", path, args)
    if bad is not None:
        return bad

    attribution = None
    if run.exit == 0:
        verdict = "SURVIVED"
    else:
        # --- claim 3: the redness belongs to the mutant ----------------------
        # Only a KILLED verdict asserts causation, and only that assertion can
        # be manufactured by the extra baseline run, so only KILLED pays for a
        # third pass. Spending one on every SURVIVED row would add 50% to a
        # mutation table's wall clock and prove nothing that was claimed.
        confirm = _run(args.cmd, "mutate-confirm-", args.timeout)
        if not _restore(path, original, original_mode):
            return _dirty_tree(path, args)
        bad = _pass_fault(confirm, "attribution", path, args)
        if bad is not None:
            return bad
        if confirm.exit != 0:
            return refuse(
                f"the command exits {confirm.exit} against the RESTORED {path}, "
                f"after exiting 0 against the same bytes at the baseline. It is "
                "not hermetic -- it fails on its own second run -- so its red "
                "cannot be attributed to the mutant. Make the check repeatable, "
                "then mutate.",
                args,
                tag="NON-HERMETIC-CHECK",
            )
        verdict = "KILLED"
        attribution = confirm.exit

    receipt = {
        "label": args.label,
        "file": path,
        "applied": True,
        "anchor_matches": matches,
        "digest_before": digest_before,
        "digest_after": digest_after,
        "bytes_before": len(original),
        "bytes_after": len(mutated),
        "env_pins": {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": run.prefix},
        "baseline_exit": baseline_exit,
        "run_exit": run.exit,
        "attribution_exit": attribution,
        "verdict": verdict,
        "restored": True,
    }

    if args.as_json:
        print(json.dumps(receipt))
    else:
        print(f"applied: yes (anchor matched {matches}x, "
              f"{digest_before[:12]} -> {digest_after[:12]}, "
              f"{len(original)} -> {len(mutated)} bytes)")
        print(f"baseline exit: {baseline_exit} (green, measured on the unmutated file)")
        print(f"run exit: {run.exit}  (bytecode cache: write off, read from {run.prefix})")
        if attribution is None:
            print("attribution: not needed (SURVIVED claims no causation)")
        else:
            print(f"attribution exit: {attribution} (green again on the restored file)")
        print(f"restored: yes\nverdict: {verdict}")

    return 0 if verdict == "KILLED" else 1


def _guard_window():
    """Turn SIGINT/SIGTERM into an exception for the life of the mutant window.

    Returns the handlers it replaced, so the caller can put them back.

    HONEST BOUNDARY: SIGKILL and a power cut run no handler at all. The mutant
    survives on disk and the lock does not detect it, which is why the harness
    prints its restore rather than assuming it.
    """
    def raise_interrupt(signum, _frame):
        raise _Interrupted(signal.Signals(signum).name)

    return {sig: signal.signal(sig, raise_interrupt)
            for sig in (signal.SIGINT, signal.SIGTERM)}


def _pass_fault(result: Pass, which: str, path: str, args):
    """The two ways a pass produces no number. Returns an exit code, or None.

    Shared by all three passes because "the command never returned a verdict"
    means the same thing wherever it happens, and three copies of this would
    drift (the baseline copy already did, gaining a timeout the mutant pass had
    no equivalent of).
    """
    if result.timed_out:
        return refuse(
            f"the {which} pass did not return inside {args.timeout}s against {path}. "
            "A hang measures nothing and, unattended, holds the subject's lock "
            "with the mutant on disk.",
            args,
            tag="TIMEOUT",
        )
    if result.error is not None:
        return refuse(f"cannot run the command: {result.error}", args)
    return None


def _run(cmd, prefix: str, timeout: float = 0.0) -> Pass:
    """Run one pass under a FRESH bytecode-cache tree.

    A fresh prefix per pass, not one shared across the experiment: with a shared
    tree the baseline pass can leave a cache the mutant pass then reads, which is
    the stale-module half of the scar rebuilt inside the harness meant to prevent
    it. The prefix is returned only so the receipt can name it; it is gone by then.
    """
    cache_prefix = tempfile.mkdtemp(prefix=prefix)
    try:
        code = subprocess.run(
            cmd, env=child_env(cache_prefix), timeout=timeout or None
        ).returncode
        return Pass(code, None, cache_prefix, False)
    except subprocess.TimeoutExpired:
        return Pass(None, None, cache_prefix, True)
    except OSError as exc:
        return Pass(None, str(exc), cache_prefix, False)
    finally:
        shutil.rmtree(cache_prefix, ignore_errors=True)


def _dirty_tree(path: str, args) -> int:
    """One message for both restore points, because both mean the same thing."""
    return refuse(
        f"the subject is not back to its original bytes: restore of {path} could not "
        "be verified, so a mutant may still be on disk. Fix the working tree before "
        "trusting any further result.",
        args,
    )


def _restore(path: str, original: bytes, mode: int) -> bool:
    """Put the original bytes AND mode back, and PROVE it rather than assume it.

    Unconditional: a command that deletes, rewrites or chmods the subject still
    leaves a clean tree. Returns False when the tree is not clean, which the
    caller turns into a FAILED EXPERIMENT -- a dirty tree poisons every run after
    this one, including the mutant write that comes next after the baseline pass.

    The mode is part of "original". A baseline pass that strips write permission
    would otherwise make the mutant write fail, and the harness would report a
    fault it caused itself.
    """
    try:
        if os.path.exists(path):
            _chmod_writable(path, mode)
        with open(path, "wb") as fh:
            fh.write(original)
        os.chmod(path, mode)
        with open(path, "rb") as fh:
            return sha256(fh.read()) == sha256(original)
    except OSError:
        return False


def _chmod_writable(path: str, mode: int) -> None:
    """Best effort: an unwritable subject is recoverable, a missing one is not."""
    try:
        os.chmod(path, mode | stat.S_IWUSR)
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
