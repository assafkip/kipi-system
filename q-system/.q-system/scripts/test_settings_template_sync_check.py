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


def build_repo_event(tmp, event, runtime_cmds, template_cmds):
    os.makedirs(os.path.join(tmp, ".claude"))
    for rel, cmds in ((".claude/settings.json", runtime_cmds),
                      ("settings-template.json", template_cmds)):
        doc = {"hooks": {event: [{"hooks": cmds}]}}
        json.dump(doc, open(os.path.join(tmp, rel), "w"))


def load_check_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_check", CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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

    # 2b. in template, NOT settings.json -> skeleton gap -> exit 2 (sp-aa7e4995 class)
    with tempfile.TemporaryDirectory() as t:
        build_repo(t, [], [prop("bar-lint.py")])
        check("in template, not settings.json -> exit 2 (skeleton gap)", run_check_cli(t) == 2)

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

    # ASK-1166: same script wired in both files, guarded in the template, not in
    # settings.json. Scripts are invented names so no recorded entry applies.
    def guarded(script):
        p = f'"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/{script}"'
        return hook(f"test -f {p} && python3 {p}")

    # 8. REPRODUCER: template guarded, settings.json unguarded -> exit 2
    with tempfile.TemporaryDirectory() as t:
        build_repo(t, [prop("foo-lint.py")], [guarded("foo-lint.py")])
        check("guard drift (template guarded, runtime not) -> exit 2 (reproducer)",
              run_check_cli(t) == 2)

    # 9. both guarded -> exit 0
    with tempfile.TemporaryDirectory() as t:
        build_repo(t, [guarded("foo-lint.py")], [guarded("foo-lint.py")])
        check("both guarded -> exit 0", run_check_cli(t) == 0)

    # 10. the `[ -f ... ] &&` loop form is a guard too -> exit 0
    loop = hook('for R in q-system/.q-system/scripts/foo-lint.py; do '
                '[ -f "$CLAUDE_PROJECT_DIR/$R" ] && python3 "$CLAUDE_PROJECT_DIR/$R"; done')
    with tempfile.TemporaryDirectory() as t:
        build_repo(t, [loop], [guarded("foo-lint.py")])
        check("[ -f ] loop form counts as a guard -> exit 0", run_check_cli(t) == 0)

    # 11/12. recorded entries, read from the table that owns them (never restated)
    mod = load_check_module()
    recorded = sorted(mod.GUARD_DRIFT_RECORDED)
    check("recorded table is non-empty (derivation floor)", len(recorded) > 0)
    event, script = recorded[0].split(":", 1)
    with tempfile.TemporaryDirectory() as t:
        build_repo_event(t, event, [prop(script)], [guarded(script)])
        check(f"recorded drift {recorded[0]} -> exit 0", run_check_cli(t) == 0)
    with tempfile.TemporaryDirectory() as t:
        build_repo_event(t, event, [guarded(script)], [guarded(script)])
        check(f"stale recorded entry {recorded[0]} (now guarded) -> exit 2",
              run_check_cli(t) == 2)

    if failures:
        print(f"\nFAILED: {failures}")
        sys.exit(1)
    print("\nOK: all checks passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
