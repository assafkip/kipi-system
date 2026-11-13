"""KIPI_REVIEW_LEAN (ASK-4743): the reviewer's command line, off and on.

No real model call: `claude` is a stub that records its argv and env. Every
tmp file lives under pytest's tmp_path; nothing touches a live data path.
"""
import json
import re
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
LIB = SCRIPTS / "review-lean-lib.sh"
SETTINGS = SCRIPTS.parent / "review-lean-settings.json"
AGENT = SCRIPTS / "pr-review-agent.sh"

# The line pr-review-agent.sh ran before this change, with the shell variables
# filled. The OFF test compares against this literal, not against the lib.
OLD = ("cd '{root}' && KIPI_AGENT=pr-reviewer {fleet} -p --model '{model}' \"$1\" "
       "--disallowedTools 'Bash(git clone:*)' 'Bash(gh:*)' 'Bash(curl:*)' </dev/null > '{dest}' 2>&1")

STUB = textwrap.dedent("""\
    #!/usr/bin/env bash
    { printf 'ARGV'; for a in "$@"; do printf '\\t%s' "$a"; done; printf '\\n';
      printf 'ENV\\t%s\\t%s\\t%s\\n' "${CLAUDE_CODE_DISABLE_CLAUDE_MDS:-}" "${CLAUDE_CODE_DISABLE_AUTO_MEMORY:-}" "${KIPI_REVIEW_SCRIPTS:-}"; } >> "$REC"
    """)


def template():
    """The double-quoted `bash -c` string of the reviewer's claude arm, as source text."""
    m = re.findall(r'(?m)^\s*("cd \'\$REVIEW_ROOT\' && .*? 2>&1")\s+_ "\$PROMPT"', AGENT.read_text())
    assert len(m) == 1, f"expected one claude bash -c line in pr-review-agent.sh, found {len(m)}"
    return m[0]


def build(lib, lean, tmp, mode):
    """Run the command the lib prints, with a stub claude; return (argv, env_row)."""
    rec = tmp / "rec.txt"
    rec.unlink(missing_ok=True)
    stub = tmp / "stub"
    stub.mkdir(exist_ok=True)
    (stub / "claude").write_text(STUB)
    (stub / "claude").chmod(0o755)
    (stub / "fleet").write_text(STUB)
    (stub / "fleet").chmod(0o755)
    fleet = str(stub / "fleet") if mode == "keyed" else "env -u ANTHROPIC_API_KEY claude"
    env = {**os.environ, "REC": str(rec), "PATH": f"{stub}:{os.environ['PATH']}"}
    env.pop("KIPI_REVIEW_LEAN", None)
    if lean is not None:
        env["KIPI_REVIEW_LEAN"] = lean
    root = tmp / "tree"
    root.mkdir(exist_ok=True)
    # The REAL template from pr-review-agent.sh's claude arm, expanded by bash with
    # the lib's two globals, so the test sees the line the reviewer runs (ASK-4796:
    # a lib-printed copy hid the call from every consumer that reads the reviewer).
    cmd = subprocess.run(
        ["bash", "-c", f'. "{lib}"; review_lean_args "{SCRIPTS}"; REVIEW_ROOT="{root}"; CLAUDE_MODEL=claude-test; '
                       f'FLEET_CLAUDE="$F"; set -- claude "{tmp}/out"; eval "cmd=$TPL"; printf "%s" "$cmd"'],
        env={**env, "F": fleet, "TPL": template()}, capture_output=True, text=True, check=True).stdout
    subprocess.run(["bash", "-c", cmd, "_", "PROMPT"], env=env, check=True,
                   capture_output=True, text=True)
    rows = rec.read_text().splitlines()
    argv = rows[0].split("\t")[1:]
    return cmd, argv, rows[1].split("\t")[1:], str(root), fleet


def failures(lib, tmp):
    """Every contract check, as a list of failure names. Empty = the lib is right."""
    bad = []
    for mode in ("keyed", "plan"):
        # OFF is KIPI_REVIEW_LEAN=0, exactly. Default ON since the planted-defect
        # control (ASK-4743, PRs #790/#791): lean caught every defect normal did.
        cmd, argv, env, root, fleet = build(lib, "0", tmp, mode)
        if cmd != OLD.format(root=root, fleet=fleet, model="claude-test", dest=f"{tmp}/out"):
            bad.append(f"{mode}: off is not byte-identical")
        if "--setting-sources" in argv or env != ["", "", ""]:
            bad.append(f"{mode}: off leaks lean flags or env")
        _, argv, env, _, _ = build(lib, None, tmp, mode)
        for v in ("1", "true", ""):
            if build(lib, v, tmp, mode)[1] != argv:
                bad.append(f"{mode}: switch value {v!r} differs from the default (lean)")
        for need in (["--setting-sources", ""], ["--strict-mcp-config"], ["--tools", "Read,Grep,Glob,Bash"],
                     ["--allowedTools", "Read,Grep,Glob,Bash"], ["--disable-slash-commands"],
                     ["--mcp-config", '{"mcpServers":{}}'], ["--disallowedTools", "Bash(git clone:*)"]):
            if not any(argv[i:i + len(need)] == need for i in range(len(argv))):
                bad.append(f"{mode}: lean missing {need}")
        if "--settings" not in argv or not argv[argv.index("--settings") + 1].endswith("/review-lean-settings.json"):
            bad.append(f"{mode}: lean does not attach the guard settings")
        if env[:2] != ["1", "1"] or env[2] != str(SCRIPTS):
            bad.append(f"{mode}: lean env wrong {env}")
        if argv[0] != "-p" or "PROMPT" not in argv:
            bad.append(f"{mode}: prompt not passed as \"$1\"")
    return bad


def test_contract_holds(tmp_path):
    assert failures(LIB, tmp_path) == []


MUTANTS = {
    "switch always on": ('"${KIPI_REVIEW_LEAN:-1}" != "0"', '"1" = "1"'),
    "switch inverted": ('"${KIPI_REVIEW_LEAN:-1}" != "0"', '"${KIPI_REVIEW_LEAN:-1}" = "0"'),
    "default off again": ("KIPI_REVIEW_LEAN:-1}", "KIPI_REVIEW_LEAN:-0}"),
    "settings sources kept": ("--setting-sources '' ", ""),
    "tools not restricted": ("--tools Read,Grep,Glob,Bash ", ""),
    "mcp kept": ("--strict-mcp-config ", ""),
    "guards not attached": ("--settings '$sdir/../review-lean-settings.json' ", ""),
    "claude.md kept": ("CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 ", ""),
    "scripts dir not exported": ("KIPI_REVIEW_SCRIPTS='$sdir' ", ""),
}


def test_every_decision_point_has_a_killed_mutant(tmp_path):
    text = LIB.read_text()
    for name, (old, new) in MUTANTS.items():
        assert text.count(old) == 1, f"mutant {name!r} anchor is stale"
        mut = tmp_path / "m.sh"
        mut.write_text(text.replace(old, new))
        (tmp_path / "w").mkdir(exist_ok=True)
        assert failures(mut, tmp_path / "w"), f"mutant {name!r} SURVIVED"


def test_settings_attach_exactly_the_guards():
    s = json.loads(SETTINGS.read_text())
    cmds = [h["command"] for g in s["hooks"]["PreToolUse"] for h in g["hooks"]]
    joined = " ".join(cmds)
    for guard in ("destructive-op-deny.sh", "ps-archive-deny.sh", "claude-path-write-guard.py"):
        assert guard in joined
    # ASK-4769 (b): no Stop or SubagentStop hook either. rule_gate.py's Stop scan reads every
    # rule file under ~/projects, so one unrelated tree's debt blocked a reviewer's Stop
    # and its verdict went UNSTATED (PR #788 round 2). The gate is wired only in user
    # settings, which --setting-sources '' does not load.
    assert set(s["hooks"]) == {"PreToolUse"}, "context-injecting and Stop-scan events must stay off in lean mode"
    assert "/Users/" not in SETTINGS.read_text()
    assert (SCRIPTS / "claude-path-write-guard.py").is_file()


def test_lean_keeps_every_project_deny_rule():
    """--setting-sources '' drops the project deny list. Measured 2026-11-12 in a
    real lean run before this copy: `sudo -n true` ran. With it: "Permission to
    use Bash with command sudo -n true has been denied." A rule added to the
    project list and not here would run unrefused in every lean review."""
    project = json.loads((SCRIPTS.parents[2] / ".claude" / "settings.json").read_text())
    lean = json.loads(SETTINGS.read_text())
    missing = set(project["permissions"]["deny"]) - set(lean.get("permissions", {}).get("deny", []))
    assert not missing, f"lean review settings lack project deny rules: {sorted(missing)}"


def test_script_is_wired_through_the_lib():
    text = AGENT.read_text()
    assert '. "$SCRIPT_DIR/review-lean-lib.sh"' in text
    assert 'review_lean_args "$SCRIPT_DIR"' in text
    # ONE claude line, and it carries both lean inserts: a second copy would bypass the switch.
    assert text.count("$FLEET_CLAUDE -p") == 1, "a second claude line would bypass the switch"
    tpl = template()
    assert "${REVIEW_LEAN_ENV}KIPI_AGENT=pr-reviewer $FLEET_CLAUDE -p --model '$CLAUDE_MODEL'" in tpl
    assert "${REVIEW_LEAN_FLAGS} </dev/null" in tpl
