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

Scope: PostToolUse(Write|Edit|MultiEdit) on four surfaces, two postures. Everything
else exits 0 immediately.

  exit 2   `memory/last-handoff.md`
  exit 2   a session handoff `handoff-*.md` (case-insensitive), unless it predates
           SESSION_HANDOFF_CUTOFF
  exit 0   an auto-memory content file under `~/.claude/projects/<slug>/memory/`
  exit 0   that directory's `MEMORY.md` index

Both postures are branches of `scope_mode()` in this file, which is the executable;
`test_handoff_provenance_lint.py` pins each branch. A session handoff is the same
artifact class as `last-handoff.md` written by a different command, so it gets the
same exit code. Auto-memory does not, and the split is measured rather than
reasoned -- see AUTO-MEMORY IS ADVISORY below.

DELIVERY: the advisory branch exits 0, and an exit-0 hook's stderr is DISCARDED by
the harness. So the finding only reaches the model in the one envelope
`hook_envelope_audit.py` measured as delivering -- `hookSpecificOutput` carrying both
`hookEventName` and `additionalContext`. The blocking branch emits no envelope: exit 2
already hands stderr to the model, and a second copy would deliver it twice.

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
# A session handoff: a basename starting `handoff-`, matched CASE-INSENSITIVELY.
#
# Round 1 of this widening matched `HANDOFF-` case-sensitively and cited
# `instrument-lint.py` as the fleet's name for the artifact. That citation was wrong
# and Codex caught it: the only two `HANDOFF-` strings in this repo are
# test_instrument_lint.py:236 and :266, where the basename is FILLER inside a case
# whose actual subject is "a bare output/ file is IN scope" -- instrument-lint scopes
# by DIRECTORY and never reads a basename prefix. No producer writes the uppercase
# form. Every handoff this repo actually carries is lowercase, so the new blocking
# scope matched none of them, which is a scope that ships green by missing everything.
HANDOFF_PREFIX = "handoff-"

# ...and having made it match, it now has an inherited population, so it needs the
# grandfathering plan-lint.py and instrument-lint.py both already carry: a gate red on
# its own population on day one gets switched off, and a gate that is off protects
# nothing. Round 1 shipped without one and a real archived handoff in this repo flagged
# 44 of its 181 lines, whose cheapest resolution is the permanent skip marker.
#
# MEASURED 2026-09-26, current logic, every tracked .md in this repo with `handoff` in
# the basename (`git ls-files`):
#   memory/last-handoff.md                             181->  0 red   original scope
#   memory/handoff-2026-08-09.md                       181-> 44 red   NEW, exempt
#   output/handoff-judgment-compiler-2026-08-04.md     169-> 20 red   NEW, exempt
#   output/claude-judgment-compiler-handoff-2026-08-04.md  399-> 28   out of scope
#   output/plans/linear-loop-handoff-2026-07-29.md     140-> 33 red   out of scope
# 2 of 2 newly-in-scope files are red and 2 of 2 carry a pre-cutoff basename date, so
# the widening lands green on the population it inherited and blocks from here on.
#
# The last two are `-handoff-` INFIX, and they stay out. The finding was the case of
# the prefix, not its position, and both are project deliverables about a judgment
# compiler rather than session handoffs. Named here so the boundary is inspectable
# rather than silent: if the infix form should be in scope, that is its own issue.
SESSION_HANDOFF_CUTOFF = "2026-09-26"

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


def is_memory_index(norm: str) -> bool:
    """The `MEMORY.md` index beside the auto-memory content files.

    A SEPARATE branch from `is_auto_memory` on purpose. memory-confidence-validator.py
    owns the content scope and correctly excludes the index (an index carries no
    confidence frontmatter), and `is_auto_memory` keeps agreeing with it exactly. But
    the index is the one memory file injected into EVERY session, and its pointer
    lines carry unlabelled measurement numbers -- so for provenance it belongs in the
    scan (Codex minor, PR #448). Measured 2026-09-26 over every
    `~/.claude/projects/*/memory/MEMORY.md` on this machine: 25 of 34 carry at least
    one unlabelled measurement line, which is exactly why it joins the ADVISORY branch
    and not the blocking one.
    """
    return (norm.endswith("/" + AUTO_MEMORY_INDEX)
            and all(m in norm for m in AUTO_MEMORY_MARKERS))


def scope_mode(file_path: str) -> str | None:
    """MODE_BLOCK, MODE_ADVISORY, or None when the path is out of scope."""
    norm = file_path.replace("\\", "/")
    if any(frag in norm for frag in HANDOFF_PATHS):
        return MODE_BLOCK
    name = norm.rsplit("/", 1)[-1]
    if norm.endswith(".md") and name.lower().startswith(HANDOFF_PREFIX):
        return MODE_BLOCK
    if is_auto_memory(norm) or is_memory_index(norm):
        return MODE_ADVISORY
    return None


DATE_IN_NAME_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def git_added_date(path: Path) -> str | None:
    """YYYY-MM-DD of the MOST RECENT commit that added this path, or None (untracked,
    no repo, no git). Lifted deliberately from instrument-lint.py rather than
    re-derived: same question, same two rounds of review already spent on it.

    mtime is useless here -- this hook runs AFTER the write, so every file it inspects
    was modified seconds ago. Most recent add, not first: a file deleted and re-created
    after the cutoff is a new file. No --follow: rename pairing let an unrelated old
    file lend its date.
    """
    import subprocess
    try:
        out = subprocess.run(
            ["git", "log", "--diff-filter=A", "--format=%as", "--", path.name],
            cwd=path.parent, capture_output=True, text=True, timeout=3).stdout.split()
    except Exception:
        return None
    return out[0] if out else None


def is_grandfathered(file_path: str, path: Path | None = None) -> bool:
    """True for a session handoff that predates SESSION_HANDOFF_CUTOFF: by a date in
    its BASENAME, else by the most recent date git added it. Undated AND untracked is
    NOT exempt.

    Applies to the session-handoff branch ONLY. `memory/last-handoff.md` has been
    blocking since 2026-07-28 and reads 0 red today; letting a cutoff reach it would
    relax the original scope as a side effect of widening -- the exact trap
    test_instrument_lint.py's "strictest cutoff wins" case exists to catch.

    HONEST BOUNDARY: the basename date wins over git, so a handoff written today under
    a backdated name is exempt. That is the cost of exempting untracked archives, and
    it is the same hole instrument-lint accepted knowingly.
    """
    name = Path(file_path.replace("\\", "/")).name
    dates = DATE_IN_NAME_RE.findall(name)
    if dates:
        return dates[-1] < SESSION_HANDOFF_CUTOFF
    if path is not None:
        added = git_added_date(path)
        return bool(added) and added < SESSION_HANDOFF_CUTOFF
    return False

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
    # Pure-string checks first; git runs only on a file that would otherwise block.
    # `HANDOFF_PATHS` is excluded by name, not by an is_grandfathered branch, so the
    # original scope cannot be relaxed by a later change to the cutoff.
    if (mode == MODE_BLOCK
            and not any(frag in fp.replace("\\", "/") for frag in HANDOFF_PATHS)
            and is_grandfathered(fp, Path(fp))):
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
    report = (
        head + listed + "\n\n"
        "  Add one of:\n" + "\n".join(forms) + "\n\n"
        "  Scar 2026-07-28: a handoff claimed a client row was dated five months in "
        "the future. The next session inherited it, repeated it as fact for several "
        "turns, and only checked when the founder asked. No such row existed. The "
        "handoff had no field to say which claims had been recomputed.\n"
        f"  Deliberate exception: add `{SKIP_MARKER}` to the file.\n")
    sys.stderr.write(report)
    if mode == MODE_BLOCK:
        return 2
    # Advisory. Exit 0 means the harness DISCARDS the stderr above, so it is written
    # for a human tailing the hook log and nothing else; the model only ever sees the
    # envelope below. Both keys are literal here on purpose -- hook_envelope_audit.py
    # classifies the emission site statically and reports UNKNOWN for a computed dict.
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": report,
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
