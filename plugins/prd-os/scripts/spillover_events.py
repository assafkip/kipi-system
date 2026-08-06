"""Validated latest-event fold for the spillover ledger (scs-validated-event-fold).

WHY THIS EXISTS (the scar, measured 2026-08-06). `_read_spillover` used to carry
`except json.JSONDecodeError: continue`, so any line it could not parse was
dropped and the fold returned successfully without it. A reproducer in
`test_spillover_events.py` truncated a `blocker` record mid-line and `gates run`
printed "all 0 regression gates green; no blocking-severity spillover" and
exited 0. A torn write, a partial flush, or a hand-edit was therefore a way to
clear the standing no-bypass gate that left no trace anywhere.

The gate is the enforcement of last resort for out-of-scope findings. A reader
that silently discards what it cannot parse makes the gate report safety it
cannot provide, which is worse than having no gate: it launders "we have
enforcement". Same failure shape as the 26 per-worktree ledgers that hid 71
findings from main, and the fix is the same kind: make the unreadable case loud.

WHAT IS VALIDATED HERE, AND WHAT DELIBERATELY IS NOT. This module owns the
STRUCTURAL contract only: parseable JSON, an object, an addressable `id`, and a
known `status`. It does NOT validate `severity`, because `prd_runner` already
fails closed on that (`_is_blocking_severity` treats an unknown severity as
blocking, and the CLI rejects one outright). Re-deriving the severity vocabulary
here would put one logical value in two places, which is how the two sides drift
apart while every test stays green.

`status` is validated here because nothing else validated it at all: it is the
field the gate branches on, and an unrecognised value folded straight through.

FILE ORDER IS THE ORDERING AUTHORITY, never `created_at`. Clocks skew across
machines and worktrees; byte order in an append-only file does not. The parent
PRD records this as a resolved decision ("timestamps are evidence, not ordering
authority") and `test_out_of_order_timestamp_does_not_reorder_the_fold` is what
holds it: an implementation that sorts by timestamp before folding passes every
other test in the suite and fails only that one.
"""

from __future__ import annotations

import json

# The statuses the ledger actually uses, MEASURED from `.prd-os/spillover.jsonl`
# on 2026-08-06 across all 860 events: open 715, resolved 139, promoted 7.
#
# `promoted` appears nowhere in the parent PRD's event list. A validator written
# from the PRD alone would have refused those 7 live records and taken every
# prd-os command down the moment it shipped. Read the population before making a
# reader fail closed on it.
KNOWN_STATUSES = ("open", "resolved", "promoted")


class SpilloverLedgerError(Exception):
    """The ledger could not be read as a whole.

    Carries the line number because the operator's next action is to open that
    line. A refusal that cannot be located is a refusal that gets bypassed.
    """


def _describe(path, lineno, problem: str) -> str:
    return (f"{path}:{lineno}: {problem}\n"
            "The spillover ledger is the standing gate's evidence, so an "
            "unreadable line is refused rather than skipped: skipping one is "
            "indistinguishable from that finding never having existed.")


def validate_for_append(record, path) -> dict:
    """Refuse an invalid record BEFORE it reaches the file (sp-940e1013).

    Making the READ path fail closed created a new foot-gun: a writer that
    appends a malformed record now bricks every prd-os read until a human edits
    the ledger by hand. The lenient reader used to absorb a bad write; nothing
    absorbs it now. So the write path has to refuse, and it has to refuse
    without touching the file -- an implementation that appends and then raises
    is the worst of both, because the bad line is on disk AND the caller saw an
    error.

    Takes NO lock, deliberately. `_spillover_lock` is LOCK_EX on a separate fd
    and `reclassify` already holds it across its read-modify-append; acquiring
    it again inside the append would deadlock the process against itself.
    Validating a record reads nothing, so it needs no lock.

    This does NOT make an append atomic. A crash midway through writing the
    line still leaves a torn record, which the reader will now (correctly)
    refuse loudly instead of skipping silently. Single-write durability belongs
    to finding-7 (`scs-concurrent-append-lock`); this is validation only.
    """
    return validate_event(record, f"{path} (refusing to append)", "new event")


def validate_event(record, path, lineno: int) -> dict:
    """Return `record` if it is a structurally valid event, else raise.

    Ordered cheapest-check-first, and each raise names the offending value so
    the message is actionable without opening the file.
    """
    if not isinstance(record, dict):
        raise SpilloverLedgerError(_describe(
            path, lineno,
            f"line is valid JSON but not an object (got {type(record).__name__})"))
    item_id = record.get("id")
    if not isinstance(item_id, str) or not item_id.strip():
        raise SpilloverLedgerError(_describe(
            path, lineno,
            "event has no usable `id`. An id-less item is unaddressable: it can "
            "never be resolved or voided, so it can never leave the ledger"))
    status = record.get("status")
    if status not in KNOWN_STATUSES:
        raise SpilloverLedgerError(_describe(
            path, lineno,
            f"unknown status {status!r} on {item_id}; expected one of "
            f"{list(KNOWN_STATUSES)}. The gate branches on this field, so an "
            "unrecognised value would decide the exit code by accident"))
    return record


def fold_ledger_text(text: str, path) -> dict:
    """Fold raw ledger text to `{id: latest_event}`, failing closed.

    Blank lines are skipped (they carry no claim and an append that ends in a
    newline is normal). Everything else must validate.
    """
    items: dict = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SpilloverLedgerError(_describe(
                path, lineno,
                f"invalid JSON ({exc.msg}). A torn write or a hand-edit here "
                "would otherwise silently remove a finding from the gate")) from exc
        validate_event(record, path, lineno)
        # Last occurrence in FILE order wins. Not sorted, not timestamp-keyed.
        items[record["id"]] = record
    return items
