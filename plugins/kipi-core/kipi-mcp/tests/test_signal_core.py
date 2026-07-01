from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from kipi_mcp.competitive_intel import build_report, load_records, load_watchlist, run_weekly_workflow
from kipi_mcp.signal_core import (
    bank_signal_buffer,
    commit_coverage,
    draw_signal_buffer,
    filter_new_records,
    item_key,
    render_podcast_digest,
)


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, indent=2))
    return path


def _watchlist(path: Path) -> Path:
    path.write_text(
        """
name: AI Builds Radar
theme_keywords:
  model releases:
    - claude sonnet
    - text-generation
  coding agents:
    - coding agent
    - mcp
entities:
  - name: Hugging Face Trending
    category: models
    sources:
      huggingface:
        - trending
  - name: AI Research Writers
    category: research
    sources:
      rss:
        - simonwillison
  - name: Hacker News AI Builders
    category: community
    sources:
      hacker-news:
        - show-hn
""".strip()
    )
    return path


def _records(path: Path) -> Path:
    return _write_json(
        path,
        [
            {
                "entity": "Hugging Face Trending",
                "source": "huggingface-ai",
                "url": "https://huggingface.co/zai-org/GLM-5.2?utm_source=x",
                "published_at": "2026-06-30T10:00:00Z",
                "text": "Trending model: zai-org/GLM-5.2 text-generation",
            },
            {
                "entity": "AI Research Writers",
                "source": "simonwillison",
                "url": "https://example.com/claude-sonnet-5",
                "published_at": "2026-06-30T11:00:00Z",
                "text": "Claude Sonnet 5 is the new model release for coding agent work.",
            },
            {
                "entity": "Hacker News AI Builders",
                "source": "hacker-news",
                "url": "https://news.ycombinator.com/item?id=1",
                "published_at": "2026-06-30T12:00:00Z",
                "text": "Show HN: MCP runtime for coding agents.",
            },
        ],
    )


def test_item_key_canonicalizes_urls_and_blocks_repeat_records(tmp_path):
    records = load_records(_records(tmp_path / "records.json"))
    ledger_path = tmp_path / "coverage.jsonl"
    commit_coverage(ledger_path, [records[0]], date="2026-06-30")

    same_story = {
        "entity": "Hugging Face Trending",
        "source": "huggingface-ai",
        "url": "https://huggingface.co/zai-org/GLM-5.2?ref=feed",
        "text": "Trending model: zai-org/GLM-5.2 text-generation",
    }
    fresh_story = {
        "entity": "AI Research Writers",
        "source": "simonwillison",
        "url": "https://example.com/claude-sonnet-5",
        "text": "Claude Sonnet 5 adds stronger tool use.",
    }

    kept, dropped = filter_new_records(
        load_records(_write_json(tmp_path / "incoming.json", [same_story, fresh_story])),
        ledger_path,
    )

    assert item_key(records[0]) == item_key(load_records(_write_json(tmp_path / "dupe.json", [same_story]))[0])
    assert [record.url for record in kept] == ["https://example.com/claude-sonnet-5"]
    assert dropped[0][1] == "covered-exact"


def test_signal_buffer_banks_only_fresh_unaired_records(tmp_path):
    now = datetime(2026, 6, 30, 12, tzinfo=timezone.utc).timestamp()
    records = load_records(
        _write_json(
            tmp_path / "pool.json",
            [
                {
                    "entity": "Hugging Face Trending",
                    "source": "huggingface-ai",
                    "url": "https://example.com/aired",
                    "published_at": "2026-06-30T11:00:00Z",
                    "text": "aired text-generation model",
                },
                {
                    "entity": "AI Research Writers",
                    "source": "simonwillison",
                    "url": "https://example.com/fresh",
                    "published_at": "2026-06-30T10:00:00Z",
                    "text": "fresh Claude Sonnet signal",
                },
                {
                    "entity": "Hacker News AI Builders",
                    "source": "hacker-news",
                    "url": "https://example.com/stale",
                    "published_at": "2026-06-27T10:00:00Z",
                    "text": "stale MCP signal",
                },
            ],
        )
    )
    buffer_path = tmp_path / "buffer.json"

    banked = bank_signal_buffer(buffer_path, pool_records=records, aired_records=[records[0]], now_ts=now)
    drawn = draw_signal_buffer(buffer_path, now_ts=now)

    assert [record.url for record in banked] == ["https://example.com/fresh"]
    assert [record.url for record in drawn] == ["https://example.com/fresh"]


def test_render_podcast_digest_turns_market_moves_into_notebooklm_source(tmp_path):
    watchlist = load_watchlist(_watchlist(tmp_path / "watchlist.yaml"))
    report = build_report(watchlist, load_records(_records(tmp_path / "records.json")), week="2026-W27")

    digest = render_podcast_digest(report, date="2026-06-30")

    assert "AI market analyst source brief for 2026-06-30" in digest
    assert "Part 1 - Market moves" in digest
    assert "model releases" in digest
    assert "Why it matters:" in digest
    assert "Source:" in digest
    assert "Part 2 - Evidence receipts" in digest


def test_weekly_workflow_can_write_podcast_digest_and_coverage_ledger(tmp_path):
    report = run_weekly_workflow(
        watchlist_path=_watchlist(tmp_path / "watchlist.yaml"),
        raw_records_path=_write_json(
            tmp_path / "raw.json",
            [
                {
                    "source_name": "huggingface-ai",
                    "record_key": "hf-1",
                    "summary": {
                        "title": "Trending model",
                        "description": "GLM text-generation",
                        "url": "https://huggingface.co/zai-org/GLM-5.2",
                        "published_at": "2026-06-30T10:00:00Z",
                    },
                },
                {
                    "source_name": "simonwillison",
                    "record_key": "rss-1",
                    "summary": {
                        "title": "Claude Sonnet 5",
                        "description": "Claude Sonnet model release for coding agent work",
                        "url": "https://example.com/claude-sonnet-5",
                        "published_at": "2026-06-30T11:00:00Z",
                    },
                },
            ],
        ),
        output_dir=tmp_path / "out",
        run_date="2026-06-30",
        week="2026-W27",
        podcast_digest=True,
        coverage_ledger_path=tmp_path / "coverage.jsonl",
    )

    base = tmp_path / "out" / "competitive-intel" / "2026-06-30"
    assert report.market_moves
    assert (base.with_suffix(".podcast.txt")).exists()
    assert "Part 1 - Market moves" in base.with_suffix(".podcast.txt").read_text()
    assert (tmp_path / "coverage.jsonl").read_text().count("\n") == 2
