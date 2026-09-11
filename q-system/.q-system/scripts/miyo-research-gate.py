#!/usr/bin/env python3
"""PreToolUse gate: force Miyo knowledge-base search before deep manual research.

Deterministic rule: inside scope, once the session transcript shows N or more
research tool calls (Grep/Glob/WebSearch/WebFetch) and zero Miyo usages, block
the next research call (exit 2) with instructions to run a Miyo search first.

Fail-open policy: missing/unreadable transcript, malformed input, or any error
exits 0 so infrastructure problems never brick a session. Kill switch for the
founder shell: MIYO_GATE_OFF=1. Threshold override: MIYO_GATE_THRESHOLD (default 4).

Scope default: only fires when cwd contains '/consulting'. Override with env
MIYO_KB_SCOPE (substring match on cwd) or set MIYO_KB_SCOPE='' to allow anywhere.
"""
import json
import os
import re
import sys

RESEARCH_TOOLS = {"Grep", "Glob", "WebSearch", "WebFetch"}
DEFAULT_SCOPE = "/consulting/"
DEFAULT_THRESHOLD = 4

RE_TOOL_NAME = re.compile(r'"(?:tool_)?name"\s*:\s*"([^"]*)"')
RE_BASH_MIYO = re.compile(r'"command"\s*:\s*"[^"]*miyo\s+search', re.IGNORECASE)


def scope():
    return os.environ.get("MIYO_KB_SCOPE", DEFAULT_SCOPE)


def in_scope(cwd):
    s = scope()
    if not s:
        return True
    return s in cwd + "/"


def threshold():
    try:
        return int(os.environ.get("MIYO_GATE_THRESHOLD", DEFAULT_THRESHOLD))
    except ValueError:
        return DEFAULT_THRESHOLD


def scan_transcript(transcript_path):
    """Return (research_calls, miyo_used) from a Claude Code transcript JSONL."""
    research = 0
    miyo_used = False
    with open(transcript_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            names = RE_TOOL_NAME.findall(line)
            for name in names:
                if name in RESEARCH_TOOLS:
                    research += 1
                elif "miyo" in name.lower():
                    miyo_used = True
            if not miyo_used and RE_BASH_MIYO.search(line):
                miyo_used = True
    return research, miyo_used


def blocked_message(research, limit):
    return (
        f"[miyo-research-gate] {research} research calls this session, zero "
        f"knowledge-base searches. The KB is the retrieval layer; run one Miyo "
        f"search before more direct searching. Use the mcp__miyo__search tool, or: "
        f"~/.miyo/bin/miyo search \"<your question>\" --limit 8. "
        f"This gate releases as soon as one lands. Founder kill switch: "
        f"MIYO_GATE_OFF=1. Current trigger: >= {limit} research calls, no KB hit."
    )


def decide(research_calls, miyo_used, limit):
    if miyo_used:
        return False, None
    if research_calls < limit:
        return False, None
    return True, blocked_message(research_calls, limit)


def main():
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else "{}"
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0
    try:
        if os.environ.get("MIYO_GATE_OFF"):
            return 0
        tool = payload.get("tool_name", "")
        if tool not in RESEARCH_TOOLS:
            return 0
        cwd = payload.get("cwd") or os.getcwd()
        if not in_scope(cwd):
            return 0
        transcript = payload.get("transcript_path")
        if not transcript or not os.path.exists(transcript):
            return 0
        research, miyo_used = scan_transcript(transcript)
        should_block, message = decide(research, miyo_used, threshold())
        if should_block:
            print(message, file=sys.stderr)
            return 2
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
