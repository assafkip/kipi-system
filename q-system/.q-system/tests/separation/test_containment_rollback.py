import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "verify-containment-export.py"
)


def load_export_module():
    spec = importlib.util.spec_from_file_location(
        "verify_containment_export",
        SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wrong_owner_rollback_retains_payload_only_in_quarantine(tmp_path):
    containment = load_export_module()
    generic_root = tmp_path / "skeleton"
    generic_file = generic_root / "q-system" / "canonical" / "discovery.md"
    generic_file.parent.mkdir(parents=True)
    generic_file.write_text("# Generic template\n", encoding="utf-8")
    before = generic_file.read_bytes()
    raw_payload = b"Synthetic Client paid $12,345"
    quarantine = tmp_path / "protected-quarantine"

    receipt = containment.retain_after_failed_owner_check(
        raw_payload=raw_payload,
        claimed_owner="wrong-owner",
        expected_owner="investigations",
        quarantine_root=quarantine,
        generic_roots=[generic_root],
    )

    assert generic_file.read_bytes() == before
    retained = list(quarantine.iterdir())
    assert len(retained) == 1
    assert retained[0].read_bytes() == raw_payload
    assert stat.S_IMODE(quarantine.stat().st_mode) == 0o700
    assert stat.S_IMODE(retained[0].stat().st_mode) == 0o600
    assert raw_payload.decode() not in json.dumps(receipt, sort_keys=True)
    assert all(
        raw_payload not in path.read_bytes()
        for path in generic_root.rglob("*")
        if path.is_file()
    )


def test_never_republish_quarantine_inside_generic_path(tmp_path):
    containment = load_export_module()
    generic_root = tmp_path / "skeleton"
    generic_root.mkdir()

    with pytest.raises(
        containment.ContainmentBlocked,
        match="outside generic roots",
    ):
        containment.retain_after_failed_owner_check(
            raw_payload=b"Synthetic raw fact",
            claimed_owner="wrong-owner",
            expected_owner="investigations",
            quarantine_root=generic_root / "q-system" / "quarantine",
            generic_roots=[generic_root],
        )

    assert not (generic_root / "q-system" / "quarantine").exists()


def test_never_republish_rejects_verified_owner_path(tmp_path):
    containment = load_export_module()

    with pytest.raises(
        containment.ContainmentBlocked,
        match="owner check did not fail",
    ):
        containment.retain_after_failed_owner_check(
            raw_payload=b"Synthetic raw fact",
            claimed_owner="investigations",
            expected_owner="investigations",
            quarantine_root=tmp_path / "protected-quarantine",
            generic_roots=[tmp_path / "skeleton"],
        )


def test_never_republish_rejects_empty_payload(tmp_path):
    containment = load_export_module()

    with pytest.raises(containment.ContainmentBlocked, match="empty payload"):
        containment.retain_after_failed_owner_check(
            raw_payload=b"",
            claimed_owner="wrong-owner",
            expected_owner="investigations",
            quarantine_root=tmp_path / "protected-quarantine",
            generic_roots=[tmp_path / "skeleton"],
        )


def test_never_republish_rejects_empty_generic_roots(tmp_path):
    containment = load_export_module()

    with pytest.raises(
        containment.ContainmentBlocked,
        match="generic roots are required",
    ):
        containment.retain_after_failed_owner_check(
            raw_payload=b"Synthetic raw fact",
            claimed_owner="wrong-owner",
            expected_owner="investigations",
            quarantine_root=tmp_path / "protected-quarantine",
            generic_roots=[],
        )


def test_never_republish_rejects_existing_payload_symlink(tmp_path):
    containment = load_export_module()
    raw_payload = b"Synthetic raw fact"
    quarantine = tmp_path / "protected-quarantine"
    quarantine.mkdir(mode=0o700)
    external = tmp_path / "external.payload"
    external.write_bytes(raw_payload)
    payload_hash = containment._sha256(raw_payload)
    (quarantine / f"{payload_hash}.payload").symlink_to(external)

    with pytest.raises(
        containment.ContainmentBlocked,
        match="existing quarantine payload",
    ):
        containment.retain_after_failed_owner_check(
            raw_payload=raw_payload,
            claimed_owner="wrong-owner",
            expected_owner="investigations",
            quarantine_root=quarantine,
            generic_roots=[tmp_path / "skeleton"],
        )

    assert external.read_bytes() == raw_payload


def test_partial_write_is_removed_and_retry_can_succeed(tmp_path, monkeypatch):
    containment = load_export_module()
    raw_payload = b"Synthetic raw fact"
    quarantine = tmp_path / "protected-quarantine"
    real_write_all = containment._write_all

    def fail_after_partial_write(descriptor, payload):
        os.write(descriptor, payload[:4])
        raise OSError("synthetic write failure")

    monkeypatch.setattr(containment, "_write_all", fail_after_partial_write)
    with pytest.raises(
        containment.ContainmentBlocked,
        match="cannot retain quarantine payload",
    ):
        containment.retain_after_failed_owner_check(
            raw_payload=raw_payload,
            claimed_owner="wrong-owner",
            expected_owner="investigations",
            quarantine_root=quarantine,
            generic_roots=[tmp_path / "skeleton"],
        )

    assert list(quarantine.iterdir()) == []

    monkeypatch.setattr(containment, "_write_all", real_write_all)
    containment.retain_after_failed_owner_check(
        raw_payload=raw_payload,
        claimed_owner="wrong-owner",
        expected_owner="investigations",
        quarantine_root=quarantine,
        generic_roots=[tmp_path / "skeleton"],
    )
    assert len(list(quarantine.iterdir())) == 1
