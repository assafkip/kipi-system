#!/usr/bin/env python3
"""settings-template-sync-check: catch enforcement hooks stranded in settings.json.

Scar (2026-06-30): `kipi update` rebuilds each instance's settings.json from
settings-template.json ONLY. A hook wired in the skeleton's runtime
.claude/settings.json but absent from settings-template.json ships its SCRIPT to
the fleet (q-system/ rsyncs from git HEAD) while the SWITCH never propagates --
it ran dead in 18/18 instances (lessons-validator, wiring-check, memory-confidence
+ 5 lints). This check fails when a hook invoking a PROPAGATED script is present
in .claude/settings.json but missing from settings-template.json.

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
    """Sorted stranded basenames (in settings.json, not template). None = no-op."""
    sj = os.path.join(repo_root, ".claude", "settings.json")
    st = os.path.join(repo_root, "settings-template.json")
    if not os.path.isfile(st) or not os.path.isfile(sj):
        return None
    try:
        runtime = scripts_in_hooks(json.load(open(sj)))
        template = scripts_in_hooks(json.load(open(st)))
    except (json.JSONDecodeError, OSError):
        return None
    return sorted((runtime - template) - SKELETON_ONLY)


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

    stranded = find_divergence(root)
    if not stranded:
        sys.exit(0)

    sys.stderr.write(
        "settings-template-sync-check: enforcement hook(s) wired in "
        ".claude/settings.json but MISSING from settings-template.json -> they "
        "ship DEAD to the fleet (kipi update rebuilds instance settings from the "
        "template only):\n"
    )
    for s in stranded:
        sys.stderr.write(f"  - {s}\n")
    sys.stderr.write(
        "Fix: add them to settings-template.json, or add to SKELETON_ONLY if "
        "intentionally skeleton-only.\n"
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
