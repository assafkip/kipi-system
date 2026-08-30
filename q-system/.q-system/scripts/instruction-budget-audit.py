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
committed baseline (instruction-budget-baseline.json) and auto-tightens the
baseline when the total shrinks. CLAUDE.md's own 200-line cap stays absolute
(it passes today). The 514->300 trim is tracked as its own spillover item.

prompt-only-enforcement-skip: THIS FILE IS A DETERMINISTIC BLOCKER (the pre-commit
ratchet), and the guard fired on its PRE-EXISTING docstring above -- prose about
baselines, blocks and caps -- the moment ASK-965 touched the file. Same
vocabulary-vs-existence gap the enforced-claim lint was built to close: the guard
matches words, and the words here describe the gate this file already is.
"""
import json
import os
import re
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


BASELINE_PATH = os.path.join(QROOT, ".q-system", "instruction-budget-baseline.json")


def read_baseline():
    if not os.path.exists(BASELINE_PATH):
        return None
    with open(BASELINE_PATH) as f:
        return json.load(f)


def write_baseline(total):
    with open(BASELINE_PATH, "w") as f:
        json.dump({"total_always_on": total}, f, indent=2)
        f.write("\n")


def run_ratchet(claude_md_lines, total):
    """Regression gate: block growth of the always-on total; tighten on shrink."""
    if claude_md_lines > BUDGET_CLAUDE_MD:
        print(
            f"RATCHET FAIL: CLAUDE.md {claude_md_lines} > {BUDGET_CLAUDE_MD} (absolute cap)"
        )
        return 1

    baseline = read_baseline()
    if baseline is None:
        write_baseline(total)
        print(f"RATCHET: baseline created at {total} (target {BUDGET_TOTAL_ALWAYS_ON})")
        return 0

    allowed = baseline["total_always_on"]
    if total > allowed:
        print(
            f"RATCHET FAIL: always-on total grew {allowed} -> {total} "
            f"(+{total - allowed}). Trim what you added, or move a rule to "
            f"paths-scoped. Target remains {BUDGET_TOTAL_ALWAYS_ON}."
        )
        return 1

    if total < allowed:
        write_baseline(total)
        print(
            f"RATCHET: tightened baseline {allowed} -> {total} "
            f"(target {BUDGET_TOTAL_ALWAYS_ON}). Stage {BASELINE_PATH} with this commit."
        )
        return 0

    print(f"RATCHET PASS: always-on total {total} (baseline {allowed}, target {BUDGET_TOTAL_ALWAYS_ON})")
    return 0


def main():
    claude_md = os.path.join(PROJECT_ROOT, "CLAUDE.md")
    rules_dir = os.path.join(PROJECT_ROOT, ".claude", "rules")

    claude_md_lines = resolve_imports(claude_md)

    always_on_rules = 0
    always_on_files = []
    conditional_files = []
    for f in sorted(os.listdir(rules_dir)):
        if not f.endswith(".md"):
            continue
        fpath = os.path.join(rules_dir, f)
        lines = count_lines(fpath)
        if is_effectively_always_on(fpath):
            always_on_rules += lines
            always_on_files.append((f, lines))
        else:
            conditional_files.append((f, lines))

    total = claude_md_lines + always_on_rules

    if "--ratchet" in sys.argv:
        sys.exit(run_ratchet(claude_md_lines, total))

    print(f"CLAUDE.md (with imports): {claude_md_lines} / {BUDGET_CLAUDE_MD}")
    print(f"Always-on rules ({len(always_on_files)} files):")
    for name, lines in always_on_files:
        print(f"  {name}: {lines}")
    print(f"Conditional rules ({len(conditional_files)} files):")
    for name, lines in conditional_files:
        print(f"  {name}: {lines}")
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
