#!/usr/bin/env python3
"""Allowlist validator for q-system/lessons/ lesson files.

PostToolUse(Edit|Write) hook wired in the skeleton .claude/settings.json. Guards
founder writes where lessons are authored; instances are read-only consumers so it
is moot there. Pairs with the lessons corpus (PRD prd-cross-instance-learning-2026-06-19).

Reads hook JSON on stdin. Exit 0 (allow) unless the edited file is a lesson under
q-system/lessons/ that violates the frontmatter contract -> exit 2 (block, stderr
fed back to Claude). Self-scoped: any path outside q-system/lessons/ (or README.md)
exits 0 fast. stdlib only.
"""
import json
import os
import re
import sys

ALLOWED_KEYS = {"id", "kind", "title", "date"}
ALLOWED_KINDS = {"pattern", "methodology"}
# client-token denylist (mirrors kipi-push-upstream.sh line 26); structural backstop
# on the one content field (title) that fans eagerly to every instance.
TOKEN_RE = re.compile(r"KTLYST|CISO|re-breach|Assaf|/Users/", re.IGNORECASE)


def block(msg):
    sys.stderr.write("lessons-validator: " + msg + "\n")
    sys.exit(2)


def parse_frontmatter(text):
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fm = {}
    for line in text[3:end].strip("\n").splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            return None
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm


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
    if "q-system/lessons/" not in norm:
        sys.exit(0)
    if os.path.basename(norm) == "README.md":
        sys.exit(0)
    try:
        with open(fp) as f:
            content = f.read()
    except Exception:
        sys.exit(0)  # PostToolUse: file is on disk; unreadable -> nothing to validate
    fm = parse_frontmatter(content)
    if fm is None:
        block(os.path.basename(norm) + ": no/invalid YAML frontmatter")
    keys = set(fm.keys())
    extra = keys - ALLOWED_KEYS
    if extra:
        block("frontmatter keys outside " + str(sorted(ALLOWED_KEYS)) + ": " + str(sorted(extra)) + " (allowlist)")
    missing = ALLOWED_KEYS - keys
    if missing:
        block("frontmatter missing required keys: " + str(sorted(missing)))
    if fm.get("kind") not in ALLOWED_KINDS:
        block("kind=" + repr(fm.get("kind")) + " not in " + str(sorted(ALLOWED_KINDS)) + " (scar/rca forbidden)")
    if TOKEN_RE.search(str(fm.get("title", ""))):
        block("title matches client-token denylist (no client identifiers in a fanned title)")
    sys.exit(0)


if __name__ == "__main__":
    main()
