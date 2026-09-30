#!/usr/bin/env python3
"""Pairs with `kipi install-jobs` -> install-plist.sh --all (sp-0c48b66c, sp-d621b67d).

THE SCAR THIS PINS. `kipi:22` advertises the verb as "Install every committed
launchd job on this machine". Measured 2026-09-07 from a checkout of main at an
arbitrary path, with a stub launchctl and a throwaway HOME:

    committed com.kipi.*.plist ......... 15   (git ls-files)
    installed by `--all` ............... 12
    announced as skipped ............... 2    (skeleton-only, by design)
    NEVER MENTIONED AT ALL ............. 1    (automation/com.kipi.voice-refresh.plist)
    exit code .......................... 0

`install-plist.sh` enumerated `"$SCRIPT_DIR"/com.kipi.*.plist`: ONE directory. A
committed template outside `q-system/.q-system/scripts/` was unreachable, and the
run said nothing and exited 0. A partial install that reports success is worse
than a failed one, because nothing downstream ever looks again: `detect_dark_jobs`
in fleet-health-daily.py enumerates `~/Library/LaunchAgents/*.plist`, so a job that
was never installed once is invisible to the watchdog too.

WHAT THIS TEST HOLDS (three properties, each able to go red on its own):
  1. COVERAGE   every committed label is either installed or announced as skipped
  2. RESOLVABLE every installed job's program path exists, with no live token left
  3. LOUD       a committed template that cannot be installed makes the run exit
                non-zero and names the label

The fixture is a real checkout built from the WORKING TREE at an arbitrary temp
path, not from HEAD: a reproducer that reads HEAD cannot see the fix you are
writing. The first cut of this measurement cloned the source repo's HEAD, landed
on a stale branch carrying 10 of the 15 plists, and described the fixture instead
of the installer. Hence _build_checkout below prints the tree it actually made.

Run: python3 q-system/.q-system/scripts/test/test-install-jobs-coverage.py
Exit 0 = pass.
"""

import importlib.util
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]

# The committed templates carry `--` inside their XML comments (prose blocks
# citing PR rounds). CoreFoundation accepts that, so launchd loads them, but
# expat rejects the document outright. Borrow fleet-health-daily.py's own comment
# stripper rather than writing a second one: a fixture parser that drifts from
# the detector's parser measures a document neither of them sees.
_fh_spec = importlib.util.spec_from_file_location(
    "fh_for_coverage", HERE.parent / "fleet-health-daily.py")
_fh = importlib.util.module_from_spec(_fh_spec)
_fh_spec.loader.exec_module(_fh)


def _parse_plist(path: Path):
    return plistlib.loads(_fh._XML_COMMENT_RE.sub("", path.read_text()).encode())

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  FAIL: {name}: got {got!r}, want {want!r}")
    else:
        print(f"  ok: {name}")


def _git(args, cwd, **kw):
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True,
                          text=True, timeout=180, **kw)


def committed_labels(tree: Path):
    """The set the verb promises, derived with git ls-files, never a glob."""
    out = _git(["ls-files", "*.plist"], tree).stdout.split()
    return sorted(Path(p).stem for p in out if Path(p).name.startswith("com.kipi."))


def _build_checkout(work: Path) -> Path:
    """A real primary checkout of the WORKING TREE, at a path nothing hardcodes.

    tar over `git ls-files` and not `git clone`: clone copies HEAD, and the whole
    point is to run the installer as it exists in the tree being reviewed. `git
    init` + one commit makes `.git` a DIRECTORY, which is what install-plist.sh
    requires before it will run --all (it refuses from a worktree on purpose).
    """
    dest = work / "an-arbitrary-checkout-path"
    dest.mkdir(parents=True)
    files = _git(["ls-files", "-z"], REPO).stdout.split("\0")
    listing = work / "tracked.txt"
    listing.write_text("\n".join(f for f in files if f))
    tar_c = subprocess.run(
        ["tar", "-cf", str(work / "tree.tar"), "-T", str(listing)],
        cwd=str(REPO), capture_output=True, text=True, timeout=300)
    if tar_c.returncode != 0:
        print(tar_c.stderr, file=sys.stderr)
        raise SystemExit("could not stage the working tree")
    subprocess.run(["tar", "-xf", str(work / "tree.tar")], cwd=str(dest),
                   capture_output=True, timeout=300)
    _git(["init", "-q"], dest)
    _git(["add", "-A"], dest)
    _git(["-c", "user.email=test@example.invalid", "-c", "user.name=coverage test",
          "commit", "-q", "-m", "fixture"], dest)
    return dest


def _stub_launchctl(work: Path) -> Path:
    """launchctl must never be the real one: this test would bootstrap live jobs."""
    stub = work / "bin" / "launchctl-stub"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text("#!/bin/bash\nexit 0\n")
    stub.chmod(0o755)
    return stub


def run_all(checkout: Path, work: Path, tag: str):
    home = work / f"home-{tag}"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["KIPI_LAUNCHCTL"] = str(_stub_launchctl(work))
    proc = subprocess.run(
        ["bash", str(checkout / "q-system/.q-system/scripts/install-plist.sh"), "--all"],
        capture_output=True, text=True, timeout=600, env=env)
    return proc, home / "Library" / "LaunchAgents"


_INSTALLED = re.compile(r"^installed (com\.kipi\.[a-z0-9.-]+)", re.M)
_SKIPPED = re.compile(r"^\s*skipped \([^)]+\): (com\.kipi\.[a-z0-9.-]+)", re.M)


def main():
    work = Path(tempfile.mkdtemp(prefix="install-jobs-coverage-"))
    try:
        checkout = _build_checkout(work)
        print(f"fixture checkout: {checkout}")
        print(f"  .git is a directory: {(checkout / '.git').is_dir()}")

        promised = committed_labels(checkout)
        print(f"  committed com.kipi labels in the fixture: {len(promised)}")
        check("the fixture carries the same committed set as the repo",
              promised, committed_labels(REPO))

        proc, agents = run_all(checkout, work, "main")
        out = proc.stdout + proc.stderr
        print("---- installer output ----")
        print(out.rstrip())
        print("--------------------------")

        installed = set(_INSTALLED.findall(out))
        skipped = set(_SKIPPED.findall(out))

        # === 1. COVERAGE ===================================================
        unaccounted = sorted(set(promised) - installed - skipped)
        check("every committed label is installed or announced as skipped",
              unaccounted, [])

        check("every non-skipped committed label has a file in LaunchAgents",
              sorted(l for l in promised
                     if l not in skipped and not (agents / f"{l}.plist").exists()),
              [])

        # === 2. RESOLVABLE =================================================
        # A rendered plist that still carries __TOKEN__ is a job launchd accepts
        # and fails at fire time, silently. A program path that does not exist is
        # the same failure one step later.
        left_tokens, dead_paths = [], []
        for f in sorted(agents.glob("com.kipi.*.plist")):
            text = f.read_text()
            if re.search(r"__[A-Z_]+__", text):
                left_tokens.append(f.stem)
            args = _parse_plist(f).get("ProgramArguments", [])
            for a in args[1:]:
                if a.startswith("/") and not Path(a).exists():
                    dead_paths.append(f"{f.stem}: {a}")
                    break
        check("no installed job carries an unsubstituted placeholder", left_tokens, [])
        check("every installed job's program path resolves", dead_paths, [])

        # === 3. LOUD =======================================================
        check("a fully-covered run reports a summary line",
              bool(re.search(r"install-jobs: \d+ installed", out)), True)
        check("a fully-covered run exits 0", proc.returncode, 0)

        # === THE NEGATIVE SELF-TEST ========================================
        # A control that fails the way an unrelated breakage fails proves nothing.
        # This one commits ONE template whose token no substituter knows, and the
        # assertion is not merely "non-zero": it is that this label is named in the
        # output and that the exit code is the installer's own partial-install code.
        control_label = "com.kipi.zz-unrenderable-control"
        ctrl = checkout / "automation" / f"{control_label}.plist"
        ctrl.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            f'  <key>Label</key><string>{control_label}</string>\n'
            '  <key>ProgramArguments</key><array><string>/bin/bash</string>'
            '<string>__NO_SUBSTITUTER_KNOWS_THIS__/x.sh</string></array>\n'
            '</dict></plist>\n')
        _git(["add", "-A"], checkout)
        _git(["-c", "user.email=test@example.invalid", "-c", "user.name=coverage test",
              "commit", "-q", "-m", "negative control"], checkout)

        proc2, agents2 = run_all(checkout, work, "control")
        out2 = proc2.stdout + proc2.stderr
        check("the control template is REACHED by the enumerator (it is named)",
              control_label in out2, True)
        check("the control makes the run exit non-zero", proc2.returncode != 0, True)
        check("the control is reported as a failure, not as installed",
              control_label in set(_INSTALLED.findall(out2)), False)
        check("the control's broken render never reaches LaunchAgents",
              (agents2 / f"{control_label}.plist").exists(), False)
        check("the healthy labels still installed alongside the failing one",
              sorted(set(promised) - set(_INSTALLED.findall(out2)) - set(_SKIPPED.findall(out2))),
              [])
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nall install-jobs coverage checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
