#!/usr/bin/env python3
"""Classify a gate registry without deleting or reordering receipts."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path


LIFECYCLES = (
    "regression",
    "historical-receipt",
    "retired",
    "external",
)


def _read_registry(path: Path) -> list[dict]:
    records = []
    seen = set()
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        gate_id = record.get("gate_id")
        if not isinstance(gate_id, str) or not gate_id:
            raise ValueError(f"{path}:{lineno}: missing gate_id")
        if gate_id in seen:
            raise ValueError(f"{path}:{lineno}: duplicate gate_id {gate_id!r}")
        seen.add(gate_id)
        records.append(record)
    return records


def _classification(args: argparse.Namespace) -> dict[str, str]:
    result = {}
    for lifecycle in ("regression", "external", "retired"):
        for gate_id in getattr(args, lifecycle):
            previous = result.get(gate_id)
            if previous:
                raise ValueError(
                    f"gate {gate_id!r} assigned to both {previous} and {lifecycle}"
                )
            result[gate_id] = lifecycle
    return result


def _write_atomic(path: Path, records: list[dict]) -> None:
    payload = "".join(
        json.dumps(record, separators=(",", ":")) + "\n"
        for record in records
    )
    with tempfile.NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--regression", action="append", default=[])
    parser.add_argument("--external", action="append", default=[])
    parser.add_argument("--retired", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    try:
        records = _read_registry(args.registry)
        classifications = _classification(args)
        known = {record["gate_id"] for record in records}
        unknown = sorted(set(classifications) - known)
        if unknown:
            raise ValueError(
                f"classification references unknown gate(s): {', '.join(unknown)}"
            )
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    migrated = []
    for record in records:
        migrated_record = dict(record)
        existing_lifecycle = record.get("lifecycle", "historical-receipt")
        if existing_lifecycle not in LIFECYCLES:
            sys.stderr.write(
                f"gate {record['gate_id']!r} has invalid existing lifecycle "
                f"{existing_lifecycle!r}\n"
            )
            return 2
        migrated_record["lifecycle"] = classifications.get(
            record["gate_id"], existing_lifecycle
        )
        migrated.append(migrated_record)

    counts = Counter(record["lifecycle"] for record in migrated)
    summary = {
        "registry": str(args.registry),
        "records": len(migrated),
        "counts": {lifecycle: counts[lifecycle] for lifecycle in LIFECYCLES},
        "applied": args.apply,
    }
    if args.apply:
        try:
            _write_atomic(args.registry, migrated)
        except OSError as exc:
            sys.stderr.write(f"{exc}\n")
            return 2
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
