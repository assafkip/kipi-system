#!/usr/bin/env python3
"""Standalone, app-agnostic skill->hook orphan audit (pairs with skill-hook-pairing rule).

This is the fleet-portable twin of investigations/tests/test_skill_hooks_wired.py. That
ratchet is pytest-bound and lives in the investigations app; this CLI runs the SAME five
invariants anywhere -- so any instance (incl. ones with no pytest suite) and the skeleton
itself can catch the orphan bug: a deterministic lint/gate script authored but never WIRED
into a hook config, so it never fires.

Manifest-gated by design: an instance with no .claude/skill-hook-manifest.json is treated
as "not onboarded" -> prints a notice and exits 0. It only ENFORCES where a manifest exists.
That keeps it safe to ship fleet-wide via the kipi-core plugin: dormant until opted in.

Root discovery: argv[1], else $CLAUDE_PROJECT_DIR, else the repo this script is installed in
(plugins/kipi-core/scripts/ -> repo root is parents[3]).

Exit codes: 0 = pass or not-onboarded; 1 = a real violation (named on stderr).
Run: python3 plugins/kipi-core/scripts/skill-hook-audit.py [root]
"""
import json
import os
import re
import sys
from pathlib import Path

_SCRIPT_RE = re.compile(r"[A-Za-z0-9_-]+\.(?:py|sh)")
# Where skill SKILL.md files live across kipi instance shapes.
_SKILL_GLOBS = ("plugins/*/skills/*/SKILL.md", "q-investigate/skills/*/SKILL.md")
# Roots to search for "does this hook script exist on disk".
_SEARCH_ROOTS = ("q-system", "plugins", "investigations", ".claude")
_VALID_STATUS = {"wired", "debt", "in-script", "interpretive"}


def resolve_root() -> Path:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return Path(sys.argv[1]).resolve()
    env = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[3]


def skills_on_disk(root: Path) -> set:
    out = set()
    for pat in _SKILL_GLOBS:
        for p in root.glob(pat):
            if "/dist/" not in str(p):
                out.add(p.parent.name)
    return out


def wired_config_files(root: Path) -> list:
    """Configs consulted as proof that a hook is wired.

    settings.local.json is deliberately absent (ASK-965, finding-13). It used to
    be read here, and that made one developer's untracked machine-local override
    able to report a skeleton hook as wired -- the exact orphan bug this audit
    exists to catch, walking past it. apply_claude_changes.py lines 512-532
    REFUSES that same file rather than merely skipping it, because "a change here
    leaves no reviewable trace". Pinned by test_skill_hook_audit_local.py.

    READ THE EXCLUSION NARROWLY -- it is one filename, not a tracked-tree
    property (codex review of a6504c49, major). This function does NOT consult
    git. An untracked `plugins/*/hooks/hooks.json`, or an untracked hook script
    that `script_exists` finds, still counts as wiring here, so the same
    local-only false green survives by a different door. settings.local.json is
    excluded because it is the one config the sanctioned write path names and
    refuses -- a known, enumerated case -- not because anything here verifies
    that a file ships. Making the general claim true means a git-tracking check
    with a defined answer for non-git trees, which is a wider change than the
    finding that motivated this one; captured rather than half-built.
    """
    files = [root / ".claude" / "settings.json"]
    files += [p for p in root.glob("plugins/*/hooks/hooks.json") if "/dist/" not in str(p)]
    return [f for f in files if f.exists()]


def wired_script_basenames(root: Path) -> set:
    refs = set()
    for f in wired_config_files(root):
        refs |= set(_SCRIPT_RE.findall(f.read_text()))
    return refs


def script_exists(root: Path, name: str) -> bool:
    for sub in _SEARCH_ROOTS:
        base = root / sub
        if not base.exists():
            continue
        for p in base.rglob(name):
            s = str(p)
            if "/.venv/" in s or "/dist/" in s or "__pycache__" in s:
                continue
            return True
    return False


def check_every_skill_triaged(manifest: dict, root: Path) -> list:
    declared = set(manifest["skills"])
    on_disk = skills_on_disk(root)
    errors = []
    untriaged = on_disk - declared
    if untriaged:
        errors.append(
            f"skills on disk but NOT triaged in manifest: {sorted(untriaged)} "
            f"(triage each: wired / debt / in-script / interpretive)")
    stale = declared - on_disk
    if stale:
        errors.append(f"manifest names skills that no longer exist on disk: {sorted(stale)}")
    return errors


def check_wired_claims_real(manifest: dict, root: Path) -> list:
    wired_refs = wired_script_basenames(root)
    errors = []
    for skill, spec in manifest["skills"].items():
        if spec["status"] != "wired":
            continue
        for hook in spec.get("hooks", []):
            if not script_exists(root, hook):
                errors.append(f"{skill}: wired hook {hook} does not exist on disk")
            elif hook not in wired_refs:
                errors.append(
                    f"{skill}: hook {hook} claimed 'wired' but referenced in NO config "
                    f"-- it's an ORPHAN, it never fires")
    return errors


def check_debt_only_shrinks(manifest: dict) -> list:
    baseline = set(manifest["debt_baseline"])
    current = {s for s, v in manifest["skills"].items() if v["status"] == "debt"}
    errors = []
    grew = current - baseline
    if grew:
        errors.append(
            f"new ungated skill(s) added without acknowledgement: {sorted(grew)} "
            f"(wire a hook or add to debt_baseline deliberately)")
    stale = baseline - current
    if stale:
        errors.append(f"debt_baseline lists skills no longer 'debt': {sorted(stale)} (remove them)")
    return errors


def check_debt_hooks_not_wired(manifest: dict, root: Path) -> list:
    wired_refs = wired_script_basenames(root)
    errors = []
    for skill, spec in manifest["skills"].items():
        if spec["status"] != "debt":
            continue
        wired_now = [h for h in spec.get("hooks", []) if h in wired_refs]
        if wired_now:
            errors.append(
                f"{skill} is 'debt' but its hook(s) {wired_now} ARE wired -- flip to 'wired' "
                f"and drop from debt_baseline")
    return errors


def check_manifest_valid(manifest: dict) -> list:
    errors = []
    for skill, spec in manifest["skills"].items():
        if spec["status"] not in _VALID_STATUS:
            errors.append(f"{skill}: bad status {spec['status']!r}")
    return errors


def run_audit(root: Path) -> int:
    manifest_path = root / ".claude" / "skill-hook-manifest.json"
    if not manifest_path.exists():
        print(f"[skill-hook-audit] no manifest at {manifest_path} -- not onboarded, skipping.")
        return 0
    manifest = json.loads(manifest_path.read_text())
    errors = []
    errors += check_manifest_valid(manifest)
    errors += check_every_skill_triaged(manifest, root)
    errors += check_wired_claims_real(manifest, root)
    errors += check_debt_only_shrinks(manifest)
    errors += check_debt_hooks_not_wired(manifest, root)
    if errors:
        print(f"[skill-hook-audit] FAIL ({len(errors)} issue(s)) at {root}:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    n_skills = len(manifest["skills"])
    print(f"[skill-hook-audit] PASS -- {n_skills} skills triaged, no orphans, debt not growing.")
    return 0


if __name__ == "__main__":
    sys.exit(run_audit(resolve_root()))
