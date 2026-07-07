"""kipi_ingest -- fleet-canonical ingestion coverage contract + readers.

Import the contract from anywhere an instance has `q-system/lib` on sys.path:

    from kipi_ingest import ReadResult, Block, reconcile, ground
    from kipi_ingest.readers import read_md, read_csv

Canonical source lives in the kipi-system skeleton and propagates unchanged to
every instance via `kipi update`. Do not edit an instance's copy; edit canonical.
See PRD prd-fleet-ingestion-coverage-contract-2026-07-06.
"""
from __future__ import annotations

from .contract import (
    Block,
    Drop,
    DuplicateBlockError,
    IngestError,
    ReadResult,
    UngroundedReferenceError,
    UnreadUnitError,
    ground,
    index_blocks,
    make_block_id,
    reconcile,
)

__all__ = [
    "Block",
    "Drop",
    "DuplicateBlockError",
    "IngestError",
    "ReadResult",
    "UngroundedReferenceError",
    "UnreadUnitError",
    "ground",
    "index_blocks",
    "make_block_id",
    "reconcile",
]

__version__ = "0.1.0"
