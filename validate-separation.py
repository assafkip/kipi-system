#!/usr/bin/env python3
"""Kipi System Separation - Validation Harness.

Usage: python3 validate-separation.py <phase> [--verbose]
Runs all checks up to and including the specified phase.
Exit code 0 = all checks pass. Non-zero = failure.
"""

import json
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(SCRIPT_DIR, "instance-registry.json")

# ANSI colors
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"

pass_count = 0
fail_count = 0
warn_count = 0
errors = []


def check(description, result):
    global pass_count, fail_count
    if result:
        print(f"  {GREEN}PASS{NC} {description}")
        pass_count += 1
    else:
        print(f"  {RED}FAIL{NC} {description}")
        fail_count += 1
        errors.append(f"  - {description}")


def warn(description):
    global warn_count
    print(f"  {YELLOW}WARN{NC} {description}")
    warn_count += 1


def phase_header(num, title):
    print()
    print(f"{BLUE}=== Phase {num}: {title} ==={NC}")


def file_exists(path):
    return os.path.isfile(path)


def dir_exists(path):
    return os.path.isdir(path)


def count_files(directory, pattern="*.md", exclude_prefixes=("_", "step-")):
    """Count files matching pattern, excluding files starting with given prefixes."""
    count = 0
    if not os.path.isdir(directory):
        return 0
    for f in os.listdir(directory):
        if not f.endswith(".md"):
            continue
        if any(f.startswith(p) for p in exclude_prefixes):
            continue
        count += 1
    return count


def grep_count(pattern, path, recursive=False):
    """Count files matching a grep pattern. Returns number of matching files."""
    try:
        cmd = ["grep", "-ril" if recursive else "-il", pattern, path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return len([l for l in result.stdout.strip().split("\n") if l])
        return 0
    except (subprocess.TimeoutExpired, Exception):
        return 0


def grep_count_multi(patterns, path):
    """Count files matching any of several patterns recursively."""
    pat = "|".join(patterns)
    return grep_count(pat, path, recursive=True)


def file_contains(filepath, pattern):
    """Check if a file contains a pattern."""
    try:
        with open(filepath) as f:
            return bool(re.search(pattern, f.read()))
    except (FileNotFoundError, Exception):
        return False


def python_parses(filepath):
    """Check if a Python file parses without syntax errors."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open('{filepath}').read())"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        return False


def load_registry():
    try:
        with open(REGISTRY) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"instances": []}


# ---------- PHASES ----------

def phase_0():
    phase_header(0, "Pre-execution checks")

    check("instance-registry.json exists", file_exists(REGISTRY))
    check("q-system/ directory exists in skeleton", dir_exists(os.path.join(SCRIPT_DIR, "q-system")))

    if os.getenv('CI') == 'true':
        print(f"  {YELLOW}SKIP{NC} Instance path checks (CI environment)")
    else:
        registry = load_registry()
        for instance in registry.get("instances", []):
            path = instance.get("path", "")
            name = os.path.basename(path)
            check(f"Instance path exists: {name}", dir_exists(path))


def phase_1():
    phase_header(1, "Skeleton integrity")

    agents_dir = os.path.join(SCRIPT_DIR, "q-system", ".q-system", "agent-pipeline", "agents")
    scripts_dir = os.path.join(SCRIPT_DIR, "q-system", ".q-system")

    # --- GATE 1.1: Agent files ---
    print()
    print("  --- Gate 1.1: Agent files ---")

    agent_count = count_files(agents_dir)
    check(f"Agent count >= 30 (found: {agent_count})", agent_count >= 30)

    # Frontmatter on all numbered agents
    missing_frontmatter = 0
    if os.path.isdir(agents_dir):
        for f in sorted(os.listdir(agents_dir)):
            if not f[0].isdigit() or not f.endswith(".md"):
                continue
            filepath = os.path.join(agents_dir, f)
            with open(filepath) as fh:
                first_line = fh.readline().strip()
            if first_line != "---":
                missing_frontmatter += 1
                if verbose:
                    warn(f"Missing frontmatter: {f}")
    check(f"All numbered agents have YAML frontmatter ({missing_frontmatter} missing)", missing_frontmatter == 0)

    # Reads sections
    missing_rw = 0
    if os.path.isdir(agents_dir):
        for f in sorted(os.listdir(agents_dir)):
            if not f[0].isdigit() or not f.endswith(".md"):
                continue
            filepath = os.path.join(agents_dir, f)
            if not file_contains(filepath, r"## Reads?"):
                missing_rw += 1
                if verbose:
                    warn(f"Missing Reads section: {f}")
    check(f"All numbered agents have Reads section ({missing_rw} missing)", missing_rw == 0)

    # No KTLYST-specific terms
    ktlyst_hits = grep_count_multi(
        [r"KTLYST", r"ktlyst", r"q-ktlyst", r"re-breach", r"re\.breach", r"threat.intel.*team", r"CNS.*nervous"],
        agents_dir,
    )
    check(f"No KTLYST-specific terms in agent files ({ktlyst_hits} files)", ktlyst_hits == 0)

    # No hardcoded paths
    hardcoded = grep_count_multi([r"/Users/assafkip", r"q-ktlyst/"], agents_dir)
    check(f"No hardcoded paths in agent files ({hardcoded} files)", hardcoded == 0)

    # Key config files
    check("step-orchestrator.md exists", file_exists(os.path.join(agents_dir, "step-orchestrator.md")))
    check(
        "_cadence-config exists (.yaml or .md)",
        file_exists(os.path.join(agents_dir, "_cadence-config.yaml")) or file_exists(os.path.join(agents_dir, "_cadence-config.md")),
    )
    check("_auto-fail-checklist.md exists", file_exists(os.path.join(agents_dir, "_auto-fail-checklist.md")))

    # --- GATE 1.2: Scripts ---
    print()
    print("  --- Gate 1.2: Scripts ---")

    for script in ["audit-morning.py", "verify-schedule.py", "token-guard.py"]:
        check(f"{script} exists", file_exists(os.path.join(scripts_dir, script)))

    # Check for ported scripts (may be in scripts/ subdir)
    scan_draft = file_exists(os.path.join(scripts_dir, "scripts", "scan-draft.py")) or file_exists(os.path.join(scripts_dir, "scan-draft.py"))
    check("scan-draft.py exists (anti-AI scanner)", scan_draft)

    check("verify-bus.py exists", file_exists(os.path.join(scripts_dir, "verify-bus.py")) or file_exists(os.path.join(scripts_dir, "scripts", "verify-bus.py")))
    check("verify-orchestrator.py exists", file_exists(os.path.join(scripts_dir, "verify-orchestrator.py")) or file_exists(os.path.join(scripts_dir, "scripts", "verify-orchestrator.py")))

    build_sched = os.path.join(SCRIPT_DIR, "q-system", "marketing", "templates", "build-schedule.py")
    check("build-schedule.py exists and is non-empty", file_exists(build_sched) and os.path.getsize(build_sched) > 0)

    # No KTLYST in scripts
    script_hits = 0
    for root, dirs, files in os.walk(scripts_dir):
        for f in files:
            if f.endswith(".py") or f.endswith(".sh"):
                filepath = os.path.join(root, f)
                if file_contains(filepath, r"KTLYST|ktlyst|q-ktlyst"):
                    script_hits += 1
    check(f"No KTLYST references in scripts ({script_hits} files)", script_hits == 0)

    # --- GATE 1.3: Canonical templates ---
    print()
    print("  --- Gate 1.3: Canonical templates ---")

    canonical = os.path.join(SCRIPT_DIR, "q-system", "canonical")
    for tmpl in ["discovery.md", "objections.md", "talk-tracks.md", "decisions.md",
                 "engagement-playbook.md", "lead-lifecycle-rules.md", "market-intelligence.md",
                 "pricing-framework.md", "verticals.md"]:
        check(f"canonical/{tmpl} exists", file_exists(os.path.join(canonical, tmpl)))

    my_project = os.path.join(SCRIPT_DIR, "q-system", "my-project")
    check("my-project/founder-profile.md exists", file_exists(os.path.join(my_project, "founder-profile.md")))

    profile_path = os.path.join(my_project, "founder-profile.md")
    check("founder-profile.md contains {{SETUP_NEEDED}}", file_contains(profile_path, r"SETUP_NEEDED"))

    canonical_ktlyst = grep_count_multi([r"KTLYST", r"ktlyst", r"Assaf", r"CISO.*pain", r"re-breach"], canonical)
    check(f"No KTLYST content in canonical templates ({canonical_ktlyst} files)", canonical_ktlyst == 0)

    # --- GATE 1.4: Voice skill framework ---
    print()
    print("  --- Gate 1.4: Voice skill ---")

    voice = os.path.join(SCRIPT_DIR, "plugins", "kipi-core", "skills", "founder-voice")
    check("founder-voice SKILL.md exists", file_exists(os.path.join(voice, "SKILL.md")))
    check("voice-dna.md template exists", file_exists(os.path.join(voice, "references", "voice-dna.md")))
    check("writing-samples.md template exists", file_exists(os.path.join(voice, "references", "writing-samples.md")))

    voice_ktlyst = grep_count_multi(
        [r"Assaf", r"KTLYST", r"threat.intel.*Google", r"threat.intel.*Meta"],
        voice,
    )
    check(f"No Assaf-specific content in voice framework ({voice_ktlyst} files)", voice_ktlyst == 0)

    research = os.path.join(SCRIPT_DIR, "plugins", "kipi-core", "skills", "research-mode")
    check("research-mode SKILL.md exists", file_exists(os.path.join(research, "SKILL.md")))
    check("research-mode command exists", file_exists(os.path.join(research, "commands", "q-research.md")))

    # --- GATE 1.5: CLAUDE.md ---
    print()
    print("  --- Gate 1.5: CLAUDE.md ---")

    check("Root CLAUDE.md exists", file_exists(os.path.join(SCRIPT_DIR, "CLAUDE.md")))
    check("q-system/CLAUDE.md exists", file_exists(os.path.join(SCRIPT_DIR, "q-system", "CLAUDE.md")))

    q_claude = os.path.join(SCRIPT_DIR, "q-system", "CLAUDE.md")
    try:
        with open(q_claude) as f:
            content = f.read()
        claude_ktlyst = len(re.findall(r"KTLYST|ktlyst|Assaf|re-breach|CISO.*pain", content, re.IGNORECASE))
    except FileNotFoundError:
        claude_ktlyst = 0
    check(f"No KTLYST references in q-system/CLAUDE.md ({claude_ktlyst} hits)", claude_ktlyst == 0)

    # --- GATE 1.6: build-schedule.py ---
    print()
    print("  --- Gate 1.6: build-schedule.py ---")

    if file_exists(build_sched):
        check("build-schedule.py has verification gate", file_contains(build_sched, r"verify.schedule"))

    # --- Full skeleton sweep ---
    print()
    print("  --- Full skeleton sweep ---")

    q_system_dir = os.path.join(SCRIPT_DIR, "q-system")
    full_sweep = 0
    exclude_files = {"PHASE-0-AUDIT", "EXECUTION-PLAN", "validate-separation", "instance-registry"}
    for root, dirs, files in os.walk(q_system_dir):
        for f in files:
            if any(ex in f for ex in exclude_files):
                continue
            filepath = os.path.join(root, f)
            if file_contains(filepath, r"KTLYST|ktlyst|q-ktlyst|/Users/assafkip"):
                full_sweep += 1
    check(f"Full skeleton sweep: zero KTLYST/hardcoded refs ({full_sweep} files)", full_sweep == 0)


def phase_2():
    phase_header(2, "KTLYST_strategy subtree")

    ktlyst = "/Users/assafkip/Desktop/KTLYST_strategy"

    if os.getenv('CI') == 'true' or not dir_exists(ktlyst):
        print(f"  {YELLOW}SKIP{NC} KTLYST_strategy checks (not available)")
        return

    check("KTLYST has q-system/ directory (subtree)", dir_exists(os.path.join(ktlyst, "q-system")))
    check("KTLYST has q-ktlyst/ directory (instance content)", dir_exists(os.path.join(ktlyst, "q-ktlyst")))

    # Try multiple path layouts: archive overlay (flat), subtree (nested), legacy
    k_agents_paths = [
        os.path.join(ktlyst, "q-system", ".q-system", "agent-pipeline", "agents"),
        os.path.join(ktlyst, "q-system", "q-system", ".q-system", "agent-pipeline", "agents"),
        os.path.join(ktlyst, "q-system", "q-system", "agent-pipeline", "agents"),
    ]
    k_agents_dir = next((p for p in k_agents_paths if dir_exists(p)), None)
    if k_agents_dir and dir_exists(k_agents_dir):
        k_count = count_files(k_agents_dir)
        check(f"KTLYST q-system/ subtree has agents ({k_count})", k_count >= 30)
    else:
        check("KTLYST q-system/ subtree agent directory exists", False)

    check(
        "KTLYST instance content in q-ktlyst/ (canonical or my-project)",
        dir_exists(os.path.join(ktlyst, "q-ktlyst", "canonical")) or dir_exists(os.path.join(ktlyst, "q-ktlyst", "my-project")),
    )

    check("KTLYST root CLAUDE.md exists", file_exists(os.path.join(ktlyst, "CLAUDE.md")))

    claude_path = os.path.join(ktlyst, "CLAUDE.md")
    if file_exists(claude_path):
        check("KTLYST CLAUDE.md imports skeleton", file_contains(claude_path, r"@q-system|q-system/CLAUDE\.md"))
        check("KTLYST CLAUDE.md imports instance rules", file_contains(claude_path, r"@q-ktlyst|q-ktlyst/CLAUDE\.md"))

    # No plugin dependency
    plugin_refs = 0
    for cf in [
        os.path.join(ktlyst, "CLAUDE.md"),
        os.path.join(ktlyst, ".claude", "settings.json"),
        os.path.join(ktlyst, ".claude", "settings.local.json"),
        os.path.join(ktlyst, ".mcp.json"),
        os.path.join(ktlyst, "q-ktlyst", ".q-system", "commands.md"),
        os.path.join(ktlyst, "q-ktlyst", ".q-system", "preflight.md"),
    ]:
        if file_exists(cf):
            try:
                with open(cf) as f:
                    plugin_refs += f.read().count("kipi-pipeline-plugin")
            except Exception:
                pass

    if plugin_refs == 0:
        check(f"No kipi-pipeline-plugin references in KTLYST ({plugin_refs})", True)
    else:
        warn(f"kipi-pipeline-plugin references in KTLYST ({plugin_refs}) - clean in Phase 3")

    # Scripts parse (try flat and nested paths)
    k_scripts_paths = [
        os.path.join(ktlyst, "q-system", ".q-system"),
        os.path.join(ktlyst, "q-system", "q-system", ".q-system"),
    ]
    k_scripts = next((p for p in k_scripts_paths if dir_exists(p)), k_scripts_paths[0])
    audit_path = os.path.join(k_scripts, "audit-morning.py")
    if file_exists(audit_path):
        check("Subtree audit-morning.py parses without errors", python_parses(audit_path))

    scan_path = os.path.join(k_scripts, "scripts", "scan-draft.py")
    if file_exists(scan_path):
        check("Subtree scan-draft.py parses without errors", python_parses(scan_path))


def phase_3():
    phase_header(3, "Plugin elimination")

    if os.getenv('CI') == 'true':
        print(f"  {YELLOW}SKIP{NC} Plugin elimination checks (CI environment)")
        return

    check("kipi-pipeline-plugin directory removed", not dir_exists("/Users/assafkip/Desktop/kipi-pipeline-plugin"))
    check("q-founder-os directory removed", not dir_exists("/Users/assafkip/Desktop/q-founder-os"))

    # Global config references
    global_plugin = 0
    home = os.path.expanduser("~")
    for cf in [
        os.path.join(home, ".claude", "settings.json"),
        os.path.join(home, ".claude", "settings.local.json"),
        os.path.join(home, ".claude", "plugins", "known_marketplaces.json"),
    ]:
        if file_exists(cf):
            try:
                with open(cf) as f:
                    global_plugin += f.read().count("kipi-pipeline-plugin")
            except Exception:
                pass
    check(f"No plugin references in Claude Code config ({global_plugin})", global_plugin == 0)

    check("Plugin cache directory removed", not dir_exists(os.path.join(home, ".claude", "plugins", "cache", "kipi-local")))


def phase_4():
    phase_header(4, "All instances")

    if os.getenv('CI') == 'true':
        print(f"  {YELLOW}SKIP{NC} Instance checks (CI environment)")
        return

    registry = load_registry()
    for instance in registry.get("instances", []):
        name = instance.get("name", "unknown")
        path = instance.get("path", "")
        prefix = instance.get("subtree_prefix", "q-system")
        itype = instance.get("type", "subtree")

        print()
        print(f"  --- {name} ({itype}) ---")

        check(f"{name}: {prefix}/ directory exists", dir_exists(os.path.join(path, prefix)))

        if itype == "direct-clone":
            agent_path = os.path.join(path, prefix, ".q-system", "agent-pipeline", "agents")
        else:
            agent_path = os.path.join(path, prefix, "q-system", ".q-system", "agent-pipeline", "agents")
            if not dir_exists(agent_path):
                agent_path = os.path.join(path, prefix, "q-system", "agent-pipeline", "agents")
            if not dir_exists(agent_path):
                agent_path = os.path.join(path, prefix, ".q-system", "agent-pipeline", "agents")

        if instance.get("skip_agent_check"):
            check(f"{name}: has agents (skipped - {instance.get('note', 'no pipeline')})", True)
        elif dir_exists(agent_path):
            i_count = count_files(agent_path)
            threshold = 15 if itype == "direct-clone" else 30
            label = f"{i_count}, direct-clone - relaxed threshold" if itype == "direct-clone" else str(i_count)
            check(f"{name}: has agents ({label})", i_count >= threshold)
        else:
            check(f"{name}: agent directory exists at expected path", False)

        check(f"{name}: root CLAUDE.md exists", file_exists(os.path.join(path, "CLAUDE.md")))

        claude_path = os.path.join(path, "CLAUDE.md")
        if file_exists(claude_path):
            check(f"{name}: CLAUDE.md imports skeleton", file_contains(claude_path, r"@q-system"))


def phase_5():
    phase_header(5, "Propagation and documentation")

    for script in ["kipi-update.sh", "kipi-new-instance.sh", "kipi-push-upstream.sh"]:
        path = os.path.join(SCRIPT_DIR, script)
        check(f"{script} exists and is executable", file_exists(path) and os.access(path, os.X_OK))

    for doc in ["SETUP.md", "UPDATE.md", "CONTRIBUTE.md", "ARCHITECTURE.md"]:
        check(f"Documentation: {doc} exists", file_exists(os.path.join(SCRIPT_DIR, doc)))

    # No KTLYST in docs
    doc_ktlyst = 0
    for doc in ["SETUP.md", "UPDATE.md", "CONTRIBUTE.md", "ARCHITECTURE.md"]:
        if file_contains(os.path.join(SCRIPT_DIR, doc), r"KTLYST|ktlyst"):
            doc_ktlyst += 1
    check(f"No KTLYST references in documentation ({doc_ktlyst})", doc_ktlyst == 0)


def main():
    global verbose

    phase = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    verbose = "--verbose" in sys.argv

    phases = [phase_0, phase_1, phase_2, phase_3, phase_4, phase_5]
    for i, func in enumerate(phases):
        if phase >= i:
            func()

    # Summary
    print()
    print(f"{BLUE}=============================={NC}")
    print(f"{BLUE}  VALIDATION SUMMARY (Phase {phase}){NC}")
    print(f"{BLUE}=============================={NC}")
    print(f"  {GREEN}PASS: {pass_count}{NC}")
    print(f"  {RED}FAIL: {fail_count}{NC}")
    print(f"  {YELLOW}WARN: {warn_count}{NC}")

    if fail_count > 0:
        print()
        print(f"{RED}FAILURES:{NC}")
        for e in errors:
            print(e)
        print()
        print(f"{RED}GATE FAILED. Do not proceed to Phase {phase + 1}.{NC}")
        sys.exit(1)
    else:
        print()
        print(f"{GREEN}ALL CHECKS PASSED. Phase {phase} gate is GREEN.{NC}")
        sys.exit(0)


if __name__ == "__main__":
    main()
