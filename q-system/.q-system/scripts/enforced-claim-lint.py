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
  - `exec` VALUES CANNOT BE SWAPPED through the sanctioned path once written, and
    this is the residue most likely to bite whoever maintains a disposition next.

    `_rule_marks` in apply_claude_changes.py ratchets each DISTINCT `.py`/`.sh`
    token a rule contains, once per exact spelling and file-wide -- not per field
    and not per occurrence -- and `ratchet_check` refuses any mark that
    disappears. So editing an entry from `exec: old-lint.py` to
    `exec: new-lint.py` is REFUSED WHEN that was the file's only occurrence of the
    old spelling: the mark vanishes, and the ratchet cannot tell a legitimate
    replacement from someone quietly cutting a reader's route to the enforcer.

    Read that as narrowly as it is written (codex review of 279f7f5f). If the old
    token still appears ANYWHERE else in the rule -- prose, a table, another entry
    -- the swap is fine, because the mark survives. And a full path yields only a
    full-path mark; the bare basename is a separate mark ONLY if it independently
    appears somewhere too. That asymmetry is why the token-discipline correction
    below had to name the full test PATH and not just the filename.

    THE WORKING FORM, used in this repo on 2026-08-21 when token-discipline.md's
    two false ENFORCED entries had to become honest ADVISORY ones: keep every
    retired reference NAMED in the entry, in `superseded_by`.

        "superseded_by": "was ENFORCED naming q-system/.q-system/token-guard.py,
                          which does not implement this clause"

    Preserve every EXACT SPELLING that would otherwise disappear -- the full path
    if that is what the entry carried, the bare name if that is -- and it is
    better documentation than a silent swap, because it records what was claimed
    and why it stopped being true.

    `superseded_by` alone does NOT satisfy the whole ratchet, only its exec-mark
    half. Marker counts and substantive-LINE counts are separate members, so a
    replacement that is shorter than the text it replaces is still refused however
    carefully its references are preserved. Landing the token-discipline
    correction took three refusals for three different reasons -- dropped rule
    lines, then a dropped exec mark, then a dropped test-PATH mark -- and each was
    the tool working: a path that made this edit easy would make gutting a rule
    easy.

    An earlier draft of the PRD promised entries could be "reworded freely". That
    was false, it was corrected in the PRD's Risks section, and this comment is
    where a maintainer will actually find it.

prompt-only-enforcement-skip: THIS FILE IS THE DETERMINISTIC BLOCKER, so the
guard that looks for one is reading its own reflection. It fired here (2026-08-21)
on the operator-facing violation messages -- strings like "nothing ties the
receipt to the enforcer it claims to pin" -- which are enforcement vocabulary
sitting next to no nearby executable NOUN, because the executable is the file
they live in. That is the same VOCABULARY-vs-EXISTENCE gap this lint exists to
close and which the module docstring above documents: the guard matched words,
not the thing. Marker used rather than reworded, because contorting a gate's own
error text to satisfy a string search would make the messages worse for the human
who has to act on them.
"""
import ast
import json
import os
import re
import shlex
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



# THE CONDITION REGISTRY: the single machine-readable list of what this lint can
# refuse, and the authority the mutation matrix derives its cases from.
#
# It exists because scraping `Violation(N, ...)` out of the source with a regex is
# NOT a derivation (codex-adversarial review of 1bbfe1c2, blocker): a condition
# passed as a variable, by keyword, through a helper, or via an alias is invisible
# to the scrape, so a new refusal could ship with no fixture and the matrix would
# stay green. Comments and dead code containing the same text invent conditions
# that do not exist. Both directions are wrong.
#
# Violation() VALIDATES against this table, so an unregistered code raises where it
# is constructed rather than sliding into stderr.
CONDITIONS = {
    0: "structural: the baseline or the file itself could not be trusted",
    1: "an ENFORCED-marked heading has no disposition entry",
    2: "clause keys collide, or normalize to empty",
    3: "a disposition entry matches no marked heading",
    4: "the enforcement block violates the schema",
    5: "the named executable is missing, not a path, or wrongly named",
    6: "the executable is not invoked by the config the entry names",
    7: "ENFORCED, but the wired command swallows the failure",
    8: "ENFORCED, but the executable has no non-zero exit path",
    9: "ENFORCED, but the named test receipt is missing or unrelated",
    10: "DETECTED, but the executable can actually block",
    11: "ADVISORY under a live marker without an open removal ticket",
    12: "the declared directive count does not match the section",
}

class Violation:
    """One blocking finding. Carries the condition number so the mutation matrix
    can assert on a stable id rather than on message wording, which drifts."""

    def __init__(self, condition, path, detail, clause=None):
        if condition not in CONDITIONS:
            raise ValueError(
                "condition %r is not in CONDITIONS. Register it: the mutation "
                "matrix derives its cases from that table, so an unregistered "
                "refusal would ship with no fixture." % (condition,))
        self.condition = condition
        self.path = path
        self.detail = detail
        # The heading text this violation is about, when there is one. --all uses
        # it to build a stable baseline key; without it the baseline would have to
        # key on the message string, which drifts on every reword.
        self.clause = clause

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
    # MARKER, not the bare word. Testing for the substring "ENFORCED" stripped
    # the parenthetical off "Cleanup Rule (UNENFORCED)" too, so it collided with
    # "Cleanup Rule (ENFORCED)" -- while marked_headings, which tests `MARKER in
    # line`, correctly does NOT treat "(UNENFORCED)" as a marker. Two functions in
    # one file disagreeing about what the marker is, is the same drift class as
    # two files disagreeing about what a heading is (codex standard review of
    # 6fdca4bf). One definition, used by both.
    if tail and ("(" + tail.group(1)).startswith(MARKER):
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
    headings = marked_headings(text)

    # HEADING collisions, not just entry collisions. Deduplicating headings into a
    # set hid the mirror-image of the bug this function exists to catch: two
    # distinct marked headings normalizing to one key (`Delete-local` and
    # `Delete local`) meant ONE entry covered BOTH, and coverage returned clean --
    # the same accidental coverage, arriving from the heading side (codex standard
    # review of 6fdca4bf). Checked before entries, because while two headings share
    # a key no entry can unambiguously cover either.
    heading_seen = {}
    for raw, key in headings:
        if key in heading_seen:
            violations.append(Violation(
                2, path,
                "headings %r and %r both normalize to clause key %r, so one "
                "disposition would cover both. Reword one heading."
                % (heading_seen[key], raw, key)))
        else:
            heading_seen[key] = raw

    heading_keys = set(heading_seen)
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
        # Type-check the OPTIONAL fields here too. Downstream checks do path
        # arithmetic on `exec` and `config`; an int or a list reached `"/" not in
        # exec_rel` and raised TypeError, turning a schema violation into a
        # traceback that could break both hook and --all mode (codex standard
        # review of 9ea17813). A validator that crashes on bad input is not a
        # validator.
        bad_type = False
        for key in ("exec", "config", "test", "note", "marker_removal_ref",
                    "superseded_by"):
            if key in entry and not isinstance(entry[key], str):
                violations.append(Violation(
                    4, path, "entry %d %s must be a string, got %s"
                    % (idx, key, type(entry[key]).__name__)))
                bad_type = True
        # `not isinstance(x, bool)` first: in Python a bool IS an int, so
        # `"directives": true` passed the type check and then compared equal to an
        # actual count of 1 (codex-adversarial review of 08f8aab0, minor). A
        # declaration that is accidentally correct for one value is a worse failure
        # than a rejected one.
        if "directives" in entry and (isinstance(entry["directives"], bool)
                                      or not isinstance(entry["directives"], int)):
            violations.append(Violation(
                4, path, "entry %d directives must be an integer, got %s"
                % (idx, type(entry["directives"]).__name__)))
            bad_type = True
        if bad_type:
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


def resolve_root(path):
    """Repo root that this RULE's exec/config values are relative to, or None.

    Derived from the RULE PATH, not from the environment. CLAUDE_PROJECT_DIR was
    preferred blindly before, so editing `/other-project/.claude/rules/foo.md`
    from this project validated that rule's claims against THIS project's scripts
    and configs and returned clean (codex-adversarial review of 9ea17813). A claim
    has to be substantiated inside the tree that makes it.

    Returns None when no rules tree can be found above the file, and callers turn
    that into a violation. The old `here.parent` fallback invented a root and then
    reported whatever that arbitrary directory happened to contain.
    """
    here = Path(path).resolve()
    for parent in here.parents:
        if (parent / ".claude" / "rules").is_dir():
            return parent
    return None


def contained(root, rel):
    """Resolve `rel` under `root` and return it only if it stays inside.

    Absolute values, `..` components and symlinks out of the tree are all
    rejected: without this an entry could substantiate an ENFORCED claim with
    files outside the repository entirely (both reviews of 9ea17813). pathlib
    silently DISCARDS root when the right-hand side is absolute, which is what
    makes the naive join dangerous rather than merely wrong.
    """
    if os.path.isabs(rel):
        return None
    try:
        target = (root / rel).resolve()
        target.relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    return target


_PROJECT_VAR = re.compile(r"^\$\{?CLAUDE_PROJECT_DIR\}?/")
_PLUGIN_VAR = re.compile(r"^\$\{?CLAUDE_PLUGIN_ROOT\}?/")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Splitting on shell operators so each segment has ONE program in position 0.
_SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\||\n")
# A program that RUNS its script argument. Anything else (test, echo, cat, [)
# merely mentions the path, and mentioning is what this whole check refuses.
INTERPRETERS = frozenset({"python", "python2", "python3", "bash", "sh", "zsh",
                          "node", "ruby", "perl", "uv", "uvx"})

# The only files whose `hooks` object actually wires anything in this fleet.
# Without this allowlist ANY in-repo JSON carrying a hooks-shaped object -- a
# fabricated docs/fake-hooks.json, a copied template -- satisfied the check while
# never running (codex review of 386bfedd, blocker).
_PLUGIN_HOOKS_RE = re.compile(r"^plugins/[^/]+/hooks/hooks\.json$")
_SETTINGS_CONFIGS = (".claude/settings.json", "settings-template.json")
# Git hooks. THIS REPO ENFORCES THROUGH THREE MECHANISMS, NOT ONE, and an earlier
# version of this allowlist knew only the first (sp-3dc0b094, measured on the real
# tree): hook configs, lefthook git hooks, and validators invoked by `kipi check`.
# linear-first.md blocks commits via lefthook's commit-msg stage and is genuinely
# ENFORCED; without lefthook here it would have been forced to declare ADVISORY.
# A gate red on rules that are honestly enforced is the unsatisfiable-population
# failure automated-filer-marking.md warns about -- it gets switched off, and a
# switched-off gate protects nothing.
_LEFTHOOK_CONFIGS = ("lefthook.yml", "lefthook.yaml", ".lefthook.yml")
# Git stages whose non-zero exit actually STOPS the operation. post-commit,
# post-merge and friends run after the fact and cannot refuse anything, so an
# invocation there substantiates nothing.
LEFTHOOK_BLOCKING_STAGES = frozenset({
    "pre-commit", "commit-msg", "prepare-commit-msg", "pre-push",
    "pre-rebase", "pre-merge-commit", "pre-applypatch",
})


def is_wiring_config(config_rel):
    """Is this path a file that actually wires an enforcement point?

    `.claude/settings.json` is what Claude Code loads. `settings-template.json` is
    the fleet ship path -- the skeleton updater rebuilds every instance's
    settings.json from it, and `skill-hook-pairing.md` requires a hook in BOTH, so
    a rule may honestly name either. Plugin `hooks/hooks.json` files are loaded per
    plugin. `lefthook.yml` wires git hooks, which is how the commit-time gates in
    this repo actually block.

    STILL NOT COMPLETE, and saying so is the point of this file: a validator
    invoked by `kipi check` (validate-separation.py, and the model-allocation rule
    that depends on it) is a real enforcement path with no config to name here. A
    rule enforced that way cannot yet declare ENFORCED honestly and must use
    DETECTED with a note. That is a known gap, not a claim of coverage.
    """
    return (config_rel in _SETTINGS_CONFIGS
            or config_rel in _LEFTHOOK_CONFIGS
            or bool(_PLUGIN_HOOKS_RE.match(config_rel)))


def _lefthook_commands(config_path):
    """Every `run:` command in a lefthook config, including block scalars.

    ONLY BLOCKING STAGES COUNT. A `run:` under `post-commit` cannot prevent the
    commit that already happened, and an earlier version counted every `run:` line
    in the file regardless of which top-level stage owned it (codex-adversarial
    review of 536ab18f, blocker). A rule could then substantiate ENFORCED with an
    invocation that structurally cannot block.

    A deliberately small YAML reader rather than a dependency: this needs two keys,
    and adding a package to a hook that runs on every rule-file write fleet-wide
    would be a much larger change than the question deserves. Both the inline form
    (`run: cmd`, quoted or bare) and the block form (`run: |`) are read; a block
    ends at the first line indented no further than the `run:` key itself.

    KNOWN GAPS, named rather than implied away: YAML flow mappings, aliases and
    anchors, lefthook's `scripts:`/`runner:` form, and true folded-scalar (`>`)
    joining are not handled. A folded block is read line-per-command, which can
    turn an argument into an apparent target. Each of those can produce a false
    REJECTION of real wiring (visible, someone complains) rather than a silent
    false pass, except the folded case, which is why `>` blocks are refused
    outright below instead of guessed at.
    """
    try:
        text = config_path.read_text()
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    lines = text.splitlines()
    i = 0
    stage = None
    for_blocking_stage = False
    while i < len(lines):
        line = lines[i]
        top = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*$", line)
        if top:
            stage = top.group(1)
            for_blocking_stage = stage in LEFTHOOK_BLOCKING_STAGES
            i += 1
            continue
        m = re.match(r"^(\s*)run:\s*(\S.*)?$", line)
        if not m or not for_blocking_stage:
            i += 1
            continue
        indent, inline = len(m.group(1)), m.group(2)
        if inline in (">", ">-"):
            # Folded scalars join lines; reading them line-per-command could turn
            # an argument into an apparent invocation. Skipped rather than guessed.
            i += 1
            continue
        if inline and inline not in ("|", "|-"):
            out.append(inline.strip().strip('"').strip("'"))
            i += 1
            continue
        i += 1
        body = []
        while i < len(lines):
            nxt = lines[i]
            if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= indent:
                break
            body.append(nxt)
            i += 1
        out.append("\n".join(body))
    return out


def plugin_root_for(config_rel):
    """Repo-relative dir that ${CLAUDE_PLUGIN_ROOT} means inside this config."""
    if _PLUGIN_HOOKS_RE.match(config_rel):
        return config_rel[:-len("/hooks/hooks.json")]
    return None


def command_targets(command, plugin_root=None):
    """Repo-relative script paths a hook command actually INVOKES.

    Two rounds of review pushed this from "any substring of the file" to "any
    token of a command" to what it is now: the token in COMMAND POSITION.

    Treating every token as a target was still wrong (codex review of 386bfedd,
    blocker), because all three of these mention the script and none of them runs
    it:
        test -f "$CLAUDE_PROJECT_DIR/.../lint.py" && python3 other.py
        echo "$CLAUDE_PROJECT_DIR/.../lint.py"
        cat < "$CLAUDE_PROJECT_DIR/.../lint.py"
    So the command is split on shell operators, each segment's program is read
    from position 0, and a path counts only if that program is an INTERPRETER
    running it, or if the path IS the program. `test -f X && python3 X` -- the
    real shape in this repo -- still matches, via its second segment.

    Both documented placeholders are resolved: ${CLAUDE_PROJECT_DIR} against the
    repo root, and ${CLAUDE_PLUGIN_ROOT} against the plugin that owns the config.
    Without the second, no plugin-wired script could ever be substantiated, and
    every plugin hook in this repo uses it (verified by reading them).
    """
    out = set()
    for segment in _SEGMENT_SPLIT.split(command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()
        # Drop leading `VAR=value` env assignments; the program follows them.
        while tokens and _ASSIGNMENT.match(tokens[0]):
            tokens = tokens[1:]
        if not tokens:
            continue
        program = _normalize_token(tokens[0], plugin_root)
        if os.path.basename(program) in INTERPRETERS:
            for token in tokens[1:]:
                if token.startswith("-"):
                    continue
                out.add(_normalize_token(token, plugin_root))
                break
        else:
            out.add(program)
    return out


def _normalize_token(token, plugin_root):
    token = _PROJECT_VAR.sub("", token)
    if plugin_root:
        token = _PLUGIN_VAR.sub(plugin_root + "/", token)
    if token.startswith("./"):
        token = token[2:]
    return token


def wired_commands(config_path):
    """Every hook invocation in a config, as argv-ish strings, read structurally.

    Only `hooks.<Event>[].hooks[]` entries with `type == "command"` count, and the
    exec form (`command` plus an `args` list) is joined so a legitimate handler
    written that way is not rejected (codex review of 386bfedd, major). Requiring
    the type means a non-command handler carrying a stray `command` field does not
    read as wiring.

    Reading the file as TEXT is what this replaced: a path in a description, a
    note, or any unrelated JSON value counted as wiring. A malformed config yields
    no commands, so a claim resting on one fails rather than passing on a parse
    error.
    """
    if config_path.name in _LEFTHOOK_CONFIGS:
        return _lefthook_commands(config_path)
    try:
        data = json.loads(config_path.read_text())
    except (OSError, ValueError, UnicodeDecodeError):
        return []
    out = []
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return out
    for matchers in hooks.values():
        if not isinstance(matchers, list):
            continue
        for matcher in matchers:
            if not isinstance(matcher, dict):
                continue
            for hook in matcher.get("hooks") or []:
                if not isinstance(hook, dict) or hook.get("type") != "command":
                    continue
                command = hook.get("command")
                if not isinstance(command, str):
                    continue
                args = hook.get("args")
                if isinstance(args, list) and all(isinstance(a, str) for a in args):
                    command = " ".join([command] + [shlex.quote(a) for a in args])
                out.append(command)
    return out


SPILLOVER_REL = os.path.join(".prd-os", "spillover.jsonl")
_SPILLOVER_ID_RE = re.compile(r"^sp-[0-9a-f]{6,}$")


def _all_mode():
    """True when running the whole-tree pass. Kept as a function so the split
    between per-file and whole-tree checks is testable rather than implicit."""
    return "--all" in sys.argv


def open_spillover_ids(root):
    """Ids of spillover items that are still OPEN, read locally.

    Local by construction: no network call from a hook that fires on every
    rule-file write. The ledger is a JSONL file in the repo, which is also what
    makes the reference checkable at all.
    """
    out = set()
    path = os.path.join(str(root), SPILLOVER_REL)
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("id"):
                    if row.get("status") == "open":
                        out.add(row["id"])
                    else:
                        out.discard(row["id"])
    except OSError:
        return set()
    return out


def _advisory_under_marker(entry, idx, path, root):
    """C11: ADVISORY under a heading that still carries the marker must be TICKETED.

    finding-4 was the sharpest of the PRD review, and it was right: the first
    design let an author satisfy a missing disposition by declaring ADVISORY while
    the heading kept its ENFORCED marker. The false claim stayed visible to every
    reader and was now mechanically blessed, which is worse than the bare claim it
    replaced.

    But a hard block here would be UNSATISFIABLE, and that is not a guess: the
    sanctioned write path REFUSES to remove the marker (`_rule_marks` censuses
    marker occurrences and marker-carrying headings as ratchet members that may
    only grow), so an author told "remove the marker or else" has no way to comply.
    A gate red on files nobody can fix is the failure `automated-filer-marking.md`
    measured before shipping and refused.

    So the honest label is allowed, and the DISCREPANCY IS RECORDED: the entry must
    carry `marker_removal_ref` naming an OPEN spillover item. The rule reads
    honestly today, the gap is countable, and `gates run` stays red until a
    founder-authorised marker removal closes it. Nothing is silently absorbed and
    nothing is unfixably red.
    """
    ref = entry.get("marker_removal_ref")
    if not ref:
        return [Violation(
            11, path,
            "entry %d is ADVISORY but its heading still carries the ENFORCED "
            "marker, so the file goes on claiming enforcement it does not have. "
            "Add `marker_removal_ref` naming an OPEN spillover item, so the "
            "discrepancy is counted until a founder removes the marker (the "
            "sanctioned write path cannot remove it, which is why this is "
            "ticketed rather than blocked)." % idx)]
    if not _SPILLOVER_ID_RE.match(ref):
        return [Violation(
            11, path,
            "entry %d marker_removal_ref %r is not a spillover id (expected "
            "sp-<hex>). The reference has to point at the ledger, or it records "
            "nothing." % (idx, ref))]
    # WELL-FORMEDNESS here, OPENNESS in --all. Split deliberately: this runs
    # PostToolUse on every rule-file write, and making a single-file lint depend
    # on live ledger state couples every write to another file's contents. The
    # whole-tree pass is where cross-file consistency belongs, and it is the mode
    # that gates the commit anyway.
    if root is None or not _all_mode():
        return []
    open_ids = open_spillover_ids(root)
    if not open_ids:
        # FAIL CLOSED. This branch used to ACCEPT, on the reasoning that refusing
        # would be unsatisfiable in a repo that never ran prd-os init. Measured
        # after the fact (codex-adversarial review of 53a10d54, blocker): the
        # ledger is GITIGNORED (`*.jsonl`) and absent from HEAD, so EVERY clean
        # checkout hits this branch and accepts any fabricated `sp-deadbeef`. The
        # escape hatch was not a corner case, it was the only case, and the check
        # never fired anywhere.
        #
        # An unverifiable ticket is not a ticket. Where the ledger is unreadable
        # the claim cannot be substantiated, so it is refused rather than waved
        # through -- the same polarity as every other condition here.
        return [Violation(
            11, path,
            "entry %d names marker_removal_ref %r but no spillover ledger is "
            "readable at %s, so the ticket cannot be verified. An unverifiable "
            "reference records nothing." % (idx, ref, SPILLOVER_REL))]
    if ref not in open_ids:
        return [Violation(
            11, path,
            "entry %d names marker_removal_ref %r, which is not an OPEN spillover "
            "item. A closed or invented reference records nothing." % (idx, ref))]
    return []


def check_exec(entries, path):
    """C5 and C6: the named executable exists, and is wired in the config named.

    C5 exec is a PATH, not a basename. `skill-hook-audit.py` matches hook scripts
       by basename (its lines 58-75) and that can pair one wired command with a
       different same-named file elsewhere in the tree. This schema does not
       inherit that: a repo-relative path has exactly one referent or it does not
       exist, and a bare basename is REFUSED rather than resolved by search --
       resolving it would reintroduce the ambiguity by the back door (finding-9).

    C6 the exec must appear in the config THIS ENTRY NAMES. Asking only whether it
       appears in ANY wired config let a false `config` value pass as long as some
       other config referenced the script (finding-8). The entry names one file;
       that file is what gets read.

    ADVISORY entries name no executable by definition, so they are not checked
    here -- what makes an ADVISORY entry legal is handled separately.
    """
    root = resolve_root(path)
    violations = []
    for idx, entry in enumerate(entries):
        if entry["status"] == "ADVISORY":
            # ADVISORY means "no executable", so NAMING one contradicts the label.
            # Skipping the entry entirely let an ADVISORY entry carry exec/config
            # silently, against the one-meaning-per-status contract (codex
            # standard review of 9ea17813).
            named = sorted(k for k in ("exec", "config", "test") if k in entry)
            if named:
                violations.append(Violation(
                    5, path,
                    "entry %d is ADVISORY, which means no executable, but it names "
                    "%s. Use DETECTED (wired, surfaces only) or ENFORCED if there "
                    "really is one." % (idx, ", ".join(named))))
            violations += _advisory_under_marker(entry, idx, path, root)
            continue
        if root is None:
            violations.append(Violation(
                5, path,
                "entry %d claims %s but no .claude/rules tree was found above this "
                "file, so its exec and config cannot be resolved"
                % (idx, entry["status"])))
            continue
        exec_rel = entry.get("exec")
        config_rel = entry.get("config")
        if not exec_rel or not config_rel:
            violations.append(Violation(
                5, path,
                "entry %d has status %s, which requires both `exec` (a "
                "repo-relative path) and `config` (the hook config wiring it)"
                % (idx, entry["status"])))
            continue
        if "/" not in exec_rel:
            violations.append(Violation(
                5, path,
                "entry %d exec %r is a bare basename. Give the repo-relative "
                "PATH: a basename can name two different files and silently pair "
                "the wrong one with the wired command." % (idx, exec_rel)))
            continue
        exec_path = contained(root, exec_rel)
        if exec_path is None:
            violations.append(Violation(
                5, path,
                "entry %d exec %r is absolute or escapes the repo. exec must be a "
                "repo-relative path INSIDE the tree that makes the claim."
                % (idx, exec_rel)))
            continue
        if not exec_path.is_file():
            violations.append(Violation(
                5, path,
                "entry %d exec %r does not exist at that path" % (idx, exec_rel)))
            continue
        if not is_wiring_config(config_rel):
            violations.append(Violation(
                6, path,
                "entry %d config %r is not a file that wires hooks. Naming any "
                "JSON with a hooks-shaped object let a fabricated or copied file "
                "substantiate a claim it never runs. Use .claude/settings.json, "
                "settings-template.json, or plugins/<name>/hooks/hooks.json."
                % (idx, config_rel)))
            continue
        config_path = contained(root, config_rel)
        if config_path is None:
            violations.append(Violation(
                6, path,
                "entry %d config %r is absolute or escapes the repo" % (idx, config_rel)))
            continue
        if not config_path.is_file():
            violations.append(Violation(
                6, path,
                "entry %d config %r does not exist" % (idx, config_rel)))
            continue
        commands = wired_commands(config_path)
        plugin_root = plugin_root_for(config_rel)
        if not any(exec_rel in command_targets(cmd, plugin_root) for cmd in commands):
            violations.append(Violation(
                6, path,
                "entry %d claims %s but no hook command in %s INVOKES %r -- it is "
                "an ORPHAN, it never fires. (A path appearing in the file's text "
                "is not wiring: it must be the target of a hook command.)"
                % (idx, entry["status"], config_rel, exec_rel)))
    return violations


# A command whose failure is swallowed, so the hook cannot block.
#
# READ THIS LIST AS A FLOOR, NOT A PROOF (codex-adversarial review of eafadb8f,
# blocker). An earlier version matched only `|| true` and `|| exit 0` and called
# itself exact; it was not. `script.py; true`, `script.py || :`,
# `script.py || /bin/true` and `script.py || echo ignored` all return success and
# all passed as unneutered. Those are covered now. What is STILL not covered, and
# is named here rather than implied away: a wrapper script that runs the enforcer
# and swallows its child's status is invisible to any inspection of this command
# string. C7 catches the inline forms; it does not prove blocking.
#
# `2>/dev/null` is deliberately NOT neutering: redirecting stderr preserves the
# exit status. An earlier comment implied otherwise.
_NEUTERED = re.compile(
    r"(?:\|\||;)\s*(?:true\b|:\s*(?:$|;|\|)|/bin/true\b|/usr/bin/true\b"
    r"|exit\s+0\b|echo\b)")
_SH_EXIT = re.compile(r"\bexit\s+(\d+)")


def _strip_sh_comments(source):
    """Drop `#` comments from shell source, keeping `#` inside quotes.

    Crude but sufficient for the one question asked of it: does a real `exit N`
    appear. A commented-out `# exit 2` used to make a never-blocking script read
    as blocking.
    """
    out = []
    for line in source.splitlines():
        quote = None
        cut = len(line)
        for i, ch in enumerate(line):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "'\"":
                quote = ch
            elif ch == "#" and (i == 0 or line[i - 1].isspace()):
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


def can_exit_nonzero(source, suffix):
    """Could this script hand back a non-zero status?

    UNPROVABLE MEANS YES, and that asymmetry is deliberate. A literal-only check
    says "no" for `sys.exit(main())` -- which is how this very lint exits, and how
    most non-trivial hooks in this repo exit -- and misclassifying the common case
    as advisory would push authors to label real gates DETECTED. For a fleet gate
    the direction matters: wrongly saying "yes" lets a claim reach a human reader,
    wrongly saying "no" blocks an honest rule and gets the gate switched off.

    PARSED, NOT PATTERN-MATCHED (codex-adversarial review of eafadb8f, blocker).
    Scanning raw text meant a script containing only `print("sys.exit(2)")` or
    `# sys.exit(2)` was classified as blocking while it always exits zero -- a
    false ENFORCED claim handed out by the checker meant to prevent them. Python
    goes through `ast`, so comments and string literals cannot contribute; shell
    has its comments stripped first.

    An unparseable Python file returns True, consistent with unprovable-means-yes.
    """
    if suffix == ".sh":
        return any(int(code) != 0
                   for code in _SH_EXIT.findall(_strip_sh_comments(source)))
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return True  # unparseable: unprovable, so treated as possible
    for node in ast.walk(tree):
        call = None
        if isinstance(node, ast.Call):
            call = node
        elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            call = node.exc
        if call is None or not _is_exit_call(call.func):
            continue
        if not call.args:
            continue  # sys.exit() == 0
        arg = call.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
            if arg.value != 0:
                return True
        elif isinstance(arg, ast.Constant) and arg.value is None:
            continue  # sys.exit(None) == 0
        else:
            return True  # computed: unprovable, so treated as possible
    return False


def _is_exit_call(func):
    if isinstance(func, ast.Name):
        return func.id in ("exit", "SystemExit")
    if isinstance(func, ast.Attribute):
        return func.attr in ("exit", "_exit")
    return False


def check_posture(entries, path):
    """C7, C8, C9, C10: does the claimed posture match what the wiring can do?

    finding-5 said the exit posture was "not implementably specified", and it was
    right that source containing a non-zero exit does not PROVE that path is
    reachable for the wired invocation. So this checks the parts that ARE
    decidable and stops there, and the docstring says which is which:

      C7 the wired command is not neutered with `|| true` / `|| exit 0`. Decidable
         and exact: the fleet has 9 such commands out of 46, and a rule calling one
         of them ENFORCED is simply wrong.
      C8 the script has some non-zero exit path at all. Necessary, not sufficient.
      C9 ENFORCED names a `test` file THAT EXISTS. This is the load-bearing one and
         it is modelled on the only two rules in this repo that were already
         honest: voice-enforcement.md and token-discipline.md each name a test that
         pins the claim. It does NOT prove the test goes red; it proves someone
         wrote the receipt down and it is still there.
      C10 a DETECTED entry whose exec can exit non-zero AND is wired unneutered is
         understating a real gate. Understating is the safe direction, so this
         reports rather than being silently tolerated -- a reader trusting
         DETECTED would not expect their write to be blocked.
    """
    root = resolve_root(path)
    if root is None:
        return []
    violations = []
    for idx, entry in enumerate(entries):
        status = entry["status"]
        if status == "ADVISORY":
            continue
        exec_rel, config_rel = entry.get("exec"), entry.get("config")
        if not exec_rel or not config_rel or not is_wiring_config(config_rel):
            continue  # already reported by check_exec; do not pile on
        exec_path = contained(root, exec_rel)
        config_path = contained(root, config_rel)
        if exec_path is None or config_path is None or not exec_path.is_file():
            continue
        if status == "ENFORCED":
            test_rel = entry.get("test")
            if not test_rel:
                violations.append(Violation(
                    9, path,
                    "entry %d claims ENFORCED but names no `test`. The two rules in "
                    "this repo that were already honest each name a test pinning "
                    "the claim; that receipt is what ENFORCED means here."
                    % idx))
            else:
                test_path = contained(root, test_rel)
                if test_path is None or not test_path.is_file():
                    violations.append(Violation(
                        9, path,
                        "entry %d names test %r, which does not exist at that path"
                        % (idx, test_rel)))
                else:
                    # is_file() alone was trivially satisfiable: an empty file, an
                    # unrelated file, or the enforcer itself passed (codex-
                    # adversarial review of eafadb8f, major). Requiring the test to
                    # MENTION the executable is a weak but real tie between the two,
                    # and it is the strongest link available without running
                    # anything -- which this lint deliberately never does, since
                    # executing hook scripts from inside a lint is the live-data
                    # path fable-discipline exists to stop.
                    #
                    # STILL NOT PROOF, and the docstring says so: a test that
                    # imports the enforcer and asserts nothing about blocking will
                    # pass this. C9 evidences that a receipt was written and is
                    # still there, not that it goes red.
                    try:
                        test_src = test_path.read_text()
                    except (OSError, UnicodeDecodeError):
                        test_src = ""
                    exec_base = os.path.basename(exec_rel)
                    stem = os.path.splitext(exec_base)[0].replace("-", "_")
                    if exec_base not in test_src and stem not in test_src:
                        violations.append(Violation(
                            9, path,
                            "entry %d names test %r, but that file never mentions "
                            "%r, so nothing ties the receipt to the enforcer it "
                            "claims to pin." % (idx, test_rel, exec_base)))
        if not config_path.is_file():
            continue
        plugin_root = plugin_root_for(config_rel)
        matched = [cmd for cmd in wired_commands(config_path)
                   if exec_rel in command_targets(cmd, plugin_root)]
        if not matched:
            continue  # orphan, already reported by check_exec
        # ANY, not ALL (codex-adversarial review of eafadb8f, major). `all` meant
        # one unneutered invocation LAUNDERED every neutered one: a script wired
        # twice, blocking on a rare event and swallowed on the common one, read as
        # a clean ENFORCED claim. The entry does not say WHICH event enforces the
        # clause, so the only claim its wiring can support is that every
        # invocation blocks. If that is too strict for a real case, the fix is a
        # schema that names the event, not a weaker quantifier.
        neutered = any(_NEUTERED.search(cmd) for cmd in matched)
        try:
            source = exec_path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        nonzero = can_exit_nonzero(source, exec_path.suffix)
        if status == "ENFORCED":
            if neutered:
                violations.append(Violation(
                    7, path,
                    "entry %d claims ENFORCED but every wired command for %r "
                    "swallows its failure (`|| true` / `|| exit 0`), so it can "
                    "never block. The honest label is DETECTED."
                    % (idx, exec_rel)))
            elif not nonzero:
                violations.append(Violation(
                    8, path,
                    "entry %d claims ENFORCED but %r has no non-zero exit path, "
                    "so it cannot block. The honest label is DETECTED."
                    % (idx, exec_rel)))
        elif status == "DETECTED" and nonzero and not neutered:
            violations.append(Violation(
                10, path,
                "entry %d says DETECTED, but %r can exit non-zero and its wired "
                "command does not swallow failure -- it can BLOCK. A reader "
                "trusting DETECTED would not expect their write refused."
                % (idx, exec_rel)))
    return violations


# A normative directive line. CASE-INSENSITIVE, and that was a measurement, not a
# preference (2026-08-21).
#
# The first version matched only the shouty forms (MUST/NEVER/ALWAYS uppercase) on
# the theory that lowercase "must" is usually explanatory prose. Counting the real
# tree settled it: uppercase-only found 15 directives across all 32 marked
# sections, case-insensitive found 88. The forecast for this repo was 118 across
# whole files, so 88-under-markers is the right order and 15 is not.
#
# A ratchet whose population is near zero cannot detect growth in anything. It
# would ship looking like a gate and protect nothing, which is the exact failure
# this whole PRD is about. Over-counting is the acceptable error here: the number
# only has to be DETERMINISTIC and to MOVE when a directive is added. It is not a
# semantic measure of how many rules a section contains, and the rule text says so.
_DIRECTIVE_RE = re.compile(r"\b(?:must|never|always|required|do not|shall)\b", re.I)


def count_directives(section_lines):
    """How many normative directives this section carries.

    PER OCCURRENCE, not per line -- and the per-line version was a real bypass I
    wrote a test to codify (codex-adversarial review of 08f8aab0, blocker).
    Counting lines meant `You MUST do X.` could become
    `You MUST do X and MUST do Y.` with the count unchanged, so a directive could
    be added under a dispositioned heading without the ratchet noticing. That
    directly contradicts the guarantee the ratchet exists to make, and a test
    asserting the bypass is worse than no test.

    The original rationale was that rewording should not move the number. That
    trade was wrong: forcing a re-read when a directive is REWORDED is a cost
    worth paying, while letting one be ADDED silently defeats the mechanism.
    Measured on the real tree, the population barely moves either way (88 lines
    vs 95 occurrences), so the bypass bought nothing.

    Fenced code is excluded -- a directive quoted inside an example is not an
    instruction the rule is issuing -- and that also excludes the enforcement
    block's own JSON, which is pinned by
    test_directive_count_excludes_the_enforcement_block_itself.
    """
    count = 0
    open_fence = None
    for line in section_lines:
        m = _FENCE_RE.match(line)
        if m:
            char, length = m.group(1)[0], len(m.group(1))
            if open_fence is None:
                open_fence = (char, length)
            elif char == open_fence[0] and length >= open_fence[1]:
                open_fence = None
            continue
        if open_fence is not None:
            continue
        count += len(_DIRECTIVE_RE.findall(line))
    return count


def sections(text):
    """Split a rule into (heading_line, [body lines]) with LEVEL-AWARE nesting.

    A section runs until the next heading of the SAME OR HIGHER level, so an H1
    owns its subsections and an H2 owns its H3s. That is how a reader understands
    "this rule (ENFORCED)" -- the marker on the H1 governs the document, not the
    two lines before the first H2.

    MEASURED, because the first version got this wrong and the number said so
    (2026-08-21). Splitting at EVERY heading gave 3 directives across all 32
    marked sections, against a forecast of 118 across the tree. A ratchet whose
    population is near zero cannot detect growth in anything, so it would have
    shipped looking like a gate and protecting nothing.
    """
    lines = text.splitlines()
    heads = []
    open_fence = None
    in_frontmatter = False
    for i, line in enumerate(lines):
        # Frontmatter first. `# comment` inside a YAML block is not a heading, and
        # treating it as one invented fake sections and could invent a fake marked
        # clause (codex-adversarial review of 08f8aab0, major).
        if i == 0 and line.strip() == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if line.strip() == "---":
                in_frontmatter = False
            continue
        # A heading inside a fenced example is an example, not a boundary. Without
        # this, a same-or-higher-level heading inside a fence TRUNCATED the
        # dispositioned section, so directives after that example were omitted and
        # a stale count stayed valid (same review, blocker). scan_blocks already
        # tracked fences; this reader did not, and count_directives receives an
        # already-sliced body so its own tracking cannot recover the loss.
        m = _FENCE_RE.match(line)
        if m:
            char, length = m.group(1)[0], len(m.group(1))
            if open_fence is None:
                open_fence = (char, length)
            elif char == open_fence[0] and length >= open_fence[1]:
                open_fence = None
            continue
        if open_fence is not None:
            continue
        m = _HEADING_RE.match(line)
        if m:
            heads.append((i, len(m.group(1)), line))
    out = []
    for n, (start, level, line) in enumerate(heads):
        end = len(lines)
        for later_start, later_level, _ in heads[n + 1:]:
            if later_level <= level:
                end = later_start
                break
        out.append((line, lines[start + 1:end]))
    return out


def check_directive_counts(entries, text, path):
    """C12: the declared directive count must match the section as it stands.

    THE POINT (finding-3, blocker): coverage keyed to a heading is heading-level
    wearing a clause-level label. One disposition greens every directive beneath a
    broad heading -- which is the file-level hole this lint replaced, one notch
    narrower. Keying entries to individual directives was rejected instead: the key
    would be directive line TEXT, which changes on every editorial pass, so
    dispositions would orphan constantly and the gate would become noise.

    So the population is ratcheted rather than enumerated. Adding a MUST under a
    dispositioned heading changes the count, the recount disagrees with the
    declaration, and the author has to re-examine the disposition instead of
    inheriting it silently.

    THIS IS A GROWTH DETECTOR, NOT A PER-DIRECTIVE PROOF, and the rule text says
    so. A disposition still covers a whole section. What it can no longer do is
    absorb a NEW directive without anyone looking.

    `directives` is optional: a rule may omit it, and then no ratchet applies to
    that clause. Omission is visible in the block, which is the honest form of
    "not ratcheted" -- unlike a default that would look like a count.
    """
    by_key = {}
    for heading_line, body in sections(text):
        m = _HEADING_RE.match(heading_line)
        if m and MARKER in heading_line:
            by_key[clause_key(m.group(2))] = (m.group(2).strip(), body)
    violations = []
    for idx, entry in enumerate(entries):
        if "directives" not in entry:
            continue
        found = by_key.get(clause_key(entry["clause"]))
        if found is None:
            continue  # orphan clause, already reported by check_clause_keys
        raw, body = found
        actual = count_directives(body)
        declared = entry["directives"]
        if actual != declared:
            violations.append(Violation(
                12, path,
                "entry %d declares directives: %d for %r, but the section now "
                "carries %d. Re-read the disposition against what the section "
                "actually says, then update the count -- a new directive must not "
                "inherit an old disposition."
                % (idx, declared, raw, actual)))
    return violations


def check_coverage(entries, text, path):
    """C1: a marker-carrying heading with no entry covering it is a bare claim."""
    covered = {clause_key(e["clause"]) for e in entries}
    violations = []
    for raw, key in marked_headings(text):
        if key not in covered:
            violations.append(Violation(
                1, path, clause=raw, detail=
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
    violations += check_exec(entries, path)
    violations += check_posture(entries, path)
    violations += check_directive_counts(entries, text, path)
    violations += check_coverage(entries, text, path)
    return violations


BASELINE_REL = os.path.join("q-system", ".q-system", "enforced-claim-baseline.json")


def load_baseline(root):
    """Markers that predate this gate, as `<rule path>::<clause key>` strings.

    WHY A BASELINE AT ALL. Measured 2026-08-21, before any of this shipped: 29
    rule files carry 35 markers across 32 headings, and NONE had a disposition.
    A gate that goes red on 32 markers the day it lands is unsatisfiable for its
    own population -- the exact shape `automated-filer-marking.md` measured before
    shipping (8 files constructed the Linear create-issue mutation, 1 carried the
    label) and refused to ship. An unsatisfiable gate gets switched off, and a
    switched-off gate protects nothing at all.

    So the debt is RATCHETED rather than forgiven. Every entry is a marker someone
    still has to disposition; the file may only shrink; and `--all` prints the
    remaining count on every run so it stays visible instead of becoming furniture.

    It lives OUTSIDE `.claude/` deliberately. A JSON config the sanctioned write
    path creates is create-once, correct-never -- `create_file` refuses a target
    that exists with different content and `replace` is pinned to rule text
    (sp-fea73326) -- so a baseline under `.claude/` could never shrink, which is
    the one thing it has to be able to do.
    """
    return _read_baseline(root)[0]


def _read_baseline(root):
    """(entries, initial_count). Split out so --all can enforce the shrink rule."""
    path = os.path.join(str(root), BASELINE_REL)
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set(), 0
    entries = data.get("uncovered_markers")
    entries = set(entries) if isinstance(entries, list) else set()
    initial = data.get("initial_count")
    return entries, initial if isinstance(initial, int) else len(entries)


def _baseline_at_head(root):
    """The committed baseline's entry set, or None when it cannot be read.

    None (no git, no such file yet, a first commit) means "no predecessor to
    compare against" and the caller falls back to the in-file count. That is a
    stated limit, not a silent pass: the in-file check still runs, and the only
    situation with neither is a repo where the baseline has never been committed.
    """
    import subprocess
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "show", "HEAD:" + BASELINE_REL.replace(os.sep, "/")],
            capture_output=True, timeout=30, check=False)
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    entries = data.get("uncovered_markers")
    return set(entries) if isinstance(entries, list) else None


def baseline_key(root, file_path, clause_key_value):
    try:
        rel = os.path.relpath(str(file_path), str(root))
    except ValueError:
        rel = str(file_path)
    return "%s::%s" % (rel.replace(os.sep, "/"), clause_key_value)


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
        baseline, initial_count = _read_baseline(root)
        violations = []
        # THE SHRINK RULE, ENFORCED rather than asserted (codex-adversarial review
        # of 536ab18f, blocker). The docstring said "may only shrink" and nothing
        # checked it: `initial_count` was written into the file and never read, so
        # a commit could add a new undispositioned marker AND its baseline key and
        # still pass. Saying shrink-only while allowing growth is the exact defect
        # class this lint exists to stop, committed by the lint.
        if len(baseline) > initial_count:
            violations.append(Violation(
                0, BASELINE_REL,
                "baseline holds %d entries but declares initial_count %d. It may "
                "only SHRINK. Raising initial_count is a deliberate act that has "
                "to be justified in review, never a side effect of adding a marker."
                % (len(baseline), initial_count)))
        # AGAINST HEAD, not against a number in the same mutable file
        # (codex-adversarial review of 53a10d54, major). Comparing len(baseline)
        # to an initial_count that lives BESIDE it means one commit can add keys
        # and raise the number together, and the file certifies itself. HEAD is
        # the immutable predecessor: whatever was committed last cannot be edited
        # by the commit under test.
        previous = _baseline_at_head(root)
        if previous is not None:
            grew = baseline - previous
            if grew:
                violations.append(Violation(
                    0, BASELINE_REL,
                    "baseline gained %d entry(ies) since HEAD: %s. It may only "
                    "shrink. A marker that needs excusing is new work, not "
                    "pre-existing debt." % (len(grew), ", ".join(sorted(grew)[:3]))))
        excused = set()
        for f in sorted(rules.rglob("*.md")):
            for v in lint_file(f, strict=True):
                key = baseline_key(root, v.path, clause_key(v.clause or ""))
                # ONLY C1 (an undispositioned marker) is baselineable. Every other
                # condition means a disposition EXISTS and is wrong, which is new
                # work by definition and never pre-existing debt.
                if v.condition == 1 and key in baseline:
                    excused.add(key)
                    continue
                violations.append(v)
        stale = sorted(baseline - excused)
        for key in stale:
            violations.append(Violation(
                0, BASELINE_REL,
                "baseline lists %r, which is no longer an undispositioned marker. "
                "Remove it: the baseline may only shrink, and a stale entry would "
                "silently re-excuse the marker if it ever came back." % key))
        if violations:
            sys.stderr.write("[enforced-claim-lint] %d violation(s):\n" % len(violations))
            for v in violations:
                sys.stderr.write("  - %s\n" % v)
            return 1
        # Printed on EVERY run, including green ones. Debt that stops being
        # mentioned stops being debt and becomes furniture.
        print("[enforced-claim-lint] PASS -- every ENFORCED marker is dispositioned "
              "or baselined. %d marker(s) still owe a disposition (baseline may only "
              "shrink)." % len(excused))
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
