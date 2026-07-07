"""CSV/TSV reader. Fixes two audited losses: (1) the header row is always
captured as its own block, so a headerless or single-row file does not vanish
into an assumed-header (kipi bug #2), and (2) a row cap is COUNTED into the
receipt as `truncated`, never a silent `break`. Every non-empty row becomes an
addressable block.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from ..contract import Block, Drop, ReadResult, make_block_id


def read_csv(
    path: str | Path,
    *,
    max_rows: int | None = None,
) -> tuple[list[Block], ReadResult]:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    delim = "\t" if (p.suffix.lower() == ".tsv"
                     or text[:2000].count("\t") > text[:2000].count(",")) else ","
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim)
            if any(c.strip() for c in r)]

    if not rows:
        return [], ReadResult(unit="row", attempted=0, captured=0)

    header = [c.strip() for c in rows[0]]
    data = rows[1:]

    blocks: list[Block] = []
    dropped: list[Drop] = []

    # Header is real content -- capture it, do not assume it away.
    blocks.append(Block(block_id=make_block_id("r", 0, 0), unit="row", page=0,
                        text=" | ".join(header)))

    truncated = max_rows is not None and len(data) > max_rows
    emit = data[:max_rows] if truncated else data
    for i, row in enumerate(emit, start=1):
        cells = []
        for j, cell in enumerate(row):
            col = header[j] if j < len(header) else f"col{j}"
            if str(cell).strip():
                cells.append(f"{col}: {cell}")
        blocks.append(Block(block_id=make_block_id("r", 0, i), unit="row", page=0,
                            text=" | ".join(cells)))

    if truncated:
        dropped.append(Drop(f"r.p0.{max_rows + 1}+",
                            f"row cap {max_rows} hit; {len(data) - max_rows} rows not read"))

    return blocks, ReadResult(
        unit="row",
        attempted=len(rows),          # header + every data row (source-truth)
        captured=len(blocks),
        truncated=truncated,
        dropped=dropped,
    )
