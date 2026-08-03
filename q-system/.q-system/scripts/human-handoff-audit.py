#!/usr/bin/env python3
"""No code path may declare that the process needs a human without naming why.

Founder-directed 2026-08-02: "review the whole code and identify anywhere that
says the process needs a human and remove it."

WHY THIS IS A SCRIPT AND NOT A GREP. The same class was hand-grepped three times
this session and each pass used a different, narrower vocabulary -- "Needs a
human" found converge.sh but missed "until someone runs", "the founder must" and
"manual intervention". A one-off grep proves the phrase you thought of is absent;
it says nothing about the phrase you did not. This carries the whole vocabulary
in one place so the next sweep is reproducible and the gate can run it forever.

THE RULE IS NOT "NEVER NAME A HUMAN". Some work genuinely is the founder's, and
`~/.claude/CLAUDE.md`'s destructive-op carve-out is explicit that asking for those
is the contract rather than a violation of it. So a call site may declare a human
by naming the CLASS that makes it human-only, using the same vocabulary
slack-notify.sh allowlists for `--kind decision --class` and founder-actor-gate.py
uses on prose. One vocabulary, three layers.

    # human-required: irreversible-git -- rewriting published history

WHAT IT DOES NOT CATCH (honest boundary):
  * A handoff phrased in words not in HANDOFF_PATTERNS. The vocabulary is
    open-ended by nature; this bounds the known shapes, it cannot bound English.
  * A call site that names a class dishonestly. The marker bounds the vocabulary,
    not the intent. Only review does.
  * Prose in .md rules and docs -- out of scope, captured as sp-87ff73a1 rather
    than merely noted here. Those describe the  # spillover-skip
    system rather than being it, and founder-actor-gate.py covers live prose.

Exit 0 = clean. Exit 1 = at least one unexplained handoff.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ALLOWED_CLASSES = (
    "irreversible-git", "out-of-tree-write", "spend", "publish", "credential",
)
MARKER = "human-required:"

# Ordered roughly by how often each shape actually appeared in this repo.
HANDOFF_PATTERNS = [
    ("names a human as the actor", re.compile(
        r"needs?\s+a\s+human|requires?\s+a\s+human|a\s+human\s+(?:must|has\s+to|needs?\s+to)"
        r"|human\s+intervention|needs?\s+manual|manual\s+intervention", re.I)),
    ("names the founder as the actor", re.compile(
        r"the\s+founder\s+(?:must|has\s+to|needs?\s+to|should|will\s+need)"
        r"|ask\s+the\s+founder|tell\s+the\s+founder\s+to\b"
        r"|only\s+the\s+founder\s+can|waiting\s+(?:on|for)\s+the\s+founder", re.I)),
    ("defers to an unnamed someone", re.compile(
        r"until\s+someone|someone\s+(?:must|has\s+to|needs?\s+to|runs)"
        r"|somebody\s+(?:must|has\s+to|needs?\s+to)", re.I)),
    ("hands over a command to run", re.compile(
        r"\bDo:\s*(?:cd|git|gh|python3|bash|npm|kipi|launchctl|brew)\b"
        r"|run\s+(?:this|it)\s+(?:by\s+hand|yourself|manually)"
        r"|by\s+hand:\s*(?:cd|git|gh|python3|bash|kipi)\b", re.I)),
]

SKIP_DIR_PARTS = (".git", "node_modules", "worktrees", "template-repo",
                  ".prd-os", "__pycache__")
SKIP_DIR_PREFIXES = (".pr", ".review-")
# This file necessarily quotes every pattern it hunts.
SKIP_FILES = ("human-handoff-audit.py",)


def is_skipped(rel: str) -> bool:
    parts = rel.split(os.sep)
    if any(p in SKIP_DIR_PARTS for p in parts):
        return True
    if any(p.startswith(SKIP_DIR_PREFIXES) for p in parts[:-1]):
        return True
    return os.path.basename(rel) in SKIP_FILES


def tracked(repo: str):
    out = subprocess.run(["git", "-C", repo, "ls-files"],
                         capture_output=True, text=True, check=False)
    for rel in out.stdout.splitlines():
        if rel.endswith((".sh", ".py")) and not is_skipped(rel):
            yield rel


def explained(line: str, window: str) -> bool:
    """A handoff is explained when the marker names an allowlisted class nearby.

    The window is small on purpose: a class named ten lines away is not an
    explanation of THIS line, it is a coincidence.
    """
    if MARKER not in window:
        return False
    tail = window.split(MARKER, 1)[1][:120]
    return any(c in tail for c in ALLOWED_CLASSES)


def findings(repo: str):
    out = []
    for rel in tracked(repo):
        try:
            lines = open(os.path.join(repo, rel), encoding="utf-8",
                         errors="replace").read().splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            for label, pat in HANDOFF_PATTERNS:
                if not pat.search(line):
                    continue
                window = "\n".join(lines[max(0, i - 3):i + 4])
                if explained(line, window):
                    continue
                out.append((rel, i + 1, label, line.strip()[:104]))
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    a = ap.parse_args()
    bad = findings(os.path.abspath(a.repo))
    if not bad:
        print("human-handoff-audit: OK -- no unexplained human handoff in live code")
        return 0
    print(f"human-handoff-audit: {len(bad)} unexplained human handoff(s).\n")
    for rel, ln, label, text in bad:
        print(f"  {rel}:{ln}  [{label}]\n      {text}")
    print(f"\nEither make the code DO it, or declare why it cannot:\n"
          f"    # {MARKER} <{'|'.join(ALLOWED_CLASSES)}> -- <reason>\n"
          f"A process that says it needs a human, without saying which authority it\n"
          f"lacks, is an unbuilt feature wearing a status message.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
