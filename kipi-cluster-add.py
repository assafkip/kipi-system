#!/usr/bin/env python3
"""
kipi cluster add <path> <name> <role>

Plugs an existing instance into the KTLYST cluster:
1. Adds ## KTLYST Cluster section to the instance's CLAUDE.md
2. Updates the cluster table in ALL existing cluster members' CLAUDE.md files
3. Updates ~/.claude/rules/ktlyst-cluster.md
4. Adds the bridge inject hook to the instance's .claude/settings.json
5. Reports what it did

Usage:
    python3 kipi-cluster-add.py ~/projects/ktlyst-hub/new-instance "new_instance" "What this instance does"
"""

import json
import os
import re
import sys
from pathlib import Path

CLUSTER_RULE = Path.home() / ".claude" / "rules" / "ktlyst-cluster.md"
BRIDGE_INJECT_HOOK = {
    "type": "command",
    "command": 'bash "$HOME/.ktlyst/bridge/inject-bridge.sh" 2>/dev/null || true',
    "timeout": 5,
}


def load_cluster_members():
    """Parse existing cluster members from the rule file."""
    if not CLUSTER_RULE.exists():
        print("ERROR: ~/.claude/rules/ktlyst-cluster.md not found. Run cluster setup first.")
        sys.exit(1)

    members = []
    text = CLUSTER_RULE.read_text()
    for line in text.split("\n"):
        m = re.match(r"\|\s*(\w+)\s*\|\s*(~/[^\|]+?)\s*\|", line)
        if m and m.group(1) not in ("Instance", "---"):
            name = m.group(1).strip()
            path = m.group(2).strip()
            members.append({"name": name, "path": path})
    return members


def resolve_path(p):
    """Expand ~ and resolve to absolute path."""
    return str(Path(p).expanduser().resolve())


def build_table_row(name, path, role):
    """Build a markdown table row."""
    return f"| {name} | {path} | {role} |"


def extract_cluster_section(text):
    """Extract the KTLYST Cluster section from a CLAUDE.md."""
    lines = text.split("\n")
    start = None
    end = None
    for i, line in enumerate(lines):
        if line.strip() == "## KTLYST Cluster":
            start = i
        elif start is not None and line.startswith("## ") and i > start:
            end = i
            break
    if start is None:
        return None, None, None
    if end is None:
        end = len(lines)
    return start, end, lines


def find_table_in_section(lines, start, end):
    """Find the instance table within the cluster section."""
    table_start = None
    table_end = None
    for i in range(start, end):
        if lines[i].startswith("| Instance") or lines[i].startswith("| strategy") or lines[i].startswith("| product"):
            if table_start is None:
                table_start = i
            table_end = i + 1
        elif table_start is not None and lines[i].startswith("|"):
            table_end = i + 1
        elif table_start is not None and not lines[i].startswith("|"):
            break
    return table_start, table_end


def add_row_to_claude_md(filepath, new_name, new_path_display, new_role):
    """Add a new row to the cluster table in a CLAUDE.md file."""
    filepath = Path(filepath)
    if not filepath.exists():
        print(f"  SKIP: {filepath} not found")
        return False

    text = filepath.read_text()
    start, end, lines = extract_cluster_section(text)
    if start is None:
        print(f"  SKIP: No KTLYST Cluster section in {filepath}")
        return False

    table_start, table_end = find_table_in_section(lines, start, end)
    if table_start is None:
        print(f"  SKIP: No table found in cluster section of {filepath}")
        return False

    # Check if already present
    for i in range(table_start, table_end):
        if new_name in lines[i]:
            print(f"  SKIP: {new_name} already in {filepath}")
            return False

    new_row = build_table_row(new_name, new_path_display, new_role)
    lines.insert(table_end, new_row)
    filepath.write_text("\n".join(lines))
    print(f"  UPDATED: {filepath}")
    return True


def add_cluster_section_to_new_instance(instance_path, new_name, new_role, all_members):
    """Add the full KTLYST Cluster section to a new instance's CLAUDE.md."""
    claude_md = Path(instance_path) / "CLAUDE.md"
    if not claude_md.exists():
        print(f"  ERROR: {claude_md} not found")
        return False

    text = claude_md.read_text()

    # Check if already has cluster section
    if "## KTLYST Cluster" in text:
        print(f"  SKIP: {claude_md} already has KTLYST Cluster section")
        return False

    # Build the section
    section = "\n## KTLYST Cluster\n\n"
    section += "This instance is part of the KTLYST cluster. Repos share positioning and state.\n\n"
    section += "| Instance | Path | Owns |\n"
    section += "|----------|------|------|\n"
    for m in all_members:
        section += f"| {m['name']} | {m['path']} | {m.get('role', '')} |\n"

    section += f"\n**Bridge:** `~/.ktlyst/bridge/` - shared state files. Read `canonical-digest.json` before making positioning claims.\n"
    section += "**Canonical authority:** Strategy owns talk tracks and positioning. Do not contradict.\n"
    section += "**Cross-instance access:** Use `--add-dir ~/projects/ktlyst-hub/<instance>` when needed.\n"

    text = text.rstrip() + "\n" + section
    claude_md.write_text(text)
    print(f"  CREATED: Cluster section in {claude_md}")
    return True


def update_cluster_rule(new_name, new_path_display, new_role):
    """Add the new instance to ~/.claude/rules/ktlyst-cluster.md."""
    text = CLUSTER_RULE.read_text()

    if new_name in text:
        print(f"  SKIP: {new_name} already in cluster rule")
        return False

    # Find the instance table and add row
    lines = text.split("\n")
    for i, line in enumerate(lines):
        # Find last row of the instances table (before empty line or next section)
        if line.startswith("| lawyer") or (line.startswith("|") and i + 1 < len(lines) and not lines[i + 1].startswith("|")):
            if "Instance" not in line and "---" not in line:
                new_row = f"| {new_name} | {new_path_display} | {new_role} | (configure after adding) |"
                lines.insert(i + 1, new_row)
                break

    CLUSTER_RULE.write_text("\n".join(lines))
    print(f"  UPDATED: {CLUSTER_RULE}")
    return True


def add_bridge_hook(instance_path):
    """Add the bridge inject hook to the instance's .claude/settings.json."""
    settings_path = Path(instance_path) / ".claude" / "settings.json"

    if not settings_path.exists():
        print(f"  SKIP: {settings_path} not found (instance may not have settings.json yet)")
        return False

    data = json.loads(settings_path.read_text())
    hooks = data.get("hooks", {})
    session_start = hooks.get("SessionStart", [])

    # Check if bridge hook already exists
    for group in session_start:
        for h in group.get("hooks", []):
            if "inject-bridge" in h.get("command", ""):
                print(f"  SKIP: Bridge hook already in {settings_path}")
                return False

    # Add to first hook group's hooks array
    if session_start and "hooks" in session_start[0]:
        session_start[0]["hooks"].append(BRIDGE_INJECT_HOOK)
    else:
        # No SessionStart hooks exist, create the structure
        hooks["SessionStart"] = [
            {
                "matcher": "startup",
                "hooks": [BRIDGE_INJECT_HOOK],
            }
        ]
        data["hooks"] = hooks

    settings_path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"  UPDATED: {settings_path}")
    return True


def main():
    if len(sys.argv) < 4:
        print("Usage: kipi cluster add <path> <name> <role>")
        print("  path: absolute or ~/relative path to the instance")
        print("  name: short name (e.g., 'analytics')")
        print('  role: what this instance does (e.g., "Data analytics and reporting")')
        sys.exit(1)

    instance_path = resolve_path(sys.argv[1])
    new_name = sys.argv[2]
    new_role = sys.argv[3]

    # Use ~/Desktop/... display path for CLAUDE.md tables
    home = str(Path.home())
    if instance_path.startswith(home):
        display_path = "~" + instance_path[len(home):]
    else:
        display_path = instance_path

    if not Path(instance_path).exists():
        print(f"ERROR: {instance_path} does not exist")
        sys.exit(1)

    if not (Path(instance_path) / "CLAUDE.md").exists():
        print(f"ERROR: {instance_path}/CLAUDE.md not found. Is this a kipi instance?")
        sys.exit(1)

    print(f"Adding '{new_name}' ({instance_path}) to KTLYST cluster...")
    print(f"Role: {new_role}")
    print()

    # Load existing members
    existing = load_cluster_members()
    existing_paths = [resolve_path(m["path"]) for m in existing]

    if instance_path in existing_paths:
        print(f"ERROR: {instance_path} is already in the cluster")
        sys.exit(1)

    # Build full member list including the new one
    all_members = list(existing) + [{"name": new_name, "path": display_path, "role": new_role}]

    # Step 1: Add cluster section to new instance's CLAUDE.md
    print("1. Adding cluster section to new instance CLAUDE.md...")
    add_cluster_section_to_new_instance(instance_path, new_name, new_role, all_members)

    # Step 2: Update cluster table in all existing members' CLAUDE.md
    print("\n2. Updating cluster table in existing members...")
    for member in existing:
        member_path = resolve_path(member["path"])
        add_row_to_claude_md(
            Path(member_path) / "CLAUDE.md",
            new_name,
            display_path,
            new_role,
        )

    # Step 3: Update ~/.claude/rules/ktlyst-cluster.md
    print("\n3. Updating cluster rule file...")
    update_cluster_rule(new_name, display_path, new_role)

    # Step 4: Add bridge hook to settings.json
    print("\n4. Adding bridge inject hook...")
    add_bridge_hook(instance_path)

    # Summary
    print("\n--- Done ---")
    print(f"'{new_name}' is now part of the KTLYST cluster.")
    print(f"Bridge context will inject on next session start.")
    print(f"Other instances will see '{new_name}' in their cluster table.")


if __name__ == "__main__":
    main()
