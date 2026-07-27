#!/usr/bin/env python3
"""Enumerate generic, tracked text surfaces for containment checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath


# Git's mode for a gitlink (submodule) entry in the index. Its object id is a
# commit in another repository, so it is never readable as a blob here.
GITLINK_MODE = "160000"


class ContainmentScopeBlocked(RuntimeError):
    """Raised when repository scope cannot be proven."""


EXCLUDED_PREFIXES = {
    ".prd-os": "prd-os-state",
    "q-system/memory": "instance-memory",
    "q-system/output": "instance-output",
}
def _prefix_reason(relative_path: str) -> str | None:
    for prefix, reason in EXCLUDED_PREFIXES.items():
        if (
            relative_path == prefix
            or relative_path.startswith(prefix + "/")
        ):
            return reason
    return None


def _tracked_entries(repo_root: Path) -> list[dict[str, str]]:
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--stage", "-z"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContainmentScopeBlocked(
            "cannot enumerate tracked repository paths"
        ) from exc

    entries = []
    for raw_entry in completed.stdout.split(b"\0"):
        if not raw_entry:
            continue
        try:
            metadata, raw_path = raw_entry.split(b"\t", 1)
            mode, object_id, stage = metadata.decode("ascii").split()
            relative_path = raw_path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContainmentScopeBlocked(
                "tracked repository path is not UTF-8"
            ) from exc
        except (ValueError, UnicodeError) as exc:
            raise ContainmentScopeBlocked(
                "git returned malformed tracked metadata"
            ) from exc
        # A gitlink records ANOTHER repo's commit sha, not a blob in this object
        # store, so `git cat-file blob` on it always fails and _indexed_bytes
        # converts that into ContainmentScopeBlocked -- taking the entire
        # containment gate down rather than skipping one entry.
        #
        # Observed 2026-07-27: the auto-committer swept the review agent's
        # scratch worktrees into main, 11 gitlinks landed, and Gate 1.3b went
        # from PASS to "scope unavailable" on every open PR at once. Nothing was
        # wrong with the containment rule; the scanner could not start.
        #
        # Skipping is the correct SCOPE, not a workaround: a submodule's content
        # lives in a different repository, so this repo cannot scan it and never
        # could. Any repo that legitimately used a submodule hit the same wall.
        # The committed scratch is a separate defect (sp-1aae7516).
        if mode == GITLINK_MODE:
            continue
        if stage != "0":
            raise ContainmentScopeBlocked(
                f"tracked path has unresolved index stage: {relative_path}"
            )
        path = PurePosixPath(relative_path)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ContainmentScopeBlocked(
                "git returned an unsafe tracked path"
            )
        entries.append(
            {
                "mode": mode,
                "object_id": object_id,
                "path": relative_path,
            }
        )
    return sorted(entries, key=lambda entry: entry["path"])


def _index_sha256(entries: list[dict[str, str]]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(entry["mode"].encode("ascii"))
        digest.update(b"\0")
        digest.update(entry["object_id"].encode("ascii"))
        digest.update(b"\0")
        digest.update(entry["path"].encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _indexed_bytes(repo_root: Path, object_id: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "cat-file", "blob", object_id],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContainmentScopeBlocked(
            "cannot read tracked object from Git index"
        ) from exc
    return completed.stdout


def read_indexed_target(
    repo_root: Path | str,
    relative_path: str,
    object_id: str,
) -> str:
    """Read one enumerated target from the same Git index snapshot."""
    root = Path(repo_root).resolve()
    if re.fullmatch(r"[0-9a-fA-F]{40,64}", object_id) is None:
        raise ContainmentScopeBlocked(
            f"invalid target object identity: {relative_path}"
        )
    content = _indexed_bytes(root, object_id)
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContainmentScopeBlocked(
            f"enumerated target is no longer text: {relative_path}"
        ) from exc


def assert_index_unchanged(
    repo_root: Path | str,
    expected_sha256: str,
) -> None:
    """Block if any tracked index entry changed after enumeration."""
    actual_sha256 = _index_sha256(
        _tracked_entries(Path(repo_root).resolve())
    )
    if actual_sha256 != expected_sha256:
        raise ContainmentScopeBlocked(
            "repository index changed during containment validation"
        )


def enumerate_containment_targets(repo_root: Path | str) -> dict:
    """Return deterministic targets and an explicit reason for every exclusion."""
    root = Path(repo_root).resolve()
    targets = []
    excluded = []

    target_objects = {}
    entries = _tracked_entries(root)
    for entry in entries:
        relative_path = entry["path"]
        reason = _prefix_reason(relative_path)

        if reason is None and entry["mode"] == "120000":
            reason = "symlink"

        if reason is None:
            content = _indexed_bytes(root, entry["object_id"])
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                reason = "generated-or-binary-asset"

        if reason is None:
            targets.append(relative_path)
            target_objects[relative_path] = entry["object_id"]
        else:
            excluded.append(
                {"path": relative_path, "reason": reason}
            )

    return {
        "excluded": excluded,
        "index_sha256": _index_sha256(entries),
        "schema_version": 1,
        "target_count": len(targets),
        "target_objects": target_objects,
        "target_source": "git-ls-files",
        "targets": targets,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enumerate tracked generic text surfaces as JSON."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
    )
    args = parser.parse_args(argv)

    try:
        manifest = enumerate_containment_targets(args.repo_root)
    except ContainmentScopeBlocked as exc:
        print(f"containment scope blocked: {exc}")
        return 2
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
