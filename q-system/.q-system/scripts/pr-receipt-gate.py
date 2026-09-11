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

The branch yields `ASK-<n>` via `plugins/kipi-dsse/scripts/linear_branch.py` --
the SAME module `issue_runner.py::cmd_close` uses to stamp `linear_issue_id`
onto the receipt it writes. That import is deliberately hard: this gate has no
private copy of the convention to fall back on. Review round 3 of ASK-210 found
the gate carrying its own regex while the producer wrote no Linear id at all,
so the gate blocked 100% of its target population and the closeout it told the
operator to run could not clear it. One module, one meaning.

A receipt satisfies the gate when the id appears in ANY string field of a
well-formed record, word-bounded and case-insensitive. Any-field rather than
`linear_issue_id` only: a DSSE spec deliberately named for its Linear issue
(`ask-210-receipt-gate`) is equally good proof, and `receipts-ledger-check.py`
is a closed key allowlist at pre-commit, so no field this scans got into the
ledger unreviewed.

Lines that are not valid JSON are NOT receipts -- a raw-text fallback would let
`echo ASK-210 >> receipts.jsonl` clear the gate, which is exactly the synthetic
receipt the whole mechanism exists to refuse.

## Coverage: a receipt proves a commit, not a branch

`linear-worker.sh:328` reuses the same branch and PR across REWORK rounds, so
existence alone would mean one closeout clears every later push forever. With
`--head-sha`, a receipt only counts when its `commit_sha` is an ancestor of the
head AND nothing outside `.prd-os/` landed after it -- the ledger commit the
operator makes right after closeout is expected; new source is not. The
remediation is real: `cmd_load` does not refuse a spec whose status is already
closed, so the flow can be re-run for the new head (pinned end-to-end by
test-receipt-gate-closeout-e2e.sh case 7).

Without `--head-sha` the gate checks existence only and SAYS SO on stdout.
CI always passes it; a local invocation may not.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_RECEIPTS = ".prd-os/receipts.jsonl"

# Everything a closeout is allowed to add on top of the commit its receipt
# pinned. `close` rewrites the spec's status, appends the receipt, and registers
# bypass gates -- all under .prd-os/. Anything else is work the receipt does not
# cover.
LEDGER_PREFIX = ".prd-os/"

CLOSEOUT_HELP = (
    "Produce one by running closeout for this issue, from the repo root:\n"
    "\n"
    "  python3 plugins/kipi-dsse/scripts/issue_runner.py load <issue-id>\n"
    "  python3 plugins/kipi-dsse/scripts/issue_runner.py close\n"
    "  git add .prd-os && git commit -m 'closeout receipt' && git push\n"
    "\n"
    "In an agent session the first two are /issue-verify then /issue-closeout,\n"
    "which drive the same runner. `close` appends the receipt; nothing else may.\n"
    "The commit and push are not optional: `close` writes into the working tree\n"
    "and CI reads the PUSHED head, so stopping after `close` leaves CI red.\n"
)


def _load_branch_convention():
    """Import the shared branch->Linear-id mapping, or die loudly.

    No fallback copy on purpose. A private regex here is how this gate and its
    producer drifted into disagreeing in the first place; failing to start is a
    better outcome than silently enforcing a second, different convention.
    """
    scripts_dir = Path(__file__).resolve().parents[3] / "plugins/kipi-dsse/scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        from linear_branch import issue_id_for_branch  # noqa: E402
    except ImportError as exc:
        raise RuntimeError(
            f"cannot import the branch convention from {scripts_dir}: {exc}. "
            "This gate shares that module with issue_runner.py so the two "
            "cannot disagree; it has no private copy to fall back on."
        ) from exc
    return issue_id_for_branch


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


def matching_receipts(receipts_path: Path, issue_id: str) -> list:
    """Every well-formed receipt record carrying issue_id in some string."""
    if not receipts_path.is_file():
        return []
    token = re.compile(rf"\b{re.escape(issue_id)}\b", re.IGNORECASE)
    found = []
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
                found.append(record)
    if malformed:
        print(
            f"receipt-gate: WARNING {malformed} unparseable line(s) in "
            f"{receipts_path}; they do not count as receipts.",
            file=sys.stderr,
        )
    return found


def _git(args: list, cwd: Path):
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def uncovered_paths(receipt_sha: str, head_sha: str, cwd: Path):
    """Paths changed between the receipt's commit and the head, ledger excluded.

    Returns None when the receipt's commit cannot be shown to cover the head at
    all (unknown object, or not an ancestor -- a force-push or a receipt written
    on a different line of history). An empty list means full coverage.
    """
    for sha in (receipt_sha, head_sha):
        exists = _git(["cat-file", "-e", f"{sha}^{{commit}}"], cwd)
        if exists is None or exists.returncode != 0:
            return None
    if receipt_sha == head_sha:
        return []
    ancestor = _git(["merge-base", "--is-ancestor", receipt_sha, head_sha], cwd)
    if ancestor is None or ancestor.returncode != 0:
        return None
    diff = _git(["diff", "--name-only", receipt_sha, head_sha], cwd)
    if diff is None or diff.returncode != 0:
        return None
    return [
        path for path in diff.stdout.splitlines()
        if path.strip() and not path.startswith(LEDGER_PREFIX)
    ]


def refuse_missing(issue_id: str, branch: str, receipts_path: Path) -> int:
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


def refuse_stale(issue_id, branch, head_sha, reasons) -> int:
    detail = "\n".join(f"  - {line}" for line in reasons)
    print(
        f"\nBLOCK: a receipt for {issue_id} exists but does not cover this head.\n"
        "\n"
        f"  branch:   {branch}\n"
        f"  head:     {head_sha}\n"
        "\n"
        f"{detail}\n"
        "\n"
        "A receipt proves the commit it pinned, not every commit later pushed to\n"
        "the same branch. linear-worker.sh reuses the branch and the PR across\n"
        "REWORK rounds, so without this check one closeout would clear every\n"
        "later push forever.\n"
        "\n"
        "Re-run closeout against the current head -- `load` does not refuse an\n"
        "already-closed spec, so the same flow runs again:\n"
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
        "--head-sha",
        help="PR head commit; enables the coverage check (CI passes "
             "github.event.pull_request.head.sha). Omitted = existence only.",
    )
    parser.add_argument(
        "--receipts",
        help=f"receipt ledger (default: <repo-root>/{DEFAULT_RECEIPTS})",
    )
    args = parser.parse_args(argv[1:])

    try:
        issue_id_for_branch = _load_branch_convention()
    except RuntimeError as exc:
        print(f"receipt-gate: {exc}", file=sys.stderr)
        return 2

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

    candidates = matching_receipts(receipts_path, issue_id)
    if not candidates:
        return refuse_missing(issue_id, branch, receipts_path)

    if not args.head_sha:
        # Say the reduced coverage out loud. A gate that quietly checks less
        # than its name implies is the failure mode this whole issue is about.
        print(
            f"receipt-gate: OK, receipt found for {issue_id}. "
            "(existence only -- no --head-sha, so whether the receipt covers "
            "the pushed head was NOT checked.)"
        )
        return 0

    cwd = repo_root()
    reasons = []
    for record in candidates:
        sha = record.get("commit_sha")
        if not isinstance(sha, str) or not sha:
            reasons.append(
                f"receipt {record.get('issue_id', '?')} carries no commit_sha, "
                "so what it covers cannot be established"
            )
            continue
        changed = uncovered_paths(sha, args.head_sha, cwd)
        if changed is None:
            reasons.append(
                f"receipt {record.get('issue_id', '?')} pins {sha[:12]}, which is "
                "not an ancestor of this head (rebased, force-pushed, or written "
                "on another branch)"
            )
            continue
        if not changed:
            print(
                f"receipt-gate: OK, receipt for {issue_id} covers {args.head_sha[:12]} "
                f"(pinned {sha[:12]}, nothing but {LEDGER_PREFIX} on top)."
            )
            return 0
        shown = ", ".join(changed[:5]) + ("..." if len(changed) > 5 else "")
        reasons.append(
            f"receipt {record.get('issue_id', '?')} pins {sha[:12]}, but "
            f"{len(changed)} file(s) changed after it: {shown}"
        )

    return refuse_stale(issue_id, branch, args.head_sha, reasons)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
