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

Scope: PostToolUse(Write|Edit|MultiEdit) on three surfaces, two postures. Everything
else exits 0 immediately.

  exit 2   `memory/last-handoff.md`, and any session handoff `HANDOFF-*.md`
  exit 0   an auto-memory content file under `~/.claude/projects/<slug>/memory/`

Both postures are branches of `scope_mode()` in this file, which is the executable;
`test_handoff_provenance_lint.py` pins each branch. A session handoff is the same
artifact class as `last-handoff.md` written by a different command, so it gets the
same exit code. Auto-memory does not, and the split is measured rather than
reasoned -- see AUTO-MEMORY IS ADVISORY below.

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

SKIP_MARKER = "handoff-provenance-skip"

MODE_BLOCK = "block"
MODE_ADVISORY = "advisory"

# The original scope, unchanged. `/q-handoff` writes it in every instance.
HANDOFF_PATHS = ("memory/last-handoff.md",)
# A session handoff. `q-consult/output/HANDOFF-<slug>-<date>.md` is the live shape;
# `instrument-lint.py` already carries the same basename in its own scope tests, so
# this is the fleet's existing name for the artifact, not a new convention.
HANDOFF_PREFIX = "HANDOFF-"

# AUTO-MEMORY IS ADVISORY, and the reason is a measurement, not a preference.
#
# RCA rca-fleet-sync-two-day-spin-2026-09-20 row T1 asks for auto-memory in scope,
# because a memory file is the OTHER way a claim crosses a session boundary: the
# handoff carries this session's state, auto-memory carries every session's. Both
# are read by the next session as settled fact.
#
# But `memory-confidence.md` already decided, in the open and for this exact corpus,
# that provenance fields there are OPTIONAL and absence is legal: "A convention that
# made ~70 files invalid on day one would be red on its whole population from the
# first run, which is how a gate gets switched off and then protects nothing."
# Sampled 2026-09-26 (4 files read from
# ~/.claude/projects/-Users-assafkipnis-projects-kipi-system/memory/):
#   feedback_verifiable_green.md            ~7 unlabelled measurement lines
#   feedback_approve_is_not_a_green_check.md  2
#   feedback_sana_owns_the_work.md            2
#   reference_reddit_json_blocked.md         ~8
# 4 of 4 red, 0 of 4 carrying a `provenance:` field. n=4 is a sample and it is small;
# it is also unanimous, and it agrees with the ~70-file figure that rule already
# records. A blocking branch here would refuse the highest-traffic write path in the
# system on its own existing content. `instrument-lint.py` excluded `/memory/` for
# the same measured reason (its lines 94-99).
#
# So auto-memory gets the DETECTED posture `coding-audhd.md` and
# `voice-loop-anywhere.md` already use fleet-wide: the scan runs, findings reach the
# model as feedback, the write lands, exit 0 on every path. Promotion to blocking is
# a founder decision made in the open once the corpus carries provenance, never a
# side effect of this widening.
AUTO_MEMORY_MARKERS = ("/.claude/projects/", "/memory/")
AUTO_MEMORY_INDEX = "MEMORY.md"


def is_auto_memory(norm: str) -> bool:
    """An auto-memory CONTENT file, index excluded.

    Deliberately the same three conditions as `in_scope` in
    memory-confidence-validator.py, which owns this scope. That module's filename is
    hyphenated and cannot be imported, so the predicate is restated here and
    `case_auto_memory_scope_matches_the_owner` in the paired test asserts the two
    agree over a path table -- the divergence check that stands in for deriving.
    """
    if not norm.endswith(".md"):
        return False
    if not all(m in norm for m in AUTO_MEMORY_MARKERS):
        return False
    return norm.rsplit("/", 1)[-1] != AUTO_MEMORY_INDEX


def scope_mode(file_path: str) -> str | None:
    """MODE_BLOCK, MODE_ADVISORY, or None when the path is out of scope."""
    norm = file_path.replace("\\", "/")
    if any(frag in norm for frag in HANDOFF_PATHS):
        return MODE_BLOCK
    if norm.endswith(".md") and norm.rsplit("/", 1)[-1].startswith(HANDOFF_PREFIX):
        return MODE_BLOCK
    if is_auto_memory(norm):
        return MODE_ADVISORY
    return None

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

# A markdown header carrying a date is metadata, the same as `Date: ...`, and it is
# the shape the skeleton's OWN handoff template uses: `# Session Handoff - 2026-06-11
# EOD`. META_RE only recognises `key: value`, so that header matched nothing, DATE_RE
# fired, and the lint blocked the canonical artifact it exists to protect
# (sp-be424cdd, ASK-231).
#
# This exempts a header from the DATE check ONLY. Numbers in a header are still
# scanned, so `## the sheet had 1177 rows` still blocks. That distinction is the
# whole point: the scar (reversal #5) WAS a date claim -- "a row is dated 2026-12-21,
# five months in the future" -- so blanket-exempting dates would blind this lint to
# the exact defect it was built for. A heading names a section; a bullet asserts a
# finding. Only the former is exempt, and only for dates.
HEADER_RE = re.compile(r"^\s{0,3}#{1,6}\s")

# ...but a `#` must not become a laundering prefix. Codex adversarial review
# 2026-07-28 found the gap between the two tests that existed: numbers in a header
# were still checked, and a dated CLAIM in a bullet was still checked, but a dated
# claim in a HEADER passed. `## Client row dated 2026-12-21, five months out` is
# reversal #5 verbatim, wearing a heading.
#
# So a header earns the date exemption only if it looks like a TITLE rather than an
# assertion. Two deterministic tells, both cheap and both inspectable:
#   - no comma: a clause after the date ("..., five months out") is argument, not a label
#   - few words besides the date: a title names a section, it does not narrate
# `# Session Handoff - 2026-06-11 EOD` -> 3 other words, no comma -> exempt.
# `## Client row dated 2026-12-21, five months out` -> comma -> checked.
#
# HONEST BOUNDARY: a short comma-free header CAN still carry a date claim
# ("## shipped 2026-12-21"). This narrows the hole, it does not close it. The
# number scan is unaffected either way, so any header carrying a measurement is
# still caught by the NUM_RE pass below.
MAX_TITLE_WORDS = 5


def is_title_header(line: str) -> bool:
    """A header shaped like a section label, not like a dated assertion."""
    if not HEADER_RE.match(line):
        return False
    if "," in line:
        return False
    rest = DATE_RE.sub(" ", line.lstrip("# \t"))
    return len(rest.split()) <= MAX_TITLE_WORDS

# `[verified: <cmd>]` is this lint's own form and stays accepted. Everything else
# comes from provenance_vocabulary, the ONE table this and
# memory-confidence-validator.py both read, so a value added there reaches both.
# Scar 2026-07-28: this lint invented a second vocabulary three days after the
# first one shipped, and nothing collided because the file scopes differ.
VERIFIED_RE = re.compile(r"\[verified:")

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import provenance_vocabulary as PV
except Exception:  # older instance mid-kipi-update: fall back to this lint's own set
    PV = None
    _FALLBACK_RE = re.compile(
        r"\{\{UNVERIFIED\}\}|\{\{UNVALIDATED\}\}|\{\{NEEDS_PROOF\}\}"
        r"|\bev-[0-9a-f]{10}\b")


def has_provenance(line: str) -> bool:
    if VERIFIED_RE.search(line):
        return True
    if PV is not None:
        return PV.has_provenance(line)
    return bool(_FALLBACK_RE.search(line))


def unlabelled_lines(body: str) -> list[tuple[int, str]]:
    """(line number, text) for every measurement-shaped line with no provenance."""
    if SKIP_MARKER in body:
        return []
    out = []
    # An auto-memory file opens with a `---` frontmatter block, and its `description:`
    # and `modified:` lines carry dates and numbers that are LABELS for the file, not
    # claims inside it -- the same reason META_RE exempts `Date: ...` in a handoff. A
    # leading frontmatter block is therefore skipped wholesale. Only leading: a `---`
    # further down is a horizontal rule, and treating it as a fence opener would
    # silently exempt the rest of the file.
    lines = body.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    for n, line in enumerate(lines[start:], start + 1):
        if has_provenance(line) or META_RE.match(line):
            continue
        if DATE_RE.search(line) and not is_title_header(line):
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
    mode = scope_mode(fp) if fp else None
    if mode is None:
        return 0

    try:
        body = Path(fp).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0

    bad = unlabelled_lines(body)
    if not bad:
        return 0

    listed = "\n".join(f"    line {n}: {text[:110]}" for n, text in bad[:15])
    forms = ["    [verified: <the command you ran>]   you ran it; this is the output"]
    if PV is not None:
        forms += [f"    {f}" for f in PV.accepted_forms()]
    else:
        forms += ["    ev-xxxxxxxxxx                       a claim id from evidence.jsonl",
                  "    {{UNVERIFIED}}                      it is an inference, and that is fine"]
    # The advisory header says the write LANDED, in its first four words. A reader who
    # skims a findings block and assumes it blocked will stop fixing the thing, which
    # is worse than no message at all.
    head = ("HANDOFF PROVENANCE (blocked): these lines carry a number with no source, "
            "so the next session cannot tell a measurement from a guess:\n"
            if mode == MODE_BLOCK else
            "HANDOFF PROVENANCE (advisory, this write was NOT blocked): these "
            "auto-memory lines carry a number with no source, so a later session "
            "reading this memory cannot tell a measurement from a guess:\n")
    sys.stderr.write(
        head + listed + "\n\n"
        "  Add one of:\n" + "\n".join(forms) + "\n\n"
        "  Scar 2026-07-28: a handoff claimed a client row was dated five months in "
        "the future. The next session inherited it, repeated it as fact for several "
        "turns, and only checked when the founder asked. No such row existed. The "
        "handoff had no field to say which claims had been recomputed.\n"
        f"  Deliberate exception: add `{SKIP_MARKER}` to the file.\n")
    return 2 if mode == MODE_BLOCK else 0


if __name__ == "__main__":
    sys.exit(main())
