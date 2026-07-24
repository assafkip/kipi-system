#!/usr/bin/env python3
"""Build a redacted inventory from ephemeral instance-fact candidates.

Raw facts are accepted only as input. Output is a whitelisted projection with
source coordinates, fact class, hashes, and a redacted identifier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


class InventoryBlocked(ValueError):
    """Raised when inventory evidence cannot be handled safely."""


FACT_CLASSES = {
    "client",
    "interaction",
    "investigation",
    "pricing",
    "proof_gap",
    "prospect",
    "relationship",
}
INPUT_FIELDS = {
    "fact_class",
    "line",
    "owner",
    "raw_fact",
    "source_path",
}
INCLUDED_TREES = {"q-system", "plugins", ".claude"}
EXCLUDED_PREFIXES = {
    ".prd-os",
    "q-system/memory",
    "q-system/output",
}
DEFAULT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas/containment-inventory.schema.json"
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_schema_value(value: Any, schema: dict, location: str) -> None:
    if "const" in schema and (
        value != schema["const"]
        or type(value) is not type(schema["const"])
    ):
        raise InventoryBlocked(f"{location} violates schema const")
    if "enum" in schema and value not in schema["enum"]:
        raise InventoryBlocked(f"{location} violates schema enum")

    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            raise InventoryBlocked(f"{location} must be an object")
        required = schema.get("required", [])
        missing = set(required) - set(value)
        if missing:
            raise InventoryBlocked(
                f"{location} is missing schema fields"
            )
        properties = schema.get("properties", {})
        unexpected = set(value) - set(properties)
        if schema.get("additionalProperties") is False and unexpected:
            raise InventoryBlocked(
                f"{location} contains forbidden persistence fields"
            )
        for key, child in value.items():
            if key in properties:
                _validate_schema_value(
                    child,
                    properties[key],
                    f"{location}.{key}",
                )
    elif expected_type == "array":
        if not isinstance(value, list):
            raise InventoryBlocked(f"{location} must be an array")
        item_schema = schema.get("items", {})
        for index, item in enumerate(value):
            _validate_schema_value(
                item,
                item_schema,
                f"{location}[{index}]",
            )
    elif expected_type == "string":
        if not isinstance(value, str):
            raise InventoryBlocked(f"{location} must be a string")
        pattern = schema.get("pattern")
        if pattern is not None and re.fullmatch(pattern, value) is None:
            raise InventoryBlocked(f"{location} violates schema pattern")
    elif expected_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise InventoryBlocked(f"{location} must be an integer")
        if "minimum" in schema and value < schema["minimum"]:
            raise InventoryBlocked(f"{location} violates schema minimum")


def _validate_schema_definition(schema: dict, location: str) -> None:
    if not isinstance(schema, dict):
        raise InventoryBlocked("containment inventory schema is malformed")
    if "const" in schema:
        if set(schema) != {"const"}:
            raise InventoryBlocked(
                "containment inventory schema is malformed"
            )
        return

    expected_type = schema.get("type")
    if expected_type == "object":
        properties = schema.get("properties")
        required = schema.get("required")
        if (
            not isinstance(properties, dict)
            or not isinstance(required, list)
            or schema.get("additionalProperties") is not False
            or set(required) != set(properties)
        ):
            raise InventoryBlocked(
                "containment inventory schema is malformed"
            )
        for key, child in properties.items():
            _validate_schema_definition(child, f"{location}.{key}")
    elif expected_type == "array":
        if not isinstance(schema.get("items"), dict):
            raise InventoryBlocked(
                "containment inventory schema is malformed"
            )
        _validate_schema_definition(schema["items"], f"{location}[]")
    elif expected_type == "string":
        if not (
            isinstance(schema.get("pattern"), str)
            or (
                isinstance(schema.get("enum"), list)
                and schema["enum"]
                and all(isinstance(item, str) for item in schema["enum"])
            )
        ):
            raise InventoryBlocked(
                "containment inventory schema is malformed"
            )
    elif expected_type == "integer":
        if (
            isinstance(schema.get("minimum"), bool)
            or not isinstance(schema.get("minimum"), int)
        ):
            raise InventoryBlocked(
                "containment inventory schema is malformed"
            )
    else:
        raise InventoryBlocked("containment inventory schema is malformed")


def validate_inventory_artifact(
    inventory: dict[str, Any],
    schema_path: Path | str = DEFAULT_SCHEMA_PATH,
) -> None:
    """Reject any inventory field not permitted by the checked-in schema."""
    try:
        schema = json.loads(
            Path(schema_path).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryBlocked(
            "cannot load containment inventory schema"
        ) from exc
    if not isinstance(schema, dict):
        raise InventoryBlocked("containment inventory schema is malformed")
    _validate_schema_definition(schema, "schema")
    _validate_schema_value(inventory, schema, "inventory")


def _is_included_path(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return False
    if any(
        relative_path == prefix or relative_path.startswith(prefix + "/")
        for prefix in EXCLUDED_PREFIXES
    ):
        return False
    return len(path.parts) == 1 or path.parts[0] in INCLUDED_TREES


def tracked_text_targets(repo_root: Path) -> set[str]:
    """Return generic tracked files whose worktree content is text."""
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InventoryBlocked("cannot enumerate tracked files") from exc

    targets: set[str] = set()
    for raw_path in completed.stdout.split(b"\0"):
        if not raw_path:
            continue
        try:
            relative_path = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InventoryBlocked("tracked path is not UTF-8") from exc
        if not _is_included_path(relative_path):
            continue

        absolute_path = repo_root / relative_path
        if absolute_path.is_symlink() or not absolute_path.is_file():
            continue
        try:
            content = absolute_path.read_bytes()
        except OSError as exc:
            raise InventoryBlocked(
                f"cannot read tracked target: {relative_path}"
            ) from exc
        if b"\0" in content:
            continue
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        targets.add(relative_path)
    return targets


def known_instance_owners(repo_root: Path) -> set[str]:
    """Load owner identifiers from the repository's instance registry."""
    registry_path = repo_root / "instance-registry.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryBlocked("cannot load authoritative owner registry") from exc

    if not isinstance(registry, dict) or not isinstance(
        registry.get("instances"), list
    ):
        raise InventoryBlocked("authoritative owner registry is malformed")

    owners: set[str] = set()
    for instance in registry["instances"]:
        if not isinstance(instance, dict):
            raise InventoryBlocked("authoritative owner registry is malformed")
        name = instance.get("name")
        if not isinstance(name, str) or not name:
            raise InventoryBlocked("authoritative owner registry is malformed")
        owners.add(name)
    return owners


def _validate_candidate(
    repo_root: Path,
    targets: set[str],
    known_owners: set[str],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    unexpected = set(candidate) - INPUT_FIELDS
    missing = INPUT_FIELDS - set(candidate)
    if unexpected:
        raise InventoryBlocked("candidate contains unexpected fields")
    if missing:
        raise InventoryBlocked("missing fields: " + ", ".join(sorted(missing)))

    source_path = candidate["source_path"]
    if not isinstance(source_path, str) or source_path not in targets:
        raise InventoryBlocked("not a tracked text target")

    line = candidate["line"]
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        raise InventoryBlocked("line must be a positive integer")
    try:
        source_lines = (repo_root / source_path).read_text(
            encoding="utf-8"
        ).splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise InventoryBlocked("cannot read tracked text target") from exc
    if line > len(source_lines):
        raise InventoryBlocked("line is outside tracked text target")

    fact_class = candidate["fact_class"]
    if not isinstance(fact_class, str) or fact_class not in FACT_CLASSES:
        raise InventoryBlocked("unknown fact class")

    owner = candidate["owner"]
    if not isinstance(owner, str) or owner not in known_owners:
        raise InventoryBlocked("unknown owner")

    raw_fact = candidate["raw_fact"]
    if not isinstance(raw_fact, str) or not raw_fact:
        raise InventoryBlocked("raw fact must be a non-empty string")
    if raw_fact != source_lines[line - 1]:
        raise InventoryBlocked("raw fact does not match the claimed source line")

    content_hash = _sha256(raw_fact)
    return {
        "content_sha256": content_hash,
        "fact_class": fact_class,
        "line": line,
        "owner_sha256": _sha256(owner),
        "redacted_identifier": f"fact-{content_hash[:16]}",
        "source_path_sha256": _sha256(source_path),
    }


def build_inventory(
    repo_root: Path | str,
    candidates: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Validate all candidates before returning any redacted output."""
    root = Path(repo_root).resolve()
    targets = tracked_text_targets(root)
    known_owners = known_instance_owners(root)
    records = [
        _validate_candidate(root, targets, known_owners, candidate)
        for candidate in candidates
    ]
    records.sort(
        key=lambda item: (
            item["source_path_sha256"],
            item["line"],
            item["fact_class"],
            item["redacted_identifier"],
        )
    )
    inventory = {
        "record_count": len(records),
        "records": records,
        "schema_version": 1,
        "target_count": len(targets),
        "target_source": "git-ls-files",
    }
    validate_inventory_artifact(inventory)
    return inventory


def _load_candidates(input_path: str) -> list[dict[str, Any]]:
    try:
        if input_path == "-":
            payload = json.load(sys.stdin)
        else:
            with Path(input_path).open(encoding="utf-8") as handle:
                payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryBlocked("candidate input must be valid JSON") from exc
    if not isinstance(payload, list) or not all(
        isinstance(item, dict) for item in payload
    ):
        raise InventoryBlocked("candidate input must be a JSON array of objects")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit a redacted instance-fact inventory as JSON."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
    )
    parser.add_argument(
        "--input",
        default="-",
        help="JSON candidate array path, or - for stdin",
    )
    args = parser.parse_args(argv)

    try:
        inventory = build_inventory(
            args.repo_root,
            _load_candidates(args.input),
        )
    except InventoryBlocked as exc:
        print(f"inventory blocked: {exc}", file=sys.stderr)
        return 2

    json.dump(inventory, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
