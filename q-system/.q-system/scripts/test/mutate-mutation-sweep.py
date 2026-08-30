#!/usr/bin/env python3
"""Mutate mutation-sweep.py itself, and require its --self-test to notice.

WHY (PR #272 codex major). test-mutation-sweep.sh ran `--self-test` and matched
its output text, and stayed GREEN with SH_RULES, PY_RULES, the syntax guard or
the dirty-tree refusal deleted. A harness that cannot fail when its own
load-bearing parts are removed is precisely the shape it was built to detect --
"two of those 17 were MUTATION HARNESSES that lied" is the sweep's own opening
line, and the third was its test.

Each mutant below removes ONE component from a COPY on disk. The original is
never touched. A mutant whose --self-test still passes is reported as SURVIVED
and this exits 1, because that component is unmeasured by the self-test.

Every mutation is asserted to actually CHANGE the file. A no-op edit that
"survives" would be a second lie on top of the first, and this script would be
reporting coverage it does not have -- so a mutation that matches nothing is a
hard error, not a survivor.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP = os.path.join(os.path.dirname(HERE), "mutation-sweep.py")


def empty_list(name):
    """Replace `NAME = [ ... ]` with `NAME = []`."""
    def apply(text):
        pattern = re.compile(r"^%s = \[\n.*?^\]" % re.escape(name), re.S | re.M)
        return pattern.subn("%s = []" % name, text, count=1)
    return apply


def drop_line_containing(needle, replacement=""):
    def apply(text):
        out, n = [], 0
        for line in text.splitlines(keepends=True):
            if needle in line and not line.lstrip().startswith("#") and n == 0:
                indent = line[:len(line) - len(line.lstrip())]
                out.append(indent + replacement + "\n" if replacement else "")
                n += 1
            else:
                out.append(line)
        return "".join(out), n
    return apply


MUTANTS = {
    "SH_RULES emptied": empty_list("SH_RULES"),
    "PY_RULES emptied": empty_list("PY_RULES"),
    "VERDICT_RULES emptied": empty_list("VERDICT_RULES"),
    "syntax guard removed": drop_line_containing("ast.parse(text)", "pass"),
    "dirty-tree refusal removed": drop_line_containing(
        "if dirty and not read_only and not args.force_dirty:", "if False:"),
}


def run_self_test(path):
    """Run `--self-test` and return (rc, output).

    A CRASH IS NOT A KILL, and separating the two is the whole point of this
    file. The first cut wrote each mutant into a tmpdir and ran it there; the
    sweep resolves its fixtures relative to its own location, so every mutant
    died with FileNotFoundError and this script reported "all 5 mutants killed".
    Five false kills, in a harness written to catch false kills. Mutants now run
    from the sweep's OWN directory so their paths resolve, and a traceback is
    reported as ERROR rather than counted as detection.
    """
    try:
        proc = subprocess.run([sys.executable, path, "--self-test"],
                              capture_output=True, text=True, timeout=300)
    except subprocess.SubprocessError as exc:
        return 1, str(exc)
    out = proc.stdout + proc.stderr
    if "Traceback (most recent call last)" in out:
        return "CRASH", out
    return proc.returncode, out


def main():
    original = open(SWEEP).read()
    rc, out = run_self_test(SWEEP)
    if rc != 0:
        print("REFUSED: the unmutated self-test does not pass, so no mutant "
              "result would mean anything.\n" + out, file=sys.stderr)
        return 2
    print("baseline: --self-test passes")

    survived, crashed = [], []
    # Beside the original, so the mutant resolves the same fixture paths.
    path = os.path.join(os.path.dirname(SWEEP), ".mutation-sweep.mutant.py")
    try:
        for label, apply in sorted(MUTANTS.items()):
            mutated, n = apply(original)
            if n == 0:
                print("  ERROR %-30s mutation matched nothing; its anchor moved"
                      % label, file=sys.stderr)
                return 2
            with open(path, "w") as fh:
                fh.write(mutated)
            rc, out = run_self_test(path)
            if rc == "CRASH":
                verdict = "ERROR (crashed, not detected)"
                crashed.append((label, out.strip().splitlines()[-1:]))
            elif rc != 0:
                verdict = "KILLED"
            else:
                verdict = "SURVIVED"
                survived.append(label)
            print("  %-30s %s" % (label, verdict))
    finally:
        if os.path.exists(path):
            os.remove(path)

    if crashed:
        print("\nERROR -- these mutants crashed, which is not a detection:")
        for label, tail in crashed:
            print("  %-30s %s" % (label, " ".join(tail)))
        return 2

    if survived:
        print("\nSURVIVED -- the self-test cannot see these components:")
        for label in survived:
            print("  " + label)
        print("\nA harness that stays green with a load-bearing part deleted is "
              "the exact shape mutation-sweep.py exists to find.")
        return 1
    print("\nall %d mutant(s) killed" % len(MUTANTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
