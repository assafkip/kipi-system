#!/usr/bin/env python3
"""
Validate project folder structure against canonical layout.
Checks for misplaced files, naming violations, missing required files,
and forbidden patterns.

Usage:
    python3 validate-structure.py [--fix] [--json]

Exit 0 = pass
Exit 1 = violations found
"""

import json
import os
import re
import sys

# Resolve project root (kipi-system/)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
QROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
PROJECT_ROOT = os.path.normpath(os.path.join(QROOT, ".."))


# --- Required directories ---

REQUIRED_DIRS = [
    ".claude",
    ".claude/rules",
    ".claude/skills",
    "q-system",
    "q-system/canonical",
    "q-system/my-project",
    "q-system/marketing",
    "q-system/methodology",
    "q-system/memory",
    "q-system/memory/working",
    "q-system/memory/weekly",
    "q-system/memory/monthly",
    "q-system/output",
    "q-system/.q-system",
    "q-system/.q-system/scripts",
    "q-system/.q-system/data",
    "q-system/.q-system/agent-pipeline/schemas",
    "q-system/.q-system/onboarding",
    "q-system/.q-system/agent-pipeline",
    "q-system/.q-system/agent-pipeline/agents",
    "q-system/.q-system/agent-pipeline/bus",
    "q-system/.q-system/agent-pipeline/templates",
]

# --- Required files ---

REQUIRED_FILES = [
    "CLAUDE.md",
    ".mcp.json",
    ".gitignore",
    ".claude/settings.json",
    "q-system/CLAUDE.md",
    "q-system/canonical/talk-tracks.md",
    "q-system/canonical/objections.md",
    "q-system/canonical/discovery.md",
    "q-system/canonical/decisions.md",
    "q-system/canonical/market-intelligence.md",
    "q-system/my-project/current-state.md",
    "q-system/my-project/founder-profile.md",
    "q-system/my-project/relationships.md",
    "q-system/methodology/debrief-template.md",
    "q-system/.q-system/preflight.md",
    "q-system/.q-system/commands.md",
    "q-system/.q-system/token-guard.py",
    "q-system/.q-system/audit-morning.py",
    "q-system/.q-system/sycophancy-harness.py",
    "q-system/.q-system/verify-bus.py",
    "q-system/.q-system/scripts/scan-draft.py",
    "q-system/.q-system/agent-pipeline/agents/step-orchestrator.md",
]

# --- Forbidden patterns ---

FORBIDDEN_PATTERNS = [
    # Shadow .q-system directories
    (r"q-system/\.q-system/\.q-system", "Shadow .q-system directory (double nesting)"),
    # Secrets in committed files
    (r"\.env$", "Environment file should be gitignored"),
    (r"credentials\.json$", "Credentials file should be gitignored"),
    # Misplaced agents
    (r"\.claude/agents/", "Agent files belong in q-system/.q-system/agent-pipeline/agents/"),
    # Output files in wrong location
    (r"q-system/[^/]+\.html$", "HTML output belongs in q-system/output/"),
    (r"q-system/[^/]+\.json$", "JSON output belongs in q-system/output/ or appropriate subdir"),
]

# --- Naming conventions ---

NAMING_RULES = {
    ".claude/rules": {
        "pattern": r"^[a-z][a-z0-9-]*\.md$",
        "description": "Rules must be kebab-case.md",
    },
    ".claude/skills": {
        "pattern": r"^[a-z][a-z0-9-]*$",
        "description": "Skill directories must be kebab-case",
        "is_dir": True,
    },
    "q-system/.q-system/agent-pipeline/agents": {
        "pattern": r"^(_[a-z][a-z0-9-]*\.md|[0-9]{2}[a-z0-9-]*\.md|step-orchestrator\.md|README\.md)$",
        "description": "Agent files must be NN-name.md, _config-name.md, or step-orchestrator.md",
    },
    "q-system/.q-system/scripts": {
        "pattern": r"^[a-z][a-z0-9_-]*\.py$",
        "description": "Scripts must be kebab-case or snake_case .py",
    },
}

# --- Skill structure validation ---

def validate_skill(skill_dir):
    """Check that a skill directory has required SKILL.md."""
    errors = []
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_md):
        errors.append(f"Missing SKILL.md in {os.path.relpath(skill_dir, PROJECT_ROOT)}")
    else:
        with open(skill_md) as f:
            content = f.read()
        # Check for frontmatter (recommended)
        if not content.startswith("---"):
            errors.append(f"SKILL.md missing YAML frontmatter: {os.path.relpath(skill_md, PROJECT_ROOT)}")
    return errors


def validate_agent(agent_file):
    """Check that an agent .md file has proper YAML frontmatter."""
    errors = []
    with open(agent_file) as f:
        content = f.read()
    basename = os.path.basename(agent_file)
    if basename.startswith("_"):
        return errors  # Config files don't need frontmatter
    if not content.startswith("---"):
        errors.append(f"Agent missing YAML frontmatter: {basename}")
    else:
        # Check required frontmatter fields
        front_end = content.find("---", 3)
        if front_end == -1:
            errors.append(f"Agent has unclosed frontmatter: {basename}")
        else:
            frontmatter = content[3:front_end]
            if "name:" not in frontmatter:
                errors.append(f"Agent missing 'name:' in frontmatter: {basename}")
            if "model:" not in frontmatter:
                errors.append(f"Agent missing 'model:' in frontmatter: {basename}")
    return errors


def validate_rules_frontmatter(rule_file):
    """Check rules file frontmatter for path-scoping (recommended, not required)."""
    warnings = []
    with open(rule_file) as f:
        content = f.read()
    if not content.startswith("---"):
        warnings.append(f"Rule has no frontmatter (path-scoping recommended): {os.path.basename(rule_file)}")
    return warnings


def validate_claude_md_size(filepath, max_lines=200):
    """Check CLAUDE.md file size against recommended limit."""
    warnings = []
    with open(filepath) as f:
        lines = f.readlines()
    if len(lines) > max_lines:
        warnings.append(f"CLAUDE.md exceeds {max_lines} lines ({len(lines)} lines): {os.path.relpath(filepath, PROJECT_ROOT)}")
    return warnings


def validate_qroot_in_scripts():
    """Check that all Python scripts in scripts/ resolve QROOT correctly."""
    errors = []
    scripts_dir = os.path.join(QROOT, ".q-system", "scripts")
    if not os.path.isdir(scripts_dir):
        return errors
    for fname in os.listdir(scripts_dir):
        if not fname.endswith(".py"):
            continue
        fpath = os.path.join(scripts_dir, fname)
        with open(fpath) as f:
            content = f.read()
        # Scripts in scripts/ must go up 2 levels
        if 'os.path.join(os.path.dirname(__file__), "..")' in content:
            if '"..", ".."' not in content:
                errors.append(f"QROOT goes up only 1 level (needs 2): {fname}")
    return errors


def main():
    fix_mode = "--fix" in sys.argv
    json_output = "--json" in sys.argv

    errors = []
    warnings = []

    # 1. Check required directories
    for d in REQUIRED_DIRS:
        path = os.path.join(PROJECT_ROOT, d)
        if not os.path.isdir(path):
            errors.append(f"Missing required directory: {d}")

    # 2. Check required files
    for f in REQUIRED_FILES:
        path = os.path.join(PROJECT_ROOT, f)
        if not os.path.isfile(path):
            errors.append(f"Missing required file: {f}")

    # 3. Check forbidden patterns
    for root, dirs, files in os.walk(PROJECT_ROOT):
        # Skip node_modules, .git
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        rel_root = os.path.relpath(root, PROJECT_ROOT)
        for fname in files:
            rel_path = os.path.join(rel_root, fname)
            for pattern, desc in FORBIDDEN_PATTERNS:
                if re.search(pattern, rel_path):
                    errors.append(f"Forbidden: {rel_path} ({desc})")

    # 4. Check naming conventions
    for dir_path, rules in NAMING_RULES.items():
        full_path = os.path.join(PROJECT_ROOT, dir_path)
        if not os.path.isdir(full_path):
            continue
        is_dir = rules.get("is_dir", False)
        pattern = re.compile(rules["pattern"])
        for item in os.listdir(full_path):
            item_path = os.path.join(full_path, item)
            if is_dir and not os.path.isdir(item_path):
                continue
            if not is_dir and not os.path.isfile(item_path):
                continue
            if not pattern.match(item):
                warnings.append(f"Naming violation in {dir_path}/: '{item}' ({rules['description']})")

    # 5. Validate skills
    skills_dir = os.path.join(PROJECT_ROOT, ".claude", "skills")
    if os.path.isdir(skills_dir):
        for skill_name in os.listdir(skills_dir):
            skill_path = os.path.join(skills_dir, skill_name)
            if os.path.isdir(skill_path):
                errors.extend(validate_skill(skill_path))

    # 6. Validate agents
    agents_dir = os.path.join(PROJECT_ROOT, "q-system", ".q-system", "agent-pipeline", "agents")
    if os.path.isdir(agents_dir):
        for fname in os.listdir(agents_dir):
            if fname.endswith(".md"):
                errors.extend(validate_agent(os.path.join(agents_dir, fname)))

    # 7. Validate CLAUDE.md sizes
    for md_path in ["CLAUDE.md", "q-system/CLAUDE.md"]:
        full = os.path.join(PROJECT_ROOT, md_path)
        if os.path.isfile(full):
            warnings.extend(validate_claude_md_size(full))

    # 8. Validate QROOT resolution in scripts
    errors.extend(validate_qroot_in_scripts())

    # 9. Check .gitignore has required entries
    gitignore_path = os.path.join(PROJECT_ROOT, ".gitignore")
    if os.path.isfile(gitignore_path):
        with open(gitignore_path) as f:
            gi_content = f.read()
        required_ignores = [".env", "settings.local.json"]
        for ri in required_ignores:
            if ri not in gi_content:
                errors.append(f".gitignore missing required entry: {ri}")

    # 10. Check for legacy commands that should be skills
    commands_dir = os.path.join(PROJECT_ROOT, ".claude", "commands")
    if os.path.isdir(commands_dir):
        cmd_files = [f for f in os.listdir(commands_dir) if f.endswith(".md")]
        if cmd_files:
            warnings.append(f".claude/commands/ has {len(cmd_files)} files - migrate to plugins/<group>/skills/")

    # Output
    result = {
        "pass": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
    }

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        if errors:
            print(f"FAIL: {len(errors)} errors, {len(warnings)} warnings\n")
            for e in errors:
                print(f"  ERROR: {e}")
        else:
            print(f"PASS: 0 errors, {len(warnings)} warnings\n")
        if warnings:
            print("")
            for w in warnings:
                print(f"  WARN:  {w}")

    sys.exit(0 if len(errors) == 0 else 1)


if __name__ == "__main__":
    main()
