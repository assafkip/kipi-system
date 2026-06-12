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

# Sensitive file patterns
SENSITIVE_PATTERNS = (".env", ".pem", ".key", "credentials")


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
    """Block if same tool+input attempted N times."""
    input_hash = hashlib.md5(
        (tool_name + json.dumps(tool_input, sort_keys=True)).encode()
    ).hexdigest()[:12]
    key = f"{tool_name}:{input_hash}"
    count = cache.get("repeat_map", {}).get(key, 0)
    if count >= RETRY_LIMIT:
        return f"You've attempted this exact call {count} times. Stop. Diagnose the failure and tell the founder what's blocking you."
    return None


def check_volume(cache):
    """Block at ceiling, warn at warning threshold."""
    calls = cache.get("tool_calls_since_user", 0)
    if calls >= VOLUME_CEILING:
        return ("block", f"{VOLUME_CEILING} tool calls without user input. Stop. Summarize what you've accomplished and what's remaining.")
    if calls >= VOLUME_WARNING and cache.get("warnings_issued", 0) == 0:
        remaining = VOLUME_CEILING - calls
        cache["warnings_issued"] = 1
        return ("warn", f"You've made {calls} tool calls since the last user message. You have {remaining} remaining before hard stop. Focus on producing output.")
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
    """Warn if too much time and too many calls since last write."""
    last_write = cache.get("last_write_time", time.time())
    elapsed = time.time() - last_write
    calls = cache.get("calls_since_write", 0)
    if elapsed >= STALL_TIME_SECONDS and calls >= STALL_MIN_CALLS:
        minutes = int(elapsed // 60)
        return f"{minutes} minutes and {calls} tool calls since your last write. You may be stuck. Summarize what you've tried and what's blocking you."
    return None


def block(message):
    """Exit with code 2 to block the tool call."""
    print(message, file=sys.stderr)
    sys.exit(2)


def warn(message):
    """Output warning as JSON additionalContext (doesn't block)."""
    print(json.dumps({"additionalContext": message}))
    sys.exit(0)


def _is_commit_command(tool_name, tool_input):
    """A `git commit` invocation, judged from the command alone (PreToolUse has no
    response yet). Used to EXEMPT a commit from the volume ceiling — a commit is the
    checkpoint the ceiling is asking for, so blocking it deadlocks the run (the
    PostToolUse commit-reset can never fire if PreToolUse blocks the commit first)."""
    if tool_name != "Bash":
        return False
    cmd = (tool_input or {}).get("command", "") or ""
    return "git commit" in cmd and "--dry-run" not in cmd


def _is_successful_commit(command, tool_response):
    """True only for a `git commit` that actually created a commit. A no-op
    ('nothing to commit'), a --dry-run, or a failed commit is NOT progress and must not
    reset the volume counter — only a real commit does. Conservative: requires the
    git-commit verb, not a dry-run, no error, and output that isn't a no-op."""
    if not command or "git commit" not in command or "--dry-run" in command:
        return False
    text = ""
    if isinstance(tool_response, dict):
        if tool_response.get("error"):
            return False
        text = (str(tool_response.get("stdout", "")) + " "
                + str(tool_response.get("stderr", ""))).lower()
    elif isinstance(tool_response, str):
        text = tool_response.lower()
    if "nothing to commit" in text or "no changes added to commit" in text:
        return False
    return True


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
    return cache


def main():
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
        save_cache(actor, cache)
        block(msg)

    # 2. Exact retry detection
    msg = check_exact_retry(tool_name, tool_input, cache)
    if msg:
        save_cache(actor, cache)
        block(msg)

    # 3. Volume ceiling/warning — EXEMPT a git commit. A commit is the checkpoint the
    # ceiling is asking for; blocking it deadlocks the run (the PostToolUse commit-reset
    # can't fire if the commit never runs). Sensitive-file + exact-retry checks above still
    # apply to commits; only the volume ceiling is skipped.
    if not _is_commit_command(tool_name, tool_input):
        result = check_volume(cache)
        if result:
            level, msg = result
            save_cache(actor, cache)
            if level == "block":
                block(msg)
            else:
                warn(msg)

    # 4. Subagent ceiling
    msg = check_agent_ceiling(tool_name, cache)
    if msg:
        save_cache(actor, cache)
        block(msg)

    # 5. MCP rate limit
    msg = check_mcp_rate(tool_name, cache)
    if msg:
        save_cache(actor, cache)
        block(msg)

    # 6. Read spiral warning
    msg = check_read_spiral(tool_name, cache)
    if msg:
        save_cache(actor, cache)
        warn(msg)

    # 7. File re-read warning
    msg = check_file_reread(tool_name, tool_input, cache)
    if msg:
        save_cache(actor, cache)
        warn(msg)

    # 8. Grep drift warning
    msg = check_grep_drift(tool_name, cache)
    if msg:
        save_cache(actor, cache)
        warn(msg)

    # 9. Edit spiral block
    msg = check_edit_spiral(tool_name, tool_input, cache)
    if msg:
        save_cache(actor, cache)
        block(msg)

    # 10. Agent no-output warning
    msg = check_agent_no_output(tool_name, cache)
    if msg:
        save_cache(actor, cache)
        warn(msg)

    # 11. Time stall warning
    msg = check_time_stall(cache)
    if msg:
        save_cache(actor, cache)
        warn(msg)

    # All clear
    save_cache(actor, cache)
    sys.exit(0)


if __name__ == "__main__":
    main()
