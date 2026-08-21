#!/usr/bin/env python3
"""enforced-claim-lint: make (ENFORCED) a claim a machine substantiates (ASK-965).

Pairs with the enforcement-disposition convention in `.claude/rules/*.md`.

THE PROBLEM, MEASURED 2026-08-21 (not reasoned about):
38 rule files in this repo, 29 of them carrying 35 ENFORCED markers across 32
headings. Exactly 2 had a test pinning the claim itself. So the word was a string
an author typed, and `prompt-only-enforcement-guard.py` -- which IS wired and DOES
fire -- matches enforcement VOCABULARY, not existence: the sentence "enforced by
the `totally-imaginary-lint.py` hook, a PostToolUse validator" exits 0 there, and
a bare `# Foo (ENFORCED)` heading never trips it at all.

The scar this re-proves is already written into `wiring-check.py` lines 20-33:
"A claim stronger than the code behind it is worse than no claim, because people
trust the claim and stop checking."

THE VOCABULARY (three values, one meaning each):
  ENFORCED  an executable that EXISTS at a resolved path, is REFERENCED in the
            config the entry names, is not neutered there, has a non-zero exit
            path, and has a named test file pinning the claim
  DETECTED  wired and runs, surfaces only (exit 0 / `|| true`), never blocks
  ADVISORY  no executable, and the file says so out loud

WHY THE DISPOSITION IS A BODY BLOCK AND NOT FRONTMATTER OR THE HEADING:
Both alternatives are mechanically REFUSED by the sanctioned write path, which is
the only way an agent may edit `.claude/`:
  - frontmatter: `apply_claude_changes.py::_guard_frontmatter` (line 562) refuses
    ANY frontmatter change by ANY op, including additive ones.
  - the heading marker: `_rule_marks` (line 682) censuses both total marker
    occurrences and how many HEADING lines carry one, as ratchet members that may
    only GROW. Its own docstring names this case: "Demoting a rule to advisory is
    enforcement-weakening whether or not the prose is honest."
A fenced block in the body is additive, so `insert_after`/`append` reach it, and
it is the shape four rules in this repo already use honestly (`coding-audhd.md`,
`token-discipline.md`, `automated-filer-marking.md`, `design-auto-invoke.md`).

WHY JSON AND NOT `key: value` LINES (codex-adversarial finding-2, blocker):
The first draft used a flat mapping, which has no record delimiter. Two entries
would repeat `clause:`/`status:` keys with undefined parser behaviour. A JSON
array has one obvious answer for "where does entry 2 begin".

EXIT CONTRACT:
  hook mode (default) : 2 = block, 0 = pass. stderr is fed back to Claude.
  --all               : 1 = violations found, 0 = clean. For lefthook/CI, where
                        2 carries no special meaning and 1 is the ordinary fail.
Anything unexpected still exits 0 in hook mode: a lint that crashes must not wedge
every rule-file write in the fleet.

STATED RESIDUE, because this file does not get to make a claim stronger than its
code (that is the whole point of it):
  - It proves a named script exists, is referenced in a named config unneutered,
    has a non-zero exit path, and that a named test FILE exists. It does NOT prove
    that script enforces THIS clause, nor that the named test actually goes red.
    A rule can name a real, wired, blocking, tested script that gates something
    else entirely and pass here.
  - `exec` values CANNOT BE SWAPPED through the sanctioned path once written:
    `_rule_marks` ratchets every referenced `.py`/`.sh` basename and refuses any
    mark disappearing (lines 748-749, 809-815). Replacing an obsolete enforcer
    with a differently-named one requires keeping the retired name in the file
    (a superseded-by line). An earlier draft of the PRD promised free rewording;
    that was false and this comment is the correction.
"""
import json
import os
import re
import sys
from pathlib import Path

# The three legal statuses. A value outside this set is a schema violation, never
# a silently-ignored entry: an unknown status is how a typo becomes a free pass.
VALID_STATUS = ("ENFORCED", "DETECTED", "ADVISORY")

# Keys the schema knows. Unknown keys are REFUSED rather than ignored, for the
# same reason apply_claude_changes refuses unknown proposal keys: a tolerated
# key is where a future `skip: true` arrives wearing a permitted name.
KNOWN_KEYS = {"clause", "status", "exec", "config", "test", "directives",
              "note", "marker_removal_ref", "superseded_by"}
REQUIRED_KEYS = {"clause", "status"}

# The block is introduced by an HTML comment so the fence itself stays ordinary
# ```json -- markdown renderers, and the rules' own readers, treat it as a normal
# code block rather than a custom dialect nothing else can parse.
BLOCK_MARKER = "<!-- enforcement -->"
# A fence opener: 3+ backticks or 3+ tildes, optionally indented up to 3, with an
# optional info string. Tracked with its own character and length because a fence
# is closed only by the SAME character at the SAME length or longer -- which is
# exactly how a ````-fenced markdown example can contain ```json without ending.
_FENCE_RE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})[ \t]*([^`~\s]*)")

# DELIBERATELY IDENTICAL to `_HEADING` in apply_claude_changes.py line 182
# (`[ ]{0,3}#{1,6}[ \t]`). That script's census decides which markers sit on
# headings; this lint decides which headings need a disposition. Two readers of
# the same thing are two readers free to drift -- the defect class that script
# hit in rounds 2 and 3 -- and the drift here is silent and exploitable: an
# earlier version anchored at column 0, so `   # Foo (ENFORCED)` (legal markdown,
# and a heading to the census) was invisible to coverage and kept a bare claim.
# Found by codex standard review of 461bd3ac. If that regex changes, change this
# one in the same commit; test_heading_matches_producer_regex fails otherwise.
_HEADING_RE = re.compile(r"^[ ]{0,3}(#{1,6})[ \t]+(.*)$")
MARKER = "(ENFORCED"


class Violation:
    """One blocking finding. Carries the condition number so the mutation matrix
    can assert on a stable id rather than on message wording, which drifts."""

    def __init__(self, condition, path, detail):
        self.condition = condition
        self.path = path
        self.detail = detail

    def __str__(self):
        return "[C%d] %s: %s" % (self.condition, self.path, self.detail)


def scan_blocks(text):
    """Return (marker_count, [block_body, ...]), counting only REAL markers.

    A line scanner rather than a regex, because a regex is not markdown-aware and
    that gap was exploitable (codex-adversarial review of 461bd3ac, major): a rule
    can wrap a marker plus a ```json block inside a LARGER ````-fenced example --
    documentation showing what a disposition looks like -- and the inert example
    would satisfy a live ENFORCED heading sitting outside the fence. A fence is
    closed only by the same character at the same length or longer, so tracking
    the open fence is what tells a real block from a quoted one.

    Markers found at fence depth > 0 are IGNORED entirely rather than counted as
    malformed: text inside an example fence is prose about the convention, not a
    claim under it. Only markers at depth 0 are the file's own disposition.
    """
    lines = text.splitlines()
    markers = 0
    blocks = []
    open_fence = None  # (char, length)
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _FENCE_RE.match(line)
        if m:
            char, length = m.group(1)[0], len(m.group(1))
            if open_fence is None:
                open_fence = (char, length)
            elif char == open_fence[0] and length >= open_fence[1]:
                open_fence = None
            i += 1
            continue
        if open_fence is None and line.strip() == BLOCK_MARKER:
            markers += 1
            body, i = _read_fenced_json(lines, i + 1)
            if body is not None:
                blocks.append(body)
            continue
        i += 1
    return markers, blocks


def _read_fenced_json(lines, i):
    """Read a ```json fence starting at or after `i`. Returns (body|None, next_i).

    Only a bare `json` info string on a 3-backtick fence counts, and only after
    blank lines. Anything else means the marker has no parseable fence, which
    parse_block reports rather than passing over in silence.
    """
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return None, i
    m = _FENCE_RE.match(lines[i])
    if not m or m.group(1) != "```" or m.group(2) != "json":
        return None, i
    i += 1
    body = []
    while i < len(lines):
        closer = _FENCE_RE.match(lines[i])
        if closer and closer.group(1)[0] == "`" and len(closer.group(1)) >= 3:
            return "\n".join(body), i + 1
        body.append(lines[i])
        i += 1
    return None, i  # unterminated fence: no parseable block


def _no_duplicate_keys(pairs):
    """json.loads hook: a repeated key inside one entry is a refusal, not a merge.

    Python's default keeps the LAST value silently, so
    `{"status": "ADVISORY", "status": "ENFORCED"}` parses clean and presents one
    disposition to the machine and a different one to anyone reading the file.
    A disposition whose meaning depends on which reader you are is exactly the
    ambiguity this lint exists to remove (codex standard review of 461bd3ac).
    """
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError("duplicate key %r in enforcement entry" % key)
        seen[key] = value
    return seen


def clause_key(text):
    """Normalize a heading or a `clause` value to a comparable key.

    Defined exactly, because "normalising case and punctuation" was not
    implementable as written (codex-adversarial finding-7).

      1. Drop a trailing parenthetical ONLY IF IT CONTAINS THE MARKER. Two
         narrower rules were tried and both alias distinct claims:
           - dropping EVERY parenthetical made `# Delete (local)` and
             `# Delete (prod)` both "delete", so one entry covered both headings
             (codex-adversarial review of 461bd3ac);
           - dropping any TRAILING parenthetical has the same effect on those two
             headings, because there the trailing parenthetical IS the claim.
         A trailing parenthetical is ambiguous on its own; carrying the marker is
         what identifies it as the marker. Everything else is claim identity and
         is kept.
      2. lowercase.
      3. Keep only [a-z0-9 ]; everything else becomes a space. Non-ASCII headings
         therefore collapse toward the empty string, which is why the empty key is
         a REFUSAL rather than a value (see check_clause_keys) -- otherwise a
         punctuation-only clause would cover every non-ASCII heading in the file.
      4. Collapse whitespace, strip.

    Collisions are reported, never silently merged. This function only computes;
    check_clause_keys is the one place that judges.
    """
    text = (text or "").strip()
    tail = re.search(r"\s*\(([^)]*)\)\s*$", text)
    if tail and "ENFORCED" in tail.group(1):
        text = text[:tail.start()]
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def check_clause_keys(entries, text, path):
    """C2 and C3: keys must be unique, non-empty, and must land on a real heading.

    Three distinct failures, all of which used to pass silently:

      C2 duplicate keys  two entries normalizing to one key means the second
                         silently shadows the first and one heading's disposition
                         is unreadable.
      C2 empty key       a clause of "..." normalizes to "" and would match every
                         heading that also normalizes to "" -- coverage by
                         accident, which is worse than no coverage.
      C3 orphan entry    a clause matching NO heading in the file is a disposition
                         for something that no longer exists. It is not harmless:
                         it reads as coverage to anyone auditing the file, and it
                         is the residue left behind when a heading is reworded.
    """
    violations = []
    heading_keys = {key for _, key in marked_headings(text)}
    seen = {}
    for idx, entry in enumerate(entries):
        key = clause_key(entry["clause"])
        if not key:
            violations.append(Violation(
                2, path,
                "entry %d clause %r normalizes to an empty key; it would match "
                "any heading that also normalizes to empty, which is coverage by "
                "accident" % (idx, entry["clause"])))
            continue
        if key in seen:
            violations.append(Violation(
                2, path,
                "entries %d and %d both normalize to clause key %r (%r vs %r); "
                "one silently shadows the other"
                % (seen[key], idx, key, entries[seen[key]]["clause"], entry["clause"])))
            continue
        seen[key] = idx
        if key not in heading_keys:
            violations.append(Violation(
                3, path,
                "entry %d clause %r matches no ENFORCED-marked heading in this "
                "file. Either the heading was reworded and this disposition is "
                "stale, or the clause is misspelled." % (idx, entry["clause"])))
    return violations


def parse_block(text, path):
    """Extract the enforcement entries from a rule's body.

    Returns (entries, violations). `entries` is a list of dicts; a file with no
    block at all yields ([], []) -- absence is not a schema error, it is a
    coverage question answered by check_coverage.

    This is THE single parser. One reader, so a second one cannot drift from it
    (the defect class apply_claude_changes hit twice, rounds 2 and 3).
    """
    markers, matches = scan_blocks(text)
    # Count MARKERS, not well-formed blocks. Matching only well-formed fences let
    # a file carry one valid covering block plus a second MALFORMED one and pass
    # on the valid half, defeating both the malformed-block refusal and the
    # one-block invariant at once (codex standard review of 461bd3ac, major).
    if markers == 0:
        return [], []
    if markers > 1:
        return [], [Violation(4, path,
                              "%d enforcement markers in one file; exactly one is "
                              "allowed so there is one source of truth" % markers)]
    if not matches:
        return [], [Violation(
            4, path,
            "an enforcement marker is present but no parseable json fence "
            "follows it. The marker must be followed immediately by a fenced "
            "json block containing a JSON array.")]
    try:
        data = json.loads(matches[0], object_pairs_hook=_no_duplicate_keys)
    except ValueError as exc:
        return [], [Violation(4, path, "enforcement block is not valid JSON: %s" % exc)]
    if not isinstance(data, list):
        return [], [Violation(4, path,
                              "enforcement block must be a JSON array of entries, got %s"
                              % type(data).__name__)]

    violations = []
    entries = []
    for idx, entry in enumerate(data):
        if not isinstance(entry, dict):
            violations.append(Violation(4, path, "entry %d is not an object" % idx))
            continue
        unknown = set(entry) - KNOWN_KEYS
        if unknown:
            violations.append(Violation(
                4, path, "entry %d has unknown key(s): %s (known: %s)"
                % (idx, ", ".join(sorted(unknown)), ", ".join(sorted(KNOWN_KEYS)))))
            continue
        missing = REQUIRED_KEYS - set(entry)
        if missing:
            violations.append(Violation(
                4, path, "entry %d is missing required key(s): %s"
                % (idx, ", ".join(sorted(missing)))))
            continue
        if entry["status"] not in VALID_STATUS:
            violations.append(Violation(
                4, path, "entry %d has status %r; must be one of %s"
                % (idx, entry["status"], ", ".join(VALID_STATUS))))
            continue
        if not isinstance(entry["clause"], str) or not entry["clause"].strip():
            violations.append(Violation(
                4, path, "entry %d clause must be a non-empty string" % idx))
            continue
        entries.append(entry)
    return entries, violations


def marked_headings(text):
    """Every heading line carrying the ENFORCED marker, as (raw_text, key).

    Headings only, deliberately. `_rule_marks` counts marker occurrences ANYWHERE
    and separately counts marker-carrying HEADINGS, because a marker parked in
    prose is a different (weaker) claim than one on the heading that declares the
    rule. This lint takes coverage from the headings for the same reason.
    """
    out = []
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m and MARKER in line:
            out.append((m.group(2).strip(), clause_key(m.group(2))))
    return out


def check_coverage(entries, text, path):
    """C1: a marker-carrying heading with no entry covering it is a bare claim."""
    covered = {clause_key(e["clause"]) for e in entries}
    violations = []
    for raw, key in marked_headings(text):
        if key not in covered:
            violations.append(Violation(
                1, path,
                "heading %r carries the ENFORCED marker but no enforcement entry "
                "covers it. Declare one: status ENFORCED (names a wired, blocking, "
                "tested executable), DETECTED (wired, surfaces only), or ADVISORY "
                "(no executable, said out loud)." % raw))
    return violations


def lint_text(text, path):
    """Run every implemented condition over one rule's content.

    Returns ALL violations rather than the first, because 14 files need
    dispositions and a one-error-at-a-time lint turns that into 14 sequential
    runs (codex-adversarial, on the same reasoning as the mutation matrix).
    """
    entries, violations = parse_block(text, path)
    violations = list(violations)
    violations += check_clause_keys(entries, text, path)
    violations += check_coverage(entries, text, path)
    return violations


def lint_file(path, strict=False):
    """Lint one rule file.

    `strict` decides what an UNREADABLE file means, and the two answers are
    different on purpose (codex standard review of 461bd3ac, major):

      hook mode (strict=False): a read error is a silence. The hook fires on
        every rule-file write fleet-wide and must never wedge a write because of
        a transient read problem in the hook itself.

      --all (strict=True): a read error is a VIOLATION. This mode runs in
        lefthook and CI, where the whole point is a verdict over the whole tree.
        Skipping a file it could not read and then printing PASS is a green that
        means "inspected nothing", which is worse than a failure.
    """
    try:
        text = Path(path).read_text()
    except (OSError, UnicodeDecodeError) as exc:
        if strict:
            return [Violation(0, str(path),
                              "unreadable, so its enforcement claims could not be "
                              "checked: %s" % exc)]
        return []
    return lint_text(text, str(path))


def is_rule_file(path):
    """Self-scope. Anything that is not a rule markdown file is not our business.

    Token discipline: this hook is wired PostToolUse fleet-wide, so it must
    fast-exit on the overwhelming majority of writes rather than run logic on
    every Edit.
    """
    p = str(path).replace(os.sep, "/")
    if not p.endswith(".md"):
        return False
    # A RELATIVE path is a real input shape, and requiring the leading slash made
    # the gate's coverage depend on whether the editing tool happened to emit an
    # absolute path -- `.claude/rules/foo.md` bypassed the lint entirely
    # (codex-adversarial review of 461bd3ac, major). A gate whose scope check can
    # be missed by a legal spelling of the same file is not a gate.
    if p.startswith(".claude/rules/") or p.startswith("./.claude/rules/"):
        return True
    return "/.claude/rules/" in p


def main():
    if "--all" in sys.argv:
        root = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
        rules = root / ".claude" / "rules"
        violations = []
        for f in sorted(rules.rglob("*.md")):
            violations += lint_file(f, strict=True)
        if violations:
            sys.stderr.write("[enforced-claim-lint] %d violation(s):\n" % len(violations))
            for v in violations:
                sys.stderr.write("  - %s\n" % v)
            return 1
        print("[enforced-claim-lint] PASS -- every ENFORCED marker is dispositioned.")
        return 0

    # Hook mode. A crash here must never wedge rule-file writes fleet-wide.
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    path = (payload.get("tool_input") or {}).get("file_path", "")
    if not path or not is_rule_file(path):
        return 0
    violations = lint_file(path)
    if not violations:
        return 0
    sys.stderr.write("[enforced-claim-lint] %d unsubstantiated enforcement claim(s):\n"
                     % len(violations))
    for v in violations:
        sys.stderr.write("  - %s\n" % v)
    return 2


if __name__ == "__main__":
    sys.exit(main())
