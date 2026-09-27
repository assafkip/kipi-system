#!/usr/bin/env python3
"""mutate.py -- the shared mutation harness for this fleet.

A mutation result is TWO claims and only one of them usually gets checked:

    1. the mutant was KILLED (the check under test went red)
    2. the mutant was APPLIED (the bytes the check ran against actually moved)

Claim 1 is meaningless until claim 2 is proven, because an unapplied mutant and
a well-defended one are identical bytes on the terminal. This script proves
claim 2 before it will report claim 1, and refuses with FAILED-TO-APPLY when it
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

Usage:

    python3 plugins/prd-os/scripts/mutate.py \
        --file path/to/subject.py \
        --anchor 'exact text, matching exactly once' \
        --replacement 'what it becomes' \
        -- pytest -q path/to/test_subject.py

Exit codes (the caller's contract; a CI job wants 0):

    0  KILLED            the mutant applied AND the command went red
    1  SURVIVED          the mutant applied AND the command stayed green
    2  FAILED EXPERIMENT nothing was measured -- never read this as a result

The subject file is always restored, and the restore is verified by digest
rather than assumed.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

FAILED_EXPERIMENT = 2


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fail_to_apply(reason: str) -> int:
    """Refuse loudly. An anchor miss must never fall through to the run.

    Printed to stderr AND stdout-tagged so a caller grepping either stream sees
    it: the scar was a human reading a terminal and taking a green at face value.
    """
    print(f"FAILED-TO-APPLY: {reason}", file=sys.stderr)
    print("verdict: FAILED-TO-APPLY (nothing was measured)")
    return FAILED_EXPERIMENT


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
    p.add_argument("cmd", nargs="+", help="the command to run against the mutated file")
    args = p.parse_args(argv)

    path = args.file

    # --- claim 2, step 1: the subject exists and the anchor is unambiguous ----
    try:
        with open(path, "rb") as fh:
            original = fh.read()
    except OSError as exc:
        return fail_to_apply(f"cannot read subject {path}: {exc}")

    anchor = args.anchor.encode()
    replacement = args.replacement.encode()

    if anchor == replacement:
        return fail_to_apply(
            "anchor and replacement are identical; this experiment mutates nothing "
            "and would report a green that means nothing"
        )

    matches = original.count(anchor)
    if matches != 1:
        # Exactly-once, not at-least-once. Zero is the anchor-drift scar. Two or
        # more means the mutated site is unknown, so no verdict can be attributed
        # to the check that produced it.
        return fail_to_apply(
            f"anchor matched {matches} times in {path}, expected exactly 1. "
            "Re-read the file and re-anchor; do not loosen the anchor."
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

    try:
        with open(path, "wb") as fh:
            fh.write(mutated)
    except OSError as exc:
        return fail_to_apply(f"cannot write mutant to {path}: {exc}")

    with open(path, "rb") as fh:
        on_disk = sha256(fh.read())
    if on_disk != digest_after:
        _restore(path, original)
        return fail_to_apply(
            f"read-back of {path} does not match the intended mutant "
            f"({on_disk[:12]} != {digest_after[:12]})"
        )

    # --- claim 1: run the check, then restore no matter what -----------------
    cache_prefix = tempfile.mkdtemp(prefix="mutate-pycache-")
    try:
        proc = subprocess.run(args.cmd, env=child_env(cache_prefix))
        run_exit = proc.returncode
    except OSError as exc:
        _restore(path, original)
        shutil.rmtree(cache_prefix, ignore_errors=True)
        return fail_to_apply(f"cannot run the command: {exc}")
    finally:
        restored = _restore(path, original)
        shutil.rmtree(cache_prefix, ignore_errors=True)

    if not restored:
        return fail_to_apply(
            f"the mutant is still on disk: restore of {path} could not be verified. "
            "Fix the working tree before trusting any further result."
        )

    verdict = "KILLED" if run_exit != 0 else "SURVIVED"
    receipt = {
        "label": args.label,
        "file": path,
        "applied": True,
        "anchor_matches": matches,
        "digest_before": digest_before,
        "digest_after": digest_after,
        "bytes_before": len(original),
        "bytes_after": len(mutated),
        "env_pins": {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": cache_prefix},
        "run_exit": run_exit,
        "verdict": verdict,
        "restored": True,
    }

    if args.as_json:
        print(json.dumps(receipt))
    else:
        print(f"applied: yes (anchor matched {matches}x, "
              f"{digest_before[:12]} -> {digest_after[:12]}, "
              f"{len(original)} -> {len(mutated)} bytes)")
        print(f"run exit: {run_exit}  (bytecode cache: write off, read from {cache_prefix})")
        print(f"restored: yes\nverdict: {verdict}")

    return 0 if verdict == "KILLED" else 1


def _restore(path: str, original: bytes) -> bool:
    """Put the original bytes back and PROVE it, rather than assume the write took.

    Unconditional: a command that deletes or rewrites the subject still leaves a
    clean tree. Returns False when the tree is not clean, which the caller turns
    into a FAILED EXPERIMENT -- a dirty tree poisons every run after this one.
    """
    try:
        with open(path, "wb") as fh:
            fh.write(original)
        with open(path, "rb") as fh:
            return sha256(fh.read()) == sha256(original)
    except OSError:
        return False


if __name__ == "__main__":
    sys.exit(main())
