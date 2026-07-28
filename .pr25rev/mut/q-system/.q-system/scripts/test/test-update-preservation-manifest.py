#!/usr/bin/env python3
"""Black-box tests for the registry-derived preservation manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = (
    REPO_ROOT
    / "q-system"
    / ".q-system"
    / "scripts"
    / "update-preservation-manifest.py"
)
CONTRACT = (
    REPO_ROOT
    / "q-system"
    / ".q-system"
    / "config"
    / "instance-ownership-contract.json"
)


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=test",
            *args,
        ],
        check=True,
        capture_output=True,
    )


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.skeleton = self.root / "skeleton"
        self.instance = self.root / "instance"
        self.registry = self.root / "registry.json"
        self.skeleton.mkdir()
        self.instance.mkdir()
        git(self.skeleton, "init", "-q")
        git(self.instance, "init", "-q")

        (self.skeleton / "q-system").mkdir()
        (self.skeleton / "q-system" / "generic.md").write_text(
            "generic\n", encoding="utf-8"
        )
        (self.skeleton / ".claude" / "agents").mkdir(parents=True)
        (self.skeleton / ".claude" / "agents" / "generic.md").write_text(
            "agent\n", encoding="utf-8"
        )
        (self.skeleton / "plugins" / "core").mkdir(parents=True)
        (self.skeleton / "plugins" / "core" / "runtime.py").write_text(
            "runtime\n", encoding="utf-8"
        )
        git(self.skeleton, "add", "-A")
        git(self.skeleton, "commit", "-qm", "skeleton")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_registry(
        self,
        *,
        instance_type: str = "subtree",
        prefix: str | None = "q-system",
        q_dir: str | None = None,
    ) -> None:
        self.registry.write_text(
            json.dumps(
                {
                    "instances": [
                        {
                            "name": "fixture",
                            "path": str(self.instance),
                            "subtree_prefix": prefix,
                            "instance_q_dir": q_dir,
                            "type": instance_type,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    def run_manifest(self, *extra: str, expect: int = 0) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--contract",
                str(CONTRACT),
                "--registry",
                str(self.registry),
                "--instance-name",
                "fixture",
                "--repo-root",
                str(self.instance),
                "--skeleton-root",
                str(self.skeleton),
                *extra,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, expect, result.stderr)
        return result

    def seed_owned_files(self, *, q_dir: str = "q-system") -> None:
        tracked_paths = (
            "q-system/canonical/tracked.md",
            "q-system/.q-system/scripts/instance-job.py",
            f"{q_dir}/my-project/tracked.md",
            f"{q_dir}/memory/tracked.md",
        )
        untracked_paths = (
            "q-system/output/untracked.json",
            "q-system/.q-system/agent-pipeline/bus/event.json",
            f"{q_dir}/canonical/private.md",
            f"{q_dir}/output/report.md",
            ".claude/agents/instance-only.md",
            "plugins/instance-only/run.py",
            ".claude/settings.json",
        )
        generic_paths = (
            "q-system/generic.md",
            ".claude/agents/generic.md",
            "plugins/core/runtime.py",
        )
        ignored_path = f"{q_dir}/output/ignored-runtime.json"
        for relative in (*tracked_paths, *untracked_paths, *generic_paths):
            path = self.instance / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{relative}\n", encoding="utf-8")
        (self.instance / ignored_path).parent.mkdir(parents=True, exist_ok=True)
        (self.instance / ignored_path).write_text("ignored\n", encoding="utf-8")
        (self.instance / ".gitignore").write_text(
            f"/{ignored_path}\n", encoding="utf-8"
        )
        git(self.instance, "add", *tracked_paths, *generic_paths, ".gitignore")
        git(self.instance, "commit", "-qm", "instance")

    def test_tracked_untracked_state_and_automation_are_manifested(self) -> None:
        self.write_registry()
        self.seed_owned_files()
        manifest = json.loads(self.run_manifest().stdout)
        entries = {entry["path"]: entry for entry in manifest["entries"]}
        self.assertEqual(manifest["status"], "ready")
        self.assertEqual(manifest["entry_count"], len(entries))
        self.assertEqual(
            entries["q-system/canonical/tracked.md"]["tracking"], "tracked"
        )
        self.assertEqual(
            entries["q-system/output/untracked.json"]["tracking"], "untracked"
        )
        self.assertEqual(
            entries["q-system/output/ignored-runtime.json"]["tracking"], "ignored"
        )
        self.assertEqual(
            entries[".claude/settings.json"]["preservation"], "field_merge_input"
        )
        self.assertEqual(
            entries["q-system/.q-system/scripts/instance-job.py"]["owner_class"],
            "instance_automation",
        )
        self.assertEqual(
            entries[".claude/agents/instance-only.md"]["owner_class"],
            "instance_automation",
        )
        self.assertEqual(
            entries["plugins/instance-only/run.py"]["owner_class"],
            "instance_automation",
        )
        for generic in (
            "q-system/generic.md",
            ".claude/agents/generic.md",
            "plugins/core/runtime.py",
        ):
            self.assertNotIn(generic, entries)

    def test_custom_q_dir_and_managed_root_both_contribute_state(self) -> None:
        self.write_registry(q_dir="q-client")
        self.seed_owned_files(q_dir="q-client")
        manifest = json.loads(self.run_manifest().stdout)
        paths = {entry["path"] for entry in manifest["entries"]}
        for relative in (
            "q-system/canonical/tracked.md",
            "q-system/output/untracked.json",
            "q-client/canonical/private.md",
            "q-client/my-project/tracked.md",
            "q-client/memory/tracked.md",
            "q-client/output/report.md",
        ):
            self.assertIn(relative, paths)
        self.assertIn("q-system/canonical", manifest["declared_state_roots"])
        self.assertIn("q-client/canonical", manifest["declared_state_roots"])

    def test_standalone_and_null_prefix_are_skipped(self) -> None:
        for instance_type in ("standalone", "subtree"):
            with self.subTest(instance_type=instance_type):
                self.write_registry(instance_type=instance_type, prefix=None)
                manifest = json.loads(self.run_manifest().stdout)
                self.assertEqual(manifest["status"], "skipped")
                self.assertEqual(manifest["entries"], [])

    def test_output_is_atomic_and_deterministic(self) -> None:
        self.write_registry()
        self.seed_owned_files()
        output = self.root / "manifest.json"
        stale = self.root / ".manifest.json.tmp.stale"
        stale.write_text("stale\n", encoding="utf-8")
        first = self.run_manifest("--output", str(output)).stdout
        second = self.run_manifest("--output", str(output)).stdout
        self.assertEqual(first, second)
        self.assertEqual(output.read_text(encoding="utf-8"), second)
        self.assertEqual(stale.read_text(encoding="utf-8"), "stale\n")
        manifest = json.loads(first)
        self.assertEqual(len(manifest["inputs"]["skeleton_tree"]), 40)
        self.assertEqual(len(manifest["inputs"]["ownership_contract_sha256"]), 64)
        self.assertEqual(len(manifest["inputs"]["registry_entry_sha256"]), 64)
        receipt = manifest.pop("manifest_sha256")
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(
            receipt, hashlib.sha256(canonical).hexdigest()
        )
        self.assertEqual(
            [entry["path"] for entry in manifest["entries"]],
            sorted(entry["path"] for entry in manifest["entries"]),
        )

    def test_invalid_layouts_fail_closed(self) -> None:
        self.write_registry(prefix="../outside")
        self.run_manifest(expect=1)
        self.write_registry(instance_type="unknown")
        self.run_manifest(expect=1)
        self.write_registry(instance_type="unknown", prefix=None)
        self.run_manifest(expect=1)

    def test_registry_path_must_match_requested_repo(self) -> None:
        self.write_registry()
        payload = json.loads(self.registry.read_text(encoding="utf-8"))
        payload["instances"][0]["path"] = str(self.root / "other")
        self.registry.write_text(json.dumps(payload), encoding="utf-8")
        self.run_manifest(expect=1)

    def test_symlinked_registry_root_is_rejected(self) -> None:
        link = self.root / "instance-link"
        link.symlink_to(self.instance, target_is_directory=True)
        self.write_registry()
        payload = json.loads(self.registry.read_text(encoding="utf-8"))
        payload["instances"][0]["path"] = str(link)
        self.registry.write_text(json.dumps(payload), encoding="utf-8")
        self.run_manifest(expect=1)

    def test_untracked_skeleton_file_does_not_claim_instance_ownership(self) -> None:
        self.write_registry()
        relative = "q-system/.q-system/scripts/local-only.py"
        instance_path = self.instance / relative
        skeleton_path = self.skeleton / relative
        instance_path.parent.mkdir(parents=True, exist_ok=True)
        skeleton_path.parent.mkdir(parents=True, exist_ok=True)
        instance_path.write_text("instance\n", encoding="utf-8")
        skeleton_path.write_text("untracked skeleton\n", encoding="utf-8")
        git(self.instance, "add", relative)
        git(self.instance, "commit", "-qm", "instance")
        manifest = json.loads(self.run_manifest().stdout)
        self.assertIn(relative, {entry["path"] for entry in manifest["entries"]})

    def test_staged_skeleton_file_is_not_treated_as_archived(self) -> None:
        self.write_registry()
        relative = "q-system/.q-system/scripts/staged-only.py"
        instance_path = self.instance / relative
        skeleton_path = self.skeleton / relative
        instance_path.parent.mkdir(parents=True, exist_ok=True)
        skeleton_path.parent.mkdir(parents=True, exist_ok=True)
        instance_path.write_text("instance\n", encoding="utf-8")
        skeleton_path.write_text("staged skeleton\n", encoding="utf-8")
        git(self.instance, "add", relative)
        git(self.instance, "commit", "-qm", "instance")
        git(self.skeleton, "add", relative)
        manifest = json.loads(self.run_manifest().stdout)
        self.assertIn(relative, {entry["path"] for entry in manifest["entries"]})

    def test_output_inside_instance_is_rejected(self) -> None:
        self.write_registry()
        self.seed_owned_files()
        self.run_manifest(
            "--output",
            str(self.instance / "q-system" / "output" / "manifest.json"),
            expect=1,
        )

    def test_symlinked_owned_ancestor_is_rejected(self) -> None:
        self.write_registry()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("external\n", encoding="utf-8")
        output = self.instance / "q-system" / "output"
        output.parent.mkdir(parents=True)
        output.symlink_to(outside, target_is_directory=True)
        (self.instance / ".gitignore").write_text(
            "/q-system/output/\n", encoding="utf-8"
        )
        git(self.instance, "add", ".gitignore")
        git(self.instance, "commit", "-qm", "ignore")
        self.run_manifest(expect=1)

    def test_empty_owned_directory_is_receipted(self) -> None:
        self.write_registry()
        self.seed_owned_files()
        empty = self.instance / "q-system" / "memory" / "empty-runtime"
        empty.mkdir(parents=True)
        manifest = json.loads(self.run_manifest().stdout)
        entry = {
            item["path"]: item for item in manifest["entries"]
        }["q-system/memory/empty-runtime"]
        self.assertEqual(entry["kind"], "directory")
        self.assertEqual(entry["tracking"], "filesystem-only")

    def test_unsupported_automation_contract_drift_fails_closed(self) -> None:
        self.write_registry()
        self.seed_owned_files()
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["instance_automation"]["excluded_relative_paths"].append("*.tmp")
        changed = self.root / "changed-contract.json"
        changed.write_text(json.dumps(contract), encoding="utf-8")
        self.run_manifest("--contract", str(changed), expect=1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--negative-layouts", action="store_true")
    args = parser.parse_args()
    if args.negative_layouts:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "instance").mkdir()
            (root / "skeleton").mkdir()
            git(root / "instance", "init", "-q")
            git(root / "skeleton", "init", "-q")
            registry = root / "registry.json"
            registry.write_text(
                json.dumps(
                    {
                        "instances": [
                            {
                                "name": "fixture",
                                "path": str(root / "instance"),
                                "subtree_prefix": "../escape",
                                "instance_q_dir": None,
                                "type": "subtree",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--contract",
                    str(CONTRACT),
                    "--registry",
                    str(registry),
                    "--instance-name",
                    "fixture",
                    "--repo-root",
                    str(root / "instance"),
                    "--skeleton-root",
                    str(root / "skeleton"),
                ],
                capture_output=True,
            )
            if result.returncode == 0:
                print("FAIL: unsafe layout was accepted", file=sys.stderr)
                return 1
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ManifestTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
