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
finally:
    shutil.rmtree(tmp, ignore_errors=True)


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
