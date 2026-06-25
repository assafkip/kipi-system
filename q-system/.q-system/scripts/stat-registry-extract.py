#!/usr/bin/env python3
"""
stat-registry-extract.py — audit + (optional) regenerate the canonical stat
registry.

Modes:
    (no args)       PostToolUse hook mode. Reads tool payload from stdin.
                    If the edited file is a canonical markdown file, audits
                    the registry against the file's numeric claims. Prints
                    warnings to stderr if drift is found. Exits 0 always
                    (warnings only — does not block).
    <file_path>     CLI audit of a single canonical file.
    --audit-all     Walk canonical/ tree, audit every file, report drift.
    --regen-stamp   Bump `regenerated_at` and `regenerated_from` in the
                    registry. Useful after manual registry edits.
    --self-test     Built-in fixtures.

Design intent:
    The registry contains curated entries (claim text, source attribution,
    canonical phrasings). Auto-extraction can't fully replace curation —
    it can only flag numerics that exist in canonical but are missing from
    the registry's approved_numerics index. That's the audit's job.

    For now the extractor does NOT auto-write entries. It surfaces drift
    and trusts the founder to update the registry. The hook keeps the
    drift visible.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CANONICAL_PATTERN = re.compile(r"/(canonical|my-project)/[^/]+\.md$")

# Same numeric patterns as stat-verify, but we don't need scope rules here —
# canonical is the source.
NUMERIC_PATTERNS = [
    re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%"),
    # Dollar form mirrors stat-verify.py: ranges (e.g. $25-75K) extract as
    # one token so the upper bound is part of the drift signal.
    re.compile(r"\$\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?[KMB]?\+?(?![\w])"),
    re.compile(r"\b\d+(?:-\d+)?x\b", re.IGNORECASE),
]

CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def find_registry(start: Path) -> Path | None:
    here = start.resolve()
    if here.is_file():
        here = here.parent
    for parent in [here, *here.parents]:
        for candidate in parent.rglob("canonical/stat-registry.json"):
            sp = str(candidate)
            if any(x in sp for x in ("/.venv/", "/node_modules/", "/__pycache__/")):
                continue
            return candidate
    return None


def collect_numerics(text: str) -> set[str]:
    """Strip code, extract every numeric token of interest."""
    stripped = CODE_FENCE_RE.sub("", text)
    stripped = INLINE_CODE_RE.sub("", stripped)
    found: set[str] = set()
    for pat in NUMERIC_PATTERNS:
        for m in pat.finditer(stripped):
            found.add(m.group(0).strip())
    return found


def registry_approved(registry: dict) -> set[str]:
    out: set[str] = set()
    for stat in registry.get("stats", []):
        for n in stat.get("approved_numerics", []):
            out.add(n.strip())
    return out


def audit_file(canonical_file: Path, registry: dict) -> list[str]:
    """Return numerics that appear in canonical_file but not in registry.

    Read errors surface as a synthetic drift entry — the contract is that
    drift is loudly surfaced. A canonical file that can't be read is itself
    a drift signal, not a silent pass.
    """
    if not canonical_file.exists():
        return []
    try:
        text = canonical_file.read_text()
    except (OSError, UnicodeDecodeError) as e:
        return [f"<unreadable: {type(e).__name__}>"]
    found = collect_numerics(text)
    approved = registry_approved(registry)
    return sorted(found - approved)


def regen_stamp(registry_path: Path, regenerated_from: list[str] | None = None) -> None:
    """Update the registry's regenerated_at timestamp (and optionally list)."""
    data = json.loads(registry_path.read_text())
    data["regenerated_at"] = datetime.now(timezone.utc).isoformat()
    if regenerated_from is not None:
        data["regenerated_from"] = regenerated_from
    registry_path.write_text(json.dumps(data, indent=2) + "\n")


def is_canonical_file(file_path: str) -> bool:
    fp = file_path.replace("\\", "/")
    return bool(CANONICAL_PATTERN.search(fp))


def hook_mode() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)
    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not file_path or not is_canonical_file(file_path):
        sys.exit(0)
    fp = Path(file_path)
    if not fp.exists():
        sys.exit(0)
    registry_path = find_registry(fp)
    if registry_path is None:
        sys.exit(0)
    registry = json.loads(registry_path.read_text())
    drift = audit_file(fp, registry)
    if drift:
        print(
            f"stat-registry: drift detected in {fp.name} ({len(drift)} numerics not in registry):",
            file=sys.stderr,
        )
        for tok in drift[:20]:
            print(f"  • {tok}", file=sys.stderr)
        if len(drift) > 20:
            print(f"  ... and {len(drift) - 20} more", file=sys.stderr)
        print(
            "Update <instance>/canonical/stat-registry.json approved_numerics or "
            "canonical_phrasings to keep the stat-verify gate in sync.",
            file=sys.stderr,
        )
    sys.exit(0)


def cli_audit(target: str) -> None:
    fp = Path(target)
    if not fp.exists():
        print(f"not found: {target}", file=sys.stderr)
        sys.exit(1)
    registry_path = find_registry(fp)
    if registry_path is None:
        print("no stat-registry.json found", file=sys.stderr)
        sys.exit(1)
    registry = json.loads(registry_path.read_text())
    drift = audit_file(fp, registry)
    if not drift:
        print(f"stat-registry: {target} clean ({len(registry_approved(registry))} approved)")
        sys.exit(0)
    print(f"stat-registry: drift in {target} ({len(drift)} unmatched):")
    for tok in drift:
        print(f"  • {tok}")
    sys.exit(0)


def cli_audit_all() -> None:
    cwd = Path.cwd()
    registry_path = find_registry(cwd)
    if registry_path is None:
        print("no stat-registry.json found", file=sys.stderr)
        sys.exit(1)
    registry = json.loads(registry_path.read_text())
    canonical_root = registry_path.parent  # canonical/
    instance_root = canonical_root.parent
    candidates = list(canonical_root.glob("*.md"))
    my_project = instance_root / "my-project"
    if my_project.exists():
        candidates.extend(my_project.glob("*.md"))
    total_drift = 0
    for f in candidates:
        drift = audit_file(f, registry)
        if drift:
            total_drift += len(drift)
            print(f"\n{f}: {len(drift)} unmatched")
            for tok in drift[:10]:
                print(f"  • {tok}")
            if len(drift) > 10:
                print(f"  ... and {len(drift) - 10} more")
    print(f"\ntotal drift across {len(candidates)} canonical files: {total_drift}")
    sys.exit(0)


def self_test() -> None:
    fake_registry = {
        "stats": [
            {"approved_numerics": ["21%", "13%", "90%"]},
            {"approved_numerics": ["$56M"]},
        ],
    }
    fake_canonical = (
        "Enterprise SIEMs cover 21% of ATT&CK despite data for 90%.\n"
        "13% of rules are broken. CardinalOps raised $56M.\n"
        "Some unknown 99% claim and a 42% stat not in registry.\n"
    )
    found = collect_numerics(fake_canonical)
    approved = registry_approved(fake_registry)
    drift = sorted(found - approved)
    expected = ["42%", "99%"]
    if drift != expected:
        print(f"FAIL: expected drift {expected}, got {drift}", file=sys.stderr)
        sys.exit(1)
    print(f"  [PASS] drift detection: expected {expected}, got {drift}")
    print(f"\nself-test: passed")
    sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        hook_mode()
    elif sys.argv[1] == "--self-test":
        self_test()
    elif sys.argv[1] == "--audit-all":
        cli_audit_all()
    elif sys.argv[1] == "--regen-stamp":
        cwd = Path.cwd()
        registry_path = find_registry(cwd)
        if registry_path is None:
            print("no stat-registry.json found", file=sys.stderr)
            sys.exit(1)
        regen_stamp(registry_path)
        print(f"stamped: {registry_path}")
        sys.exit(0)
    elif len(sys.argv) == 2:
        cli_audit(sys.argv[1])
    else:
        print("Usage: stat-registry-extract.py [<file> | --audit-all | --regen-stamp | --self-test]", file=sys.stderr)
        sys.exit(1)
