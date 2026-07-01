from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from html import unescape
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import yaml


USER_AGENT = "kipi-competitive-intel/1.0 (+https://ktlystlabs.com)"
ARCTIC_BASE = "https://arctic-shift.photon-reddit.com"
PULLPUSH_BASE = "https://api.pullpush.io"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
HTTP_TIMEOUT = 20


@dataclass(frozen=True)
class WatchedEntity:
    name: str
    category: str
    sources: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class Watchlist:
    name: str
    entities: list[WatchedEntity]
    theme_keywords: dict[str, list[str]]
    min_entities_for_move: int = 2
    theme_rules: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class HarvestRecord:
    entity: str
    source: str
    text: str
    source_id: str = ""
    url: str = ""
    published_at: str = ""
    author: str = ""
    engagement: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketMove:
    theme: str
    entities: list[str]
    evidence_count: int
    records: list[HarvestRecord]
    score: float = 0.0
    why_this_matters: str = ""


@dataclass(frozen=True)
class EntityActivity:
    entity: str
    category: str
    record_count: int
    sources: list[str]
    themes: list[str]


@dataclass(frozen=True)
class IntelReport:
    watchlist_name: str
    week: str
    records_seen: int
    market_moves: list[MarketMove]
    entity_activity: list[EntityActivity]
    unmatched_records: list[HarvestRecord]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_watchlist(path: str | Path) -> Watchlist:
    payload = _load_yaml_or_json(Path(path))
    if not isinstance(payload, dict):
        raise ValueError("watchlist must be a mapping")

    raw_entities = payload.get("entities")
    if not isinstance(raw_entities, list) or not raw_entities:
        raise ValueError("watchlist.entities must be a non-empty list")

    entities: list[WatchedEntity] = []
    for index, raw in enumerate(raw_entities):
        if not isinstance(raw, dict):
            raise ValueError(f"entities[{index}] must be a mapping")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"entities[{index}].name is required")
        category = raw.get("category", "unknown")
        if not isinstance(category, str) or not category.strip():
            raise ValueError(f"entities[{index}].category must be a string")
        sources = raw.get("sources", {})
        if not isinstance(sources, dict):
            raise ValueError(f"entities[{index}].sources must be a mapping")
        normalized_sources = {
            str(platform): _string_list(handles, f"entities[{index}].sources.{platform}")
            for platform, handles in sources.items()
        }
        entities.append(
            WatchedEntity(
                name=name.strip(),
                category=category.strip(),
                sources=normalized_sources,
            )
        )

    theme_keywords = payload.get("theme_keywords", {})
    if not isinstance(theme_keywords, dict) or not theme_keywords:
        raise ValueError("watchlist.theme_keywords must be a non-empty mapping")

    normalized_themes: dict[str, list[str]] = {}
    for theme, keywords in theme_keywords.items():
        theme_name = str(theme).strip()
        if not theme_name:
            raise ValueError("watchlist.theme_keywords contains an empty theme")
        normalized_themes[theme_name] = [
            keyword.lower() for keyword in _string_list(keywords, f"theme_keywords.{theme}")
        ]

    min_entities = int(payload.get("min_entities_for_move", 2))
    if min_entities < 2:
        raise ValueError("watchlist.min_entities_for_move must be >= 2")
    theme_rules = payload.get("theme_rules", {})
    if theme_rules is None:
        theme_rules = {}
    if not isinstance(theme_rules, dict):
        raise ValueError("watchlist.theme_rules must be a mapping")

    return Watchlist(
        name=str(payload.get("name") or "Weekly").strip(),
        entities=entities,
        theme_keywords=normalized_themes,
        min_entities_for_move=min_entities,
        theme_rules={str(theme): rule for theme, rule in theme_rules.items() if isinstance(rule, dict)},
    )


def load_records(path: str | Path) -> list[HarvestRecord]:
    payload = json.loads(Path(path).read_text())
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        raw_records = payload["records"]
    elif isinstance(payload, list):
        raw_records = payload
    else:
        raise ValueError("records must be a list or a mapping with records")

    records: list[HarvestRecord] = []
    for index, raw in enumerate(raw_records):
        if not isinstance(raw, dict):
            raise ValueError(f"records[{index}] must be a mapping")
        entity = raw.get("entity")
        source = raw.get("source")
        text = raw.get("text")
        if not isinstance(entity, str) or not entity.strip():
            raise ValueError(f"records[{index}].entity is required")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"records[{index}].source is required")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"records[{index}].text is required")
        engagement = raw.get("engagement") or {}
        if not isinstance(engagement, dict):
            raise ValueError(f"records[{index}].engagement must be a mapping")
        records.append(
            HarvestRecord(
                entity=entity.strip(),
                source=source.strip(),
                text=_clean_text(text),
                source_id=str(raw.get("source_id") or raw.get("id") or ""),
                url=str(raw.get("url") or raw.get("link") or ""),
                published_at=str(raw.get("published_at") or raw.get("created_at") or ""),
                author=str(raw.get("author") or ""),
                engagement=engagement,
            )
        )
    return records


def normalize_raw_records(
    raw_records_path: str | Path,
    output_path: str | Path | None = None,
) -> list[HarvestRecord]:
    payload = json.loads(Path(raw_records_path).read_text())
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        raw_records = payload["records"]
    elif isinstance(payload, list):
        raw_records = payload
    else:
        raise ValueError("raw records must be a list or a mapping with records")

    records: list[HarvestRecord] = []
    for index, raw in enumerate(raw_records):
        if not isinstance(raw, dict):
            raise ValueError(f"raw_records[{index}] must be a mapping")
        records.append(_normalize_raw_record(raw, index))

    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps([asdict(record) for record in records], indent=2))

    return records


def collect_ai_raw_records(
    output_path: str | Path | None = None,
    query: str = "AI agent OR Claude Code OR MCP OR eval harness",
    per_source_limit: int = 5,
    sources_config_path: str | Path | None = None,
    fetch_json: Any | None = None,
    fetch_text: Any | None = None,
    post_json: Any | None = None,
    apify_token: str | None = None,
) -> list[dict[str, Any]]:
    config = _load_collector_config(sources_config_path)
    fetch_json = fetch_json or _fetch_json
    fetch_text = fetch_text or _fetch_text
    post_json = post_json or _post_json
    token = os.environ.get("APIFY_TOKEN", "") if apify_token is None else apify_token

    raw_records: list[dict[str, Any]] = []
    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue
        limit = int(source.get("limit") or per_source_limit)
        try:
            raw_records.extend(
                _collect_source(
                    source=source,
                    query=str(source.get("query") or query),
                    limit=limit,
                    fetch_json=fetch_json,
                    fetch_text=fetch_text,
                    post_json=post_json,
                    apify_token=token,
                )
            )
        except Exception:
            continue

    raw_records = _dedupe_raw_records(raw_records)[: int(config.get("pool_size", 60))]
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(raw_records, indent=2))
    return raw_records


def build_report(
    watchlist: Watchlist,
    records: list[HarvestRecord],
    week: str | None = None,
) -> IntelReport:
    watched = {entity.name: entity for entity in watchlist.entities}
    watched_records = [record for record in records if record.entity in watched]
    unmatched = [record for record in records if record.entity not in watched]

    records_by_theme: dict[str, list[HarvestRecord]] = {}
    for theme, keywords in watchlist.theme_keywords.items():
        rule = watchlist.theme_rules.get(theme, {})
        records_by_theme[theme] = [
            record
            for record in watched_records
            if _record_matches_theme(record, keywords, rule)
        ]

    market_moves: list[MarketMove] = []
    for theme, theme_records in records_by_theme.items():
        entities = sorted({record.entity for record in theme_records})
        if len(entities) >= watchlist.min_entities_for_move:
            rule = watchlist.theme_rules.get(theme, {})
            ranked_records = sorted(
                theme_records,
                key=lambda record: (
                    -_record_quality_score(record, rule),
                    record.published_at,
                    record.entity,
                    record.source_id,
                ),
            )
            evidence_limit = int(rule.get("evidence_limit") or 5)
            capped_records = _select_evidence_records(ranked_records, evidence_limit)
            score = sum(_record_quality_score(record, rule) for record in ranked_records)
            market_moves.append(
                MarketMove(
                    theme=theme,
                    entities=entities,
                    evidence_count=len(theme_records),
                    records=capped_records,
                    score=round(score, 2),
                    why_this_matters=_why_this_matters(theme, entities, len(theme_records), ranked_records),
                )
            )

    market_moves.sort(key=lambda move: (-move.score, -len(move.entities), -move.evidence_count, move.theme))

    entity_activity: list[EntityActivity] = []
    for entity in watchlist.entities:
        entity_records = [record for record in watched_records if record.entity == entity.name]
        themes = sorted(
            theme
            for theme, theme_records in records_by_theme.items()
            if any(record.entity == entity.name for record in theme_records)
        )
        entity_activity.append(
            EntityActivity(
                entity=entity.name,
                category=entity.category,
                record_count=len(entity_records),
                sources=sorted({record.source for record in entity_records}),
                themes=themes,
            )
        )

    return IntelReport(
        watchlist_name=watchlist.name,
        week=week or _current_iso_week(),
        records_seen=len(records),
        market_moves=market_moves,
        entity_activity=entity_activity,
        unmatched_records=unmatched,
    )


def render_newsletter(report: IntelReport) -> str:
    lines = [
        f"# {report.watchlist_name} Competitive Intel",
        "",
        f"Week: {report.week}",
        f"Records scanned: {report.records_seen}",
        "",
        "## Market Moves",
        "",
    ]

    if report.market_moves:
        for move in report.market_moves:
            entities = ", ".join(move.entities)
            lines.extend(
                [
                    f"### {move.theme}",
                    "",
                    (
                        f"{len(move.entities)} watched entities converged on "
                        f"{move.theme}: {entities}."
                    ),
                    "",
                    f"Evidence records: {move.evidence_count}",
                    "",
                    f"Why this matters: {move.why_this_matters}",
                    "",
                ]
            )
            for record in move.records:
                lines.append(f"- {record.entity} on {record.source}: {_one_line(record.text)}")
                if record.url:
                    lines.append(f"  Source: {record.url}")
            lines.append("")
    else:
        lines.extend(["No cross-entity market moves met the threshold.", ""])

    lines.extend(["## Entity Activity", ""])
    for activity in report.entity_activity:
        themes = ", ".join(activity.themes) if activity.themes else "none"
        sources = ", ".join(activity.sources) if activity.sources else "none"
        lines.append(
            f"- {activity.entity} ({activity.category}): "
            f"{activity.record_count} records, sources: {sources}, themes: {themes}"
        )

    lines.extend(["", "## Source Appendix", ""])
    seen_sources: set[tuple[str, str, str]] = set()
    for move in report.market_moves:
        for record in move.records:
            label = record.url or record.source_id or "no source id"
            source_key = (record.entity, record.source, label)
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)
            lines.append(f"- {record.entity} / {record.source}: {label}")

    if report.unmatched_records:
        lines.extend(["", "## Unmatched Records", ""])
        for record in report.unmatched_records:
            lines.append(f"- {record.entity} / {record.source}: {_one_line(record.text)}")

    return "\n".join(lines).rstrip() + "\n"


def run_workflow(
    watchlist_path: str | Path,
    records_path: str | Path,
    output_path: str | Path,
    report_json_path: str | Path | None = None,
    week: str | None = None,
) -> IntelReport:
    watchlist = load_watchlist(watchlist_path)
    records = load_records(records_path)
    report = build_report(watchlist, records, week=week)
    markdown = render_newsletter(report)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown)

    if report_json_path:
        report_json = Path(report_json_path)
        report_json.parent.mkdir(parents=True, exist_ok=True)
        report_json.write_text(json.dumps(report.to_dict(), indent=2))

    return report


def run_weekly_workflow(
    watchlist_path: str | Path,
    raw_records_path: str | Path,
    output_dir: str | Path,
    run_date: str | None = None,
    week: str | None = None,
    podcast_digest: bool = False,
    coverage_ledger_path: str | Path | None = None,
) -> IntelReport:
    stamp = run_date or date.today().isoformat()
    intel_dir = Path(output_dir) / "competitive-intel"
    normalized_path = intel_dir / f"{stamp}.records.json"
    newsletter_path = intel_dir / f"{stamp}.md"
    report_json_path = intel_dir / f"{stamp}.report.json"
    podcast_path = intel_dir / f"{stamp}.podcast.txt"

    records = normalize_raw_records(raw_records_path, output_path=normalized_path)
    if coverage_ledger_path:
        from kipi_mcp.signal_core import filter_new_records

        records, _dropped = filter_new_records(records, coverage_ledger_path, today=stamp)
        normalized_path.write_text(json.dumps([asdict(record) for record in records], indent=2))

    report = run_workflow(
        watchlist_path=watchlist_path,
        records_path=normalized_path,
        output_path=newsletter_path,
        report_json_path=report_json_path,
        week=week,
    )
    if podcast_digest:
        from kipi_mcp.signal_core import render_podcast_digest

        podcast_path.write_text(render_podcast_digest(report, date=stamp))
    if coverage_ledger_path:
        from kipi_mcp.signal_core import commit_coverage

        commit_coverage(coverage_ledger_path, records, date=stamp)
    return report


def run_collect_weekly_workflow(
    watchlist_path: str | Path,
    output_dir: str | Path,
    run_date: str | None = None,
    week: str | None = None,
    query: str = "AI agent OR Claude Code OR MCP OR eval harness",
    per_source_limit: int = 5,
    sources_config_path: str | Path | None = None,
    collector: Any | None = None,
    podcast_digest: bool = False,
    coverage_ledger_path: str | Path | None = None,
) -> IntelReport:
    stamp = run_date or date.today().isoformat()
    intel_dir = Path(output_dir) / "competitive-intel"
    intel_dir.mkdir(parents=True, exist_ok=True)
    raw_path = intel_dir / f"{stamp}.raw.json"

    collector_fn = collector or collect_ai_raw_records
    collector_fn(
        output_path=raw_path,
        query=query,
        per_source_limit=per_source_limit,
        **({"sources_config_path": sources_config_path} if sources_config_path else {}),
    )
    return run_weekly_workflow(
        watchlist_path=watchlist_path,
        raw_records_path=raw_path,
        output_dir=output_dir,
        run_date=stamp,
        week=week,
        podcast_digest=podcast_digest,
        coverage_ledger_path=coverage_ledger_path,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] == "weekly":
        parser = argparse.ArgumentParser(description="Build a weekly competitive intel newsletter.")
        parser.add_argument("command", choices=["weekly"])
        parser.add_argument("--watchlist", required=True, help="YAML or JSON watchlist path")
        parser.add_argument("--raw-records", required=True, help="Raw harvest records JSON path")
        parser.add_argument("--output-dir", required=True, help="Base output directory")
        parser.add_argument("--run-date", help="Output date, for example 2026-06-30")
        parser.add_argument("--week", help="Week label, for example 2026-W27")
        parser.add_argument(
            "--podcast-digest",
            action="store_true",
            help="Write a NotebookLM-ready podcast source brief",
        )
        parser.add_argument("--coverage-ledger", help="JSONL ledger for records already covered")
        args = parser.parse_args(args_list)

        run_weekly_workflow(
            watchlist_path=args.watchlist,
            raw_records_path=args.raw_records,
            output_dir=args.output_dir,
            run_date=args.run_date,
            week=args.week,
            podcast_digest=args.podcast_digest,
            coverage_ledger_path=args.coverage_ledger,
        )
        return 0

    if args_list and args_list[0] == "collect-weekly":
        parser = argparse.ArgumentParser(description="Collect public AI signals and build a newsletter.")
        parser.add_argument("command", choices=["collect-weekly"])
        parser.add_argument("--watchlist", required=True, help="YAML or JSON watchlist path")
        parser.add_argument("--output-dir", required=True, help="Base output directory")
        parser.add_argument("--run-date", help="Output date, for example 2026-06-30")
        parser.add_argument("--week", help="Week label, for example 2026-W27")
        parser.add_argument("--query", default="AI agent OR Claude Code OR MCP OR eval harness")
        parser.add_argument("--per-source-limit", type=int, default=5)
        parser.add_argument("--sources-config", help="Optional collector source config JSON")
        parser.add_argument(
            "--podcast-digest",
            action="store_true",
            help="Write a NotebookLM-ready podcast source brief",
        )
        parser.add_argument("--coverage-ledger", help="JSONL ledger for records already covered")
        args = parser.parse_args(args_list)

        run_collect_weekly_workflow(
            watchlist_path=args.watchlist,
            output_dir=args.output_dir,
            run_date=args.run_date,
            week=args.week,
            query=args.query,
            per_source_limit=args.per_source_limit,
            sources_config_path=args.sources_config,
            podcast_digest=args.podcast_digest,
            coverage_ledger_path=args.coverage_ledger,
        )
        return 0

    parser = argparse.ArgumentParser(description="Build a competitive intel newsletter.")
    parser.add_argument("--watchlist", required=True, help="YAML or JSON watchlist path")
    parser.add_argument("--records", required=True, help="Normalized harvest records JSON path")
    parser.add_argument("--output", required=True, help="Markdown newsletter output path")
    parser.add_argument("--report-json", help="Optional structured JSON report output path")
    parser.add_argument("--week", help="Week label, for example 2026-W26")
    args = parser.parse_args(args_list)

    run_workflow(
        watchlist_path=args.watchlist,
        records_path=args.records,
        output_path=args.output,
        report_json_path=args.report_json,
        week=args.week,
    )
    return 0


def _load_yaml_or_json(path: Path) -> Any:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text())
    return yaml.safe_load(path.read_text())


def _normalize_raw_record(raw: dict[str, Any], index: int) -> HarvestRecord:
    summary = _extract_summary(raw)
    source_name = str(raw.get("source_name") or raw.get("source") or summary.get("source") or "")
    source = _infer_source(source_name, summary)
    entity = _infer_entity(source_name, summary, source)
    text = _extract_text(summary, raw)
    if not text:
        raise ValueError(f"raw_records[{index}].text could not be inferred")

    engagement = _extract_engagement(summary)
    record_key = str(raw.get("record_key") or raw.get("source_id") or raw.get("id") or summary.get("id") or "")

    return HarvestRecord(
        entity=entity,
        source=source,
        text=text,
        source_id=record_key,
        url=str(summary.get("url") or summary.get("link") or raw.get("url") or ""),
        published_at=str(
            summary.get("published_at")
            or summary.get("created_at")
            or summary.get("updated_at")
            or raw.get("created_at")
            or ""
        ),
        author=str(summary.get("author") or summary.get("user") or ""),
        engagement=engagement,
    )


def _extract_summary(raw: dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw.get("summary"), dict):
        return raw["summary"]
    if isinstance(raw.get("summary_json"), str):
        try:
            parsed = json.loads(raw["summary_json"])
        except json.JSONDecodeError as exc:
            raise ValueError(f"summary_json is invalid JSON: {exc}") from exc
        if isinstance(parsed, dict):
            return parsed
    return raw


def _infer_source(source_name: str, summary: dict[str, Any]) -> str:
    joined = f"{source_name} {summary.get('url', '')} {summary.get('link', '')}".lower()
    if "github" in joined or "repo" in summary or "stars" in summary:
        return "github"
    if "reddit" in joined or "subreddit" in summary:
        return "reddit"
    if "hacker" in joined or "news.ycombinator.com" in joined:
        return "hacker-news"
    if "arxiv" in joined:
        return "arxiv"
    if "huggingface" in joined:
        return "huggingface-ai"
    if "twitter" in joined or source_name.lower().startswith("x-") or "x.com" in joined:
        return "x"
    if "youtube" in joined:
        return "youtube"
    if "linkedin" in joined:
        return "linkedin"
    if "substack" in joined:
        return "substack"
    if "medium" in joined:
        return "medium"
    return source_name or "unknown"


def _infer_entity(source_name: str, summary: dict[str, Any], source: str) -> str:
    explicit = summary.get("entity") or summary.get("account") or summary.get("source_entity")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    author = summary.get("author") or summary.get("user")
    if isinstance(author, str) and author.strip() and source in {"x", "linkedin", "youtube"}:
        return author.strip()

    if source == "github":
        return "GitHub Trending"
    if source == "reddit":
        return "Reddit AI Builders"
    if source == "hacker-news":
        return "Hacker News AI Builders"
    if source == "arxiv":
        return "AI Research Papers"
    if source == "huggingface-ai":
        return "Hugging Face Trending"
    if source == "x":
        return "Builder Thread"
    if source == "youtube":
        return "YouTube AI Builders"
    if source == "linkedin":
        return "LinkedIn AI Builders"
    if source in {"substack", "medium", "simonwillison"}:
        return "AI Research Writers"
    return source_name or "Unknown Source"


def _load_collector_config(path: str | Path | None) -> dict[str, Any]:
    if path:
        payload = json.loads(Path(path).read_text())
        if not isinstance(payload, dict):
            raise ValueError("collector config must be a mapping")
        return payload
    return {
        "pool_size": 60,
        "sources": [
            {"enabled": True, "type": "github_search", "name": "github-ai-search"},
            {"enabled": True, "type": "hackernews", "name": "hacker-news-ai"},
            {
                "enabled": True,
                "type": "reddit_rss",
                "name": "reddit-ai-builds",
                "subreddits": ["ClaudeCode", "mcp", "ClaudeAI", "LocalLLaMA"],
            },
            {"enabled": True, "type": "arxiv", "name": "arxiv-ai"},
            {"enabled": True, "type": "huggingface", "name": "huggingface-ai"},
            {
                "enabled": True,
                "type": "x_apify",
                "name": "x-ai-builders",
                "twitter_handles": [
                    "bcherny",
                    "trq212",
                    "leerob",
                    "ericzakariasson",
                    "gregpr07",
                    "simonw",
                    "AnjneyMidha",
                    "AIHighlight",
                ],
                "days_back": 2,
                "max_items": 80,
                "per_author_cap": 2,
            },
            {
                "enabled": True,
                "type": "rss",
                "name": "simonwillison",
                "url": "https://simonwillison.net/atom/everything/",
            },
            {
                "enabled": True,
                "type": "rss",
                "name": "claude-code-releases",
                "url": "https://github.com/anthropics/claude-code/releases.atom",
            },
            {
                "enabled": True,
                "type": "rss",
                "name": "openhands-releases",
                "url": "https://github.com/All-Hands-AI/OpenHands/releases.atom",
            },
        ],
    }


def _collect_source(
    source: dict[str, Any],
    query: str,
    limit: int,
    fetch_json: Any,
    fetch_text: Any,
    post_json: Any,
    apify_token: str,
) -> list[dict[str, Any]]:
    source_type = source.get("type")
    if source_type == "github_search":
        return _collect_github_search(source, query, limit, fetch_json)
    if source_type == "hackernews":
        return _collect_hackernews(source, query, limit, fetch_json)
    if source_type == "reddit_rss":
        return _collect_reddit_rss(source, limit, fetch_json)
    if source_type == "rss":
        return _collect_rss(source, limit, fetch_text)
    if source_type == "huggingface":
        return _collect_huggingface(source, limit, fetch_json)
    if source_type == "arxiv":
        return _collect_arxiv(source, query, limit, fetch_text)
    if source_type == "x_apify":
        return _collect_x_apify(source, limit, post_json, apify_token)
    return []


def _collect_github_search(
    source: dict[str, Any],
    query: str,
    limit: int,
    fetch_json: Any,
) -> list[dict[str, Any]]:
    created_after = (date.today() - timedelta(days=int(source.get("days_back", 14)))).isoformat()
    q = f"{query} created:>={created_after}"
    url = (
        "https://api.github.com/search/repositories?"
        + urllib.parse.urlencode(
            {
                "q": q,
                "sort": source.get("sort", "stars"),
                "order": "desc",
                "per_page": limit,
            }
        )
    )
    data = fetch_json(url)
    records: list[dict[str, Any]] = []
    for item in data.get("items", [])[:limit]:
        repo = item.get("full_name") or item.get("name") or ""
        records.append(
            _raw_record(
                source_name=source["name"],
                record_key=str(item.get("id") or repo),
                summary={
                    "repo": repo,
                    "title": f"New repo: {repo}",
                    "description": item.get("description") or "",
                    "url": item.get("html_url") or "",
                    "published_at": item.get("created_at") or item.get("updated_at") or "",
                    "stars": item.get("stargazers_count") or 0,
                    "forks": item.get("forks_count") or 0,
                },
            )
        )
    return records


def _collect_hackernews(
    source: dict[str, Any],
    query: str,
    limit: int,
    fetch_json: Any,
) -> list[dict[str, Any]]:
    url = (
        "https://hn.algolia.com/api/v1/search_by_date?"
        + urllib.parse.urlencode({"tags": "story", "query": query, "hitsPerPage": limit})
    )
    data = fetch_json(url)
    records: list[dict[str, Any]] = []
    for hit in data.get("hits", [])[:limit]:
        points = hit.get("points") or 0
        link = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        records.append(
            _raw_record(
                source_name=source["name"],
                record_key=str(hit.get("objectID") or link),
                summary={
                    "title": hit.get("title") or hit.get("story_title") or "",
                    "description": hit.get("story_text") or "",
                    "url": link,
                    "published_at": hit.get("created_at") or "",
                    "score": points,
                    "comments": hit.get("num_comments") or 0,
                },
            )
        )
    return records


def _collect_reddit_rss(source: dict[str, Any], limit: int, fetch_json: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    subs = [str(sub).lstrip("/").removeprefix("r/") for sub in source.get("subreddits", [])]
    after = (date.today() - timedelta(days=int(source.get("lookback_days", 35)))).isoformat()
    per_sub = int(source.get("posts_per_sub") or source.get("per_sub") or limit)
    for sub in subs:
        if len(records) >= limit:
            break
        for entry in _reddit_archive_posts(sub, after, per_sub, fetch_json):
            records.append(
                _raw_record(
                    source_name=source["name"],
                    record_key=entry.get("id") or entry.get("url") or entry.get("title") or "",
                    summary={
                        "subreddit": sub,
                        "title": entry.get("title") or "",
                        "selftext": entry.get("selftext") or "",
                        "url": entry.get("url") or "",
                        "published_at": entry.get("published_at") or "",
                        "score": entry.get("score") or 0,
                        "comments": entry.get("comment_count") or 0,
                    },
                )
            )
            if len(records) >= limit:
                break
    return records


def _reddit_archive_posts(subreddit: str, after: str, limit: int, fetch_json: Any) -> list[dict[str, Any]]:
    try:
        return [
            post
            for post in (_reddit_archive_post(item) for item in _archive_items(fetch_json(_arctic_posts_url(subreddit, after, limit))))
            if post
        ]
    except Exception:
        pass
    try:
        return [
            post
            for post in (_reddit_archive_post(item) for item in _archive_items(fetch_json(_pullpush_posts_url(subreddit, limit))))
            if post
        ]
    except Exception:
        return []


def _archive_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        data = payload.get("data", [])
        return data if isinstance(data, list) else []
    return payload if isinstance(payload, list) else []


def _arctic_posts_url(subreddit: str, after: str, limit: int) -> str:
    query = urllib.parse.urlencode({"subreddit": subreddit, "after": after, "limit": limit, "sort": "desc"})
    return f"{ARCTIC_BASE}/api/posts/search?{query}"


def _pullpush_posts_url(subreddit: str, limit: int) -> str:
    query = urllib.parse.urlencode({"subreddit": subreddit, "size": limit, "sort": "desc"})
    return f"{PULLPUSH_BASE}/reddit/search/submission?{query}"


def _reddit_archive_post(data: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    post_id = str(data.get("id") or "").strip()
    title = str(data.get("title") or "").strip()
    subreddit = str(data.get("subreddit") or "").strip()
    if not post_id or not title or not subreddit:
        return None
    permalink = str(data.get("permalink") or "")
    url = f"https://www.reddit.com{permalink}" if permalink else str(data.get("url") or "")
    return {
        "id": post_id,
        "subreddit": subreddit,
        "title": unescape(title),
        "selftext": unescape(str(data.get("selftext") or "")),
        "url": url,
        "published_at": _epoch_to_iso(data.get("created_utc")),
        "score": int(data.get("score") or data.get("ups") or 0),
        "comment_count": int(data.get("num_comments") or 0),
    }


def _epoch_to_iso(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return ""


def _collect_rss(source: dict[str, Any], limit: int, fetch_text: Any) -> list[dict[str, Any]]:
    xml = fetch_text(source["url"])
    records = []
    for entry in _parse_feed(xml)[:limit]:
        records.append(
            _raw_record(
                source_name=source["name"],
                record_key=entry.get("url") or entry.get("title") or "",
                summary={
                    "entity": "AI Research Writers",
                    "author": "AI Research Writers",
                    "title": entry.get("title") or "",
                    "description": entry.get("summary") or "",
                    "url": entry.get("url") or "",
                    "published_at": entry.get("published_at") or "",
                },
            )
        )
    return records


def _collect_huggingface(source: dict[str, Any], limit: int, fetch_json: Any) -> list[dict[str, Any]]:
    data = fetch_json(f"https://huggingface.co/api/models?sort=trendingScore&limit={limit}")
    records = []
    for item in data[:limit]:
        model_id = item.get("modelId") or item.get("id") or ""
        if not model_id:
            continue
        records.append(
            _raw_record(
                source_name=source["name"],
                record_key=model_id,
                summary={
                    "entity": "Hugging Face Trending",
                    "title": f"Trending model: {model_id}",
                    "description": item.get("pipeline_tag") or "",
                    "url": f"https://huggingface.co/{model_id}",
                    "published_at": item.get("createdAt") or item.get("lastModified") or "",
                    "likes": item.get("likes") or 0,
                },
            )
        )
    return records


def _collect_arxiv(source: dict[str, Any], query: str, limit: int, fetch_text: Any) -> list[dict[str, Any]]:
    url = (
        "https://export.arxiv.org/api/query?"
        + urllib.parse.urlencode(
            {
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": limit,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }
        )
    )
    xml = fetch_text(url)
    records = []
    for entry in _parse_feed(xml)[:limit]:
        records.append(
            _raw_record(
                source_name=source["name"],
                record_key=entry.get("url") or entry.get("title") or "",
                summary={
                    "entity": "AI Research Papers",
                    "title": entry.get("title") or "",
                    "description": entry.get("summary") or "",
                    "url": entry.get("url") or "",
                    "published_at": entry.get("published_at") or "",
                },
            )
        )
    return records


def _collect_x_apify(
    source: dict[str, Any],
    limit: int,
    post_json: Any,
    apify_token: str,
) -> list[dict[str, Any]]:
    if not apify_token:
        return []

    handles = [
        str(handle).lstrip("@").strip()
        for handle in source.get("twitter_handles", [])
        if str(handle).strip()
    ]
    search_terms = source.get("search_terms") or []
    if not handles and not search_terms:
        return []

    payload: dict[str, Any] = {
        "maxItems": int(source.get("max_items") or limit),
        "sort": "Latest",
        "start": (date.today() - timedelta(days=int(source.get("days_back", 2)))).isoformat(),
    }
    if handles:
        payload["twitterHandles"] = handles
    if search_terms:
        payload["searchTerms"] = search_terms

    url = "https://api.apify.com/v2/acts/apidojo~tweet-scraper/run-sync-get-dataset-items"
    tweets = post_json(url, payload, apify_token)
    records: list[dict[str, Any]] = []
    author_counts: dict[str, int] = {}
    per_author_cap = int(source.get("per_author_cap") or 2)

    for tweet in tweets:
        text = str(tweet.get("text") or "").strip()
        if not text or text.startswith("RT @") or tweet.get("isRetweet"):
            continue
        author = ""
        if isinstance(tweet.get("author"), dict):
            author = str(tweet["author"].get("userName") or "")
        author = author or str(tweet.get("authorUsername") or "")
        if author_counts.get(author, 0) >= per_author_cap:
            continue
        author_counts[author] = author_counts.get(author, 0) + 1

        records.append(
            _raw_record(
                source_name=source["name"],
                record_key=str(tweet.get("id") or tweet.get("url") or text[:80]),
                summary={
                    "entity": "Builder Thread",
                    "author": author,
                    "title": (f"@{author}: " if author else "") + text[:120],
                    "description": text,
                    "url": tweet.get("url") or "",
                    "published_at": tweet.get("createdAt") or tweet.get("created_at") or "",
                    "likes": tweet.get("likeCount") or 0,
                    "reposts": tweet.get("retweetCount") or 0,
                },
            )
        )
        if len(records) >= limit:
            break
    return records


def _raw_record(source_name: str, record_key: str, summary: dict[str, Any]) -> dict[str, Any]:
    return {"source_name": source_name, "record_key": record_key, "summary": summary}


def _fetch_text(url: str, headers: dict[str, str] | None = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
        return response.read().decode("utf-8", "replace")


def _fetch_json(url: str, headers: dict[str, str] | None = None) -> Any:
    return json.loads(_fetch_text(url, headers))


def _post_json(url: str, payload: dict[str, Any], token: str) -> Any:
    request_url = f"{url}?token={urllib.parse.quote(token)}"
    req = urllib.request.Request(
        request_url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _parse_feed(xml: str) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml)
    entries: list[dict[str, str]] = []
    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag not in {"entry", "item"}:
            continue
        entries.append(
            {
                "title": _feed_text(node, "title"),
                "summary": _feed_text(node, "description", "summary", "content"),
                "url": _feed_link(node),
                "published_at": _feed_text(node, "pubDate", "published", "updated"),
            }
        )
    return entries


def _feed_text(node: ElementTree.Element, *tags: str) -> str:
    for wanted in tags:
        for child in node:
            if child.tag.split("}")[-1] == wanted and child.text:
                return re.sub(r"\s+", " ", child.text).strip()
    return ""


def _feed_link(node: ElementTree.Element) -> str:
    for child in node:
        if child.tag.split("}")[-1] != "link":
            continue
        if child.get("href"):
            return child.get("href") or ""
        if child.text:
            return child.text.strip()
    for child in node:
        if child.tag.split("}")[-1] == "id" and child.text:
            return child.text.strip()
    return ""


def _dedupe_raw_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        summary = record.get("summary") if isinstance(record.get("summary"), dict) else {}
        key = str(summary.get("url") or record.get("record_key") or summary.get("title") or "").lower()
        key = key.split("?")[0].rstrip("/")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _extract_text(summary: dict[str, Any], raw: dict[str, Any]) -> str:
    fields = (
        "title",
        "description",
        "summary",
        "text",
        "selftext",
        "body",
        "repo",
        "name",
    )
    parts: list[str] = []
    for field_name in fields:
        value = summary.get(field_name)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())

    if not parts:
        body = raw.get("body")
        if isinstance(body, str) and body.strip():
            parts.append(body.strip())

    return _clean_text(" ".join(dict.fromkeys(parts)))


def _extract_engagement(summary: dict[str, Any]) -> dict[str, Any]:
    engagement: dict[str, Any] = {}
    for key in ("stars", "forks", "score", "comments", "likes", "reposts", "views"):
        if key in summary:
            engagement[key] = summary[key]
    raw_engagement = summary.get("engagement")
    if isinstance(raw_engagement, dict):
        engagement.update(raw_engagement)
    return engagement


def _string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be a non-empty list")
    out: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name}[{index}] must be a non-empty string")
        out.append(item.strip())
    return out


def _matches_any_keyword(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(_contains_phrase(lowered, keyword) for keyword in keywords)


def _record_matches_theme(record: HarvestRecord, keywords: list[str], rule: dict[str, Any]) -> bool:
    allow_sources = set(rule.get("allow_sources") or [])
    deny_sources = set(rule.get("deny_sources") or [])
    if allow_sources and record.source not in allow_sources:
        return False
    if deny_sources and record.source in deny_sources:
        return False
    deny_entities = set(rule.get("deny_entities") or [])
    if deny_entities and record.entity in deny_entities:
        return False
    return _matches_any_keyword(record.text, keywords)


def _contains_phrase(lowered_text: str, keyword: str) -> bool:
    lowered_keyword = keyword.lower().strip()
    if not lowered_keyword:
        return False
    if re.search(r"[a-z0-9]", lowered_keyword):
        pattern = r"(?<![a-z0-9])" + re.escape(lowered_keyword) + r"(?![a-z0-9])"
        return re.search(pattern, lowered_text) is not None
    return lowered_keyword in lowered_text


def _record_quality_score(record: HarvestRecord, rule: dict[str, Any]) -> float:
    weights = rule.get("source_weights") or {}
    score = float(weights.get(record.source, 1.0))
    if record.url:
        score += 0.2
    for key in ("stars", "score", "likes", "reposts", "comments", "views"):
        value = record.engagement.get(key)
        if isinstance(value, (int, float)) and value > 0:
            score += min(2.0, value ** 0.25 / 4)
            break
    return score


def _why_this_matters(
    theme: str,
    entities: list[str],
    evidence_count: int,
    records: list[HarvestRecord],
) -> str:
    source_count = len({record.source for record in records})
    top_sources = ", ".join(sorted({record.source for record in records})[:3])
    return (
        f"{evidence_count} signals across {len(entities)} watched entities and "
        f"{source_count} source types suggest {theme} shows up in multiple "
        f"independent sources, not just one feed. Strongest sources: {top_sources}."
    )


def _select_evidence_records(records: list[HarvestRecord], evidence_limit: int) -> list[HarvestRecord]:
    if evidence_limit <= 0:
        return []
    selected: list[HarvestRecord] = []
    selected_keys: set[tuple[str, str, str]] = set()
    seen_entities: set[str] = set()

    for record in records:
        key = (record.entity, record.source, record.url or record.source_id or record.text)
        if record.entity in seen_entities or key in selected_keys:
            continue
        selected.append(record)
        selected_keys.add(key)
        seen_entities.add(record.entity)
        if len(selected) >= evidence_limit:
            return selected

    for record in records:
        key = (record.entity, record.source, record.url or record.source_id or record.text)
        if key in selected_keys:
            continue
        selected.append(record)
        selected_keys.add(key)
        if len(selected) >= evidence_limit:
            break
    return selected


def _clean_text(value: str) -> str:
    text = unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _current_iso_week() -> str:
    year, week, _ = date.today().isocalendar()
    return f"{year}-W{week:02d}"


def _one_line(text: str, limit: int = 180) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."
