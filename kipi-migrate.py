#!/usr/bin/env python3
"""
kipi-migrate.py - Programmatic instance compliance migration tool.

Takes any instance from its existing state and makes it fully compliant
with the kipi-system skeleton structure, Anthropic Claude Code docs,
and all skeleton rules.

Usage:
    python3 kipi-migrate.py <instance-path> [--dry-run] [--verbose]

Phases:
    1. AUDIT   - Scan instance, report compliance gaps
    2. STRUCT  - Fix directory structure (.claude/, q-system/, instance content dir)
    3. CONFIG  - Sync settings.json, rules, agents, output-styles, plugins, hooks
    4. CLAUDE  - Fix CLAUDE.md imports and structure
    5. CODE    - Apply coding standards to existing code
    6. VERIFY  - Run validation checks
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# --- Constants ---

SKELETON_DIR = os.path.dirname(os.path.abspath(__file__))
SKELETON_REMOTE = "https://github.com/assafkip/kipi-system.git"

REQUIRED_CLAUDE_DIRS = [
    ".claude/agents",
    ".claude/output-styles",
    ".claude/rules",
]

REQUIRED_SKELETON_FILES = [
    "q-system/q-system/CLAUDE.md",
    "q-system/q-system/.q-system/token-guard.py",
    "q-system/q-system/.q-system/agent-pipeline/agents/step-orchestrator.md",
]

# Anthropic docs: correct frontmatter for rules files
RULES_FRONTMATTER_PATTERN = re.compile(
    r"^---\n(.*?)\n---\n", re.DOTALL
)

# Files that must never be in .claude/skills/ (old location)
OLD_SKILLS_INDICATOR = ".claude/skills"

# Coding standards checks
BASH_SHEBANG = "#!/bin/bash"
BASH_STRICT = "set -euo pipefail"
PYTHON_MAIN_GUARD = 'if __name__ == "__main__"'


def log(msg, verbose=False, level="INFO"):
    """Print with level prefix."""
    colors = {"INFO": "\033[0;34m", "PASS": "\033[0;32m", "FAIL": "\033[0;31m",
              "WARN": "\033[0;33m", "FIX": "\033[0;36m", "SKIP": "\033[0;90m"}
    reset = "\033[0m"
    prefix = colors.get(level, "") + f"[{level}]" + reset
    if level in ("PASS", "FAIL", "WARN", "FIX") or verbose:
        print(f"  {prefix} {msg}")


class MigrationContext:
    def __init__(self, instance_path, dry_run=False, verbose=False):
        self.path = os.path.abspath(instance_path)
        self.dry_run = dry_run
        self.verbose = verbose
        self.fixes = []
        self.warnings = []
        self.passes = []
        self.instance_name = os.path.basename(self.path)

    def fix(self, msg, action=None):
        """Record a fix. If not dry run, execute action."""
        self.fixes.append(msg)
        log(msg, level="FIX")
        if not self.dry_run and action:
            action()

    def warn(self, msg):
        self.warnings.append(msg)
        log(msg, level="WARN")

    def ok(self, msg):
        self.passes.append(msg)
        log(msg, level="PASS", verbose=self.verbose)

    def fail(self, msg):
        log(msg, level="FAIL")

    def p(self, *args):
        return os.path.join(self.path, *args)

    def exists(self, *args):
        return os.path.exists(self.p(*args))

    def is_dir(self, *args):
        return os.path.isdir(self.p(*args))


# --- Phase 1: AUDIT ---

def phase_audit(ctx):
    """Scan instance and report current state."""
    print(f"\n=== Phase 1: AUDIT ({ctx.instance_name}) ===")

    # Git repo?
    if ctx.is_dir(".git"):
        ctx.ok("Git repository initialized")
    else:
        ctx.warn("No git repo. Will need git init.")

    # Skeleton subtree?
    if ctx.is_dir("q-system"):
        ctx.ok("q-system/ subtree present")
        # Check nesting: q-system/q-system/ means proper subtree
        if ctx.is_dir("q-system", "q-system"):
            ctx.ok("Skeleton content at q-system/q-system/ (subtree nesting)")
        elif ctx.exists("q-system", "CLAUDE.md"):
            ctx.warn("q-system/ has flat structure (direct clone or shallow subtree)")
    else:
        ctx.warn("No q-system/ subtree. Will add.")

    # .claude/ directory
    for d in REQUIRED_CLAUDE_DIRS:
        if ctx.is_dir(d):
            ctx.ok(f"{d}/ exists")
        else:
            ctx.warn(f"{d}/ missing")

    # Old .claude/skills/ (should be plugins now)
    if ctx.is_dir(OLD_SKILLS_INDICATOR):
        ctx.warn(".claude/skills/ exists (old location, should be marketplace plugins)")

    # settings.json
    if ctx.exists(".claude", "settings.json"):
        ctx.ok(".claude/settings.json exists")
        try:
            with open(ctx.p(".claude", "settings.json")) as f:
                settings = json.load(f)
            # Check required keys
            for key in ["permissions", "hooks", "outputStyle"]:
                if key in settings:
                    ctx.ok(f"settings.json has '{key}'")
                else:
                    ctx.warn(f"settings.json missing '{key}'")
        except json.JSONDecodeError:
            ctx.warn("settings.json is invalid JSON")
    else:
        ctx.warn(".claude/settings.json missing")

    # CLAUDE.md
    if ctx.exists("CLAUDE.md"):
        ctx.ok("CLAUDE.md exists")
        with open(ctx.p("CLAUDE.md")) as f:
            content = f.read()
        if "@q-system" in content:
            ctx.ok("CLAUDE.md imports skeleton via @q-system")
        else:
            ctx.warn("CLAUDE.md does not import skeleton")
    else:
        ctx.warn("No CLAUDE.md")

    # Plugins
    if ctx.is_dir("plugins"):
        ctx.ok("plugins/ directory present")
    else:
        ctx.warn("plugins/ missing")

    # .githooks
    if ctx.is_dir(".githooks"):
        ctx.ok(".githooks/ present")
    else:
        ctx.warn(".githooks/ missing")

    # .gitignore
    if ctx.exists(".gitignore"):
        ctx.ok(".gitignore exists")
    else:
        ctx.warn(".gitignore missing")

    # Scan for code files
    code_files = {"py": [], "js": [], "sh": [], "yaml": [], "md": []}
    for root, dirs, files in os.walk(ctx.path):
        # Skip skeleton, dependencies, .git, plugins, virtual envs
        rel = os.path.relpath(root, ctx.path)
        skip_dirs = ["q-system", "node_modules", ".git", "plugins", ".claude",
                     ".venv", "venv", "__pycache__", ".cache", "dist", "build",
                     "site-packages", ".githooks"]
        rel_parts = set(Path(rel).parts)
        if rel_parts & set(skip_dirs):
            continue
        for f in files:
            ext = f.rsplit(".", 1)[-1] if "." in f else ""
            if ext in code_files:
                code_files[ext].append(os.path.join(root, f))

    for ext, files in code_files.items():
        if files:
            ctx.ok(f"Found {len(files)} .{ext} files in instance content")

    return code_files


# --- Phase 2: STRUCT ---

def phase_struct(ctx):
    """Fix directory structure."""
    print(f"\n=== Phase 2: STRUCTURE ===")

    # Git init if needed
    if not ctx.is_dir(".git"):
        ctx.fix("Initializing git repo", lambda: subprocess.run(
            ["git", "init"], cwd=ctx.path, capture_output=True))

    # Add skeleton subtree if missing
    if not ctx.is_dir("q-system"):
        def add_subtree():
            subprocess.run(["git", "add", "-A"], cwd=ctx.path, capture_output=True)
            subprocess.run(["git", "commit", "-m", "chore: pre-subtree commit"],
                           cwd=ctx.path, capture_output=True)
            subprocess.run(
                ["git", "subtree", "add", "--prefix=q-system",
                 SKELETON_REMOTE, "main", "--squash"],
                cwd=ctx.path, capture_output=True)
        ctx.fix("Adding q-system/ subtree from skeleton", add_subtree)
    else:
        ctx.ok("q-system/ subtree already present")

    # Create required .claude/ directories
    for d in REQUIRED_CLAUDE_DIRS:
        full = ctx.p(d)
        if not os.path.isdir(full):
            ctx.fix(f"Creating {d}/", lambda d=full: os.makedirs(d, exist_ok=True))
        else:
            ctx.ok(f"{d}/ exists")

    # Remove old .claude/skills/ if present
    old_skills = ctx.p(OLD_SKILLS_INDICATOR)
    if os.path.isdir(old_skills):
        ctx.fix("Removing .claude/skills/ (replaced by marketplace plugins)",
                lambda: shutil.rmtree(old_skills))

    # Create .githooks/
    hooks_dir = ctx.p(".githooks")
    if not os.path.isdir(hooks_dir):
        def copy_hooks():
            os.makedirs(hooks_dir, exist_ok=True)
            for f in os.listdir(os.path.join(SKELETON_DIR, ".githooks")):
                src = os.path.join(SKELETON_DIR, ".githooks", f)
                dst = os.path.join(hooks_dir, f)
                shutil.copy2(src, dst)
                os.chmod(dst, 0o755)
            subprocess.run(["git", "config", "core.hooksPath", ".githooks"],
                           cwd=ctx.path, capture_output=True)
        ctx.fix("Installing .githooks/ from skeleton", copy_hooks)
    else:
        ctx.ok(".githooks/ present")


# --- Phase 3: CONFIG ---

def phase_config(ctx):
    """Sync settings, rules, agents, output-styles, plugins."""
    print(f"\n=== Phase 3: CONFIG ===")

    # Settings.json - merge from template
    settings_path = ctx.p(".claude", "settings.json")
    template_path = os.path.join(SKELETON_DIR, "settings-template.json")

    if os.path.exists(settings_path) and os.path.exists(template_path):
        def merge_settings():
            template = json.load(open(template_path))
            existing = json.load(open(settings_path))
            merged = dict(template)

            # Preserve instance MCP servers
            if "mcpServers" in existing:
                merged["mcpServers"] = dict(template.get("mcpServers", {}))
                for k, v in existing["mcpServers"].items():
                    merged["mcpServers"][k] = v

            # Preserve instance enabled plugins (additive)
            if "enabledPlugins" in existing:
                merged["enabledPlugins"] = dict(template.get("enabledPlugins", {}))
                merged["enabledPlugins"].update(existing["enabledPlugins"])

            # Preserve instance permission additions (union)
            if "permissions" in existing and "allow" in existing["permissions"]:
                template_allow = set(template.get("permissions", {}).get("allow", []))
                instance_allow = set(existing["permissions"]["allow"])
                merged["permissions"]["allow"] = sorted(template_allow | instance_allow)

            # Preserve instance tool configurations
            if "toolConfigurations" in existing:
                merged["toolConfigurations"] = dict(template.get("toolConfigurations", {}))
                merged["toolConfigurations"].update(existing["toolConfigurations"])

            # Preserve model override
            if existing.get("model") and existing.get("model") != template.get("model"):
                merged["model"] = existing["model"]

            # Fix paths for subtree nesting
            raw = json.dumps(merged, indent=2)
            raw = raw.replace("/q-system/hooks/", "/q-system/q-system/hooks/")
            raw = raw.replace("/q-system/.q-system/", "/q-system/q-system/.q-system/")
            merged = json.loads(raw)

            with open(settings_path, "w") as f:
                json.dump(merged, f, indent=2)

        ctx.fix("Merging settings.json from template (preserving instance config)", merge_settings)
    elif not os.path.exists(settings_path):
        def create_settings():
            shutil.copy2(template_path, settings_path)
            # Fix paths
            with open(settings_path) as f:
                raw = f.read()
            raw = raw.replace("/q-system/hooks/", "/q-system/q-system/hooks/")
            raw = raw.replace("/q-system/.q-system/", "/q-system/q-system/.q-system/")
            with open(settings_path, "w") as f:
                f.write(raw)
        ctx.fix("Creating settings.json from template", create_settings)

    # Sync rules, agents, output-styles from skeleton
    for subdir in ["agents", "output-styles", "rules"]:
        src_dir = os.path.join(SKELETON_DIR, ".claude", subdir)
        dst_dir = ctx.p(".claude", subdir)
        if not os.path.isdir(src_dir):
            continue
        synced = 0
        for f in os.listdir(src_dir):
            if not f.endswith(".md"):
                continue
            src = os.path.join(src_dir, f)
            dst = os.path.join(dst_dir, f)
            if not os.path.exists(dst) or _file_differs(src, dst):
                if not ctx.dry_run:
                    shutil.copy2(src, dst)
                synced += 1
        if synced > 0:
            ctx.fix(f"Synced {synced} files to .claude/{subdir}/")
        else:
            ctx.ok(f".claude/{subdir}/ up to date")

    # Sync plugins
    for d in [".claude-plugin", "plugins"]:
        src = os.path.join(SKELETON_DIR, d)
        dst = ctx.p(d)
        if os.path.isdir(src):
            if not ctx.dry_run:
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            ctx.fix(f"Synced {d}/ from skeleton")

    # Sync .gitignore
    src_gi = os.path.join(SKELETON_DIR, ".gitignore")
    dst_gi = ctx.p(".gitignore")
    if os.path.exists(src_gi):
        if not os.path.exists(dst_gi) or _file_differs(src_gi, dst_gi):
            if not ctx.dry_run:
                shutil.copy2(src_gi, dst_gi)
            ctx.fix("Synced .gitignore from skeleton")
        else:
            ctx.ok(".gitignore up to date")


# --- Phase 4: CLAUDE.md ---

def phase_claude_md(ctx):
    """Ensure CLAUDE.md imports skeleton and follows Anthropic conventions."""
    print(f"\n=== Phase 4: CLAUDE.MD ===")

    claude_path = ctx.p("CLAUDE.md")
    if not os.path.exists(claude_path):
        ctx.warn("No CLAUDE.md - cannot fix imports. Create one manually.")
        return

    with open(claude_path) as f:
        content = f.read()

    modified = False

    # Check for skeleton import
    if "@q-system" not in content:
        # Find the right insertion point: after the first heading
        lines = content.split("\n")
        insert_idx = 1
        for i, line in enumerate(lines):
            if line.startswith("# "):
                insert_idx = i + 1
                break

        # Insert import after first blank line after heading
        while insert_idx < len(lines) and lines[insert_idx].strip() == "":
            insert_idx += 1

        import_block = "\n## Entrepreneur OS (Skeleton)\n@q-system/q-system/CLAUDE.md\n"
        lines.insert(insert_idx, import_block)
        content = "\n".join(lines)
        modified = True
        ctx.fix("Added @q-system/q-system/CLAUDE.md import to CLAUDE.md")
    else:
        ctx.ok("CLAUDE.md imports skeleton")

    # Check for old rule imports that skeleton now provides
    old_imports = [
        "@.claude/rules/security.md",
        "@.claude/rules/coding-standards.md",
        "@.claude/rules/content-output.md",
        "@.claude/rules/token-discipline.md",
    ]
    for imp in old_imports:
        if imp in content:
            content = content.replace(imp + "\n", "")
            content = content.replace(imp, "")
            modified = True
            ctx.fix(f"Removed redundant import {imp} (now in skeleton)")

    if modified and not ctx.dry_run:
        with open(claude_path, "w") as f:
            f.write(content)


# --- Phase 5: CODE ---

def phase_code(ctx, code_files):
    """Apply coding standards to existing code files."""
    print(f"\n=== Phase 5: CODE STANDARDS ===")

    # Bash: check set -euo pipefail
    for f in code_files.get("sh", []):
        with open(f) as fh:
            content = fh.read()
        lines = content.split("\n")
        has_shebang = lines[0].startswith("#!") if lines else False
        has_strict = BASH_STRICT in content

        if not has_strict:
            ctx.warn(f"Bash script missing 'set -euo pipefail': {os.path.relpath(f, ctx.path)}")
            if not ctx.dry_run:
                if has_shebang:
                    lines.insert(1, BASH_STRICT)
                else:
                    lines.insert(0, BASH_SHEBANG)
                    lines.insert(1, BASH_STRICT)
                with open(f, "w") as fh:
                    fh.write("\n".join(lines))
                ctx.fix(f"Added 'set -euo pipefail' to {os.path.relpath(f, ctx.path)}")
        else:
            ctx.ok(f"Bash compliant: {os.path.relpath(f, ctx.path)}")

    # Python: check __main__ guard and import grouping
    for f in code_files.get("py", []):
        rel = os.path.relpath(f, ctx.path)
        with open(f) as fh:
            content = fh.read()

        # Skip tiny files
        if len(content) < 100:
            continue

        # Check for main guard (only for scripts, not modules)
        if "def main" in content and PYTHON_MAIN_GUARD not in content:
            ctx.warn(f"Python missing __main__ guard: {rel}")
        else:
            ctx.ok(f"Python compliant: {rel}")

    # JavaScript: check for var usage
    for f in code_files.get("js", []):
        rel = os.path.relpath(f, ctx.path)
        with open(f) as fh:
            content = fh.read()

        # Check for var (should be const/let)
        var_matches = re.findall(r"\bvar\s+\w+", content)
        if var_matches:
            ctx.warn(f"JS uses 'var' ({len(var_matches)} instances): {rel}")
        else:
            ctx.ok(f"JS compliant: {rel}")

    # Rules files: check frontmatter format per Anthropic docs
    rules_dir = ctx.p(".claude", "rules")
    if os.path.isdir(rules_dir):
        for f in os.listdir(rules_dir):
            if not f.endswith(".md"):
                continue
            with open(os.path.join(rules_dir, f)) as fh:
                content = fh.read()
            # Rules with paths: frontmatter must have 'paths:' key
            # Rules without paths: frontmatter optional
            if content.startswith("---"):
                match = RULES_FRONTMATTER_PATTERN.match(content)
                if match:
                    ctx.ok(f"Rule {f}: valid frontmatter")
                else:
                    ctx.warn(f"Rule {f}: malformed frontmatter")
            # No frontmatter = unconditional rule (valid per Anthropic docs)


# --- Phase 6: VERIFY ---

def phase_verify(ctx):
    """Run compliance verification."""
    print(f"\n=== Phase 6: VERIFY ===")

    checks = [
        (".git", "Git repo"),
        ("q-system", "Skeleton subtree"),
        (".claude/settings.json", "Settings"),
        (".claude/rules", "Rules dir"),
        (".claude/agents", "Agents dir"),
        (".claude/output-styles", "Output styles dir"),
        ("plugins", "Plugins"),
        (".githooks", "Git hooks"),
        (".gitignore", "Gitignore"),
        ("CLAUDE.md", "CLAUDE.md"),
    ]

    for check_path, label in checks:
        if ctx.exists(check_path):
            ctx.ok(f"{label}: present")
        else:
            ctx.fail(f"{label}: MISSING")

    # Verify CLAUDE.md imports skeleton
    if ctx.exists("CLAUDE.md"):
        with open(ctx.p("CLAUDE.md")) as f:
            if "@q-system" in f.read():
                ctx.ok("CLAUDE.md: skeleton import present")
            else:
                ctx.fail("CLAUDE.md: skeleton import MISSING")

    # Verify settings.json is valid and has required keys
    if ctx.exists(".claude", "settings.json"):
        try:
            with open(ctx.p(".claude", "settings.json")) as f:
                settings = json.load(f)
            for key in ["permissions", "hooks", "outputStyle", "enabledPlugins"]:
                if key in settings:
                    ctx.ok(f"settings.json: '{key}' present")
                else:
                    ctx.fail(f"settings.json: '{key}' MISSING")
        except json.JSONDecodeError:
            ctx.fail("settings.json: invalid JSON")

    # Verify rules count matches skeleton
    skel_rules = len([f for f in os.listdir(os.path.join(SKELETON_DIR, ".claude", "rules"))
                       if f.endswith(".md")])
    inst_rules = 0
    if ctx.is_dir(".claude", "rules"):
        inst_rules = len([f for f in os.listdir(ctx.p(".claude", "rules"))
                          if f.endswith(".md")])
    if inst_rules >= skel_rules:
        ctx.ok(f"Rules: {inst_rules} files (skeleton has {skel_rules})")
    else:
        ctx.warn(f"Rules: {inst_rules} files (skeleton has {skel_rules}, some missing)")


# --- Helpers ---

def _file_differs(a, b):
    """Check if two files differ."""
    try:
        with open(a) as fa, open(b) as fb:
            return fa.read() != fb.read()
    except Exception:
        return True


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Migrate instance to kipi compliance")
    parser.add_argument("instance_path", help="Path to the instance to migrate")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no changes")
    parser.add_argument("--verbose", action="store_true", help="Show all checks, not just fixes")
    args = parser.parse_args()

    if not os.path.isdir(args.instance_path):
        print(f"ERROR: {args.instance_path} is not a directory")
        sys.exit(1)

    ctx = MigrationContext(args.instance_path, args.dry_run, args.verbose)

    print(f"{'DRY RUN: ' if ctx.dry_run else ''}Migrating {ctx.instance_name}")
    print(f"Skeleton: {SKELETON_DIR}")

    code_files = phase_audit(ctx)
    phase_struct(ctx)
    phase_config(ctx)
    phase_claude_md(ctx)
    phase_code(ctx, code_files)
    phase_verify(ctx)

    # Summary
    print(f"\n{'=' * 40}")
    print(f"  MIGRATION SUMMARY ({ctx.instance_name})")
    print(f"{'=' * 40}")
    print(f"  \033[0;32mPASS: {len(ctx.passes)}\033[0m")
    print(f"  \033[0;36mFIX:  {len(ctx.fixes)}\033[0m")
    print(f"  \033[0;33mWARN: {len(ctx.warnings)}\033[0m")
    if ctx.dry_run:
        print(f"\n  DRY RUN - no changes made. Run without --dry-run to apply.")
    elif ctx.fixes:
        print(f"\n  {len(ctx.fixes)} fixes applied. Commit with:")
        print(f"  cd {ctx.path} && git add -A && git commit -m 'chore: kipi migrate - full compliance'")

    return 0 if not ctx.warnings else 1


if __name__ == "__main__":
    sys.exit(main())
