import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "instance-fact-inventory.py"
)


def load_inventory_module():
    spec = importlib.util.spec_from_file_location("instance_fact_inventory", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tracked_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    canonical = (
        tmp_path
        / "q-system"
        / "canonical"
        / "Synthetic-Client"
    )
    canonical.mkdir(parents=True)
    tracked = canonical / "discovery.md"
    tracked.write_text(
        "Synthetic Client paid $12,345\n",
        encoding="utf-8",
    )
    (tmp_path / "instance-registry.json").write_text(
        json.dumps(
            {
                "instances": [
                    {
                        "name": "investigations",
                        "path": "/synthetic/investigations",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [
            "git",
            "add",
            "instance-registry.json",
            "q-system/canonical/Synthetic-Client/discovery.md",
        ],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def candidate(**overrides):
    record = {
        "source_path": (
            "q-system/canonical/Synthetic-Client/discovery.md"
        ),
        "line": 1,
        "fact_class": "client",
        "owner": "investigations",
        "raw_fact": "Synthetic Client paid $12,345",
    }
    record.update(overrides)
    return record


def test_inventory_derives_targets_from_tracked_files(tracked_repo):
    inventory = load_inventory_module()
    result = inventory.build_inventory(tracked_repo, [candidate()])

    assert result["target_source"] == "git-ls-files"
    record = result["records"][0]
    assert len(record["source_path_sha256"]) == 64
    assert "source_path" not in record

    untracked = tracked_repo / "q-system" / "canonical" / "untracked.md"
    untracked.write_text(
        "Synthetic Client paid $12,345\n",
        encoding="utf-8",
    )
    with pytest.raises(inventory.InventoryBlocked, match="not a tracked text target"):
        inventory.build_inventory(
            tracked_repo,
            [candidate(source_path="q-system/canonical/untracked.md")],
        )


def test_raw_fact_is_replaced_by_hashes_and_redacted_identifier(tracked_repo):
    inventory = load_inventory_module()
    raw_fact = "Synthetic Client paid $12,345"
    result = inventory.build_inventory(
        tracked_repo,
        [candidate(raw_fact=raw_fact)],
    )

    encoded = json.dumps(result, sort_keys=True)
    assert raw_fact not in encoded
    assert "Synthetic Client" not in encoded
    assert "Synthetic-Client" not in encoded
    assert result["records"][0]["redacted_identifier"].startswith("fact-")
    assert len(result["records"][0]["content_sha256"]) == 64
    assert set(result["records"][0]) == {
        "content_sha256",
        "fact_class",
        "line",
        "owner_sha256",
        "redacted_identifier",
        "source_path_sha256",
    }


@pytest.mark.parametrize(
    "owner",
    ["", "unknown", "unknown_owner", "unassigned", "tbd", "made_up", None],
)
def test_unknown_owner_fails_closed_without_partial_output(tracked_repo, owner):
    inventory = load_inventory_module()

    with pytest.raises(inventory.InventoryBlocked, match="unknown owner"):
        inventory.build_inventory(
            tracked_repo,
            [candidate(), candidate(owner=owner, line=1)],
        )


def test_raw_fact_must_match_the_claimed_source_line(tracked_repo):
    inventory = load_inventory_module()

    with pytest.raises(inventory.InventoryBlocked, match="source line"):
        inventory.build_inventory(
            tracked_repo,
            [candidate(raw_fact="Unrelated synthetic fact")],
        )


def test_non_utf8_target_fails_as_a_controlled_non_target(tracked_repo):
    inventory = load_inventory_module()
    invalid = tracked_repo / "q-system" / "canonical" / "invalid.md"
    invalid.write_bytes(b"\xff\n")
    subprocess.run(
        ["git", "add", "q-system/canonical/invalid.md"],
        cwd=tracked_repo,
        check=True,
    )

    with pytest.raises(inventory.InventoryBlocked, match="not a tracked text target"):
        inventory.build_inventory(
            tracked_repo,
            [
                candidate(
                    source_path="q-system/canonical/invalid.md",
                    raw_fact="unreadable",
                )
            ],
        )


def test_uncontrolled_fields_cannot_copy_raw_fact_to_output(tracked_repo):
    inventory = load_inventory_module()

    with pytest.raises(inventory.InventoryBlocked, match="unexpected fields"):
        inventory.build_inventory(
            tracked_repo,
            [candidate(notes="Synthetic Client paid $12,345")],
        )
