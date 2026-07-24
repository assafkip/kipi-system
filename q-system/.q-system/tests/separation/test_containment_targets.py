import importlib.util
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
TARGETS_SCRIPT = (
    REPO_ROOT / "q-system/.q-system/scripts/containment-targets.py"
)
VALIDATOR_SCRIPT = REPO_ROOT / "validate-separation.py"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
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
def generic_repo(tmp_path):
    git(tmp_path, "init")
    files = {
        "AGENTS.md": "# Generic instructions\n",
        "q-system/canonical/discovery.md": (
            "# Discovery\n\n- **Client:** {{CLIENT_NAME}}\n"
        ),
        "q-system/output/private.md": "- **Client:** Private Output\n",
        "q-system/memory/private.md": "- **Client:** Private Memory\n",
        ".prd-os/issues/private.md": "- **Client:** PRD State\n",
        "plugins/kipi-core/README.md": "# Generic plugin\n",
        ".claude/rules/generic.md": "# Generic rule\n",
        "docs/new-generic-surface.md": "# Generic documentation\n",
    }
    for relative_path, content in files.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    binary = tmp_path / "plugins/kipi-core/generated/logo.png"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00")
    git(tmp_path, "add", ".")
    return tmp_path


def test_new_tracked_surface_is_discovered_and_semantically_checked(
    generic_repo,
):
    targets = load_module("containment_targets", TARGETS_SCRIPT)
    validator = load_module("validate_separation_targets", VALIDATOR_SCRIPT)
    new_surface = generic_repo / "new-generic/new-surface.md"
    new_surface.parent.mkdir(parents=True)
    new_surface.write_text(
        (
            "# Added later\n\n"
            "- **Client:** Cedar Observatory\n"
            "- **Engagement detail:** Requested private deployment\n"
        ),
        encoding="utf-8",
    )
    git(generic_repo, "add", "new-generic/new-surface.md")

    manifest = targets.enumerate_containment_targets(generic_repo)
    violations = validator.semantic_separation_violations(generic_repo)

    assert "new-generic/new-surface.md" in manifest["targets"]
    assert {
        "fact_class": "client_identity",
        "line": 3,
        "path": "new-generic/new-surface.md",
    } in violations
    assert {
        "fact_class": "unclassified_populated_record",
        "line": 4,
        "path": "new-generic/new-surface.md",
    } in violations


def test_untracked_surface_is_not_a_containment_target(generic_repo):
    targets = load_module("containment_targets_untracked", TARGETS_SCRIPT)
    path = generic_repo / "q-system/canonical/untracked.md"
    path.write_text("- **Client:** Not Shipped\n", encoding="utf-8")

    manifest = targets.enumerate_containment_targets(generic_repo)

    assert "q-system/canonical/untracked.md" not in manifest["targets"]


def test_exclusions_are_explicit_and_deterministic(generic_repo):
    targets = load_module("containment_targets_exclusions", TARGETS_SCRIPT)

    manifest = targets.enumerate_containment_targets(generic_repo)
    exclusions = {
        item["path"]: item["reason"] for item in manifest["excluded"]
    }

    assert exclusions[".prd-os/issues/private.md"] == "prd-os-state"
    assert exclusions["q-system/output/private.md"] == "instance-output"
    assert exclusions["q-system/memory/private.md"] == "instance-memory"
    assert exclusions["plugins/kipi-core/generated/logo.png"] == (
        "generated-or-binary-asset"
    )
    assert "docs/new-generic-surface.md" in manifest["targets"]
    assert manifest["target_source"] == "git-ls-files"


def test_tracked_non_utf8_content_is_classified_as_binary(generic_repo):
    targets = load_module("containment_targets_non_utf8", TARGETS_SCRIPT)
    path = generic_repo / "plugins/kipi-core/generated/raw.dat"
    path.write_bytes(b"\xff\xfe\xfd")
    git(generic_repo, "add", "plugins/kipi-core/generated/raw.dat")

    manifest = targets.enumerate_containment_targets(generic_repo)

    assert {
        "path": "plugins/kipi-core/generated/raw.dat",
        "reason": "generated-or-binary-asset",
    } in manifest["excluded"]


def test_text_with_binary_extension_cannot_bypass(generic_repo):
    targets = load_module("containment_targets_spoof", TARGETS_SCRIPT)
    validator = load_module("validate_separation_spoof", VALIDATOR_SCRIPT)
    path = generic_repo / "plugins/kipi-core/generated/client.pdf"
    path.write_text("- **Client:** Extension Spoof\n", encoding="utf-8")
    git(generic_repo, "add", "plugins/kipi-core/generated/client.pdf")

    manifest = targets.enumerate_containment_targets(generic_repo)
    violations = validator.semantic_separation_violations(generic_repo)

    assert "plugins/kipi-core/generated/client.pdf" in manifest["targets"]
    assert {
        "fact_class": "client_identity",
        "line": 1,
        "path": "plugins/kipi-core/generated/client.pdf",
    } in violations


def test_nul_appended_to_text_cannot_bypass(generic_repo):
    targets = load_module("containment_targets_nul_text", TARGETS_SCRIPT)
    validator = load_module("validate_separation_nul_text", VALIDATOR_SCRIPT)
    path = generic_repo / "plugins/kipi-core/generated/client.md"
    path.write_bytes(b"- **Client:** Nul Spoof\n\x00")
    git(generic_repo, "add", "plugins/kipi-core/generated/client.md")

    manifest = targets.enumerate_containment_targets(generic_repo)
    violations = validator.semantic_separation_violations(generic_repo)

    assert "plugins/kipi-core/generated/client.md" in manifest["targets"]
    assert {
        "fact_class": "client_identity",
        "line": 1,
        "path": "plugins/kipi-core/generated/client.md",
    } in violations


def test_unapproved_fixture_path_cannot_claim_synthetic_bypass(
    generic_repo,
):
    validator = load_module(
        "validate_separation_fixture_provenance",
        VALIDATOR_SCRIPT,
    )
    path = generic_repo / "plugins/kipi-core/fixtures/claimed.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "fixture: synthetic\n- **Client:** Hidden Leak\n",
        encoding="utf-8",
    )
    git(generic_repo, "add", "plugins/kipi-core/fixtures/claimed.md")

    violations = validator.semantic_separation_violations(generic_repo)

    assert {
        "fact_class": "client_identity",
        "line": 2,
        "path": "plugins/kipi-core/fixtures/claimed.md",
    } in violations


def test_semantic_gate_reads_index_not_safe_worktree_replacement(
    generic_repo,
):
    validator = load_module(
        "validate_separation_index_content",
        VALIDATOR_SCRIPT,
    )
    path = generic_repo / "q-system/canonical/discovery.md"
    path.write_text("- **Client:** Indexed Leak\n", encoding="utf-8")
    git(generic_repo, "add", "q-system/canonical/discovery.md")
    path.write_text("- **Client:** {{CLIENT_NAME}}\n", encoding="utf-8")

    violations = validator.semantic_separation_violations(generic_repo)

    assert {
        "fact_class": "client_identity",
        "line": 1,
        "path": "q-system/canonical/discovery.md",
    } in violations


def test_missing_worktree_file_does_not_hide_indexed_leak(generic_repo):
    targets = load_module("containment_targets_missing", TARGETS_SCRIPT)
    validator = load_module(
        "validate_separation_missing_worktree",
        VALIDATOR_SCRIPT,
    )
    path = generic_repo / "q-system/canonical/discovery.md"
    path.write_text("- **Client:** Indexed Leak\n", encoding="utf-8")
    git(generic_repo, "add", "q-system/canonical/discovery.md")
    path.unlink()

    manifest = targets.enumerate_containment_targets(generic_repo)
    violations = validator.semantic_separation_violations(generic_repo)

    assert "q-system/canonical/discovery.md" in manifest["targets"]
    assert {
        "fact_class": "client_identity",
        "line": 1,
        "path": "q-system/canonical/discovery.md",
    } in violations


def test_index_addition_invalidates_prior_manifest(generic_repo):
    targets = load_module(
        "containment_targets_index_change",
        TARGETS_SCRIPT,
    )
    manifest = targets.enumerate_containment_targets(generic_repo)
    path = generic_repo / "q-system/canonical/added-later.md"
    path.write_text("- **Client:** Late Index Addition\n", encoding="utf-8")
    git(generic_repo, "add", "q-system/canonical/added-later.md")

    with pytest.raises(
        targets.ContainmentScopeBlocked,
        match="index changed",
    ):
        targets.assert_index_unchanged(
            generic_repo,
            manifest["index_sha256"],
        )


def test_git_enumeration_failure_blocks_instead_of_returning_empty(tmp_path):
    targets = load_module("containment_targets_failure", TARGETS_SCRIPT)

    with pytest.raises(targets.ContainmentScopeBlocked):
        targets.enumerate_containment_targets(tmp_path)
