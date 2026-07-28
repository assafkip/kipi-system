#!/usr/bin/env python3
"""handoff-provenance-lint: an inherited claim must not be indistinguishable from a
verified one.

WHY (RCA rca-conclusions-before-evidence-2026-07-28, root cause #4): "last-handoff.md
mixed verified measurements with unverified inferences in one prose voice. Reversal #5
rode in on that. A reader cannot distinguish 'recomputed from the export' from
'inferred last Tuesday' because the format has no field for it. `{{UNVALIDATED}}`
exists as a convention but was not applied on write, and nothing checks for its
absence."

Reversal #5 was a claim that a client row was dated five months in the future. It was
inherited verbatim from the handoff and repeated as fact across several turns of the
next session. Recomputation showed no such row existed. The next session had no way to
see it was reading an inference.

So: in a handoff, any line carrying a measurement-shaped number (2+ significant
digits, ISO dates excluded) must also carry its provenance. Three accepted forms:

  [verified: <what you ran>]   a command was run and this is its output
  ev-xxxxxxxxxx                a claim id from canonical/evidence.jsonl (strongest)
  {{UNVERIFIED}} / {{UNVALIDATED}} / {{NEEDS_PROOF}}   an inference, labelled as one

The third is not a lesser option. Labelling an inference is the correct move; the
defect is prose that hides which kind of statement it is making.

Scope: PostToolUse(Write|Edit|MultiEdit) on `memory/last-handoff.md`. Everything else
exits 0 immediately.

HONEST BOUNDARY: this checks that a line DECLARES its provenance, not that the
declaration is true. `[verified: I checked]` passes and proves nothing. It removes the
ambiguity, not the possibility of lying. It is also blind to a false claim carrying no
numbers -- "nobody works in that sheet" (reversal #6) would pass this lint untouched.

Bypass: put `handoff-provenance-skip` in the file.
Contract: reads hook JSON on stdin. exit 0 = pass, exit 2 = block. stdlib only.
Self-test: `python3 test_handoff_provenance_lint.py`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCOPE = "memory/last-handoff.md"
SKIP_MARKER = "handoff-provenance-skip"

# A date in a HEADER is metadata; a date asserted in a finding is a measurement.
# Reversal #5 was exactly that -- "a row is dated 2026-12-21, five months in the
# future" -- so stripping every date would blind this lint to its own scar. Only
# metadata lines are exempt, and they are recognised by shape, not by guessing.
META_RE = re.compile(
    r"^\s*[*_#>\-]*\s*\**\s*(date|session|updated|last updated|as of|generated"
    r"|created|handoff|author)\s*\**\s*:", re.IGNORECASE)
NUM_RE = re.compile(r"(?<![\w.$-])(\d[\d,]*\.?\d*)(?![\w-])")
# Matched separately: NUM_RE's hyphen boundaries deliberately reject `2026-12-21`, so
# a date-shaped claim would slip through the number scan that is supposed to catch it.
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
MIN_SIGNIFICANT_DIGITS = 2

PROVENANCE_RE = re.compile(
    r"\[verified:|\{\{UNVERIFIED\}\}|\{\{UNVALIDATED\}\}|\{\{NEEDS_PROOF\}\}"
    r"|\bev-[0-9a-f]{10}\b")


def unlabelled_lines(body: str) -> list[tuple[int, str]]:
    """(line number, text) for every measurement-shaped line with no provenance."""
    if SKIP_MARKER in body:
        return []
    out = []
    for n, line in enumerate(body.splitlines(), 1):
        if PROVENANCE_RE.search(line) or META_RE.match(line):
            continue
        if DATE_RE.search(line):
            out.append((n, line.strip()))
            continue
        for m in NUM_RE.finditer(line):
            digits = m.group(1).replace(",", "").replace(".", "").lstrip("0")
            if len(digits) >= MIN_SIGNIFICANT_DIGITS:
                out.append((n, line.strip()))
                break
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    ti = payload.get("tool_input") or {}
    fp = ti.get("file_path") or ti.get("path") or ""
    if not fp or SCOPE not in fp.replace("\\", "/"):
        return 0

    try:
        body = Path(fp).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0

    bad = unlabelled_lines(body)
    if not bad:
        return 0

    listed = "\n".join(f"    line {n}: {text[:110]}" for n, text in bad[:15])
    sys.stderr.write(
        "HANDOFF PROVENANCE (blocked): these lines carry a number with no source, so "
        "the next session cannot tell a measurement from a guess:\n" + listed + "\n\n"
        "  Add one of:\n"
        "    [verified: <the command you ran>]   you ran something and this is it\n"
        "    ev-xxxxxxxxxx                       a claim id from evidence.jsonl\n"
        "    {{UNVERIFIED}}                      it is an inference, and that is fine\n\n"
        "  Scar 2026-07-28: a handoff claimed a client row was dated five months in "
        "the future. The next session inherited it, repeated it as fact for several "
        "turns, and only checked when the founder asked. No such row existed. The "
        "handoff had no field to say which claims had been recomputed.\n"
        f"  Deliberate exception: add `{SKIP_MARKER}` to the file.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
