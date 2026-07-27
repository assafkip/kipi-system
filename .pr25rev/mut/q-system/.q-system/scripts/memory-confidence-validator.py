#!/usr/bin/env python3
"""Confidence/provenance validator for auto-memory files.

PostToolUse(Edit|Write) hook. Pairs with .claude/rules/memory-confidence.md and
PRD prd-memory-confidence-provenance-2026-06-30. Self-scoped: only fires on auto-
memory files (a path under ~/.claude/projects/<slug>/memory/*.md, excluding the
MEMORY.md index); every other path exits 0 fast.

Reads hook JSON on stdin. Exit 0 (allow) unless the written memory file declares a
`confidence` outside [0.0, 1.0] or a `provenance` outside the fixed enum -> exit 2
(block, stderr fed back to Claude). Absent fields always pass (the fields are
optional, like `decay`). stdlib only.

Scar (why this exists): kipi auto-memory stored facts with no certainty signal, so
a model-inferred guess and a founder-stated fact were byte-indistinguishable at
recall. memanto tags every record with confidence + provenance; kipi did not. This
hook is the deterministic half (no-prompt-only rule) -- the rule file is the spec,
this is the enforcement.

Scope is matched by PATH SUBSTRING (not by resolving an absolute dir) so the check
is unit-testable against a temp path, exactly as lessons-validator.py scopes on
"q-system/lessons/".
"""
import json
import sys

PROVENANCE = {
    "explicit_statement",
    "inferred",
    "corrected",
    "validated",
    "observed",
    "imported",
}


def block(msg):
    sys.stderr.write("memory-confidence-validator: " + msg + "\n")
    sys.exit(2)


def in_scope(file_path):
    """True only for an auto-memory content file (not the MEMORY.md index)."""
    norm = file_path.replace("\\", "/")
    if not norm.endswith(".md"):
        return False
    if "/.claude/projects/" not in norm or "/memory/" not in norm:
        return False
    if norm.rsplit("/", 1)[-1] == "MEMORY.md":
        return False
    return True


def parse_frontmatter(text):
    """Return dict of top-level frontmatter scalars, or None if no frontmatter."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fm = {}
    for line in text[3:end].strip("\n").splitlines():
        # only top-level keys (no leading whitespace); skip nested (metadata:) and comments
        if not line or line[0].isspace() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        fm[key.strip()] = val.strip().strip('"').strip("'")
    return fm


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not file_path or not in_scope(file_path):
        sys.exit(0)
    try:
        with open(file_path) as fh:
            content = fh.read()
    except Exception:
        sys.exit(0)  # PostToolUse: file is on disk; unreadable -> nothing to validate
    fm = parse_frontmatter(content)
    if not fm:
        sys.exit(0)  # no frontmatter -> nothing to validate (freshness/other hooks own that)

    if "confidence" in fm:
        raw = fm["confidence"]
        try:
            conf = float(raw)
        except (TypeError, ValueError):
            block(f"confidence {raw!r} is not a number (want a float in [0.0, 1.0])")
        # NaN fails both comparisons below, so reject it explicitly. inf is caught
        # by the range check. (degenerate-case guard; fable-discipline)
        if conf != conf:
            block(f"confidence {raw!r} is NaN (want a real number in [0.0, 1.0])")
        if conf < 0.0 or conf > 1.0:
            block(f"confidence {conf} out of range [0.0, 1.0]")

    if "provenance" in fm:
        prov = fm["provenance"]
        if prov not in PROVENANCE:
            block(
                f"provenance {prov!r} not in enum "
                + str(sorted(PROVENANCE))
            )

    sys.exit(0)


if __name__ == "__main__":
    main()
