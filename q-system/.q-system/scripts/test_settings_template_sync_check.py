#!/usr/bin/env python3
"""Test for settings-template-sync-check.py (reproducer-first).

Builds temp repos with .claude/settings.json + settings-template.json and proves
the check FAILS (exit 2) exactly when a propagated-script hook is stranded in
settings.json, and PASSES otherwise. Test isolation: temp dirs only.

Run: python3 q-system/.q-system/scripts/test_settings_template_sync_check.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = os.path.join(HERE, "settings-template-sync-check.py")


def hook(cmd):
    return {"type": "command", "command": cmd}


def prop(script):  # a propagated-script hook command
    return hook(f'python3 "$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/{script}"')


def build_repo(tmp, runtime_cmds, template_cmds, with_template=True):
    os.makedirs(os.path.join(tmp, ".claude"))
    sj = {"hooks": {"PostToolUse": [{"matcher": "Edit|Write", "hooks": runtime_cmds}]}}
    json.dump(sj, open(os.path.join(tmp, ".claude", "settings.json"), "w"))
    if with_template:
        st = {"hooks": {"PostToolUse": [{"matcher": "Edit|Write", "hooks": template_cmds}]}}
        json.dump(st, open(os.path.join(tmp, "settings-template.json"), "w"))


def run_check_cli(tmp):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=tmp)
    return subprocess.run([sys.executable, CHECK, "--check"], capture_output=True,
                          text=True, env=env, stdin=subprocess.DEVNULL).returncode


def run_check_hook(tmp, file_path):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=tmp)
    payload = json.dumps({"tool_input": {"file_path": file_path}})
    return subprocess.run([sys.executable, CHECK], input=payload, capture_output=True,
                          text=True, env=env).returncode


def main():
    failures = []

    def check(label, ok):
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            failures.append(label)

    # 1. REPRODUCER: stranded propagated hook -> exit 2
    with tempfile.TemporaryDirectory() as t:
        build_repo(t, [prop("foo-lint.py")], [])
        check("stranded hook -> exit 2 (reproducer)", run_check_cli(t) == 2)

    # 2. in sync -> exit 0
    with tempfile.TemporaryDirectory() as t:
        build_repo(t, [prop("foo-lint.py")], [prop("foo-lint.py")])
        check("in sync -> exit 0", run_check_cli(t) == 0)

    # 3. allowlisted skeleton-only (the check itself) missing from template -> exit 0
    with tempfile.TemporaryDirectory() as t:
        build_repo(t, [prop("settings-template-sync-check.py")], [])
        check("allowlisted skeleton-only -> exit 0", run_check_cli(t) == 0)

    # 4. non-propagated script (not under q-system) stranded -> exit 0 (does not ship)
    with tempfile.TemporaryDirectory() as t:
        build_repo(t, [hook("python3 /usr/local/bin/external.py")], [])
        check("non-propagated script ignored -> exit 0", run_check_cli(t) == 0)

    # 5. template absent (instance) -> exit 0 no-op
    with tempfile.TemporaryDirectory() as t:
        build_repo(t, [prop("foo-lint.py")], [], with_template=False)
        check("template absent (instance) -> exit 0", run_check_cli(t) == 0)

    # 6. hook mode: in-scope edit + divergence -> exit 2
    with tempfile.TemporaryDirectory() as t:
        build_repo(t, [prop("foo-lint.py")], [])
        sj = os.path.join(t, ".claude", "settings.json")
        check("hook mode, settings.json edit + divergence -> exit 2",
              run_check_hook(t, sj) == 2)

    # 7. hook mode: off-scope edit -> exit 0 even with divergence
    with tempfile.TemporaryDirectory() as t:
        build_repo(t, [prop("foo-lint.py")], [])
        check("hook mode, off-scope file -> exit 0",
              run_check_hook(t, os.path.join(t, "README.md")) == 0)

    if failures:
        print(f"\nFAILED: {failures}")
        sys.exit(1)
    print("\nOK: all checks passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
