#!/usr/bin/env python3
"""Sweep skeleton-owned reference files for retired strings (ASK-701).

Pairs with `q-system/.q-system/tests/test_retired_strings_sweep.py`, which holds
the negative self-test: plant a blocking entry into a copy of the tree and this
script must exit non-zero. A sweep nobody has watched go red is decoration.

WHY THIS PATH SET AND NOT THE PIPELINE'S. The retired-set sweeps that already
existed read pipeline prompt constants. Skill references were swept by nothing,
so a retired positioning line sat in founder-voice's voice DNA (voice-dna.md:55)
long after it was taken out of circulation, feeding drafts the publishing engine
then rejected (sp-36788323). Those files are SKELETON-owned: `kipi update` rsyncs
`plugins/*/` down into every instance, so an instance-side check could only ever
flag copy the instance is not allowed to fix. The skeleton is the chokepoint, so
the check lives here.

Tier is derived, never stored: a match of `voicekit.echo.NGRAM` words or more is
a lift and fails; anything shorter is reported and passes. `echo` already owns
"long enough that a shared idiom cannot fire, short enough that a lifted sentence
cannot hide" -- reusing its number keeps one definition instead of two.

Exit codes:
  0 = clean, or warn-tier matches only
  1 = at least one blocking retired string is present
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

WHITESPACE = re.compile(r"\s+")

REPO_ROOT = Path(__file__).resolve().parents[3]

# The globs this sweep covers. `plugins/*/skills/*/references/` is the gap ASK-701
# closed; add a glob here rather than teaching callers to pass paths, so the
# covered set stays greppable from one place.
COVERED_GLOBS = (
    "plugins/*/skills/*/references/",
)

FILE_SUFFIXES = (".md", ".txt")

DEFAULT_RETIRED_SET = Path(__file__).resolve().parent / "retired-strings.json"


def _echo_module():
    """voicekit.echo owns the word tokenizer and the lift threshold. Import it
    rather than re-deriving either; a second copy of NGRAM is a second answer."""
    sys.path.insert(0, str(REPO_ROOT / "plugins" / "kipi-core"))
    from voicekit import echo

    return echo


def load_retired(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["retired"]


def covered_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for glob in COVERED_GLOBS:
        for directory in root.glob(glob.rstrip("/")):
            if not directory.is_dir():
                continue
            found.extend(
                p for p in sorted(directory.rglob("*"))
                if p.is_file() and p.suffix in FILE_SUFFIXES
            )
    return found


def flatten(body: str) -> tuple[str, list[int]]:
    """Collapse every whitespace run to one space, and return the line number each
    surviving character came from.

    WHY, and it is the whole point of this function: the corpus this sweeps is
    hard-wrapped markdown prose, so a retired SENTENCE is stored straddling a line
    break far more often than it sits on one physical line. Matching line by line
    would therefore miss the exact shape the files actually store, and the sweep
    would report green on the corpus it was built for. Matching the flattened text
    and mapping the offset back is what makes a wrapped hit reportable at all.
    """
    chars: list[str] = []
    linenos: list[int] = []
    lineno = 1
    i = 0
    while i < len(body):
        run = WHITESPACE.match(body, i)
        if run:
            lineno += body.count("\n", i, run.end())
            # One separator stands in for the run, so a wrap reads as a space.
            # Never lead or trail with it: a match starts on a real character.
            if chars and run.end() < len(body):
                chars.append(" ")
                linenos.append(lineno)
            i = run.end()
            continue
        chars.append(body[i])
        linenos.append(lineno)
        i += 1
    return "".join(chars), linenos


def scan(root: Path, retired: list[dict]) -> tuple[list[str], list[str]]:
    """Returns (blocking, warning) human-readable hit lines."""
    echo = _echo_module()
    blocking: list[str] = []
    warning: list[str] = []

    for path in covered_files(root):
        body = path.read_text(encoding="utf-8", errors="replace")
        flat, linenos = flatten(body)
        for entry in retired:
            needle = WHITESPACE.sub(" ", entry["text"]).strip()
            if not needle:
                continue
            is_lift = len(echo._words(entry["text"])) >= echo.NGRAM
            at = flat.find(needle)
            while at != -1:
                rel = path.relative_to(root)
                hit = (f"{rel}:{linenos[at]}: retired {entry['id']!r} "
                       f"({entry.get('retired_by', 'unknown')})")
                (blocking if is_lift else warning).append(hit)
                at = flat.find(needle, at + 1)

    return blocking, warning


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=str(REPO_ROOT),
                    help="tree to sweep (default: this repo)")
    ap.add_argument("--retired-set", default=str(DEFAULT_RETIRED_SET),
                    help="JSON file that owns the retired strings")
    ap.add_argument("--show-paths", action="store_true",
                    help="print the covered globs and exit 0")
    args = ap.parse_args()

    if args.show_paths:
        for glob in COVERED_GLOBS:
            print(glob)
        return 0

    root = Path(args.root).resolve()
    retired = load_retired(Path(args.retired_set))
    blocking, warning = scan(root, retired)

    for hit in warning:
        print(f"WARN  {hit}")
    for hit in blocking:
        print(f"BLOCK {hit}")

    if blocking:
        print(
            f"\n{len(blocking)} retired string(s) still present. Rewrite the line, "
            f"or drop the entry from {args.retired_set} if it is back in circulation.",
            file=sys.stderr,
        )
        return 1

    scanned = len(covered_files(root))
    print(f"clean: {scanned} file(s) swept, {len(warning)} warn-tier match(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
