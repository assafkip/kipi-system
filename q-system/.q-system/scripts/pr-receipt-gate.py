#!/usr/bin/env python3
"""PR gate: an agent-authored PR cannot merge without a prd-os receipt.

Wired as a PR-only step in .github/workflows/validate.yml, next to the plugin
version-bump guard. Exit 0 = allow, exit 1 = refuse the merge, exit 2 = usage.

Why this exists (ASK-210). `linear-worker.sh` correctly tells the agent to stop
at "open a PR, do not merge -- closeout runs through /issue-verify and
/issue-closeout". Nothing invoked that closeout. On 2026-07-27 seven PRs merged
with ZERO entries in .prd-os/receipts.jsonl and no gate noticed: prd-os was
capture-only for Linear work (findings flowed in, completion was never proved).
This makes the ABSENCE of a receipt fatal at merge. It writes nothing -- receipt
production stays owned by kipi-dsse's issue_runner.

## What is gated, and what is not

Gated: branches matching `sana/ask-<number>` -- the shape `linear-worker.sh`
creates for agent-authored work. That is the population that merged unreceipted.

NOT gated, deliberately: every other branch (human PRs, chore branches, other
agent prefixes, main). They pass with an explicit "not gated" line on stdout
rather than silently, because a gate whose blind spot is undocumented reads as
full coverage. The alternative bootstrap (gate everything from a cutoff commit
forward) was rejected: it needs a cutoff nobody can see from the branch name,
and it would fail every PR open on the day this landed, including this one.

## Matching

The branch yields `ASK-<n>`; a receipt satisfies the gate when that token
appears in ANY string field of a well-formed receipt record, word-bounded and
case-insensitive. Any-field rather than `issue_id` only: the DSSE spec id is a
slug (`ask-210-receipt-gate`) and no convention yet pins WHERE the Linear id
lands, so pinning one key would make the gate brittle against a naming choice
that has not been made. Word-bounded so `ask-9990` cannot satisfy `ask-999`.

Lines that are not valid JSON are NOT receipts -- a raw-text fallback would let
`echo ASK-210 >> receipts.jsonl` clear the gate, which is exactly the synthetic
receipt the whole mechanism exists to refuse.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# The branch shape linear-worker.sh creates. A trailing slug is allowed
# (`sana/ask-210-receipt-gate`); the number is the id.
GATED_BRANCH_RE = re.compile(r"^sana/ask-(?P<num>\d+)(?:[-_/].*)?$", re.IGNORECASE)

DEFAULT_RECEIPTS = ".prd-os/receipts.jsonl"

CLOSEOUT_HELP = (
    "Produce one by running closeout for this issue, from the repo root:\n"
    "\n"
    "  python3 plugins/kipi-dsse/scripts/issue_runner.py load <issue-id>\n"
    "  python3 plugins/kipi-dsse/scripts/issue_runner.py close\n"
    "\n"
    "In an agent session that is /issue-verify then /issue-closeout, which\n"
    "drive the same runner. `close` appends the receipt; nothing else may.\n"
)


def repo_root() -> Path:
    """Resolve the repo root, falling back to cwd outside a git dir."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd()


def branch_for_pr(pr_number: str) -> str:
    """The PR's head branch, via gh.

    The branch -- not the PR body -- is the reliable source: the body is prose
    an agent writes, the branch is what the worker script created.
    """
    try:
        out = subprocess.run(
            ["gh", "pr", "view", pr_number, "--json", "headRefName",
             "-q", ".headRefName"],
            capture_output=True, text=True, timeout=60,
        )
    except OSError as exc:
        raise RuntimeError(f"cannot run gh: {exc}") from exc
    if out.returncode != 0:
        raise RuntimeError(
            f"gh pr view {pr_number} failed: {out.stderr.strip()[:300]}"
        )
    branch = out.stdout.strip()
    if not branch:
        raise RuntimeError(f"gh returned no head branch for PR {pr_number}")
    return branch


def issue_id_for_branch(branch: str):
    """`ASK-<n>` for a gated branch, else None (= not gated)."""
    match = GATED_BRANCH_RE.match(branch.strip())
    if not match:
        return None
    return f"ASK-{match.group('num')}"


def _strings(value):
    """Every string reachable in a decoded JSON value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def receipt_exists(receipts_path: Path, issue_id: str) -> bool:
    """True iff a well-formed receipt record carries issue_id in some string."""
    if not receipts_path.is_file():
        return False
    token = re.compile(rf"\b{re.escape(issue_id)}\b", re.IGNORECASE)
    malformed = 0
    with receipts_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if any(token.search(text) for text in _strings(record)):
                return True
    if malformed:
        print(
            f"receipt-gate: WARNING {malformed} unparseable line(s) in "
            f"{receipts_path}; they do not count as receipts.",
            file=sys.stderr,
        )
    return False


def refuse(issue_id: str, branch: str, receipts_path: Path) -> int:
    print(
        f"\nBLOCK: no prd-os receipt for {issue_id}.\n"
        "\n"
        f"  branch:   {branch}\n"
        f"  receipts: {receipts_path}\n"
        "\n"
        f"This PR claims to close {issue_id}, but nothing in the receipt ledger\n"
        f"proves the work was verified, reviewed, and triaged. Merging it would\n"
        "repeat 2026-07-27, when seven PRs landed with zero receipts.\n"
        "\n"
        + CLOSEOUT_HELP,
        file=sys.stderr,
    )
    return 1


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(
        description="Refuse an agent PR that carries no prd-os receipt.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pr", help="PR number; head branch resolved via gh")
    # CI passes --branch (github.head_ref is handed to the workflow for free),
    # which keeps the gate off the network and off a gh token.
    source.add_argument("--branch", help="head branch name, resolved already")
    parser.add_argument(
        "--receipts",
        help=f"receipt ledger (default: <repo-root>/{DEFAULT_RECEIPTS})",
    )
    args = parser.parse_args(argv[1:])

    if args.branch is not None:
        branch = args.branch
    else:
        try:
            branch = branch_for_pr(args.pr)
        except RuntimeError as exc:
            print(f"receipt-gate: {exc}", file=sys.stderr)
            return 2

    issue_id = issue_id_for_branch(branch)
    if issue_id is None:
        print(
            f"receipt-gate: '{branch}' is not gated. Only sana/ask-<n> branches "
            "(agent-authored Linear work) require a receipt; human and chore "
            "PRs are outside this gate's coverage."
        )
        return 0

    receipts_path = (
        Path(args.receipts) if args.receipts
        else repo_root() / DEFAULT_RECEIPTS
    )

    if receipt_exists(receipts_path, issue_id):
        print(f"receipt-gate: OK, receipt found for {issue_id}.")
        return 0

    return refuse(issue_id, branch, receipts_path)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
