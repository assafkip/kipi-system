#!/usr/bin/env python3
"""Run a PR's tests and write the green receipt the merge gate reads.

WHY THIS EXISTS (Codex major, PR #269 round 5). `merge-bypass-gate.py` gained a
receipt-based deferral on 2026-08-25: on a repo with no branch protection,
`gh pr merge --auto` is refused outright by GitHub and the required contexts are
never posted, so the gate deferred to "proof that someone actually ran the tests"
instead. Its refusal message told the operator to run `automation/pr_verify.py`.

That file did not exist. Anywhere. Nothing in the fleet wrote
`.prd-os/pr-receipts/` either, so the branch could never be satisfied: every
non---auto merge got "no green receipt", forever. The gate was not looser than it
looked, it was INERT in the one direction it had just been widened -- an escape
hatch naming a producer nobody had built. Same class as a rule marked ENFORCED
that names no executable, one layer over.

So: the producer. It is deliberately small, and it is the only writer of that
directory.

WHAT MAKES A RECEIPT TRUSTWORTHY

1. It names a SHA, and the gate re-reads the PR head and compares. A receipt
   written before the branch moved clears nothing.
2. It is written only when the checkout IS that sha. Running the tests on one
   tree and stamping another is the whole failure it exists to prevent.
3. A run that executed ZERO tests is a FAILURE, never a pass. That case is named
   in the gate's own message because it already happened here: two red PRs looked
   mergeable off a suite that collected nothing.

HONEST BOUNDARY. This runs `verify.sh --full` and records what it said. It does
not know whether the suite is good, whether it covers the diff, or whether a
green suite means the PR is correct. It proves a specific tree was run through
this repo's floor and the floor said ok. That is all a receipt has ever claimed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

RECEIPT_DIR = os.path.join(".prd-os", "pr-receipts")

# A pytest line verify.sh prints per suite: "  pytest:<suite>   ok" / "FAILED".
_PYTEST_LINE = re.compile(r"^\s*(pytest[^\s]*)\s+(ok|FAILED)", re.M)
# What pytest says when it collected nothing. Any of these means the suite did
# not run, which this refuses to call green.
_EMPTY_RUN = ("no tests ran", "collected 0 items")


def run(args, cwd=None, timeout=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)


def repo_root(start: str) -> str:
    r = run(["git", "-C", start, "rev-parse", "--show-toplevel"])
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit("not inside a git repository: %s" % start)
    return r.stdout.strip()


def pr_head(pr: str, cwd: str) -> str:
    r = run(["gh", "pr", "view", pr, "--json", "headRefOid", "-q", ".headRefOid"],
            cwd=cwd, timeout=30)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit("could not read PR #%s's head: %s"
                 % (pr, (r.stderr or r.stdout).strip()))
    return r.stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pr", help="PR number")
    ap.add_argument("--root", default=".")
    ap.add_argument("--allow-detached", action="store_true",
                    help="write the receipt when HEAD equals the PR head even "
                         "on a detached checkout (the review-tree case)")
    args = ap.parse_args()

    root = repo_root(args.root)
    head = run(["git", "-C", root, "rev-parse", "HEAD"]).stdout.strip()
    want = pr_head(args.pr, root)

    # RULE 2. No exception for "it is probably the same". The receipt's whole
    # value is that the sha it names is the sha that was run.
    if head != want:
        sys.exit("refusing: this checkout is at %s but PR #%s's head is %s.\n"
                 "  Check out the PR head first:  gh pr checkout %s"
                 % (head[:12], args.pr, want[:12], args.pr))

    verify = os.path.join(root, "q-system", ".q-system", "verify.sh")
    if not os.path.isfile(verify):
        sys.exit("no floor to run: %s is missing" % verify)

    started = time.time()
    r = run(["bash", verify, "--full"], cwd=root, timeout=3600)
    out = (r.stdout or "") + (r.stderr or "")
    elapsed = round(time.time() - started, 1)

    suites = _PYTEST_LINE.findall(out)
    empty = [m for m in _EMPTY_RUN if m in out]

    # RULE 3. Three separate ways to not be green, and each is named in the
    # receipt rather than collapsed into one boolean.
    if r.returncode != 0:
        result, why = "red", "verify.sh exited %d" % r.returncode
    elif not suites:
        result, why = "red", ("verify.sh ran no pytest suite at all; a floor "
                              "that runs nothing cannot certify anything")
    elif empty:
        result, why = "red", ("a suite collected zero tests (%s); a zero-test "
                              "run is a FAILURE here" % ", ".join(empty))
    else:
        result, why = "green", "verify.sh --full ok across %d suite(s)" % len(suites)

    receipt = {
        "pr": int(args.pr),
        "sha": head,
        "result": result,
        "why": why,
        "suites": ["%s:%s" % (name, verdict) for name, verdict in suites],
        "seconds": elapsed,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "producer": "q-system/.q-system/scripts/pr_verify.py",
    }

    dest_dir = os.path.join(root, RECEIPT_DIR)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "pr-%s.json" % args.pr)
    with open(dest, "w") as fh:
        json.dump(receipt, fh, indent=1, sort_keys=True)
        fh.write("\n")

    print("%s  %s" % (result.upper(), why))
    print("receipt: %s" % dest)
    for line in ("  " + s for s in receipt["suites"]):
        print(line)
    # A RED receipt is still WRITTEN, and still exits non-zero. Writing it is
    # what stops a later run from mistaking "never verified" for "verified and
    # fine"; exiting non-zero is what stops a caller chaining a merge onto it.
    return 0 if result == "green" else 1


if __name__ == "__main__":
    sys.exit(main())
