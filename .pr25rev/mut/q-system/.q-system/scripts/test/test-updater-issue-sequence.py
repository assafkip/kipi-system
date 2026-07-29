#!/usr/bin/env python3
"""Order gate for the shared fail-closed updater work.

Three issues rewrite the SAME orchestration inside kipi-update.sh: the
preservation precondition, the exact-final-state dry run, and hook-safe
commits. They are only safe in one order. Preservation has to fail closed
BEFORE anything can rsync, the dry run has to model that already-failing-closed
path, and hook-safe commits then commit the state those two produce. Landing
them out of order ships a dry run that models a preservation path which does
not exist yet, or commits through hooks that were never taught to abort.

Nothing in git enforces that ordering by itself, so this is the deterministic
gate: the sequence is proven from closure receipts AND commit ancestry, and
every earlier step's own checks are rerun against the current tree so a later
step cannot quietly regress an earlier guarantee.

Modes:
  (default)              full gate: order + self-tests + cumulative check reruns
  --reject-out-of-order  order + self-tests only (the bypass proof)
  --fixture-root DIR     validate an arbitrary repo-shaped directory
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[4]

# The order is the contract. Index 0 must close first.
REQUIRED_SEQUENCE = (
    "fcu-preservation-precondition",
    "fcu-dry-run-final-state",
    "fcu-hook-safe-commits",
)


class SequenceError(AssertionError):
    """Raised when the gate itself cannot run (not an ordering violation)."""


def parse_frontmatter(text: str) -> dict:
    """Read the small, fixed YAML subset the issue specs actually use.

    Dependency-free on purpose: this test is a required check and must run on a
    bare instance with no PyYAML.
    """
    if not text.startswith("---\n"):
        raise SequenceError("spec has no frontmatter block")
    end = text.index("\n---", 3)
    fields: dict = {}
    current_list_key = None
    for raw in text[4:end].split("\n"):
        if not raw.strip():
            continue
        if raw.startswith("  - ") and current_list_key is not None:
            fields[current_list_key].append(unquote(raw[4:].strip()))
            continue
        if raw.startswith(" "):
            continue
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if value:
            fields[key] = unquote(value)
            current_list_key = None
        else:
            fields[key] = []
            current_list_key = key
    return fields


def unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read_spec(root: Path, issue_id: str) -> dict | None:
    spec = root / ".prd-os" / "issues" / f"{issue_id}.md"
    if not spec.is_file():
        return None
    return parse_frontmatter(spec.read_text(encoding="utf-8"))


def read_receipts(root: Path) -> tuple:
    """(latest closure receipt per issue id, ledger damage).

    A corrupt line is NOT skipped. Skipping one leaves an older receipt for the
    same issue authoritative, so a truncated ledger would silently downgrade to
    stale evidence instead of failing closed.
    """
    receipts_path = root / ".prd-os" / "receipts.jsonl"
    latest: dict = {}
    damage: list = []
    if not receipts_path.is_file():
        return latest, damage
    for number, line in enumerate(
        receipts_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            damage.append(f"receipts.jsonl line {number} is not valid JSON: {error}")
            continue
        if not isinstance(record, dict):
            damage.append(
                f"receipts.jsonl line {number} is a {type(record).__name__}, "
                "not a receipt object"
            )
            continue
        issue_id = record.get("issue_id")
        if not isinstance(issue_id, str) or not issue_id:
            damage.append(f"receipts.jsonl line {number} carries no issue_id")
            continue
        # Only a well-formed CLOSURE record counts. Taking the last physical
        # line for an issue would let any later ledger event with the same
        # issue_id stand in for closure evidence.
        closed_at = record.get("closed_at")
        commit_sha = record.get("commit_sha")
        if not isinstance(closed_at, str) or not isinstance(commit_sha, str):
            continue
        if not closed_at or not commit_sha:
            continue
        latest[issue_id] = record
    return latest, damage


def git_is_ancestor(root: Path, older: str, newer: str) -> bool:
    """True when `older` is a strict ancestor of `newer` in this repo."""
    if older == newer:
        return False
    result = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", older, newer],
        capture_output=True,
    )
    return result.returncode == 0


def parse_timestamp(value: str):
    """ISO-8601 receipt timestamp -> an aware datetime. Naive means UTC."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{value!r} is not a timestamp")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{value!r} is not ISO-8601: {error}") from error
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def git_reaches_head(root: Path, commit: str) -> bool:
    """True when `commit` is HEAD or an ancestor of it."""
    result = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", commit, "HEAD"],
        capture_output=True,
    )
    return result.returncode == 0


def validate_order(
    root: Path,
    sequence=REQUIRED_SEQUENCE,
    ancestry=git_is_ancestor,
    reaches_head=git_reaches_head,
) -> list:
    """Return every ordering violation. Empty list means the order holds."""
    errors = []
    receipts, damage = read_receipts(root)
    errors.extend(damage)
    previous_id = None
    previous_receipt = None
    for issue_id in sequence:
        spec = read_spec(root, issue_id)
        if spec is None:
            errors.append(f"{issue_id}: spec is missing")
            continue
        if spec.get("status") != "closed":
            errors.append(
                f"{issue_id}: status is {spec.get('status')!r}, not closed"
            )
        receipt = receipts.get(issue_id)
        if receipt is None:
            errors.append(f"{issue_id}: no closure receipt")
        if previous_id is not None and receipt is not None:
            if previous_receipt is None:
                errors.append(
                    f"{issue_id}: closed while {previous_id} has no receipt"
                )
            else:
                # Compare instants, not strings: two receipts written with
                # different UTC offsets sort the wrong way lexicographically.
                try:
                    this_at = parse_timestamp(receipt.get("closed_at", ""))
                    previous_at = parse_timestamp(previous_receipt.get("closed_at", ""))
                except ValueError as error:
                    errors.append(f"{issue_id}: unreadable closure timestamp: {error}")
                else:
                    if this_at <= previous_at:
                        errors.append(
                            f"out of order: {issue_id} closed at "
                            f"{receipt.get('closed_at')} but {previous_id} closed at "
                            f"{previous_receipt.get('closed_at')}"
                        )
                older = previous_receipt.get("commit_sha", "")
                newer = receipt.get("commit_sha", "")
                if not older or not newer:
                    errors.append(
                        f"{issue_id}: closure receipt carries no commit_sha"
                    )
                elif not ancestry(root, older, newer):
                    errors.append(
                        f"out of order: {previous_id} commit {older[:8]} is not an "
                        f"ancestor of {issue_id} commit {newer[:8]}"
                    )
        # Pairwise ancestry alone is satisfied by a linear chain on a side
        # branch that never landed. Every closure commit must also be reachable
        # from the HEAD this gate is being run against.
        if receipt is not None:
            commit = receipt.get("commit_sha", "")
            if commit and not reaches_head(root, commit):
                errors.append(
                    f"{issue_id}: closure commit {commit[:8]} is not reachable "
                    "from HEAD"
                )
            previous_id = issue_id
            previous_receipt = receipt
    return errors


def cumulative_checks(root: Path, sequence=REQUIRED_SEQUENCE) -> list:
    """[(issue_id, commit_sha, [checks of this step and every earlier step])]."""
    receipts, _damage = read_receipts(root)
    plan = []
    running: list = []
    for issue_id in sequence:
        spec = read_spec(root, issue_id)
        if spec is None:
            raise SequenceError(f"{issue_id}: spec is missing")
        receipt = receipts.get(issue_id)
        if receipt is None or not receipt.get("commit_sha"):
            raise SequenceError(f"{issue_id}: no closure commit to check out")
        step_checks = list(spec.get("required_checks") or [])
        bypass = spec.get("bypass_check")
        if bypass:
            step_checks.append(bypass)
        for check in step_checks:
            if check not in running:
                running.append(check)
        plan.append((issue_id, receipt["commit_sha"], list(running)))
    return plan


def assert_archive_fidelity(root: Path, commit: str) -> None:
    """Refuse to check a step whose tree `git archive` would not reproduce.

    archive is not checkout: export-ignore and export-subst rewrite content and
    submodules come out empty. Rather than quietly testing a transformed tree,
    fail closed when either mechanism is present at that commit.
    """
    listing = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "--name-only", commit],
        capture_output=True,
        text=True,
    )
    if listing.returncode != 0:
        raise SequenceError(f"could not list {commit[:8]}: {listing.stderr.strip()}")
    paths = listing.stdout.splitlines()
    modules = [name for name in paths if Path(name).name == ".gitmodules"]
    if modules:
        raise SequenceError(
            f"{commit[:8]} carries submodules ({modules[0]}); git archive would "
            "not reproduce its tree"
        )
    for name in [name for name in paths if Path(name).name == ".gitattributes"]:
        content = subprocess.run(
            ["git", "-C", str(root), "show", f"{commit}:{name}"],
            capture_output=True,
            text=True,
        )
        if content.returncode != 0:
            raise SequenceError(f"could not read {name} at {commit[:8]}")
        for attribute in ("export-ignore", "export-subst"):
            if attribute in content.stdout:
                raise SequenceError(
                    f"{commit[:8]} declares {attribute} in {name}; git archive "
                    "would not reproduce its tree"
                )


def extract_commit(root: Path, commit: str, destination: Path) -> None:
    """Materialize the tracked tree of `commit` into `destination`."""
    assert_archive_fidelity(root, commit)
    archive = subprocess.run(
        ["git", "-C", str(root), "archive", "--format=tar", commit],
        capture_output=True,
    )
    if archive.returncode != 0:
        raise SequenceError(
            f"could not archive {commit[:8]}: {archive.stderr.decode(errors='replace')}"
        )
    unpack = subprocess.run(
        ["tar", "-x", "-C", str(destination)], input=archive.stdout, capture_output=True
    )
    if unpack.returncode != 0:
        raise SequenceError(
            f"could not unpack {commit[:8]}: {unpack.stderr.decode(errors='replace')}"
        )


def run_cumulative_checks(root: Path, plan: list) -> list:
    """Rerun every earlier step's checks AT each step's own commit.

    Running them against the current tree only would prove the final state is
    healthy -- a check that was broken when step two landed and repaired by
    step three would still pass. Each step is therefore checked out into a
    throwaway tree and its cumulative check set runs there, which is what makes
    the ordering claim mean anything.
    """
    failures = []
    for issue_id, commit, checks in plan:
        print(f"  step {issue_id} at {commit[:8]}: {len(checks)} check(s)")
        with tempfile.TemporaryDirectory() as work:
            tree = Path(work)
            try:
                extract_commit(root, commit, tree)
            except SequenceError as error:
                failures.append(f"{issue_id}: {error}")
                continue
            for check in checks:
                completed = subprocess.run(
                    shlex.split(check), cwd=str(tree), capture_output=True, text=True
                )
                status = "PASS" if completed.returncode == 0 else "FAIL"
                print(f"    {status}: {check}")
                if completed.returncode != 0:
                    failures.append(f"{issue_id}@{commit[:8]}: check failed: {check}")
                    tail = (completed.stdout + completed.stderr).strip().splitlines()
                    for line in tail[-5:]:
                        print(f"      {line}")
    return failures


def write_fixture(root: Path, steps: list, corrupt: str = "") -> None:
    """steps: [(issue_id, status, closed_at, commit_sha_or_None)]."""
    issues = root / ".prd-os" / "issues"
    issues.mkdir(parents=True, exist_ok=True)
    receipts = []
    for issue_id, status, closed_at, commit_sha in steps:
        (issues / f"{issue_id}.md").write_text(
            "---\n"
            f"id: {issue_id}\n"
            f"status: {status}\n"
            "required_checks:\n"
            "  - true\n"
            'bypass_check: "true"\n'
            "---\n\nbody\n",
            encoding="utf-8",
        )
        if commit_sha is not None:
            receipts.append(
                json.dumps(
                    {
                        "issue_id": issue_id,
                        "closed_at": closed_at,
                        "commit_sha": commit_sha,
                    }
                )
            )
    if corrupt:
        receipts.append(corrupt)
    (root / ".prd-os" / "receipts.jsonl").write_text(
        "\n".join(receipts) + ("\n" if receipts else ""), encoding="utf-8"
    )


def run_self_tests() -> list:
    """Prove the order gate rejects what it claims to reject.

    A gate that only ever sees a compliant repo is indistinguishable from a
    gate that returns 0 unconditionally. These fixtures are the difference.
    """
    failures = []
    sequence = ("step-one", "step-two", "step-three")
    linear = {"step-one": "a" * 40, "step-two": "b" * 40, "step-three": "c" * 40}

    def linear_ancestry(_root, older, newer):
        order = list(linear.values())
        return older in order and newer in order and order.index(older) < order.index(newer)

    def reachable(_root, _commit):
        return True

    ordered_steps = [
        ("step-one", "closed", "2026-07-24T01:00:00Z", linear["step-one"]),
        ("step-two", "closed", "2026-07-24T02:00:00Z", linear["step-two"]),
        ("step-three", "closed", "2026-07-24T03:00:00Z", linear["step-three"]),
    ]

    extra_cases = [
        (
            "a closure commit unreachable from HEAD is rejected",
            ordered_steps,
            linear_ancestry,
            lambda _root, _commit: False,
            "",
            "not reachable from HEAD",
        ),
        (
            "a corrupt receipt ledger is rejected",
            ordered_steps,
            linear_ancestry,
            reachable,
            '{"issue_id": "step-three", "closed_at":',
            "not valid JSON",
        ),
        (
            "a non-object ledger line is rejected",
            ordered_steps,
            linear_ancestry,
            reachable,
            '["step-three", "closed"]',
            "not a receipt object",
        ),
        (
            "a later non-closure record cannot supersede closure evidence",
            ordered_steps,
            linear_ancestry,
            reachable,
            '{"issue_id": "step-one", "note": "reopened for review"}',
            None,
        ),
        (
            # Lexicographically ordered, chronologically reversed.
            "offset-shifted timestamps are compared as instants",
            [
                ("step-one", "closed", "2026-07-24T01:00:00-12:00", linear["step-one"]),
                ("step-two", "closed", "2026-07-24T02:00:00+14:00", linear["step-two"]),
                ("step-three", "closed", "2026-07-25T03:00:00Z", linear["step-three"]),
            ],
            linear_ancestry,
            reachable,
            "",
            "out of order",
        ),
    ]

    cases = [
        (
            "compliant order is accepted",
            [
                ("step-one", "closed", "2026-07-24T01:00:00Z", linear["step-one"]),
                ("step-two", "closed", "2026-07-24T02:00:00Z", linear["step-two"]),
                ("step-three", "closed", "2026-07-24T03:00:00Z", linear["step-three"]),
            ],
            linear_ancestry,
            None,
        ),
        (
            "reversed closure timestamps are rejected",
            [
                ("step-one", "closed", "2026-07-24T09:00:00Z", linear["step-one"]),
                ("step-two", "closed", "2026-07-24T02:00:00Z", linear["step-two"]),
                ("step-three", "closed", "2026-07-24T03:00:00Z", linear["step-three"]),
            ],
            linear_ancestry,
            "out of order",
        ),
        (
            "an unclosed earlier step is rejected",
            [
                ("step-one", "in-progress", "2026-07-24T01:00:00Z", linear["step-one"]),
                ("step-two", "closed", "2026-07-24T02:00:00Z", linear["step-two"]),
                ("step-three", "closed", "2026-07-24T03:00:00Z", linear["step-three"]),
            ],
            linear_ancestry,
            "not closed",
        ),
        (
            "a missing closure receipt is rejected",
            [
                ("step-one", "closed", "2026-07-24T01:00:00Z", None),
                ("step-two", "closed", "2026-07-24T02:00:00Z", linear["step-two"]),
                ("step-three", "closed", "2026-07-24T03:00:00Z", linear["step-three"]),
            ],
            linear_ancestry,
            "no closure receipt",
        ),
        (
            "a missing spec is rejected",
            [
                ("step-two", "closed", "2026-07-24T02:00:00Z", linear["step-two"]),
                ("step-three", "closed", "2026-07-24T03:00:00Z", linear["step-three"]),
            ],
            linear_ancestry,
            "spec is missing",
        ),
        (
            "a non-ancestor commit is rejected",
            [
                ("step-one", "closed", "2026-07-24T01:00:00Z", linear["step-one"]),
                ("step-two", "closed", "2026-07-24T02:00:00Z", linear["step-two"]),
                ("step-three", "closed", "2026-07-24T03:00:00Z", linear["step-three"]),
            ],
            lambda _root, _older, _newer: False,
            "is not an ancestor of",
        ),
    ]

    normalized = [
        (name, steps, ancestry, reachable, "", expected)
        for name, steps, ancestry, expected in cases
    ] + extra_cases

    for name, steps, ancestry, reaches_head, corrupt, expected in normalized:
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            write_fixture(root, steps, corrupt)
            errors = validate_order(
                root,
                sequence=sequence,
                ancestry=ancestry,
                reaches_head=reaches_head,
            )
            if expected is None:
                if errors:
                    failures.append(f"self-test '{name}': unexpected errors {errors}")
            elif not any(expected in error for error in errors):
                failures.append(
                    f"self-test '{name}': expected an error containing "
                    f"{expected!r}, got {errors}"
                )
        print(f"  self-test: {name}")

    # The real git ancestry probe, not a stub: two roots are never ordered.
    with tempfile.TemporaryDirectory() as work:
        root = Path(work)
        env_git = ["git", "-C", str(root), "-c", "user.email=t@e", "-c", "user.name=t"]
        subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
        (root / "a.txt").write_text("a\n", encoding="utf-8")
        subprocess.run(env_git + ["add", "-A"], check=True, capture_output=True)
        subprocess.run(env_git + ["commit", "-qm", "a"], check=True, capture_output=True)
        first = subprocess.run(
            env_git + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
        subprocess.run(
            env_git + ["checkout", "-q", "--orphan", "other"], check=True, capture_output=True
        )
        (root / "b.txt").write_text("b\n", encoding="utf-8")
        subprocess.run(env_git + ["add", "-A"], check=True, capture_output=True)
        subprocess.run(env_git + ["commit", "-qm", "b"], check=True, capture_output=True)
        second = subprocess.run(
            env_git + ["rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
        if git_is_ancestor(root, first, second):
            failures.append("self-test: unrelated roots reported as ancestors")
        if git_is_ancestor(root, first, first):
            failures.append("self-test: a commit reported as its own strict ancestor")
        print("  self-test: git ancestry probe rejects unrelated commits")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reject-out-of-order",
        action="store_true",
        help="prove the order gate rejects violations; skip the check reruns",
    )
    parser.add_argument(
        "--fixture-root",
        default=None,
        help="validate an arbitrary repo-shaped directory instead of this repo",
    )
    args = parser.parse_args()

    root = Path(args.fixture_root).resolve() if args.fixture_root else REPO_ROOT

    print("Self-tests (the gate must be able to fail):")
    failures = run_self_tests()

    print(f"Order of {' -> '.join(REQUIRED_SEQUENCE)}:")
    order_errors = validate_order(root)
    for error in order_errors:
        print(f"  ERROR: {error}")
    if not order_errors:
        print("  ordered: receipts and commit ancestry agree")
    failures.extend(order_errors)

    if args.reject_out_of_order:
        # The required check runs the cumulative suite in the same verify pass;
        # rerunning it here would only double the wall clock against an
        # identical tree. Stated, not silently dropped.
        print("Cumulative checks: skipped (covered by the required check)")
    else:
        print("Cumulative prior checks rerun at each step:")
        try:
            plan = cumulative_checks(root)
        except SequenceError as error:
            failures.append(str(error))
        else:
            failures.extend(run_cumulative_checks(root, plan))

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    if args.reject_out_of_order:
        print("PASS: the order gate rejects every out-of-order shape it claims to")
    else:
        print("PASS: updater issues landed in order and every prior check still holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
