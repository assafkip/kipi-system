#!/usr/bin/env bash
# Required check for kipi-settings-merge.py (extracted from kipi-update.sh).
# Scar 2026-07-02: the inline merge deduped hooks by EXACT command string, so a
# template command-form change (token-guard `|| true` -> if-then) left BOTH
# forms in every instance — token-guard ran twice per tool call and all its
# counters doubled (50-call ceiling behaved as 25). Observed live in
# school-negotiator: 3 token-guard commands per event (current, prior form,
# pre-flattening `q-system/q-system/` fossil). This test proves the merge
# retires stale variants of the same script while instance-added hooks survive.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
# Ref hatch: SETTINGS_MERGE=<mutated merge, kipi-retired-hooks.json beside it> shows the guard cases red.
MERGE="${SETTINGS_MERGE:-$REPO_ROOT/kipi-settings-merge.py}"
# Skeleton-only harness: instances receive this test via sync but not the
# merge script (repo-root files do not propagate). No-op there.
[ -f "$MERGE" ] || { echo "SKIP: kipi-settings-merge.py absent (instance)"; exit 0; }

FIXTURE="$(mktemp -d)"
trap 'python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$FIXTURE"' EXIT

cat > "$FIXTURE/template.json" <<'EOF'
{
  "permissions": {"allow": ["Bash(ls:*)"]},
  "hooks": {
    "PreToolUse": [
      {"matcher": ".*", "hooks": [
        {"type": "command", "command": "if [ -f \"$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py\" ]; then python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py\"; fi", "timeout": 5}
      ]}
    ]
  }
}
EOF

cat > "$FIXTURE/instance.json" <<'EOF'
{
  "mcpServers": {"custom-server": {"command": "npx custom"}},
  "permissions": {"allow": ["Bash(instance-only:*)"]},
  "hooks": {
    "PreToolUse": [
      {"matcher": ".*", "hooks": [
        {"type": "command", "command": "test -f \"$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py\" && python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py\" || true", "timeout": 5},
        {"type": "command", "command": "test -f \"$CLAUDE_PROJECT_DIR/q-system/q-system/.q-system/token-guard.py\" && python3 \"$CLAUDE_PROJECT_DIR/q-system/q-system/.q-system/token-guard.py\" || true", "timeout": 5},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/instance-custom-gate.py\"", "timeout": 5}
      ]}
    ],
    "UserPromptSubmit": [
      {"hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/memory-scores-surface.py\" 2>/dev/null || true"},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/instance-live-surface.py\" 2>/dev/null || true"},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/chained-live-guard.py\"; python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/memory-scores-surface.py\" || true"}
      ]}
    ],
    "Stop": [
      {"hooks": [
        {"type": "command", "command": "test -f \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/memory_autocapture.py\" && python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/memory_autocapture.py\" 2>/dev/null || true", "async": true}
      ]}
    ]
  }
}
EOF

python3 "$MERGE" "$FIXTURE/template.json" "$FIXTURE/instance.json" >/dev/null

python3 - "$FIXTURE/instance.json" "$REPO_ROOT/settings-template.json" "$REPO_ROOT/kipi-retired-hooks.json" <<'EOF'
import json, sys
merged = json.load(open(sys.argv[1]))
cmds = [h["command"]
        for g in merged["hooks"]["PreToolUse"]
        for h in g["hooks"]]

tg = [c for c in cmds if "token-guard.py" in c]
assert len(tg) == 1, f"expected exactly 1 token-guard wiring after merge, got {len(tg)}: {tg}"
assert tg[0].startswith("if [ -f"), f"template's current form must win, got: {tg[0][:60]}"
assert "|| true" not in tg[0], "stale swallow form survived the merge"

assert any("instance-custom-gate.py" in c for c in cmds), \
    "instance-added hook for a script the template does not know must survive"

# ASK-3512: the union keeps every instance-only hook, so hooks RETIRED from the
# template (#571: memory_autocapture, memory-scores-surface) lived on in every
# instance as inert test -f wiring no check could tell from live wiring. The
# retired list is data (kipi-retired-hooks.json), dropped from the INSTANCE side
# only. Negative control: an unlisted live hook must stay.
all_cmds = [h["command"] for ev in merged["hooks"].values() for g in ev for h in g["hooks"]]
for dead in ("memory_autocapture.py", "memory-scores-surface.py"):
    assert not any(dead in c and "chained-live-guard.py" not in c for c in all_cmds), f"retired hook {dead} survived the merge"
assert any("chained-live-guard.py" in c for c in all_cmds), "a live script chained with a retired one was dropped"
# Review minor: a retired script still wired in the template makes the list a silent no-op.
tpl = open(sys.argv[2]).read()
for e in json.load(open(sys.argv[3]))["scripts"]:
    assert e["script"] not in tpl, f"{e['script']} is on the retired list but still wired in settings-template.json"
assert any("instance-live-surface.py" in c for c in all_cmds), \
    "live instance hook not on the retired list was dropped"
assert all(g["hooks"] for ev in merged["hooks"].values() for g in ev), \
    "empty hook group left behind after retiring its only hook"

assert "custom-server" in merged.get("mcpServers", {}), "instance mcpServers dropped"
assert "Bash(instance-only:*)" in merged["permissions"]["allow"], "instance permission dropped"
assert "Bash(ls:*)" in merged["permissions"]["allow"], "template permission dropped"
EOF
echo "ok: stale token-guard variants retired, template form wins, instance hooks/MCP/permissions survive"

# ASK-3685: apply-claude-changes now lets an instance wire its OWN hooks in
# .claude/settings.json, on the premise that this merge keeps them. Codex review
# of PR #615 showed the premise held only by luck: identity was the BASENAME
# alone, so an instance script that happened to share a name with a template
# script (or with a retired one) was deduped or retired away on the next update.
# A script outside the q-system/ subtree is the instance's own, so it is keyed
# by its path instead. Template hooks all live under q-system/ and keep their
# basename identity, so the token-guard fossil dedup above is unchanged.
cat > "$FIXTURE/template2.json" <<'EOF'
{
  "hooks": {
    "PreToolUse": [
      {"matcher": ".*", "hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py\""}
      ]}
    ]
  }
}
EOF
cat > "$FIXTURE/instance2.json" <<'EOF'
{
  "hooks": {
    "PreToolUse": [
      {"matcher": ".*", "hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py\""},
        {"type": "command", "command": "if test -f \"$CLAUDE_PROJECT_DIR/q-inst/token-guard.py\"; then python3 \"$CLAUDE_PROJECT_DIR/q-inst/token-guard.py\"; fi"}
      ]}
    ],
    "Stop": [
      {"hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-inst/memory_autocapture.py\""},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/memory_autocapture.py\""}
      ]}
    ]
  }
}
EOF
python3 "$MERGE" "$FIXTURE/template2.json" "$FIXTURE/instance2.json" >/dev/null
python3 - "$FIXTURE/instance2.json" <<'EOF'
import json, sys
merged = json.load(open(sys.argv[1]))
all_cmds = [h["command"] for ev in merged["hooks"].values() for g in ev for h in g["hooks"]]
assert any("q-inst/token-guard.py" in c for c in all_cmds), \
    "an instance-owned script sharing a template basename was deduped away"
assert sum("q-system/.q-system/token-guard.py" in c for c in all_cmds) == 1, \
    "the template token-guard must stay exactly once"
assert any("q-inst/memory_autocapture.py" in c for c in all_cmds), \
    "an instance-owned script sharing a retired basename was retired away"
assert not any("q-system/.q-system/scripts/memory_autocapture.py" in c for c in all_cmds), \
    "the retired skeleton script must still be dropped"
EOF
echo "ok: instance-owned scripts keep their hooks even when a basename collides"

# Codex round 2 on PR #615, two spellings that defeated a substring test:
#  - "q-system/" deeper in an INSTANCE path still made it skeleton-owned;
#  - a quote between directory and file name hid the q-system/ prefix, so a
#    template script read as an instance path and ran twice (the doubled
#    token-guard scar) or escaped retirement.
# Ownership is now the leading component of the project-relative path, read
# after shell quotes are removed. Anything not provably project-relative keeps
# the old basename identity, so an unknown spelling fails toward dedup.
cat > "$FIXTURE/instance3.json" <<'EOF'
{
  "hooks": {
    "PreToolUse": [
      {"matcher": ".*", "hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system\"/token-guard.py"},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/Q-SYSTEM/.q-system/token-guard.py\""},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-inst/not-q-system/token-guard.py\""}
      ]}
    ],
    "Stop": [
      {"hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts\"/memory_autocapture.py"}
      ]}
    ]
  }
}
EOF
python3 "$MERGE" "$FIXTURE/template2.json" "$FIXTURE/instance3.json" >/dev/null
python3 - "$FIXTURE/instance3.json" <<'EOF'
import json, sys
merged = json.load(open(sys.argv[1]))
all_cmds = [h["command"] for ev in merged["hooks"].values() for g in ev for h in g["hooks"]]
assert any("q-inst/not-q-system/token-guard.py" in c for c in all_cmds), \
    "an instance path containing q-system/ deeper down was deduped away"
skel = [c for c in all_cmds if "token-guard.py" in c and "q-inst/" not in c]
assert len(skel) == 1, f"template token-guard must run once, got {len(skel)}: {skel}"
assert not any("memory_autocapture.py" in c for c in all_cmds), \
    "a quoted spelling of a retired skeleton script escaped retirement"
EOF
echo "ok: ownership reads the leading path component, after shell quotes"

# Codex round 3 on PR #615: `cd "$CLAUDE_PROJECT_DIR/q-system" && python3
# .q-system/token-guard.py` read as the instance path .q-system/token-guard.py,
# so the template guard ran twice. Rounds 1 to 3 each closed one shell spelling
# and the next review found another (RCA
# rca-settings-merge-identity-three-rounds-2026-11-06), so this pins a NARROWER
# grammar, not a fourth spelling: path identity only for the one form all 17
# live path-identity hooks in the fleet use (measured over 14 instances,
# 2026-11-06). Every other spelling keeps basename identity: fails toward dedup.
cat > "$FIXTURE/instance4.json" <<'EOF'
{
  "hooks": {
    "PreToolUse": [
      {"matcher": ".*", "hooks": [
        {"type": "command", "command": "cd \"$CLAUDE_PROJECT_DIR/q-system\" && python3 .q-system/token-guard.py"}
      ]}
    ]
  }
}
EOF
python3 "$MERGE" "$FIXTURE/template2.json" "$FIXTURE/instance4.json" >/dev/null
python3 - "$FIXTURE/instance4.json" <<'EOF'
import json, sys
merged = json.load(open(sys.argv[1]))
all_cmds = [h["command"] for ev in merged["hooks"].values() for g in ev for h in g["hooks"]]
tg = [c for c in all_cmds if "token-guard.py" in c]
assert len(tg) == 1, f"a cd-relative spelling of the template token-guard ran as a second guard: {tg}"
EOF
echo "ok: a cd-relative spelling of a template script dedupes (codex round 3)"

# Codex round 4 on PR #615, the other direction: a CANONICAL instance hook lost
# its path identity and was dropped. The file-name pattern had no dots, so
# custom.memory_autocapture.py read as the retired memory_autocapture.py; and a
# `.` ARGUMENT read as the source builtin, so the hook deduped against the
# template's token-guard.
cat > "$FIXTURE/instance5.json" <<'EOF'
{
  "hooks": {
    "PreToolUse": [
      {"matcher": ".*", "hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py\""},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-inst/token-guard.py\" ."}
      ]}
    ],
    "Stop": [
      {"hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-inst/custom.memory_autocapture.py\""},
        {"type": "command", "command": "cd \"$CLAUDE_PROJECT_DIR\" && python3 \"$CLAUDE_PROJECT_DIR/automation/memory_autocapture.py\""}
      ]}
    ]
  }
}
EOF
python3 "$MERGE" "$FIXTURE/template2.json" "$FIXTURE/instance5.json" >/dev/null
python3 - "$FIXTURE/instance5.json" <<'EOF'
import json, sys
merged = json.load(open(sys.argv[1]))
all_cmds = [h["command"] for ev in merged["hooks"].values() for g in ev for h in g["hooks"]]
assert any("q-inst/token-guard.py" in c for c in all_cmds), \
    "a canonical instance hook with a '.' argument was deduped away"
assert sum("q-system/.q-system/token-guard.py" in c for c in all_cmds) == 1, \
    "the template token-guard must stay exactly once"
assert any("q-inst/custom.memory_autocapture.py" in c for c in all_cmds), \
    "a dotted instance file name was read as a retired basename and dropped"
# Fleet review 2 on PR #615: a `cd` cannot change what an ANCHORED path names
# (it is absolute), so refusing cd protected nothing and deleted this instance
# hook as the retired memory_autocapture.py.
assert any(c.startswith("cd ") and "automation/memory_autocapture.py" in c for c in all_cmds), \
    "a cd in front of an anchored instance path dropped the hook as a retired basename"
EOF
echo "ok: canonical instance hooks keep identity with a dotted name, a '.' argument or a cd (codex round 4, fleet review 2)"

# ASK-3876 (fleet reviewer, PR #615 round 1): a command outside the canonical
# grammar keeps BASENAME identity, so an instance's own script that shares a
# retired name was deleted by the retired-hook drop, with nothing printed. That
# drop runs before the union and ignores event and matcher, so nothing replaced
# the hook. A retired hook is now dropped only in the canonical spelling under
# q-system/, the one every template spelling of a retired script ever used;
# anything else is kept and named on stdout, the stream the updater shows. A
# dedup drop of such a spelling is named too, never silent.
# Codex round 1 on PR #624: the first fix read q-system/ off ANY spelling, so
# `cd automation && python3 q-system/memory_autocapture.py`, which runs the
# instance's automation/q-system/ script, was still deleted. A relative path
# names whatever the working directory says, so it is kept and named.
cat > "$FIXTURE/instance6.json" <<'EOF'
{
  "hooks": {
    "PreToolUse": [
      {"matcher": ".*", "hooks": [
        {"type": "command", "command": "python3 automation/token-guard.py"},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/q-system/.q-system/token-guard.py\""}
      ]}
    ],
    "Stop": [
      {"hooks": [
        {"type": "command", "command": "eval true && python3 \"$CLAUDE_PROJECT_DIR/automation/memory_autocapture.py\""},
        {"type": "command", "command": "python3 automation/memory-scores-surface.py"},
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/memory_autocapture.py\""},
        {"type": "command", "command": "test -f \"$CLAUDE_PROJECT_DIR/q-system/q-system/.q-system/scripts/memory-scores-surface.py\" && python3 \"$CLAUDE_PROJECT_DIR/q-system/q-system/.q-system/scripts/memory-scores-surface.py\" || true"}
      ]}
    ],
    "Notification": [
      {"hooks": [
        {"type": "command", "command": "cd automation && python3 q-system/memory_autocapture.py"}
      ]}
    ],
    "SubagentStop": [
      {"hooks": [
        {"type": "command", "command": "python3 q-system/.q-system/scripts/memory_autocapture.py"}
      ]}
    ],
    "SessionStart": [
      {"hooks": [
        {"type": "command", "command": "python3 memory_autocapture.py --session"}
      ]}
    ],
    "PreCompact": [
      {"hooks": [
        {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/Q-SYSTEM/memory_autocapture.py\""}
      ]}
    ]
  }
}
EOF
OUT6="$(python3 "$MERGE" "$FIXTURE/template2.json" "$FIXTURE/instance6.json")"
python3 - "$FIXTURE/instance6.json" "$OUT6" <<'EOF'
import json, sys
merged = json.load(open(sys.argv[1]))
report = sys.argv[2]
all_cmds = [h["command"] for ev in merged["hooks"].values() for g in ev for h in g["hooks"]]
kept = ['eval true && python3 "$CLAUDE_PROJECT_DIR/automation/memory_autocapture.py"',
        'python3 automation/memory-scores-surface.py',
        'cd automation && python3 q-system/memory_autocapture.py',
        'python3 q-system/.q-system/scripts/memory_autocapture.py',
        'python3 memory_autocapture.py --session',
        # Codex round 2 on PR #624: on a case-sensitive file system Q-SYSTEM/ is
        # not the skeleton's subtree, so case is kept when reading the evidence
        'python3 "$CLAUDE_PROJECT_DIR/Q-SYSTEM/memory_autocapture.py"']
for cmd in kept:
    assert cmd in all_cmds, \
        "a retired-name hook outside the canonical q-system/ spelling was deleted: " + cmd
    assert any(cmd in line and "KEPT" in line for line in report.splitlines()), \
        "a kept retired-name hook was not named on stdout: " + cmd
for fossil in ('python3 "$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/memory_autocapture.py"',
               'test -f "$CLAUDE_PROJECT_DIR/q-system/q-system/.q-system/scripts/memory-scores-surface.py"'):
    assert not any(c.startswith(fossil) for c in all_cmds), \
        "a canonical q-system/ fossil of a retired script survived: " + fossil
# Dedup is unchanged: the template's token-guard runs once. The drop of a
# spelling that does not show it is the skeleton's is named; a fossil is not.
tg = [c for c in all_cmds if "token-guard.py" in c]
assert tg == ['python3 "$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py"'], tg
assert any("automation/token-guard.py" in line and "DROPPED" in line for line in report.splitlines()), \
    "a dedup drop of a non-canonical hook was silent"
assert "q-system/q-system" not in report, "a fossil drop was reported: the report would be noise"
EOF
echo "ok: retired names are dropped only in the canonical q-system/ spelling; every other spelling is kept and named (ASK-3876)"

# Every instance carries the template's for-loop guard verbatim. It is not in the
# canonical spelling, so a report keyed on spelling alone named its drop in all
# 14 instances on every run (measured 2026-11-07). An exact copy of a kept hook
# loses nothing and must stay quiet, or the report is noise nobody reads.
python3 - "$REPO_ROOT/settings-template.json" "$FIXTURE/instance7.json" <<'EOF'
import json, sys
t = json.load(open(sys.argv[1]))
loop = [(ev, g.get("matcher", ""), h) for ev, gs in t["hooks"].items() for g in gs
        for h in g["hooks"] if h.get("command", "").startswith("for R in ")]
assert loop, "the template no longer carries the for-loop guard this case copies"
ev, matcher, hook = loop[0]
json.dump({"hooks": {ev: [{"matcher": matcher, "hooks": [hook]}]}}, open(sys.argv[2], "w"))
EOF
OUT7="$(python3 "$MERGE" "$REPO_ROOT/settings-template.json" "$FIXTURE/instance7.json")"
case "$OUT7" in
  *DROPPED*) echo "FAIL: an exact copy of a template hook was reported as dropped: $OUT7" >&2; exit 1 ;;
esac
echo "ok: an exact copy of a kept hook drops quietly (ASK-3876)"

python3 - "$MERGE" <<'EOF'
import importlib.util, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("kipi_settings_merge", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
# The canonical form keeps path identity. The first three are the hooks this PR
# exists to protect (case gate, gate-draft), the rest are live fleet spellings.
keeps_path = {
    'python3 "$CLAUDE_PROJECT_DIR/q-investigate/skills/osint/scripts/case-gate.py"':
        {"path:q-investigate/skills/osint/scripts/case-gate.py"},
    'test -f "${CLAUDE_PROJECT_DIR}/automation/gate_draft_hook.py" && python3 "${CLAUDE_PROJECT_DIR}/automation/gate_draft_hook.py"':
        {"path:automation/gate_draft_hook.py"},
    'if test -f "$CLAUDE_PROJECT_DIR/automation/gate_draft_hook.py"; then python3 "$CLAUDE_PROJECT_DIR/automation/gate_draft_hook.py"; fi':
        {"path:automation/gate_draft_hook.py"},
    'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/autonomous_mode_detector.py" 2>/dev/null || true':
        {"path:.claude/hooks/autonomous_mode_detector.py"},
    'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/run-lint.sh" "$CLAUDE_PROJECT_DIR/q-system/.q-system/scripts/audhd-lint.py"':
        {"path:.claude/hooks/run-lint.sh", "audhd-lint.py"},
    'python3 "$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py"':
        {"token-guard.py"},
    # codex round 4: a builtin's name as an ARGUMENT is not the builtin, and a
    # dotted file name is one name
    'python3 "$CLAUDE_PROJECT_DIR/q-inst/token-guard.py" .':
        {"path:q-inst/token-guard.py"},
    'python3 "$CLAUDE_PROJECT_DIR/q-inst/run.py" eval --mode source --dir cd':
        {"path:q-inst/run.py"},
    'python3 "$CLAUDE_PROJECT_DIR/q-inst/custom.memory_autocapture.py"':
        {"path:q-inst/custom.memory_autocapture.py"},
    # fleet review 2: an anchored path is absolute, so moving the working
    # directory does not change what it names
    'cd "$CLAUDE_PROJECT_DIR" && python3 "$CLAUDE_PROJECT_DIR/q-inst/token-guard.py"':
        {"path:q-inst/token-guard.py"},
    'pushd "$CLAUDE_PROJECT_DIR" >/dev/null; python3 "$CLAUDE_PROJECT_DIR/q-inst/token-guard.py"':
        {"path:q-inst/token-guard.py"},
    'if cd "$CLAUDE_PROJECT_DIR"; then python3 "$CLAUDE_PROJECT_DIR/q-inst/token-guard.py"; fi':
        {"path:q-inst/token-guard.py"},
}
# Outside the grammar: basename identity, whatever the path seems to say.
basename_only = [
    # round 3 itself, and the bare-relative branch it exposed (dropped)
    'cd "$CLAUDE_PROJECT_DIR/q-system" && python3 .q-system/token-guard.py',
    'python3 q-inst/token-guard.py',
    'python3 ./q-inst/token-guard.py',
    # code the merge cannot read (a sourced file, an eval) can repoint the
    # anchor, wherever the builtin is the command name: after a reserved word,
    # an assignment, a redirection, or the builtin/command wrappers
    'if . "$CLAUDE_PROJECT_DIR/q-inst/env.sh"; then python3 "$CLAUDE_PROJECT_DIR/q-inst/token-guard.py"; fi',
    'X=1 builtin source "$CLAUDE_PROJECT_DIR/q-inst/env.sh" && python3 "$CLAUDE_PROJECT_DIR/q-inst/token-guard.py"',
    '> /dev/null eval "python3 $CLAUDE_PROJECT_DIR/q-inst/token-guard.py"',
    '2>/dev/null command . "$CLAUDE_PROJECT_DIR/q-inst/env.sh"; python3 "$CLAUDE_PROJECT_DIR/q-inst/token-guard.py"',
    'true && { source "$CLAUDE_PROJECT_DIR/q-inst/env.sh"; } && python3 "$CLAUDE_PROJECT_DIR/q-inst/token-guard.py"',
    # a command that rewrites the anchor, or runs text as code in this shell
    'CLAUDE_PROJECT_DIR="$CLAUDE_PROJECT_DIR/q-system"; python3 "$CLAUDE_PROJECT_DIR/.q-system/token-guard.py"',
    'python3 "${CLAUDE_PROJECT_DIR:=/x}/q-inst/token-guard.py"',
    '. "$CLAUDE_PROJECT_DIR/q-inst/env.sh"; python3 "$CLAUDE_PROJECT_DIR/q-inst/token-guard.py"',
    'eval "python3 $CLAUDE_PROJECT_DIR/q-inst/token-guard.py"',
    # the path itself is not plain: a variable, a glob, a doubled slash, an escape
    'python3 "$CLAUDE_PROJECT_DIR/$SUB/token-guard.py"',
    'python3 $CLAUDE_PROJECT_DIR/q-sys*/.q-system/token-guard.py',
    'python3 $CLAUDE_PROJECT_DIR//q-system/.q-system/token-guard.py',
    'python3 "$CLAUDE_PROJECT_DIR/../q-system/.q-system/token-guard.py"',
    r'python3 $CLAUDE_PROJECT_DIR/q-sys\tem/.q-system/token-guard.py',
]
bad = []
for cmd, want in keeps_path.items():
    got = set(m.hook_script_names(cmd))
    if got != want:
        bad.append(f"KEEP {cmd!r}: got {sorted(got)}, want {sorted(want)}")
for cmd in basename_only:
    got = set(m.hook_script_names(cmd))
    if any(i.startswith("path:") for i in got):
        bad.append(f"BASENAME {cmd!r}: got {sorted(got)}")
assert not bad, "hook identity grammar:\n  " + "\n  ".join(bad)
EOF
echo "ok: path identity only for the canonical \$CLAUDE_PROJECT_DIR/<plain path> form"

# ASK-3879: the merge gives path identity to an anchored path that does not lead
# with q-system/, which is safe only while EVERY template hook script lives under
# q-system/. A template script anywhere else would stop deduping against its own
# fossils in instances (the 2026-07-02 doubled token-guard scar) and could never
# be retired through kipi-retired-hooks.json, whose entries are basenames (the
# ASK-3512 scar). Nothing checked the premise, so this pins it on the real
# template, and first proves the check fires on a copy that breaks it.
python3 - "$MERGE" "$REPO_ROOT/settings-template.json" <<'EOF'
import importlib.util, json, os, re, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("kipi_settings_merge", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ANCHOR = re.compile(r"(?:\$CLAUDE_PROJECT_DIR|\$\{CLAUDE_PROJECT_DIR\})/")

def misplaced(template):
    """(script references read, the ones not under q-system/, path identities).

    Read with the merge's own pattern, after its quote removal. The path is what
    follows the LAST anchor in the token, because one live template hook spells
    its script inside a default expansion, N=${KIPI_NOTIFY:-$CLAUDE_PROJECT_DIR/...}.
    """
    refs, outside, path_ids = 0, [], []
    for event, groups in template.get("hooks", {}).items():
        for group in groups:
            for hook in group.get("hooks", []):
                cmd = hook.get("command", "")
                for prefix, name in m.SCRIPT_PATH_RE.findall(cmd.translate(m._SHELL_QUOTING)):
                    refs += 1
                    rel = os.path.normpath(ANCHOR.split(prefix + name)[-1])
                    if rel.split("/", 1)[0] != "q-system":
                        outside.append("%s: %s%s" % (event, prefix, name))
                path_ids += [i for i in m.hook_script_names(cmd) if i.startswith("path:")]
    return refs, outside, path_ids

template = json.load(open(sys.argv[2]))
# Negative self-test: move one template script out of q-system/ in a COPY and
# the check must name it, both as a misplaced path and as a path identity.
broken = json.loads(json.dumps(template))
first = next(h for gs in broken["hooks"].values() for g in gs for h in g["hooks"]
             if "/q-system/" in h.get("command", ""))
first["command"] = first["command"].replace("/q-system/", "/automation/", 1)
_, outside, path_ids = misplaced(broken)
assert outside and path_ids, "the q-system/ check cannot fail: it missed a moved script"

refs, outside, path_ids = misplaced(template)
assert refs > 0, "read no script references in settings-template.json"
assert not outside, "template hook scripts outside q-system/:\n  " + "\n  ".join(outside)
assert not path_ids, "template hooks the merge keys by path: %s" % sorted(set(path_ids))
print("ok: all %d template hook script references lead with q-system/" % refs)
EOF

# ASK-4249 (voicegate K1a): an instance PostToolUse gate whose script is missing
# is a silent no-op under the usual `if test -f ...; then ...; fi` wrapper, so the
# gate stops gating and nothing says so. The fix is ADDITIVE: a separate entry in
# the same event and matcher, `test -f X || { echo ...; exit 2; }`, that fails
# loud. It only works if the merge keeps it beside the gate's own hook. Scar: the
# merge keys hooks by the script they invoke, so a guard spelled like the hook
# reads as a duplicate and is dropped. The braces make this spelling a distinct
# key; the bare `[ -f X ] || exit 2` form does not, and is the negative control.
cat > "$FIXTURE/template4.json" <<'EOF'
{"hooks": {"PreToolUse": [{"matcher": ".*", "hooks": [
  {"type": "command", "command": "python3 \"$CLAUDE_PROJECT_DIR/q-system/.q-system/token-guard.py\""}]}]}}
EOF
cat > "$FIXTURE/instance4.json" <<'EOF'
{"hooks": {"PostToolUse": [{"matcher": "Edit|Write", "hooks": [
  {"type": "command", "command": "if test -f \"$CLAUDE_PROJECT_DIR/q-inst/voice-gate.py\"; then python3 \"$CLAUDE_PROJECT_DIR/q-inst/voice-gate.py\"; fi"},
  {"type": "command", "command": "test -f \"$CLAUDE_PROJECT_DIR/q-inst/voice-gate.py\" || { echo \"voice-gate.py missing: the gate cannot run\" >&2; exit 2; }"}]}]}}
EOF
cp "$FIXTURE/instance4.json" "$FIXTURE/instance4-bare.json"
python3 - "$FIXTURE/instance4-bare.json" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
d["hooks"]["PostToolUse"][0]["hooks"][1]["command"] = '[ -f "$CLAUDE_PROJECT_DIR/q-inst/voice-gate.py" ] || exit 2'
json.dump(d, open(sys.argv[1], "w"))
EOF
OUT1=$(python3 "$MERGE" "$FIXTURE/template4.json" "$FIXTURE/instance4.json")
OUT2=$(python3 "$MERGE" "$FIXTURE/template4.json" "$FIXTURE/instance4.json")
OUTB=$(python3 "$MERGE" "$FIXTURE/template4.json" "$FIXTURE/instance4-bare.json")
python3 - "$FIXTURE/instance4.json" "$FIXTURE/instance4-bare.json" "$OUT1$OUT2" "$OUTB" <<'EOF'
import json, sys
def post(p):
    d = json.load(open(p))["hooks"]["PostToolUse"]
    assert len(d) == 1 and d[0]["matcher"] == "Edit|Write", "guard must stay in the gate's own event and matcher"
    return [h["command"] for h in d[0]["hooks"]]
kept = post(sys.argv[1])
assert len(kept) == 2, f"guard beside the gate hook did not survive two merges: {kept}"
assert any(c.startswith("if test -f") for c in kept), "the gate's own hook was lost"
assert any('|| { echo "voice-gate.py missing: the gate cannot run" >&2; exit 2; }' in c for c in kept), "the exit-2 guard was lost"
assert "DROPPED" not in sys.argv[3], f"merge reported a drop for the guard: {sys.argv[3]}"
# Negative self-test: the bare form is a duplicate by key and IS dropped, with a
# DROPPED line. Without this, the survival check above could not tell a merge
# that keeps everything from one that keeps the guard.
bare = post(sys.argv[2])
assert len(bare) == 1, f"bare [ -f ] guard should have been dropped as a duplicate: {bare}"
assert "DROPPED" in sys.argv[4] and "|| exit 2" in sys.argv[4], f"the drop was not reported: {sys.argv[4]}"
EOF
echo "ok: exit-2 existence guard survives the merge twice; the bare [ -f ] form is dropped and reported"

# Shell contract of the guard itself, on a temp tree: exit 2 with its message
# on stderr when the script is missing, exit 0 when present. Run through bash -c
# as the harness runs a hook command, with CLAUDE_PROJECT_DIR pointing at the tree.
GUARD=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['hooks']['PostToolUse'][0]['hooks'][1]['command'])" "$FIXTURE/instance4.json")
GT="$FIXTURE/guard-tree"; mkdir -p "$GT/q-inst"
set +e
GERR=$(CLAUDE_PROJECT_DIR="$GT" bash -c "$GUARD" 2>&1 >/dev/null); GRC=$?
set -e
[ "$GRC" = 2 ] || { echo "FAIL: guard exited $GRC with the script missing, wanted 2"; exit 1; }
case "$GERR" in *"voice-gate.py missing: the gate cannot run"*) ;; *) echo "FAIL: guard stderr lacks its message: $GERR"; exit 1;; esac
echo "print('gate')" > "$GT/q-inst/voice-gate.py"
set +e
CLAUDE_PROJECT_DIR="$GT" bash -c "$GUARD" >/dev/null 2>&1; GRC=$?
set -e
[ "$GRC" = 0 ] || { echo "FAIL: guard exited $GRC with the script present, wanted 0"; exit 1; }
echo "ok: guard exits 2 with its message when the script is missing, 0 when present"

# Scope: the guard is for a gate that runs AFTER the action. Wired under a
# PreToolUse event the same entry would block the very edit that restores the
# script, which is the lesson a-hook-that-fails-closed-on-a-missing-script-blocks-the-fix-too.
python3 - "$FIXTURE/instance4.json" <<'EOF'
import json, sys
events = [e for e, gs in json.load(open(sys.argv[1]))["hooks"].items()
          for g in gs for h in g["hooks"] if "exit 2" in h["command"]]
assert events == ["PostToolUse"], f"the exit-2 guard must be PostToolUse only, found {events}"
EOF
echo "ok: the exit-2 guard is scoped to PostToolUse"

echo "PASS: kipi-settings-merge dedupes hooks by invoked script, not raw command string"
