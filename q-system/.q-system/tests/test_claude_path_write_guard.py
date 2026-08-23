"""claude-path-write-guard must block writes and nothing else.

Pins the reader-stage fixes for sp-54b02aa0 (read-only find enumerations, the
layer2_blind false trigger from a bare `q-system` token) and sp-1d4ca360
(`.claude-plugin/` is not `.claude/`; substring matching over-blocked the
plugin-version-bump gate's own required edit).

Every case drives the guard through its REAL stdin contract (hook payload in,
exit 2 on block), so a refactor of internals cannot silently invalidate the
pin. Run: python3 test_claude_path_write_guard.py  (also pytest-discoverable).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUARD = HERE.parent / "scripts" / "claude-path-write-guard.py"
CWD = str(HERE.parent.parent.parent)

# Writes nothing; blocked before the fix (sp-54b02aa0 case 1).
READ_FIND_UNDER_CLAUDE = "find .claude/skills -name SKILL.md -maxdepth 2"

# Writes nothing. The bare `q-system` token used to flip layer2_blind via
# baseline containment, then the glob operand hit the unreadable-literal rule
# (sp-54b02aa0 case 3).
FIND_GLOB_QSYSTEM = (
    "find q-system plugins -name validate-separation.py "
    "-not -path '*__pycache__*'"
)

# The plugin-version-bump gate REQUIRES this edit; `.claude-plugin` is not
# `.claude` (sp-1d4ca360).
SED_CLAUDE_PLUGIN = (
    "sed -i '' 's/1.7.18/1.7.19/' "
    "plugins/kipi-core/.claude-plugin/plugin.json"
)

CONTROLS = [
    ("touch .claude/_probe.txt",
     "plain write into .claude"),
    ("find .claude/skills -name old.md -delete",
     "find -delete under .claude"),
    ("sed -i '' 's/a/b/' .claude/settings.json",
     "sed -i on a .claude file"),
    ("awk '{print > \".claude/x.txt\"}' foo.txt",
     "awk redirect target inside .claude"),
    # sp-50db1764's lesson applies to gates too: a control that cannot fail
    # proves nothing. These two keep the fix from eating pinned history.
    ("sed -n 'w .claude/x.txt' foo.txt",
     "sed w-target hidden in program text"),
    ("find .claude -fls /tmp/out.txt",
     "find -fls writes its hit list to a file"),
]

ROUND9_PHASE1 = (
    "P=.claude; V=P; touch ${!V}/rules/pwn.md; "
    "python3 q-system/.q-system/scripts/claude-integrity-tripwire.py --baseline"
)


def run_guard(command):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command},
                          "cwd": CWD})
    p = subprocess.run([sys.executable, str(GUARD)], input=payload,
                       capture_output=True, text=True)
    return p.returncode


def test_reader_find_enumerations_pass():
    assert run_guard(READ_FIND_UNDER_CLAUDE) == 0
    assert run_guard(FIND_GLOB_QSYSTEM) == 0


def test_claude_plugin_edit_passes():
    assert run_guard(SED_CLAUDE_PLUGIN) == 0


def test_write_controls_still_block():
    for cmd, name in CONTROLS:
        rc = run_guard(cmd)
        assert rc == 2, f"{name} must stay BLOCKED, got rc={rc}: {cmd}"


def test_round9_hidden_tail_plus_rebaseline_still_blocks():
    assert run_guard(ROUND9_PHASE1) == 2, (
        "hidden-tail expansion + same-command rebaseline is the round-9 "
        "blocker shape; the component-boundary matcher must not eat it")


if __name__ == "__main__":
    test_reader_find_enumerations_pass()
    test_claude_plugin_edit_passes()
    test_write_controls_still_block()
    test_round9_hidden_tail_plus_rebaseline_still_blocks()
    print("claude-path-write-guard tests: PASS")
