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
import datetime
import json
import os
import sys
from pathlib import Path

CTX_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def expand(paths: list[str], subagents: bool, unreadable: list[str] | None = None) -> list[Path]:
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
            # os.walk with onerror, never Path.rglob: rglob swallows a directory it
            # cannot list, so a locked dir read as "zero requests, wrong path".
            def _bad(e: OSError) -> None:
                if unreadable is not None:
                    unreadable.append(str(e.filename or p))

            found = [Path(r) / n for r, _, ns in os.walk(p, onerror=_bad) for n in ns if n.endswith(".jsonl")]
            for f in sorted(found):
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


def _when(ts) -> datetime.datetime | None:
    """A record's `timestamp` as an aware datetime, or None when absent or unparseable."""
    if not isinstance(ts, str):
        return None
    try:
        # the "Z" swap keeps this working on Pythons whose fromisoformat predates "Z"
        t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def read_best(files: list[Path],
              unreadable: list[str] | None = None) -> dict[str, tuple[dict, str, datetime.datetime | None]]:
    """message id -> (largest-output usage snapshot, file it came from, earliest timestamp seen).

    A file that cannot be opened is named in `unreadable`, never skipped silently:
    a partial read that exits 0 lets a cap check pass on most of the data (review of #765).
    """
    best: dict[str, tuple[dict, str, datetime.datetime | None]] = {}
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
                ts = _when(rec.get("timestamp"))
                if held is None:
                    best[msg["id"]] = (usage, str(f), ts)
                    continue
                # the request's time is its FIRST snapshot's, whichever snapshot's usage is kept
                first = ts if held[2] is None or (ts is not None and ts < held[2]) else held[2]
                # strictly greater: a tie keeps the first snapshot seen
                if _num(usage.get("output_tokens")) > _num(held[0].get("output_tokens")):
                    best[msg["id"]] = (usage, str(f), first)
                else:
                    best[msg["id"]] = (held[0], held[1], first)
    return best


def _pct(sorted_vals: list[int], q: float) -> int:
    """Nearest-rank percentile."""
    if not sorted_vals:
        return 0
    import math
    return sorted_vals[max(0, math.ceil(q * len(sorted_vals)) - 1)]


def _context_first(items: list[tuple[dict, datetime.datetime | None]]) -> int | None:
    """Context (input + cache read + cache write) of the earliest request by timestamp.

    Why this exists (ASK-4747): the worker's start-up cost was the one row the token
    analysis could not fill (token-drain-analysis-2026-11-12 s.2, "NOT MEASURED, the
    row has no first-request field"), so the lean start-up cut had no before number.
    By timestamp, never by read order: files are read in path order (a session plus
    its subagents, or a sorted directory), so the first record read need not be the
    first request made. None, never 0, when ANY request carries no time: that one may
    be the first (review of #789), and a 0 would read as a free start-up, the same
    lie the exit 1 on zero requests refuses.
    """
    if not items or any(t is None for _, t in items):
        return None
    _, u = min(((t, u) for u, t in items), key=lambda p: p[0])  # min keeps the first of equal times
    return sum(_num(u.get(k)) for k in CTX_KEYS)


def summarize(items: list[tuple[dict, datetime.datetime | None]]) -> dict:
    usages = [u for u, _ in items]
    ctx = sorted(sum(_num(u.get(k)) for k in CTX_KEYS) for u in usages)
    mid = len(ctx) // 2
    median = 0 if not ctx else (ctx[mid] if len(ctx) % 2 else (ctx[mid - 1] + ctx[mid]) // 2)
    return {
        "requests": len(usages),
        "input_tokens": sum(_num(u.get("input_tokens")) for u in usages),
        "cache_read_tokens": sum(_num(u.get("cache_read_input_tokens")) for u in usages),
        "cache_write_tokens": sum(_num(u.get("cache_creation_input_tokens")) for u in usages),
        "output_tokens": sum(_num(u.get("output_tokens")) for u in usages),
        "context_median": median,
        "context_p90": _pct(ctx, 0.9),
        "context_first": _context_first(items),
    }


def report(paths: list[str], by_agent: bool = False, subagents: bool = False,
           start_of: str | None = None) -> dict:
    """`start_of` names the one transcript whose first request is `context_first`."""
    bad: list[str] = []
    files = expand(paths, subagents, bad)
    best = read_best(files, bad)
    out = summarize([(u, t) for u, _, t in best.values()])
    out["transcripts"] = len(files)
    out["unreadable"] = bad
    groups: dict[str, list[tuple[dict, datetime.datetime | None]]] = {}
    for u, f, t in best.values():
        groups.setdefault(f, []).append((u, t))
    if start_of is not None:
        # A run's start-up is ITS OWN transcript's first request. The minimum over the
        # session plus its subagent files reported a subagent's request instead (review of #789).
        out["context_first"] = _context_first(groups.get(start_of, []))
    if by_agent:
        out["by_agent"] = {f: summarize(g) for f, g in sorted(groups.items())}
    return out


def record(a) -> int:
    """Append one row {ts, ticket, repo, pr, session, ...tokens} for a worker run.

    Single writer: one O_APPEND write of one short line, so concurrent workers
    interleave whole rows, never bytes. No transcript found is a nonzero exit with a
    named reason, never an all-zero row that reads as a free run.
    """
    import re
    if not a.session or not re.fullmatch(r"[0-9a-fA-F-]{36}", a.session):
        print("run_tokens: --record needs a uuid --session", file=sys.stderr)
        return 1
    hits = sorted((Path.home() / ".claude" / "projects").glob(f"*/{a.session}.jsonl"))
    if not hits:
        print(f"run_tokens: no transcript for session {a.session}", file=sys.stderr)
        return 1
    rep = report([str(hits[0])], subagents=True, start_of=str(hits[0]))
    if rep["unreadable"] or rep["requests"] == 0:
        print(f"run_tokens: session {a.session}: unreadable or zero requests", file=sys.stderr)
        return 1
    row = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "ticket": a.ticket, "repo": a.repo, "pr": a.pr, "session": a.session, **rep}
    out = Path(a.record).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(row) + "\n").encode())
    finally:
        os.close(fd)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", help="transcript .jsonl files or directories")
    # --record is the worker's caller (ASK-4649/4675): after a run, the WORKER'S SHELL
    # names the session it launched; this finds that transcript and appends ONE row.
    ap.add_argument("--record", metavar="OUT.jsonl", help="append one row for --session to this file")
    ap.add_argument("--session", help="the --session-id the run was started with")
    ap.add_argument("--ticket", default="")
    ap.add_argument("--repo", default="")
    ap.add_argument("--pr", default="")
    ap.add_argument("--by-agent", action="store_true")
    ap.add_argument("--subagents", action="store_true", help="also read <stem>/subagents/ beside each file")
    a = ap.parse_args(argv)
    if a.record:
        return record(a)
    if not a.paths:
        ap.error("give transcript paths, or --record with --session")
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
