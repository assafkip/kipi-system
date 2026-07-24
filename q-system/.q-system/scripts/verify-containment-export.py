#!/usr/bin/env python3
"""Verify containment exports and retain failed-owner payloads safely."""

from __future__ import annotations

import hashlib
import os
import secrets
import stat
from pathlib import Path
from typing import Iterable


class ContainmentBlocked(ValueError):
    """Raised when containment cannot preserve the separation boundary."""


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
