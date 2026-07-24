#!/usr/bin/env python3
"""Executable contract tests for registry-derived updater ownership."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "instance-ownership-contract.json"
)
UPDATER_PATH = REPO_ROOT / "kipi-update.sh"
REGISTRY_PATH = REPO_ROOT / "instance-registry.json"
VALID_CLASSES = {"generic_managed", "preserved_state", "instance_automation"}
VALID_KINDS = {"directory", "file", "repository", "selection"}
VALID_PLACEHOLDERS = {"{managed_root}", "{state_root}"}


def load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def validate_relative_path(value: str, *, allow_repository_root: bool = False) -> None:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or value == ""
        or (value == "." and not allow_repository_root)
    ):
        raise ValueError(f"unsafe contract path: {value!r}")


def validate_contract(contract: dict) -> None:
    if set(contract) != {
        "schema_version",
        "registry_contract",
        "ownership_classes",
        "managed_destinations",
        "preserved_state",
        "instance_automation",
    }:
        raise ValueError("contract has missing or unknown top-level keys")
    if contract["schema_version"] != 1:
        raise ValueError("unsupported ownership contract version")
    if set(contract["ownership_classes"]) != VALID_CLASSES:
        raise ValueError("ownership classes are incomplete")

    records = [
        *contract["managed_destinations"],
        *contract["preserved_state"],
    ]
    ids: set[str] = set()
    for record in records:
        if record.get("id") in ids:
            raise ValueError(f"duplicate destination id: {record.get('id')}")
        ids.add(record.get("id"))
        if record.get("class") not in VALID_CLASSES:
            raise ValueError(f"unclassified destination: {record.get('id')}")
        if record.get("kind") not in VALID_KINDS:
            raise ValueError(f"unknown destination kind: {record.get('id')}")
        rendered = record.get("path")
        if not isinstance(rendered, str):
            raise ValueError(f"missing destination path: {record.get('id')}")
        probe = rendered
        for placeholder in VALID_PLACEHOLDERS:
            probe = probe.replace(placeholder, "fixture")
        if "{" in probe or "}" in probe:
            raise ValueError(f"unknown path placeholder: {rendered}")
        validate_relative_path(
            probe, allow_repository_root=record["kind"] == "repository"
        )
        if record["class"] == "generic_managed":
            if not record.get("selection") or not record.get("updater_marker"):
                raise ValueError(
                    f"generic destination lacks executable boundary: {record['id']}"
                )

    automation = contract["instance_automation"]
    if automation.get("class") != "instance_automation":
        raise ValueError("instance automation is unclassified")
    if automation.get("kind") != "selection":
        raise ValueError("instance automation must be a selection")
    if not automation.get("selection"):
        raise ValueError("instance automation selection is missing")
    for template in automation.get("paths", []):
        probe = template
        for placeholder in VALID_PLACEHOLDERS:
            probe = probe.replace(placeholder, "fixture")
        validate_relative_path(probe)
    if automation.get("applies_to") != ["subtree"]:
        raise ValueError("instance automation scope must match updater preservation")

    for preserved in contract["preserved_state"]:
        if preserved.get("applies_to") != ["subtree"]:
            raise ValueError(
                f"preserved state has unsupported updater type: {preserved['id']}"
            )

    for destination in contract["managed_destinations"]:
        applies_to = destination.get("applies_to")
        if not isinstance(applies_to, list) or not applies_to:
            raise ValueError(f"destination has no registry types: {destination['id']}")
        unknown = set(applies_to) - set(
            contract["registry_contract"]["managed_types"]
        )
        if unknown:
            raise ValueError(
                f"destination {destination['id']} has unknown types: {unknown}"
            )


def resolve_layout(contract: dict, instance: dict) -> dict | None:
    registry = contract["registry_contract"]
    instance_type = instance.get("type", "subtree")
    managed_root = instance.get(registry["managed_root_field"])
    state_root = instance.get(registry["state_root_field"])

    if instance_type not in registry["managed_types"]:
        if instance_type == registry["standalone_type"]:
            return None
        raise ValueError(f"unknown instance type: {instance_type}")
    if not managed_root:
        return None
    validate_relative_path(managed_root)
    if not state_root:
        state_root = managed_root
    validate_relative_path(state_root)
    return {
        "instance_type": instance_type,
        "managed_root": managed_root,
        "state_root": state_root,
    }


def render_path(
    template: str, layout: dict, *, allow_repository_root: bool = False
) -> str:
    value = template.format(
        managed_root=layout["managed_root"],
        state_root=layout["state_root"],
    )
    validate_relative_path(
        value, allow_repository_root=allow_repository_root
    )
    return value


def enumerate_paths(contract: dict, instance: dict) -> list[dict]:
    layout = resolve_layout(contract, instance)
    if layout is None:
        return []
    records: list[dict] = []
    for destination in contract["managed_destinations"]:
        if layout["instance_type"] in destination["applies_to"]:
            records.append(
                {
                    **destination,
                    "path": render_path(
                        destination["path"],
                        layout,
                        allow_repository_root=destination["kind"]
                        == "repository",
                    ),
                }
            )
    for preserved in contract["preserved_state"]:
        if layout["instance_type"] in preserved["applies_to"]:
            records.append(
                {
                    **preserved,
                    "path": render_path(preserved["path"], layout),
                }
            )
    automation = contract["instance_automation"]
    if layout["instance_type"] in automation["applies_to"]:
        for template in automation["paths"]:
            records.append(
                {
                    **automation,
                    "path": render_path(template, layout),
                }
            )
    return records


def path_is_within(candidate: str, root: str) -> bool:
    if root == ".":
        return True
    candidate_path = PurePosixPath(candidate)
    root_path = PurePosixPath(root)
    return candidate_path == root_path or root_path in candidate_path.parents


def classify_path(
    contract: dict,
    instance: dict,
    candidate: str,
    *,
    origin_changed_paths: set[str] | None = None,
) -> str | None:
    validate_relative_path(candidate)
    records = enumerate_paths(contract, instance)

    for record in records:
        if record["class"] == "preserved_state" and path_is_within(
            candidate, record["path"]
        ):
            return "preserved_state"
    for record in records:
        if record["class"] == "generic_managed" and generic_selects(
            record, candidate, origin_changed_paths=origin_changed_paths
        ):
            return "generic_managed"
    for record in records:
        if record["kind"] == "selection" and path_is_within(
            candidate, record["path"]
        ):
            relative = PurePosixPath(candidate).relative_to(record["path"])
            relative_text = relative.as_posix()
            if (
                relative_text == "q-system"
                or relative_text.startswith("q-system/")
                or relative_text.endswith(".pyc")
                or "__pycache__" in relative.parts
            ):
                return None
            return "instance_automation"
    return None


def skeleton_ever_tracked(candidate: str) -> bool:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "log",
            "--all",
            "--format=%H",
            "-1",
            "--",
            candidate,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(result.stdout.strip())


def generic_selects(
    record: dict,
    candidate: str,
    *,
    origin_changed_paths: set[str] | None,
) -> bool:
    if record["kind"] == "repository":
        return candidate in (origin_changed_paths or set())
    if record["kind"] == "file":
        return candidate == record["path"] and (REPO_ROOT / candidate).is_file()
    if not path_is_within(candidate, record["path"]):
        return False
    selection = record["selection"]
    if selection == "skeleton_archive_contents":
        return (REPO_ROOT / candidate).exists() or skeleton_ever_tracked(candidate)
    if selection == "skeleton_matching_markdown":
        return candidate.endswith(".md") and (REPO_ROOT / candidate).is_file()
    if selection == "skeleton_present_plugin_directories":
        parts = PurePosixPath(candidate).parts
        return len(parts) > 1 and (REPO_ROOT / parts[0] / parts[1]).is_dir()
    raise ValueError(f"unknown generic selection: {selection}")


def updater_config_targets(source: str) -> set[str]:
    targets: set[str] = set()
    for raw in re.findall(r'["\']\$(?:path|\{path\})/([^"\']+)', source):
        normalized = raw.rstrip("/")
        if "$" in normalized and not normalized.startswith("plugins/"):
            continue
        if normalized == ".claude":
            continue
        if normalized.startswith("plugins/"):
            normalized = "plugins"
        if (
            normalized == "plugins"
            or normalized.startswith(".claude/")
            or (
                normalized.startswith(".")
                and not normalized.startswith(".git")
            )
        ):
            targets.add(normalized)
    return targets


class OwnershipContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_contract()

    def test_contract_is_closed_and_versioned(self) -> None:
        validate_contract(self.contract)

    def test_default_layout_enumerates_every_owned_state_class(self) -> None:
        fixture = {
            "type": "subtree",
            "subtree_prefix": "q-system",
            "instance_q_dir": None,
        }
        records = enumerate_paths(self.contract, fixture)
        classes = {record["class"] for record in records}
        self.assertEqual(classes, VALID_CLASSES)
        preserved = {
            record["path"]
            for record in records
            if record["class"] == "preserved_state"
        }
        self.assertEqual(
            preserved,
            {
                "q-system/canonical",
                "q-system/my-project",
                "q-system/memory",
                "q-system/output",
                "q-system/.q-system/agent-pipeline/bus",
            },
        )

    def test_custom_state_root_is_registry_derived(self) -> None:
        fixture = {
            "type": "subtree",
            "subtree_prefix": "q-system",
            "instance_q_dir": "q-client",
        }
        self.assertEqual(
            classify_path(
                self.contract,
                fixture,
                "q-client/canonical/private.md",
            ),
            "preserved_state",
        )
        self.assertEqual(
            classify_path(
                self.contract,
                fixture,
                "q-system/.q-system/custom-job.py",
            ),
            "instance_automation",
        )

    def test_tracked_and_untracked_automation_share_one_owner_class(self) -> None:
        fixture = {
            "type": "subtree",
            "subtree_prefix": "q-system",
            "instance_q_dir": None,
        }
        for candidate in (
            "q-system/.q-system/scripts/instance-tracked.py",
            "q-system/sources/untracked-input.json",
        ):
            self.assertEqual(
                classify_path(
                    self.contract,
                    fixture,
                    candidate,
                ),
                "instance_automation",
            )

    def test_skeleton_present_path_is_generic_not_automation(self) -> None:
        fixture = {
            "type": "subtree",
            "subtree_prefix": "q-system",
            "instance_q_dir": None,
        }
        candidate = "q-system/.q-system/scripts/capability-gate.py"
        self.assertEqual(
            classify_path(
                self.contract,
                fixture,
                candidate,
            ),
            "generic_managed",
        )

    def test_null_prefix_is_valid_only_for_standalone(self) -> None:
        standalone = {
            "type": "standalone",
            "subtree_prefix": None,
            "instance_q_dir": None,
        }
        self.assertEqual(enumerate_paths(self.contract, standalone), [])
        managed = {**standalone, "type": "subtree"}
        self.assertEqual(enumerate_paths(self.contract, managed), [])

    def test_direct_clone_has_no_q_root_replace_destination(self) -> None:
        fixture = {
            "type": "direct-clone",
            "subtree_prefix": "q-system",
            "instance_q_dir": None,
        }
        ids = {record["id"] for record in enumerate_paths(self.contract, fixture)}
        self.assertIn("direct-repository-pull", ids)
        self.assertNotIn("q-root-sync", ids)
        self.assertIn("plugins", ids)
        self.assertNotIn("managed-root-canonical", ids)
        self.assertEqual(
            classify_path(
                self.contract,
                fixture,
                "q-system/runtime.py",
                origin_changed_paths={"q-system/runtime.py"},
            ),
            "generic_managed",
        )

    def test_new_destination_without_classification_fails(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["managed_destinations"].append(
            {
                "id": "new-surface",
                "path": ".claude/new-surface",
                "kind": "directory",
                "operation": "copy",
                "applies_to": ["subtree"],
            }
        )
        with self.assertRaisesRegex(ValueError, "unclassified destination"):
            validate_contract(broken)

    def test_unknown_destination_is_not_silently_generic(self) -> None:
        fixture = {
            "type": "subtree",
            "subtree_prefix": "q-system",
            "instance_q_dir": None,
        }
        self.assertIsNone(
            classify_path(
                self.contract,
                fixture,
                ".claude/new-surface/file.md",
            )
        )

    def test_live_registry_variants_resolve_from_contract(self) -> None:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        known_types = {
            *self.contract["registry_contract"]["managed_types"],
            self.contract["registry_contract"]["standalone_type"],
        }
        self.assertTrue(registry["instances"])
        for instance in registry["instances"]:
            self.assertIn(instance.get("type", "subtree"), known_types)
            enumerate_paths(self.contract, instance)
        custom = [
            instance
            for instance in registry["instances"]
            if instance.get("instance_q_dir")
        ]
        self.assertTrue(custom)
        for instance in custom:
            preserved = {
                record["path"]
                for record in enumerate_paths(self.contract, instance)
                if record["class"] == "preserved_state"
            }
            for suffix in (
                "canonical",
                "my-project",
                "memory",
                "output",
                ".q-system/agent-pipeline/bus",
            ):
                self.assertIn(
                    f"{instance['subtree_prefix']}/{suffix}", preserved
                )
                self.assertIn(
                    f"{instance['instance_q_dir']}/{suffix}", preserved
                )

    def test_contract_covers_live_updater_config_destinations(self) -> None:
        updater = UPDATER_PATH.read_text(encoding="utf-8")
        destinations = {
            record["path"]
            for record in self.contract["managed_destinations"]
            if record["path"].startswith(".claude/")
            or record["path"] == "plugins"
        }
        self.assertEqual(updater_config_targets(updater), destinations)
        for record in self.contract["managed_destinations"]:
            self.assertIn(record["updater_marker"], updater)

    def test_new_updater_destination_is_detected(self) -> None:
        updater = UPDATER_PATH.read_text(encoding="utf-8")
        destinations = {
            record["path"]
            for record in self.contract["managed_destinations"]
            if record["path"].startswith(".claude/")
            or record["path"] == "plugins"
        }
        for probe in (
            'mkdir -p "$path/.claude/new-surface"',
            'mkdir -p "$path/.codex/agents"',
            'mkdir -p "${path}/.claude/new-surface"',
        ):
            self.assertNotEqual(
                updater_config_targets(f"{updater}\n{probe}\n"),
                destinations,
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--unclassified-must-fail",
        action="store_true",
        help="run the same suite with the explicit bypass assertion enabled",
    )
    args = parser.parse_args()
    if args.unclassified_must_fail:
        contract = load_contract()
        contract["managed_destinations"].append(
            {
                "id": "bypass-probe",
                "path": "new-destination",
                "kind": "directory",
                "operation": "copy",
                "applies_to": ["subtree"],
            }
        )
        try:
            validate_contract(contract)
        except ValueError:
            pass
        else:
            print("FAIL: unclassified destination passed validation", file=sys.stderr)
            return 1
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        OwnershipContractTests
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
