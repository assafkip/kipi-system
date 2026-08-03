#!/usr/bin/env python3
"""Classify every open spillover finding by whether its SUBJECT still exists.

Pairs with PRD prd-finding-quality-bar-2026-08-03 (ASK-337).

why: 476 open findings, 75 resolved all time. Many name code that has since been
deleted, renamed or inlined -- those are dead and can go. But a single-root
`os.path.exists()` check said 209 were gone, and reading them showed most were
alive somewhere else in the fleet or named a module rather than a file. A wrong
bulk void destroys the signal the ledger exists to keep.

So: resolve every named subject against EVERY fleet root, and classify into
THREE buckets, never two.

  still-exists    the subject was found; the finding may well be live
  confirmed-gone  a well-formed subject that exists in NO fleet root
  unresolvable    no subject could be extracted at all

why three (scar sp-5b736e86 / ASK-327): capability-gate.py printed a per-test
TIMEOUT identically to a FAILURE, and it cost real hours hunting breakage in
healthy tests. An ABSENT result is not a NEGATIVE result. `unresolvable` must
never be voided as `confirmed-gone` -- 2026-08-03 measurement showed that class
is mostly REAL findings naming a component rather than a file.

Read-only by default. `--apply` voids ONLY `confirmed-gone`, one recorded
reason per row. Founder authorized delete-and-record 2026-08-03.

Usage:
  spillover-validate.py                 # dry run, prints the proposal
  spillover-validate.py --json          # machine-readable
  spillover-validate.py --apply         # void confirmed-gone only
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
SKELETON = HERE.parents[3]

# A path claim: has a code extension.
PATH_RE = re.compile(r"\b([\w.-]+(?:/[\w.-]+)*\.(?:py|sh|js|ts|json|jsonl|md|yml|yaml|toml))\b")
# A module / dotted symbol / function call.
SYMBOL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{3,})(?:\.[a-z_]+|\(\))")
# A directory-ish path with no extension.
DIR_RE = re.compile(r"\b((?:[\w.-]+/){1,}[\w.-]+)\b")

# Tokens that are English, not code. Without this, "the.py" style false hits and
# common words like `status` or `config` mark everything still-exists.
NOISE = {"the", "this", "that", "and", "for", "with", "from", "into", "when",
         "then", "than", "which", "where", "there", "here", "what", "does",
         "should", "would", "could", "every", "never", "always", "because"}


def fleet_roots() -> list:
    """Every repo the fleet knows about, so a subject alive in ANOTHER repo is
    never called gone. A single-root check is the whole reason the first count
    (209) was untrustworthy."""
    roots = {SKELETON}
    reg = SKELETON / "instance-registry.json"
    if reg.is_file():
        try:
            data = json.loads(reg.read_text())
        except json.JSONDecodeError:
            data = {}
        entries = data.get("instances", data) if isinstance(data, dict) else data
        if isinstance(entries, dict):
            entries = list(entries.values())
        for e in entries or []:
            p = e.get("path") if isinstance(e, dict) else e
            if p:
                q = Path(os.path.expanduser(str(p)))
                if q.is_dir():
                    roots.add(q)
    return sorted(roots)


def tracked_index(root: Path) -> tuple:
    """(basenames, stems) of tracked files. One git call per root."""
    names = set()
    try:
        out = subprocess.run(["git", "ls-files"], cwd=str(root),
                             capture_output=True, text=True, timeout=60)
        if out.returncode == 0:
            names = {os.path.basename(l) for l in out.stdout.splitlines() if l.strip()}
    except (OSError, subprocess.TimeoutExpired):
        pass
    stems = {os.path.splitext(n)[0] for n in names}
    return names, stems


def subjects(desc: str) -> list:
    """Every concrete thing this finding claims to be about."""
    text = desc or ""
    out = []
    for m in PATH_RE.findall(text):
        out.append(("path", m))
    for m in SYMBOL_RE.findall(text):
        if m.lower() not in NOISE:
            out.append(("symbol", m))
    for m in DIR_RE.findall(text):
        if "." not in os.path.basename(m):
            out.append(("dir", m))
    return out


def classify(desc: str, roots: list, index: dict) -> tuple:
    """(bucket, reason). Any single surviving subject means still-exists."""
    subs = subjects(desc)
    if not subs:
        return "unresolvable", "no file, module or directory named in the text"
    checked = []
    for kind, tok in subs:
        base = os.path.basename(tok)
        for root in roots:
            names, stems = index[root]
            if (root / tok).exists():
                return "still-exists", f"{tok} exists in {root.name}"
            if kind == "path" and base in names:
                return "still-exists", f"{base} tracked in {root.name}"
            if kind == "symbol" and (tok in stems or tok in names):
                return "still-exists", f"module {tok} tracked in {root.name}"
        checked.append(tok)
    return "confirmed-gone", ("named subject(s) found in no fleet root: "
                              + ", ".join(sorted(set(checked))[:5]))


def load(ledger: Path) -> dict:
    rows = {}
    if not ledger.is_file():
        return rows
    for line in ledger.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows[r["id"]] = r
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", default=str(SKELETON))
    ap.add_argument("--apply", action="store_true",
                    help="void confirmed-gone rows (records a reason on each)")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args()

    root = Path(args.repo_root).resolve()
    ledger = root / ".prd-os" / "spillover.jsonl"
    rows = load(ledger)
    openv = [r for r in rows.values() if r.get("status") == "open"]
    if not openv:
        print("no open spillover items")
        return 0

    roots = fleet_roots()
    index = {rt: tracked_index(rt) for rt in roots}

    buckets = {"still-exists": [], "confirmed-gone": [], "unresolvable": []}
    for r in openv:
        b, why = classify(r.get("description", ""), roots, index)
        buckets[b].append((r, why))

    if args.as_json:
        print(json.dumps({k: [{"id": r["id"], "reason": w} for r, w in v]
                          for k, v in buckets.items()}, indent=1))
        return 0

    print(f"ledger: {ledger}")
    print(f"fleet roots checked: {len(roots)}")
    for rt in roots:
        print(f"  - {rt}")
    print(f"\nopen: {len(openv)}")
    for k in ("still-exists", "confirmed-gone", "unresolvable"):
        print(f"  {k:16} {len(buckets[k])}")

    print("\n== PROPOSED VOID (confirmed-gone only) ==")
    for r, why in buckets["confirmed-gone"]:
        print(f"  {r['id']}: {why}")
        print(f"      {(r.get('description') or '')[:100]}")
    print("\n== NOT PROPOSED: unresolvable ==")
    print("  These name no concrete subject. Measured 2026-08-03: this class is")
    print("  mostly REAL findings naming a component rather than a file, so it is")
    print("  never auto-voided. An absent result is not a negative result.")
    for r, _ in buckets["unresolvable"][:10]:
        print(f"  {r['id']}: {(r.get('description') or '')[:90]}")
    if len(buckets["unresolvable"]) > 10:
        print(f"  ...and {len(buckets['unresolvable']) - 10} more")

    if not args.apply:
        before = ledger.stat().st_size
        print(f"\nDRY RUN. Nothing written (ledger {before} bytes, unchanged).")
        print("Re-run with --apply to void the confirmed-gone rows.")
        return 0

    runner = root / "plugins/prd-os/scripts/prd_runner.py"
    voided = 0
    for r, why in buckets["confirmed-gone"]:
        reason = (f"Auto-voided by spillover-validate.py 2026-08-03: {why}. "
                  f"Checked against {len(roots)} fleet roots by path, tracked "
                  f"basename and module stem. Founder authorized delete-and-record. "
                  f"Original text preserved: {(r.get('description') or '')[:400]}")
        res = subprocess.run([sys.executable, str(runner), "--repo-root", str(root),
                              "spillover", "resolve", r["id"], "--void", reason],
                             capture_output=True, text=True)
        if res.returncode == 0:
            voided += 1
        else:
            print(f"  FAILED {r['id']}: {res.stderr.strip()[:120]}")
    print(f"\nvoided {voided} of {len(buckets['confirmed-gone'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
