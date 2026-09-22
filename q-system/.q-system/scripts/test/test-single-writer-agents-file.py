#!/usr/bin/env python3
"""One writer per launchd agents file (ASK-1345, sp-173ead80, sp-3a513fce).

THE SCAR. Measured 2026-09-07, the night 6668550d widened install-plist.sh's
enumerator to reach `automation/com.kipi.voice-refresh.plist`:

    writers for com.kipi.voice-refresh ..... 2
      q-system/.q-system/scripts/install-plist.sh   (label-generic, sed renderer)
      automation/install-voice-refresh.sh           (this label only, python renderer)

Two renderers, two root resolutions, one destination file, so which bytes landed
in the agents file depended on which script ran last. That was survivable only
while the dedicated one was the sole path that could reach the template; the
enumerator repair removed that accident.

Rendering both against the same plain root produced byte-identical output, so
"they agree" is NOT why the duplication was safe, it is why it was invisible.
They disagree on the two inputs that matter:

  * a root containing `&`: the python writer XML-escapes it and produces a plist
    `plutil -lint` accepts; the sed writer emits a raw `&` and plutil rejects the
    file. Same input, different outcome.
  * a template carrying a SECOND placeholder: the python writer substitutes
    __ROOT__, writes the file with the other token still in it, loads it, exits 0.
    install-plist.sh's assert_rendered refuses. launchd accepts an unsubstituted
    plist and fails at fire time, silently, which is the class assert_rendered
    exists for.

WHAT THIS HOLDS (three properties, each able to go red on its own):
  P1 SINGLE WRITER   exactly one shipped, non-test code path writes the agents
                     file for a given label
  P2 IDEMPOTENT      installing that label twice by any shipped path produces
                     byte-identical output
  P3 REFUSES A HOLE  every shipped writer refuses a template that still carries a
                     placeholder after its own render

THE RED IS REPRODUCIBLE, and that is what KIPI_SINGLE_WRITER_REF is for. A
regression test written after its fix has never been seen to fail, so this one
takes its whole fixture from a git ref instead of the working tree when that
variable is set. Run it against the commit before the fix and P1 and P3 go red:

    KIPI_SINGLE_WRITER_REF=6668550d python3 \\
      q-system/.q-system/scripts/test/test-single-writer-agents-file.py

Run: python3 q-system/.q-system/scripts/test/test-single-writer-agents-file.py
Exit 0 = pass.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]

LABEL = "com.kipi.voice-refresh"
SOURCE_REF = os.environ.get("KIPI_SINGLE_WRITER_REF", "").strip()

# The destination every writer must contend for. Matching the DIRECTORY, not a
# rendered path: a writer that builds the path from parts still names this.
AGENTS_DIR_RE = re.compile(r"Library/LaunchAgents")
# A WRITER loads what it wrote. `launchctl list` (read-only status) must not
# qualify, or launchd-health-check.py and fleet-health-daily.py -- which enumerate
# that directory and never write it -- read as writers and the count is noise.
LOAD_RE = re.compile(r"launchctl[^\n]{0,40}?\b(load|bootstrap)\b")


def _git(args, cwd):
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True,
                          text=True, timeout=180)


def _is_test_path(rel: str) -> bool:
    name = os.path.basename(rel)
    return (name.startswith("test_") or name.startswith("test-")
            or "/test/" in rel or "/tests/" in rel)


def find_writers(tree: Path, label: str):
    """(non_test_writers, test_writers), sorted, relative to `tree`.

    A writer names the agents directory AND loads what it put there. It counts for
    `label` when it hardcodes that label or takes one as an argument: the
    label-generic installer writes this file too.
    """
    out = _git(["ls-files", "-z"], tree).stdout.split("\0")
    hits, test_hits = [], []
    for rel in out:
        if not rel:
            continue
        p = tree / rel
        if not p.is_file():
            continue
        try:
            body = p.read_text(errors="replace")
        except OSError:
            continue
        if not (AGENTS_DIR_RE.search(body) and LOAD_RE.search(body)):
            continue
        generic = "$LABEL" in body or "sys.argv" in body
        if not (label in body or generic):
            continue
        (test_hits if _is_test_path(rel) else hits).append(rel)
    return sorted(hits), sorted(test_hits)


def selftest_detector(tree: Path):
    """NEGATIVE SELF-TEST: the detector must not call a read-only enumerator a
    writer. launchd-health-check.py globs the agents directory and shells
    `launchctl list`; it writes nothing. If it lands in the writer set, the count
    above is measuring the wrong population and every other number here is noise.
    """
    reader = tree / "q-system/.q-system/scripts/launchd-health-check.py"
    body = reader.read_text(errors="replace")
    assert AGENTS_DIR_RE.search(body), (
        "fixture drift: the read-only enumerator no longer names the agents dir, "
        "so this self-test proves nothing")
    assert not LOAD_RE.search(body), (
        "detector is too loose: it classifies the read-only enumerator "
        "launchd-health-check.py as a writer")


def build_tree(work: Path) -> Path:
    """A real primary checkout at a path nothing hardcodes.

    `git init` + one commit, because install-plist.sh resolves its template set
    with `git ls-files`: a plain directory copy sends it down the
    not-a-git-checkout fallback and measures the wrong code path. A `.git`
    DIRECTORY and not a worktree file, because --all refuses from a worktree.

    Source is the working tree by default and a git ref when
    KIPI_SINGLE_WRITER_REF is set, so the pre-fix red can be re-run at any time.
    """
    dest = work / "an-arbitrary-checkout-path"
    dest.mkdir(parents=True)
    tar = work / "tree.tar"
    if SOURCE_REF:
        r = _git(["archive", "--format=tar", "-o", str(tar), SOURCE_REF], REPO)
        if r.returncode != 0:
            raise SystemExit("could not archive ref %s: %s" % (SOURCE_REF, r.stderr))
        print("fixture source: git ref %s" % SOURCE_REF)
    else:
        files = _git(["ls-files", "-z"], REPO).stdout.split("\0")
        listing = work / "tracked.txt"
        listing.write_text("\n".join(f for f in files if f))
        r = subprocess.run(["tar", "-cf", str(tar), "-T", str(listing)],
                           cwd=str(REPO), capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise SystemExit("could not stage the working tree: " + r.stderr)
        print("fixture source: working tree at %s" % REPO)
    subprocess.run(["tar", "-xf", str(tar)], cwd=str(dest), capture_output=True,
                   timeout=300)
    _git(["init", "-q"], dest)
    _git(["add", "-A"], dest)
    _git(["-c", "user.email=t@example.invalid", "-c", "user.name=single-writer test",
          "commit", "-q", "-m", "fixture"], dest)
    print("fixture tree:   %s" % dest)
    return dest


def seal_env(work: Path):
    """A stub launchctl, a sealed PATH, and a canary that proves the seal.

    Without the canary this is a live-path hazard, not a test: the writers call
    bare `launchctl load` on a plist whose Label is a REAL label, so an unsealed
    PATH rebinds the running job to a temp directory that is about to be deleted.
    The stub records its argv; if the canary leaves no record, the real binary was
    reachable and nothing below is allowed to run.
    """
    bindir = work / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    log = work / "launchctl-calls.log"
    stub = bindir / "launchctl"
    stub.write_text('#!/bin/bash\necho "$@" >> "%s"\nexit 0\n' % log)
    stub.chmod(0o755)

    home = work / "home"
    (home / "Library" / "LaunchAgents").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PATH"] = "%s:/usr/bin:/bin" % bindir
    env["KIPI_LAUNCHCTL"] = str(stub)

    subprocess.run(["launchctl", "canary"], env=env, capture_output=True, timeout=60)
    if not log.exists() or not log.read_text().strip():
        raise SystemExit("REFUSING TO RUN: the launchctl stub was not reached, so "
                         "the real binary is on PATH and these writers would touch "
                         "live jobs")
    log.write_text("")
    print("ok   launchctl stub sealed (canary recorded)")
    return env, home


def run_writer(rel: str, tree: Path, env, label: str):
    """Invoke one shipped writer the way its own usage line says to."""
    script = tree / rel
    args = ["bash", str(script)]
    if "install-plist.sh" in rel:
        args.append(label)
    return subprocess.run(args, cwd=str(tree), env=env, capture_output=True,
                          text=True, timeout=180)


def check_single_writer(writers, failures):
    if len(writers) != 1:
        failures.append("P1 SINGLE WRITER: expected exactly 1 shipped writer for %s, "
                        "found %d: %s" % (LABEL, len(writers), ", ".join(writers)))
    else:
        print("ok   P1 single writer")


def check_idempotent(writers, tree, env, dest, failures):
    produced = {}
    for rel in writers:
        for run_i in (1, 2):
            if dest.exists():
                dest.unlink()
            r = run_writer(rel, tree, env, LABEL)
            if not dest.exists():
                failures.append("P2: %s run %d wrote no agents file (rc=%d) %s"
                                % (rel, run_i, r.returncode, r.stderr.strip()[:200]))
                continue
            produced["%s#%d" % (rel, run_i)] = dest.read_bytes()
    uniq = {bytes(v) for v in produced.values()}
    if produced and len(uniq) != 1:
        failures.append("P2 IDEMPOTENT: %d shipped install runs produced %d distinct "
                        "agents files: %s" % (len(produced), len(uniq),
                                              ", ".join(sorted(produced))))
    elif produced:
        print("ok   P2 idempotent across %d install runs" % len(produced))


def hole_the_template(tree: Path):
    """Add a SECOND placeholder to the committed template, in the fixture only."""
    tmpl = tree / "automation" / (LABEL + ".plist")
    # __PROBE_TOKEN__ and not __HOME__. Measured 2026-09-07: the first cut used
    # __HOME__, which install-plist.sh SUBSTITUTES, so the "holed" template
    # rendered cleanly and the survivor was graded on a template with no hole in
    # it. The probe has to be a token no writer in the repo renders, and
    # assert_rendered matches the CLASS __[A-Z][A-Z0-9_]*__ rather than a list of
    # known names, which is exactly why an unknown token is the right probe.
    tmpl.write_text(tmpl.read_text().replace(
        "<key>Label</key>",
        "<key>ProbeToken</key><string>__PROBE_TOKEN__</string><key>Label</key>", 1))
    _git(["add", "-A"], tree)
    _git(["-c", "user.email=t@example.invalid", "-c", "user.name=single-writer test",
          "commit", "-q", "-m", "holed template"], tree)


def check_refuses_a_hole(writers, tree, env, dest, failures):
    hole_the_template(tree)
    for rel in writers:
        if dest.exists():
            dest.unlink()
        r = run_writer(rel, tree, env, LABEL)
        leftover = ""
        if dest.exists():
            leftover = " ".join(sorted(set(re.findall(
                r"__[A-Z][A-Z0-9_]*__", dest.read_text(errors="replace")))))
        # A REFUSAL IS NON-ZERO PLUS NO FILE, and both halves are asserted. The
        # first cut accepted `rc == 0 and no leftover`, which is also what a writer
        # that silently did nothing looks like: the control could not fail
        # distinctively. Measured 2026-09-07 while writing this, install-plist.sh
        # came back rc=0 on the holed template and the loose form called that a
        # pass.
        if leftover:
            failures.append("P3 REFUSES A HOLE: %s exited %d and installed a plist "
                            "still carrying %s" % (rel, r.returncode, leftover))
        elif r.returncode == 0:
            failures.append("P3 REFUSES A HOLE: %s exited 0 on a template carrying "
                            "__PROBE_TOKEN__. A refusal must be loud, and exit 0 is "
                            "not one. stdout=%r stderr=%r"
                            % (rel, r.stdout.strip()[-300:], r.stderr.strip()[-300:]))
        else:
            print("ok   P3 %s refused the holed template (rc=%d)" % (rel, r.returncode))


def main():
    failures = []
    work = Path(tempfile.mkdtemp(prefix="single-writer-"))
    try:
        tree = build_tree(work)
        selftest_detector(tree)
        print("ok   detector self-test: the read-only enumerator is not a writer")

        writers, test_writers = find_writers(tree, LABEL)
        print("writers for %s (non-test): %d" % (LABEL, len(writers)))
        for w in writers:
            print("    %s" % w)
        if test_writers:
            print("  (test files with the same shape, not counted: %s)"
                  % ", ".join(test_writers))

        check_single_writer(writers, failures)
        env, home = seal_env(work)
        dest = home / "Library" / "LaunchAgents" / (LABEL + ".plist")
        check_idempotent(writers, tree, env, dest, failures)
        check_refuses_a_hole(writers, tree, env, dest, failures)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    for f in failures:
        print("FAIL " + f, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
