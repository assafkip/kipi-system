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

    if failures:
        print(f"\nFAILED: {failures}")
        sys.exit(1)
    print("\nOK: all checks passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
