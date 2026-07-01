#!/usr/bin/env python3
"""lessons_scrub: the fail-closed client-data gate for autonomous lesson publishing.

A distilled lesson publishes ONLY if `is_clean` returns True. A cross-client data leak is
irreversible for a threat-intel shop, so this gate is DETERMINISTIC hard code, not model judgment:
it catches the known high-signal leaks (static client tokens, absolute paths, emails, URLs, and the
registry's instance codenames). The distiller's LLM does the HOW-only abstraction; a separate LLM
semantic pass is a second net; THIS module is the last deterministic backstop before a write.

Fail-closed: if ANY client-data signal remains, the lesson is HELD (not published) and reported.
Over-holding a clean lesson is a safe false positive; leaking one is not. This module holds.

Importable: `find_client_data(text, extra_terms)`, `scrub(text, extra_terms)`, `is_clean(text, extra_terms)`.
`codenames_from_registry(path)` builds the extra_terms roster (distinctive instance names only).
"""
import json
import re
from pathlib import Path

# Static high-signal tokens (mirrors lessons-validator.py:22 / kipi-push-upstream.sh:26).
STATIC_TOKEN_RE = re.compile(r"KTLYST|CISO|re-breach|Assaf", re.IGNORECASE)
# Absolute path (/Users/... or any 2+ segment unix path), email, and URL.
PATH_RE = re.compile(r"/Users/[^\s]*|(?:/[A-Za-z0-9_.\-]+){2,}")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
URL_RE = re.compile(r"https?://[^\s)]+")


def codenames_from_registry(registry_path):
    """Instance names that are distinctive identifiers (codenames), not generic English.
    Heuristic: contains an uppercase letter, a digit, or an underscore. Generic lowercase
    role names (accountant, negotiator, travel-agent) are skipped to avoid over-holding."""
    try:
        data = json.loads(Path(registry_path).read_text())
    except Exception:
        return []
    names = []
    for entry in data.get("instances", []):
        name = entry.get("name", "")
        if re.search(r"[A-Z]|\d|_", name):
            names.append(name)
    return names


def find_client_data(text, extra_terms=()):
    """Return list of (category, matched_string) for every client-data signal in text. Empty = clean."""
    hits = []
    for m in STATIC_TOKEN_RE.finditer(text):
        hits.append(("token", m.group(0)))
    for m in URL_RE.finditer(text):
        hits.append(("url", m.group(0)))
    for m in EMAIL_RE.finditer(text):
        hits.append(("email", m.group(0)))
    for m in PATH_RE.finditer(text):
        hits.append(("path", m.group(0)))
    for term in extra_terms:
        if term and re.search(r"\b" + re.escape(term) + r"\b", text, re.IGNORECASE):
            hits.append(("codename", term))
    return hits


def is_clean(text, extra_terms=()):
    """Fail-closed: clean ONLY when no client-data signal is found."""
    return len(find_client_data(text, extra_terms)) == 0


PLACEHOLDER = {"token": "[CLIENT]", "url": "[URL]", "email": "[EMAIL]",
               "path": "[PATH]", "codename": "[CLIENT]"}


def scrub(text, extra_terms=()):
    """Best-effort replace of client-data signals with placeholders. Returns (scrubbed, hits).
    The caller must still gate on is_clean(scrubbed) -- scrub is a helper, not the guarantee."""
    scrubbed = text
    scrubbed = URL_RE.sub(PLACEHOLDER["url"], scrubbed)
    scrubbed = EMAIL_RE.sub(PLACEHOLDER["email"], scrubbed)
    scrubbed = PATH_RE.sub(PLACEHOLDER["path"], scrubbed)
    scrubbed = STATIC_TOKEN_RE.sub(PLACEHOLDER["token"], scrubbed)
    for term in extra_terms:
        if term:
            scrubbed = re.sub(r"\b" + re.escape(term) + r"\b", PLACEHOLDER["codename"],
                              scrubbed, flags=re.IGNORECASE)
    return scrubbed, find_client_data(text, extra_terms)


if __name__ == "__main__":
    import sys
    sample = sys.stdin.read()
    hits = find_client_data(sample)
    print("clean" if not hits else "HELD: " + ", ".join(f"{c}:{v}" for c, v in hits))
