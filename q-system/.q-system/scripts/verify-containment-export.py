#!/usr/bin/env python3
"""Verify containment exports and retain failed-owner payloads safely."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from pathlib import Path
from typing import Iterable


class ContainmentBlocked(ValueError):
    """Raised when containment cannot preserve the separation boundary."""


EXPECTED_EXPORT_PATHS = (
    "q-system/canonical/discovery.md",
    "q-system/canonical/pricing-framework.md",
)
RECEIPT_RELATIVE_PATH = (
    "q-system/canonical/.containment-receipt.json"
)
RECEIPT_KEYS = {
    "files",
    "instance",
    "owner_root",
    "schema_version",
    "source_commit",
}
FILE_RECEIPT_KEYS = {
    "destination_path",
    "destination_sha256",
    "source_path",
    "source_sha256",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40,64}")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _resolved(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_quarantine_location(
    quarantine_root: Path,
    generic_roots: Iterable[Path | str],
) -> None:
    for generic_root in generic_roots:
        if _inside(quarantine_root, _resolved(generic_root)):
            raise ContainmentBlocked(
                "protected quarantine must stay outside generic roots"
            )


def _validate_parent_control(quarantine_root: Path) -> None:
    try:
        parent_stat = quarantine_root.parent.stat()
    except OSError as exc:
        raise ContainmentBlocked("cannot verify quarantine parent") from exc
    if parent_stat.st_uid != os.geteuid() or stat.S_IMODE(
        parent_stat.st_mode
    ) & 0o022:
        raise ContainmentBlocked(
            "quarantine parent must be owner-controlled"
        )


def _open_quarantine_directory(
    quarantine_root: Path,
) -> int:
    quarantine_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        directory_fd = os.open(quarantine_root, flags)
    except OSError as exc:
        raise ContainmentBlocked("cannot open protected quarantine") from exc

    try:
        opened = os.fstat(directory_fd)
        current = os.stat(quarantine_root, follow_symlinks=False)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (current.st_dev, current.st_ino)
        ):
            raise ContainmentBlocked("quarantine directory identity changed")
        os.fchmod(directory_fd, 0o700)
    except ContainmentBlocked:
        os.close(directory_fd)
        raise
    except OSError as exc:
        os.close(directory_fd)
        raise ContainmentBlocked(
            "cannot verify protected quarantine"
        ) from exc
    return directory_fd


def _write_all(descriptor: int, raw_payload: bytes) -> None:
    remaining = memoryview(raw_payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written < 1:
            raise OSError("zero-byte quarantine write")
        remaining = remaining[written:]
    os.fsync(descriptor)


def _read_existing_payload(
    directory_fd: int,
    filename: str,
    raw_payload: bytes,
) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(filename, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise ContainmentBlocked(
            "cannot verify existing quarantine payload"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise ContainmentBlocked(
                "existing quarantine payload is not a private file"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            retained = handle.read()
        if retained != raw_payload:
            raise ContainmentBlocked(
                "existing quarantine payload failed hash identity"
            )
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def _write_protected_payload(
    directory_fd: int,
    raw_payload: bytes,
) -> str:
    payload_hash = _sha256(raw_payload)
    filename = f"{payload_hash}.payload"
    temporary = f".{payload_hash}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        descriptor = os.open(
            temporary,
            flags,
            0o600,
            dir_fd=directory_fd,
        )
    except OSError as exc:
        raise ContainmentBlocked("cannot create quarantine payload") from exc

    try:
        _write_all(descriptor, raw_payload)
        os.fchmod(descriptor, 0o600)
    except OSError as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except OSError:
            pass
        raise ContainmentBlocked("cannot retain quarantine payload") from exc
    else:
        os.close(descriptor)

    try:
        os.link(
            temporary,
            filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileExistsError:
        _read_existing_payload(directory_fd, filename, raw_payload)
    except OSError as exc:
        raise ContainmentBlocked("cannot publish quarantine payload") from exc
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except OSError:
            pass
    return filename


def retain_after_failed_owner_check(
    *,
    raw_payload: bytes,
    claimed_owner: str,
    expected_owner: str,
    quarantine_root: Path | str,
    generic_roots: Iterable[Path | str],
) -> dict[str, object]:
    """Retain a wrong-owner payload without republishing it to the skeleton."""
    if not isinstance(raw_payload, bytes) or not raw_payload:
        raise ContainmentBlocked("cannot retain an empty payload")
    if (
        not isinstance(claimed_owner, str)
        or not claimed_owner
        or not isinstance(expected_owner, str)
        or not expected_owner
    ):
        raise ContainmentBlocked("owner identifiers must be non-empty strings")
    if claimed_owner == expected_owner:
        raise ContainmentBlocked("owner check did not fail")

    quarantine = _resolved(quarantine_root)
    generic = tuple(generic_roots)
    if not generic:
        raise ContainmentBlocked("generic roots are required")
    _validate_quarantine_location(quarantine, generic)
    _validate_parent_control(quarantine)
    directory_fd = _open_quarantine_directory(quarantine)
    try:
        opened = os.fstat(directory_fd)
        current = os.stat(quarantine, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (
            current.st_dev,
            current.st_ino,
        ):
            raise ContainmentBlocked("quarantine directory identity changed")
        filename = _write_protected_payload(directory_fd, raw_payload)
        retained_identity = (
            f"{opened.st_dev}:{opened.st_ino}:{filename}".encode("utf-8")
        )
    finally:
        os.close(directory_fd)

    return {
        "byte_count": len(raw_payload),
        "content_sha256": _sha256(raw_payload),
        "retained_path_sha256": _sha256(retained_identity),
        "retention": "protected_quarantine",
    }


def _load_json_object(path: Path, label: str) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ContainmentBlocked(f"{label} is missing or unsafe")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContainmentBlocked(f"{label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ContainmentBlocked(f"{label} must be a JSON object")
    return payload


def _git_blob(repo_root: Path, revision: str, relative_path: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "show", f"{revision}:{relative_path}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContainmentBlocked(
            f"cannot read committed file: {relative_path}"
        ) from exc
    return completed.stdout


def _json_object_from_bytes(raw: bytes, label: str) -> dict:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContainmentBlocked(f"{label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ContainmentBlocked(f"{label} must be a JSON object")
    return payload


def _load_owner(repo_root: Path, instance_name: str) -> Path:
    registry = _json_object_from_bytes(
        _git_blob(repo_root, "HEAD", "instance-registry.json"),
        "instance registry",
    )
    instances = registry.get("instances")
    if not isinstance(instances, list):
        raise ContainmentBlocked("instance registry is malformed")
    matches = [
        item
        for item in instances
        if isinstance(item, dict)
        and item.get("name") == instance_name
    ]
    if len(matches) != 1:
        raise ContainmentBlocked(
            "instance owner is missing or ambiguous"
        )
    owner_path = matches[0].get("path")
    if not isinstance(owner_path, str) or not owner_path:
        raise ContainmentBlocked("instance owner path is invalid")
    owner = Path(owner_path).expanduser().resolve(strict=False)
    if not owner.is_dir():
        raise ContainmentBlocked("instance owner path does not exist")
    return owner


def _owned_regular_file(
    owner: Path,
    relative_path: str,
    label: str,
) -> Path:
    candidate = owner / relative_path
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(owner)
    except (OSError, ValueError) as exc:
        raise ContainmentBlocked(
            f"{label} escapes the registered owner"
        ) from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise ContainmentBlocked(f"{label} is missing or unsafe")
    return resolved


def _validate_source_commit(repo_root: Path, source_commit: str) -> None:
    try:
        object_type = subprocess.run(
            ["git", "cat-file", "-t", source_commit],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", source_commit, "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContainmentBlocked(
            "source commit is not a trusted HEAD ancestor"
        ) from exc
    if object_type != "commit":
        raise ContainmentBlocked("source commit is not a commit object")


def _validate_owner_commit(owner: Path) -> None:
    paths = [*EXPECTED_EXPORT_PATHS, RECEIPT_RELATIVE_PATH]
    try:
        subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", *paths],
            cwd=owner,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", *paths],
            cwd=owner,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContainmentBlocked(
            "owner export and receipt must match the owner HEAD commit"
        ) from exc


def _source_blob(
    repo_root: Path,
    commit: str,
    relative_path: str,
) -> bytes:
    return _git_blob(repo_root, commit, relative_path)


def _validate_file_receipt(
    *,
    repo_root: Path,
    owner: Path,
    source_commit: str,
    record: dict,
    require_hash_match: bool,
) -> str:
    if set(record) != FILE_RECEIPT_KEYS:
        raise ContainmentBlocked("file receipt fields are invalid")
    source_path = record["source_path"]
    destination_path = record["destination_path"]
    if (
        not isinstance(source_path, str)
        or not isinstance(destination_path, str)
        or source_path != destination_path
        or source_path not in EXPECTED_EXPORT_PATHS
    ):
        raise ContainmentBlocked("file receipt path is invalid")

    source_sha256 = record["source_sha256"]
    destination_sha256 = record["destination_sha256"]
    if (
        not isinstance(source_sha256, str)
        or SHA256_RE.fullmatch(source_sha256) is None
        or not isinstance(destination_sha256, str)
        or SHA256_RE.fullmatch(destination_sha256) is None
    ):
        raise ContainmentBlocked("file receipt hash is invalid")

    source_raw = _source_blob(repo_root, source_commit, source_path)
    if _sha256(source_raw) != source_sha256:
        raise ContainmentBlocked(
            f"source hash mismatch: {source_path}"
        )

    destination = _owned_regular_file(
        owner,
        destination_path,
        f"destination {destination_path}",
    )
    try:
        destination_raw = destination.read_bytes()
    except OSError as exc:
        raise ContainmentBlocked(
            f"cannot read destination: {destination_path}"
        ) from exc
    if _sha256(destination_raw) != destination_sha256:
        raise ContainmentBlocked(
            f"destination hash mismatch: {destination_path}"
        )
    if source_sha256 != destination_sha256:
        raise ContainmentBlocked(
            f"source and destination hash match failed: {source_path}"
        )
    return source_path


def verify_export(
    repo_root: Path | str,
    instance_name: str,
    *,
    require_hash_match: bool = False,
) -> dict[str, object]:
    """Verify the owner, receipt, committed source, and exported files."""
    if not isinstance(instance_name, str) or not instance_name:
        raise ContainmentBlocked("instance name is required")
    root = Path(repo_root).resolve()
    owner = _load_owner(root, instance_name)
    receipt_path = _owned_regular_file(
        owner,
        RECEIPT_RELATIVE_PATH,
        "containment receipt",
    )
    receipt = _load_json_object(
        receipt_path,
        "containment receipt",
    )
    if set(receipt) != RECEIPT_KEYS or receipt.get("schema_version") != 1:
        raise ContainmentBlocked("containment receipt fields are invalid")
    if receipt.get("instance") != instance_name:
        raise ContainmentBlocked("containment receipt instance is invalid")
    if receipt.get("owner_root") != str(owner):
        raise ContainmentBlocked(
            "containment receipt owner does not match registry"
        )

    source_commit = receipt.get("source_commit")
    if (
        not isinstance(source_commit, str)
        or COMMIT_RE.fullmatch(source_commit) is None
    ):
        raise ContainmentBlocked("source commit is invalid")
    _validate_source_commit(root, source_commit)
    files = receipt.get("files")
    if not isinstance(files, list) or not all(
        isinstance(record, dict) for record in files
    ):
        raise ContainmentBlocked("containment receipt files are invalid")

    verified_paths = [
        _validate_file_receipt(
            repo_root=root,
            owner=owner,
            source_commit=source_commit,
            record=record,
            require_hash_match=require_hash_match,
        )
        for record in files
    ]
    if (
        len(verified_paths) != len(EXPECTED_EXPORT_PATHS)
        or sorted(verified_paths) != sorted(EXPECTED_EXPORT_PATHS)
    ):
        raise ContainmentBlocked(
            "containment receipt does not cover the complete export"
        )
    _validate_owner_commit(owner)
    return {
        "file_count": len(verified_paths),
        "instance": instance_name,
        "status": "verified",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a containment export receipt."
    )
    parser.add_argument("--instance", required=True)
    parser.add_argument("--require-hash-match", action="store_true")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
    )
    args = parser.parse_args(argv)
    try:
        result = verify_export(
            args.repo_root,
            args.instance,
            require_hash_match=args.require_hash_match,
        )
    except ContainmentBlocked as exc:
        print(f"containment export blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
