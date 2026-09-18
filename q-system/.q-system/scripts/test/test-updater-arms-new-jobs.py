#!/usr/bin/env python3
"""Pairs with kipi-update.sh `arm_new_jobs` -> `install-plist.sh --missing` (ASK-1130).

THE GAP. `kipi install-jobs` installs every committed launchd template, and nothing
called it: the fleet updater did not, so a merged com.kipi.*.plist ran nowhere
until somebody knew to type the command. ASK-729 closed that gap at the installer
and left it open one level up.

What this pins, each against a scratch primary checkout with a scratch HOME and a
recording launchctl stub (a real launchctl here would bootstrap live jobs):

  1. The updater, run from the registry's skeleton, installs a committed template
     that has no job yet.
  2. It never touches a job that is already installed: the plist bytes are
     identical afterwards, and launchctl never hears its label (no bootout, so a
     running job is not killed and a live incident value is not overwritten).
  3. A paused label is not armed.
  4. From a git worktree, `--missing` REFUSES (exit 2) and the updater arms
     nothing: no plist is written and launchctl is never called.
  5. A scratch tree whose registry does not name it the skeleton arms nothing,
     which is what keeps ~15 other updater tests from arming real jobs.

NEGATIVE SELF-TEST. `python3 <this> --source-ref origin/main` builds the
fixture from the pre-change scripts; case 1 goes RED there, which is the proof
the check can fail.

Run: python3 q-system/.q-system/scripts/test/test-updater-arms-new-jobs.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SOURCE_REF = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--source-ref" else ""
FILES = (
    "kipi-update.sh",
    "q-system/.q-system/scripts/install-plist.sh",
    "q-system/.q-system/scripts/launchd-health-check.py",
)
TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{label}</string>
<key>ProgramArguments</key><array><string>__KIPI_REPO__/run.sh</string></array>
</dict></plist>
"""
# What an installed job looks like when it points at the primary checkout. The
# test proves these bytes survive the update unchanged.
LIVE_OLD = TEMPLATE.replace("__KIPI_REPO__", "/the/primary/checkout").format(label="com.kipi.old")

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  (got {got!r}, want {want!r})"))
    if not ok:
        FAILS.append(name)


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=120)


def stage_tree(sk):
    """The whole tracked tree, not a hand-picked file list.

    The first version copied three files and the updater aborted before its loop
    on a missing fail-closed gate, so the RED it produced was about the fixture,
    not the gap. The updater's own preconditions decide what it needs; the test
    does not get to restate them.
    """
    sk.mkdir(parents=True)
    if SOURCE_REF:
        arch = subprocess.run(["git", "archive", SOURCE_REF], cwd=str(REPO), capture_output=True, timeout=300)
        subprocess.run(["tar", "-x", "-C", str(sk)], input=arch.stdout, capture_output=True, timeout=300)
        return
    files = [f for f in git(["ls-files", "-z"], REPO).stdout.split("\0") if f and (REPO / f).exists()]
    listing = sk.parent / "tracked.txt"
    listing.write_text("\n".join(files))
    tarball = sk.parent / "tree.tar"
    subprocess.run(["tar", "-cf", str(tarball), "-T", str(listing)], cwd=str(REPO), capture_output=True, timeout=300)
    subprocess.run(["tar", "-xf", str(tarball)], cwd=str(sk), capture_output=True, timeout=300)


def build_skeleton(work, name_it_skeleton):
    sk = work / "skeleton"
    stage_tree(sk)
    for rel in FILES:
        if not (sk / rel).is_file():
            raise SystemExit(f"fixture is missing {rel}")
    scripts = sk / "q-system/.q-system/scripts"
    for label in ("com.kipi.old", "com.kipi.new", "com.kipi.paused"):
        (scripts / f"{label}.plist").write_text(TEMPLATE.format(label=label))
    registry = '{"instances": []}'
    if name_it_skeleton:
        registry = '{"skeleton": {"path": "%s"}, "instances": []}' % sk.resolve()
    (sk / "instance-registry.json").write_text(registry)
    git(["init", "-q"], sk)
    git(["add", "-A"], sk)
    git(["-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-m", "fixture"], sk)
    return sk


def scratch_home(work):
    home = work / "home"
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "com.kipi.old.plist").write_text(LIVE_OLD)
    (home / ".config" / "kipi").mkdir(parents=True)
    (home / ".config" / "kipi" / "launchd-paused.txt").write_text("com.kipi.paused  # paused on purpose\n")
    return home, agents


def env_for(work, home):
    log = work / "launchctl.log"
    stub = work / "launchctl-stub"
    stub.write_text(f'#!/bin/bash\necho "$*" >> "{log}"\nexit 0\n')
    stub.chmod(0o755)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["KIPI_LAUNCHCTL"] = str(stub)
    return env, log


def run_updater(checkout, env):
    return subprocess.run(["bash", str(checkout / "kipi-update.sh")], cwd=str(checkout),
                          capture_output=True, text=True, timeout=300, env=env)


def calls(log):
    return log.read_text() if log.exists() else ""


def case_updater_arms_only_the_missing_job():
    print("case 1-3: updater from the registry skeleton")
    work = Path(tempfile.mkdtemp(prefix="arm-new-jobs-"))
    sk = build_skeleton(work, name_it_skeleton=True)
    home, agents = scratch_home(work)
    env, log = env_for(work, home)
    proc = run_updater(sk, env)
    if proc.returncode != 0:
        print(proc.stdout[-2000:], proc.stderr[-2000:], sep="\n")
    check("updater exits 0", proc.returncode, 0)
    new = agents / "com.kipi.new.plist"
    check("newly committed job is installed", new.is_file(), True)
    # Either spelling of the scratch path: on macOS /var is a symlink to
    # /private/var, and the installer renders the path it was invoked through.
    rendered = new.read_text() if new.is_file() else ""
    check("installed job points at the skeleton",
          f"{sk}/run.sh" in rendered or f"{sk.resolve()}/run.sh" in rendered, True)
    check("already-installed job's plist is byte-identical", (agents / "com.kipi.old.plist").read_text(), LIVE_OLD)
    check("launchctl never hears the installed label", "com.kipi.old" in calls(log), False)
    check("paused job is not armed", (agents / "com.kipi.paused.plist").exists(), False)
    check("per-job report names the new job", "installed com.kipi.new" in proc.stdout, True)
    return sk, work


def case_worktree_refuses(sk, work):
    print("case 4: from a git worktree")
    wt = work / "a-worktree"
    git(["worktree", "add", "-q", "--detach", str(wt)], sk)
    home = work / "home-wt"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    (home / "Library" / "LaunchAgents" / "com.kipi.old.plist").write_text(LIVE_OLD)
    env, log = env_for(work / "a-worktree", home)
    direct = subprocess.run(["bash", str(wt / "q-system/.q-system/scripts/install-plist.sh"), "--missing"],
                            capture_output=True, text=True, timeout=120, env=env)
    # The message, not only the code: an installer that does not know --missing
    # also exits 2 ("no committed plist template for label"), which is a pass for
    # the wrong reason.
    check("install-plist.sh --missing refuses with exit 2", direct.returncode, 2)
    check("the refusal is the worktree refusal", "REFUSED: --missing only runs from the primary checkout" in direct.stderr, True)
    run_updater(wt, env)
    listing = sorted(p.name for p in (home / "Library" / "LaunchAgents").iterdir())
    check("no plist written from the worktree", listing, ["com.kipi.old.plist"])
    check("installed job untouched from the worktree",
          (home / "Library" / "LaunchAgents" / "com.kipi.old.plist").read_text(), LIVE_OLD)
    check("launchctl never called from the worktree", calls(log), "")


def case_unnamed_scratch_tree_arms_nothing():
    print("case 5: scratch tree the registry does not name")
    work = Path(tempfile.mkdtemp(prefix="arm-new-jobs-unnamed-"))
    sk = build_skeleton(work, name_it_skeleton=False)
    home, agents = scratch_home(work)
    env, log = env_for(work, home)
    run_updater(sk, env)
    check("no job armed from an unnamed tree", (agents / "com.kipi.new.plist").exists(), False)
    check("launchctl never called from an unnamed tree", calls(log), "")


# Each guard, broken in the FIXTURE COPY (never the repo file), must turn the
# suite red. A guard no mutant can reach is decoration.
MUTANTS = (
    ("installed-skip removed", "q-system/.q-system/scripts/install-plist.sh",
     'if [ -e "$HOME/Library/LaunchAgents/$_label.plist" ]; then', "if false; then"),
    ("paused-skip removed", "q-system/.q-system/scripts/install-plist.sh",
     'grep -qxF "$_label"', 'grep -qxF "no-such-label"'),
    ("updater never arms", "kipi-update.sh", "\narm_new_jobs\n", "\ntrue\n"),
    ("skeleton check dropped", "kipi-update.sh",
     'if [ -z "$skeleton" ] || [ "$here" != "$skeleton" ]; then', "if false; then"),
)


def run_mutants():
    global build_skeleton
    real_build = build_skeleton
    survivors = []
    for name, rel, old, new in MUTANTS:
        def mutated(work, name_it_skeleton, rel=rel, old=old, new=new):
            sk = real_build(work, name_it_skeleton)
            text = (sk / rel).read_text()
            if old not in text:
                raise SystemExit(f"mutant anchor not found in {rel}: {old!r}")
            (sk / rel).write_text(text.replace(old, new, 1))
            return sk
        build_skeleton = mutated
        FAILS.clear()
        print(f"== mutant: {name}")
        sk, work = case_updater_arms_only_the_missing_job()
        case_worktree_refuses(sk, work)
        case_unnamed_scratch_tree_arms_nothing()
        killed = bool(FAILS)
        print(f"== mutant {name}: {'KILLED' if killed else 'SURVIVED'}")
        if not killed:
            survivors.append(name)
    build_skeleton = real_build
    print(f"mutants: {len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed")
    return 1 if survivors else 0


def main():
    if "--mutants" in sys.argv:
        return run_mutants()
    print(f"test-updater-arms-new-jobs.py (source: {SOURCE_REF or 'working tree'})")
    sk, work = case_updater_arms_only_the_missing_job()
    case_worktree_refuses(sk, work)
    case_unnamed_scratch_tree_arms_nothing()
    if FAILS:
        print(f"test-updater-arms-new-jobs.py: FAIL ({len(FAILS)})")
        return 1
    print("test-updater-arms-new-jobs.py: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
