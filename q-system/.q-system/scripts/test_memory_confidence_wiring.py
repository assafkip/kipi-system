#!/usr/bin/env python3
"""Wiring test for the memory-confidence feature (mcp-03).

DEPENDS ON mcp-01 + mcp-02: asserts the validator and surfacer scripts exist and
are executable BEFORE checking they are wired into settings.json. Then checks the
rule doc and the skill-hook-pairing registration. Proves the feature is connected
end-to-end, not just present as files (wiring-check rule).

Run: python3 q-system/.q-system/scripts/test_memory_confidence_wiring.py
"""
import json
import os
import sys

# QROOT: q-system/.q-system/scripts/ -> up 3 = repo root
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(SCRIPTS, "..", "..", ".."))

VALIDATOR = os.path.join(SCRIPTS, "memory-confidence-validator.py")
SURFACER = os.path.join(SCRIPTS, "memory-confidence-surface.py")
SETTINGS = os.path.join(REPO, ".claude", "settings.json")
RULE = os.path.join(REPO, ".claude", "rules", "memory-confidence.md")
PAIRING = os.path.join(REPO, ".claude", "rules", "skill-hook-pairing.md")


def main():
    failures = []

    def check(label, ok):
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            failures.append(label)

    # mcp-01 + mcp-02 dependency: scripts exist and are executable
    check("validator script exists", os.path.isfile(VALIDATOR))
    check("surfacer script exists", os.path.isfile(SURFACER))
    check("validator is executable", os.access(VALIDATOR, os.X_OK))
    check("surfacer is executable", os.access(SURFACER, os.X_OK))

    # settings.json valid + both hooks wired in the right events
    settings_text = ""
    try:
        with open(SETTINGS) as fh:
            settings_text = fh.read()
        json.loads(settings_text)  # must parse
        check("settings.json is valid JSON", True)
    except Exception as exc:
        check(f"settings.json is valid JSON ({exc})", False)

    hooks = {}
    try:
        hooks = json.loads(settings_text).get("hooks", {})
    except Exception:
        pass

    def event_has(event, needle):
        blob = json.dumps(hooks.get(event, []))
        return needle in blob

    check("surfacer wired in SessionStart",
          event_has("SessionStart", "memory-confidence-surface.py"))
    check("validator wired in PostToolUse",
          event_has("PostToolUse", "memory-confidence-validator.py"))

    # rule doc present with frontmatter
    rule_ok = False
    if os.path.isfile(RULE):
        with open(RULE) as fh:
            rule_ok = fh.read().startswith("---")
    check("memory-confidence.md present with frontmatter", rule_ok)

    # pairing registered
    pairing_ok = False
    if os.path.isfile(PAIRING):
        with open(PAIRING) as fh:
            pairing_ok = "memory-confidence" in fh.read()
    check("pairing registered in skill-hook-pairing.md", pairing_ok)

    if failures:
        print(f"\nFAILED: {failures}")
        sys.exit(1)
    print("\nOK: feature wired end-to-end")
    sys.exit(0)


if __name__ == "__main__":
    main()
