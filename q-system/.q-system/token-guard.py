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
AGENT_CEILING = 25          # Agent spawns per user message = block (morning routine needs ~20)
MCP_RATE_WINDOW = 60        # Seconds
MCP_RATE_LIMIT = 30         # MCP calls in window = block
READ_SPIRAL_LIMIT = 15      # Consecutive reads without write = warn

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

    # All clear
    save_cache(session_id, cache)
    sys.exit(0)


if __name__ == "__main__":
    main()
