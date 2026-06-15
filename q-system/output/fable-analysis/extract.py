#!/usr/bin/env python3
"""Attribute code + behavior to the exact model that produced it, from CC transcripts.

Tags every assistant message by message.model. For code-writing tool calls
(Edit/Write/MultiEdit/NotebookEdit) it captures the written text and computes
deterministic style metrics. Also captures behavioral metrics (prose length,
thinking usage, tool cadence). Within-repo so project/task is held ~constant.
"""
import json, os, sys, re, glob
from collections import defaultdict

PROJ_DIR = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "/tmp/fable-vs-opus/result.json"

CODE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
CODE_EXT = (".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".html", ".css", ".sql", ".json", ".md", ".yaml", ".yml")

def model_bucket(m):
    if not m: return None
    if m.startswith("claude-fable"): return "fable"
    if m.startswith("claude-opus-4-8"): return "opus48"
    if m.startswith("claude-opus-4-7"): return "opus47"
    if m.startswith("claude-sonnet"): return "sonnet"
    if m.startswith("claude-haiku"): return "haiku"
    return "other"

def code_metrics(text, ext):
    """Return dict of style metrics for a written code blob."""
    lines = text.split("\n")
    nonblank = [l for l in lines if l.strip()]
    blank = len(lines) - len(nonblank)
    comment = 0
    for l in lines:
        s = l.strip()
        if s.startswith("#") or s.startswith("//") or s.startswith("/*") or s.startswith("*"):
            comment += 1
    linelens = [len(l) for l in lines]
    m = {
        "lines": len(lines),
        "nonblank": len(nonblank),
        "blank": blank,
        "comment_lines": comment,
        "max_line_len": max(linelens) if linelens else 0,
        "sum_line_len": sum(linelens),
        "char": len(text),
    }
    if ext == ".py":
        defs = re.findall(r'^\s*def\s+\w+\s*\(', text, re.M)
        m["py_defs"] = len(defs)
        # type-hinted defs: param ': ' inside parens or '-> ' return
        hinted = re.findall(r'^\s*def\s+\w+\s*\([^)]*:[^)]*\)|->', text, re.M)
        m["py_hinted_defs"] = len(hinted)
        m["py_docstrings"] = len(re.findall(r'"""', text)) // 2
        m["py_try"] = len(re.findall(r'^\s*try:', text, re.M))
        m["py_except"] = len(re.findall(r'^\s*except', text, re.M))
        m["py_fstring"] = len(re.findall(r'f["\']', text))
        m["py_format"] = len(re.findall(r'\.format\(', text))
        m["py_typing_import"] = 1 if re.search(r'from typing import|import typing', text) else 0
    return m

def acc_add(acc, m):
    for k, v in m.items():
        acc[k] += v

def main():
    files = glob.glob(os.path.join(PROJ_DIR, "*.jsonl"))
    # per-model accumulators
    beh = defaultdict(lambda: defaultdict(float))   # behavioral
    code = defaultdict(lambda: defaultdict(float))   # code-style sums
    edit_sizes = defaultdict(list)                   # lines per edit
    tool_counts = defaultdict(lambda: defaultdict(int))
    ext_counts = defaultdict(lambda: defaultdict(int))
    samples = defaultdict(list)                       # sample edits per model

    for f in files:
        with open(f, errors="ignore") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("type") != "assistant":
                    continue
                msg = r.get("message", {})
                b = model_bucket(msg.get("model"))
                if not b:
                    continue
                beh[b]["msgs"] += 1
                for c in msg.get("content", []):
                    if not isinstance(c, dict):
                        continue
                    t = c.get("type")
                    if t == "text":
                        beh[b]["text_blocks"] += 1
                        beh[b]["text_chars"] += len(c.get("text", ""))
                    elif t == "thinking":
                        beh[b]["think_blocks"] += 1
                        beh[b]["think_chars"] += len(c.get("thinking", ""))
                    elif t == "tool_use":
                        name = c.get("name", "?")
                        beh[b]["tool_calls"] += 1
                        tool_counts[b][name] += 1
                        if name in CODE_TOOLS:
                            inp = c.get("input", {})
                            fp = inp.get("file_path", inp.get("notebook_path", ""))
                            ext = os.path.splitext(fp)[1].lower()
                            ext_counts[b][ext or "noext"] += 1
                            blobs = []
                            if name == "Write":
                                blobs.append(inp.get("content", ""))
                            elif name == "Edit":
                                blobs.append(inp.get("new_string", ""))
                            elif name == "MultiEdit":
                                for e in inp.get("edits", []):
                                    blobs.append(e.get("new_string", ""))
                            elif name == "NotebookEdit":
                                blobs.append(inp.get("new_source", ""))
                            for blob in blobs:
                                if not blob:
                                    continue
                                cm = code_metrics(blob, ext)
                                acc_add(code[b], cm)
                                code[b]["edits"] += 1
                                edit_sizes[b].append(cm["lines"])
                                if ext in CODE_EXT and len(samples[b]) < 12 and cm["lines"] >= 8:
                                    samples[b].append({"file": fp, "tool": name, "lines": cm["lines"], "code": blob[:1400]})

    out = {
        "project": os.path.basename(PROJ_DIR.rstrip("/")),
        "behavioral": {k: dict(v) for k, v in beh.items()},
        "code_sums": {k: dict(v) for k, v in code.items()},
        "tool_counts": {k: dict(v) for k, v in tool_counts.items()},
        "ext_counts": {k: dict(v) for k, v in ext_counts.items()},
        "edit_size_lists": {k: v for k, v in edit_sizes.items()},
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh)
    with open(OUT.replace(".json", "_samples.json"), "w") as fh:
        json.dump({k: v for k, v in samples.items()}, fh, indent=1)
    print("wrote", OUT)

if __name__ == "__main__":
    main()
