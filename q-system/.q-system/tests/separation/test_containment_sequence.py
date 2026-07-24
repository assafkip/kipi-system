import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
ISSUES_DIR = REPO_ROOT / ".prd-os/issues"
RECEIPTS = REPO_ROOT / ".prd-os/receipts.jsonl"
DEPENDENCIES = {
    "sdc-owner-export": (
        "sdc-inventory-scope",
        "sdc-quarantine-rollback",
    ),
    "sdc-template-restoration": ("sdc-owner-export",),
    "sdc-update-propagation-proof": (
        "sdc-template-restoration",
        "fcu-dry-run-final-state",
    ),
}


def issue_status(issue_id):
    content = (ISSUES_DIR / f"{issue_id}.md").read_text(encoding="utf-8")
    match = re.search(r"(?m)^status:\s*(.+)$", content)
    assert match is not None
    return match.group(1).strip()


def receipt_index(receipts):
    return {
        receipt["issue_id"]: receipt
        for receipt in receipts
        if receipt.get("closed_at")
        and receipt.get("verified_at")
        and receipt.get("reviewed_at")
        and receipt.get("findings_triaged_at")
        and receipt.get("commit_sha")
    }


def can_start(issue_id, statuses, receipts):
    closed_receipts = receipt_index(receipts)
    return all(
        statuses.get(dependency) == "closed"
        and dependency in closed_receipts
        for dependency in DEPENDENCIES.get(issue_id, ())
    )


def repository_receipts():
    return [
        json.loads(line)
        for line in RECEIPTS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_refuses_out_of_order_execution():
    complete = {
        "closed_at": "2026-07-24T00:00:04Z",
        "verified_at": "2026-07-24T00:00:01Z",
        "reviewed_at": "2026-07-24T00:00:02Z",
        "findings_triaged_at": "2026-07-24T00:00:03Z",
        "commit_sha": "a" * 40,
    }
    owner_receipt = {"issue_id": "sdc-owner-export", **complete}
    updater_receipt = {"issue_id": "fcu-dry-run-final-state", **complete}

    assert not can_start(
        "sdc-template-restoration",
        {"sdc-owner-export": "open"},
        [owner_receipt],
    )
    assert not can_start(
        "sdc-template-restoration",
        {"sdc-owner-export": "closed"},
        [],
    )
    assert not can_start(
        "sdc-update-propagation-proof",
        {
            "sdc-template-restoration": "closed",
            "fcu-dry-run-final-state": "open",
        },
        [updater_receipt],
    )
    assert not can_start(
        "sdc-update-propagation-proof",
        {
            "sdc-template-restoration": "open",
            "fcu-dry-run-final-state": "closed",
        },
        [updater_receipt],
    )


def test_repository_sequence_allows_only_the_next_safe_step():
    statuses = {
        issue_id: issue_status(issue_id)
        for dependencies in DEPENDENCIES.values()
        for issue_id in dependencies
    }
    receipts = repository_receipts()

    assert can_start("sdc-owner-export", statuses, receipts)
    assert can_start("sdc-template-restoration", statuses, receipts)
    assert not can_start(
        "sdc-update-propagation-proof",
        statuses,
        receipts,
    )


def test_export_closed_after_inventory_and_quarantine():
    receipts = receipt_index(repository_receipts())
    export_closed_at = receipts["sdc-owner-export"]["closed_at"]

    assert receipts["sdc-inventory-scope"]["closed_at"] < export_closed_at
    assert receipts["sdc-quarantine-rollback"]["closed_at"] < export_closed_at
