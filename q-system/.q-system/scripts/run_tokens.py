#!/usr/bin/env python3
"""run_tokens: what did a run cost in TOKENS, read from Claude Code transcripts (ASK-4649).

Reports tokens only, never dollars. Prices move; token counts do not.

The dedup rule is ported from Sagargupta16/claude-cost-optimizer
tools/claude-rate/rate.py (MIT), `_keep_latest` / `_transcript_entry`. The
pricing table is not ported.

Why each message id counts once, at its largest snapshot: Claude Code writes one
transcript record per content block of a response, all with the same message id.
Their usage blocks are snapshots taken as the response grows, so the first can
undercount output. Summing records instead of ids double counts; taking the first
undercounts. Measured on chief's build set (2026-11-11/12): see the PR.

Input: transcript JSONL paths and/or directories (a directory is searched
recursively, so a session directory yields its subagent transcripts).
`--subagents` also adds <stem>/subagents/*.jsonl beside each given file.
A path of "-" reads concatenated transcripts from stdin (one pseudo-file).
Output: one JSON object on stdout. `--by-agent` adds a per-transcript breakdown.
Exit 0 on a read with at least one request; exit 1 on zero requests (empty or
malformed input must not look like a clean zero).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CTX_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def expand(paths: list[str], subagents: bool) -> list[Path]:
    """Files to read, in order, each once."""
    out: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path) -> None:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            out.append(p)

    for raw in paths:
        if raw == "-":  # stdin, e.g. `find <dir> -name '*.jsonl' -exec cat {} +`
            out.append(Path("-"))
            continue
        p = Path(raw).expanduser()
        if p.is_dir():
            for f in sorted(p.rglob("*.jsonl")):
                add(f)
        else:
            add(p)
            if subagents:
                side = p.parent / p.stem / "subagents"
                if side.is_dir():
                    for f in sorted(side.rglob("*.jsonl")):
                        add(f)
    return out


def _num(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def read_best(files: list[Path], unreadable: list[str] | None = None) -> dict[str, tuple[dict, str]]:
    """message id -> (largest-output usage snapshot, file it came from).

    A file that cannot be opened is named in `unreadable`, never skipped silently:
    a partial read that exits 0 lets a cap check pass on most of the data (review of #765).
    """
    best: dict[str, tuple[dict, str]] = {}
    for f in files:
        try:
            handle = sys.stdin.buffer if str(f) == "-" else f.open("rb")
        except OSError:
            if unreadable is not None:
                unreadable.append(str(f))
            continue
        with handle:
            for raw in handle:
                if b'"usage"' not in raw or b'"assistant"' not in raw:
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(rec, dict) or rec.get("type") != "assistant" or rec.get("isApiErrorMessage"):
                    continue
                msg = rec.get("message")
                if not isinstance(msg, dict) or not msg.get("id"):
                    continue
                usage = msg.get("usage")
                model = msg.get("model") or ""
                if not isinstance(usage, dict) or model.startswith("<"):
                    continue
                held = best.get(msg["id"])
                # strictly greater: a tie keeps the first snapshot seen
                if held is None or _num(usage.get("output_tokens")) > _num(held[0].get("output_tokens")):
                    best[msg["id"]] = (usage, str(f))
    return best


def _pct(sorted_vals: list[int], q: float) -> int:
    """Nearest-rank percentile."""
    if not sorted_vals:
        return 0
    import math
    return sorted_vals[max(0, math.ceil(q * len(sorted_vals)) - 1)]


def summarize(items: list[dict]) -> dict:
    ctx = sorted(sum(_num(u.get(k)) for k in CTX_KEYS) for u in items)
    mid = len(ctx) // 2
    median = 0 if not ctx else (ctx[mid] if len(ctx) % 2 else (ctx[mid - 1] + ctx[mid]) // 2)
    return {
        "requests": len(items),
        "input_tokens": sum(_num(u.get("input_tokens")) for u in items),
        "cache_read_tokens": sum(_num(u.get("cache_read_input_tokens")) for u in items),
        "cache_write_tokens": sum(_num(u.get("cache_creation_input_tokens")) for u in items),
        "output_tokens": sum(_num(u.get("output_tokens")) for u in items),
        "context_median": median,
        "context_p90": _pct(ctx, 0.9),
    }


def report(paths: list[str], by_agent: bool = False, subagents: bool = False) -> dict:
    files = expand(paths, subagents)
    bad: list[str] = []
    best = read_best(files, bad)
    out = summarize([u for u, _ in best.values()])
    out["transcripts"] = len(files)
    out["unreadable"] = bad
    if by_agent:
        groups: dict[str, list[dict]] = {}
        for u, f in best.values():
            groups.setdefault(f, []).append(u)
        out["by_agent"] = {f: summarize(g) for f, g in sorted(groups.items())}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+", help="transcript .jsonl files or directories")
    ap.add_argument("--by-agent", action="store_true")
    ap.add_argument("--subagents", action="store_true", help="also read <stem>/subagents/ beside each file")
    a = ap.parse_args(argv)
    rep = report(a.paths, a.by_agent, a.subagents)
    print(json.dumps(rep))
    if rep["unreadable"]:
        print(f"run_tokens: {len(rep['unreadable'])} transcript(s) could not be opened", file=sys.stderr)
        return 1
    if rep["requests"] == 0:
        print("run_tokens: zero requests read (empty, malformed or wrong path)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
