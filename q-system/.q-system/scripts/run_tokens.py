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
    bad: list[str] = []
    files = expand(paths, subagents, bad)
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


def record(a) -> int:
    """Append one row {ts, ticket, repo, pr, session, ...tokens} for a worker run.

    Single writer: one O_APPEND write of one short line, so concurrent workers
    interleave whole rows, never bytes. No transcript found is a nonzero exit with a
    named reason, never an all-zero row that reads as a free run.
    """
    import datetime
    import re
    if not a.session or not re.fullmatch(r"[0-9a-fA-F-]{36}", a.session):
        print("run_tokens: --record needs a uuid --session", file=sys.stderr)
        return 1
    hits = sorted((Path.home() / ".claude" / "projects").glob(f"*/{a.session}.jsonl"))
    if not hits:
        print(f"run_tokens: no transcript for session {a.session}", file=sys.stderr)
        return 1
    rep = report([str(hits[0])], subagents=True)
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


#: The plan token cap (ASK-4721). Tracked beside this script so a change to the cap
#: is a reviewed diff, and the pinned dispatcher checkout reads origin/main's copy.
DEFAULT_CAP_FILE = Path(__file__).resolve().parent.parent / "run-token-cap.json"
WEIGHT_KEYS = {"input": "input_tokens", "cache_read": "cache_read_tokens",
               "cache_write": "cache_write_tokens", "output": "output_tokens"}
CAP_RUN, CAP_OVER, CAP_BROKEN = 0, 3, 2


def _load_cap(path: Path) -> tuple[dict | None, str]:
    """(config, "") or (None, reason). Every field is checked: a cap file the brake
    half-understands is a brake set to a number nobody wrote down."""
    try:
        cfg = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return None, f"cannot read cap file {path}: {exc}"
    w = cfg.get("weights") if isinstance(cfg, dict) else None
    wins = cfg.get("windows") if isinstance(cfg, dict) else None
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    if not isinstance(w, dict) or set(w) != set(WEIGHT_KEYS) or not all(num(v) and v >= 0 for v in w.values()):
        return None, f"cap file {path}: weights must be exactly {sorted(WEIGHT_KEYS)}, each a number >= 0"
    if not isinstance(wins, list) or not wins or not all(
            isinstance(x, dict) and num(x.get("hours")) and x["hours"] > 0 and num(x.get("cap")) and x["cap"] > 0
            for x in wins):
        return None, f"cap file {path}: windows must be a non-empty list of {{hours > 0, cap > 0}}"
    return cfg, ""


def cap_check(ledger: str, cap_file: str | None = None, now: str | None = None) -> int:
    """Exit 0 run, 3 over the cap, 2 broken. One line on stdout either way.

    The unit is WEIGHTED tokens, not total processed tokens. A worker run is about 97%
    cache reads by count (2026-11-12: 7.6M read, 0.19M written, 21k out), and the plan
    meters compute, not token count: at API prices a cache read is a tenth of an input
    token on claude-opus-5 (the worker default) and output is five. Counting raw tokens
    would let 1M output tokens through as if they were 1M cache reads, a 50x error in
    the direction of draining. The weights live in the cap file, beside the cap.
    """
    import datetime
    # KIPI_RUN_TOKEN_CAP_FILE is the test seam: the callers pass no --cap-file, so a
    # test of the dispatcher's broken-cap branch needs a way in that is not the repo file.
    cap_file = cap_file or os.environ.get("KIPI_RUN_TOKEN_CAP_FILE")
    cfg, why = _load_cap(Path(cap_file).expanduser() if cap_file else DEFAULT_CAP_FILE)
    if cfg is None:
        print(f"run_tokens cap: BROKEN: {why}")
        return CAP_BROKEN
    t_now = (datetime.datetime.fromisoformat(now) if now
             else datetime.datetime.now(datetime.timezone.utc))
    path = Path(ledger).expanduser()
    if not path.exists():
        # Not "0 of cap": no ledger means nothing has ever been measured, and a brake
        # with no meter must say so, not look green (the UNMETERED line of ASK-4721).
        print(f"run_tokens cap: UNMETERED: no ledger at {path}; the plan cap cannot brake runs it never saw")
        return CAP_RUN
    rows, bad = [], 0
    try:
        with path.open() as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                    ts = datetime.datetime.fromisoformat(r["ts"])
                except (ValueError, KeyError, TypeError):
                    bad += 1
                    continue
                rows.append((ts, r))
    except OSError as exc:
        # The dispatcher is the fail-closed chokepoint: a meter it cannot read is not a
        # meter reading zero.
        print(f"run_tokens cap: BROKEN: cannot read ledger {path}: {exc}")
        return CAP_BROKEN
    if not rows:
        print(f"run_tokens cap: UNMETERED: zero readable rows in {path} ({bad} malformed)")
        return CAP_RUN
    w = cfg["weights"]
    parts, over = [], False
    for win in cfg["windows"]:
        start = t_now - datetime.timedelta(hours=win["hours"])
        # No upper bound: a row stamped ahead of this clock still counts. Skew must
        # fail toward braking, never toward a free run.
        used = sum(sum(w[k] * _num(r.get(f)) for k, f in WEIGHT_KEYS.items())
                   for ts, r in rows if ts >= start)
        hit = used >= win["cap"]
        over = over or hit
        parts.append(f"{win['hours']:g}h {used / 1e6:.1f}M of {win['cap'] / 1e6:.1f}M{' OVER' if hit else ''}")
    tail = f"; {bad} malformed row(s) skipped" if bad else ""
    label = cfg.get("status", "")
    print(f"run_tokens cap: {'OVER' if over else 'under'}: weighted tokens {', '.join(parts)}"
          f"{' (' + label + ')' if label else ''}{tail}")
    return CAP_OVER if over else CAP_RUN


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", help="transcript .jsonl files or directories")
    # --cap-check is the plan brake (ASK-4721): kipi-dispatch.sh and linear-worker.sh
    # read the --record ledger through it before spending more of the plan.
    ap.add_argument("--cap-check", metavar="LEDGER.jsonl", help="exit 0 under the cap, 3 over, 2 broken")
    ap.add_argument("--cap-file", help="cap config (default: q-system/.q-system/run-token-cap.json)")
    ap.add_argument("--now", help="ISO timestamp for --cap-check (tests); default now, UTC")
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
    if a.cap_check:
        return cap_check(a.cap_check, a.cap_file, a.now)
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
