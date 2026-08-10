#!/usr/bin/env python3
"""Flag a test that is named for a script it never actually runs.

THE SHAPE, hit three times in one day (2026-08-10):

  1. `test-kipi-update-preserve-integration.sh` lifts the preservation sequence
     "verbatim from kipi-update.sh" into its own body. It proves the ALGORITHM
     and can never observe whether kipi-update.sh still calls it, or which bash
     interprets it. That is how the ASK-607 bash-3.2 abort shipped green.
  2. `test_durable.py` set the durability flag itself with monkeypatch, so it
     measured the guard's logic and was blind to whether the declaration reaches
     a real runner. Production broke 20 minutes after the guard shipped.
  3. The lane-H break itself: a docstring asserting a deployment nothing performed.

The common root is a test that SUPPLIES the thing it should be OBSERVING. That
is not decidable in general. This checks the one narrow, deterministic slice:
a test file named `test-<target>*.sh` where `<target>` is a real script in the
repo, and the test never invokes `<target>`.

WHAT IT DOES NOT CLAIM. Invoking the target is necessary, not sufficient -- a
test can run the real script and still assert nothing that could fail. This
catches the structural miss, not the weak assertion.

Three earlier versions of this check were wrong, and each was caught by running
it over the repo rather than by reasoning about it:

  v1 asked "does the test invoke ANY script it names". Zero flags, and it MISSED
     the known-bad case, which invokes the HELPER while re-implementing the
     ORCHESTRATOR.
  v2 derived the target from the filename but matched raw text, so
     "(lifted verbatim from kipi-update.sh)" IN A COMMENT read as an invocation.
     Comments have to be stripped -- a text check that ignores them breaks both
     ways.
  v3 stripped comments and produced one true positive plus one FALSE positive:
     test-kipi-update-preserve-scan.sh assigns the path to $HELPER on line 7 and
     runs `python3 "$HELPER"`. Hence the variable resolution below.

Exit 0 = clean, 1 = findings. Advisory by design: run it, read it, decide.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

INTERPRETERS = r'(?:bash|sh|zsh|python3|python|source|\.)'


def strip_comments(text):
    """Comments must not count as invocations, and must not hide one either."""
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        # Leave $# and ${#...} alone; drop a trailing comment otherwise.
        out.append(re.sub(r'(?<!\$)#(?![{(]).*$', '', line))
    return "\n".join(out)


def invokes(code, target_file):
    """Does this code actually RUN target_file, directly or through a variable?"""
    esc = re.escape(target_file)
    # Direct: `bash /path/to/target.sh`, `python3 "$D/target.py"`
    if re.search(INTERPRETERS + r'\s+"?[^\n|;&"]*' + esc, code):
        return True
    # Executed directly: `./target.sh`, `"$SKEL/target.sh" --flag`
    if re.search(r'(?:\./|\$\{?\w+\}?/)[^\n"]*' + esc, code):
        return True
    # Through a variable: VAR=...target...  then  `python3 "$VAR"`.
    for var in re.findall(r'(\w+)=[^\n]*' + esc, code):
        if re.search(INTERPRETERS + r'\s+"?\$\{?' + re.escape(var) + r'\}?', code):
            return True
    return False


def audit(root):
    scripts = [p for p in os.listdir(root)
               if (p.endswith(".sh") or p.endswith(".py"))
               and not p.startswith("test-")]
    stems = sorted({os.path.splitext(s)[0] for s in scripts}, key=len, reverse=True)
    findings, checked = [], 0
    for path in sorted(glob.glob(os.path.join(root, "test-*.sh"))):
        name = os.path.splitext(os.path.basename(path))[0][len("test-"):]
        target = next((s for s in stems if name.startswith(s)), None)
        if not target:
            # The filename names no script in this repo, so there is no target to
            # compare against and nothing for this check to say. Not a deferral.
            continue
        target_file = target + ".sh"
        if not os.path.exists(os.path.join(root, target_file)):
            target_file = target + ".py"
        checked += 1
        with open(path, encoding="utf-8", errors="replace") as fh:
            code = strip_comments(fh.read())
        if not invokes(code, target_file):
            findings.append((os.path.basename(path), target_file))
    return findings, checked


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    findings, checked = audit(args.root)
    if not args.quiet:
        print(f"reimplementing-test-lint: {checked} test file(s) named for a script")
    for test, target in findings:
        print(f"  {test}: never invokes {target} -- it may be re-implementing it. "
              f"A test that supplies its own copy of the code proves the algorithm "
              f"and can never see the wiring or the interpreter.")
    if not findings and not args.quiet:
        print("  clean")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
