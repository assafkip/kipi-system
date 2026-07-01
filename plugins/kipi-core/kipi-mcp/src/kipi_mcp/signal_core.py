from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from kipi_mcp.competitive_intel import HarvestRecord


DEFAULT_COVERAGE_DAYS = 7
DEFAULT_JACCARD = 0.6
DEFAULT_WINDOW_HOURS = 48

_STOP_WORDS = {
    "a",
    "an",
    "the",
    "to",
    "of",
    "in",
    "on",
    "and",
    "for",
    "is",
    "are",
    "with",
    "as",
    "at",
    "by",
    "from",
    "how",
    "why",
    "what",
    "new",
    "now",
    "this",
    "that",
    "its",
    "it",
    "you",
    "your",
    "ai",
    "model",
    "models",
}


def canonical_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "").rstrip("/")
    if not host:
        return url.strip().lower()
    return f"{host}{path}".lower()


def normalize_title(title: str) -> str:
    lowered = (title or "").lower()
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def title_tokens(title: str) -> set[str]:
    return {
        word
        for word in normalize_title(title).split()
        if word not in _STOP_WORDS and len(word) > 2
    }


def item_key(record: HarvestRecord | dict[str, Any]) -> str:
    url = _record_value(record, "url")
    canonical = canonical_url(url)
    if canonical:
        return f"url:{canonical}"
    return f"title:{normalize_title(_record_title(record))}"


def filter_new_records(
    records: list[HarvestRecord],
    ledger_path: str | Path,
    *,
    today: str | None = None,
    days: int = DEFAULT_COVERAGE_DAYS,
    jaccard_threshold: float = DEFAULT_JACCARD,
) -> tuple[list[HarvestRecord], list[tuple[HarvestRecord, str]]]:
    coverage = _load_recent_coverage(Path(ledger_path), today=today, days=days)
    recent_keys = {item.get("key", "") for item in coverage}
    recent_tokens = [title_tokens(str(item.get("title") or item.get("text") or "")) for item in coverage]

    kept: list[HarvestRecord] = []
    dropped: list[tuple[HarvestRecord, str]] = []
    seen_keys: set[str] = set()
    seen_tokens: list[set[str]] = []
    for record in records:
        key = item_key(record)
        tokens = title_tokens(_record_title(record))
        if key in seen_keys:
            dropped.append((record, "dupe-in-batch-exact"))
            continue
        if any(_jaccard(tokens, prior) >= jaccard_threshold for prior in seen_tokens):
            dropped.append((record, "dupe-in-batch-near"))
            continue
        if key in recent_keys:
            dropped.append((record, "covered-exact"))
            continue
        if any(_jaccard(tokens, prior) >= jaccard_threshold for prior in recent_tokens):
            dropped.append((record, "covered-near"))
            continue
        kept.append(record)
        seen_keys.add(key)
        seen_tokens.append(tokens)
    return kept, dropped


def commit_coverage(ledger_path: str | Path, records: list[HarvestRecord], *, date: str) -> int:
    """Single writer for coverage state. Podcast scar: prompt memory is not memory."""
    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(
                json.dumps(
                    {
                        "date": date,
                        "key": item_key(record),
                        "title": _record_title(record),
                        "entity": record.entity,
                        "source": record.source,
                        "url": record.url,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return len(records)


def bank_signal_buffer(
    buffer_path: str | Path,
    *,
    pool_records: list[HarvestRecord],
    aired_records: list[HarvestRecord],
    now_ts: float | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> list[HarvestRecord]:
    now = _now_ts(now_ts)
    existing = _load_buffer(Path(buffer_path))
    aired_keys = {item_key(record) for record in aired_records}
    seen: set[str] = set()
    banked: list[HarvestRecord] = []

    for record in existing + list(pool_records):
        key = item_key(record)
        if key in aired_keys or key in seen:
            continue
        seen.add(key)
        if _is_fresh(record, now, window_hours):
            banked.append(record)

    _write_buffer(Path(buffer_path), banked)
    return banked


def draw_signal_buffer(
    buffer_path: str | Path,
    *,
    now_ts: float | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> list[HarvestRecord]:
    now = _now_ts(now_ts)
    fresh = [record for record in _load_buffer(Path(buffer_path)) if _is_fresh(record, now, window_hours)]
    _write_buffer(Path(buffer_path), fresh)
    return fresh


def render_podcast_digest(
    report: Any,
    *,
    date: str,
    audience: str = (
        "AI builders, AI consultants, threat intelligence professionals, "
        "AI startup founders, fraud consultants, and fractional leaders"
    ),
) -> str:
    lines = [
        f"AI market analyst source brief for {date}.",
        f"Audience: {audience}.",
        (
            "Use this as source material for a short audio brief. Explain what changed, "
            "why it matters, and which receipts support it."
        ),
        "",
        "Part 1 - Market moves",
        "",
    ]
    if not report.market_moves:
        lines.extend(
            [
                "Quiet stretch. No cross-source market move cleared the threshold.",
                "Keep the brief short. Do not pad it with isolated stories.",
                "",
            ]
        )
    for index, move in enumerate(report.market_moves, start=1):
        entities = ", ".join(move.entities)
        lines.extend(
            [
                f"{index}. {move.theme}",
                f"Entities: {entities}",
                f"Evidence count: {move.evidence_count}",
                f"Why it matters: {move.why_this_matters}",
                "",
            ]
        )

    lines.extend(["Part 2 - Evidence receipts", ""])
    receipt_index = 1
    seen: set[str] = set()
    for move in report.market_moves:
        for record in move.records:
            key = item_key(record)
            if key in seen:
                continue
            seen.add(key)
            lines.extend(
                [
                    f"{receipt_index}. {record.entity} on {record.source}",
                    _one_line(record.text, 260),
                ]
            )
            if record.url:
                lines.append(f"Source: {record.url}")
            lines.append("")
            receipt_index += 1

    return "\n".join(lines).rstrip() + "\n"


def _load_recent_coverage(path: Path, *, today: str | None, days: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    today_date = _parse_date(today) if today else None
    out: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if today_date and item.get("date"):
            covered_date = _parse_date(str(item["date"]))
            if covered_date and (today_date - covered_date).days > days:
                continue
        out.append(item)
    return out


def _load_buffer(path: Path) -> list[HarvestRecord]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    records: list[HarvestRecord] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            records.append(_record_from_dict(item))
        except TypeError:
            continue
    return records


def _write_buffer(path: Path, records: list[HarvestRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([_record_to_dict(record) for record in records], indent=2))


def _record_to_dict(record: HarvestRecord) -> dict[str, Any]:
    return {
        "entity": record.entity,
        "source": record.source,
        "text": record.text,
        "source_id": record.source_id,
        "url": record.url,
        "published_at": record.published_at,
        "author": record.author,
        "engagement": record.engagement,
    }


def _record_from_dict(item: dict[str, Any]) -> HarvestRecord:
    return HarvestRecord(
        entity=str(item.get("entity") or ""),
        source=str(item.get("source") or ""),
        text=str(item.get("text") or ""),
        source_id=str(item.get("source_id") or ""),
        url=str(item.get("url") or ""),
        published_at=str(item.get("published_at") or ""),
        author=str(item.get("author") or ""),
        engagement=item.get("engagement") if isinstance(item.get("engagement"), dict) else {},
    )


def _record_value(record: HarvestRecord | dict[str, Any], field_name: str) -> str:
    if isinstance(record, dict):
        return str(record.get(field_name) or "")
    return str(getattr(record, field_name, "") or "")


def _record_title(record: HarvestRecord | dict[str, Any]) -> str:
    if isinstance(record, dict):
        return str(record.get("title") or record.get("text") or "")
    return record.text


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _parse_ts(value: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.isdigit():
        return float(text)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _is_fresh(record: HarvestRecord, now_ts: float, window_hours: int) -> bool:
    published = _parse_ts(record.published_at)
    if published is None:
        return False
    return (now_ts - published) / 3600.0 <= window_hours


def _now_ts(value: float | None) -> float:
    return datetime.now(timezone.utc).timestamp() if value is None else value


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _one_line(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."
