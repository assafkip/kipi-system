#!/usr/bin/env python3
"""instance-automation-guard: block writing automation scripts into an INSTANCE's q-system/ subtree.

Deterministic enforcement of RULE-2026-06-30-A (see q-system/canonical/decisions.md and
AUTONOMOUS-SYSTEMS.md). The scar: instance-specific scripts placed inside the synced q-system/ tree
were deleted by `kipi update`'s `rsync --delete`; two income-scanner jobs then exited 127 silently
for 6 days (2026-06-24). A prose rule is a suggestion; this hook is the enforcement.

PostToolUse(Edit|Write|MultiEdit) hook, wired in settings-template.json so it FANS to every instance
(the skeleton is where it's authored but it no-ops there). Reads hook JSON on stdin.

Fires (exit 2, block) when ALL hold:
  - the edited path is a script (.sh / .py / .plist), and
  - it is under a `q-system/` subtree, and
  - this repo is an INSTANCE, not the skeleton (skeleton has instance-registry.json at its root;
    skeleton scripts belong in q-system/ and SHOULD fan), and
  - the file does not carry the bypass marker `automation-guard-skip`.

Otherwise exit 0 fast. stdlib only.
"""
import json
import os
import sys

SCRIPT_EXTS = (".sh", ".py", ".plist")
BYPASS_MARKER = "automation-guard-skip"


def is_skeleton(project_dir):
    """The skeleton (kipi-system) has instance-registry.json at its root; instances do not."""
    return os.path.exists(os.path.join(project_dir, "instance-registry.json"))


def block(path):
    sys.stderr.write(
        "instance-automation-guard: refusing to write a script into the q-system/ subtree of an "
        "instance.\n"
        f"  {path}\n"
        "  That subtree is read-only from an instance AND is a `kipi update` rsync --delete target, "
        "so a script here gets clobbered on the next update (scar 2026-06-24; RULE-2026-06-30-A).\n"
        "  Fix: put instance-specific automation at the repo ROOT (e.g. automation/), which is never "
        "fanned; or edit skeleton scripts upstream in kipi-system.\n"
        "  Deliberate exception: add the marker `" + BYPASS_MARKER + "` to the file.\n"
    )
    sys.exit(2)


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    ti = payload.get("tool_input") or {}
    fp = ti.get("file_path") or ti.get("path") or ""
    if not fp:
        sys.exit(0)
    norm = fp.replace("\\", "/")
    if "/q-system/" not in norm and not norm.startswith("q-system/"):
        sys.exit(0)
    if not norm.endswith(SCRIPT_EXTS):
        sys.exit(0)

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    if is_skeleton(project_dir):
        sys.exit(0)  # skeleton: scripts belong in q-system/ and should propagate

    try:
        if BYPASS_MARKER in open(fp, errors="ignore").read():
            sys.exit(0)
    except Exception:
        pass

    block(norm)


if __name__ == "__main__":
    main()
