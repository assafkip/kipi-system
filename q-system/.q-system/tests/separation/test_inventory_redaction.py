import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
INVENTORY_SCRIPT = (
    REPO_ROOT / "q-system/.q-system/scripts/instance-fact-inventory.py"
)
SCHEMA_PATH = (
    REPO_ROOT
    / "q-system/.q-system/schemas/containment-inventory.schema.json"
)
# ASK-608. These were restated literals that happened to match the schema
# exactly -- which is not reassurance, it is the setup for silent drift: the day
# the schema gains or loses a field, this file keeps asserting the old shape and
# passes while the contract has moved.
#
# Third instance of the same pattern in this suite, found by sweeping for it
# rather than by meeting it again. The other two were the fixture's helper list
# (a missing file aborted every run) and the rsync excludes (moved behind
# $(rsync_owned_excludes), read as zero excludes). The rule that falls out: if
# the shipping code owns a value, derive it; a copy in a test is a second source
# of truth that only ever agrees until it matters.
#
# Verified equal to the previous literals at the time of the change, so this is a
# refactor and not a quiet relaxation.
def _schema_fields():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    root = set(schema.get("properties", {}))
    records = set(
        schema.get("properties", {})
        .get("records", {})
        .get("items", {})
        .get("properties", {})
    )
    assert root, "schema declares no root properties; the derivation is broken"
    assert records, "schema declares no record properties; the derivation is broken"
    return root, records


ROOT_FIELDS, RECORD_FIELDS = _schema_fields()
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^fact-[0-9a-f]{16}$")


def load_inventory_module():
    spec = importlib.util.spec_from_file_location(
        "instance_fact_inventory",
        INVENTORY_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def inventory_output(tmp_path):
    git(tmp_path, "init")
    source_path = "q-system/canonical/discovery.md"
    raw_fact = "- **Client:** Cedar Observatory"
    source = tmp_path / source_path
    source.parent.mkdir(parents=True)
    source.write_text(raw_fact + "\n", encoding="utf-8")
    (tmp_path / "instance-registry.json").write_text(
        json.dumps(
            {
                "instances": [
                    {
                        "name": "investigations",
                        "path": "/not-persisted",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    git(tmp_path, "add", ".")
    inventory = load_inventory_module().build_inventory(
        tmp_path,
        [
            {
                "fact_class": "client",
                "line": 1,
                "owner": "investigations",
                "raw_fact": raw_fact,
                "source_path": source_path,
            }
        ],
    )
    return {
        "inventory": inventory,
        "owner": "investigations",
        "raw_fact": raw_fact,
        "repo_root": tmp_path,
        "source_path": source_path,
    }


def test_schema_is_an_exact_allowlist():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == ROOT_FIELDS
    assert set(schema["properties"]) == ROOT_FIELDS
    record_schema = schema["properties"]["records"]["items"]
    assert record_schema["type"] == "object"
    assert record_schema["additionalProperties"] is False
    assert set(record_schema["required"]) == RECORD_FIELDS
    assert set(record_schema["properties"]) == RECORD_FIELDS


def test_raw_payload_and_owner_never_persist(inventory_output):
    output = json.dumps(
        inventory_output["inventory"],
        sort_keys=True,
    )

    assert inventory_output["raw_fact"] not in output
    assert inventory_output["source_path"] not in output
    assert inventory_output["owner"] not in output
    assert set(inventory_output["inventory"]) == ROOT_FIELDS
    assert set(inventory_output["inventory"]["records"][0]) == RECORD_FIELDS


def test_real_inventory_output_matches_schema_constraints(inventory_output):
    inventory = inventory_output["inventory"]
    record = inventory["records"][0]

    assert inventory["schema_version"] == 1
    assert inventory["target_source"] == "git-ls-files"
    assert inventory["record_count"] == len(inventory["records"]) == 1
    assert isinstance(inventory["target_count"], int)
    assert inventory["target_count"] >= inventory["record_count"]
    assert record["fact_class"] in {
        "client",
        "interaction",
        "investigation",
        "pricing",
        "proof_gap",
        "prospect",
        "relationship",
    }
    assert isinstance(record["line"], int) and record["line"] >= 1
    for field in (
        "content_sha256",
        "owner_sha256",
        "source_path_sha256",
    ):
        assert HASH_RE.fullmatch(record[field])
    assert IDENTIFIER_RE.fullmatch(record["redacted_identifier"])


def test_raw_payload_fields_are_rejected_by_schema():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    record_properties = schema["properties"]["records"]["items"][
        "properties"
    ]

    assert {
        "owner",
        "raw_fact",
        "source",
        "source_path",
        "text",
        "value",
    }.isdisjoint(record_properties)


def test_raw_payload_artifact_is_rejected_by_producer(inventory_output):
    inventory_module = load_inventory_module()
    leaking = json.loads(
        json.dumps(inventory_output["inventory"])
    )
    leaking["records"][0]["raw_fact"] = inventory_output["raw_fact"]

    with pytest.raises(
        inventory_module.InventoryBlocked,
        match="forbidden persistence fields",
    ):
        inventory_module.validate_inventory_artifact(leaking)


def test_producer_blocks_when_schema_is_unavailable(
    inventory_output,
    tmp_path,
):
    inventory_module = load_inventory_module()

    with pytest.raises(
        inventory_module.InventoryBlocked,
        match="cannot load",
    ):
        inventory_module.validate_inventory_artifact(
            inventory_output["inventory"],
            tmp_path / "missing.schema.json",
        )


def test_schema_const_rejects_boolean_version(inventory_output):
    inventory_module = load_inventory_module()
    malformed = json.loads(json.dumps(inventory_output["inventory"]))
    malformed["schema_version"] = True

    with pytest.raises(
        inventory_module.InventoryBlocked,
        match="schema const",
    ):
        inventory_module.validate_inventory_artifact(malformed)


@pytest.mark.parametrize(
    "field",
    [
        "content_sha256",
        "owner_sha256",
        "source_path_sha256",
        "redacted_identifier",
    ],
)
def test_schema_patterns_reject_trailing_newline(
    inventory_output,
    field,
):
    inventory_module = load_inventory_module()
    malformed = json.loads(json.dumps(inventory_output["inventory"]))
    malformed["records"][0][field] += "\n"

    with pytest.raises(
        inventory_module.InventoryBlocked,
        match="schema pattern",
    ):
        inventory_module.validate_inventory_artifact(malformed)


def test_parseable_empty_schema_fails_closed(inventory_output, tmp_path):
    inventory_module = load_inventory_module()
    schema_path = tmp_path / "empty.schema.json"
    schema_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        inventory_module.InventoryBlocked,
        match="schema is malformed",
    ):
        inventory_module.validate_inventory_artifact(
            inventory_output["inventory"],
            schema_path,
        )


@pytest.mark.parametrize("attack", ["unknown_key", "fact_class"])
def test_rejected_candidate_values_never_reach_cli_output(
    inventory_output,
    tmp_path,
    capsys,
    attack,
):
    inventory_module = load_inventory_module()
    secret = "RAW-OWNER-SOURCE-SECRET"
    candidate = {
        "fact_class": "client",
        "line": 1,
        "owner": inventory_output["owner"],
        "raw_fact": inventory_output["raw_fact"],
        "source_path": inventory_output["source_path"],
    }
    if attack == "unknown_key":
        candidate[secret] = "value"
    else:
        candidate["fact_class"] = secret
    candidate_path = tmp_path / f"{attack}.json"
    candidate_path.write_text(
        json.dumps([candidate]),
        encoding="utf-8",
    )

    result = inventory_module.main(
        [
            "--repo-root",
            str(inventory_output["repo_root"]),
            "--input",
            str(candidate_path),
        ]
    )
    captured = capsys.readouterr()

    assert result == 2
    assert secret not in captured.out
    assert secret not in captured.err
