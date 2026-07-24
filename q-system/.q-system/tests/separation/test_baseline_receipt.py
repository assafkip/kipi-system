import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
RECEIPT = (
    REPO_ROOT
    / "q-system/.q-system/tests/separation/fixtures/"
    "validate-separation-baseline.txt"
)
EXPECTED_KEYS = (
    "receipt_version",
    "command",
    "commit_sha",
    "timestamp_utc",
    "exit_code",
)
EXPECTED_SUMMARY = (
    "PASS: 70\n"
    "FAIL: 2\n"
    "WARN: 1\n"
    "FAILURES:\n"
    "- capability gate: declared-vs-actual diff + full test run exits 0\n"
    "- Repository-derived generic targets contain no semantic instance facts "
    "(11340 findings)\n"
    "GATE FAILED. Do not proceed to Phase 4."
)


def parse_receipt(content):
    header, separator, summary = content.partition("summary:\n")
    assert separator
    fields = {}
    for line in header.splitlines():
        key, value = line.split(": ", 1)
        assert key not in fields
        fields[key] = value
    assert tuple(fields) == EXPECTED_KEYS
    return fields, summary.rstrip("\n")


def commit_exists(commit_sha):
    return subprocess.run(
        ["git", "cat-file", "-e", f"{commit_sha}^{{commit}}"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    ).returncode == 0


def validate_receipt(content, commit_lookup=commit_exists):
    fields, summary = parse_receipt(content)
    assert fields["receipt_version"] == "1"
    assert fields["command"] == "python3 validate-separation.py 3"
    assert re.fullmatch(r"[0-9a-f]{40}", fields["commit_sha"])
    assert commit_lookup(fields["commit_sha"])

    timestamp = datetime.fromisoformat(
        fields["timestamp_utc"].replace("Z", "+00:00")
    )
    assert timestamp.tzinfo == timezone.utc
    assert fields["exit_code"] == "1"
    assert summary == EXPECTED_SUMMARY

    failure_lines = [
        line[2:]
        for line in summary.splitlines()
        if line.startswith("- ")
    ]
    assert len(failure_lines) == int(
        re.search(r"^FAIL: (\d+)$", summary, re.M).group(1)
    )
    return fields


def test_stale_or_unattributed_receipt_fails_closed():
    content = RECEIPT.read_text(encoding="utf-8")

    validate_receipt(content)

    stale = re.sub(
        r"(?m)^commit_sha: .+$",
        "commit_sha: " + ("0" * 40),
        content,
    )
    try:
        validate_receipt(stale)
    except AssertionError:
        pass
    else:
        raise AssertionError("nonexistent baseline commit was accepted")

    unattributed = content.replace(
        "- Repository-derived generic targets contain no semantic instance "
        "facts (11340 findings)\n",
        "",
    )
    try:
        validate_receipt(unattributed)
    except AssertionError:
        pass
    else:
        raise AssertionError("summary accepted an unreceipted failure count")


def test_receipt_records_only_observed_failure_summary():
    fields = validate_receipt(RECEIPT.read_text(encoding="utf-8"))

    assert fields["commit_sha"] == "3ec75a79fb1832911572d1ccd438baab1f86a486"
    assert fields["timestamp_utc"] == "2026-07-24T22:55:57Z"
    assert "missing q-system/AGENTS.md" not in EXPECTED_SUMMARY
    assert "pre-existing spillover" not in EXPECTED_SUMMARY
