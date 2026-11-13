#!/usr/bin/env python3
"""startup_census: what a subagent's FIRST request is made of, and what the run used (ASK-4747).

run_tokens.py says how big the first request was (`context_first`). This says
what filled it, so a cut can be aimed and then proven by the same instrument.

Why it reads `api-request-shape` / `api-request-blob` and not the attachment
records: the attachment records are what the CLI collected, the request records
are the bytes it SENT. The 2026-11-12 token-drain analysis split the 120k from
attachments alone and left 66k "by subtraction" -- that remainder held 23.7k
characters of granola tool schemas sent in full on every request (not deferred),
which no attachment shows. Characters, not tokens: the CLI records no per-part
token count, and a guess per part would be a second unmeasured number.

Usage evidence is from the transcript's own tool_use blocks: which tools, Skill
calls and MCP servers the run called. "Never used" in a cut decision means zero
calls across the transcripts read, stated with that count.

usage:
  startup_census.py <transcript.jsonl> [...]    one JSON object per transcript
Exit 1 when a transcript has no request records (an unreadable shape must not
read as an empty start-up).
"""
from __future__ import annotations

import json
import sys
from collections import Counter


def _first_usage(recs: list[dict]) -> int | None:
    """Context of the transcript's first request: input + cache read + cache write."""
    for r in recs:
        if r.get("type") == "assistant":
            u = (r.get("message") or {}).get("usage") or {}
            return sum(int(u.get(k) or 0) for k in
                       ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return None


def _tool_key(prefix: str, name: str) -> str:
    return prefix + (name.split("__")[1] if name.startswith("mcp__") else "builtin")


def parts(recs: list[dict]) -> dict:
    """Characters per part of the FIRST request, from its shape and first blobs."""
    out: Counter = Counter()
    shape = next((r for r in recs if r.get("type") == "api-request-shape"), None)
    if shape is None:
        return {}
    sysb = shape["shape"].get("system") or []
    for blk in sysb:
        text = blk.get("text") or ""
        cut = text.find("\n## MEMORY.md")
        if cut >= 0:
            out["system.agent_memory_index"] += len(text) - cut
            out["system.prompt"] += cut
        else:
            out["system.prompt"] += len(text)
    for tool in shape["shape"].get("tools") or []:
        out[_tool_key("tools.", tool.get("name", ""))] += len(json.dumps(tool))
    # The first request's messages travel as blobs written before its api-request
    # record; later requests write their own. Stop at the first api-request.
    for r in recs:
        if r.get("type") == "api-request":
            break
        if r.get("type") != "api-request-blob":
            continue
        content = (r.get("message") or {}).get("content")
        for blk in content if isinstance(content, list) else []:
            text = blk.get("text") or ""
            if blk.get("type") == "tool_addition":
                tool = blk.get("tool") or {}
                name = (tool.get("definition") or {}).get("name") or tool.get("name", "")
                out[_tool_key("tool_addition.", name)] += len(json.dumps(blk))
            elif "Codebase and user instructions" in text[:300]:
                out["instructions"] += len(text)
            elif "just became available" in text[:300]:
                skills = text.find("The following skills are available")
                env = text.find("# Environment")
                head = env if env >= 0 else (skills if skills >= 0 else len(text))
                out["deferred_tools_and_mcp_instructions"] += head
                if env >= 0:
                    out["environment"] += (skills if skills > env else len(text)) - env
                if skills >= 0:
                    out["skill_listing"] += len(text) - skills
            else:
                out["brief_and_other"] += len(text)
    return dict(out)


def instruction_files(recs: list[dict]) -> dict:
    att = next((r["attachment"] for r in recs if r.get("type") == "attachment"
                and (r.get("attachment") or {}).get("type") == "instructions"), None)
    return {f.get("path"): len(f.get("content") or "") for f in (att or {}).get("files", [])}


def usage(recs: list[dict]) -> dict:
    tools: Counter = Counter()
    skills: Counter = Counter()
    mcp: Counter = Counter()
    for r in recs:
        if r.get("type") != "assistant":
            continue
        for blk in (r.get("message") or {}).get("content") or []:
            if blk.get("type") != "tool_use":
                continue
            name = blk.get("name", "")
            tools[name] += 1
            if name.startswith("mcp__"):
                mcp[name.split("__")[1]] += 1
            if name == "Skill":
                skills[(blk.get("input") or {}).get("skill")] += 1
    return {"tool_calls": dict(tools), "skills_called": dict(skills), "mcp_servers_called": dict(mcp)}


def census(recs: list[dict]) -> dict:
    return {"context_first": _first_usage(recs), "parts_chars": parts(recs),
            "instruction_files": instruction_files(recs), **usage(recs)}


def main(argv: list[str]) -> int:
    rc = 0
    for path in argv:
        with open(path) as fh:
            recs = [json.loads(line) for line in fh if line.strip()]
        row = census(recs)
        row["file"] = path
        if not row["parts_chars"]:
            print("startup_census: no api-request-shape record in %s" % path, file=sys.stderr)
            rc = 1
        print(json.dumps(row))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
