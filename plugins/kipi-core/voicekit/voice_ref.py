#!/usr/bin/env python3
"""Print the voice reference for ONE piece of writing. A CALLER, not a selector.

Every decision belongs to voicekit: `assemble.voice_section` builds the section
(identity, pov, lexicon, correction SCOPES, exemplars) and `selector` decides which
rows ride in it. This file resolves the corpus, asks, and prints.

why the boundary is stated this hard: version one of this file WAS a second
selector with its own rotation and its own random sampling, written before I found
voicekit. Version two still rebuilt identity and corrections by hand, which quietly
dropped correction `scope` -- a correction withheld from the model was still shown.
Both are the same shape as two voice corpora, which took a night to kill
(ASK-699, 2026-08-13). A duplicate that agrees today is still a duplicate.

Usage:
    python3 scripts/voice_ref.py --channel x --words 480   # long-form register
    python3 scripts/voice_ref.py --channel x --words 25    # DM / comment register
    python3 scripts/voice_ref.py --channel linkedin --words 200
    python3 scripts/voice_ref.py --channel x --words 480 --ids-only
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# LIVES BESIDE THE ENGINE, and that placement is the fix (ASK-710, 2026-08-14).
# It used to sit at social-voice/scripts/voice_ref.py while voice-dna-loader.py --
# which ships to EVERY instance via the skeleton -- told agents to run
# "<project root>/scripts/voice_ref.py". That path exists in exactly one repo, so
# on every other instance the runtime named a selector that was not there and the
# length matching silently never ran. A caller that does not travel with its
# engine is not wired; it is wired on one machine.
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
# voicekit ships in this repo's kipi-core plugin. Import from HERE, never from
# whatever the caller's cwd exposes, so the answer cannot change with the directory
# the founder happened to run from.
sys.path.insert(0, str(PLUGIN_ROOT))

from voicekit import assemble, corpus, selector  # noqa: E402

DEFAULT_CORPUS = Path.home() / "projects" / "consulting" / "q-consult" / "voice"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True, choices=["x", "linkedin"])
    ap.add_argument("--words", type=int, required=True,
                    help="target length of the piece being written")
    ap.add_argument("-k", type=int, default=selector.DEFAULT_K)
    ap.add_argument("--counter", type=int, default=0,
                    help="rotation position; the engine passes the postbook count")
    ap.add_argument("--slot-kind", default="post", choices=["post", "comment"])
    ap.add_argument("--ids-only", action="store_true")
    args = ap.parse_args()

    path = Path(os.environ.get("KIPI_VOICE_DIR") or DEFAULT_CORPUS)
    if not (path / "exemplars.jsonl").exists():
        # Loud, never an empty reference. A blank voice section still produces
        # writing; it just produces it in nobody's voice, and nothing would say so.
        sys.exit(f"voice corpus missing: {path / 'exemplars.jsonl'}\n"
                 f"set $KIPI_VOICE_DIR if it moved. Refusing to write without it.")

    voice = corpus.load(str(path))
    rows = voice.active_exemplars()
    if not rows:
        sys.exit(f"{path} has no active exemplars. Refusing.")

    text, provenance = assemble.voice_section(
        voice, args.channel, args.counter, k=args.k,
        slot_kind=args.slot_kind, target_words=args.words)

    picked_ids = list(provenance.get("exemplar_ids") or [])
    if not picked_ids:
        sys.exit(f"no exemplar matched channel={args.channel} words={args.words}.")

    if args.ids_only:
        print(" ".join(str(i) for i in picked_ids))
        return 0

    # The denominator, derived the SAME way the selector derives it (resolved_pool
    # then length_band), not recounted by hand. A checker that reimplements the rule
    # it checks is testing its own copy -- voicekit's own docstring makes that point
    # about its validators, and version two of this file made exactly that mistake.
    pool = selector.resolved_pool(rows, args.channel, args.slot_kind, args.k,
                                  args.words)
    band = selector.length_band(pool, args.words)
    kind = "long" if args.words >= selector.LONG_WORDS else "short"

    print(f"# VOICE REFERENCE ({args.channel}, {kind}-form, target {args.words} words)\n")
    print(f"> pool: {len(band)} {kind}-form {args.channel} row(s) eligible; "
          f"showing {len(picked_ids)}.")
    if len(band) == 1:
        print("> ONE sample is not a register. Bank more before trusting this.")
    print(f"> {selector.selection_reason([{'id': i} for i in picked_ids], args.channel, args.counter)}")
    print()
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
