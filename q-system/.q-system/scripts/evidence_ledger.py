#!/usr/bin/env python3
"""evidence_ledger: the durable store of verified facts, and the single writer to it.

WHY (RCA rca-conclusions-before-evidence-2026-07-28): six conclusions were delivered
in settled language and reversed later in the same session by evidence available from
the first minute. One reached a client email draft. Measurements survived
recomputation; inferences did not. This module stores only the survivors, and it
cannot store anything else: a row without a `command` and a `result` is refused, so an
inference cannot be written in the shape of a measurement.

Lesson applied: "store the evidence, derive the conclusions". `system-map.md` and any
client-facing draft become DERIVED views of this file, not independent prose.

HONEST BOUNDARY (stated so this is not theater): this module guarantees that a stored
row records a command and its output. It does NOT verify the command was actually run,
that its output was transcribed faithfully, or that the claim follows from the result.
Those are behavioral. What it removes is the ability to be ambiguous about which kind
of statement you are making.

Layout: `<instance-root>/canonical/evidence.jsonl`, append-only JSONL, one verified
fact per line:
  {claim_id, claim, source, command, result, verified_at}

CLI:
  python3 evidence_ledger.py add --claim C --source S --command CMD --result R
  python3 evidence_ledger.py list [--json]
  python3 evidence_ledger.py check          # exit 2 if any row is malformed
  python3 evidence_ledger.py resolve FILE   # exit 2 if a number/quote does not trace

stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_FIELDS = ("claim_id", "claim", "source", "command", "result", "verified_at")

# A number a client would act on. Single digits are list markers and ordinals far more
# often than claims, so the floor is 2 significant digits. Stated hole, not a silent one.
NUM_RE = re.compile(r"(?<![\w.$])(\d[\d,]*\.?\d*)(?![\w])")
MIN_SIGNIFICANT_DIGITS = 2

# A date is not a measurement a client acts on, and treating it as one made the gate
# unusable (sp-f551ef30, ASK-232): `zach-info-request.md` blocked on ['13','2026'],
# both of which fell out of a date. The only ways past that are to invent ledger rows
# for calendar facts or to bypass the gate -- each worse than the gate not firing.
#
# Two shapes are dropped before the number scan:
#   ISO dates   2026-07-28   removed whole, so 07 and 28 never become "numbers"
#   bare years  1900..2100   a standalone year is a date, not a count
# `13` in "13 workflows" is NOT a date and stays gated. That is the line this draws.
#
# HONEST BOUNDARY: a real measurement that happens to be a 4-digit number in
# 1900..2100 ("2026 orders shipped") is exempted and will pass unbacked. Declared
# hole, not a silent one -- the alternative blocks every draft that names a year.
ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
YEAR_MIN, YEAR_MAX = 1900, 2100


def _is_year(norm: str) -> bool:
    return len(norm) == 4 and norm.isdigit() and YEAR_MIN <= int(norm) <= YEAR_MAX

# A quoted span long enough to be an attribution rather than a turn of phrase.
SPAN_RE = re.compile(r"[\"“]([^\"”\n]{3,300})[\"”]")
MIN_SPAN_WORDS = 4


class LedgerError(Exception):
    """A write that would put an unverifiable row in the ledger."""


# --------------------------------------------------------------------------- paths

def instance_root(repo=None) -> Path:
    """The dir holding this instance's canonical/ content.

    Instances name it per-instance (q-consult/, q-prodigy/); the skeleton uses its own
    q-system/. Prefer a named instance dir, fall back to q-system. One resolver, so no
    caller re-derives the path. Precedent: capability-map-gen.py:390.
    """
    repo = Path(repo or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    named = [p for p in sorted(repo.glob("q-*"))
             if p.is_dir() and p.name != "q-system" and (p / "canonical").is_dir()]
    if named:
        return named[0]
    return repo / "q-system"


def ledger_path(repo=None) -> Path:
    return instance_root(repo) / "canonical" / "evidence.jsonl"


# ---------------------------------------------------------------------- read/write

def read(repo=None) -> list[dict]:
    """Every row, in insertion order. A missing ledger is empty, not an error."""
    path = ledger_path(repo)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue  # `check` reports it; `read` stays usable
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def make_claim_id(claim: str, source: str, command: str) -> str:
    digest = hashlib.sha256(f"{claim}\x00{source}\x00{command}".encode()).hexdigest()
    return f"ev-{digest[:10]}"


def _validate(row: dict) -> list[str]:
    errs = []
    for field in REQUIRED_FIELDS:
        if not str(row.get(field, "")).strip():
            errs.append(f"missing or empty `{field}`")
    return errs


def append_row(repo, row: dict) -> dict:
    """The single write path. Every field required; claim_id unique; append only."""
    errs = _validate(row)
    if errs:
        raise LedgerError(
            "refusing to write an unverifiable evidence row: " + "; ".join(errs) +
            ". A claim with no command and no result is an inference, not a "
            "measurement -- record it as {{UNVERIFIED}} prose instead."
        )
    existing = {r.get("claim_id") for r in read(repo)}
    if row["claim_id"] in existing:
        raise LedgerError(
            f"claim_id {row['claim_id']} is already in the ledger. The ledger is "
            "append-only and single-writer; re-verifying a claim means adding a row "
            "with a new command, not rewriting the old one."
        )
    path = ledger_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return row


def add(repo=None, *, claim: str, source: str, command: str, result: str,
        verified_at: str | None = None) -> dict:
    """Build and append a row. claim_id derives from content, so it is reproducible."""
    row = {
        "claim_id": make_claim_id(claim, source, command),
        "claim": claim,
        "source": source,
        "command": command,
        "result": result,
        "verified_at": verified_at or datetime.now(timezone.utc)
                                             .strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return append_row(repo, row)


def check(repo=None) -> list[str]:
    """Standing validator over the whole file. Returns human-readable problems."""
    path = ledger_path(repo)
    if not path.exists():
        return []
    problems, seen = [], set()
    for n, line in enumerate(path.read_text(encoding="utf-8",
                                            errors="ignore").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception as exc:
            problems.append(f"line {n}: not valid JSON ({exc})")
            continue
        if not isinstance(row, dict):
            problems.append(f"line {n}: row is not an object")
            continue
        for err in _validate(row):
            problems.append(f"line {n}: {err}")
        cid = row.get("claim_id")
        if cid in seen:
            problems.append(f"line {n}: duplicate claim_id {cid}")
        seen.add(cid)
    return problems


# ------------------------------------------------------------------- resolution

def _norm_number(raw: str) -> str:
    """`1,177` and `1177` are the same measurement. Compare on digits."""
    return raw.replace(",", "").rstrip(".").lstrip("0") or "0"


def _evidence_blob(repo=None) -> str:
    return "\n".join(f"{r.get('claim','')}\n{r.get('result','')}\n{r.get('command','')}"
                     for r in read(repo))


def adopted(repo=None) -> bool:
    """Has this instance started keeping a ledger at all?

    WHY (ASK-233): with no ledger, every row lookup misses, so EVERY number in a
    client draft is unbacked and the first write to output/outreach/ blocks on all
    of them at once. The gate was most hostile exactly where it had zero signal to
    offer, which is a wall rather than incremental adoption -- and 21 instances
    received these scripts with no ledger in any of them.

    An absent ledger is now "not adopted yet" and the gate stands down. A ledger
    with even one row means the instance opted in, and enforcement is full strength
    from that point on. The file's existence is the switch.
    """
    return ledger_path(repo).exists()


def resolve_numbers(repo, text: str) -> list[str]:
    """Numbers in `text` that trace to no ledger row. Empty list = everything traces."""
    if not adopted(repo):
        return []
    text = ISO_DATE_RE.sub(" ", text)  # a date is not a measurement; see ISO_DATE_RE
    grounded = {_norm_number(m.group(1)) for m in NUM_RE.finditer(_evidence_blob(repo))}
    missing = []
    for m in NUM_RE.finditer(text):
        norm = _norm_number(m.group(1))
        if len(norm.replace(".", "")) < MIN_SIGNIFICANT_DIGITS:
            continue
        if _is_year(norm):
            continue
        if norm in grounded:
            continue
        missing.append(norm)
    return sorted(set(missing), key=lambda s: (len(s), s))


def resolve_spans(repo, text: str) -> list[str]:
    """Quoted spans in `text` that appear in no ledger row."""
    if not adopted(repo):
        return []
    blob = _evidence_blob(repo).lower()
    missing = []
    for m in SPAN_RE.finditer(text):
        span = m.group(1).strip()
        if len(span.split()) < MIN_SPAN_WORDS:
            continue
        if span.lower() in blob:
            continue
        missing.append(span)
    return sorted(set(missing))


# -------------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=None, help="repo root (default: CLAUDE_PROJECT_DIR)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="append one verified fact")
    for f in ("claim", "source", "command", "result"):
        a.add_argument(f"--{f}", required=True)
    a.add_argument("--verified-at", default=None)

    lst = sub.add_parser("list", help="print the ledger")
    lst.add_argument("--json", action="store_true")

    sub.add_parser("check", help="validate every row; exit 2 on any problem")

    r = sub.add_parser("resolve", help="check a file's numbers and quotes trace to rows")
    r.add_argument("path")

    args = ap.parse_args(argv)
    repo = args.repo

    if args.cmd == "add":
        try:
            row = add(repo, claim=args.claim, source=args.source, command=args.command,
                      result=args.result, verified_at=args.verified_at)
        except LedgerError as exc:
            sys.stderr.write(f"evidence_ledger: {exc}\n")
            return 2
        print(row["claim_id"])
        return 0

    if args.cmd == "list":
        rows = read(repo)
        if args.json:
            print(json.dumps(rows, indent=2, ensure_ascii=False))
        else:
            for row in rows:
                print(f"{row.get('claim_id')}  {row.get('claim')}\n"
                      f"    source : {row.get('source')}\n"
                      f"    command: {row.get('command')}\n"
                      f"    result : {row.get('result')}\n"
                      f"    at     : {row.get('verified_at')}")
        return 0

    if args.cmd == "check":
        problems = check(repo)
        if problems:
            sys.stderr.write("evidence_ledger check FAILED:\n" +
                             "\n".join(f"  - {p}" for p in problems) + "\n")
            return 2
        print(f"evidence_ledger check OK ({len(read(repo))} rows)")
        return 0

    if args.cmd == "resolve":
        text = Path(args.path).read_text(encoding="utf-8", errors="ignore")
        nums = resolve_numbers(repo, text)
        spans = resolve_spans(repo, text)
        if nums or spans:
            sys.stderr.write("evidence_ledger resolve FAILED for " + args.path + "\n")
            for n in nums:
                sys.stderr.write(f"  - number {n} traces to no ledger row\n")
            for s in spans:
                sys.stderr.write(f'  - quote "{s}" traces to no ledger row\n')
            return 2
        print(f"evidence_ledger resolve OK ({args.path})")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
