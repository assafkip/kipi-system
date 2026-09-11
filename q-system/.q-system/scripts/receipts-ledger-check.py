#!/usr/bin/env python3
"""Gate the ONE .jsonl file allowed past blocked-paths, on content not on trust.

`.prd-os/receipts.jsonl` is the closure-evidence ledger. It is tracked (the
test that audits it cannot otherwise exist in a fresh clone) and it carries a
by-path exception in lefthook.yml's blocked-paths, which is otherwise a blanket
`*.jsonl` refusal covering session transcripts and secrets.

That exception is PERMANENT. The justification for it was a human reading the
file once on 2026-07-26 and finding only structural ids and timestamps. A
one-time read defending a permanent path is precisely the prompt-only
enforcement `q-system/CLAUDE.md` rule 3 forbids: a claim with no checker is not
enforcement. Adversarial review 2026-07-26 made the point concretely -- the repo
is PUBLIC, gitleaks only catches credential-SHAPED strings, and
validate-separation's containment sweep is rooted at `q-system/` so it never
looks at `.prd-os/` at all. A client-identifying issue slug would sail through
every existing gate.

So this is the checker. Closed allowlist: unknown keys, free text, paths,
emails, and anything with whitespace are refused. The producer
(`issue_runner.py::_append_receipt`) serializes a fixed 8-key dict, so a
conforming ledger stays conforming and a drifting one is caught at commit time.

WHAT THIS DOES NOT DO, stated plainly so nobody trusts it further than it goes:
it bounds the SHAPE, not the semantics. Free text, paths, emails, whitespace,
over-long values and unknown keys are refused. A client's name written as a
plain hyphenated slug (`chris-pi-onboarding`) is structurally indistinguishable
from any other issue id and WILL pass. Reducing the surface to "slugs the
founder chose" is the honest description of the protection; it is not a
semantic leak detector, and naming issues after clients remains a judgment call
the founder makes when creating them.

Exit 0 clean, exit 1 on any violation (lefthook pre-commit contract).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

LEDGER = ".prd-os/receipts.jsonl"

# Every key the producer emits. Anything else is drift and must be reviewed
# before it reaches a public repo.
ALLOWED_KEYS = {
    "prd_id",
    "finding_id",
    "issue_id",
    # ASK-210: the Linear issue the closeout branch belonged to, e.g. `ASK-210`.
    # Added here in the SAME change that taught issue_runner.py to emit it --
    # a producer key missing from this allowlist makes every closeout commit
    # die at pre-commit, which is a worse failure than the gate it unblocks.
    # The `_id` suffix means SLUG_RE already bounds it; a Linear identifier is
    # a team key plus digits, so it carries nothing identifying.
    "linear_issue_id",
    "closed_at",
    "commit_sha",
    "findings_triaged_at",
    "reviewed_at",
    "verified_at",
    # ASK-988 round 3 (codex): a close row for an issue that later REOPENED
    # kept downstream closure metrics counting unfinished work. A reopen is
    # recorded with its own timestamped row; same shape contract as closed_at,
    # no free text.
    "reopened_at",
    "receipts",
}
NESTED_RECEIPT_KEYS = {"findings_triaged", "reviewed", "verified"}

SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
MAX_VALUE_LEN = 120


def staged_ledger_lines() -> list[str] | None:
    """The staged content of the ledger, or None when it is not in this commit."""
    names = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    if LEDGER not in names:
        return None
    blob = subprocess.run(
        ["git", "show", f":{LEDGER}"], capture_output=True, text=True, check=False
    )
    if blob.returncode != 0:
        return []
    return blob.stdout.splitlines()


def check_value(where: str, key: str, value) -> list[str]:
    problems: list[str] = []
    if not isinstance(value, str):
        return [f"{where}: `{key}` is {type(value).__name__}, expected a string"]
    if len(value) > MAX_VALUE_LEN:
        problems.append(f"{where}: `{key}` is {len(value)} chars (max {MAX_VALUE_LEN})")
    if any(ch.isspace() for ch in value):
        problems.append(
            f"{where}: `{key}` contains whitespace -- structural ids never do, "
            "and free text is what leaks"
        )
    if "/" in value or "@" in value:
        problems.append(
            f"{where}: `{key}` looks like a path or address ({value!r}); the ledger "
            "carries ids and timestamps only"
        )
    if key.endswith("_at") and not ISO_RE.match(value):
        problems.append(f"{where}: `{key}`={value!r} is not an ISO-8601 timestamp")
    elif key == "commit_sha" and not SHA_RE.match(value):
        problems.append(f"{where}: `commit_sha`={value!r} is not a hex sha")
    elif key.endswith("_id") and not SLUG_RE.match(value):
        problems.append(f"{where}: `{key}`={value!r} is not a plain slug")
    return problems


def check_record(number: int, record) -> list[str]:
    where = f"{LEDGER} line {number}"
    if not isinstance(record, dict):
        return [f"{where}: expected a JSON object, got {type(record).__name__}"]
    problems: list[str] = []
    unknown = set(record) - ALLOWED_KEYS
    if unknown:
        problems.append(
            f"{where}: unknown key(s) {sorted(unknown)}. The ledger is a closed "
            "allowlist because it is committed to a PUBLIC repo; add the key here "
            "deliberately after checking it carries no identifying content."
        )
    for key, value in record.items():
        if key == "receipts":
            if not isinstance(value, dict):
                problems.append(f"{where}: `receipts` is not an object")
                continue
            nested_unknown = set(value) - NESTED_RECEIPT_KEYS
            if nested_unknown:
                problems.append(f"{where}: unknown receipts key(s) {sorted(nested_unknown)}")
            for nested_key, nested_value in value.items():
                problems.extend(check_value(where, f"receipts.{nested_key}", nested_value))
        elif key in ALLOWED_KEYS:
            problems.extend(check_value(where, key, value))
    return problems


def main() -> int:
    lines = staged_ledger_lines()
    if lines is None:
        return 0  # ledger not part of this commit
    problems: list[str] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(
                f"{LEDGER} line {number}: not valid JSON ({exc}). If these are merge "
                "conflict markers, resolve them -- the ledger uses merge=union so "
                "both sides' receipts are kept."
            )
            continue
        problems.extend(check_record(number, record))

    if problems:
        sys.stderr.write(
            "BLOCK: .prd-os/receipts.jsonl is the one .jsonl allowed past "
            "blocked-paths, and it is committed to a PUBLIC repo. It failed its "
            "content check:\n\n"
        )
        for problem in problems[:40]:
            sys.stderr.write(f"  - {problem}\n")
        if len(problems) > 40:
            sys.stderr.write(f"  ... and {len(problems) - 40} more\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
