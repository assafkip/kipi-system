#!/usr/bin/env python3
"""Drift gate for the fleet ingestion coverage contract.

The homogeneity enforcer. `kipi update` rsyncs the canonical `kipi_ingest/` from
the skeleton into every instance, so drift can only appear if an instance copy is
hand-edited between updates. This script makes that deterministic:

  --emit                 (run in the skeleton) recompute canonical.sha256, the
                         committed manifest of every source file's hash.
  --check <dir>          (run in an instance) recompute the hashes of <dir> and
                         compare to the shipped canonical.sha256. Exit non-zero,
                         naming every drifted / missing / extra file, if they
                         differ. Wired as a required_check + a kipi update
                         preflight, so a drifted copy is caught, not eyeballed.

Stdlib only. Modeled on export-fable-mirror.sh --check (the fable-discipline
mirror gate), applied inside the fleet instead of to a public repo.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parent
_MANIFEST = _PKG / "canonical.sha256"
_SKIP_DIRS = {"__pycache__", "tests"}
_SKIP_NAMES = {"canonical.sha256"}


def _source_files(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        if p.name in _SKIP_NAMES:
            continue
        out.append(p)
    return out


def _hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest_for(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): _hash(p) for p in _source_files(root)}


def _read_manifest(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, rel = line.split("  ", 1)
        out[rel] = digest
    return out


def emit() -> int:
    entries = _manifest_for(_PKG)
    body = ["# canonical.sha256 -- fleet ingestion contract. Regenerate: drift_check.py --emit"]
    body += [f"{digest}  {rel}" for rel, digest in sorted(entries.items())]
    _MANIFEST.write_text("\n".join(body) + "\n", encoding="utf-8")
    print(f"wrote {_MANIFEST} ({len(entries)} files)")
    return 0


def check(target_dir: str) -> int:
    root = Path(target_dir).resolve()
    pkg = root if (root / "contract.py").exists() else root / "kipi_ingest"
    manifest_path = pkg / "canonical.sha256"
    if not manifest_path.exists():
        print(f"DRIFT: no canonical.sha256 in {pkg} (contract not adopted here?)",
              file=sys.stderr)
        return 2
    want = _read_manifest(manifest_path)
    have = _manifest_for(pkg)
    problems = []
    for rel, digest in want.items():
        if rel not in have:
            problems.append(f"MISSING {rel}")
        elif have[rel] != digest:
            problems.append(f"DRIFTED {rel}")
    for rel in have:
        if rel not in want:
            problems.append(f"EXTRA   {rel}")
    if problems:
        print(f"DRIFT in {pkg} vs canonical:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print("Fix: re-run `kipi update` (do not hand-edit an instance copy).",
              file=sys.stderr)
        return 2
    print(f"drift check: clean ({len(want)} files match canonical)")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 1 and argv[0] == "--emit":
        return emit()
    if len(argv) == 2 and argv[0] == "--check":
        return check(argv[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
