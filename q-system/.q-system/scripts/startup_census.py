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
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# context_first is run_tokens.py's number, read through run_tokens itself. A second
# copy of "first request" here skipped its record filters (API-error and synthetic
# records, no message id) and reported a free start-up of 0 (review of #794).
import run_tokens  # noqa: E402


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
        # The CLI writes some blobs with plain-string content: 1,128 of 44,854
        # blobs in 2,168 transcripts (2026-11-13), one of them 45,869 chars. A
        # list-only loop dropped them at exit 0 (review of #794, round 3).
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for blk in content if isinstance(content, list) else []:
            text = blk.get("text") or ""
            if blk.get("type") == "tool_addition":
                tool = blk.get("tool") or {}
                name = (tool.get("definition") or {}).get("name") or tool.get("name", "")
                out[_tool_key("tool_addition.", name)] += len(json.dumps(blk))
            elif "Codebase and user instructions" in text[:300]:
                out["instructions"] += len(text)
            elif ("just became available" in text[:300]
                  or "deferred tools are now available" in text[:300]):
                # Two producer headers for one block: "just became available"
                # when some tools arrive with full schemas, "deferred tools are
                # now available" when none do (seen after the MCP cut, 2026-11-13).
                # Split on the section markers, never on the header.
                # Each marker owns the text up to the NEXT marker, in position
                # order. Fixed offsets counted the listing twice when it came
                # before "# Environment" (review of #794).
                marks = sorted((i, k) for k, i in (
                    ("environment", text.find("# Environment")),
                    ("skill_listing", text.find("The following skills are available"))) if i >= 0)
                cuts = [0] + [i for i, _ in marks] + [len(text)]
                labels = ["deferred_tools_and_mcp_instructions"] + [k for _, k in marks]
                for label, a, b in zip(labels, cuts, cuts[1:]):
                    out[label] += b - a
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
    return {"parts_chars": parts(recs), "instruction_files": instruction_files(recs), **usage(recs)}


def census_file(path: str) -> dict:
    with open(path) as fh:
        recs = [json.loads(line) for line in fh if line.strip()]
    row = census(recs)
    row["has_shape"] = any(r.get("type") == "api-request-shape" for r in recs)
    # One file in, so no start_of: run_tokens keys its groups by the normalized
    # Path, and a raw "./x" start_of matched no group and read null (review of #794).
    row["context_first"] = run_tokens.report([path]).get("context_first")
    row["file"] = path
    return row


def main(argv: list[str]) -> int:
    rc = 0
    for path in argv:
        # One bad transcript is reported and the batch goes on: a KeyError here
        # used to abandon every later file (review of #794).
        try:
            row = census_file(path)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as e:
            print("startup_census: cannot read %s: %s: %s" % (path, type(e).__name__, e), file=sys.stderr)
            rc = 1
            continue
        if not row["parts_chars"]:
            why = ("api-request-shape present, no parts in it" if row.get("has_shape")
                   else "no api-request-shape record")
            print("startup_census: %s in %s" % (why, path), file=sys.stderr)
            rc = 1
        print(json.dumps(row))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
