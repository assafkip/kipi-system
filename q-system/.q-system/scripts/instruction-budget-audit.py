#!/usr/bin/env python3
"""Audit always-on instruction token budget.

Single budget: CLAUDE.md (with imports) + effectively-always-on rules < 300 lines.

IMPORTANT: Rules with paths: ["**/*"] are functionally always-on because **/*
matches every file Claude will ever read. The script must count these as always-on,
not conditional. A naive has_paths_frontmatter() check would misclassify them.

Exits non-zero if budget exceeded.

--ratchet (the commit-time mode, wired in lefthook.yml pre-commit): the 300-line
target was already 214 lines underwater when the hook was resurrected from a dead
pre-commit.old backup (2026-07-02, spillover sp-b417481b), so an absolute block
would freeze all commits. Ratchet mode blocks only REGRESSION against the
committed baseline (instruction-budget-baseline.json). CLAUDE.md's own 200-line
cap stays absolute (it passes today). The 514->300 trim is tracked as its own
spillover item.

ONE NUMBER BECAME TWO (ASK-285). The baseline used to hold a single
`total_always_on` that auto-tightened on any shrink, and that deadlocked against
the only sanctioned write path into `.claude/`:

  Gate A (this file) allowed ZERO net growth in always-on lines.
  Gate B (apply_claude_changes.py) cannot express a removal, its line census
         refuses to let a `replace` SHORTEN a rule, and _guard_frontmatter
         refuses a frontmatter change by ANY op -- so it can perform neither a
         removal nor a scoping.

Every non-empty append to a `.claude/rules/*.md` file therefore added an
always-on line that Gate A demanded be paid for and Gate B could not pay. PR #48
only landed because an unrelated duplicate happened to exist in root CLAUDE.md;
neither that duplicate nor direct write access to it generalises.

So the baseline now holds:

  cap               the gate. Monotone NON-INCREASING by construction.
  total_always_on   the last observed total. Informational.
  files             per-file line counts at the last write, which is what makes
                    the classification below possible at all.

A drop in the total is classified against that snapshot:

  SCOPING   a rule moved from always-on to paths-scoped. Every line of it is
            still on disk and still loads for the paths it names, so nothing
            left the tree: the cap HOLDS and the freed lines become headroom an
            append may spend.
  DELETION  lines left the tree (a rule shrank, a rule file vanished, CLAUDE.md
            shrank). The cap follows down, permanently, exactly as before.

cap only ever moves by -deletion_delta, so the floor may tighten and never
loosen. An AGENT cannot bank headroom -- scoping is a frontmatter edit
apply_claude_changes.py refuses outright -- it can only spend what is already
banked. That asymmetry is the point, not an oversight.

--root DIR measures another tree. --rules-total and --rules-cap are the two
machine modes apply_claude_changes.py reads, both in rules-only line units so
they are directly comparable; `cap_rules` is the single reader of "what ceiling
does the baseline declare", shared by the ratchet and that pair, because two
spellings of one judgement is the drift class this gate keeps finding.

prompt-only-enforcement-skip: THIS FILE IS A DETERMINISTIC BLOCKER (the pre-commit
ratchet), and the guard fired on its PRE-EXISTING docstring above -- prose about
baselines, blocks and caps -- the moment ASK-965 touched the file. Same
vocabulary-vs-existence gap the enforced-claim lint was built to close: the guard
matches words, and the words here describe the gate this file already is.
"""
import json
import os
import re
import subprocess
import sys

QROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
PROJECT_ROOT = os.path.normpath(os.path.join(QROOT, ".."))

# Anthropic docs say <200 for CLAUDE.md (stated 3x).
# Docs also say: "Rules without paths frontmatter are loaded at launch
# with the same priority as .claude/CLAUDE.md."
# Rules with paths: ["**/*"] match everything = same as no paths.
# Single budget: CLAUDE.md + effectively-always-on rules combined.
BUDGET_CLAUDE_MD = 200
BUDGET_TOTAL_ALWAYS_ON = 300

# Glob patterns that match everything (functionally always-on)
CATCH_ALL_PATTERNS = {"**/*", "**/**", "**"}


ENFORCEMENT_MARKER = "<!-- enforcement -->"
# Same fence grammar the enforced-claim lint uses: a fence closes only on the
# same character at the same length or longer, which is what makes a ````-fenced
# example able to contain ```json without ending.
_FENCE_RE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})[ \t]*([^`~\s]*)")


def count_lines(path):
    """Non-blank lines, EXCLUDING the machine-read enforcement block (ASK-965).

    This budget measures always-on INSTRUCTION lines -- text a model loads and
    reads every session. A rule's `<!-- enforcement -->` block is a fenced JSON
    disposition for `enforced-claim-lint.py`; no model needs to read it, and
    charging it here would mean either spending real instruction budget on JSON
    nobody reads, or bumping the very ratchet that exists to stop that.

    Measured when the first disposition pass landed: 4 blocks across always-on
    rules moved the total 511 -> 545 (+34) against a target of 300.

    Only the fence that FOLLOWS the marker is skipped, so an ordinary example
    block in a rule still counts as the instruction text it is.
    """
    if not os.path.exists(path):
        return 0
    total = 0
    outer_fence = None      # (char, length) of an enclosing example fence
    block_fence = None      # length of the disposition fence being skipped
    pending = False
    with open(path) as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            fence = _FENCE_RE.match(stripped)

            if block_fence is not None:
                # Inside the disposition block. Closed by a fence of the same
                # character at the same length or longer.
                if fence and fence.group(1)[0] == "`" and len(fence.group(1)) >= block_fence:
                    block_fence = None
                continue

            if fence:
                char, length = fence.group(1)[0], len(fence.group(1))
                if pending and char == "`" and fence.group(2) == "json" and outer_fence is None:
                    # The disposition fence: skip its contents, count neither end.
                    block_fence = length
                    pending = False
                    continue
                pending = False
                if outer_fence is None:
                    outer_fence = (char, length)
                elif char == outer_fence[0] and length >= outer_fence[1]:
                    outer_fence = None
                total += 1      # an ordinary fence line IS instruction text
                continue

            # MARKER ONLY AT TOP LEVEL. Reacting to it at any fence depth let a
            # rule nest the marker plus an inner ```json inside a FOUR-backtick
            # example: enforced-claim-lint ignores that marker (it is inside the
            # outer fence) while this counter skipped the inner contents, so
            # arbitrary instruction lines could be hidden from the budget
            # (codex-adversarial review of 53a10d54, major). Two readers of one
            # marker disagreeing about depth is the same drift class this PRD
            # keeps finding; both now require depth 0.
            if outer_fence is None and stripped == ENFORCEMENT_MARKER:
                pending = True
                continue
            pending = False
            total += 1
    return total


def parse_paths_from_frontmatter(path):
    """Extract paths/globs list from YAML frontmatter. Returns None if no scoping key."""
    with open(path) as f:
        content = f.read()

    if not content.startswith("---"):
        return None

    end = content.find("---", 3)
    if end == -1:
        return None

    frontmatter = content[3:end]
    # Check for either paths: or globs: (both are scoping keys in Claude Code)
    has_scoping = re.search(r"^(paths|globs):", frontmatter, re.MULTILINE)
    if not has_scoping:
        return None

    # Extract list values from whichever key is present
    paths = []
    in_list = False
    for line in frontmatter.splitlines():
        if re.match(r"^(paths|globs):\s*$", line):
            in_list = True
            continue
        if in_list:
            m = re.match(r'^\s+-\s+"?([^"]+)"?\s*$', line)
            if m:
                paths.append(m.group(1).strip())
            else:
                break
    return paths


def is_effectively_always_on(path):
    """Return True if the rule has no paths: or paths: contains a catch-all glob."""
    paths = parse_paths_from_frontmatter(path)

    # No paths key = always-on
    if paths is None:
        return True

    # Empty paths list = always-on (no restriction)
    if len(paths) == 0:
        return True

    # If ANY pattern is a catch-all, the rule is effectively always-on
    for p in paths:
        if p.strip().strip('"').strip("'") in CATCH_ALL_PATTERNS:
            return True

    return False


def resolve_imports(path):
    """Count lines including @import targets."""
    total = count_lines(path)
    if not os.path.exists(path):
        return total
    with open(path) as f:
        for line in f:
            match = re.match(r"^@(.+)$", line.strip())
            if match:
                import_path = os.path.join(os.path.dirname(path), match.group(1))
                total += count_lines(import_path)
    return total


BASELINE_REL = os.path.join("q-system", ".q-system", "instruction-budget-baseline.json")
BASELINE_PATH = os.path.join(QROOT, ".q-system", "instruction-budget-baseline.json")

# The snapshot key for root CLAUDE.md. Deliberately not a bare filename: every
# rules key is a path relative to .claude/rules/ and ends in ".md", so this
# spelling can never collide with one.
CLAUDE_KEY = "::claude_md"


def measure(project_root):
    """(claude_md_lines, always_on, conditional) for a tree.

    os.walk, not os.listdir: apply_claude_changes.py's rule_text_only permits a
    rule at ANY depth under .claude/rules/, so a one-level count left a rule at
    .claude/rules/team/nested.md inside the sanctioned write path's reach and
    outside this budget at the same time -- uncounted always-on instructions
    while the gate reported held. The key is the path relative to rules/, which
    is byte-identical to the old bare filename for every top-level rule, so a
    baseline snapshot written before this change keeps matching.
    """
    claude_md_lines = resolve_imports(os.path.join(project_root, "CLAUDE.md"))
    rules_dir = os.path.join(project_root, ".claude", "rules")
    always_on, conditional = {}, {}
    if os.path.isdir(rules_dir):
        for dirpath, dirnames, filenames in os.walk(rules_dir):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for filename in sorted(filenames):
                if filename.startswith(".") or not filename.endswith(".md"):
                    continue
                full = os.path.join(dirpath, filename)
                key = os.path.relpath(full, rules_dir)
                lines = count_lines(full)
                if is_effectively_always_on(full):
                    always_on[key] = lines
                else:
                    conditional[key] = lines
    return claude_md_lines, always_on, conditional


def baseline_path(project_root):
    return os.path.join(project_root, BASELINE_REL)


def read_baseline(project_root):
    p = baseline_path(project_root)
    if not os.path.exists(p):
        return None
    try:
        with open(p) as f:
            data = json.load(f)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def cap_of(baseline):
    """The ONE reader of "what ceiling does this baseline declare".

    A legacy baseline carries only total_always_on, and is read as its own cap:
    that adopts the old floor without loosening it by a line. Two spellings of
    one judgement is the drift class this gate keeps finding, so the ratchet,
    --rules-cap and nothing else all ask this function.
    """
    if baseline is None:
        return None
    for key in ("cap", "total_always_on"):
        value = baseline.get(key)
        if isinstance(value, int):
            return value
    return None


def write_baseline(project_root, cap, total, files, note=None):
    data = {"cap": cap, "total_always_on": total, "files": files}
    if note:
        data["note"] = note
    p = baseline_path(project_root)
    with open(p, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    return p


def stage_baseline(path, project_root):
    """git add the baseline this run just rewrote.

    The ratchet runs as an UNATTENDED pre-commit hook, so the old "Stage this
    file with this commit" line told nobody: the commit landed carrying the old
    number while the working tree held the new one, and every clone then read a
    baseline that never matched its tree. No-ops outside a git work tree, so the
    fixture suites and a bare export are unaffected.
    """
    try:
        inside = subprocess.run(
            ["git", "-C", project_root, "rev-parse", "--is-inside-work-tree"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode
    except OSError:
        return False
    if inside != 0:
        return False
    try:
        return subprocess.run(
            ["git", "-C", project_root, "add", "--", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
    except OSError:
        return False


def _lines_deleted(snapshot, claude_md_lines, always_on, conditional):
    """Lines that LEFT the tree since the snapshot.

    A rule that merely moved from always-on to paths-scoped keeps every line on
    disk and still loads for the paths it names, so it contributes NOTHING here
    and the cap holds. A rule that shrank, that vanished, or that moved to
    paths-scoped and also shrank, contributes the lines it lost.
    """
    delta = 0
    for key, old in snapshot.items():
        if not isinstance(old, int):
            continue
        if key == CLAUDE_KEY:
            new = claude_md_lines
        elif key in always_on:
            new = always_on[key]
        elif key in conditional:
            new = conditional[key]
        else:
            new = 0
        if new < old:
            delta += old - new
    return delta


def run_ratchet(project_root, write=True, stage=True):
    """Regression gate against the committed cap. See ONE NUMBER BECAME TWO."""
    claude_md_lines, always_on, conditional = measure(project_root)
    total = claude_md_lines + sum(always_on.values())

    if claude_md_lines > BUDGET_CLAUDE_MD:
        print(
            f"RATCHET FAIL: CLAUDE.md {claude_md_lines} > {BUDGET_CLAUDE_MD} (absolute cap)"
        )
        return 1

    files = {CLAUDE_KEY: claude_md_lines}
    files.update(always_on)

    baseline = read_baseline(project_root)
    if baseline is None:
        if write:
            p = write_baseline(project_root, total, total, files)
            if stage:
                stage_baseline(p, project_root)
        print(f"RATCHET: baseline created at {total} "
              f"(cap {total}, target {BUDGET_TOTAL_ALWAYS_ON})")
        return 0

    cap = cap_of(baseline)
    if cap is None:
        print("RATCHET FAIL: baseline declares neither cap nor total_always_on; "
              f"repair {baseline_path(project_root)}")
        return 1

    snapshot = baseline.get("files")
    if isinstance(snapshot, dict):
        deletion_delta = _lines_deleted(snapshot, claude_md_lines, always_on, conditional)
    else:
        # A legacy baseline carries no per-file snapshot, so a drop cannot be
        # classified. Read it exactly the way the old gate did -- every drop is
        # a deletion -- which tightens and never loosens. The snapshot written
        # below is what lets the NEXT run tell scoping from deletion.
        deletion_delta = max(0, cap - total)

    cap_new = cap - deletion_delta
    if cap_new < 0:
        cap_new = 0

    if total > cap_new:
        print(
            f"RATCHET FAIL: always-on total {total} exceeds the cap {cap_new} "
            f"(+{total - cap_new}). Trim what you added, or move a rule to "
            f"paths-scoped -- that keeps the cap and banks the freed lines as "
            f"headroom. Target remains {BUDGET_TOTAL_ALWAYS_ON}."
        )
        return 1

    if write:
        p = write_baseline(project_root, cap_new, total, files, baseline.get("note"))
        if stage:
            stage_baseline(p, project_root)

    headroom = cap_new - total
    if cap_new < cap:
        print(f"RATCHET: tightened cap {cap} -> {cap_new} "
              f"({deletion_delta} line(s) left the tree). total {total}, "
              f"headroom {headroom}. Target {BUDGET_TOTAL_ALWAYS_ON}.")
    else:
        print(f"RATCHET PASS: total {total}, cap {cap_new}, headroom {headroom}. "
              f"Target {BUDGET_TOTAL_ALWAYS_ON}.")
    return 0


def main():
    argv = sys.argv[1:]
    project_root = PROJECT_ROOT
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 >= len(argv):
            print("--root needs a value")
            sys.exit(2)
        project_root = os.path.abspath(argv[i + 1])

    claude_md_lines, always_on, conditional = measure(project_root)
    always_on_rules = sum(always_on.values())

    # Machine modes. Both speak RULES-ONLY line units so they are directly
    # comparable: root CLAUDE.md is out of apply_claude_changes.py's reach, so a
    # staged copy of .claude/ does not carry one and a total that included it
    # would compare a tree against a different tree.
    if "--rules-total" in argv:
        print(always_on_rules)
        sys.exit(0)
    if "--rules-cap" in argv:
        cap = cap_of(read_baseline(project_root))
        print("none" if cap is None else max(0, cap - claude_md_lines))
        sys.exit(0)

    if "--ratchet" in argv:
        sys.exit(run_ratchet(project_root,
                             write="--no-write" not in argv,
                             stage="--no-stage" not in argv))

    total = claude_md_lines + always_on_rules

    print(f"CLAUDE.md (with imports): {claude_md_lines} / {BUDGET_CLAUDE_MD}")
    print(f"Always-on rules ({len(always_on)} files):")
    for name in sorted(always_on):
        print(f"  {name}: {always_on[name]}")
    print(f"Conditional rules ({len(conditional)} files):")
    for name in sorted(conditional):
        print(f"  {name}: {conditional[name]}")
    print(f"Total always-on (CLAUDE.md + rules): {total} / {BUDGET_TOTAL_ALWAYS_ON}")

    failed = False
    if claude_md_lines > BUDGET_CLAUDE_MD:
        print(
            f"\nFAIL: CLAUDE.md exceeds {BUDGET_CLAUDE_MD}-line budget "
            f"by {claude_md_lines - BUDGET_CLAUDE_MD} lines"
        )
        failed = True
    if total > BUDGET_TOTAL_ALWAYS_ON:
        print(
            f"\nFAIL: Total always-on exceeds {BUDGET_TOTAL_ALWAYS_ON}-line budget "
            f"by {total - BUDGET_TOTAL_ALWAYS_ON} lines"
        )
        failed = True

    if not failed:
        print("\nPASS: All budgets within limits")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
