#!/usr/bin/env python3
"""
Instance CLAUDE.md diet tool.

Analyzes an instance's CLAUDE.md and reports which sections duplicate
content already covered by skeleton rules, skills, or the slimmed
q-system/CLAUDE.md. Optionally rewrites the file with duplicates removed.

Usage:
    python3 instance-diet.py <instance-path>           # Audit only
    python3 instance-diet.py <instance-path> --fix     # Rewrite CLAUDE.md

Checks for:
1. Broken @import paths (file doesn't exist)
2. Sections that duplicate skeleton rules (token discipline, AUDHD, voice, etc.)
3. Total always-on line count vs 300-line budget
4. Import chain total size
"""

import os
import re
import sys

# Sections that are now covered by skeleton rules or auto-discovery.
# If an instance CLAUDE.md contains these, they're duplicate weight.
DUPLICATE_SECTION_PATTERNS = [
    # Covered by .claude/rules/token-discipline.md
    (r"(?i)token.?discipline", "token-discipline.md rule"),
    # Covered by .claude/rules/audhd-interaction.md
    (r"(?i)adhd.?aware.?interaction|audhd.?interaction", "audhd-interaction.md rule"),
    # Covered by output-style founder.md
    (r"(?i)formatting.?rules", "founder output style"),
    # Covered by .claude/rules/voice-enforcement.md + founder-voice skill
    (r"(?i)voice.?rules|writing.?style", "voice-enforcement.md rule"),
    # Claude Code discovers these automatically
    (r"(?i)^## (tech.?stack|mcp.?servers.?available)", "auto-discovered at startup"),
    # Covered by .claude/rules/folder-structure.md
    (r"(?i)^## project.?structure", "folder-structure.md rule"),
    # Covered by existing rules
    (r"(?i)^## tool.?preferences", "coded in rules/settings"),
    # Covered by q-system/CLAUDE.md
    (r"(?i)^## operating.?modes$", "q-system/CLAUDE.md or methodology/modes.md"),
]


def read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None


def count_nonblank(text):
    return sum(1 for line in text.splitlines() if line.strip())


def check_imports(claude_md_path, content):
    """Check @import paths exist."""
    issues = []
    base_dir = os.path.dirname(claude_md_path)
    for line in content.splitlines():
        m = re.match(r"^@(.+)$", line.strip())
        if m:
            import_path = os.path.join(base_dir, m.group(1))
            if os.path.exists(import_path):
                lines = count_nonblank(read_file(import_path))
                issues.append(("OK", f"@{m.group(1)} ({lines} lines)"))
            else:
                issues.append(("BROKEN", f"@{m.group(1)} -> {import_path} NOT FOUND"))
    return issues


def find_duplicate_sections(content):
    """Find ## sections that duplicate skeleton content."""
    dupes = []
    sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    for section in sections:
        if not section.strip():
            continue
        header_line = section.splitlines()[0] if section.splitlines() else ""
        section_lines = count_nonblank(section)
        for pattern, covered_by in DUPLICATE_SECTION_PATTERNS:
            if re.search(pattern, header_line):
                dupes.append((header_line.strip(), section_lines, covered_by))
                break
    return dupes


def count_always_on_rules(instance_path):
    """Count always-on rules lines (same logic as instruction-budget-audit.py)."""
    rules_dir = os.path.join(instance_path, ".claude", "rules")
    if not os.path.isdir(rules_dir):
        return 0, []

    catch_all = {"**/*", "**/**", "**"}
    total = 0
    files = []
    for f in sorted(os.listdir(rules_dir)):
        if not f.endswith(".md"):
            continue
        fpath = os.path.join(rules_dir, f)
        content = read_file(fpath)
        if content is None:
            continue

        is_always_on = True
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                fm = content[3:end]
                paths_match = re.search(r"^(paths|globs):", fm, re.MULTILINE)
                if paths_match:
                    is_always_on = False
                    # Check for catch-all
                    for line in fm.splitlines():
                        m = re.match(r'^\s+-\s+"?([^"]+)"?\s*$', line)
                        if m and m.group(1).strip() in catch_all:
                            is_always_on = True
                            break

        lines = count_nonblank(content)
        if is_always_on:
            total += lines
            files.append((f, lines))

    return total, files


def resolve_import_lines(claude_md_path, content):
    """Total lines including imports."""
    total = count_nonblank(content)
    base_dir = os.path.dirname(claude_md_path)
    for line in content.splitlines():
        m = re.match(r"^@(.+)$", line.strip())
        if m:
            import_path = os.path.join(base_dir, m.group(1))
            imported = read_file(import_path)
            if imported:
                total += count_nonblank(imported)
    return total


def main():
    if len(sys.argv) < 2:
        print("Usage: instance-diet.py <instance-path> [--fix]", file=sys.stderr)
        sys.exit(1)

    instance_path = os.path.abspath(sys.argv[1])
    fix_mode = "--fix" in sys.argv

    claude_md_path = os.path.join(instance_path, "CLAUDE.md")
    content = read_file(claude_md_path)

    if content is None:
        print(f"ERROR: {claude_md_path} not found")
        sys.exit(1)

    print(f"=== Instance Diet: {os.path.basename(instance_path)} ===\n")

    # 1. Imports
    imports = check_imports(claude_md_path, content)
    if imports:
        print("Imports:")
        for status, detail in imports:
            marker = "  OK" if status == "OK" else "  xx"
            print(f"  {marker}: {detail}")
        print()

    # 2. Duplicate sections
    dupes = find_duplicate_sections(content)
    if dupes:
        dupe_lines = sum(d[1] for d in dupes)
        print(f"Duplicate sections ({dupe_lines} lines removable):")
        for header, lines, covered_by in dupes:
            print(f"  - {header} ({lines} lines) -> already in {covered_by}")
        print()
    else:
        print("No duplicate sections found.\n")

    # 3. Budget
    claude_md_lines = resolve_import_lines(claude_md_path, content)
    rules_lines, rules_files = count_always_on_rules(instance_path)
    total = claude_md_lines + rules_lines

    print(f"Budget:")
    print(f"  CLAUDE.md (with imports): {claude_md_lines}")
    print(f"  Always-on rules: {rules_lines} ({len(rules_files)} files)")
    print(f"  Total always-on: {total} / 300")
    if total > 300:
        print(f"  OVER BUDGET by {total - 300} lines")
    else:
        print(f"  Under budget by {300 - total} lines")
    print()

    # 4. Fix mode
    if fix_mode and dupes:
        print("Applying diet...\n")
        new_content = content
        for header, _, _ in dupes:
            # Remove the section (from ## header to next ## or end of file)
            pattern = re.escape(header) + r"\n[\s\S]*?(?=\n## |\Z)"
            new_content = re.sub(pattern, "", new_content)

        # Fix broken imports
        for status, detail in imports:
            if status == "BROKEN":
                import_line = detail.split(" ->")[0]
                new_content = new_content.replace(import_line, f"# REMOVED (broken): {import_line}")

        # Clean up multiple blank lines
        new_content = re.sub(r"\n{3,}", "\n\n", new_content).strip() + "\n"

        new_lines = count_nonblank(new_content)
        saved = count_nonblank(content) - new_lines
        print(f"  Before: {count_nonblank(content)} lines")
        print(f"  After:  {new_lines} lines")
        print(f"  Saved:  {saved} lines")

        # Write backup and new file
        backup_path = claude_md_path + ".bak"
        with open(backup_path, "w") as f:
            f.write(content)
        with open(claude_md_path, "w") as f:
            f.write(new_content)
        print(f"\n  Backup: {backup_path}")
        print(f"  Rewritten: {claude_md_path}")

        # Re-check budget
        new_total = resolve_import_lines(claude_md_path, new_content) + rules_lines
        print(f"\n  New total always-on: {new_total} / 300")
    elif fix_mode:
        print("Nothing to fix.")

    sys.exit(0)


if __name__ == "__main__":
    main()
