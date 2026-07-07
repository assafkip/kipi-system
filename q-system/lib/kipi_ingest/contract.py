"""Fleet-canonical ingestion coverage contract.

Canonical source (PRD prd-fleet-ingestion-coverage-contract-2026-07-06). This
module is skeleton-owned and propagates to every instance via `kipi update`
(git archive q-system/ + rsync --delete), so all document-ingesting tools share
ONE read-boundary contract and cannot drift. A `--check` (conformance.py --check)
is the deterministic gate between updates.

Two composable layers, each distilled from a real sibling tool (audited
2026-07-06):

  Layer 1 COUNTING  (from QEP) -- did we read every unit?
    ReadResult(attempted, captured, truncated, dropped) + reconcile().
    A cap or per-unit failure is COUNTED, never silent. reconcile() raises and
    names any enumerated unit with no result.

  Layer 2 PROVENANCE (from the KTLYST product) -- is every kept unit real?
    Block(block_id, text-derived-from-source) + index_blocks() + ground().
    A downstream reference to a unit that was not read raises; "captured"
    becomes unfakeable.

Neither sibling had both halves; together they are the complete receipt.
Stdlib only: the contract carries no parse dependencies (readers own those).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = [
    "IngestError",
    "UnreadUnitError",
    "UngroundedReferenceError",
    "DuplicateBlockError",
    "Drop",
    "ReadResult",
    "Block",
    "make_block_id",
    "index_blocks",
    "ground",
    "reconcile",
]

# Recognized coverage units. A reader picks the one that matches its format's
# natural atom so attempted/captured counts are source-truth, not output-derived.
UNITS = ("page", "sheet", "row", "fenced_block", "doc_part", "record")


# --------------------------------------------------------------------------- #
# Fail-loud exceptions (the unreadable tier shared by QEP + product).
# --------------------------------------------------------------------------- #
class IngestError(Exception):
    """Base for every hard ingestion failure."""


class UnreadUnitError(IngestError):
    """Reconciliation found enumerated units with no captured result. Names them
    so the miss is never silent (QEP's UnreadFileError, generalized to units)."""


class UngroundedReferenceError(IngestError):
    """A downstream reference to a block_id that was not in the read set. The
    product's construction-site gate: you cannot cite a unit you did not read."""


class DuplicateBlockError(IngestError):
    """Two blocks share a block_id. Fail closed (product _build_blocks_by_id):
    a collision would let one unit silently shadow another."""


# --------------------------------------------------------------------------- #
# Layer 2 -- provenance: page-anchored, format-validated unit ids.
# --------------------------------------------------------------------------- #
# kind.p<page>.<index...>  e.g. t.p4.2  c.p1.t0.r3.c2  i.p2.0  fb.p0.1
_BLOCK_ID_RE = re.compile(r"^[a-z]{1,3}\.p\d+(?:\.[0-9a-z]+)+$")


def make_block_id(kind: str, page: int, *parts: object) -> str:
    """Build and validate a stable, page-anchored block id. Raises ValueError on
    a malformed id so a bad id can never enter the read set (ids validated on
    write, mirroring the product's per-producer id checks)."""
    if not parts:
        raise ValueError("block id needs at least one index part")
    tail = ".".join(str(p) for p in parts)
    bid = f"{kind}.p{int(page)}.{tail}"
    if not _BLOCK_ID_RE.match(bid):
        raise ValueError(f"malformed block_id: {bid!r}")
    return bid


@dataclass(frozen=True)
class Block:
    """One extracted, addressable unit. `text` is DERIVED from the source at read
    time, never caller-supplied downstream (fabrication surface removed)."""

    block_id: str
    unit: str
    page: int
    text: str
    bbox: tuple | None = None

    def __post_init__(self) -> None:
        if not _BLOCK_ID_RE.match(self.block_id):
            raise ValueError(f"malformed block_id: {self.block_id!r}")
        if self.unit not in UNITS:
            raise ValueError(f"unknown unit {self.unit!r}; expected one of {UNITS}")


def index_blocks(blocks: list[Block]) -> dict[str, Block]:
    """block_id -> Block, failing closed on a duplicate id."""
    out: dict[str, Block] = {}
    for b in blocks:
        if b.block_id in out:
            raise DuplicateBlockError(b.block_id)
        out[b.block_id] = b
    return out


def ground(reference_block_id: str, read_blocks: dict[str, Block]) -> Block:
    """Return the Block a downstream reference points to, or raise if it was not
    read. This is the construction-site gate: a citation to an unread unit is a
    hard error, not a silently accepted claim."""
    b = read_blocks.get(reference_block_id)
    if b is None:
        raise UngroundedReferenceError(reference_block_id)
    return b


# --------------------------------------------------------------------------- #
# Layer 1 -- counting: attempted vs captured, caps and failures made visible.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Drop:
    """One unit that was attempted but not captured, with the reason. A dropped
    unit is accounted, never silent."""

    unit_id: str
    reason: str


@dataclass
class ReadResult:
    """Attempted-vs-captured receipt for one read. `attempted` is source-truth
    (what the file actually contains), `captured` is what made it into blocks.
    `truncated` marks a cap or failure that kept capture below attempted."""

    unit: str
    attempted: int
    captured: int
    truncated: bool = False
    dropped: list[Drop] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.unit not in UNITS:
            raise ValueError(f"unknown unit {self.unit!r}; expected one of {UNITS}")
        if self.attempted < 0 or self.captured < 0:
            raise ValueError("attempted/captured must be non-negative")
        if self.captured > self.attempted:
            raise ValueError(
                f"captured {self.captured} > attempted {self.attempted}: "
                "a reader miscounted its source"
            )

    def recall(self) -> float:
        """captured / attempted, defined as 1.0 when there was nothing to read."""
        return 1.0 if self.attempted == 0 else self.captured / self.attempted

    def is_lossy(self, threshold: float = 1.0) -> bool:
        """True when this read lost content: truncated, or recall below threshold.
        Fail closed (a truncated read is lossy even if the count looks complete)."""
        return self.truncated or self.recall() < threshold


def reconcile(enumerated: list[str], captured_ids: set[str]) -> None:
    """Raise UnreadUnitError naming every enumerated unit id with no captured
    block. The enumeration is source-truth (e.g. every page index the PDF
    reports); this proves each one produced output. No enumerated unit is skipped
    in silence."""
    missing = [u for u in enumerated if u not in captured_ids]
    if missing:
        shown = ", ".join(missing[:20])
        more = f" (+{len(missing) - 20} more)" if len(missing) > 20 else ""
        raise UnreadUnitError(
            f"{len(missing)} of {len(enumerated)} enumerated unit(s) not read: {shown}{more}"
        )
