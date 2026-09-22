#!/usr/bin/env python3
"""decision-corpus-cost.py -- what it would cost, per turn, to load the
decision corpus on every turn.

Plan item 2h of prd-morning-brief-learns-2026-09-01: Grace Clark's
think-like-me corpus "autofires in almost every single thing" she does. This
system's equivalent already exists (pov.md, identity.md, scars.md in the
voice corpus) but loads only on writing requests. Widening that trigger to
every turn has a token cost on every turn; the plan asked for the number
before the decision, not an argument.

The formula is stated in the output and is the whole point of Codex finding-16
on the PRD: tokens = ceil(bytes / 4). It is an approximation with no tokenizer
dependency, so two runs on the same corpus agree by construction and the
number is reproducible. It is not a billing figure.

Exit 3 when KIPI_VOICE_DIR is unset or a corpus file is missing: an absent
apparatus never prints a zero (skill-trigger-eval.py posture).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

FILES = ("pov.md", "identity.md", "scars.md")
FORMULA = "tokens = ceil(bytes / 4)"
EXIT_OK, EXIT_BROKEN = 0, 3


def measure(voice_dir: Path) -> dict:
    per_file, missing = {}, []
    for name in FILES:
        path = voice_dir / name
        if not path.is_file():
            missing.append(name)
            continue
        size = path.stat().st_size
        per_file[name] = {"bytes": size, "tokens": math.ceil(size / 4)}
    total_bytes = sum(v["bytes"] for v in per_file.values())
    return {"voice_dir": str(voice_dir), "files": per_file, "missing": missing,
            "total_bytes": total_bytes, "total_tokens": math.ceil(total_bytes / 4), "formula": FORMULA}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="per-turn cost of loading the decision corpus (advisory)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    raw = os.environ.get("KIPI_VOICE_DIR", "").strip()
    if not raw:
        sys.stderr.write("error: KIPI_VOICE_DIR is unset. Refusing to report a misleading cost.\n")
        return EXIT_BROKEN
    result = measure(Path(raw).expanduser())
    if result["missing"]:
        sys.stderr.write(f"error: missing corpus file(s) under {raw}: {', '.join(result['missing'])}. "
                         "Refusing to report a partial cost as the cost.\n")
        return EXIT_BROKEN
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for name, v in result["files"].items():
            print(f"{name:<12} {v['bytes']:>7} bytes  ~{v['tokens']:>6} tokens")
        print(f"{'total':<12} {result['total_bytes']:>7} bytes  ~{result['total_tokens']:>6} tokens per turn if loaded every turn")
        print(f"formula: {FORMULA}  (approximation, reproducible, not a billing figure)")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
