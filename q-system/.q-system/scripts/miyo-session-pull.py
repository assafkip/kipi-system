#!/usr/bin/env python3
"""SessionStart hook: pull knowledge-base context from Miyo for the working folder.

Deterministic: runs on every session start inside an indexed scope, no agent
choice involved. Prints a capped digest to stdout; Claude Code injects
SessionStart stdout into session context. Fails open (exit 0, no output) on any
infrastructure error so a missing/down Miyo never breaks a session.

Scope default: only fires when cwd contains '/consulting'. Override with env
MIYO_KB_SCOPE (substring match on cwd) or set MIYO_KB_SCOPE='' to allow anywhere.
"""
import json
import os
import subprocess
import sys

MIYO_BIN = os.environ.get("MIYO_BIN", os.path.expanduser("~/.miyo/bin/miyo"))
DEFAULT_SCOPE = "/consulting/"
LIMIT = int(os.environ.get("MIYO_PULL_LIMIT", "6"))
MAX_CHARS = int(os.environ.get("MIYO_PULL_MAX_CHARS", "1800"))


def scope():
    return os.environ.get("MIYO_KB_SCOPE", DEFAULT_SCOPE)


def in_scope(cwd):
    s = scope()
    if not s:
        return True
    return s in cwd + "/"


def build_queries(cwd):
    project = os.path.basename(cwd.rstrip("/")) or "consulting"
    return [project, f"{project} state decisions open items"]


def run_search(query):
    out = subprocess.run(
        [MIYO_BIN, "search", "--limit", str(LIMIT), "--json", query],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if out.returncode != 0:
        return []
    try:
        data = json.loads(out.stdout)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = data.get("results") or data.get("hits") or []
    results = []
    for r in data[:LIMIT]:
        path = (r.get("file_path") or r.get("path") or "?").strip()
        title = (r.get("title") or os.path.basename(path)).strip()
        snippet = (r.get("snippet") or r.get("content") or "").strip()
        if len(snippet) > 160:
            snippet = snippet[:157] + "..."
        results.append((path, title, snippet))
    return results


def render(cwd, queries, per_query):
    lines = [f"[miyo kb] context pull for {os.path.basename(cwd.rstrip('/'))}"]
    seen = set()
    for q, hits in zip(queries, per_query):
        if not hits:
            continue
        lines.append(f"query: {q}")
        for path, title, snippet in hits:
            if path in seen:
                continue
            seen.add(path)
            line = f"- {path} | {title}" + (f": {snippet}" if snippet else "")
            lines.append(line)
    text = "\n".join(lines)
    if len(text) > MAX_CHARS:
        text = text[: MAX_CHARS - 3].rsplit("\n", 1)[0] + "\n..."
    return text


def main():
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else "{}"
        payload = json.loads(raw) if raw.strip() else {}
        cwd = payload.get("cwd") or os.getcwd()
        if not in_scope(cwd) or not os.path.exists(MIYO_BIN):
            return 0
        queries = build_queries(cwd)
        per_query = [run_search(q) for q in queries]
        if not any(per_query):
            return 0
        print(render(cwd, queries, per_query))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
