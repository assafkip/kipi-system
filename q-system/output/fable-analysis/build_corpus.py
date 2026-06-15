#!/usr/bin/env python3
"""Build a clean, readable Fable-only corpus from CC transcripts.

For every assistant message authored by claude-fable-5, capture text, tool calls
(with full input), and link tool_results (execution outcomes) by tool_use_id.
Reconstruct per-session timelines so 'how Fable operates' is observable.

Output: /tmp/fable-corpus/by_repo/<repo>/{code.md,bash.md,prose.md,timeline.md}
        /tmp/fable-corpus/manifest.json
        /tmp/fable-corpus/ALL_CODE_INDEX.tsv
"""
import json, os, glob, re
from collections import defaultdict, OrderedDict

PROJ_ROOT = "/Users/assafkipnis/.claude/projects"
OUT = "/tmp/fable-corpus"
CODE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

REPOS = {
    "kipi-investigations": "-Users-assafkipnis-projects-kipi-investigations",
    "ASK-AI-consultant": "-Users-assafkipnis-projects-ASK-AI-consultant",
    "ktlyst-hub-strategy": "-Users-assafkipnis-projects-ktlyst-hub-strategy",
    "AUDHD-KIDS": "-Users-assafkipnis-projects-AUDHD-KIDS",
}
TMP_GLOBS = ["-private-tmp-kipi-oss-export-1781105305",
             "-private-tmp-kipi-public-1781109312",
             "-private-tmp-kipi-public-final-1781113516",
             "-private-tmp-kipi-pre"]


def is_fable(rec):
    return rec.get("type") == "assistant" and rec.get("message", {}).get("model", "").startswith("claude-fable")


def first_line(s, n=200):
    s = (s or "").strip().replace("\n", " ")
    return s[:n]


def tool_summary(name, inp):
    if name == "Bash":
        return inp.get("command", "")[:500]
    if name in CODE_TOOLS:
        return inp.get("file_path", inp.get("notebook_path", ""))
    if name == "Task":
        return f"subagent={inp.get('subagent_type','?')} :: {first_line(inp.get('description',''),80)}"
    if name == "TodoWrite":
        todos = inp.get("todos", [])
        return f"{len(todos)} todos: " + " | ".join(first_line(t.get('content',''),40) for t in todos[:6])
    if name in ("Grep", "Glob"):
        return inp.get("pattern", "")[:120]
    if name == "Read":
        return inp.get("file_path", "")
    return first_line(json.dumps(inp), 160)


def code_blobs(name, inp):
    out = []
    if name == "Write":
        out.append((inp.get("file_path", ""), inp.get("content", "")))
    elif name == "Edit":
        out.append((inp.get("file_path", ""), inp.get("new_string", "")))
    elif name == "MultiEdit":
        for e in inp.get("edits", []):
            out.append((inp.get("file_path", ""), e.get("new_string", "")))
    elif name == "NotebookEdit":
        out.append((inp.get("notebook_path", ""), inp.get("new_source", "")))
    return out


def collect(dirs):
    """Return ordered events across all transcripts in dirs, plus tool_result map."""
    events = []           # dicts in file+line order
    results = {}          # tool_use_id -> (is_error, text snippet)
    files = []
    for d in dirs:
        files += sorted(glob.glob(os.path.join(PROJ_ROOT, d, "**", "*.jsonl"), recursive=True))
    for f in files:
        sess = os.path.basename(f)
        with open(f, errors="ignore") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                # capture tool_results from any user message (to link outcomes)
                if r.get("type") == "user":
                    msg = r.get("message", {})
                    cont = msg.get("content", [])
                    if isinstance(cont, list):
                        for c in cont:
                            if isinstance(c, dict) and c.get("type") == "tool_result":
                                tid = c.get("tool_use_id", "")
                                body = c.get("content", "")
                                if isinstance(body, list):
                                    body = " ".join(x.get("text", "") for x in body if isinstance(x, dict))
                                results[tid] = (bool(c.get("is_error")), (body or "")[:600])
                    continue
                if not is_fable(r):
                    continue
                ts = r.get("timestamp", "")
                side = r.get("isSidechain", False)
                branch = r.get("gitBranch", "")
                for c in r.get("message", {}).get("content", []):
                    if not isinstance(c, dict):
                        continue
                    t = c.get("type")
                    if t == "text" and c.get("text", "").strip():
                        events.append({"k": "text", "sess": sess, "ts": ts, "side": side,
                                       "branch": branch, "text": c["text"]})
                    elif t == "tool_use":
                        nm = c.get("name", "?")
                        inp = c.get("input", {})
                        events.append({"k": "tool", "sess": sess, "ts": ts, "side": side,
                                       "branch": branch, "name": nm, "id": c.get("id", ""),
                                       "summary": tool_summary(nm, inp),
                                       "blobs": code_blobs(nm, inp)})
    return events, results


def write_repo(repo, events, results):
    rd = os.path.join(OUT, "by_repo", repo)
    os.makedirs(rd, exist_ok=True)
    code_idx = []
    # code.md
    with open(os.path.join(rd, "code.md"), "w") as cf:
        cf.write(f"# Fable code corpus — {repo}\n\n")
        i = 0
        for e in events:
            if e["k"] != "tool":
                continue
            for (fp, blob) in e.get("blobs", []):
                if not blob.strip():
                    continue
                i += 1
                ln = blob.count("\n") + 1
                ext = os.path.splitext(fp)[1]
                cf.write(f"\n\n===== CODE #{i} | {e['name']} | {fp} | {ln} lines | {e['ts']} | sidechain={e['side']} =====\n")
                cf.write("```" + ext.lstrip(".") + "\n")
                cf.write(blob[:6000])
                cf.write("\n```\n")
                code_idx.append((i, repo, e["sess"], e["ts"], e["name"], fp, ln))
    # bash.md (commands + outcome)
    with open(os.path.join(rd, "bash.md"), "w") as bf:
        bf.write(f"# Fable bash/exec corpus — {repo}\n\n")
        for e in events:
            if e["k"] == "tool" and e["name"] == "Bash":
                err, res = results.get(e["id"], (None, ""))
                tag = "ERROR" if err else ("ok" if err is False else "?")
                bf.write(f"\n$ {e['summary']}\n  [{tag}] {first_line(res, 240)}\n")
    # prose.md
    with open(os.path.join(rd, "prose.md"), "w") as pf:
        pf.write(f"# Fable prose/text output — {repo}\n\n")
        for e in events:
            if e["k"] == "text":
                pf.write(f"\n--- {e['ts']} (sidechain={e['side']}) ---\n{e['text'][:2500]}\n")
    # timeline.md (interleaved operate loop)
    with open(os.path.join(rd, "timeline.md"), "w") as tf:
        tf.write(f"# Fable operate-loop timeline — {repo}\n\n")
        for e in events:
            if e["k"] == "text":
                tf.write(f"\n[SAY] {first_line(e['text'], 300)}\n")
            else:
                if e["name"] == "Bash":
                    err, res = results.get(e["id"], (None, ""))
                    tag = "ERR" if err else "ok"
                    tf.write(f"  [DO] Bash: {first_line(e['summary'],160)}  -> {tag}\n")
                elif e["name"] in CODE_TOOLS:
                    nb = sum((b.count(chr(10)) + 1) for _, b in e.get("blobs", []) if b.strip())
                    tf.write(f"  [DO] {e['name']}: {e['summary']} ({nb} lines)\n")
                else:
                    tf.write(f"  [DO] {e['name']}: {first_line(e['summary'],140)}\n")
    return code_idx


def main():
    os.makedirs(OUT, exist_ok=True)
    manifest = {}
    all_idx = []
    targets = OrderedDict(REPOS)
    targets["tmp-exports"] = None  # handled specially
    for repo, d in REPOS.items():
        events, results = collect([d])
        idx = write_repo(repo, events, results)
        all_idx += idx
        manifest[repo] = {
            "text_blocks": sum(1 for e in events if e["k"] == "text"),
            "tool_calls": sum(1 for e in events if e["k"] == "tool"),
            "code_edits": len(idx),
            "bash_calls": sum(1 for e in events if e["k"] == "tool" and e["name"] == "Bash"),
            "tools_breakdown": dict(_tool_breakdown(events)),
        }
    # tmp exports combined
    ev, rs = collect(TMP_GLOBS)
    idx = write_repo("tmp-exports", ev, rs)
    all_idx += idx
    manifest["tmp-exports"] = {
        "text_blocks": sum(1 for e in ev if e["k"] == "text"),
        "tool_calls": sum(1 for e in ev if e["k"] == "tool"),
        "code_edits": len(idx),
        "bash_calls": sum(1 for e in ev if e["k"] == "tool" and e["name"] == "Bash"),
        "tools_breakdown": dict(_tool_breakdown(ev)),
    }
    with open(os.path.join(OUT, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(OUT, "ALL_CODE_INDEX.tsv"), "w") as f:
        f.write("idx\trepo\tsession\tts\ttool\tfile\tlines\n")
        for row in all_idx:
            f.write("\t".join(str(x) for x in row) + "\n")
    print(json.dumps(manifest, indent=2))


def _tool_breakdown(events):
    d = defaultdict(int)
    for e in events:
        if e["k"] == "tool":
            d[e["name"]] += 1
    return d


if __name__ == "__main__":
    main()
