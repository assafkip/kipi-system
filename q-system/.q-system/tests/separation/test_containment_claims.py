import json
import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
PARENT_PRD = (
    REPO_ROOT
    / ".prd-os/prds/prd-skeleton-data-containment-2026-07-24.md"
)
UPDATER_ISSUE = (
    REPO_ROOT / ".prd-os/issues/fcu-dry-run-final-state.md"
)
UPDATER = REPO_ROOT / "kipi-update.sh"
RECEIPTS = REPO_ROOT / ".prd-os/receipts.jsonl"
REGISTRY = REPO_ROOT / "instance-registry.json"
DEPENDENCY_ID = "fcu-dry-run-final-state"
DEPENDENCY_PRD = "prd-fail-closed-fleet-updater-2026-07-24"


def frontmatter_value(path, key):
    content = path.read_text(encoding="utf-8")
    frontmatter = content.split("---", 2)[1]
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", frontmatter, re.M)
    assert match is not None
    return match.group(1).strip()


def verified_dependency_receipt():
    if frontmatter_value(UPDATER_ISSUE, "status") != "closed":
        return None

    for line in RECEIPTS.read_text(encoding="utf-8").splitlines():
        receipt = json.loads(line)
        if (
            receipt.get("issue_id") == DEPENDENCY_ID
            and receipt.get("prd_id") == DEPENDENCY_PRD
            and receipt.get("verified_at")
            and receipt.get("reviewed_at")
            and receipt.get("findings_triaged_at")
            and receipt.get("closed_at")
            and receipt.get("commit_sha")
        ):
            commit = receipt["commit_sha"]
            if re.fullmatch(r"[0-9a-f]{40}", commit) and subprocess.run(
                ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
            ).returncode == 0:
                return receipt
    return None


def propagation_contract(prd):
    match = re.search(
        r"^4\. Treat update propagation.+?(?=^5\.)",
        prd,
        re.M | re.S,
    )
    assert match is not None
    return match.group(0)


def rsync_command(updater, source):
    pattern = (
        rf"(?m)^\s*(?:CHANGED=\$\()?rsync [^\n]*{re.escape(source)}"
        rf".+?(?:2>/dev/null\)?)"
    )
    match = re.search(pattern, updater, re.S)
    assert match is not None
    return match.group(0)


def assert_storage_classification(contract):
    assert "storage separation breach, not proof of observed propagation" in contract


def assert_preventive_contract(contract):
    assert "Treat update propagation as preventive hardening." in contract
    assert "Block propagation proof on closed issue" in contract
    assert DEPENDENCY_ID in contract

    approved_negative = (
        "storage separation breach, not proof of observed propagation"
    )
    remaining_contract = contract.replace(approved_negative, "")
    proof_terms = (
        "observed",
        "confirmed",
        "proven",
        "verified",
        "demonstrated",
        "reproduced",
    )
    for term in proof_terms:
        assert re.search(
            rf"(?i)\b{term}\b.{{0,100}}\bpropagat\w*"
            rf"|\bpropagat\w*.{{0,100}}\b{term}\b",
            remaining_contract,
        ) is None
    assert re.search(
        r"(?i)\bpropagated\s+(?:to|across|into)\b|\bfleet\s+proof\b",
        remaining_contract,
    ) is None


def assert_updater_evidence():
    updater = UPDATER.read_text(encoding="utf-8")
    real_command = rsync_command(updater, '"$ARCHIVE_TMP/q-system/"')
    dry_command = rsync_command(updater, '"$DRY_TMP/q-system/"')

    assert "rsync -a --delete" in real_command
    assert '--exclude="/canonical/"' in real_command
    assert "rsync -ain --delete" in dry_command
    assert '--exclude="/canonical/"' in dry_command

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    managed_direct_clones = [
        instance["name"]
        for instance in registry["instances"]
        if instance.get("type") == "direct-clone"
    ]
    assert managed_direct_clones == []


def test_no_unproven_propagation_claim():
    prd = PARENT_PRD.read_text(encoding="utf-8")
    contract = propagation_contract(prd)

    assert_storage_classification(contract)
    assert_updater_evidence()
    receipt = verified_dependency_receipt()
    if receipt is None:
        assert_preventive_contract(contract)

        with pytest.raises(AssertionError):
            assert_preventive_contract(
                contract + "\nPropagation to every fleet instance is proven."
            )


def test_storage_and_propagation_have_distinct_evidence_labels():
    contract = propagation_contract(PARENT_PRD.read_text(encoding="utf-8"))

    assert_storage_classification(contract)
    if verified_dependency_receipt() is None:
        assert_preventive_contract(contract)


def test_current_updater_excludes_canonical_in_real_and_dry_paths():
    assert_updater_evidence()
