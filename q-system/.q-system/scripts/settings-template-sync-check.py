#!/usr/bin/env python3
"""settings-template-sync-check: catch enforcement hooks drifted between the two
settings files (both directions).

Scar (2026-06-30): `kipi update` rebuilds each instance's settings.json from
settings-template.json ONLY. A hook wired in the skeleton's runtime
.claude/settings.json but absent from settings-template.json ships its SCRIPT to
the fleet (q-system/ rsyncs from git HEAD) while the SWITCH never propagates --
it ran dead in 18/18 instances (lessons-validator, wiring-check, memory-confidence
+ 5 lints). The inverse also drifts: a hook in the template but not in the
skeleton's settings.json runs dead in the skeleton's own runtime (scar sp-aa7e4995:
memory-freshness-check + prompt-only-enforcement-guard). This check fails on either
direction for any hook invoking a PROPAGATED script.

Modes:
- CLI / preflight (`--check`, or stdin empty): compare the repo's two settings
  files; exit 2 on divergence. Used as a `kipi update` preflight and manually.
- PostToolUse hook (hook JSON on stdin): self-scope on edits to settings.json or
  settings-template.json; same comparison; exit 2 blocks the edit.

No-op (exit 0) when settings-template.json is absent (i.e. inside an instance --
instances do not propagate further, so there is nothing to strand). stdlib only.
"""
import json
import os
import re
import sys

# Scripts that legitimately live ONLY in the skeleton runtime settings.json.
# This check itself is meaningless inside an instance (no template there), so it
# is skeleton-only by design -- without this entry the check would flag itself.
SKELETON_ONLY = {
    "settings-template-sync-check.py",
}

# Scripts that legitimately live ONLY in settings-template.json (fleet) and not in
# the skeleton's own runtime settings.json. Empty by default: a hook in the
# template but not the skeleton runs dead in the skeleton itself (scar sp-aa7e4995:
# memory-freshness-check + prompt-only-enforcement-guard were live in the fleet but
# dead in the skeleton). Add here only when an asymmetry is deliberate.
# Hooks that intentionally run ONLY on instances (the skeleton self-detects and no-ops),
# so they belong in settings-template.json but NOT in the skeleton's own .claude/settings.json.
FLEET_ONLY = {"instance-automation-guard.py"}

# A hook "propagates" when it invokes a script under a directory kipi update
# rsyncs into instances. Such a hook's switch MUST live in the template too.
SCRIPT_RE = re.compile(
    r"q-system/(?:\.q-system/scripts|hooks)/([A-Za-z0-9_\-]+\.(?:py|sh))"
)


def scripts_in_hooks(settings):
    """Set of propagated-script basenames referenced by any hook command."""
    found = set()
    for _event, groups in settings.get("hooks", {}).items():
        for grp in groups:
            for h in grp.get("hooks", []):
                for name in SCRIPT_RE.findall(h.get("command", "")):
                    found.add(name)
    return found


def find_divergence(repo_root):
    """Both drift directions. Returns (stranded, skeleton_gap) or None for no-op.

    stranded     -- in settings.json, not template: ships dead to the fleet.
    skeleton_gap -- in template, not settings.json: runs dead in the skeleton.
    """
    sj = os.path.join(repo_root, ".claude", "settings.json")
    st = os.path.join(repo_root, "settings-template.json")
    if not os.path.isfile(st) or not os.path.isfile(sj):
        return None
    try:
        runtime = scripts_in_hooks(json.load(open(sj)))
        template = scripts_in_hooks(json.load(open(st)))
    except (json.JSONDecodeError, OSError):
        return None
    stranded = sorted((runtime - template) - SKELETON_ONLY)
    skeleton_gap = sorted((template - runtime) - FLEET_ONLY)
    return (stranded, skeleton_gap)


def repo_root_from(path):
    d = os.path.dirname(os.path.abspath(path))
    while d != "/":
        if os.path.isfile(os.path.join(d, "settings-template.json")):
            return d
        d = os.path.dirname(d)
    return None


def main():
    hook_data = None
    if "--check" not in sys.argv:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        if raw.strip():
            try:
                hook_data = json.loads(raw)
            except json.JSONDecodeError:
                hook_data = None

    if hook_data is not None:
        fp = (hook_data.get("tool_input") or {}).get("file_path", "")
        norm = fp.replace("\\", "/")
        if not (norm.endswith("/.claude/settings.json") or norm.endswith("/settings-template.json")):
            sys.exit(0)
        root = os.environ.get("CLAUDE_PROJECT_DIR") or repo_root_from(fp) or os.getcwd()
    else:
        root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    result = find_divergence(root)
    if not result:
        sys.exit(0)
    stranded, skeleton_gap = result
    if not stranded and not skeleton_gap:
        sys.exit(0)

    if stranded:
        sys.stderr.write(
            "settings-template-sync-check: hook(s) wired in .claude/settings.json "
            "but MISSING from settings-template.json -> they ship DEAD to the fleet "
            "(kipi update rebuilds instance settings from the template only):\n"
        )
        for s in stranded:
            sys.stderr.write(f"  - {s}\n")
        sys.stderr.write(
            "Fix: add to settings-template.json, or add to SKELETON_ONLY if "
            "intentionally skeleton-only.\n"
        )
    if skeleton_gap:
        sys.stderr.write(
            "settings-template-sync-check: hook(s) in settings-template.json but "
            "MISSING from .claude/settings.json -> they run DEAD in the skeleton's "
            "own runtime (the fleet has them, the skeleton does not):\n"
        )
        for s in skeleton_gap:
            sys.stderr.write(f"  - {s}\n")
        sys.stderr.write(
            "Fix: add to .claude/settings.json, or add to FLEET_ONLY if "
            "intentionally fleet-only.\n"
        )
    sys.exit(2)


if __name__ == "__main__":
    main()
