import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
VERIFIER_PATH = (
    REPO_ROOT
    / "q-system/.q-system/scripts/verify-containment-export.py"
)
EXPECTED_FILES = (
    "q-system/canonical/discovery.md",
    "q-system/canonical/pricing-framework.md",
)


def load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_containment_export",
        VERIFIER_PATH,
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


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def export_layout(tmp_path):
    skeleton = tmp_path / "skeleton"
    owner = tmp_path / "owner"
    skeleton.mkdir()
    owner.mkdir()
    git(skeleton, "init")

    source_payloads = {
        "q-system/canonical/discovery.md": b"discovery facts\n",
        "q-system/canonical/pricing-framework.md": b"pricing facts\n",
    }
    for relative_path, raw in source_payloads.items():
        source = skeleton / relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(raw)
        destination = owner / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)

    registry = {
        "instances": [
            {
                "name": "investigations",
                "path": str(owner),
                "type": "subtree",
                "subtree_prefix": "q-system",
                "instance_q_dir": None,
                "has_git": True,
            }
        ]
    }
    (skeleton / "instance-registry.json").write_text(
        json.dumps(registry),
        encoding="utf-8",
    )
    git(skeleton, "add", ".")
    git(
        skeleton,
        "-c",
        "user.name=Containment Test",
        "-c",
        "user.email=containment@example.invalid",
        "commit",
        "-m",
        "fixture",
    )
    source_commit = git(skeleton, "rev-parse", "HEAD").stdout.strip()

    files = []
    for relative_path, raw in source_payloads.items():
        files.append(
            {
                "destination_path": relative_path,
                "destination_sha256": sha256(raw),
                "source_path": relative_path,
                "source_sha256": sha256(raw),
            }
        )
    receipt = {
        "files": files,
        "instance": "investigations",
        "owner_root": str(owner.resolve()),
        "schema_version": 1,
        "source_commit": source_commit,
    }
    receipt_path = (
        owner / "q-system/canonical/.containment-receipt.json"
    )
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    git(owner, "init")
    git(owner, "add", ".")
    git(
        owner,
        "-c",
        "user.name=Containment Test",
        "-c",
        "user.email=containment@example.invalid",
        "commit",
        "-m",
        "export fixture",
    )
    return skeleton, owner, receipt_path


def test_missing_destination_receipt_blocks_before_export(export_layout):
    verifier = load_verifier()
    skeleton, _, receipt_path = export_layout
    receipt_path.unlink()

    with pytest.raises(
        verifier.ContainmentBlocked,
        match="receipt",
    ):
        verifier.verify_export(skeleton, "investigations")


def test_complete_hash_matched_export_passes(export_layout):
    verifier = load_verifier()
    skeleton, _, _ = export_layout

    result = verifier.verify_export(
        skeleton,
        "investigations",
        require_hash_match=True,
    )

    assert result == {
        "file_count": 2,
        "instance": "investigations",
        "status": "verified",
    }


def test_destination_tamper_blocks(export_layout):
    verifier = load_verifier()
    skeleton, owner, _ = export_layout
    (owner / EXPECTED_FILES[0]).write_text(
        "changed after export\n",
        encoding="utf-8",
    )

    with pytest.raises(
        verifier.ContainmentBlocked,
        match="destination hash",
    ):
        verifier.verify_export(skeleton, "investigations")


def test_registry_owner_must_match_receipt(export_layout):
    verifier = load_verifier()
    skeleton, _, receipt_path = export_layout
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["owner_root"] = str((skeleton / "wrong-owner").resolve())
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(
        verifier.ContainmentBlocked,
        match="owner",
    ):
        verifier.verify_export(skeleton, "investigations")


def test_worktree_registry_redirect_cannot_change_owner(export_layout):
    verifier = load_verifier()
    skeleton, _, _ = export_layout
    attacker = skeleton / "attacker-owner"
    attacker.mkdir()
    registry_path = skeleton / "instance-registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["instances"][0]["path"] = str(attacker)
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    assert verifier.verify_export(
        skeleton,
        "investigations",
        require_hash_match=True,
    )["status"] == "verified"


def test_source_hash_must_match_recorded_commit(export_layout):
    verifier = load_verifier()
    skeleton, _, receipt_path = export_layout
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["files"][0]["source_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(
        verifier.ContainmentBlocked,
        match="source hash",
    ):
        verifier.verify_export(skeleton, "investigations")


def test_default_and_strict_modes_reject_transformed_destination(
    export_layout,
):
    verifier = load_verifier()
    skeleton, owner, receipt_path = export_layout
    destination = owner / EXPECTED_FILES[0]
    transformed = b"facts wrapped in another template\n"
    destination.write_bytes(transformed)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["files"][0]["destination_sha256"] = sha256(transformed)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(
        verifier.ContainmentBlocked,
        match="hash match",
    ):
        verifier.verify_export(skeleton, "investigations")
    with pytest.raises(
        verifier.ContainmentBlocked,
        match="hash match",
    ):
        verifier.verify_export(
            skeleton,
            "investigations",
            require_hash_match=True,
        )


def test_untrusted_source_commit_is_rejected(export_layout):
    verifier = load_verifier()
    skeleton, _, receipt_path = export_layout
    main_branch = git(
        skeleton,
        "branch",
        "--show-current",
    ).stdout.strip()
    git(skeleton, "switch", "-c", "untrusted-export")
    source = skeleton / EXPECTED_FILES[0]
    source.write_text("attacker source\n", encoding="utf-8")
    git(skeleton, "add", EXPECTED_FILES[0])
    git(
        skeleton,
        "-c",
        "user.name=Containment Test",
        "-c",
        "user.email=containment@example.invalid",
        "commit",
        "-m",
        "untrusted source",
    )
    untrusted_commit = git(skeleton, "rev-parse", "HEAD").stdout.strip()
    git(skeleton, "switch", main_branch)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["source_commit"] = untrusted_commit
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(
        verifier.ContainmentBlocked,
        match="trusted HEAD ancestor",
    ):
        verifier.verify_export(skeleton, "investigations")


def test_intermediate_symlink_cannot_escape_owner(export_layout):
    verifier = load_verifier()
    skeleton, owner, _ = export_layout
    canonical = owner / "q-system/canonical"
    outside = owner.parent / "outside-canonical"
    canonical.rename(outside)
    canonical.symlink_to(outside, target_is_directory=True)

    with pytest.raises(
        verifier.ContainmentBlocked,
        match="escapes",
    ):
        verifier.verify_export(skeleton, "investigations")


def test_receipt_and_export_must_match_owner_commit(export_layout):
    verifier = load_verifier()
    skeleton, _, receipt_path = export_layout
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["extra"] = "mutable"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(verifier.ContainmentBlocked):
        verifier.verify_export(skeleton, "investigations")
