#!/usr/bin/env python3
"""Regression tests for launchd-deploy-gap.py (ASK-1135).

The first version of ASK-1135 reported "cole-gtm 405 behind main". cole-gtm's
default is `master`; `git rev-list HEAD..origin/main` answered with a NUMBER about
a stale divergent `main` instead of an error. Test 1 builds exactly that repo --
default `master`, a stale `main` five commits off -- and pins the checker to the
branch `origin/HEAD` names. Test 7 re-runs the same assertions against a copy of
the checker mutated to assume `origin/main`, and requires them to go RED, so the
guard is proven to be the thing holding the line.

Every fixture lives in a tempdir: bare origins, clones, plists and `launchctl
list` output passed in as strings. Nothing here reads ~/Library/LaunchAgents or
calls launchctl. The ASK-1132 case (test 5) uses real commits from THIS repo's
history, through a `--shared --no-checkout` temp clone, so the real checkout is
only read.

Run: python3 test_launchd_deploy_gap.py   (exit 0 = pass, 1 = fail)
"""
import importlib.util
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

# ASK-1132: the DoR drafter's `--tools ""` fix landed on main as 896b0e5a, while
# com.kipi.linear-dor ran `cd <repo> && ./kipi dor --apply` from a checkout on a
# feature branch that did not have it.
ASK_1132_FIX = "896b0e5a"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dg = _load(os.environ.get("DEPLOY_GAP_UNDER_TEST", HERE / "launchd-deploy-gap.py"), "dg")

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")


def git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
         "-c", "init.defaultBranch=master", *args],
        cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def commit(cwd, name):
    Path(cwd, name).write_text(name)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "--no-verify", "-m", name)


def write_plist(folder, label, program, comment=""):
    body = plistlib.dumps({"Label": label, **program})
    if comment:
        # Apple's parser tolerates `--` inside an XML comment; expat does not.
        # com.kipi.dispatch and com.kipi.linear-triage-health ship exactly this.
        body = body.replace(b"<dict>", b"<dict>\n<!-- " + comment.encode() + b" -->", 1)
    (folder / f"{label}.plist").write_bytes(body)


def launchctl_list(*labels):
    rows = ["PID\tStatus\tLabel", "-\t0\tcom.apple.something"]
    rows += [f"-\t0\t{label}" for label in labels]
    return "\n".join(rows) + "\n"


# Resolved: macOS tempdirs live behind the /var -> /private/var symlink, and git
# reports the real path for --show-toplevel.
tmp = Path(tempfile.mkdtemp(prefix="deploy-gap-")).resolve()
try:
    # --- the cole-gtm shape: default master, a stale main far off it ---------
    seed = tmp / "seed"
    seed.mkdir()
    git(seed, "init", "-q")
    commit(seed, "base")
    git(seed, "checkout", "-q", "-b", "main")
    for i in range(5):
        commit(seed, f"stale-main-{i}")
    git(seed, "checkout", "-q", "master")
    origin = tmp / "origin.git"
    git(tmp, "clone", "-q", "--bare", str(seed), str(origin))
    clone = tmp / "clone"
    git(tmp, "clone", "-q", str(origin), str(clone))  # clone sets origin/HEAD -> master
    commit(seed, "on-master-after-clone")
    git(seed, "push", "-q", str(origin), "master")
    git(clone, "fetch", "-q", "origin")               # clone is now 1 behind master
    git(clone, "checkout", "-q", "-b", "feat/work")
    commit(clone, "local-only")                       # 1 ahead
    Path(clone, "scratch.txt").write_text("dirty")    # 1 dirty (untracked)
    Path(clone, "run.sh").write_text("dirty too")     # 2 dirty

    # 1. The default is what origin/HEAD names, never an assumed `main`.
    state = dg.tree_state(str(clone))
    check("1a default resolved from origin/HEAD", state["default"], "origin/master")
    check("1b behind counted against master, not the stale main", state["behind"], 1)
    check("1c ahead counted against master", state["ahead"], 1)
    check("1d branch the tree runs", state["branch"], "feat/work")

    # 2. Ahead and dirty are reported, not only behind: they carry the risk.
    check("2a dirty count includes untracked", state["dirty"], 2)
    check("2b reasons name ahead, dirty and the off-default branch",
          sorted(dg.risk_reasons(state)),
          sorted(["on feat/work, not master", "1 behind", "1 ahead", "2 dirty"]))

    # 3. No origin/HEAD: UNRESOLVED, never a fallback to main.
    bare_init = tmp / "no-head"
    bare_init.mkdir()
    git(bare_init, "init", "-q")
    commit(bare_init, "x")
    git(bare_init, "remote", "add", "origin", str(origin))
    git(bare_init, "fetch", "-q", "origin")  # has origin/main AND origin/master
    # git >= 2.48 creates origin/HEAD on fetch (remote.<name>.followRemoteHEAD),
    # so the unset state has to be made explicitly.
    git(bare_init, "remote", "set-head", "origin", "-d")
    unresolved = dg.tree_state(str(bare_init))
    check("3a default unresolved when origin/HEAD is unset", unresolved["default"], None)
    check("3b no behind number is invented", unresolved["behind"], None)
    check("3c the reason says so",
          any("default UNRESOLVED" in r for r in dg.risk_reasons(unresolved)), True)

    # 4. LOADED jobs only. A paused job has a plist and is absent from the count.
    agents = tmp / "LaunchAgents"
    agents.mkdir()
    write_plist(agents, "com.kipi.runner",
                {"ProgramArguments": ["/bin/bash", "-c", f"cd {clone} && ./run.sh"]})
    write_plist(agents, "com.kipi.paused",
                {"ProgramArguments": ["/bin/bash", "-c", f"cd {clone} && ./run.sh"]})
    write_plist(agents, "com.kipi.dashes",
                {"ProgramArguments": ["/usr/bin/python3", f"{clone}/base"]},
                comment="do not edit -- regenerated by the installer")
    write_plist(agents, "com.other.unwatched",
                {"ProgramArguments": ["/bin/bash", "-c", f"cd {clone} && ./run.sh"]})
    listing = launchctl_list("com.kipi.runner", "com.kipi.dashes", "com.other.unwatched")
    prefixes = ("com.kipi.",)
    labels = dg.loaded_labels(listing, prefixes)
    check("4a loaded + watched only; paused and unwatched absent",
          labels, ["com.kipi.dashes", "com.kipi.runner"])
    jobs = dg.survey(listing, prefixes, agents)
    check("4b the paused job is not in the survey",
          sorted(j["label"] for j in jobs), ["com.kipi.dashes", "com.kipi.runner"])
    check("4c `cd <repo> && ...` inside bash -c resolves to the tree",
          next(j["tree"] for j in jobs if j["label"] == "com.kipi.runner"), str(clone))
    check("4d a `--` XML comment does not blind the parser",
          next(j["tree"] for j in jobs if j["label"] == "com.kipi.dashes"), str(clone))
    check("4e both jobs carry the tree's risk",
          all(j["reasons"] for j in jobs), True)
    missing = dg.survey(launchctl_list("com.kipi.ghost"), prefixes, agents)
    check("4f a loaded job with no plist is reported, not dropped",
          [(j["label"], j["tree"], j["reasons"]) for j in missing],
          [("com.kipi.ghost", "", ["no plist, tree unknown"])])

    # 5. "Is commit X live for job Y" -- the ASK-1132 case, on real history.
    real = tmp / "real"
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(REPO), str(real)],
                   check=True, capture_output=True)
    fix = git(real, "rev-parse", f"{ASK_1132_FIX}^{{commit}}")
    check("5a the fix is on main", subprocess.run(
        ["git", "-C", str(REPO), "merge-base", "--is-ancestor", fix, "origin/main"]
    ).returncode, 0)
    git(real, "update-ref", "--no-deref", "HEAD", f"{fix}^")  # the tree the job ran
    write_plist(agents, "com.kipi.linear-dor",
                {"ProgramArguments": ["/bin/bash", "-c", f"cd {real} && ./kipi dor --apply"]})
    dor_listing = launchctl_list("com.kipi.linear-dor")
    live, why = dg.commit_live_for_job("com.kipi.linear-dor", ASK_1132_FIX,
                                       dor_listing, prefixes, agents)
    check("5b merged on main, NOT live for the job", live, False)
    check("5c and it says which tree", str(real) in why, True)
    git(real, "update-ref", "--no-deref", "HEAD", fix)
    live, _ = dg.commit_live_for_job("com.kipi.linear-dor", ASK_1132_FIX,
                                     dor_listing, prefixes, agents)
    check("5d once the tree has it, live", live, True)
    live, why = dg.commit_live_for_job("com.kipi.linear-dor", "0" * 40,
                                       dor_listing, prefixes, agents)
    check("5e a commit the tree has never seen is not live", live, False)
    live, why = dg.commit_live_for_job("com.kipi.paused", ASK_1132_FIX,
                                       launchctl_list(), prefixes, agents)
    check("5f a job that is not loaded gets no answer", live, None)

    # 6. Alert path: one rollup finding, deduped by a stable key.
    filed = dg.linear_findings(jobs, lambda det, subj: f"fleet-health/{det}/{subj}")
    check("6a one rollup, not one issue per job", len(filed), 1)
    check("6b stable key", filed[0]["key"], f"fleet-health/{dg.LINEAR_DETECTOR}/rollup")
    check("6c the body names every affected job",
          all(j["label"] in filed[0]["body"] for j in jobs), True)
    check("6d a clean fleet files nothing",
          dg.linear_findings([dict(jobs[0], reasons=[])], lambda d, s: s), [])

    # 9. --live with launchctl failing is NO ANSWER (exit 2), never NOT LIVE (1).
    # PR #361 review: the RuntimeError escaped and Python's own exit 1 read as a
    # verdict about the commit.
    fake_bin = tmp / "fake-bin"
    fake_bin.mkdir()
    (fake_bin / "launchctl").write_text("#!/bin/sh\necho refused >&2\nexit 1\n")
    (fake_bin / "launchctl").chmod(0o755)
    run = subprocess.run(
        [sys.executable, str(Path(dg.__file__)), "--live", ASK_1132_FIX, "com.kipi.linear-dor"],
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
        capture_output=True, text=True)
    check("9a launchctl failing gives exit 2", run.returncode, 2)
    check("9b and says NO ANSWER", run.stdout.startswith("NO ANSWER"), True)

    # 10. The survey takes no optional lock in a tree a live job writes to. A
    # stat-stale index is the case where a plain `git status` rewrites the index
    # under .git/index.lock (PR #361 review: a concurrent `git add` then failed).
    locky = tmp / "locky"
    locky.mkdir()
    git(locky, "init", "-q")
    commit(locky, "tracked")
    os.utime(locky / "tracked", (1, 1))
    index = locky / ".git" / "index"
    before = (index.stat().st_mtime_ns, index.read_bytes())
    dg.tree_state(str(locky))
    check("10 tree_state leaves the index untouched",
          (index.stat().st_mtime_ns, index.read_bytes()) == before, True)

    # 11. The rollup describes what it files, and moves only when its CONTENT does.
    on_default = {"label": "com.kipi.dirty-only", "tree": "/t/a", "branch": "master",
                  "default": "origin/master", "behind": 0, "ahead": 0, "dirty": 2}
    key = lambda d, s: s  # noqa: E731
    dirty_only = dg.linear_findings([dict(on_default, reasons=dg.risk_reasons(on_default))], key)
    check("11a a dirty tree on its default is not filed as off its default branch",
          "off its default branch" in dirty_only[0]["title"], False)
    counted = dict(on_default, behind=1)
    moved = dict(on_default, behind=4, dirty=3)
    filed, refiled = (dg.linear_findings([dict(s, reasons=dg.risk_reasons(s))], key)
                      for s in (counted, moved))
    check("11b a count that moves does not rewrite the rollup",
          (refiled[0]["title"], refiled[0]["body"]), (filed[0]["title"], filed[0]["body"]))
    branched = dict(moved, branch="feat/x")
    rebranched = dg.linear_findings([dict(branched, reasons=dg.risk_reasons(branched))], key)
    check("11c a new KIND of risk does rewrite it",
          rebranched[0]["body"] != refiled[0]["body"], True)

    # 12. A job that runs through a re-exec wrapper gets NO ANSWER, never a verdict
    # about the checkout its plist names. PR #361 review r2, major: the plist names
    # the primary checkout, and kipi-dispatch-pinned.sh execs the payload from a
    # worktree pinned at origin/main, so --live answered LIVE / NOT LIVE inverted.
    # The plist is the REAL template, rendered the way the installer renders it.
    wrapper_home = tmp / "home"
    wrapper_home.mkdir()
    Path(clone, "kipi-dispatch-pinned.sh").write_text("#!/bin/bash\n")
    template = (HERE / "com.kipi.dispatch.plist").read_text()
    (agents / "com.kipi.dispatch.plist").write_text(
        template.replace("__KIPI_REPO__", str(clone)).replace("__HOME__", str(wrapper_home)))
    wrapped_listing = launchctl_list("com.kipi.dispatch")
    wrapped = dg.survey(wrapped_listing, prefixes, agents)
    check("12a the wrapped job is not mapped to the checkout its plist names",
          [(j["label"], j["tree"]) for j in wrapped], [("com.kipi.dispatch", "")])
    check("12b and it is not filed as off its default",
          dg.linear_findings(wrapped, lambda d, s: s), [])
    live, why = dg.commit_live_for_job("com.kipi.dispatch", "HEAD", wrapped_listing,
                                       prefixes, agents)
    check("12c --live gives NO ANSWER for it", live, None)
    check("12d and names the wrapper", "kipi-dispatch-pinned.sh" in why, True)
    check("12e the carve-out is bound to a wrapper that still re-execs elsewhere",
          'exec env KIPI_REPO="$PINNED" bash "$PINNED/' in (REPO / "kipi-dispatch-pinned.sh").read_text(),
          True)

    # 13. A tree whose `git status` fails is unreadable, never clean. PR #361
    # review r2: the return code was dropped and an empty stdout counted 0 dirty.
    broken = tmp / "broken"
    git(tmp, "clone", "-q", str(origin), str(broken))
    Path(broken, "base").write_text("locally modified")
    (broken / ".git" / "index").write_bytes(b"garbage")
    broken_state = dg.tree_state(str(broken))
    check("13a a failing status is no dirty count, not 0", broken_state["dirty"], None)
    check("13b and the reason says so",
          any("status unreadable" in r for r in dg.risk_reasons(broken_state)), True)
    check("13c the report line does not print a count",
          "None dirty" in dg.report_line(dict(broken_state, label="x",
                                              reasons=dg.risk_reasons(broken_state))), False)

    # 15. A git-IGNORED interpreter path is skipped, so a Homebrew-python job maps
    # to its script's tree and not to /opt/homebrew (which is itself a git repo).
    # PR #361 review r2, nit: deleting the check-ignore guard left the suite green.
    brew = tmp / "brew"
    brew.mkdir()
    git(brew, "init", "-q")
    Path(brew, ".gitignore").write_text("bin/\n")
    commit(brew, "README")
    (brew / "bin").mkdir()
    (brew / "bin" / "python3").write_text("")
    write_plist(agents, "com.kipi.brewpy",
                {"ProgramArguments": [str(brew / "bin" / "python3"), f"{clone}/base"]})
    brewed = dg.survey(launchctl_list("com.kipi.brewpy"), prefixes, agents)
    check("15 an ignored interpreter path does not claim the job",
          brewed[0]["tree"], str(clone))

    # 14. A refused rollup write is owed-and-unfiled, never the clean fleet's line.
    # PR #361 review r2: run_check set no `owed`, so the watchdog's unfiled_count
    # fell back to skipped_no_key and printed unfiled=0 over errors=1.
    wd = _load(HERE / "launchd-health-check.py", "wd")

    class RefusingFleetHealth:
        @staticmethod
        def finding_key(detector, subject):
            return f"fleet-health/{detector}/{subject}"

        @staticmethod
        def file_findings(findings, apply, filer):
            return {"created": 0, "existing": 0, "skipped_no_key": 0, "errors": 1}

    real_listing = dg.launchctl_listing
    dg.launchctl_listing = lambda: launchctl_list("com.kipi.ghost")
    try:
        refused = dg.run_check(prefixes, RefusingFleetHealth, dry_run=False, agents_dir=agents)
        dg.launchctl_listing = lambda: launchctl_list()
        clean = dg.run_check(prefixes, RefusingFleetHealth, dry_run=False, agents_dir=agents)
    finally:
        dg.launchctl_listing = real_listing
    check("14a a refused write leaves the rollup unfiled", wd.unfiled_count(refused), 1)
    check("14b a clean fleet owes nothing", wd.unfiled_count(clean), 0)
finally:
    shutil.rmtree(tmp, ignore_errors=True)


# 8. Test 5 needs kipi-system commit 896b0e5a, which no instance history has, so
# this suite is skeleton-only. Unlisted, it crashed `kipi check` in every
# instance (PR #361 review, major).
sys.path.insert(0, str(HERE))
import capability_manifest  # noqa: E402

manifest_errors = []
manifest = capability_manifest.load(REPO, manifest_errors) or {}
check("8 this suite is declared skeleton-only",
      "q-system/.q-system/scripts/test_launchd_deploy_gap.py" in manifest.get("skeleton_only", []),
      True)


# 7. Negative self-test: the default-branch guard is what holds test 1.
if "DEPLOY_GAP_UNDER_TEST" not in os.environ:
    mutant_dir = Path(tempfile.mkdtemp(prefix="deploy-gap-mutant-"))
    try:
        source = (HERE / "launchd-deploy-gap.py").read_text()
        marker = "def resolve_default(top):\n"
        check("7a the resolver exists to mutate", marker in source, True)
        mutant = mutant_dir / "launchd-deploy-gap.py"
        mutant.write_text(source.replace(
            marker, marker + '    return "origin/main"  # MUTANT: assume main\n', 1))
        run = subprocess.run([sys.executable, str(HERE / Path(__file__).name)],
                             env={**os.environ, "DEPLOY_GAP_UNDER_TEST": str(mutant)},
                             capture_output=True, text=True)
        check("7b assuming origin/main turns the suite RED", run.returncode, 1)
        check("7c on the default-branch assertions",
              "1a default resolved from origin/HEAD" in run.stdout, True)
    finally:
        shutil.rmtree(mutant_dir, ignore_errors=True)


if failures:
    print("FAIL")
    for line in failures:
        print("  " + line)
    sys.exit(1)
print("PASS: launchd-deploy-gap")
sys.exit(0)
