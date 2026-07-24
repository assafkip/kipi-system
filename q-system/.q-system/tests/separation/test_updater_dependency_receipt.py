import json
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
DEPENDENCY_ID = "fcu-dry-run-final-state"
DEPENDENCY_PRD = "prd-fail-closed-fleet-updater-2026-07-24"
DEPENDENCY_SPEC = REPO_ROOT / ".prd-os/issues" / f"{DEPENDENCY_ID}.md"
PARENT_PRD = (
    REPO_ROOT
    / ".prd-os/prds/prd-skeleton-data-containment-2026-07-24.md"
)
RECEIPTS = REPO_ROOT / ".prd-os/receipts.jsonl"
REQUIRED_RECEIPT_FIELDS = (
    "verified_at",
    "reviewed_at",
    "findings_triaged_at",
    "closed_at",
    "commit_sha",
)


def frontmatter_value(content, key):
    frontmatter = content.split("---", 2)[1]
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", frontmatter, re.M)
    assert match is not None
    return match.group(1).strip()


def dependency_ready(spec_content, receipts, commit_exists):
    if frontmatter_value(spec_content, "id") != DEPENDENCY_ID:
        return False
    if frontmatter_value(spec_content, "parent_prd") != DEPENDENCY_PRD:
        return False
    if frontmatter_value(spec_content, "status") != "closed":
        return False

    matching = [
        receipt
        for receipt in receipts
        if receipt.get("issue_id") == DEPENDENCY_ID
        and receipt.get("prd_id") == DEPENDENCY_PRD
    ]
    if len(matching) != 1:
        return False

    receipt = matching[0]
    if any(not receipt.get(field) for field in REQUIRED_RECEIPT_FIELDS):
        return False
    commit_sha = receipt["commit_sha"]
    return bool(re.fullmatch(r"[0-9a-f]{40}", commit_sha)) and commit_exists(
        commit_sha
    )


def require_dependency_ready(spec_content, receipts, commit_exists):
    assert dependency_ready(
        spec_content,
        receipts,
        commit_exists,
    ), (
        f"{DEPENDENCY_ID} must be closed with one complete, attributed, "
        "commit-backed verification receipt before propagation proof"
    )


def repository_receipts():
    return [
        json.loads(line)
        for line in RECEIPTS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def repository_commit_exists(commit_sha):
    return subprocess.run(
        ["git", "cat-file", "-e", f"{commit_sha}^{{commit}}"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    ).returncode == 0


def complete_receipt():
    return {
        "issue_id": DEPENDENCY_ID,
        "prd_id": DEPENDENCY_PRD,
        "verified_at": "2026-07-24T00:00:00Z",
        "reviewed_at": "2026-07-24T00:00:01Z",
        "findings_triaged_at": "2026-07-24T00:00:02Z",
        "closed_at": "2026-07-24T00:00:03Z",
        "commit_sha": "a" * 40,
    }


def closed_spec():
    return (
        "---\n"
        f"id: {DEPENDENCY_ID}\n"
        "status: closed\n"
        f"parent_prd: {DEPENDENCY_PRD}\n"
        "---\n"
    )


def test_missing_or_open_dependency_blocks_propagation_proof():
    spec_content = DEPENDENCY_SPEC.read_text(encoding="utf-8")
    ready = dependency_ready(
        spec_content,
        repository_receipts(),
        repository_commit_exists,
    )

    if frontmatter_value(spec_content, "status") == "closed":
        assert ready
    else:
        assert not ready
        try:
            require_dependency_ready(
                spec_content,
                repository_receipts(),
                repository_commit_exists,
            )
        except AssertionError as error:
            assert DEPENDENCY_ID in str(error)
        else:
            raise AssertionError("open dependency did not block proof")


def test_missing_receipt_and_open_issue_fail_closed():
    open_spec = closed_spec().replace("status: closed", "status: open")

    assert not dependency_ready(open_spec, [complete_receipt()], lambda _: True)
    assert not dependency_ready(closed_spec(), [], lambda _: True)


def test_receipt_must_be_unique_complete_attributed_and_real():
    receipt = complete_receipt()

    assert dependency_ready(closed_spec(), [receipt], lambda _: True)
    assert not dependency_ready(
        closed_spec(), [receipt, receipt.copy()], lambda _: True
    )
    for field in REQUIRED_RECEIPT_FIELDS:
        incomplete = receipt.copy()
        incomplete.pop(field)
        assert not dependency_ready(
            closed_spec(), [incomplete], lambda _: True
        )
    wrong_prd = receipt.copy()
    wrong_prd["prd_id"] = "prd-unrelated"
    assert not dependency_ready(closed_spec(), [wrong_prd], lambda _: True)
    assert not dependency_ready(closed_spec(), [receipt], lambda _: False)


def test_parent_prd_names_exact_blocking_dependency():
    parent = PARENT_PRD.read_text(encoding="utf-8")

    assert "Block propagation proof on closed issue" in parent
    assert DEPENDENCY_ID in parent
    assert DEPENDENCY_PRD in parent
