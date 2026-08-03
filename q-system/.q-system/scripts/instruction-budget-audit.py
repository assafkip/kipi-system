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
committed cap. CLAUDE.md's own 200-line cap stays absolute (it passes today).

WHY THE CAP AND THE LAST TOTAL ARE TWO NUMBERS (ASK-285; do not collapse them
back into one):

The ratchet used to auto-tighten its baseline to the total on every shrink. That
made it mutually exclusive with the only sanctioned write path into .claude/.
apply_claude_changes.py is additive-only and refuses ANY frontmatter change on
any op, so through that route the always-on total can grow or stay flat and can
never drop. A cap that tightens on every drop and refuses every rise therefore
refused every rule-file append that route could express: the only way through was
to find unrelated dead weight somewhere else and delete it. PR #48 got through
exactly that way, by the luck of a duplicated paragraph existing in root
CLAUDE.md, and neither the duplicate nor the direct writability generalises.

The fix is in the ACCOUNTING, not in the write path's vocabulary. Additive-only
is why that route is safe to run unattended (ASK-282), so it stays untouched.
A drop in the always-on total is now classified:

  scoping  : a rule that was always-on at the last audit and now carries
             paths:/globs: frontmatter, with its body intact. Its lines stop
             loading every turn. The cap does NOT follow the total down, so the
             freed lines stay as headroom that a later append may spend.
  deletion : anything else -- lines removed from a rule, a rule deleted, root
             CLAUDE.md trimmed. The cap follows the total down, permanently,
             exactly as it did before.

The cap therefore changes only by `-deletion_delta`, which is never negative, so
it is monotone NON-INCREASING by construction: "the floor may tighten, never
loosen" holds. Scoping buys back budget it genuinely freed; it never raises the
ceiling above a value the repo has already lived under.

WHO CAN BANK HEADROOM (say it plainly): scoping means editing a rule's
frontmatter, and apply_claude_changes.py refuses that on every op because a
narrowed paths: switches a rule off while body, tokens and line count all stay
identical (PR #70 rounds 3 and 4, both MAJOR). So an agent cannot bank headroom;
the founder can, with an ordinary edit. An agent SPENDS headroom. That split is
deliberate: deciding a rule may stop loading is a judgement call, and keeping
judgement calls out of the unattended engine is the property that makes it safe.

HONEST BOUNDARY: this baseline JSON lives outside .claude/, so an agent's
ordinary tools can write it and nothing here stops a fabricated cap. The
protection is that the file is tracked and any change to it lands in the commit
diff. That was equally true before this change; it is not a regression, and it is
not a claim this script makes good on.
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

# Baseline keys. `cap` is the gate; `total_always_on` is the last observed total
# and is what the next run diffs against. They were one field before ASK-285 and
# are equal in a repo that has only ever deleted, which is why the old name keeps
# its old meaning for any reader that only knows about one number.
KEY_CAP = "cap"
KEY_TOTAL = "total_always_on"
KEY_SNAPSHOT = "always_on_files"


def count_lines(path):
    if not os.path.exists(path):
        return 0
    with open(path) as f:
        return sum(1 for line in f if line.strip())


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


def baseline_path(project_root):
    return os.path.join(project_root, "q-system", ".q-system",
                        "instruction-budget-baseline.json")


def read_baseline(project_root):
    path = baseline_path(project_root)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def write_baseline(project_root, cap, total, always_on):
    path = baseline_path(project_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({KEY_CAP: cap, KEY_TOTAL: total,
                   KEY_SNAPSHOT: dict(sorted(always_on.items()))}, f, indent=2)
        f.write("\n")


def scan_rules(rules_dir):
    """Return (always_on, conditional) as {filename: substantive line count}."""
    always_on = {}
    conditional = {}
    if not os.path.isdir(rules_dir):
        return always_on, conditional
    for name in sorted(os.listdir(rules_dir)):
        if not name.endswith(".md"):
            continue
        full = os.path.join(rules_dir, name)
        lines = count_lines(full)
        if is_effectively_always_on(full):
            always_on[name] = lines
        else:
            conditional[name] = lines
    return always_on, conditional


def scoping_freed(snapshot, always_on, conditional):
    """Lines the last audit counted as always-on that are now paths-scoped.

    Returns (freed_lines, [(name, lines), ...]).

    Only a rule that WAS always-on can free anything: a brand-new paths-scoped
    rule was never costing always-on lines, so crediting it would mint headroom
    out of nothing. A rule that vanished entirely is a deletion and earns no
    credit either -- deleting a rule already tightens the cap, which is the
    behaviour that has held since the ratchet was resurrected.

    A rule that was scoped AND shortened in the same step is credited only
    min(before, after): the shortening half is a deletion and tightens the cap
    like any other.
    """
    freed = 0
    moved = []
    for name, before in sorted(snapshot.items()):
        if name in always_on:
            continue
        if name not in conditional:
            continue
        credited = min(before, conditional[name])
        if credited <= 0:
            continue
        freed += credited
        moved.append((name, credited))
    return freed, moved


def ratchet_fail_text(cap, total, always_on):
    """The message an agent reads when it is over the cap.

    It names the moves that are actually REACHABLE from where the reader stands,
    because the old text ("Trim what you added, or move a rule to paths-scoped")
    named two moves the sanctioned write path cannot make and cost a full agent
    pass to discover (ASK-285).
    """
    candidates = sorted(always_on.items(), key=lambda kv: -kv[1])[:3]
    named = ", ".join("%s (%d)" % (n, c) for n, c in candidates) or "none"
    return (
        "RATCHET FAIL: always-on total {cap} -> {total} (+{over}); headroom 0.\n"
        "  Reachable with no deletion anywhere: put the new lines in a rule that "
        "declares paths:/globs: frontmatter. A paths-scoped rule costs 0 always-on "
        "lines, create_file through apply-claude-changes.sh can make one, and "
        "appending to an already-scoped rule is free.\n"
        "  Growing an ALWAYS-ON rule needs headroom, and only scoping an existing "
        "always-on rule creates it. Largest candidates: {named}.\n"
        "  Scoping is a founder edit: apply_claude_changes.py refuses frontmatter "
        "changes on every op, because a narrowed paths: switches a rule off.\n"
        "  Target remains {target}."
    ).format(cap=cap, total=total, over=total - cap, named=named,
             target=BUDGET_TOTAL_ALWAYS_ON)


def run_ratchet(project_root, claude_md_lines, total, always_on, conditional, write=True):
    """Regression gate: block growth past the cap; tighten the cap on deletion."""
    if claude_md_lines > BUDGET_CLAUDE_MD:
        print(
            f"RATCHET FAIL: CLAUDE.md {claude_md_lines} > {BUDGET_CLAUDE_MD} (absolute cap)"
        )
        return 1

    baseline = read_baseline(project_root)
    if baseline is None:
        if write:
            write_baseline(project_root, total, total, always_on)
        print(f"RATCHET: baseline created at {total} (target {BUDGET_TOTAL_ALWAYS_ON})")
        return 0

    # A pre-ASK-285 baseline carries one number that meant both cap and total.
    # Reading it as both is exactly the old behaviour, so the upgrade run cannot
    # move the gate: it only records the snapshot the next run needs.
    cap = baseline.get(KEY_CAP, baseline.get(KEY_TOTAL))
    prev_total = baseline.get(KEY_TOTAL, cap)
    snapshot = baseline.get(KEY_SNAPSHOT)

    if total > cap:
        print(ratchet_fail_text(cap, total, always_on))
        return 1

    if snapshot is None:
        # No snapshot to diff against, so no drop can be attributed to scoping.
        # Fall back to the old auto-tighten, which is the conservative answer.
        freed, moved = 0, []
    else:
        freed, moved = scoping_freed(snapshot, always_on, conditional)

    delta = prev_total - total
    deletion_delta = max(0, delta - freed)
    new_cap = cap - deletion_delta

    changed = (new_cap != cap or total != prev_total or snapshot is None)
    if changed and write:
        write_baseline(project_root, new_cap, total, always_on)

    scoped_note = ""
    if moved:
        scoped_note = " scoped: %s;" % ", ".join("%s (%d)" % (n, c) for n, c in moved)
    if new_cap < cap:
        print(f"RATCHET: tightened cap {cap} -> {new_cap} on {deletion_delta} deleted "
              f"line(s).{scoped_note} total {total}, headroom {new_cap - total} "
              f"(target {BUDGET_TOTAL_ALWAYS_ON}).")
    else:
        print(f"RATCHET PASS: total {total}, cap {new_cap}, headroom "
              f"{new_cap - total}.{scoped_note} Target {BUDGET_TOTAL_ALWAYS_ON}.")
    if changed and write:
        print(f"RATCHET: stage {baseline_path(project_root)} with this commit.")
    return 0


def parse_root(argv):
    """--root DIR overrides the tree under audit.

    One resolver, so the baseline path, CLAUDE.md and the rules dir cannot end up
    pointing at different trees. Without it the script derives everything from
    __file__, which means a test fixture is audited only if the test copies the
    script into the fixture AND nothing else in the tree disagrees -- and it
    means apply_claude_changes.py could not run this as a gate against a
    --root'ed tree at all.
    """
    if "--root" not in argv:
        return PROJECT_ROOT
    idx = argv.index("--root")
    if idx + 1 >= len(argv):
        print("--root needs a value")
        sys.exit(2)
    return os.path.abspath(argv[idx + 1])


def main():
    argv = sys.argv[1:]
    project_root = parse_root(argv)
    write = "--no-write" not in argv

    claude_md = os.path.join(project_root, "CLAUDE.md")
    rules_dir = os.path.join(project_root, ".claude", "rules")

    claude_md_lines = resolve_imports(claude_md)
    always_on, conditional = scan_rules(rules_dir)
    total = claude_md_lines + sum(always_on.values())

    if "--ratchet" in argv:
        sys.exit(run_ratchet(project_root, claude_md_lines, total,
                             always_on, conditional, write=write))

    print(f"CLAUDE.md (with imports): {claude_md_lines} / {BUDGET_CLAUDE_MD}")
    print(f"Always-on rules ({len(always_on)} files):")
    for name, lines in sorted(always_on.items()):
        print(f"  {name}: {lines}")
    print(f"Conditional rules ({len(conditional)} files):")
    for name, lines in sorted(conditional.items()):
        print(f"  {name}: {lines}")
    print(f"Total always-on (CLAUDE.md + rules): {total} / {BUDGET_TOTAL_ALWAYS_ON}")

    baseline = read_baseline(project_root)
    if baseline is not None:
        cap = baseline.get(KEY_CAP, baseline.get(KEY_TOTAL))
        print(f"Ratchet cap: {cap} (headroom {cap - total})")

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
