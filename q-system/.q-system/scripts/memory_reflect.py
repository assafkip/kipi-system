"""Earned-trust scoring engine for kipi memory (memory_reflect).

Ports graphify reflect.py's deterministic work-memory model to kipi's flat
outcome log (parent PRD prd-memory-outcome-scoring-2026-07-04). Reads the events
`memory_outcomes.record_outcome` appended and produces a per-memory earned-trust
verdict:

  - **preferred**  — corroborated by >= N distinct useful outcomes, positive score.
  - **tentative**  — useful but under the corroboration bar (one save can't mint trust).
  - **contested**  — both positive and negative outcomes; recency (the signed
                     time-decayed score) decides the verdict.
  - **dead ends**  — negative-only.

Scoring is signed and time-decayed with a half-life (default 30d): a fresh dead
end outweighs a months-old useful. Distinctness for corroboration is by
`event_id`, so a replayed outcome can't inflate the count (the log already dedups
by event_id; this is the second guard).

The result is written to a SIDECAR (`q-system/memory/.memory-scores.json`), keyed
by memory_id. The memory `.md` files and their `confidence`/`provenance`/`decay`
frontmatter are NEVER touched — earned trust is a separate axis from declared
trust (an explicitly chosen design, mirroring graphify's sidecar).

Determinism: stable sort orders, `now` is injectable, and the sidecar is written
with sorted keys + indent 2, so identical input + identical `now` => identical
bytes. No LLM anywhere.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# QROOT = q-system/ (this script lives at q-system/.q-system/scripts/).
QROOT = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")).resolve()
DEFAULT_SIDECAR = QROOT / "memory" / ".memory-scores.json"

_DEFAULT_HALF_LIFE_DAYS = 30.0
_DEFAULT_MIN_CORROBORATION = 2
_SCORE_NDIGITS = 9          # round so sort order + verdict are cross-platform stable
_PROVENANCE_CAP = 5         # most-recent (date, outcome, note) entries per memory
_SIDECAR_VERSION = 1

_POSITIVE = ("useful",)
_NEGATIVE = ("dead_end", "corrected")


# --- time decay ---------------------------------------------------------------

def _parse_dt(date_str: str) -> datetime | None:
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str)
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _decay(date_str: str, now: datetime, half_life_days: float) -> float:
    """Weight in (0, 1]: halves every `half_life_days`. Undated/future => 1.0."""
    dt = _parse_dt(date_str)
    if dt is None or half_life_days <= 0:
        return 1.0
    age_days = max(0.0, (now - dt).total_seconds() / 86400.0)
    return 0.5 ** (age_days / half_life_days)


# --- aggregation --------------------------------------------------------------

def aggregate(events: list[dict], *, now: datetime | None = None,
              half_life_days: float = _DEFAULT_HALF_LIFE_DAYS,
              min_corroboration: int = _DEFAULT_MIN_CORROBORATION) -> dict:
    """Aggregate outcome events into preferred/tentative/contested/dead_ends.

    Each memory accumulates a signed, time-decayed score and distinct-`event_id`
    positive/negative counts. Deterministic given `now`.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    score: dict[str, float] = {}
    pos_ids: dict[str, set[str]] = {}
    neg_ids: dict[str, set[str]] = {}
    last: dict[str, str] = {}
    source: dict[str, str] = {}
    prov: dict[str, list[tuple]] = {}

    # De-duplicate by (memory_id, event_id) up front so a replayed event cannot
    # inflate the signed score OR the counts (review finding: the log dedups by
    # event_id, but the engine must be robust to a hand-edited/foreign log too —
    # distinctness is enforced in ONE place, before scoring). First occurrence wins.
    seen: set[tuple[str, str]] = set()

    for ev in events:
        mid = ev.get("memory_id")
        outcome = ev.get("outcome")
        eid = ev.get("event_id")
        if not mid or not eid or outcome not in (_POSITIVE + _NEGATIVE):
            continue
        key = (str(mid), str(eid))
        if key in seen:
            continue
        seen.add(key)
        date = ev.get("date", "")
        weight = _decay(date, now, half_life_days)
        sign = 1 if outcome in _POSITIVE else -1
        score[mid] = score.get(mid, 0.0) + sign * weight
        (pos_ids if sign > 0 else neg_ids).setdefault(mid, set()).add(str(eid))
        if date > last.get(mid, ""):
            last[mid] = date
        if ev.get("source_file") and mid not in source:
            source[mid] = str(ev["source_file"])
        prov.setdefault(mid, []).append((date, outcome, ev.get("note", "")))

    preferred, tentative, contested, dead_ends = [], [], [], []
    for mid in score:
        pos = len(pos_ids.get(mid, ()))
        neg = len(neg_ids.get(mid, ()))
        raw = score[mid]
        sc = round(raw, _SCORE_NDIGITS)
        entry = {"memory_id": mid, "score": sc, "pos": pos, "neg": neg,
                 "last": last.get(mid, ""), "source_file": source.get(mid, ""),
                 "provenance": _provenance(prov.get(mid, []))}
        if pos and neg:
            # Verdict from the RAW (unrounded) score so a tiny recency lean is not
            # erased by rounding; "even" only for a genuine 0.0 (review finding).
            entry["verdict"] = ("useful" if raw > 0 else "dead end" if raw < 0 else "even")
            contested.append(entry)
        elif pos:
            (preferred if pos >= min_corroboration else tentative).append(entry)
        else:  # negative-only
            dead_ends.append(entry)

    # Deterministic ordering: score desc, then memory_id asc.
    key = lambda e: (-e["score"], e["memory_id"])
    preferred.sort(key=key)
    tentative.sort(key=key)
    contested.sort(key=key)
    dead_ends.sort(key=lambda e: (e["score"], e["memory_id"]))
    return {"preferred": preferred, "tentative": tentative,
            "contested": contested, "dead_ends": dead_ends,
            "min_corroboration": min_corroboration}


def _provenance(events: list[tuple]) -> list[dict]:
    """Most-recent-first, capped (date, outcome, note) trail for a memory."""
    ordered = sorted(events, key=lambda e: (e[0], e[1]), reverse=True)
    return [{"date": d, "outcome": o, "note": n} for d, o, n in ordered[:_PROVENANCE_CAP]]


# --- source fingerprint (finding-4) -------------------------------------------

def _resolve_source(src: str, root: Path) -> Path | None:
    """Locate a memory's source_file on disk. Ported from graphify's multi-root
    candidate search.

    A recorded source_file may be relative to QROOT (`my-project/foo.md`) OR to
    the REPO root (`q-system/my-project/foo.md`, the form the PRD documents), so
    both roots are tried, plus cwd as a last resort (review finding: trying only
    QROOT + cwd made resolution cwd-dependent and marked unchanged sources stale).
    First existing candidate wins; None if missing/renamed."""
    if not src:
        return None
    p = Path(src)
    if p.is_absolute():
        return p if p.is_file() else None
    seen: set[str] = set()
    for base in (root, root.parent, Path(".")):
        key = str(base)
        if key in seen:
            continue
        seen.add(key)
        cand = base / p
        if cand.is_file():
            return cand
    return None


def _content_hash(path: Path) -> str:
    """SHA256 of file CONTENT only (path-independent), so the fingerprint is
    stable across which root resolved the file and across machines."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _fingerprint(src: str, root: Path) -> str:
    sp = _resolve_source(src, root)
    return _content_hash(sp) if sp is not None else ""


# --- sidecar ------------------------------------------------------------------

def build_overlay(events: list[dict], root: Path, *, now: datetime | None = None,
                  half_life_days: float = _DEFAULT_HALF_LIFE_DAYS,
                  min_corroboration: int = _DEFAULT_MIN_CORROBORATION) -> dict:
    """Project the aggregate into the sidecar structure keyed by memory_id."""
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    agg = aggregate(events, now=now, half_life_days=half_life_days,
                    min_corroboration=min_corroboration)
    nodes: dict[str, dict] = {}
    for status in ("preferred", "tentative", "contested", "dead_ends"):
        for e in agg[status]:
            out = {"status": "dead_end" if status == "dead_ends" else status,
                   "score": e["score"], "pos": e["pos"], "neg": e["neg"],
                   "last": e["last"], "source_file": e["source_file"],
                   "code_fingerprint": _fingerprint(e["source_file"], root),
                   "provenance": e["provenance"]}
            if "verdict" in e:
                out["verdict"] = e["verdict"]
            nodes[e["memory_id"]] = out
    return {"version": _SIDECAR_VERSION, "generated_at": now.isoformat(),
            "min_corroboration": min_corroboration, "nodes": nodes}


def write_sidecar(events: list[dict], path: Path | None = None, *,
                  root: Path | None = None, now: datetime | None = None,
                  half_life_days: float = _DEFAULT_HALF_LIFE_DAYS,
                  min_corroboration: int = _DEFAULT_MIN_CORROBORATION) -> Path:
    """Write the earned-trust sidecar deterministically (sorted keys, indent 2)."""
    path = Path(path) if path is not None else DEFAULT_SIDECAR
    root = Path(root) if root is not None else QROOT
    overlay = build_overlay(events, root, now=now, half_life_days=half_life_days,
                            min_corroboration=min_corroboration)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overlay, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def load_sidecar(path: Path | None = None, *, root: Path | None = None) -> dict[str, dict]:
    """Load the sidecar and return {memory_id -> entry} with a recomputed
    `stale` per entry. Stale = the cited source_file's content changed or the
    file vanished since the fingerprint was taken (the safe over-flag direction).
    An entry with no source_file is never stale. Best-effort -> {} on any error.
    """
    path = Path(path) if path is not None else DEFAULT_SIDECAR
    root = Path(root) if root is not None else QROOT
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    nodes = data.get("nodes")
    if not isinstance(nodes, dict):
        return {}
    out: dict[str, dict] = {}
    for mid, entry in nodes.items():
        if not isinstance(entry, dict):
            continue
        merged = dict(entry)
        merged["stale"] = _is_stale(entry, root)
        out[str(mid)] = merged
    return out


def _is_stale(entry: dict, root: Path) -> bool:
    src = entry.get("source_file", "")
    if not src:
        return False  # nothing to track
    sp = _resolve_source(src, root)
    if sp is None:
        return True  # file gone / unfindable -> re-verify
    stored = entry.get("code_fingerprint", "")
    if not stored:
        return True  # had a file but never fingerprinted -> can't trust
    return _content_hash(sp) != stored
