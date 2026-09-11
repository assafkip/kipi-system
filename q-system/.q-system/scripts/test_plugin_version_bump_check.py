#!/usr/bin/env python3
"""Test for plugin-version-bump-check.py (reproducer-first).

Unit-tests the pure core (find_violations) and runs a git integration test in a
temp repo proving the check FAILS when a plugin changes without a version bump and
PASSES after the bump. Test isolation: temp git repo only.

Run: python3 q-system/.q-system/scripts/test_plugin_version_bump_check.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "plugin-version-bump-check.py")

spec = importlib.util.spec_from_file_location("pvbc", SCRIPT)
pvbc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pvbc)


def git(cwd, *args):
    subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True, check=True)


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(content)


def manifest(version):
    return json.dumps({"name": "foo", "version": version})


def run_script(cwd, *args):
    return subprocess.run([sys.executable, SCRIPT, *args], cwd=cwd,
                          capture_output=True, text=True).returncode


def run_script_full(cwd, *args):
    """(returncode, stderr). Needed because an exit code alone cannot say WHICH
    plugin was flagged, and case D below passed for the wrong plugin until the
    reason was asserted (ASK-514)."""
    r = subprocess.run([sys.executable, SCRIPT, *args], cwd=cwd,
                       capture_output=True, text=True)
    return r.returncode, r.stderr


def main():
    failures = []

    def check(label, ok):
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            failures.append(label)

    # --- unit: pure core ---
    check("core: same version -> violation",
          pvbc.find_violations({"a"}, {"a": "1.0"}, {"a": "1.0"}) == [("a", "1.0")])
    check("core: bumped -> no violation",
          pvbc.find_violations({"a"}, {"a": "1.0"}, {"a": "1.1"}) == [])
    check("core: only the unbumped plugin flagged",
          pvbc.find_violations({"a", "b"}, {"a": "1", "b": "2"}, {"a": "1", "b": "3"}) == [("a", "1")])

    # --- integration: real git repo ---
    with tempfile.TemporaryDirectory() as tmp:
        git(tmp, "init", "-q")
        git(tmp, "config", "user.email", "t@t")
        git(tmp, "config", "user.name", "t")
        write(os.path.join(tmp, "plugins/foo/.claude-plugin/plugin.json"), manifest("1.0.0"))
        write(os.path.join(tmp, "plugins/foo/cmd.md"), "v1\n")
        write(os.path.join(tmp, "README.md"), "root\n")
        git(tmp, "add", "-A"); git(tmp, "commit", "-qm", "init")

        # REPRODUCER: change plugin file, no bump, stage -> exit 2
        write(os.path.join(tmp, "plugins/foo/cmd.md"), "v2\n")
        git(tmp, "add", "plugins/foo/cmd.md")
        check("changed plugin, no bump -> exit 2 (reproducer)", run_script(tmp, "--staged") == 2)

        # bump version, stage -> exit 0
        write(os.path.join(tmp, "plugins/foo/.claude-plugin/plugin.json"), manifest("1.1.0"))
        git(tmp, "add", "plugins/foo/.claude-plugin/plugin.json")
        check("changed plugin + bump -> exit 0", run_script(tmp, "--staged") == 0)

        git(tmp, "commit", "-qm", "bump")

        # non-plugin change only -> exit 0
        write(os.path.join(tmp, "README.md"), "edited\n")
        git(tmp, "add", "README.md")
        check("non-plugin change only -> exit 0", run_script(tmp, "--staged") == 0)

        # --against mode: plugin changed since a ref without bump -> exit 2
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp, capture_output=True, text=True).stdout.strip()
        write(os.path.join(tmp, "plugins/foo/cmd.md"), "v3\n")
        check("--against ref, changed no bump -> exit 2", run_script(tmp, "--against", base) == 2)

    # --- ASK-514: --against must resolve to the MERGE BASE, not the moving tip ---
    #
    # The shipped check ran `git diff <ref>` and `version_at(<ref>)` against the
    # TIP of origin/main, so anything landing on main after a PR branched was
    # attributed to that PR. Reproduced live on PR #127, which touched only
    # plugins/kipi-core and was failed for plugins/kipi-design.
    #
    # FOUR cases on purpose. A fix that simply stops the gate firing would pass
    # case A alone, so B and C prove the gate still refuses a real violation and
    # still clears a real bump. D is the half that is easy to miss: the moving
    # tip can also HIDE a violation, because a bump on MAIN makes the PR's own
    # unbumped plugin look bumped.
    with tempfile.TemporaryDirectory() as tmp:
        git(tmp, "init", "-q")
        git(tmp, "config", "user.email", "t@t")
        git(tmp, "config", "user.name", "t")
        for name, ver in (("foo", "1.0.0"), ("bar", "2.0.0")):
            write(os.path.join(tmp, f"plugins/{name}/.claude-plugin/plugin.json"),
                  manifest(ver))
            write(os.path.join(tmp, f"plugins/{name}/cmd.md"), "v1\n")
        write(os.path.join(tmp, "README.md"), "root\n")
        git(tmp, "add", "-A"); git(tmp, "commit", "-qm", "init")
        git(tmp, "branch", "-M", "main")
        git(tmp, "checkout", "-qb", "feature")

        # main advances with an unbumped plugin change of its OWN (the c166cc96
        # shape: kipi-design edited on main, version left at 1.2.8).
        git(tmp, "checkout", "-q", "main")
        write(os.path.join(tmp, "plugins/bar/cmd.md"), "v2\n")
        git(tmp, "add", "-A"); git(tmp, "commit", "-qm", "main: bar, no bump")
        git(tmp, "checkout", "-q", "feature")

        # A. the PR touches no plugin at all -> main's sin is not the PR's
        write(os.path.join(tmp, "README.md"), "feature edit\n")
        git(tmp, "add", "-A"); git(tmp, "commit", "-qm", "feature: docs only")
        check("A. main's unbumped plugin is NOT attributed to the PR -> exit 0",
              run_script(tmp, "--against", "main") == 0)

        # B. the PR's OWN unbumped plugin must still be refused
        write(os.path.join(tmp, "plugins/foo/cmd.md"), "v2\n")
        git(tmp, "add", "-A"); git(tmp, "commit", "-qm", "feature: foo, no bump")
        check("B. the PR's own unbumped plugin STILL fails -> exit 2",
              run_script(tmp, "--against", "main") == 2)

        # C. and a real bump must still clear it, so B is not just 'always red'
        write(os.path.join(tmp, "plugins/foo/.claude-plugin/plugin.json"),
              manifest("1.1.0"))
        git(tmp, "add", "-A"); git(tmp, "commit", "-qm", "feature: bump foo")
        check("C. the PR's own plugin, bumped -> exit 0",
              run_script(tmp, "--against", "main") == 0)

        # D. the tip can HIDE a violation: main bumps foo, the PR does not, and
        # comparing versions against the tip makes the PR look compliant.
        git(tmp, "checkout", "-q", "main")
        write(os.path.join(tmp, "plugins/foo/.claude-plugin/plugin.json"),
              manifest("1.9.0"))
        git(tmp, "add", "-A"); git(tmp, "commit", "-qm", "main: bump foo to 1.9.0")
        git(tmp, "checkout", "-qb", "feature2", "feature~1")   # foo changed, NOT bumped
        rc, err = run_script_full(tmp, "--against", "main")
        # THE REASON, not just the code. Against the tip this exited 2 for `bar`
        # -- main's own change -- while silently EXCUSING foo, because
        # version_at(tip, foo)=1.9.0 differed from the PR's 1.0.0 and so read as
        # a bump the PR never made. Asserting only the exit code passed on the
        # wrong plugin and hid exactly the half this case exists to catch.
        check("D. a bump on MAIN does not excuse the PR's unbumped plugin",
              rc == 2 and "- foo" in err and "- bar" not in err)

    # --- ASK-514: an unresolvable --against ref must FAIL CLOSED ---
    #
    # run() returns only stdout and throws the return code away, so a git
    # command that FAILED was indistinguishable from one that found nothing:
    # `git diff <bad-ref>` returned "", changed_files saw no files, and the gate
    # exited 0 having verified nothing. A blocking check that silently becomes
    # no check is worse than no check, because CI reports it green.
    #
    # The workflow makes this reachable rather than theoretical:
    #     git fetch origin main || true
    #     ... --against origin/main
    # The `|| true` swallows a fetch failure, and on a runner whose fetch failed
    # origin/main may not resolve at all.
    with tempfile.TemporaryDirectory() as tmp:
        git(tmp, "init", "-q")
        git(tmp, "config", "user.email", "t@t")
        git(tmp, "config", "user.name", "t")
        write(os.path.join(tmp, "plugins/foo/.claude-plugin/plugin.json"),
              manifest("1.0.0"))
        write(os.path.join(tmp, "plugins/foo/cmd.md"), "v1\n")
        git(tmp, "add", "-A"); git(tmp, "commit", "-qm", "init")

        # A REAL violation is sitting in the tree the whole time, so a green
        # result here can only mean the gate checked nothing at all.
        write(os.path.join(tmp, "plugins/foo/cmd.md"), "v2\n")
        rc, err = run_script_full(tmp, "--against", "no-such-ref-xyz")
        check("E. an unresolvable --against ref fails CLOSED, naming the ref",
              rc == 2 and "no-such-ref-xyz" in err)

        # And the resolvable case must still work, so E is not just 'always 2'.
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp,
                              capture_output=True, text=True).stdout.strip()
        check("F. a resolvable ref still evaluates normally -> exit 2",
              run_script(tmp, "--against", base) == 2)
        write(os.path.join(tmp, "plugins/foo/.claude-plugin/plugin.json"),
              manifest("1.1.0"))
        check("G. ...and still clears on a real bump -> exit 0",
              run_script(tmp, "--against", base) == 0)

    # --- ASK-514: CI must hand the gate an IMMUTABLE base, not a fetched ref ---
    #
    # The gate is only as correct as the base it is given, and a
    # remote-tracking ref is not trustworthy: `git fetch origin main || true`
    # swallows a failure, leaving origin/main STALE BUT RESOLVABLE. Fail-closed
    # never fires (it resolves fine), and version_at(stale base) then reads a
    # HISTORICAL bump that makes the PR's own unbumped plugin look bumped.
    # Measured on a scratch repo:
    #     --against HEAD        -> exit 2   (correctly refused)
    #     --against stale-main  -> exit 0   (the violation was EXCUSED)
    # github.event.pull_request.base.sha is the base GitHub itself computed for
    # the PR. It needs no fetch, always resolves, and cannot go stale.
    # COMMENTS ARE STRIPPED FIRST, and that is the whole point of this block.
    # The first cut scanned raw lines, so the explanatory comment above the step
    # -- which quotes `--against HEAD` and `--against stale-main` -- kept the
    # check green after the real argument was deleted. Verified by deleting it:
    # the gate silently falls back to --staged mode and the test still printed
    # "OK: all checks passed". A check that cannot fail for the reason it exists
    # (codex minor, PR #129; same shape as METRICS_VERSION - 1 and case D).
    wf = os.path.join(HERE, "..", "..", "..", ".github", "workflows", "validate.yml")
    if os.path.isfile(wf):
        raw = open(wf).read().splitlines()
        code = [l for l in raw if not l.strip().startswith("#")]
        invocations = [l for l in code
                       if "plugin-version-bump-check.py" in l or "--against" in l]
        joined = "\n".join(invocations)
        check("H. CI passes an immutable base sha, not a fetched ref",
              bool(invocations) and "--against" in joined
              and "origin/main" not in joined)
        # The fetch must not be re-added on an EXECUTABLE line near the gate.
        idx = code.index(invocations[0]) if invocations else 0
        near = code[max(0, idx - 6):idx + 1]
        check("I. CI does not swallow a failure on the line feeding the gate",
              bool(invocations)
              and not any("|| true" in l and "fetch" in l for l in near))    # --- Codex findings on PR #253 ---

    # MAJOR: --fix must never `git add` a manifest carrying unstaged work.
    # `git add <man>` stages the WHOLE working-tree file, so an unrelated edit
    # the founder had in flight is absorbed into a commit whose message says
    # only "version bump". That is the same absorption this gate exists to stop
    # (the script header records it eating the ASK-999 port), so a fixer that
    # does it reproduces the defect it was written to end.
    with tempfile.TemporaryDirectory() as tmp:
        git(tmp, "init", "-q")
        git(tmp, "config", "user.email", "t@t")
        git(tmp, "config", "user.name", "t")
        man_rel = "plugins/foo/.claude-plugin/plugin.json"
        write(os.path.join(tmp, man_rel), manifest("1.0.0"))
        write(os.path.join(tmp, "plugins/foo/cmd.md"), "v1\n")
        git(tmp, "add", "-A"); git(tmp, "commit", "-qm", "base")
        # a plugin edit staged for commit (this is what trips the gate) ...
        write(os.path.join(tmp, "plugins/foo/cmd.md"), "v2\n")
        git(tmp, "add", "plugins/foo/cmd.md")
        # ... and UNRELATED founder work sitting unstaged in the manifest.
        import json as _j
        d = _j.loads(open(os.path.join(tmp, man_rel)).read())
        d["description"] = "founder work in flight"
        open(os.path.join(tmp, man_rel), "w").write(_j.dumps(d))

        rc, err = run_script_full(tmp, "--fix")
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"],
                                cwd=tmp, capture_output=True, text=True).stdout
        absorbed = man_rel in staged
        check("fix: refuses rather than absorbing unstaged manifest work",
              rc != 0 and not absorbed)
        check("fix: says WHY it refused, not just that it did",
              "unstaged" in err.lower())

    # MINOR: --fix must handle the root-level plugin.json layout that
    # manifest_path() already supports. The fixer hardcoded the
    # .claude-plugin/ path, so it crashed on the very layout the checker flags.
    with tempfile.TemporaryDirectory() as tmp:
        git(tmp, "init", "-q")
        git(tmp, "config", "user.email", "t@t")
        git(tmp, "config", "user.name", "t")
        write(os.path.join(tmp, "plugins/bar/plugin.json"), manifest("2.0.0"))
        write(os.path.join(tmp, "plugins/bar/cmd.md"), "v1\n")
        git(tmp, "add", "-A"); git(tmp, "commit", "-qm", "base")
        write(os.path.join(tmp, "plugins/bar/cmd.md"), "v2\n")
        git(tmp, "add", "plugins/bar/cmd.md")

        rc, err = run_script_full(tmp, "--fix")
        newver = json.loads(open(os.path.join(tmp, "plugins/bar/plugin.json")).read())["version"]
        check("fix: bumps the root-level plugin.json layout", rc == 0 and newver == "2.0.1")
        check("fix: does not traceback on the root-level layout",
              "Traceback" not in err)

    print()
    if failures:
        print(f"\nFAILED: {failures}")
        sys.exit(1)
    print("\nOK: all checks passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
