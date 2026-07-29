#!/usr/bin/env python3
"""Dependency-free producer and consumer tests for updater receipts."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import sys
import unittest


SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "updater-receipt.schema.json"
HASH = "a" * 64
HEAD = "b" * 40


class ContractError(ValueError):
    pass


def json_equal(left: object, right: object) -> bool:
    return type(left) is type(right) and left == right


def resolve_ref(root: dict, reference: str) -> dict:
    if not reference.startswith("#/"):
        raise ContractError(f"external reference is forbidden: {reference}")
    value = root
    for part in reference[2:].split("/"):
        value = value[part]
    return value


def validate(value: object, rule: dict, root: dict, location: str = "$") -> None:
    if "$ref" in rule:
        validate(value, resolve_ref(root, rule["$ref"]), root, location)
        return
    if "anyOf" in rule:
        errors = []
        for option in rule["anyOf"]:
            try:
                validate(value, option, root, location)
                return
            except ContractError as error:
                errors.append(str(error))
        raise ContractError(f"{location} matches no allowed shape: {errors}")
    if "oneOf" in rule:
        matches = 0
        for option in rule["oneOf"]:
            try:
                validate(value, option, root, location)
                matches += 1
            except ContractError:
                pass
        if matches != 1:
            raise ContractError(f"{location} must match exactly one allowed shape")
        return
    for constraint in rule.get("allOf", []):
        validate(value, constraint, root, location)
    if "if" in rule:
        try:
            validate(value, rule["if"], root, location)
        except ContractError:
            if "else" in rule:
                validate(value, rule["else"], root, location)
        else:
            if "then" in rule:
                validate(value, rule["then"], root, location)
    expected = rule.get("type")
    type_matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }
    if expected and not type_matches[expected]:
        raise ContractError(f"{location} must be {expected}")
    if "const" in rule and not json_equal(value, rule["const"]):
        raise ContractError(f"{location} must equal {rule['const']!r}")
    if "enum" in rule and not any(json_equal(value, item) for item in rule["enum"]):
        raise ContractError(f"{location} is not in the closed enum")
    if isinstance(value, str):
        if len(value) < rule.get("minLength", 0):
            raise ContractError(f"{location} is too short")
        if "pattern" in rule and re.search(rule["pattern"], value) is None:
            raise ContractError(f"{location} does not match {rule['pattern']}")
    if isinstance(value, list) and "items" in rule:
        for index, item in enumerate(value):
            validate(item, rule["items"], root, f"{location}[{index}]")
    if isinstance(value, dict):
        if len(value) < rule.get("minProperties", 0):
            raise ContractError(f"{location} has too few properties")
        if "maxProperties" in rule and len(value) > rule["maxProperties"]:
            raise ContractError(f"{location} has too many properties")
        properties = rule.get("properties", {})
        missing = set(rule.get("required", [])) - set(value)
        if missing:
            raise ContractError(f"{location} is missing {sorted(missing)}")
        if rule.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise ContractError(f"{location} has unknown keys {sorted(unknown)}")
        if "propertyNames" in rule:
            for key in value:
                validate(key, rule["propertyNames"], root, f"{location}.<key>")
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], root, f"{location}.{key}")
            elif isinstance(rule.get("additionalProperties"), dict):
                validate(
                    item,
                    rule["additionalProperties"],
                    root,
                    f"{location}.{key}",
                )


def consume(receipt: dict, schema: dict) -> None:
    """Apply schema checks plus cross-field rollback preconditions."""
    validate(receipt, schema, schema)
    rollback = receipt["rollback"]
    if rollback["eligible"]:
        if rollback["required_head"] != receipt["after"]["head"]:
            raise ContractError("rollback required HEAD must equal after HEAD")
        if (
            rollback["required_worktree_sha256"]
            != receipt["after"]["worktree_sha256"]
        ):
            raise ContractError(
                "rollback required worktree hash must equal after worktree hash"
            )
    if receipt["producer"] == "rollback" and not rollback["target_receipt_id"]:
        raise ContractError("rollback producer must identify its target receipt")


def updater_receipt() -> dict:
    return {
        "schema_version": 1,
        "receipt_id": "ur-0123456789abcdef",
        "producer": "updater",
        "instance": {
            "name": "fixture",
            "path": "/tmp/fixture",
            "type": "subtree",
        },
        "mode": "apply",
        "phase": "complete",
        "status": "complete",
        "created_at": "2026-07-25T00:00:00Z",
        "before": {"head": HEAD, "worktree_sha256": HASH},
        "after": {"head": "c" * 40, "worktree_sha256": "d" * 64},
        "changes": {
            "q-system/runtime.py": {
                "operation": "update",
                "before_sha256": HASH,
                "after_sha256": "d" * 64,
            }
        },
        "rollback": {
            "eligible": True,
            "target_receipt_id": None,
            "required_head": "c" * 40,
            "required_worktree_sha256": "d" * 64,
            "refusal_reason": None,
            "recovery_artifact": {
                "kind": "snapshot",
                "path": "/tmp/receipts/fixture.tar",
                "sha256": "e" * 64,
            },
        },
    }


def rollback_receipt() -> dict:
    receipt = updater_receipt()
    receipt.update(
        {
            "receipt_id": "ur-fedcba9876543210",
            "producer": "rollback",
            "mode": "rollback",
            "phase": "rollback",
        }
    )
    receipt["rollback"] = {
        "eligible": False,
        "target_receipt_id": "ur-0123456789abcdef",
        "required_head": None,
        "required_worktree_sha256": None,
        "refusal_reason": "receipt consumed",
        "recovery_artifact": None,
    }
    return receipt


def preservation_receipt() -> dict:
    receipt = updater_receipt()
    receipt.update(
        {
            "receipt_id": "ur-1111111111111111",
            "producer": "preservation-helper",
            "phase": "restore",
            "mode": "rollback",
        }
    )
    receipt["rollback"] = {
        "eligible": False,
        "target_receipt_id": None,
        "required_head": None,
        "required_worktree_sha256": None,
        "refusal_reason": "helper receipt is not a rollback target",
        "recovery_artifact": None,
    }
    return receipt


class ReceiptContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    def assert_invalid(self, receipt: dict) -> None:
        with self.assertRaises(ContractError):
            consume(receipt, self.schema)

    def test_schema_is_closed_and_versioned(self) -> None:
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(self.schema["properties"]["schema_version"]["const"], 1)

    def test_updater_producer_matches_shared_consumer(self) -> None:
        consume(updater_receipt(), self.schema)

    def test_rollback_producer_matches_shared_consumer(self) -> None:
        consume(rollback_receipt(), self.schema)

    def test_preservation_restore_matches_shared_consumer(self) -> None:
        consume(preservation_receipt(), self.schema)

    def test_unknown_version_is_rejected(self) -> None:
        for invalid in (2, True):
            with self.subTest(invalid=invalid):
                receipt = updater_receipt()
                receipt["schema_version"] = invalid
                self.assert_invalid(receipt)

    def test_path_hash_phase_mode_and_rollback_are_locked(self) -> None:
        mutations = [
            (
                "unsafe path",
                lambda item: item.update(
                    changes={".": next(iter(item["changes"].values()))}
                ),
            ),
            (
                "repeated separator",
                lambda item: item.update(
                    changes={"q-system//x": next(iter(item["changes"].values()))}
                ),
            ),
            ("short hash", lambda item: item["before"].update(worktree_sha256="bad")),
            ("unknown phase", lambda item: item.update(phase="mystery")),
            ("unknown mode", lambda item: item.update(mode="preview")),
            (
                "create has before hash",
                lambda item: item["changes"]["q-system/runtime.py"].update(
                    operation="create"
                ),
            ),
            (
                "eligible missing artifact",
                lambda item: item["rollback"].update(recovery_artifact=None),
            ),
            (
                "eligible missing worktree guard",
                lambda item: item["rollback"].update(
                    required_worktree_sha256=None
                ),
            ),
            (
                "eligible stale worktree guard",
                lambda item: item["rollback"].update(
                    required_worktree_sha256="f" * 64
                ),
            ),
            (
                "eligible stale HEAD guard",
                lambda item: item["rollback"].update(required_head="f" * 40),
            ),
            (
                "boolean encoded as integer",
                lambda item: item["rollback"].update(eligible=1),
            ),
            (
                "eligible has refusal",
                lambda item: item["rollback"].update(refusal_reason="later edit"),
            ),
            ("missing rollback", lambda item: item.pop("rollback")),
            ("unknown field", lambda item: item.update(extra=True)),
        ]
        for label, mutate in mutations:
            with self.subTest(label=label):
                receipt = copy.deepcopy(updater_receipt())
                mutate(receipt)
                self.assert_invalid(receipt)

    def test_producer_mode_contract_is_isolated(self) -> None:
        receipt = rollback_receipt()
        receipt["mode"] = "apply"
        self.assert_invalid(receipt)

    def test_pre_mutation_failure_can_have_no_changes(self) -> None:
        receipt = updater_receipt()
        receipt.update(status="failed", changes={})
        receipt["rollback"] = {
            "eligible": False,
            "target_receipt_id": None,
            "required_head": None,
            "required_worktree_sha256": None,
            "refusal_reason": "preservation failed before mutation",
            "recovery_artifact": None,
        }
        consume(receipt, self.schema)

    def test_mode_change_locks_content_and_permission_bits(self) -> None:
        receipt = updater_receipt()
        receipt["changes"] = {
            "q-system/run.sh": {
                "operation": "mode-change",
                "content_sha256": HASH,
                "before_mode": "0644",
                "after_mode": "0755",
            }
        }
        consume(receipt, self.schema)
        receipt["changes"]["q-system/run.sh"]["after_mode"] = "755"
        self.assert_invalid(receipt)

    def test_skipped_receipt_must_be_empty_and_ineligible(self) -> None:
        receipt = updater_receipt()
        receipt.update(status="skipped", changes={})
        receipt["rollback"] = {
            "eligible": False,
            "target_receipt_id": None,
            "required_head": None,
            "required_worktree_sha256": None,
            "refusal_reason": "no changes",
            "recovery_artifact": None,
        }
        consume(receipt, self.schema)
        receipt["changes"] = updater_receipt()["changes"]
        self.assert_invalid(receipt)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--producer-consumer-mismatch", action="store_true")
    args = parser.parse_args()
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    if args.producer_consumer_mismatch:
        mismatch = updater_receipt()
        mismatch["schema_version"] = 999
        try:
            consume(mismatch, schema)
        except ContractError:
            pass
        else:
            print("FAIL: producer-consumer version mismatch was accepted", file=sys.stderr)
            return 1
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ReceiptContractTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
