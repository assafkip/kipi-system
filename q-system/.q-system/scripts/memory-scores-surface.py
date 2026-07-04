#!/usr/bin/env python3
"""Earned-trust recall surface for kipi memory (SessionStart).

The READ side of memory-outcome-scoring (parent PRD
prd-memory-outcome-scoring-2026-07-04). Reads the `.memory-scores.json` sidecar
that `memory_reflect` produces and surfaces earned trust at two read points
(finding-5 — earned trust must reach every reader, not just a direct file read):

  1. A SessionStart context block: which memories to lean on (preferred), which
     to treat skeptically (contested), and which to re-verify (stale).
  2. `annotate_index`: prefixes `[contested]` / `[stale]` onto MEMORY.md index
     lines, mirroring the existing `[fast]` / `[low-conf]` markers so the trust
     risk is visible at a glance without opening a file.

A raw `Read` of a memory `.md` deliberately does NOT carry earned trust: the
sidecar never mutates the durable memory files (an explicitly chosen design,
mirroring how the memory age-warning and the pi metric surface at recall/index,
not in every file). Coverage is q-system/memory ONLY (v1) and is labeled as such
so the block never implies it covers the auto-memory store.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import memory_outcomes as mo  # noqa: E402
import memory_reflect as mr  # noqa: E402

QROOT = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")).resolve()
DEFAULT_SIDECAR = QROOT / "memory" / ".memory-scores.json"
OUTCOMES_LOG = QROOT / "memory" / "outcomes.jsonl"

_COVERAGE = "earned-trust for q-system/memory"
# MEMORY.md index line: `- [Title](slug.md) - hook`. An optional leading
# `[contested]`/`[stale]` marker run is consumed so annotate_index is idempotent
# WITHOUT a blind pre-strip (a blind strip corrupted non-index bullets — review
# finding). Only a line matching this whole shape, whose slug is in the sidecar,
# is ever rewritten; every other line is passed through untouched.
_INDEX_LINE_RE = re.compile(
    r"^- (?:\[(?:contested|stale)\] )*(\[[^\]]*\]\((?P<slug>[^)]+?)\.md\)(?: .*)?)$")


def render_block(scores: dict[str, dict]) -> str:
    """Render the SessionStart earned-trust block, or "" when nothing to surface."""
    if not scores:
        return ""
    preferred, contested, stale = [], [], []
    for mid, e in sorted(scores.items()):
        if e.get("stale"):
            stale.append(mid)
        status = e.get("status")
        if status == "preferred":
            preferred.append(mid)
        elif status == "contested":
            verdict = e.get("verdict", "mixed")
            contested.append(f"{mid} (recency leans {verdict})")

    if not (preferred or contested or stale):
        return ""

    out = [f"[EARNED-TRUST] {_COVERAGE} (from recorded outcomes; verify before relying):"]
    if preferred:
        out.append("  lean on: " + ", ".join(preferred))
    if contested:
        out.append("  skeptical: " + "; ".join(contested))
    if stale:
        out.append("  re-verify (source changed): " + ", ".join(sorted(set(stale))))
    return "\n".join(out)


def annotate_index(index_text: str, scores: dict[str, dict]) -> str:
    """Return MEMORY.md text with `[contested]`/`[stale]` prefixes on the index
    lines whose memory matches a risky sidecar entry. Idempotent: an existing
    marker is stripped first, so re-running never stacks markers.
    """
    out: list[str] = []
    for line in index_text.splitlines(keepends=False):
        m = _INDEX_LINE_RE.match(line)
        # Only a real index entry whose slug is in the sidecar is ever rewritten.
        if m and m.group("slug") in scores:
            entry = scores[m.group("slug")]
            markers = []
            if entry.get("status") == "contested":
                markers.append("[contested]")
            if entry.get("stale"):
                markers.append("[stale]")
            rest = m.group(1)  # the `[Title](slug.md) - hook` part, marker stripped
            line = f"- {' '.join(markers)} {rest}" if markers else f"- {rest}"
        out.append(line)
    trailing = "\n" if index_text.endswith("\n") else ""
    return "\n".join(out) + trailing


def _safe_load(sidecar: Path) -> dict[str, dict]:
    """load_sidecar, but never raises. A malformed sidecar (e.g. top-level JSON
    that is a list, not an object) must not crash SessionStart — the surface
    stays silent instead. The deeper isinstance guard belongs in load_sidecar
    itself (memory_reflect); captured as spillover, guarded here at the boundary."""
    try:
        scores = mr.load_sidecar(sidecar, root=QROOT)
    except Exception:
        return {}
    return scores if isinstance(scores, dict) else {}


def _refresh_sidecar() -> None:
    """Rebuild the sidecar from the outcomes log so SessionStart never reads a
    stale one (finding-6). Fast, no LLM. Best-effort AND atomic: write_sidecar
    truncates-then-writes, so writing straight to DEFAULT_SIDECAR would leave it
    empty if the write failed mid-way (review finding). We write to a temp file
    and os.replace() it into place only on full success, so a failure preserves
    the previous good sidecar. Any failure is swallowed — never crash SessionStart."""
    tmp = None
    try:
        events = mo.read_events(OUTCOMES_LOG)
        if not events:
            return
        tmp = Path(str(DEFAULT_SIDECAR) + ".tmp")
        mr.write_sidecar(events, tmp, root=QROOT)
        os.replace(tmp, DEFAULT_SIDECAR)  # atomic; old sidecar intact until here
    except Exception:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    """Print the earned-trust block to stdout for SessionStart context injection.
    Refreshes the sidecar from the log first, then reads it. Silent (exit 0, no
    output) when there are no events / the sidecar is absent, empty, or malformed."""
    _refresh_sidecar()
    block = render_block(_safe_load(DEFAULT_SIDECAR))
    if block:
        print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
