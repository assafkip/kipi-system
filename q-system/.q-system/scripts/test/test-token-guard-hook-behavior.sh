#!/usr/bin/env bash
# Required checks for the token-guard hook fixes (hooks review 2026-07-02).
# Scar 1: warn() printed top-level {"additionalContext": ...} from PreToolUse,
#   which Claude Code IGNORES (contract: nested hookSpecificOutput with
#   hookEventName). Every warning tier was silent; the guard went from zero
#   feedback straight to exit-2 hard blocks.
# Scar 2: the PostToolUse leg (successful-edit spiral reset, commit reset
#   "Wiring A") existed in the script but was wired in no settings file, so a
#   3rd successful Edit to one file falsely blocked. This test pins the LEG's
#   behavior; the wiring test pins the settings wiring.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
GUARD="$REPO_ROOT/q-system/.q-system/token-guard.py"
SESSION="tg-behavior-test-$$"
CACHE="/tmp/claude-guard-$SESSION.json"
FIXTURE="$(mktemp -d)"
trap 'rm -f "$CACHE"; python3 -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$FIXTURE"' EXIT

run_guard() { # $1 = event JSON on stdin; guard runs with fixture as project dir
  printf '%s' "$1" | CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$GUARD"
}

run_guard_file() { # $1 = path to a payload JSON file (for payloads with unicode/newlines)
  CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$GUARD" < "$1"
}

# --- 1) warn() output must use the nested PreToolUse hookSpecificOutput form ---
# Seed a cache one read short of the read-spiral threshold; the next Read warns.
python3 - "$CACHE" "$SESSION" <<'EOF'
import json, sys, time
cache = {
    "actor_key": sys.argv[2],
    "tool_calls_since_user": 1,
    "agent_calls_since_user": 0,
    "mcp_timestamps": [],
    "repeat_map": {},
    "consecutive_reads": 14,
    "warnings_issued": 0,
    "file_read_counts": {},
    "greps_since_write": 0,
    "edit_targets": {},
    "agents_without_write": 0,
    "last_write_time": time.time(),
    "calls_since_write": 1,
    "last_volume_reset": time.time(),
}
json.dump(cache, open(sys.argv[1], "w"))
EOF

OUT="$(run_guard "{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PreToolUse\", \"tool_name\": \"Read\", \"tool_input\": {\"file_path\": \"/tmp/spiral-probe\"}}")" \
  || { echo "FAIL: warn path exited non-zero"; exit 1; }
python3 - <<EOF
import json, sys
out = json.loads('''$OUT''')
hso = out.get("hookSpecificOutput")
assert isinstance(hso, dict), f"warn() must nest under hookSpecificOutput, got top-level keys: {list(out)}"
assert hso.get("hookEventName") == "PreToolUse", f"hookEventName wrong: {hso.get('hookEventName')}"
assert hso.get("additionalContext"), "additionalContext missing/empty inside hookSpecificOutput"
assert "additionalContext" not in out, "additionalContext must NOT be top-level (Claude Code ignores it there)"
EOF
echo "ok: warn() emits nested PreToolUse hookSpecificOutput"

# --- 2) PostToolUse leg: a SUCCESSFUL Edit clears that file's spiral counter ---
python3 - "$CACHE" <<'EOF'
import json, sys
cache = json.load(open(sys.argv[1]))
cache["edit_targets"] = {"/tmp/some-file.py": 2}
cache["consecutive_reads"] = 0
json.dump(cache, open(sys.argv[1], "w"))
EOF

run_guard "{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PostToolUse\", \"tool_name\": \"Edit\", \"tool_input\": {\"file_path\": \"/tmp/some-file.py\"}, \"tool_response\": {\"filePath\": \"/tmp/some-file.py\"}}" \
  >/dev/null || { echo "FAIL: PostToolUse leg exited non-zero"; exit 1; }
python3 - "$CACHE" <<'EOF'
import json, sys
cache = json.load(open(sys.argv[1]))
assert "/tmp/some-file.py" not in cache.get("edit_targets", {}), \
    f"successful Edit did not clear edit_targets: {cache.get('edit_targets')}"
EOF
echo "ok: PostToolUse successful Edit clears edit_targets"

# --- 3) PostToolUse leg: a FAILED Edit keeps counting (the real spiral) ---
python3 - "$CACHE" <<'EOF'
import json, sys
cache = json.load(open(sys.argv[1]))
cache["edit_targets"] = {"/tmp/some-file.py": 2}
json.dump(cache, open(sys.argv[1], "w"))
EOF
run_guard "{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PostToolUse\", \"tool_name\": \"Edit\", \"tool_input\": {\"file_path\": \"/tmp/some-file.py\"}, \"tool_response\": \"Error: string not found\"}" \
  >/dev/null || { echo "FAIL: PostToolUse failed-edit path exited non-zero"; exit 1; }
python3 - "$CACHE" <<'EOF'
import json, sys
cache = json.load(open(sys.argv[1]))
assert cache.get("edit_targets", {}).get("/tmp/some-file.py") == 2, \
    f"failed Edit must NOT clear edit_targets: {cache.get('edit_targets')}"
EOF
echo "ok: PostToolUse failed Edit keeps the spiral counter"

# --- 4) A guard-BLOCKED attempt must not escalate into a false exact-retry ---
# Scar 3 (2026-07-02, Pure_spectrum_Q/qep_agent): at the 50-call volume ceiling,
# each blocked Edit still incremented repeat_map; the 3rd blocked retry was
# reported as "attempted this exact call 3 times" for a call that executed
# ZERO times (exact-retry outranks volume in check order). Blocked attempts
# must be un-counted so the block reason stays the true one.
python3 - "$CACHE" "$SESSION" <<'EOF'
import json, sys, time
cache = {
    "actor_key": sys.argv[2],
    "tool_calls_since_user": 50,
    "agent_calls_since_user": 0,
    "mcp_timestamps": [],
    "repeat_map": {},
    "consecutive_reads": 0,
    "warnings_issued": 1,
    "file_read_counts": {},
    "greps_since_write": 0,
    "edit_targets": {},
    "agents_without_write": 0,
    "last_write_time": time.time(),
    "calls_since_write": 1,
    "last_volume_reset": time.time(),
}
json.dump(cache, open(sys.argv[1], "w"))
EOF

CEILING_EDIT="{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PreToolUse\", \"tool_name\": \"Edit\", \"tool_input\": {\"file_path\": \"/tmp/deadlock-probe.py\", \"old_string\": \"a\", \"new_string\": \"b\"}}"
for attempt in 1 2 3; do
  set +e
  ERR="$(printf '%s' "$CEILING_EDIT" | CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$GUARD" 2>&1 >/dev/null)"
  CODE=$?
  set -e
  [ "$CODE" -eq 2 ] || { echo "FAIL: ceiling attempt $attempt exited $CODE, want 2"; exit 1; }
  case "$ERR" in
    *"attempted this exact call"*)
      echo "FAIL: attempt $attempt escalated to false exact-retry: $ERR"; exit 1;;
    *"tool calls"*) ;;
    *) echo "FAIL: attempt $attempt lost the volume message: $ERR"; exit 1;;
  esac
done
python3 - "$CACHE" <<'EOF'
import json, sys
cache = json.load(open(sys.argv[1]))
repeats = [v for v in cache.get("repeat_map", {}).values() if v > 0]
assert not repeats, f"blocked attempts leaked into repeat_map: {cache.get('repeat_map')}"
assert cache.get("edit_targets", {}).get("/tmp/deadlock-probe.py", 0) == 0, \
    f"blocked attempts leaked into edit_targets: {cache.get('edit_targets')}"
EOF
echo "ok: guard-blocked attempts stay volume-blocked and are un-counted"

# --- 5) The volume block must name the commit escape hatch ---
# Same scar: git commit is exempt and resets the ceiling, but the old message
# only said "Stop. Summarize." — so the model retried edits into the deadlock
# instead of committing its 4 finished edits.
case "$ERR" in
  *commit*) echo "ok: volume block names the commit escape hatch";;
  *) echo "FAIL: volume block message does not mention commit: $ERR"; exit 1;;
esac

# --- 6) Exact-retry still fires for identical calls that PASS the guard ---
python3 - "$CACHE" "$SESSION" <<'EOF'
import json, sys, time
cache = json.load(open(sys.argv[1]))
cache.update(tool_calls_since_user=1, repeat_map={}, edit_targets={},
             warnings_issued=0, last_volume_reset=time.time())
json.dump(cache, open(sys.argv[1], "w"))
EOF
REAL_RETRY="{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PreToolUse\", \"tool_name\": \"Bash\", \"tool_input\": {\"command\": \"pytest tests/flaky\"}}"
for attempt in 1 2; do
  printf '%s' "$REAL_RETRY" | CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$GUARD" >/dev/null \
    || { echo "FAIL: allowed attempt $attempt was blocked"; exit 1; }
done
set +e
ERR="$(printf '%s' "$REAL_RETRY" | CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$GUARD" 2>&1 >/dev/null)"
CODE=$?
set -e
[ "$CODE" -eq 2 ] || { echo "FAIL: 3rd executed identical call exited $CODE, want 2"; exit 1; }
case "$ERR" in
  *"attempted this exact call"*) echo "ok: exact-retry still fires for executed identical calls";;
  *) echo "FAIL: 3rd executed identical call blocked with wrong reason: $ERR"; exit 1;;
esac

# --- 7-10) The ceiling's escape hatch must survive a pre-commit gate (ASK-215) --
# Scar 4 (2026-07-27, ASK-214): at the ceiling the ONLY exempt call is `git
# commit`. lefthook's plugin-version-bump REFUSED that commit, and bumping
# plugin.json needs an Edit the ceiling blocks. The run stranded with 18/20 tests
# done and everything staged. A refused commit is not a checkpoint, so the
# commit-command exemption alone does not reach the deadlock: the gate's
# PRECONDITION needs a bounded budget of its own.
#
# Fixture is a real lefthook v2.1.6 refusal (captured 2026-07-27). git passes a
# hook's output through verbatim and adds no marker of its own, so the gate name
# can only come from the gate's own text.
mk_payloads() {
python3 - "$FIXTURE" "$SESSION" <<'EOF'
import json, os, sys
fixture, session = sys.argv[1], sys.argv[2]

LEFTHOOK_REFUSAL = (
    "╭──────╮\n"
    "│ \U0001f94a lefthook v2.1.6  hook: pre-commit │\n"
    "╰──────╯\n"
    "┃  gitleaks ❯ \n\nclean\n\n"
    "┃  plugin-version-bump ❯ \n\nBLOCK: bump plugin.json\n\n"
    "exit status 1\n"
    "summary: (done in 0.10 seconds)\n"
    "✔️ gitleaks (0.10 seconds)\n"
    "\U0001f94a plugin-version-bump: A changed plugin must bump its "
    ".claude-plugin/plugin.json version. (0.10 seconds)\n"
)

def write(name, payload):
    with open(os.path.join(fixture, name), "w") as fh:
        json.dump(payload, fh)

def post_commit(response):
    return {"session_id": session, "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'wip (ASK-214)'"},
            "tool_response": response}

write("refused.json", post_commit(
    {"stdout": "", "stderr": LEFTHOOK_REFUSAL, "error": "Exit code 1"}))
write("noop.json", post_commit(
    {"stdout": "On branch main\nnothing to commit, working tree clean",
     "stderr": "", "error": "Exit code 1"}))
write("landed.json", post_commit(
    {"stdout": "[sana/ask-215 abc1234] fix (ASK-215)\n 1 file changed", "stderr": ""}))

# --- Real transient git failures (captured 2026-07-28 by
# q-system/output/capture-git-transient-failures.sh). Every one of these is git
# itself failing at exit 128; a hook refusal is exit 1. They are NOT a gate.
INDEX_LOCK = (
    "fatal: Unable to create '/tmp/repo/.git/index.lock': File exists.\n\n"
    "Another git process seems to be running in this repository, or the lock "
    "file may be stale\n")
REF_LOCK = (
    "fatal: cannot lock ref 'HEAD': Unable to create "
    "'/tmp/repo/.git/refs/heads/main.lock': File exists.\n\n"
    "Another git process seems to be running in this repository, or the lock "
    "file may be stale\n")
GPG_FAIL = (
    "fatal: cannot exec '/usr/bin/gpg': No such file or directory\n"
    "error: gpg failed to sign the data:\n(no gpg output)\n"
    "fatal: failed to write commit object\n")

write("indexlock.json", post_commit(
    {"stdout": "", "stderr": INDEX_LOCK, "error": "Exit code 128"}))
write("reflock.json", post_commit(
    {"stdout": "", "stderr": REF_LOCK, "error": "Exit code 128"}))
write("gpgfail.json", post_commit(
    {"stdout": "", "stderr": GPG_FAIL, "error": "Exit code 128"}))
# A git-self failure whose text is NOT in the phrase list. Only the exit code
# separates it from a gate refusal, so this pins the exit-128 rule on its own.
write("unknown128.json", post_commit(
    {"stdout": "", "stderr": "fatal: a failure mode nobody enumerated\n",
     "error": "Exit code 128"}))

# A failing command that merely MENTIONS the string "git commit" and never
# invokes it. Real producer: a grep over the canonical corpus with no match.
write("mentions.json", {
    "session_id": session, "hook_event_name": "PostToolUse", "tool_name": "Bash",
    "tool_input": {"command": 'grep -rn "git commit" q-system/canonical/'},
    "tool_response": {"stdout": "", "stderr": "", "error": "Exit code 1"}})

# The same lefthook refusal delivered with an integer exit_code and NO error
# key. The Bash response shape is not pinned by contract, so both readers must
# work; without this fixture the exit_code branch is untested.
write("refused_exitcode.json", post_commit(
    {"stdout": "", "stderr": LEFTHOOK_REFUSAL, "exit_code": 1}))
EOF
}
mk_payloads

seed_ceiling() { # reset to a clean at-the-ceiling cache, no grace recorded
python3 - "$CACHE" "$SESSION" <<'EOF'
import json, sys, time
json.dump({
    "actor_key": sys.argv[2], "tool_calls_since_user": 50,
    "agent_calls_since_user": 0, "mcp_timestamps": [], "repeat_map": {},
    "consecutive_reads": 0, "warnings_issued": 1, "file_read_counts": {},
    "greps_since_write": 0, "edit_targets": {}, "agents_without_write": 0,
    "last_write_time": time.time(), "calls_since_write": 1,
    "last_volume_reset": time.time(),
}, open(sys.argv[1], "w"))
EOF
}

# Each probe Edit targets a DISTINCT path so neither the exact-retry hash nor the
# edit-spiral counter fires -- this test is about the volume ceiling only.
ceiling_edit() { # $1 = probe index -> exit code in CODE, stderr in ERR
  local payload
  payload="{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PreToolUse\", \"tool_name\": \"Edit\", \"tool_input\": {\"file_path\": \"/tmp/gate-probe-$1.json\", \"old_string\": \"version-$1\", \"new_string\": \"bumped-$1\"}}"
  set +e
  ERR="$(printf '%s' "$payload" | CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$GUARD" 2>&1 >/dev/null)"
  CODE=$?
  set -e
}

# --- 7) A gate-refused commit grants the remediation budget ------------------
seed_ceiling
run_guard_file "$FIXTURE/refused.json" >/dev/null \
  || { echo "FAIL: PostToolUse gate-refusal leg exited non-zero"; exit 1; }
ceiling_edit 1
[ "$CODE" -eq 0 ] || { echo "FAIL: Edit after a gate-refused commit exited $CODE, want 0 (deadlock): $ERR"; exit 1; }
echo "ok: a gate-refused commit grants a bounded budget so the ceiling is escapable"

# --- 8) A no-op commit must NOT mint budget ---------------------------------
# Otherwise an agent clears the ceiling forever with an empty commit.
seed_ceiling
run_guard_file "$FIXTURE/noop.json" >/dev/null \
  || { echo "FAIL: PostToolUse no-op commit leg exited non-zero"; exit 1; }
ceiling_edit 2
[ "$CODE" -eq 2 ] || { echo "FAIL: 'nothing to commit' minted grace (Edit exited $CODE, want 2)"; exit 1; }
case "$ERR" in
  *"plugin-version-bump"*) echo "FAIL: no-op commit recorded a refusing gate: $ERR"; exit 1;;
  *"tool calls"*) echo "ok: a no-op commit mints no budget; the ceiling still blocks";;
  *) echo "FAIL: no-op path blocked with the wrong reason: $ERR"; exit 1;;
esac

# --- 9) Bounded: the call after the budget is spent blocks, naming the gate --
seed_ceiling
run_guard_file "$FIXTURE/refused.json" >/dev/null
GRACE="$(python3 -c "import re,sys; print(re.search(r'^GATE_GRACE = (\d+)', open(sys.argv[1]).read(), re.M).group(1))" "$GUARD")"
probe=0
while [ "$probe" -lt "$GRACE" ]; do
  probe=$(( probe + 1 ))
  ceiling_edit "9$probe"
  [ "$CODE" -eq 0 ] || { echo "FAIL: grace call $probe/$GRACE blocked early (exit $CODE): $ERR"; exit 1; }
done
ceiling_edit "9over"
[ "$CODE" -eq 2 ] || { echo "FAIL: call $(( GRACE + 1 )) after the grant exited $CODE, want 2 (budget is unbounded)"; exit 1; }
case "$ERR" in
  *plugin-version-bump*) echo "ok: budget is bounded at $GRACE and the hard stop names the refusing gate";;
  *) echo "FAIL: spent-budget block does not name the refusing gate: $ERR"; exit 1;;
esac

# --- 10) A landed commit clears the budget (no stale grace at a later ceiling) --
seed_ceiling
run_guard_file "$FIXTURE/refused.json" >/dev/null
run_guard_file "$FIXTURE/landed.json" >/dev/null \
  || { echo "FAIL: PostToolUse landed-commit leg exited non-zero"; exit 1; }
python3 - "$CACHE" <<'EOF'
import json, sys
cache = json.load(open(sys.argv[1]))
assert cache.get("gate_grace_remaining", 0) == 0, \
    f"a landed commit must clear the grace budget: {cache.get('gate_grace_remaining')}"
assert not cache.get("gate_grace_gate"), \
    f"a landed commit must clear the recorded gate: {cache.get('gate_grace_gate')}"
EOF
echo "ok: a landed commit clears the budget"

# --- 11-15) The classifier must not invent a gate (PR #27 review, round 2) ----
# Scar 5 (2026-07-28): the first cut treated ANY failed commit that dodged a
# short phrase list as a gate refusal. This repo runs a 15-minute auto-committer
# and parallel sessions share a checkout, so an `index.lock` race is a routine
# event -- and it was being reported at 3am as "a pre-commit gate refused the
# checkpoint", after burning the whole budget chasing a gate that did not exist.
# Ground truth (q-system/output/capture-git-transient-failures.sh): git's OWN
# failures exit 128, and git normalises EVERY hook refusal to exit 1 whatever
# the hook returned.

# --- 11) A transient git failure mints no budget and keeps the true message --
for probe in indexlock reflock gpgfail unknown128; do
  seed_ceiling
  run_guard_file "$FIXTURE/$probe.json" >/dev/null \
    || { echo "FAIL: PostToolUse $probe leg exited non-zero"; exit 1; }
  python3 - "$CACHE" "$probe" <<'EOF'
import json, sys
cache = json.load(open(sys.argv[1]))
assert cache.get("gate_grace_remaining", 0) == 0, \
    f"{sys.argv[2]}: a transient git failure minted budget: {cache.get('gate_grace_remaining')}"
assert not cache.get("gate_grace_gate"), \
    f"{sys.argv[2]}: a transient git failure recorded a gate: {cache.get('gate_grace_gate')!r}"
EOF
  ceiling_edit "11$probe"
  [ "$CODE" -eq 2 ] || { echo "FAIL: $probe left the ceiling open (Edit exited $CODE, want 2)"; exit 1; }
  case "$ERR" in
    *"refused the checkpoint"*)
      echo "FAIL: $probe was reported to the operator as a gate refusal: $ERR"; exit 1;;
    *"tool calls"*) ;;
    *) echo "FAIL: $probe blocked with the wrong reason: $ERR"; exit 1;;
  esac
done
echo "ok: a transient git failure (lock/ref-lock/gpg/exit-128) is not read as a gate refusal"

# --- 12) Mentioning "git commit" in a command is not committing ---------------
seed_ceiling
run_guard_file "$FIXTURE/mentions.json" >/dev/null \
  || { echo "FAIL: PostToolUse mentions leg exited non-zero"; exit 1; }
python3 - "$CACHE" <<'EOF'
import json, sys
cache = json.load(open(sys.argv[1]))
assert cache.get("gate_grace_remaining", 0) == 0, \
    f"a failing grep minted grace: {cache.get('gate_grace_remaining')}"
assert not cache.get("gate_grace_gate"), \
    f"a failing grep recorded a refusing gate: {cache.get('gate_grace_gate')!r}"
EOF
ceiling_edit 12
[ "$CODE" -eq 2 ] || { echo "FAIL: a failing grep opened the ceiling (Edit exited $CODE, want 2)"; exit 1; }
case "$ERR" in
  *"refused the checkpoint"*)
    echo "FAIL: a failing grep hijacked the ceiling message: $ERR"; exit 1;;
  *"tool calls"*) echo "ok: a command that only mentions 'git commit' mints no budget";;
  *) echo "FAIL: mentions path blocked with the wrong reason: $ERR"; exit 1;;
esac

# --- 13) The other detectors stay reachable while the budget is being spent ---
# The grace path warns and returns; if it exits there, checks 4-11 never run and
# an agent spiralling on the gate file gets GATE_GRACE unchecked edit attempts
# and never hears "your edit approach is wrong".
seed_ceiling
run_guard_file "$FIXTURE/refused.json" >/dev/null
python3 - "$CACHE" "$GUARD" <<'EOF'
import json, re, sys
limit = int(re.search(r"^EDIT_FAIL_LIMIT = (\d+)", open(sys.argv[2]).read(), re.M).group(1))
cache = json.load(open(sys.argv[1]))
cache["edit_targets"] = {"/tmp/stuck-on-the-gate.py": limit + 5}
json.dump(cache, open(sys.argv[1], "w"))
EOF
SPIRAL_EDIT="{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PreToolUse\", \"tool_name\": \"Edit\", \"tool_input\": {\"file_path\": \"/tmp/stuck-on-the-gate.py\", \"old_string\": \"a\", \"new_string\": \"b\"}}"
set +e
ERR="$(printf '%s' "$SPIRAL_EDIT" | CLAUDECODE=1 CLAUDE_PROJECT_DIR="$FIXTURE" python3 "$GUARD" 2>&1 >/dev/null)"
CODE=$?
set -e
[ "$CODE" -eq 2 ] || { echo "FAIL: edit-spiral is unreachable during the grace budget (exit $CODE, want 2)"; exit 1; }
case "$ERR" in
  *"edit attempts on"*) echo "ok: edit-spiral still blocks while the grace budget is live";;
  *) echo "FAIL: grace budget swallowed the edit-spiral block: $ERR"; exit 1;;
esac

# --- 14) The gate-name reader must not name a detail line of a real gate ------
# Producer is this repo's own commit-msg gate, run for real: its BLOCK line is
# correctly ignored, and the INDENTED "  subject: ..." detail line under it must
# not become the gate's name.
python3 - "$GUARD" <<'EOF'
import importlib.util, os, subprocess, sys, tempfile
spec = importlib.util.spec_from_file_location("tg", sys.argv[1])
tg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tg)
repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(sys.argv[1]))))
gate = os.path.join(repo, "q-system/.q-system/scripts/linear-issue-ref-check.py")
msg = os.path.join(tempfile.mkdtemp(), "msg.txt")
open(msg, "w").write("chore: no issue id here\n")
run = subprocess.run(["python3", gate, msg], capture_output=True, text=True)
assert run.returncode != 0, "the commit-msg gate did not refuse; fixture is stale"
text = run.stdout + run.stderr
name = tg._refusing_gate_name(text)
assert name == "a pre-commit gate", \
    f"gate-name reader took a detail line as the gate name: {name!r}"
EOF
echo "ok: the gate-name reader falls back to the generic label, not a detail line"

# --- 15) The exit_code branch is live (no `error` key in the response) --------
seed_ceiling
run_guard_file "$FIXTURE/refused_exitcode.json" >/dev/null \
  || { echo "FAIL: PostToolUse exit_code-shaped refusal leg exited non-zero"; exit 1; }
python3 - "$CACHE" <<'EOF'
import json, sys
cache = json.load(open(sys.argv[1]))
assert cache.get("gate_grace_remaining", 0) > 0, \
    "a refusal delivered as exit_code (no error key) minted no budget"
assert cache.get("gate_grace_gate") == "plugin-version-bump", \
    f"exit_code-shaped refusal lost the gate name: {cache.get('gate_grace_gate')!r}"
EOF
echo "ok: a refusal carried by exit_code alone is read the same as one carried by error"

# --- 16) Holding the volume warning must not lose it --------------------------
# The finding-3 fix defers the volume warning so the checks below it can run. A
# later warning must therefore CARRY it, not replace it -- otherwise the fix
# buys reachability by making the ceiling warning silent, which is the trade the
# operator would never agree to.
python3 - "$CACHE" "$SESSION" "$GUARD" <<'EOF'
import json, re, sys, time
src = open(sys.argv[3]).read()
warning = int(re.search(r"^VOLUME_WARNING = (\d+)", src, re.M).group(1))
spiral = int(re.search(r"^READ_SPIRAL_LIMIT = (\d+)", src, re.M).group(1))
json.dump({
    "actor_key": sys.argv[2], "tool_calls_since_user": warning,
    "agent_calls_since_user": 0, "mcp_timestamps": [], "repeat_map": {},
    "consecutive_reads": spiral - 1, "warnings_issued": 0, "file_read_counts": {},
    "greps_since_write": 0, "edit_targets": {}, "agents_without_write": 0,
    "last_write_time": time.time(), "calls_since_write": 1,
    "last_volume_reset": time.time(),
}, open(sys.argv[1], "w"))
EOF
OUT="$(run_guard "{\"session_id\": \"$SESSION\", \"hook_event_name\": \"PreToolUse\", \"tool_name\": \"Read\", \"tool_input\": {\"file_path\": \"/tmp/both-warnings-probe\"}}")" \
  || { echo "FAIL: combined-warning path exited non-zero"; exit 1; }
python3 - <<EOF
import json
context = json.loads(r'''$OUT''')["hookSpecificOutput"]["additionalContext"]
volume, _, spiral = context.partition("\n\n")
assert "before hard stop" in volume, \
    f"the held volume warning was dropped by a later warning: {context!r}"
assert spiral.strip(), \
    f"the later read-spiral warning was dropped: {context!r}"
EOF
echo "ok: a held volume warning is carried by the next warning, not replaced"

echo "PASS: token-guard hook behavior (warn shape + PostToolUse edit reset + blocked-attempt un-count + gate-refusal grace + non-gate classifier)"
