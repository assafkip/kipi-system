#!/usr/bin/env python3
"""
Token Bleed Guardrail System
Two-layer defense against runaway token consumption in Claude Code sessions.
Layer 1: Hook-based circuit breaker (this script).
Layer 2: CLAUDE.md + .claude/rules/token-discipline.md (behavioral).

Called by PreToolUse hook on every tool call. Parses session transcript
to count tool calls, detect retries, and enforce ceilings.

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
AGENT_CEILING = 3           # Agent spawns per session = block
MCP_RATE_WINDOW = 60        # Seconds
MCP_RATE_LIMIT = 30         # MCP calls in window = block
READ_SPIRAL_LIMIT = 15      # Consecutive reads without write = warn

# Sensitive file patterns (migrated from old PreToolUse hook)
SENSITIVE_PATTERNS = (".env", ".pem", ".key", "credentials")


def load_cache(session_id):
    path = f"/tmp/claude-guard-{session_id}.json"
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "session_id": session_id,
        "tool_calls_total": 0,
        "tool_calls_since_user": 0,
        "agent_calls": 0,
        "mcp_timestamps": [],
        "repeat_map": {},
        "consecutive_reads": 0,
        "warnings_issued": 0,
        "last_byte_offset": 0,
        "last_user_message_idx": -1,
    }


def save_cache(session_id, cache):
    path = f"/tmp/claude-guard-{session_id}.json"
    try:
        with open(path, "w") as f:
            json.dump(cache, f)
    except IOError:
        pass


def parse_transcript(transcript_path, cache):
    """Parse transcript JSONL incrementally from last known position."""
    if not transcript_path or not os.path.exists(transcript_path):
        return cache

    offset = cache.get("last_byte_offset", 0)
    tool_calls_total = cache.get("tool_calls_total", 0)
    tool_calls_since_user = cache.get("tool_calls_since_user", 0)
    agent_calls = cache.get("agent_calls", 0)
    repeat_map = cache.get("repeat_map", {})
    consecutive_reads = cache.get("consecutive_reads", 0)

    try:
        with open(transcript_path, "rb") as f:
            f.seek(offset)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = entry.get("type", "")

                # User message resets the "since user" counter
                if msg_type == "human" or entry.get("role") == "user":
                    tool_calls_since_user = 0

                # Tool use
                if msg_type == "tool_use" or entry.get("type") == "tool_use":
                    tool_calls_total += 1
                    tool_calls_since_user += 1

                    tool_name = entry.get("name", "")
                    tool_input = entry.get("input", {})

                    # Track agents
                    if tool_name == "Agent":
                        agent_calls += 1

                    # Track repeats
                    input_hash = hashlib.md5(
                        (tool_name + json.dumps(tool_input, sort_keys=True)).encode()
                    ).hexdigest()[:12]
                    key = f"{tool_name}:{input_hash}"
                    repeat_map[key] = repeat_map.get(key, 0) + 1

                    # Track consecutive reads
                    if tool_name in ("Read", "Grep", "Glob", "Explore"):
                        consecutive_reads += 1
                    elif tool_name in ("Edit", "Write", "Bash"):
                        consecutive_reads = 0

            new_offset = f.tell()
    except IOError:
        new_offset = offset

    cache["tool_calls_total"] = tool_calls_total
    cache["tool_calls_since_user"] = tool_calls_since_user
    cache["agent_calls"] = agent_calls
    cache["repeat_map"] = repeat_map
    cache["consecutive_reads"] = consecutive_reads
    cache["last_byte_offset"] = new_offset
    return cache


def check_sensitive_file(tool_name, tool_input):
    """Block edits to sensitive files (migrated from old hook)."""
    if tool_name not in ("Edit", "Write"):
        return None

    file_path = tool_input.get("file_path", "") or ""
    file_path_lower = file_path.lower()
    for pattern in SENSITIVE_PATTERNS:
        if pattern in file_path_lower:
            return f"BLOCK: Attempted to modify sensitive file ({file_path}). This file matches pattern '{pattern}'."
    return None


def check_exact_retry(tool_name, tool_input, cache):
    """Block if same tool+input attempted N times."""
    input_hash = hashlib.md5(
        (tool_name + json.dumps(tool_input, sort_keys=True)).encode()
    ).hexdigest()[:12]
    key = f"{tool_name}:{input_hash}"

    # Include current call in count
    count = cache.get("repeat_map", {}).get(key, 0) + 1
    if count >= RETRY_LIMIT:
        return f"You've attempted this exact call {count} times. Stop. Diagnose the failure and tell the founder what's blocking you."
    return None


def check_volume(cache):
    """Block at ceiling, warn at warning threshold."""
    calls = cache.get("tool_calls_since_user", 0) + 1  # Include current

    if calls >= VOLUME_CEILING:
        return ("block", f"{VOLUME_CEILING} tool calls without user input. Stop. Summarize what you've accomplished and what's remaining.")

    if calls >= VOLUME_WARNING and cache.get("warnings_issued", 0) == 0:
        remaining = VOLUME_CEILING - calls
        cache["warnings_issued"] = 1
        return ("warn", f"You've made {calls} tool calls since the last user message. You have {remaining} remaining before hard stop. Focus on producing output.")

    return None


def check_agent_ceiling(tool_name, cache):
    """Block if too many agents spawned."""
    if tool_name != "Agent":
        return None
    # Include current call
    count = cache.get("agent_calls", 0) + 1
    if count > AGENT_CEILING:
        return f"{AGENT_CEILING} subagents already spawned this session. Use direct tool calls (Grep, Glob, Read) instead."
    return None


def check_mcp_rate(tool_name, cache):
    """Block if MCP calls exceed rate limit."""
    if not tool_name.startswith("mcp__"):
        return None

    now = time.time()
    timestamps = cache.get("mcp_timestamps", [])
    # Prune old entries
    timestamps = [t for t in timestamps if now - t < MCP_RATE_WINDOW]
    timestamps.append(now)
    cache["mcp_timestamps"] = timestamps

    if len(timestamps) > MCP_RATE_LIMIT:
        return f"{MCP_RATE_LIMIT} MCP calls in the last {MCP_RATE_WINDOW} seconds. Pause and batch your requests."
    return None


def check_read_spiral(tool_name, cache):
    """Warn if too many consecutive reads without output."""
    if tool_name not in ("Read", "Grep", "Glob"):
        return None

    count = cache.get("consecutive_reads", 0) + 1  # Include current
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


def main():
    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)  # Can't parse, allow

    session_id = hook_input.get("session_id", "unknown")
    transcript_path = hook_input.get("transcript_path", "")
    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    # Load and update cache
    cache = load_cache(session_id)
    cache = parse_transcript(transcript_path, cache)

    # --- Run checks in priority order ---

    # 1. Sensitive file blocking (highest priority, always runs)
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
