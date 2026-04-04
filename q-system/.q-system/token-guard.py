#!/usr/bin/env python3
"""
Token Bleed Guardrail System
Two-layer defense against runaway token consumption in Claude Code sessions.
Layer 1: Hook-based circuit breaker (this script).
Layer 2: CLAUDE.md + .claude/rules/token-discipline.md (behavioral).

Called by two hooks:
  - PreToolUse: counts tool calls and enforces limits
  - UserPromptSubmit: resets per-message counters

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


def cache_path(session_id):
    return f"/tmp/claude-guard-{session_id}.json"


def load_cache(session_id):
    path = cache_path(session_id)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "session_id": session_id,
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
    }


def save_cache(session_id, cache):
    path = cache_path(session_id)
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
    return cache


def main():
    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    session_id = hook_input.get("session_id", "unknown")
    hook_event = hook_input.get("hook_event_name", "")

    # UserPromptSubmit: reset per-message counters and exit
    if hook_event == "UserPromptSubmit":
        cache = load_cache(session_id)
        cache = reset_per_message_counters(cache)
        save_cache(session_id, cache)
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    # Load cache, update counters from this invocation
    cache = load_cache(session_id)
    cache = update_counters(tool_name, tool_input, cache)

    # --- Run checks in priority order ---

    # 1. Sensitive file blocking (highest priority)
    msg = check_sensitive_file(tool_name, tool_input)
    if msg:
        save_cache(session_id, cache)
        block(msg)

    # 2. Exact retry detection
    msg = check_exact_retry(tool_name, tool_input, cache)
    if msg:
        save_cache(session_id, cache)
        block(msg)

    # 3. Volume ceiling/warning
    result = check_volume(cache)
    if result:
        level, msg = result
        save_cache(session_id, cache)
        if level == "block":
            block(msg)
        else:
            warn(msg)

    # 4. Subagent ceiling
    msg = check_agent_ceiling(tool_name, cache)
    if msg:
        save_cache(session_id, cache)
        block(msg)

    # 5. MCP rate limit
    msg = check_mcp_rate(tool_name, cache)
    if msg:
        save_cache(session_id, cache)
        block(msg)

    # 6. Read spiral warning
    msg = check_read_spiral(tool_name, cache)
    if msg:
        save_cache(session_id, cache)
        warn(msg)

    # 7. File re-read warning
    msg = check_file_reread(tool_name, tool_input, cache)
    if msg:
        save_cache(session_id, cache)
        warn(msg)

    # 8. Grep drift warning
    msg = check_grep_drift(tool_name, cache)
    if msg:
        save_cache(session_id, cache)
        warn(msg)

    # 9. Edit spiral block
    msg = check_edit_spiral(tool_name, tool_input, cache)
    if msg:
        save_cache(session_id, cache)
        block(msg)

    # 10. Agent no-output warning
    msg = check_agent_no_output(tool_name, cache)
    if msg:
        save_cache(session_id, cache)
        warn(msg)

    # 11. Time stall warning
    msg = check_time_stall(cache)
    if msg:
        save_cache(session_id, cache)
        warn(msg)

    # All clear
    save_cache(session_id, cache)
    sys.exit(0)


if __name__ == "__main__":
    main()
