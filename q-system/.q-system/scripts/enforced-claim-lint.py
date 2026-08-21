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
_BLOCK_RE = re.compile(
    re.escape(BLOCK_MARKER) + r"\s*\n```json\s*\n(.*?)\n```",
    re.DOTALL)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
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


def clause_key(text):
    """Normalize a heading or a `clause` value to a comparable key.

    Defined exactly, because "normalising case and punctuation" was not
    implementable as written (codex-adversarial finding-7): lowercase, drop any
    parenthetical (which is where the marker lives), keep only [a-z0-9 ], collapse
    whitespace, strip. Two distinct headings that collapse to one key are a
    reported collision, never a silent merge -- see check_duplicate_clause_keys.
    """
    text = re.sub(r"\([^)]*\)", " ", text or "")
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_block(text, path):
    """Extract the enforcement entries from a rule's body.

    Returns (entries, violations). `entries` is a list of dicts; a file with no
    block at all yields ([], []) -- absence is not a schema error, it is a
    coverage question answered by check_coverage.

    This is THE single parser. One reader, so a second one cannot drift from it
    (the defect class apply_claude_changes hit twice, rounds 2 and 3).
    """
    matches = _BLOCK_RE.findall(text)
    if not matches:
        return [], []
    if len(matches) > 1:
        return [], [Violation(4, path,
                              "%d enforcement blocks in one file; exactly one is "
                              "allowed so there is one source of truth" % len(matches))]
    try:
        data = json.loads(matches[0])
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
    violations += check_coverage(entries, text, path)
    return violations


def lint_file(path):
    try:
        text = Path(path).read_text()
    except (OSError, UnicodeDecodeError):
        return []
    return lint_text(text, str(path))


def is_rule_file(path):
    """Self-scope. Anything that is not a rule markdown file is not our business.

    Token discipline: this hook is wired PostToolUse fleet-wide, so it must
    fast-exit on the overwhelming majority of writes rather than run logic on
    every Edit.
    """
    p = str(path).replace(os.sep, "/")
    return "/.claude/rules/" in p and p.endswith(".md")


def main():
    if "--all" in sys.argv:
        root = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
        rules = root / ".claude" / "rules"
        violations = []
        for f in sorted(rules.rglob("*.md")):
            violations += lint_file(f)
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
