#!/usr/bin/env python3
"""Build a deterministic registry-derived manifest of instance-owned files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tempfile


SCHEMA_VERSION = 1


def fail(message: str) -> None:
    raise ValueError(message)


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value in {"", "."}:
        fail(f"unsafe relative path: {value!r}")
    return path.as_posix()


def run_git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
    )
    if result.returncode != 0:
        fail(
            f"git {' '.join(args)} failed with exit {result.returncode}: "
            f"{result.stderr.decode(errors='replace').strip()}"
        )
    return result.stdout


def git_path_set(repo: Path, *args: str) -> set[str]:
    output = run_git(repo, "ls-files", "-z", *args)
    return {
        item.decode("utf-8", "surrogateescape")
        for item in output.split(b"\0")
        if item
    }


def git_owned_paths(repo: Path) -> tuple[set[str], set[str], set[str]]:
    tracked = git_path_set(repo, "--cached")
    untracked = git_path_set(repo, "--others", "--exclude-standard")
    ignored = git_path_set(repo, "--others", "--ignored", "--exclude-standard")
    return tracked | untracked | ignored, tracked, ignored


def git_head_tree_paths(repo: Path) -> set[str]:
    output = run_git(repo, "ls-tree", "-r", "--name-only", "-z", "HEAD")
    return {
        item.decode("utf-8", "surrogateescape")
        for item in output.split(b"\0")
        if item
    }


def git_input_receipts(repo: Path, skeleton: Path) -> dict:
    return {
        "instance_head": run_git(repo, "rev-parse", "HEAD").decode().strip(),
        "instance_index_sha256": hashlib.sha256(
            run_git(repo, "ls-files", "--stage", "-z")
        ).hexdigest(),
        "instance_status_sha256": hashlib.sha256(
            run_git(repo, "status", "--porcelain=v1", "-z", "--ignored=matching")
        ).hexdigest(),
        "skeleton_head": run_git(skeleton, "rev-parse", "HEAD").decode().strip(),
        "skeleton_tree": run_git(skeleton, "rev-parse", "HEAD^{tree}")
        .decode()
        .strip(),
    }


def is_within(candidate: str, root: str) -> bool:
    candidate_path = PurePosixPath(candidate)
    root_path = PurePosixPath(root)
    return candidate_path == root_path or root_path in candidate_path.parents


def skeleton_ever_tracked(skeleton: Path, candidate: str) -> bool:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(skeleton),
            "log",
            "--all",
            "--format=%H",
            "-1",
            "--",
            candidate,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(f"skeleton history lookup failed for {candidate}")
    return bool(result.stdout.strip())


def generic_selected(
    candidate: str,
    *,
    managed_root: str,
    skeleton: Path,
    skeleton_archived: set[str],
    destinations: list[dict],
) -> bool:
    for destination in destinations:
        root = expand_contract_path(destination["path"], managed_root, managed_root)
        selection = destination["selection"]
        if selection == "skeleton_archive_contents" and is_within(candidate, root):
            relative = PurePosixPath(candidate).relative_to(root).as_posix()
            skeleton_candidate = f"q-system/{relative}"
            return skeleton_candidate in skeleton_archived or skeleton_ever_tracked(
                skeleton, skeleton_candidate
            )
        if selection == "settings_template_fields" and candidate == root:
            return True
        if selection == "skeleton_matching_markdown" and is_within(candidate, root):
            return candidate.endswith(".md") and candidate in skeleton_archived
        if selection == "skeleton_present_plugin_directories" and is_within(
            candidate, root
        ):
            parts = PurePosixPath(candidate).parts
            plugin_root = "/".join(parts[:2])
            return any(
                tracked == plugin_root or is_within(tracked, plugin_root)
                for tracked in skeleton_archived
            )
    return False


def automation_candidate(
    candidate: str,
    *,
    managed_root: str,
    state_root: str,
    automation: dict,
) -> bool:
    scopes = tuple(
        expand_contract_path(path, managed_root, state_root)
        for path in automation["paths"]
    )
    if not any(is_within(candidate, root) for root in scopes):
        return False
    for excluded in automation["excluded_relative_paths"]:
        if excluded == "**/__pycache__" and "__pycache__" in PurePosixPath(
            candidate
        ).parts:
            return False
        if excluded == "**/*.pyc" and candidate.endswith(".pyc"):
            return False
        if not excluded.startswith("**/") and is_within(candidate, managed_root):
            relative = PurePosixPath(candidate).relative_to(managed_root).as_posix()
            if relative == excluded or relative.startswith(f"{excluded}/"):
                return False
    return True


def expand_contract_path(template: str, managed_root: str, state_root: str) -> str:
    expanded = template.replace("{managed_root}", managed_root).replace(
        "{state_root}", state_root
    )
    if "{" in expanded or "}" in expanded:
        fail(f"unsupported ownership contract path template: {template!r}")
    return safe_relative(expanded)


def validate_contract_entry(entry: dict, required: set[str], label: str) -> None:
    if not isinstance(entry, dict) or not required.issubset(entry):
        fail(f"ownership contract has incomplete {label}")


def applicable_entries(entries: list[dict], instance_type: str) -> list[dict]:
    return [entry for entry in entries if instance_type in entry["applies_to"]]


def validate_contract(contract: dict) -> None:
    if contract.get("schema_version") != 1:
        fail("unsupported ownership contract version")
    required = {
        "registry_contract",
        "managed_destinations",
        "preserved_state",
        "instance_automation",
    }
    if not required.issubset(contract):
        fail("ownership contract is incomplete")
    registry_contract = contract["registry_contract"]
    validate_contract_entry(
        registry_contract,
        {
            "managed_types",
            "standalone_type",
            "managed_root_field",
            "state_root_field",
            "state_root_fallback",
            "null_managed_root_policy",
        },
        "registry contract",
    )
    if registry_contract["state_root_fallback"] != "managed_root":
        fail("unsupported state-root fallback")
    if registry_contract["null_managed_root_policy"] != "skip_any_null_managed_root":
        fail("unsupported null managed-root policy")
    destination_selections = {
        "skeleton_archive_contents",
        "origin_branch_changes",
        "settings_template_fields",
        "skeleton_matching_markdown",
        "skeleton_present_plugin_directories",
    }
    for entry in contract["managed_destinations"]:
        validate_contract_entry(
            entry, {"path", "selection", "applies_to"}, "managed destination"
        )
        if entry["selection"] not in destination_selections:
            fail(f"unsupported generic selection: {entry['selection']!r}")
    for entry in contract["preserved_state"]:
        validate_contract_entry(
            entry, {"path", "class", "applies_to"}, "preserved-state entry"
        )
        if entry["class"] != "preserved_state":
            fail("preserved-state entry has wrong ownership class")
    automation = contract["instance_automation"]
    validate_contract_entry(
        automation,
        {
            "paths",
            "class",
            "applies_to",
            "selection",
            "excluded_relative_paths",
        },
        "instance-automation entry",
    )
    if (
        automation["class"] != "instance_automation"
        or automation["selection"]
        != "tracked_or_untracked_paths_not_selected_by_generic_operation"
    ):
        fail("unsupported instance-automation contract")
    if automation["applies_to"] != ["subtree"]:
        fail("unsupported instance-automation applicability")
    if set(automation["excluded_relative_paths"]) != {
        "q-system",
        "**/__pycache__",
        "**/*.pyc",
    }:
        fail("unsupported instance-automation exclusions")


def manifest_with_receipt(payload: dict) -> dict:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {**payload, "manifest_sha256": hashlib.sha256(canonical).hexdigest()}


def absolute_without_symlinks(path: Path, label: str) -> Path:
    absolute = path.expanduser().absolute()
    if absolute.is_symlink():
        fail(f"{label} must not be a symlink")
    return absolute.resolve()


def ensure_registry_repo(instance: dict, repo: Path) -> None:
    registered = instance.get("path")
    if not isinstance(registered, str) or not registered:
        fail("registry instance path is missing")
    registered_path = absolute_without_symlinks(Path(registered), "registry path")
    if registered_path != repo:
        fail("repo root does not match the selected registry instance path")


def validate_layout_type(contract: dict, instance_type: str) -> None:
    registry_contract = contract["registry_contract"]
    allowed = set(registry_contract["managed_types"]) | {
        registry_contract["standalone_type"]
    }
    if instance_type not in allowed:
        fail(f"unsupported preservation layout type: {instance_type}")


def skipped_manifest(instance_name: str, instance: dict, reason: str) -> dict:
    return manifest_with_receipt(
        {
            "entries": [],
            "entry_count": 0,
            "instance": instance_name,
            "layout": {
                "instance_q_dir": instance.get("instance_q_dir"),
                "subtree_prefix": instance.get("subtree_prefix"),
                "type": instance.get("type", "subtree"),
            },
            "reason": reason,
            "schema_version": SCHEMA_VERSION,
            "status": "skipped",
        }
    )


def ensure_inside_repo(repo: Path, relative: str) -> Path:
    path = repo / relative
    current = repo
    for part in PurePosixPath(relative).parts[:-1]:
        current /= part
        if current.is_symlink():
            fail(f"owned path has symlinked ancestor: {relative}")
    try:
        path.parent.resolve().relative_to(repo)
    except ValueError:
        fail(f"owned path escapes instance: {relative}")
    return path


def tracking_label(relative: str, tracked: set[str], ignored: set[str]) -> str:
    if relative in tracked:
        return "tracked"
    if relative in ignored:
        return "ignored"
    return "untracked"


def file_receipt(
    repo: Path, relative: str, tracked: set[str], ignored: set[str]
) -> dict:
    path = ensure_inside_repo(repo, relative)
    before = path.lstat()
    metadata = before
    if stat.S_ISLNK(metadata.st_mode):
        kind = "symlink"
        target = os.readlink(path)
        if os.path.isabs(target):
            fail(f"owned symlink is absolute: {relative}")
        resolved = (path.parent / target).resolve(strict=False)
        try:
            resolved.relative_to(repo)
        except ValueError:
            fail(f"owned symlink escapes instance: {relative}")
        payload = target.encode("utf-8", "surrogateescape")
    elif stat.S_ISREG(metadata.st_mode):
        kind = "file"
        payload = path.read_bytes()
    else:
        fail(f"unsupported owned path type: {relative}")
    after = path.lstat()
    stable_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
        fail(f"owned path changed while manifest was built: {relative}")
    return {
        "kind": kind,
        "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
        "path": relative,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "tracking": tracking_label(relative, tracked, ignored),
    }


def directory_receipt(repo: Path, relative: str) -> dict:
    path = ensure_inside_repo(repo, relative)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        fail(f"owned directory is not a directory: {relative}")
    return {
        "kind": "directory",
        "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
        "path": relative,
        "sha256": hashlib.sha256(b"directory").hexdigest(),
        "tracking": "filesystem-only",
    }


def empty_directories(repo: Path, roots: set[str]) -> set[str]:
    result: set[str] = set()
    for relative_root in sorted(roots):
        root = repo / relative_root
        if root.is_symlink():
            fail(f"owned root is a symlink: {relative_root}")
        if not root.is_dir():
            continue
        for current, directories, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            relative = current_path.relative_to(repo).as_posix()
            if any((current_path / name).is_symlink() for name in directories):
                fail(f"owned directory contains symlinked directory: {relative}")
            if not directories and not files:
                result.add(relative)
    return result


def merge_managed(candidate: str, destinations: list[dict]) -> bool:
    return any(
        destination["selection"] == "settings_template_fields"
        and candidate == destination["path"]
        for destination in destinations
    )


def resolve_instance(registry: dict, name: str) -> dict:
    matches = [
        item for item in registry.get("instances", []) if item.get("name") == name
    ]
    if len(matches) != 1:
        fail(f"registry must contain exactly one instance named {name!r}")
    return matches[0]


def collect_entries(
    *,
    repo: Path,
    skeleton: Path,
    managed_root: str,
    state_root: str,
    state_roots: list[str],
    destinations: list[dict],
    automation: dict,
    instance_type: str,
) -> list[dict]:
    all_paths, tracked, ignored = git_owned_paths(repo)
    skeleton_archived = git_head_tree_paths(skeleton)
    automation_applies = instance_type in automation["applies_to"]
    entries: list[dict] = []
    included: set[str] = set()
    for candidate in sorted(all_paths):
        safe_relative(candidate)
        path = repo / candidate
        if not (path.exists() or path.is_symlink()):
            continue
        owner_class: str | None = None
        preservation: str | None = None
        if any(is_within(candidate, root) for root in state_roots):
            owner_class = "preserved_state"
        elif merge_managed(candidate, destinations):
            owner_class = "generic_managed"
            preservation = "field_merge_input"
        elif (
            automation_applies
            and automation_candidate(
                candidate,
                managed_root=managed_root,
                state_root=state_root,
                automation=automation,
            )
            and not generic_selected(
                candidate,
                managed_root=managed_root,
                skeleton=skeleton,
                skeleton_archived=skeleton_archived,
                destinations=destinations,
            )
        ):
            owner_class = "instance_automation"
        if owner_class is None:
            continue
        receipt = file_receipt(repo, candidate, tracked, ignored)
        receipt["owner_class"] = owner_class
        if preservation is not None:
            receipt["preservation"] = preservation
        entries.append(receipt)
        included.add(candidate)

    automation_roots = (
        {
            expand_contract_path(path, managed_root, state_root)
            for path in automation["paths"]
        }
        if automation_applies
        else set()
    )
    for candidate in sorted(empty_directories(repo, set(state_roots) | automation_roots)):
        if candidate in included:
            continue
        owner_class: str | None = None
        if any(is_within(candidate, root) for root in state_roots):
            owner_class = "preserved_state"
        elif automation_candidate(
            candidate,
            managed_root=managed_root,
            state_root=state_root,
            automation=automation,
        ) and not generic_selected(
            candidate,
            managed_root=managed_root,
            skeleton=skeleton,
            skeleton_archived=skeleton_archived,
            destinations=destinations,
        ):
            owner_class = "instance_automation"
        if owner_class is not None:
            receipt = directory_receipt(repo, candidate)
            receipt["owner_class"] = owner_class
            entries.append(receipt)
    return sorted(entries, key=lambda entry: entry["path"])


def build_manifest(
    *,
    contract: dict,
    registry: dict,
    instance_name: str,
    repo: Path,
    skeleton: Path,
) -> dict:
    validate_contract(contract)
    instance = resolve_instance(registry, instance_name)
    instance_type = instance.get("type", "subtree")
    validate_layout_type(contract, instance_type)
    ensure_registry_repo(instance, repo)
    registry_contract = contract["registry_contract"]
    managed_root_value = instance.get(registry_contract["managed_root_field"])
    if (
        instance_type == registry_contract["standalone_type"]
        or not managed_root_value
    ):
        return skipped_manifest(instance_name, instance, "not-skeleton-managed")
    if instance_type != "subtree":
        return skipped_manifest(instance_name, instance, "no-preservation-operation")
    managed_root = safe_relative(managed_root_value)
    state_root = safe_relative(
        instance.get(registry_contract["state_root_field"]) or managed_root
    )
    if not repo.is_dir() or not skeleton.is_dir():
        fail("instance and skeleton roots must exist")

    preserved_entries = applicable_entries(contract["preserved_state"], instance_type)
    state_roots = sorted(
        {
            expand_contract_path(entry["path"], managed_root, state_root)
            for entry in preserved_entries
        }
    )
    destinations = applicable_entries(
        contract["managed_destinations"], instance_type
    )
    automation = contract["instance_automation"]
    before_inputs = git_input_receipts(repo, skeleton)
    entries = collect_entries(
        repo=repo,
        skeleton=skeleton,
        managed_root=managed_root,
        state_root=state_root,
        state_roots=state_roots,
        destinations=destinations,
        automation=automation,
        instance_type=instance_type,
    )
    confirmation = collect_entries(
        repo=repo,
        skeleton=skeleton,
        managed_root=managed_root,
        state_root=state_root,
        state_roots=state_roots,
        destinations=destinations,
        automation=automation,
        instance_type=instance_type,
    )
    after_inputs = git_input_receipts(repo, skeleton)
    if entries != confirmation or before_inputs != after_inputs:
        fail("manifest inputs changed during collection")

    contract_receipt = hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    instance_receipt = hashlib.sha256(
        json.dumps(instance, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return manifest_with_receipt(
        {
            "declared_state_roots": state_roots,
            "entries": entries,
            "entry_count": len(entries),
            "inputs": {
                **before_inputs,
                "ownership_contract_sha256": contract_receipt,
                "registry_entry_sha256": instance_receipt,
            },
            "instance": instance_name,
            "layout": {
                "instance_q_dir": instance.get("instance_q_dir"),
                "subtree_prefix": managed_root,
                "type": instance_type,
            },
            "schema_version": SCHEMA_VERSION,
            "status": "ready",
        }
    )


def write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.tmp.",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def ensure_output_outside_repo(output: Path, repo: Path) -> Path:
    absolute = output.expanduser().absolute().resolve(strict=False)
    try:
        absolute.relative_to(repo)
    except ValueError:
        return absolute
    fail("manifest output must be outside the instance repository")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--instance-name", required=True)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--skeleton-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        repo = absolute_without_symlinks(args.repo_root, "repo root")
        skeleton = absolute_without_symlinks(args.skeleton_root, "skeleton root")
        output = (
            ensure_output_outside_repo(args.output, repo) if args.output else None
        )
        manifest = build_manifest(
            contract=json.loads(args.contract.read_text(encoding="utf-8")),
            registry=json.loads(args.registry.read_text(encoding="utf-8")),
            instance_name=args.instance_name,
            repo=repo,
            skeleton=skeleton,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if output:
        try:
            write_atomic(output, payload)
        except OSError as error:
            print(f"ERROR: could not write manifest: {error}", file=sys.stderr)
            return 1
    sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
