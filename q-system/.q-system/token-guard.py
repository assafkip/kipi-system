#!/usr/bin/env python3
"""
Token Bleed Guardrail System
Two-layer defense against runaway token consumption in Claude Code sessions.
Layer 1: Hook-based circuit breaker (this script).
Layer 2: CLAUDE.md + .claude/rules/token-discipline.md (behavioral).

Called by three hooks:
  - PreToolUse: counts tool calls and enforces limits
  - PostToolUse (Edit|Write|MultiEdit|Bash): progress resets (successful edit
    clears that file's spiral counter; successful commit clears the volume
    counters)
  - UserPromptSubmit: resets per-message counters + sweeps stale caches

Per-actor budget scoping (sp0-guard-actor-scope):
  Counters are keyed per ACTOR, not per session. Subagent (Task/workflow)
  tool calls fire hooks with the parent's session_id and transcript_path but
  carry their own `agent_id` field — observed live in
  q-system/output/guard-payload-dump.json (2026-06-11): main-session events
  have no agent_id; each spawned agent's events carry a distinct agent_id.
  Cache key: /tmp/claude-guard-{session_id}.json for the main actor,
  /tmp/claude-guard-{session_id}-agent-{agent_id}.json per subagent. A
  spinning single actor still hits its own ceiling; a fan-out no longer
  burns the orchestrator's budget (and a blocked subagent no longer
  deadlocks the parent).

Commit-progress valve (both wirings):
  A successful `git commit` resets the volume counters — the ceiling gates
  lack-of-progress, not raw volume (founder-approved 2026-06-11). Wiring A:
  PostToolUse on Bash (settings.json matcher includes Bash). Wiring B:
  PreToolUse checks whether the repo HEAD commit is newer than the last
  volume reset — this works even when PostToolUse delivery is missing, and
  takes effect live (the script is re-read every hook fire). The
  empty-commit edge is accepted, not defended (same posture as the
  commit-string volume exemption below).

Exit codes:
  0 = allow (optionally with warning via stdout JSON)
  2 = block (stderr message goes to Claude as feedback)
"""

import hashlib
import json
import os
import re
import shlex
import sys
import time


# --- Thresholds ---
RETRY_LIMIT = 3            # Same tool+input N times = block
VOLUME_CEILING = 50         # Tool calls since last user message = block
VOLUME_WARNING = 35         # Tool calls since last user message = warn
AGENT_CEILING = 30          # Agent spawns per user message = block (morning routine needs ~25)
MCP_RATE_WINDOW = 60        # Seconds
MCP_RATE_LIMIT = 30         # MCP calls in window = block
READ_SPIRAL_LIMIT = 15      # Consecutive reads without write = warn
FILE_REREAD_LIMIT = 3       # Same file path read N times = warn
GREP_DRIFT_LIMIT = 5        # Greps since last write = warn
EDIT_FAIL_LIMIT = 3         # Edit attempts on same file without success = block
AGENT_NO_OUTPUT_LIMIT = 3   # Agent spawns with no write between them = warn
STALL_TIME_SECONDS = 120    # Seconds since last write + calls = warn
STALL_MIN_CALLS = 10        # Minimum calls before time-based stall triggers
GATE_GRACE = 8              # Calls granted at the ceiling to clear a gate that refused the commit
GATE_GRACE_GRANTS = 1       # Grants per user-message window (bounded: no re-arming ratchet)

# Sensitive file patterns
SENSITIVE_PATTERNS = (".env", ".pem", ".key", "credentials")

# Read-only browser/desktop observation tools. Repeating one of these with
# identical input is legitimate polling of a CHANGING screen, not a stuck
# retry — the hash can't see that the page behind it moved. Scar
# (sp-ff7611cd, cole-gtm 2026-07): LinkedIn's compose overlay is not in the
# DOM, so a screenshot is the ONLY way to verify the recipient before
# typing; check_exact_retry blocked the 3rd identical screenshot, the loop
# correctly refused to blind-send, and the DM lane went quiet. Exemption is
# scoped to check_exact_retry ONLY — the volume ceiling still catches a
# genuinely runaway observation loop.
OBSERVATION_TOOLS = frozenset((
    "mcp__computer-use__screenshot",
    "mcp__computer-use__cursor_position",
    "mcp__claude-in-chrome__read_page",
    "mcp__claude-in-chrome__get_page_text",
    "mcp__claude-in-chrome__tabs_context_mcp",
    "mcp__playwright__browser_snapshot",
    "mcp__playwright__browser_take_screenshot",
    "mcp__plugin_chrome-devtools-mcp_chrome-devtools__take_screenshot",
    "mcp__plugin_chrome-devtools-mcp_chrome-devtools__take_snapshot",
))
# Multi-action tools where only the observation action is read-only.
OBSERVATION_ACTIONS = {"mcp__claude-in-chrome__computer": ("screenshot", "zoom")}


def is_readonly_observation(tool_name, tool_input):
    if tool_name in OBSERVATION_TOOLS:
        return True
    actions = OBSERVATION_ACTIONS.get(tool_name)
    if actions:
        return (tool_input or {}).get("action") in actions
    return False


CACHE_TTL_DAYS = 7          # Stale guard caches in /tmp older than this are swept


def actor_cache_key(hook_input):
    """Per-actor cache key. Subagents share the parent's session_id but carry
    their own agent_id (evidence: q-system/output/guard-payload-dump.json) —
    compounding the two gives each actor its own budget. No agent_id = the
    main session actor."""
    session_id = hook_input.get("session_id", "unknown")
    agent_id = hook_input.get("agent_id")
    if agent_id:
        return f"{session_id}-agent-{agent_id}"
    return session_id


def cache_path(actor_key):
    return f"/tmp/claude-guard-{actor_key}.json"


def sweep_stale_caches(max_age_days=CACHE_TTL_DAYS):
    """Delete guard caches older than max_age_days. Runs on UserPromptSubmit
    only (once per user message), so the per-tool-call path stays free of
    directory scans. Subagent caches have no UserPromptSubmit of their own;
    this sweep is their cleanup path."""
    import glob
    cutoff = time.time() - max_age_days * 86400
    for path in glob.glob("/tmp/claude-guard-*.json"):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


def load_cache(actor_key):
    path = cache_path(actor_key)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "actor_key": actor_key,
        "tool_calls_since_user": 0,
        "agent_calls_since_user": 0,
        "mcp_timestamps": [],
        "repeat_map": {},
        "consecutive_reads": 0,
        "warnings_issued": 0,
        "file_read_counts": {},
        "greps_since_write": 0,
        "edit_targets": {},
        "agents_without_write": 0,
        "last_write_time": time.time(),
        "calls_since_write": 0,
        "last_volume_reset": time.time(),
        "gate_grace_remaining": 0,
        "gate_grace_gate": None,
        "gate_grace_grants": 0,
    }


def save_cache(actor_key, cache):
    path = cache_path(actor_key)
    try:
        with open(path, "w") as f:
            json.dump(cache, f)
    except IOError:
        pass


def update_counters(tool_name, tool_input, cache):
    """Update all counters from the current hook invocation."""
    cache["tool_calls_since_user"] = cache.get("tool_calls_since_user", 0) + 1

    # Track agent spawns (per user message)
    if tool_name == "Agent":
        cache["agent_calls_since_user"] = cache.get("agent_calls_since_user", 0) + 1

    # Track exact repeats
    input_hash = hashlib.md5(
        (tool_name + json.dumps(tool_input, sort_keys=True)).encode()
    ).hexdigest()[:12]
    key = f"{tool_name}:{input_hash}"
    repeat_map = cache.get("repeat_map", {})
    repeat_map[key] = repeat_map.get(key, 0) + 1
    cache["repeat_map"] = repeat_map

    # Track consecutive reads vs writes
    if tool_name in ("Read", "Grep", "Glob"):
        cache["consecutive_reads"] = cache.get("consecutive_reads", 0) + 1
    elif tool_name in ("Edit", "Write", "Bash", "Agent"):
        cache["consecutive_reads"] = 0

    # --- Token suck detection ---

    # Track file re-reads
    if tool_name == "Read":
        file_path = tool_input.get("file_path", "")
        if file_path:
            counts = cache.get("file_read_counts", {})
            counts[file_path] = counts.get(file_path, 0) + 1
            cache["file_read_counts"] = counts

    # Track greps since last write
    if tool_name in ("Grep", "Glob"):
        cache["greps_since_write"] = cache.get("greps_since_write", 0) + 1

    # Track edit attempts per file
    if tool_name == "Edit":
        file_path = tool_input.get("file_path", "")
        if file_path:
            targets = cache.get("edit_targets", {})
            targets[file_path] = targets.get(file_path, 0) + 1
            cache["edit_targets"] = targets

    # Track agents without write
    if tool_name == "Agent":
        cache["agents_without_write"] = cache.get("agents_without_write", 0) + 1

    # Track calls since last write + reset write-dependent counters on write
    cache["calls_since_write"] = cache.get("calls_since_write", 0) + 1
    if tool_name in ("Edit", "Write"):
        cache["greps_since_write"] = 0
        cache["agents_without_write"] = 0
        cache["last_write_time"] = time.time()
        cache["calls_since_write"] = 0
    # Only Write resets edit_targets (Edit can't reset its own spiral tracker)
    if tool_name == "Write":
        cache["edit_targets"] = {}

    # Track MCP rate
    if tool_name.startswith("mcp__"):
        now = time.time()
        timestamps = cache.get("mcp_timestamps", [])
        timestamps = [t for t in timestamps if now - t < MCP_RATE_WINDOW]
        timestamps.append(now)
        cache["mcp_timestamps"] = timestamps

    return cache


def check_sensitive_file(tool_name, tool_input):
    """Block edits to sensitive files."""
    if tool_name not in ("Edit", "Write"):
        return None
    file_path = (tool_input.get("file_path", "") or "").lower()
    for pattern in SENSITIVE_PATTERNS:
        if pattern in file_path:
            return f"BLOCK: Attempted to modify sensitive file matching '{pattern}'."
    return None


def check_exact_retry(tool_name, tool_input, cache):
    """Block if same tool+input attempted N times. Read-only observation
    tools are exempt (see OBSERVATION_TOOLS scar): an identical screenshot
    of a changing screen is polling, not retrying."""
    if is_readonly_observation(tool_name, tool_input):
        return None
    input_hash = hashlib.md5(
        (tool_name + json.dumps(tool_input, sort_keys=True)).encode()
    ).hexdigest()[:12]
    key = f"{tool_name}:{input_hash}"
    count = cache.get("repeat_map", {}).get(key, 0)
    if count >= RETRY_LIMIT:
        return f"You've attempted this exact call {count} times. Stop. Diagnose the failure and tell the founder what's blocking you."
    return None


def check_volume(cache):
    """Block at ceiling, warn at warning threshold.

    The gate-refusal budget is spent HERE and nowhere else — only on a call the
    ceiling would otherwise have blocked. That is why granting it eagerly (on any
    refused commit, at any call count) costs nothing: a run that never reaches the
    ceiling never touches it."""
    calls = cache.get("tool_calls_since_user", 0)
    if calls >= VOLUME_CEILING:
        gate = cache.get("gate_grace_gate")
        remaining = cache.get("gate_grace_remaining", 0)
        if remaining > 0:
            cache["gate_grace_remaining"] = remaining - 1
            return ("warn", f"{gate} refused your commit, so you have {remaining - 1} call(s) left to satisfy that gate and retry `git commit` (which is exempt from this ceiling). At zero this run hard-stops. Do nothing else with these calls.")
        if gate:
            return ("block", f"{gate} refused the checkpoint and the {GATE_GRACE}-call grace budget is spent. Stop. Report what {gate} is asking for, what you tried, and that the work is staged and uncommitted.")
        return ("block", f"{VOLUME_CEILING} tool calls without user input or a commit. Commit finished work now (git commit is exempt from this ceiling and resets it), or stop and summarize what you've accomplished and what's remaining.")
    if calls >= VOLUME_WARNING and cache.get("warnings_issued", 0) == 0:
        remaining = VOLUME_CEILING - calls
        cache["warnings_issued"] = 1
        return ("warn", f"You've made {calls} tool calls since the last user message. You have {remaining} remaining before hard stop. Committing finished work resets the counter; otherwise focus on producing output.")
    return None


def check_agent_ceiling(tool_name, cache):
    """Block if too many agents spawned since last user message."""
    if tool_name != "Agent":
        return None
    count = cache.get("agent_calls_since_user", 0)
    if count > AGENT_CEILING:
        return f"{AGENT_CEILING} subagents spawned since last user message. Use direct tool calls (Grep, Glob, Read) instead."
    return None


def check_mcp_rate(tool_name, cache):
    """Block if MCP calls exceed rate limit."""
    if not tool_name.startswith("mcp__"):
        return None
    timestamps = cache.get("mcp_timestamps", [])
    if len(timestamps) > MCP_RATE_LIMIT:
        return f"{MCP_RATE_LIMIT} MCP calls in the last {MCP_RATE_WINDOW} seconds. Pause and batch your requests."
    return None


def check_read_spiral(tool_name, cache):
    """Warn if too many consecutive reads without output."""
    if tool_name not in ("Read", "Grep", "Glob"):
        return None
    count = cache.get("consecutive_reads", 0)
    if count >= READ_SPIRAL_LIMIT:
        return f"{READ_SPIRAL_LIMIT} consecutive read operations with no output. Are you exploring or producing?"
    return None


def check_file_reread(tool_name, tool_input, cache):
    """Warn if same file read too many times."""
    if tool_name != "Read":
        return None
    file_path = tool_input.get("file_path", "")
    count = cache.get("file_read_counts", {}).get(file_path, 0)
    if count >= FILE_REREAD_LIMIT:
        short = os.path.basename(file_path)
        return f"You've read {short} {count} times. You already have this information. Use it or move on."
    return None


def check_grep_drift(tool_name, cache):
    """Warn if too many greps without producing output."""
    if tool_name not in ("Grep", "Glob"):
        return None
    count = cache.get("greps_since_write", 0)
    if count >= GREP_DRIFT_LIMIT:
        return f"{count} searches without producing output. You're searching, not working. Pick a direction."
    return None


def check_edit_spiral(tool_name, tool_input, cache):
    """Block if too many edit attempts on the same file."""
    if tool_name != "Edit":
        return None
    file_path = tool_input.get("file_path", "")
    count = cache.get("edit_targets", {}).get(file_path, 0)
    if count >= EDIT_FAIL_LIMIT:
        short = os.path.basename(file_path)
        return f"{count} edit attempts on {short}. The approach isn't working. Read the file again, find the exact string, or tell the founder what's wrong."
    return None


def check_agent_no_output(tool_name, cache):
    """Warn if agents spawned with no writes between them."""
    if tool_name != "Agent":
        return None
    count = cache.get("agents_without_write", 0)
    if count >= AGENT_NO_OUTPUT_LIMIT:
        return f"{count} agents spawned with no output written. Agents aren't helping. Use Grep/Glob/Read directly or tell the founder what you're looking for."
    return None


def check_time_stall(cache):
    """Warn if too much time and too many calls since last write. Re-fires at
    most once per STALL_TIME_SECONDS: without the rate limit a legitimate
    read-only stretch (an audit, a reproduction pass) got the SAME warning on
    EVERY tool call — observed live 2026-07-23, 9 consecutive warns in one
    session (F4, prd-silent-absence-capability-gate). One nudge per window
    keeps the detector; the spam killed its signal."""
    last_write = cache.get("last_write_time", time.time())
    elapsed = time.time() - last_write
    calls = cache.get("calls_since_write", 0)
    if elapsed >= STALL_TIME_SECONDS and calls >= STALL_MIN_CALLS:
        last_warn = cache.get("last_stall_warn_time", 0)
        if time.time() - last_warn < STALL_TIME_SECONDS:
            return None
        cache["last_stall_warn_time"] = time.time()
        minutes = int(elapsed // 60)
        return f"{minutes} minutes and {calls} tool calls since your last write. You may be stuck. Summarize what you've tried and what's blocking you."
    return None


# --- Cross-model escalation on a stuck block (ASK-311) -----------------------
# The executable is scripts/fable-escalate.py; the test that pins this branch is
# tests/test_fable_escalation.py. Every check in this file terminates in exactly
# two outcomes, block() or warn(), and neither changes the REASONING
# DISTRIBUTION — so a pattern that deadlocks Opus deadlocks it again on the next
# attempt. This is the third outcome: the script above hands the situation to a
# different model in a fresh session, gets a triage back, and staples it to the
# refusal. Opus keeps the work; Fable never implements.
#
# ONLY ON A STUCK BLOCK, NEVER ON A WARN. A warn means "you may be drifting" and
# most runs recover unaided (the time-stall detector fires on any legitimate
# read-only audit stretch). A block means the run has already stopped, so the
# few seconds a triage costs were lost anyway. Which blocks count is declared at
# the call site, not inferred from the message text: a sensitive-file refusal is
# policy and an MCP rate limit is environmental-trigger class
# (self-healing-retry.md rule 5), and no amount of cross-model triage fixes
# either one.
FABLE_ESCALATE_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "scripts", "fable-escalate.py")


def _int_env(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def maybe_escalate(cache, hook_input, trigger, reason):
    """Fable's triage for this stuck block, or None. Never raises, never hangs.

    EVERY failure path returns None so the caller emits today's plain block. The
    lesson this is built against is
    `a-hook-that-fails-closed-on-a-missing-script-blocks-the-fix-too`: a
    fail-closed hook whose own dependency is missing blocks the repair too. So a
    missing script, a dead model, a timeout and a malformed reply are all a
    no-op here — the escalation can only ADD to a block, never withhold one.

    The outer timeout is deliberately larger than the inner one in
    fable-escalate.py. Two nested caps, because the inner one protects against a
    slow model and the outer one protects against fable-escalate.py itself
    wedging; a single cap would leave the hook hanging on the case it cannot see.
    """
    if os.environ.get("KIPI_FABLE_ESCALATION") == "0":
        return None
    if not os.path.exists(FABLE_ESCALATE_SCRIPT):
        return None
    import subprocess
    args = [
        sys.executable, FABLE_ESCALATE_SCRIPT, "--json",
        "--trigger", trigger,
        "--reason", (reason or "")[:500],
        "--transcript", hook_input.get("transcript_path", "") or "",
        "--count", str(cache.get("fable_escalations", 0)),
    ]
    if cache.get("fable_capped_notified"):
        args.append("--capped-notified")
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True,
            timeout=_int_env("KIPI_FABLE_TIMEOUT", 45) + 15)
        result = json.loads((proc.stdout or "").strip().splitlines()[-1])
    except Exception:
        return None
    if not isinstance(result, dict):
        return None
    if result.get("notified"):
        cache["fable_capped_notified"] = True
    if result.get("capped"):
        cache["fable_capped"] = True
        return None
    if result.get("escalated") and result.get("triage"):
        cache["fable_escalations"] = cache.get("fable_escalations", 0) + 1
        return result["triage"]
    return None


def block(message, cache=None, hook_input=None, trigger=None, actor=None):
    """Exit with code 2 to block the tool call.

    `trigger` is what opts a refusal into cross-model escalation, and it is set
    per call site rather than sniffed from the text. Untagged call sites keep
    the exact behaviour they had before ASK-311, byte for byte — the test
    tests/test_fable_escalation.py asserts that equality against a baseline.
    """
    if trigger and cache is not None and hook_input is not None:
        triage = maybe_escalate(cache, hook_input, trigger, message)
        if triage:
            message = ("%s\n\n--- FABLE TRIAGE (fresh session, %s) ---\n%s\n"
                       "--- end triage. It is a proposal, not a measurement: "
                       "run its REFUTE command before acting on it. ---"
                       % (message, "claude-fable-5", triage))
        elif cache.get("fable_capped"):
            message = ("%s\n\n[Fable escalation cap spent for this actor. The "
                       "founder has been paged. Stop and report what you tried.]"
                       % message)
        save_cache(actor, cache)
    print(message, file=sys.stderr)
    sys.exit(2)


def uncount_blocked_attempt(cache, tool_name, tool_input):
    """A guard-BLOCKED call never executed, so it must not count toward the
    escalation counters. Scar (2026-07-02, Pure_spectrum_Q/qep_agent): at the
    volume ceiling each blocked Edit still incremented repeat_map; the 3rd
    blocked retry was reported as 'attempted this exact call 3 times' for a
    call that ran ZERO times (exact-retry outranks volume), hijacking the true
    block reason. Only repeat_map and edit_targets are undone — the volume
    counters stay, since a blocked attempt still spent budget and the volume
    message stays truthful either way."""
    input_hash = hashlib.md5(
        (tool_name + json.dumps(tool_input, sort_keys=True)).encode()
    ).hexdigest()[:12]
    key = f"{tool_name}:{input_hash}"
    repeat_map = cache.get("repeat_map", {})
    if repeat_map.get(key, 0) > 1:
        repeat_map[key] -= 1
    else:
        repeat_map.pop(key, None)
    if tool_name == "Edit":
        targets = cache.get("edit_targets", {})
        file_path = tool_input.get("file_path", "")
        if targets.get(file_path, 0) > 1:
            targets[file_path] -= 1
        else:
            targets.pop(file_path, None)
    return cache


def warn(message):
    """Output warning as PreToolUse additionalContext (doesn't block). Must be
    nested under hookSpecificOutput with hookEventName — a top-level
    additionalContext key is silently ignored by Claude Code, which left every
    warning tier invisible until 2026-07-02 (the guard jumped from zero
    feedback straight to exit-2 blocks). warn() is only called from the
    PreToolUse path; UserPromptSubmit and PostToolUse exit before the checks."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": message,
        }
    }))
    sys.exit(0)


# The subcommands that make a checkpoint possible, for the volume-ceiling
# exemption only. `add` is here because a blocked `git add` makes the commit
# impossible regardless — staging is part of the checkpoint, not a separate
# errand. It is deliberately NOT in the reset/grace readers below: `git add`
# ships nothing, so it must never reset the ceiling or mint a grace budget.
GIT_CHECKPOINT_SUBCOMMANDS = ("commit", "add")


def _is_commit_command(tool_name, tool_input):
    """A `git commit`/`git add` invocation, judged from the command alone
    (PreToolUse has no response yet). Used to EXEMPT the checkpoint from the
    volume ceiling — a commit is the checkpoint the ceiling is asking for, so
    blocking it deadlocks the run (the PostToolUse commit-reset can never fire
    if PreToolUse blocks the commit first).

    Scar (sp-91a19d16, observed live 2026-08-01): this was `"git commit" in cmd`,
    a raw substring test, and it was wrong in BOTH directions at once. Too tight:
    `git -C <worktree> commit -m ...` contains no "git commit" substring, and
    `git add` was never matched at all — so an agent working in a worktree (the
    standard dispatch pattern here) could never clear the ceiling. One finished
    cross-repo GH_REPO scoping with a passing 26-case suite, could not commit any
    of it, correctly refused to route around the gate, and stopped. Too loose:
    `echo "git commit"` and `grep -r "git commit" .` carried the substring and
    cleared the ceiling while shipping nothing. Match the INVOCATION, not the
    substring; the tokeniser below already knew how."""
    if tool_name != "Bash":
        return False
    cmd = (tool_input or {}).get("command", "") or ""
    return _invokes_git_subcommand(cmd, GIT_CHECKPOINT_SUBCOMMANDS)


def _invokes_git_subcommand(command, subcommands):
    """True only when the command actually RUNS `git <subcommand>`, for any
    subcommand in `subcommands`.

    A substring test on the command text is not that: `grep -rn "git commit"
    canonical/` carries the string and ships nothing, and a failing one was read
    as a refused checkpoint (PR #27 review, finding 2). Tokenising drops the
    quoted mention (shlex collapses "git commit" into ONE token, which is not
    `git`) while keeping `cd x && git add -A && git commit -m y`, `git -C x
    commit`, and the newline/`;`-separated forms — the scan walks every token,
    so the position of the verb in the command does not matter.

    Two callers, two subcommand sets, on purpose. The ceiling exemption passes
    GIT_CHECKPOINT_SUBCOMMANDS, where a false negative is the expensive error: it
    blocks the checkpoint the ceiling is asking for and deadlocks the run, while
    a false positive costs one exempted call that still cannot reset anything.
    _invokes_git_commit passes commit-only, because there a false positive is the
    expensive one: it mints a grace budget, or resets the ceiling, for a command
    that committed nothing."""
    if not command:
        return False
    segments = _command_segments(command)
    for position, (operator, tokens) in enumerate(segments):
        if position and not _segment_is_reachable(
                operator, segments[position - 1][1]):
            continue
        if _segment_invokes(tokens, subcommands):
            return True
    return False


# Shell operators that end one command and begin the next.
_CMD_SEPARATORS = frozenset(("&&", "||", ";", "|", "&"))

# git's global options that swallow the following token as their value.
_GIT_GLOBAL_TWO_WORD = frozenset(
    ("-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path"))

# Commands whose exit status is knowable from the text alone. Everything else is
# runtime-valued, so `foo && git commit` stays reachable.
_ALWAYS_FALSE = frozenset(("false", "/bin/false", "/usr/bin/false"))
_ALWAYS_TRUE = frozenset(("true", "/bin/true", "/usr/bin/true", ":"))

# The flag meaning "this invocation ships nothing", per subcommand. `-n` is add's
# short --dry-run, but commit's -n is --no-verify: a REAL commit. Reading them
# the same way would refuse a --no-verify checkpoint, which is exactly the
# strands-finished-work failure this exemption exists to prevent.
_DRY_RUN_FLAGS = {
    "commit": frozenset(("--dry-run",)),
    "add": frozenset(("--dry-run", "-n")),
}


def _command_segments(command):
    """Every independently-executable command in the string, as
    (preceding_operator, tokens).

    Newlines are real command separators in shell but plain WHITESPACE to shlex,
    so lines are split first and `&&`/`||`/`;`/`|`/`&` split what remains. Doing
    it in that order is what keeps _is_dry_run's argument region from running off
    the end of one command into the next."""
    segments = []
    for line in command.splitlines():
        if not line.strip():
            continue
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            tokens = line.split()
        operator, current = None, []
        for token in tokens:
            if token in _CMD_SEPARATORS:
                segments.append((operator, current))
                operator, current = token, []
            else:
                current.append(token)
        segments.append((operator, current))
    return segments


def _segment_is_reachable(operator, previous_tokens):
    """False only for the two cases decidable from the text alone: a command
    guarded by `false &&`, or by `true ||`.

    Deliberately NOT general reachability. That needs a real shell parser, and
    even with one, `foo && git commit` depends on foo's runtime exit status, so
    it is undecidable here. The error budget forces the narrowness: calling a
    REACHABLE commit unreachable refuses a real checkpoint and strands finished
    work, the expensive failure. So only the always-false/always-true builtins,
    only as a whole command, and only against the IMMEDIATELY preceding segment
    (`false && a && git commit` leaves the commit reachable — conservative in the
    safe direction). (Round-1 review, MINOR.)"""
    guard = previous_tokens[0] if len(previous_tokens) == 1 else None
    if operator == "&&" and guard in _ALWAYS_FALSE:
        return False
    if operator == "||" and guard in _ALWAYS_TRUE:
        return False
    return True


def _segment_invokes(tokens, subcommands):
    """Scan one command for `git [global-opts] <subcommand>` that is not a dry
    run. The scan walks every token rather than assuming position 0, so wrapper
    prefixes (`env FOO=bar git commit ...`) still match."""
    index = 0
    while index < len(tokens):
        if tokens[index] == "git" or tokens[index].endswith("/git"):
            cursor = index + 1
            while cursor < len(tokens) and tokens[cursor].startswith("-"):
                if tokens[cursor] in _GIT_GLOBAL_TWO_WORD:
                    cursor += 2
                else:
                    cursor += 1
            if (cursor < len(tokens) and tokens[cursor] in subcommands
                    and not _is_dry_run(tokens, cursor)):
                return True
            index = cursor
        index += 1
    return False


def _is_dry_run(tokens, subcommand_index):
    """True when THIS invocation carries its subcommand's dry-run flag.

    Scoped to the one invocation and matched on WHOLE tokens, never on the
    command string. Scar (sp-9ca7e393, round-1 review MAJOR): this was
    `"--dry-run" in command`, so `git commit -m "fix: honor --dry-run flag"` was
    read as a dry run and blocked at the volume ceiling — a real commit refused,
    leaving unattended work uncommitted until a human resumed it, the same shape
    as the worktree strand this file's other scar records. It also masked a real
    commit that followed a dry-run probe (`git commit --dry-run && git -C x
    commit -m y`). shlex collapses a quoted message into ONE token, so exact
    matching inside the invocation's own argument region cannot be fooled by
    message text."""
    flags = _DRY_RUN_FLAGS.get(tokens[subcommand_index], frozenset())
    for token in tokens[subcommand_index + 1:]:
        # A new `git ...` begins the next invocation; its flags are not ours.
        if token == "git" or token.endswith("/git"):
            break
        if token in flags:
            return True
    return False


def _invokes_git_commit(command):
    """True only when the command actually RUNS `git commit`. Feeds the
    volume-counter reset and the gate-grace budget, so it stays commit-only:
    `git add` ships nothing and must not look like progress."""
    return _invokes_git_subcommand(command, ("commit",))


def _is_successful_commit(command, tool_response):
    """True only for a `git commit` that actually created a commit. A no-op
    ('nothing to commit'), a --dry-run, or a failed commit is NOT progress and must not
    reset the volume counter — only a real commit does. Conservative: requires the
    git-commit verb, not a dry-run, no error, and output that isn't a no-op."""
    if not _invokes_git_commit(command):
        return False
    if isinstance(tool_response, dict) and tool_response.get("error"):
        return False
    text, code = _response_text_and_code(tool_response)
    # A non-zero exit code is a failed commit even when the response carries no
    # `error` key. Without this the two readers of one response disagreed: a
    # refusal delivered as exit_code=1 was a gate refusal to
    # _commit_gate_refusal and a landed commit here — so it reset the ceiling
    # and cleared the budget it had just minted, one branch earlier in the same
    # if/elif chain. (Narrower than sp-1078fbe2, which is the case where the
    # response carries no failure signal at all; that stays captured, not fixed.)
    if code is not None and code != 0:
        return False
    text = text.lower()
    if "nothing to commit" in text or "no changes added to commit" in text:
        return False
    return True


# --- The gate-refusal grace budget (ASK-215) ---------------------------------
# The commit exemption above covers the commit COMMAND. It does not cover the
# commit's PRECONDITIONS. A commit refused by a pre-commit gate is not a
# checkpoint, and satisfying that gate needs an Edit the ceiling blocks — so the
# run deadlocks with everything staged and nothing committed (observed 2026-07-27
# on ASK-214: lefthook's plugin-version-bump refused the checkpoint, the agent had
# 18 of 20 tests done, and the work was recovered by hand).
#
# The fix is a BOUNDED budget, not an allowlist. This repo has seven blocking
# pre-commit gates and each can demand a different file; exempting plugin.json
# specifically is whack-a-mole that the next gate defeats. The budget is blind to
# which gate fired, so it also covers gates that do not exist yet.

# Failures of `git commit` that are NOT a gate refusing the checkpoint. The no-op
# entries are the load-bearing ones: without them an agent could mint budget with
# an empty commit, which is the runaway loop the ceiling exists to stop.
NON_GATE_COMMIT_FAILURES = (
    "nothing to commit",
    "no changes added to commit",
    "nothing added to commit",
    "empty commit message",
    "not a git repository",
    "please tell me who you are",
    "unmerged files",
    "needs merge",
    # Transient / environmental git failures. A lock collision is routine in
    # this fleet, not exotic: a 15-minute auto-committer and parallel sessions
    # share a checkout. Reporting one as "a pre-commit gate refused the
    # checkpoint" spends the whole budget chasing a gate that does not exist and
    # then hands the operator a fabricated diagnosis at 3am (PR #27 review,
    # finding 1). Nothing is lost by excluding them: the recovery is to retry
    # `git commit`, which the ceiling already exempts, so no budget is needed.
    "index.lock",
    "another git process",
    "cannot lock ref",
    "gpg failed to sign",
    "failed to write commit object",
)

# git's OWN failures exit 128. git normalises EVERY hook refusal to exit 1,
# whatever status the hook returned — captured 2026-07-28 by
# q-system/output/capture-git-transient-failures.sh (hook exits 1, 2, 3, 42 and
# 128 all produced git exit 1; index.lock, cannot-lock-ref and a gpg failure all
# produced 128). So a 128 is git failing, never a gate refusing. It is the one
# near-positive signal available, since git prints no marker of its own, and it
# covers transient failures whose text nobody has enumerated yet.
GIT_SELF_FAILURE_EXIT = 128

# lefthook v2 marks each FAILED command in its summary with a boxing glove
# (passing ones get a check mark). Verified against real output 2026-07-27.
LEFTHOOK_FAIL_MARK = "\U0001f94a"

# Words a gate shouts as a prefix; they are severity labels, not gate names.
_NOT_A_GATE_NAME = frozenset(("block", "error", "fail", "failed", "warning",
                              "fatal", "traceback", "hint", "usage", "note"))


def _response_text_and_code(tool_response):
    """(combined output text, exit code or None) from a tool_response. The Bash
    response shape is not pinned by contract, so read every key the fleet has
    observed — same key set as rca-notify.py's looks_failed."""
    if isinstance(tool_response, str):
        return tool_response, None
    if not isinstance(tool_response, dict):
        return "", None
    code = tool_response.get("exit_code", tool_response.get("returncode"))
    if not isinstance(code, int):
        # The runtime reports a failed Bash call as an `error` STRING
        # ("Exit code 128"), not an integer field. Parsing it is what makes the
        # exit-128 rule reachable on the shape the runtime actually sends; the
        # integer keys stay supported because the shape is not pinned.
        match = re.search(r"exit code\s+(\d+)",
                          str(tool_response.get("error", "")), re.I)
        code = int(match.group(1)) if match else None
    parts = []
    for key in ("stdout", "stderr", "output", "content"):
        value = tool_response.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts), code if isinstance(code, int) else None


def _refusing_gate_name(text):
    """Best-effort name of the gate that refused the commit.

    git passes a hook's output through verbatim and adds NO marker of its own
    (verified 2026-07-27: a hook-refused commit printed only the hook's text and
    exit 1), so the name can only come from the gate's own output. Two readers,
    then a generic label — the block message must never fall back to "50 tool
    calls", which is the wrong reason and sent the ASK-214 agent back into the
    deadlock instead of at the gate."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(LEFTHOOK_FAIL_MARK):
            rest = stripped[len(LEFTHOOK_FAIL_MARK):].strip(" ️")
            name = rest.split(":")[0].split("(")[0].strip()
            if name and " " not in name:
                return name
    # A plain hook / husky / pre-commit-framework line: "my-gate: refused".
    # Only UNINDENTED lines are candidates. A gate prints its name at the left
    # margin and indents the detail beneath it, and without that rule this
    # repo's own commit-msg gate was named `subject`, off its indented
    # "  subject: <the message>" detail line (PR #27 review, finding 4).
    for line in text.splitlines():
        if not line[:1].strip():
            continue
        head = line.strip().split(":")[0]
        if (head and head != line.strip() and " " not in head
                and len(head) <= 48 and head[0].isalnum()
                and head.lower() not in _NOT_A_GATE_NAME):
            return head
    return "a pre-commit gate"


def _commit_gate_refusal(command, tool_response):
    """The name of the gate that refused this `git commit`, or None.

    Deliberately narrow on WHAT it excludes and blind to WHICH gate fired: any
    commit that failed, other than the known non-gate failures above, is treated
    as a refused checkpoint. A mis-read costs at most GATE_GRACE calls; missing a
    real refusal costs the whole run."""
    if not _invokes_git_commit(command):
        return None
    text, code = _response_text_and_code(tool_response)
    errored = bool(isinstance(tool_response, dict) and tool_response.get("error"))
    failed = errored or (code is not None and code != 0)
    if not failed:
        return None
    if code == GIT_SELF_FAILURE_EXIT:
        return None
    lowered = text.lower()
    for phrase in NON_GATE_COMMIT_FAILURES:
        if phrase in lowered:
            return None
    return _refusing_gate_name(text)


def grant_gate_grace(cache, gate):
    """Record the refusing gate always; hand out budget at most
    GATE_GRACE_GRANTS times per user-message window.

    Re-arming on every refusal would turn the ceiling into an endless ratchet —
    refuse, get 8, spend 8, refuse again — which is the runaway loop the ceiling
    exists to stop. A second refusal updates the NAME (so the hard stop cites the
    gate actually blocking now) without topping the budget up: the budget is per
    deadlock episode, not per gate."""
    cache["gate_grace_gate"] = gate
    if cache.get("gate_grace_grants", 0) >= GATE_GRACE_GRANTS:
        return cache
    cache["gate_grace_grants"] = cache.get("gate_grace_grants", 0) + 1
    cache["gate_grace_remaining"] = GATE_GRACE
    return cache


def clear_gate_grace(cache):
    """The checkpoint landed, so the episode is over. Clearing matters: stale
    budget left on the cache would silently widen a LATER ceiling in the same
    session by GATE_GRACE calls."""
    cache["gate_grace_remaining"] = 0
    cache["gate_grace_gate"] = None
    cache["gate_grace_grants"] = 0
    return cache


def reset_per_message_counters(cache):
    """Reset counters that track 'since last user message'."""
    cache["tool_calls_since_user"] = 0
    cache["agent_calls_since_user"] = 0
    cache["repeat_map"] = {}
    cache["consecutive_reads"] = 0
    cache["warnings_issued"] = 0
    cache["file_read_counts"] = {}
    cache["greps_since_write"] = 0
    cache["edit_targets"] = {}
    cache["agents_without_write"] = 0
    cache["last_write_time"] = time.time()
    cache["calls_since_write"] = 0
    cache["last_volume_reset"] = time.time()
    cache = clear_gate_grace(cache)
    return cache


AUTO_COMMIT_SUBJECT = "chore: update project files"  # the repo's 15-min auto-committer


def _head_commit_epoch():
    """Unix time of the most recent NON-auto commit, or None outside a repo /
    on error. The 15-minute auto-committer ships dirty files on a timer, not
    progress — counting it would quietly turn the ceiling into '50 calls per
    15 minutes'. Excluded by exact subject match."""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "-C", os.environ.get("CLAUDE_PROJECT_DIR", "."),
             "log", "-1", "--format=%ct", "--fixed-strings",
             f"--grep={AUTO_COMMIT_SUBJECT}", "--invert-grep"],
            capture_output=True, text=True, timeout=3)
    except (subprocess.SubprocessError, OSError):
        return None
    stamp = out.stdout.strip()
    if out.returncode == 0 and stamp.isdigit():
        return int(stamp)
    return None


def reset_volume_if_committed(cache):
    """The commit-progress valve, PreToolUse side. A repo HEAD commit newer
    than the last volume reset means the run is shipping — zero the volume
    counters (gate lack-of-progress, not raw volume). Only consulted once the
    counter is near the ceiling, so the common path stays subprocess-free.
    Works even when PostToolUse delivery is missing (the dead-valve defect
    this issue closes)."""
    if cache.get("tool_calls_since_user", 0) < VOLUME_WARNING:
        return cache
    head_epoch = _head_commit_epoch()
    if head_epoch and head_epoch > cache.get("last_volume_reset", 0):
        cache["tool_calls_since_user"] = 0
        cache["agent_calls_since_user"] = 0
        cache["warnings_issued"] = 0
        cache["last_volume_reset"] = time.time()
        cache = clear_gate_grace(cache)
    return cache


def main():
    # Runtime guard (scar sp-28bf75a4): this is a Claude Code circuit breaker.
    # Foreign runtimes that load the kipi plugins via their own marketplace clone
    # (e.g. Codex through ~/.codex/.tmp/marketplaces/kipi) must NOT run it -- a
    # UserPromptSubmit block fired inside `codex exec` and killed an in-repo Codex
    # review. CLAUDECODE=1 is set only by the Claude Code runtime; absent it, no-op.
    if not os.environ.get("CLAUDECODE"):
        sys.exit(0)
    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    # Per-actor key: the main session and each spawned subagent get their own
    # counter file (see module docstring; evidence in guard-payload-dump.json).
    actor = actor_cache_key(hook_input)
    hook_event = hook_input.get("hook_event_name", "")

    # UserPromptSubmit: reset per-message counters, sweep stale caches, exit.
    # Only the main actor receives this event; subagent caches age out via
    # the TTL sweep.
    if hook_event == "UserPromptSubmit":
        cache = load_cache(actor)
        cache = reset_per_message_counters(cache)
        save_cache(actor, cache)
        sweep_stale_caches()
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    # PostToolUse: a SUCCESSFUL edit is progress, not a spiral — clear that file's edit
    # counter so the PreToolUse edit-spiral check only fires on repeated FAILED edits (the
    # real spiral). A failed edit keeps counting. check_exact_retry still catches identical
    # retries regardless. Without this, 3 successful edits to one file in a turn falsely block.
    if hook_event == "PostToolUse":
        if tool_name == "Edit":
            resp = hook_input.get("tool_response")
            failed = (isinstance(resp, dict) and resp.get("error")) or (
                isinstance(resp, str) and resp.strip().lower().startswith(
                    ("error", "edit failed", "no match", "string not found")))
            if not failed:
                cache = load_cache(actor)
                cache.get("edit_targets", {}).pop(tool_input.get("file_path", ""), None)
                save_cache(actor, cache)
        # A SUCCESSFUL `git commit` is a durable check-in, so it resets the volume counter —
        # the same shape as the edit-spiral reset above (progress clears the counter). The
        # 50-call ceiling exists to catch a stuck/spinning run, NOT to punish a run that is
        # shipping tested, committed increments (the autonomous-PRD case). A run that grinds
        # 50 calls WITHOUT committing still gets stopped; one that commits keeps going. This
        # makes the guard gate lack-of-progress, not raw volume. (sr-staff call 2026-06-11.)
        elif tool_name == "Bash" and _is_successful_commit(
                tool_input.get("command", ""), hook_input.get("tool_response")):
            cache = load_cache(actor)
            cache["tool_calls_since_user"] = 0
            cache["agent_calls_since_user"] = 0
            cache["warnings_issued"] = 0
            cache["last_volume_reset"] = time.time()
            cache = clear_gate_grace(cache)
            save_cache(actor, cache)
        # A commit REFUSED by a pre-commit gate is the other half of the valve.
        # It is not progress, so it must not reset the counter — but the gate's
        # precondition needs an Edit the ceiling blocks, so the run gets a bounded
        # budget to satisfy the gate and retry. See the grace block above (ASK-215).
        elif tool_name == "Bash":
            gate = _commit_gate_refusal(
                tool_input.get("command", ""), hook_input.get("tool_response"))
            if gate:
                cache = load_cache(actor)
                cache = grant_gate_grace(cache, gate)
                save_cache(actor, cache)
        sys.exit(0)

    # Load cache, update counters from this invocation. The commit-progress
    # valve runs before the checks so a freshly-shipped commit lifts the
    # ceiling even when the PostToolUse event never arrived (wiring B).
    cache = load_cache(actor)
    cache = update_counters(tool_name, tool_input, cache)
    cache = reset_volume_if_committed(cache)

    # --- Run checks in priority order ---

    # 1. Sensitive file blocking (highest priority)
    msg = check_sensitive_file(tool_name, tool_input)
    if msg:
        cache = uncount_blocked_attempt(cache, tool_name, tool_input)
        save_cache(actor, cache)
        block(msg)

    # 2. Exact retry detection
    msg = check_exact_retry(tool_name, tool_input, cache)
    if msg:
        cache = uncount_blocked_attempt(cache, tool_name, tool_input)
        save_cache(actor, cache)
        block(msg, cache=cache, hook_input=hook_input,
              trigger="exact-retry", actor=actor)

    # 3. Volume ceiling/warning — EXEMPT a git commit. A commit is the checkpoint the
    # ceiling is asking for; blocking it deadlocks the run (the PostToolUse commit-reset
    # can't fire if the commit never runs). Sensitive-file + exact-retry checks above still
    # apply to commits; only the volume ceiling is skipped.
    #
    # A volume WARNING is held, not emitted here. warn() exits 0, so emitting it
    # inline made checks 4-11 unreachable — for the whole grace budget, an agent
    # spiralling on the gate file got GATE_GRACE unchecked edit attempts and
    # never heard "your edit approach is wrong", then got a block that blamed the
    # gate (PR #27 review, finding 3). Held warnings are emitted at the end, or
    # carried into a later warning; a later BLOCK outranks them and wins.
    pending_warning = None

    def emit_warning(message):
        if pending_warning and message != pending_warning:
            message = pending_warning + "\n\n" + message
        warn(message)

    if not _is_commit_command(tool_name, tool_input):
        result = check_volume(cache)
        if result:
            level, msg = result
            if level == "block":
                cache = uncount_blocked_attempt(cache, tool_name, tool_input)
                save_cache(actor, cache)
                block(msg, cache=cache, hook_input=hook_input,
                      trigger="volume-ceiling", actor=actor)
            pending_warning = msg

    # 4. Subagent ceiling
    msg = check_agent_ceiling(tool_name, cache)
    if msg:
        cache = uncount_blocked_attempt(cache, tool_name, tool_input)
        save_cache(actor, cache)
        block(msg)

    # 5. MCP rate limit
    msg = check_mcp_rate(tool_name, cache)
    if msg:
        cache = uncount_blocked_attempt(cache, tool_name, tool_input)
        save_cache(actor, cache)
        block(msg)

    # 6. Read spiral warning
    msg = check_read_spiral(tool_name, cache)
    if msg:
        save_cache(actor, cache)
        emit_warning(msg)

    # 7. File re-read warning
    msg = check_file_reread(tool_name, tool_input, cache)
    if msg:
        save_cache(actor, cache)
        emit_warning(msg)

    # 8. Grep drift warning
    msg = check_grep_drift(tool_name, cache)
    if msg:
        save_cache(actor, cache)
        emit_warning(msg)

    # 9. Edit spiral block
    msg = check_edit_spiral(tool_name, tool_input, cache)
    if msg:
        cache = uncount_blocked_attempt(cache, tool_name, tool_input)
        save_cache(actor, cache)
        block(msg, cache=cache, hook_input=hook_input,
              trigger="edit-spiral", actor=actor)

    # 10. Agent no-output warning
    msg = check_agent_no_output(tool_name, cache)
    if msg:
        save_cache(actor, cache)
        emit_warning(msg)

    # 11. Time stall warning
    msg = check_time_stall(cache)
    if msg:
        save_cache(actor, cache)
        emit_warning(msg)

    # All clear
    save_cache(actor, cache)
    if pending_warning:
        warn(pending_warning)
    sys.exit(0)


if __name__ == "__main__":
    main()
