"""Markdown reader. Fixes a LIVE silent loss: the legacy `markdown.extract_text`
stripped frontmatter AND code fences, so evidence inside a ``` block (wallets,
phones) or in the frontmatter (owner, ids) silently vanished before entity
extraction. This reader KEEPS every segment as an addressable block and reports
attempted-vs-captured, so nothing is dropped without a reason.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..contract import Block, Drop, ReadResult, make_block_id

_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def read_md(path: str | Path) -> tuple[list[Block], ReadResult]:
    raw = Path(path).read_text(encoding="utf-8", errors="replace")

    segments: list[tuple[str, str]] = []  # (kind, text) in document order

    body = raw
    fm = _FRONTMATTER_RE.match(raw)
    if fm:
        segments.append(("fm", fm.group(0)))
        body = raw[fm.end():]

    # Split the body into alternating prose / fenced-block segments, preserving
    # order. Every char lands in exactly one segment (no content skipped).
    cursor = 0
    for m in _CODE_FENCE_RE.finditer(body):
        if m.start() > cursor:
            segments.append(("p", body[cursor:m.start()]))
        segments.append(("fb", m.group(0)))
        cursor = m.end()
    if cursor < len(body):
        segments.append(("p", body[cursor:]))

    blocks: list[Block] = []
    dropped: list[Drop] = []
    idx = 0
    for kind, text in segments:
        idx += 1
        unit = "fenced_block" if kind == "fb" else "doc_part"
        bid = make_block_id(kind, 0, idx)
        if not text.strip():
            dropped.append(Drop(bid, "empty segment"))
            continue
        blocks.append(Block(block_id=bid, unit=unit, page=0, text=text))

    receipt = ReadResult(
        unit="doc_part",
        attempted=len(segments),
        captured=len(blocks),
        truncated=False,
        dropped=dropped,
    )
    return blocks, receipt
