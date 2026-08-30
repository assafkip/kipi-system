from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from kipi_mcp.competitive_intel import (
    build_report,
    collect_ai_raw_records,
    load_records,
    load_watchlist,
    main,
    normalize_raw_records,
    render_newsletter,
    run_weekly_workflow,
    run_collect_weekly_workflow,
    run_workflow,
)


def _ai_quality_watchlist(path: Path) -> Path:
    return _write_yaml(
        path,
        {
            "name": "AI Builds Radar",
            "theme_keywords": {
                "model releases": [
                    "model release",
                    "new model",
                    "text-generation",
                    "claude sonnet",
                    "qwen",
                    "glm",
                ],
                "new repos": ["open-source", "new repo", "github"],
                "coding agents": ["coding agent", "claude code", "mcp", "ai agent"],
            },
            "theme_rules": {
                "model releases": {
                    "allow_sources": ["huggingface-ai", "simonwillison", "github", "reddit"],
                    "deny_sources": ["hacker-news"],
                    "evidence_limit": 3,
                    "source_weights": {
                        "huggingface-ai": 5,
                        "simonwillison": 4,
                        "github": 3,
                        "reddit": 2,
                    },
                },
                "new repos": {
                    "deny_sources": ["arxiv"],
                    "evidence_limit": 3,
                    "source_weights": {"github": 5, "hacker-news": 3, "x": 2},
                },
                "coding agents": {"evidence_limit": 3},
            },
            "entities": [
                {"name": "GitHub Trending", "category": "repos", "sources": {"github": ["trending"]}},
                {"name": "Hacker News AI Builders", "category": "community", "sources": {"hacker-news": ["show-hn"]}},
                {"name": "Hugging Face Trending", "category": "models", "sources": {"huggingface": ["trending"]}},
                {"name": "AI Research Writers", "category": "research", "sources": {"rss": ["simonwillison"]}},
                {"name": "AI Research Papers", "category": "research", "sources": {"arxiv": ["cs-ai"]}},
            ],
        },
    )


def _write_yaml(path: Path, payload: dict) -> Path:
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    return path


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, indent=2))
    return path


def _watchlist(path: Path) -> Path:
    return _write_yaml(
        path,
        {
            "name": "Beauty Competitive Set",
            "theme_keywords": {
                "barrier repair": ["barrier repair", "ceramide", "skin barrier"],
                "mini formats": ["mini size", "travel size"],
            },
            "entities": [
                {
                    "name": "North Star Skin",
                    "category": "brand",
                    "sources": {"instagram": ["northstarskin"]},
                },
                {
                    "name": "Glow Lab",
                    "category": "brand",
                    "sources": {"tiktok": ["glowlab"]},
                },
                {
                    "name": "Retail Pulse",
                    "category": "retailer",
                    "sources": {"youtube": ["retailpulse"]},
                },
            ],
        },
    )


def _records(path: Path) -> Path:
    return _write_json(
        path,
        [
            {
                "entity": "North Star Skin",
                "source": "instagram",
                "source_id": "ig-1",
                "url": "https://example.com/ig-1",
                "published_at": "2026-06-24T12:00:00Z",
                "text": "Launching our new ceramide barrier repair serum this week.",
            },
            {
                "entity": "Glow Lab",
                "source": "tiktok",
                "source_id": "tt-1",
                "url": "https://example.com/tt-1",
                "published_at": "2026-06-25T12:00:00Z",
                "text": "Creators keep asking why skin barrier routines are everywhere.",
            },
            {
                "entity": "Retail Pulse",
                "source": "youtube",
                "source_id": "yt-1",
                "url": "https://example.com/yt-1",
                "published_at": "2026-06-26T12:00:00Z",
                "text": "Retail shelf space is shifting toward barrier repair and ceramide kits.",
            },
            {
                "entity": "Glow Lab",
                "source": "x",
                "source_id": "x-1",
                "url": "https://example.com/x-1",
                "published_at": "2026-06-27T12:00:00Z",
                "text": "Our travel size kit sold out.",
            },
        ],
    )


def test_build_report_connects_cross_entity_theme(tmp_path):
    watchlist = load_watchlist(_watchlist(tmp_path / "watchlist.yaml"))
    records = load_records(_records(tmp_path / "records.json"))

    report = build_report(watchlist, records, week="2026-W26")

    assert report.week == "2026-W26"
    assert len(report.market_moves) == 1
    move = report.market_moves[0]
    assert move.theme == "barrier repair"
    assert move.entities == ["Glow Lab", "North Star Skin", "Retail Pulse"]
    assert move.evidence_count == 3

    newsletter = render_newsletter(report)
    assert "## Market Moves" in newsletter
    assert "3 watched entities converged on barrier repair" in newsletter
    assert "North Star Skin" in newsletter
    assert "https://example.com/ig-1" in newsletter


def test_run_workflow_writes_markdown_and_json(tmp_path):
    watchlist_path = _watchlist(tmp_path / "watchlist.yaml")
    records_path = _records(tmp_path / "records.json")
    markdown_path = tmp_path / "newsletter.md"
    json_path = tmp_path / "report.json"

    result = run_workflow(
        watchlist_path=watchlist_path,
        records_path=records_path,
        output_path=markdown_path,
        report_json_path=json_path,
        week="2026-W26",
    )

    assert result.market_moves[0].theme == "barrier repair"
    assert markdown_path.exists()
    assert json_path.exists()
    assert "# Beauty Competitive Set Competitive Intel" in markdown_path.read_text()
    parsed = json.loads(json_path.read_text())
    assert parsed["market_moves"][0]["theme"] == "barrier repair"


def test_watchlist_validation_rejects_missing_entity_name(tmp_path):
    watchlist_path = _write_yaml(
        tmp_path / "bad-watchlist.yaml",
        {
            "theme_keywords": {"barrier repair": ["ceramide"]},
            "entities": [{"category": "brand", "sources": {"instagram": ["missing"]}}],
        },
    )

    with pytest.raises(ValueError, match="entities\\[0\\].name"):
        load_watchlist(watchlist_path)


def test_records_validation_rejects_missing_text(tmp_path):
    records_path = _write_json(
        tmp_path / "bad-records.json",
        [{"entity": "North Star Skin", "source": "instagram", "source_id": "ig-1"}],
    )

    with pytest.raises(ValueError, match="records\\[0\\].text"):
        load_records(records_path)


def test_output_quality_cleans_html_and_entities_before_rendering(tmp_path):
    watchlist = load_watchlist(_ai_quality_watchlist(tmp_path / "watchlist.yaml"))
    records = load_records(
        _write_json(
            tmp_path / "records.json",
            [
                {
                    "entity": "Hugging Face Trending",
                    "source": "huggingface-ai",
                    "url": "https://huggingface.co/zai-org/GLM-5.2",
                    "text": "Trending model: zai-org/GLM-5.2 text-generation",
                },
                {
                    "entity": "AI Research Writers",
                    "source": "simonwillison",
                    "url": "https://example.com/claude-sonnet-5",
                    "text": "<p>What&#x27;s new in Claude Sonnet 5</p>",
                },
            ],
        )
    )

    report = build_report(watchlist, records, week="2026-W27")
    newsletter = render_newsletter(report)

    assert "<p>" not in newsletter
    assert "&#x27;" not in newsletter
    assert "What's new in Claude Sonnet 5" in newsletter


def test_theme_rules_prevent_false_model_and_new_repo_matches(tmp_path):
    watchlist = load_watchlist(_ai_quality_watchlist(tmp_path / "watchlist.yaml"))
    records = load_records(
        _write_json(
            tmp_path / "records.json",
            [
                {
                    "entity": "Hugging Face Trending",
                    "source": "huggingface-ai",
                    "url": "https://huggingface.co/zai-org/GLM-5.2",
                    "text": "Trending model: zai-org/GLM-5.2 text-generation",
                },
                {
                    "entity": "AI Research Writers",
                    "source": "simonwillison",
                    "url": "https://example.com/claude-sonnet-5",
                    "text": "Claude Sonnet 5 is the new default model in Claude Code.",
                },
                {
                    "entity": "Hacker News AI Builders",
                    "source": "hacker-news",
                    "url": "https://sigmashake.com",
                    "text": "Show HN: A policy gate that runs before your AI coding agent tool calls.",
                },
                {
                    "entity": "AI Research Papers",
                    "source": "arxiv",
                    "url": "https://arxiv.org/abs/2606.30645v1",
                    "text": "Reconstructed scenes for humanoid robotics.",
                },
            ],
        )
    )

    report = build_report(watchlist, records, week="2026-W27")

    model_move = next(move for move in report.market_moves if move.theme == "model releases")
    assert model_move.entities == ["AI Research Writers", "Hugging Face Trending"]
    assert all(record.source != "hacker-news" for record in model_move.records)
    assert all(record.source != "arxiv" for move in report.market_moves for record in move.records)


def test_newsletter_caps_evidence_and_explains_why_it_matters(tmp_path):
    watchlist = load_watchlist(_ai_quality_watchlist(tmp_path / "watchlist.yaml"))
    records = load_records(
        _write_json(
            tmp_path / "records.json",
            [
                {
                    "entity": "Hugging Face Trending",
                    "source": "huggingface-ai",
                    "url": f"https://huggingface.co/model-{idx}",
                    "text": f"Trending model: model-{idx} text-generation",
                }
                for idx in range(5)
            ]
            + [
                {
                    "entity": "AI Research Writers",
                    "source": "simonwillison",
                    "url": "https://example.com/claude-sonnet-5",
                    "text": "Claude Sonnet 5 is a new model release.",
                }
            ],
        )
    )

    report = build_report(watchlist, records, week="2026-W27")
    move = next(move for move in report.market_moves if move.theme == "model releases")
    newsletter = render_newsletter(report)

    assert move.evidence_count == 6
    assert len(move.records) == 3
    assert "Why this matters:" in newsletter
    assert "multiple independent sources" in newsletter


def test_source_weights_rank_higher_quality_evidence_first(tmp_path):
    watchlist = load_watchlist(_ai_quality_watchlist(tmp_path / "watchlist.yaml"))
    records = load_records(
        _write_json(
            tmp_path / "records.json",
            [
                {
                    "entity": "AI Research Writers",
                    "source": "simonwillison",
                    "url": "https://example.com/sonnet",
                    "text": "Claude Sonnet 5 is a new model release.",
                },
                {
                    "entity": "Hugging Face Trending",
                    "source": "huggingface-ai",
                    "url": "https://huggingface.co/qwen",
                    "text": "Trending model: Qwen-AgentWorld text-generation",
                },
                {
                    "entity": "GitHub Trending",
                    "source": "github",
                    "url": "https://github.com/example/model-wrapper",
                    "text": "New model wrapper repo for Claude Sonnet.",
                },
            ],
        )
    )

    report = build_report(watchlist, records, week="2026-W27")
    move = next(move for move in report.market_moves if move.theme == "model releases")

    assert move.records[0].source == "huggingface-ai"
    assert move.records[1].source == "simonwillison"
    assert move.score > 0


def test_evidence_cap_preserves_entity_diversity_before_filling(tmp_path):
    watchlist = load_watchlist(_ai_quality_watchlist(tmp_path / "watchlist.yaml"))
    records = load_records(
        _write_json(
            tmp_path / "records.json",
            [
                {
                    "entity": "Hugging Face Trending",
                    "source": "huggingface-ai",
                    "url": f"https://huggingface.co/model-{idx}",
                    "text": f"Trending model: model-{idx} text-generation",
                }
                for idx in range(5)
            ]
            + [
                {
                    "entity": "AI Research Writers",
                    "source": "simonwillison",
                    "url": "https://example.com/sonnet",
                    "text": "Claude Sonnet 5 is a new model release.",
                },
                {
                    "entity": "GitHub Trending",
                    "source": "github",
                    "url": "https://github.com/example/model-wrapper",
                    "text": "New model wrapper repo for Claude Sonnet.",
                },
            ],
        )
    )

    report = build_report(watchlist, records, week="2026-W27")
    move = next(move for move in report.market_moves if move.theme == "model releases")

    assert len(move.records) == 3
    assert {record.entity for record in move.records} == {
        "Hugging Face Trending",
        "AI Research Writers",
        "GitHub Trending",
    }


def test_normalize_raw_records_maps_ai_build_chatter(tmp_path):
    raw_path = _write_json(
        tmp_path / "raw.json",
        [
            {
                "source_name": "github-trending",
                "record_key": "gh-1",
                "summary": {
                    "repo": "context-labs/agent-memory",
                    "title": "Agent memory repo adds eval harness",
                    "url": "https://github.com/context-labs/agent-memory",
                    "published_at": "2026-06-28T10:00:00Z",
                    "description": "New open-source memory layer for AI agents with benchmark evals.",
                    "stars": 1840,
                },
            },
            {
                "source_name": "reddit-ai-builds",
                "record_key": "rd-1",
                "summary_json": json.dumps(
                    {
                        "subreddit": "LocalLLaMA",
                        "title": "Everyone is wiring agent memory into coding agents",
                        "selftext": "New repos keep shipping persistent context and eval harnesses.",
                        "url": "https://reddit.example/rd-1",
                        "created_at": "2026-06-28T11:00:00Z",
                        "score": 512,
                    }
                ),
            },
            {
                "source": "x-ai-builders",
                "id": "x-1",
                "author": "Builder Thread",
                "text": "Seeing a wave of agent memory launches with eval harnesses.",
                "url": "https://x.example/x-1",
                "published_at": "2026-06-28T12:00:00Z",
                "engagement": {"likes": 900},
            },
        ],
    )
    output_path = tmp_path / "records.json"

    records = normalize_raw_records(raw_path, output_path=output_path)

    assert output_path.exists()
    assert [record.entity for record in records] == [
        "GitHub Trending",
        "Reddit AI Builders",
        "Builder Thread",
    ]
    assert records[0].source == "github"
    assert records[0].engagement["stars"] == 1840
    assert "benchmark evals" in records[0].text
    assert records[1].source == "reddit"
    assert records[2].source == "x"


def test_weekly_workflow_writes_ai_trends_outputs(tmp_path):
    watchlist_path = _write_yaml(
        tmp_path / "ai-watchlist.yaml",
        {
            "name": "AI Builds Radar",
            "theme_keywords": {
                "agent memory": ["agent memory", "persistent context"],
                "eval harnesses": ["eval harness", "benchmark eval"],
            },
            "entities": [
                {"name": "GitHub Trending", "category": "repos", "sources": {"github": ["trending"]}},
                {"name": "Reddit AI Builders", "category": "community", "sources": {"reddit": ["LocalLLaMA"]}},
                {"name": "Builder Thread", "category": "builder", "sources": {"x": ["builderthread"]}},
            ],
        },
    )
    raw_path = _write_json(
        tmp_path / "raw.json",
        [
            {
                "source_name": "github-trending",
                "record_key": "gh-1",
                "summary": {
                    "repo": "context-labs/agent-memory",
                    "title": "Agent memory repo adds eval harness",
                    "description": "New memory capability for agents with benchmark evals.",
                    "url": "https://github.com/context-labs/agent-memory",
                },
            },
            {
                "source_name": "reddit-ai-builds",
                "record_key": "rd-1",
                "summary": {
                    "title": "Agent memory is the new default build",
                    "selftext": "Builders are asking for persistent context and eval harness examples.",
                    "url": "https://reddit.example/rd-1",
                },
            },
        ],
    )

    report = run_weekly_workflow(
        watchlist_path=watchlist_path,
        raw_records_path=raw_path,
        output_dir=tmp_path / "out",
        run_date="2026-06-30",
        week="2026-W27",
    )

    assert [move.theme for move in report.market_moves] == ["agent memory", "eval harnesses"]
    newsletter = tmp_path / "out" / "competitive-intel" / "2026-06-30.md"
    normalized = tmp_path / "out" / "competitive-intel" / "2026-06-30.records.json"
    structured = tmp_path / "out" / "competitive-intel" / "2026-06-30.report.json"
    assert newsletter.exists()
    assert normalized.exists()
    assert structured.exists()
    assert "AI Builds Radar Competitive Intel" in newsletter.read_text()


def test_main_weekly_subcommand_writes_outputs(tmp_path):
    watchlist_path = _write_yaml(
        tmp_path / "ai-watchlist.yaml",
        {
            "name": "AI Builds Radar",
            "theme_keywords": {"agent memory": ["agent memory", "persistent context"]},
            "entities": [
                {"name": "GitHub Trending", "category": "repos", "sources": {"github": ["trending"]}},
                {"name": "Reddit AI Builders", "category": "community", "sources": {"reddit": ["LocalLLaMA"]}},
            ],
        },
    )
    raw_path = _write_json(
        tmp_path / "raw.json",
        [
            {
                "source_name": "github-trending",
                "record_key": "gh-1",
                "summary": {"title": "Agent memory repo", "description": "persistent context"},
            },
            {
                "source_name": "reddit-ai-builds",
                "record_key": "rd-1",
                "summary": {"title": "Agent memory thread", "selftext": "persistent context"},
            },
        ],
    )

    exit_code = main(
        [
            "weekly",
            "--watchlist",
            str(watchlist_path),
            "--raw-records",
            str(raw_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--run-date",
            "2026-06-30",
            "--week",
            "2026-W27",
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "out" / "competitive-intel" / "2026-06-30.md").exists()


def test_source_appendix_dedupes_records_that_support_multiple_themes(tmp_path):
    watchlist = load_watchlist(
        _write_yaml(
            tmp_path / "watchlist.yaml",
            {
                "name": "AI Builds Radar",
                "theme_keywords": {
                    "agent memory": ["agent memory"],
                    "eval harnesses": ["eval harness"],
                },
                "entities": [
                    {"name": "GitHub Trending", "category": "repos", "sources": {"github": ["trending"]}},
                    {"name": "Reddit AI Builders", "category": "community", "sources": {"reddit": ["LocalLLaMA"]}},
                ],
            },
        )
    )
    records = [
        {
            "entity": "GitHub Trending",
            "source": "github",
            "source_id": "gh-1",
            "url": "https://example.com/gh-1",
            "text": "agent memory eval harness",
        },
        {
            "entity": "Reddit AI Builders",
            "source": "reddit",
            "source_id": "rd-1",
            "url": "https://example.com/rd-1",
            "text": "agent memory eval harness",
        },
    ]
    report = build_report(watchlist, load_records(_write_json(tmp_path / "records.json", records)))

    newsletter = render_newsletter(report)

    assert newsletter.count("GitHub Trending / github: https://example.com/gh-1") == 1
    assert newsletter.count("Reddit AI Builders / reddit: https://example.com/rd-1") == 1


def test_collect_ai_raw_records_from_public_sources_with_fake_fetchers(tmp_path):
    def fake_json(url: str) -> dict:
        if "api.github.com/search/repositories" in url:
            return {
                "items": [
                    {
                        "full_name": "agent-labs/eval-memory",
                        "html_url": "https://github.com/agent-labs/eval-memory",
                        "description": "Agent memory with regression eval harness",
                        "stargazers_count": 2400,
                        "forks_count": 210,
                        "updated_at": "2026-06-30T10:00:00Z",
                    }
                ]
            }
        if "hn.algolia.com/api/v1/search_by_date" in url:
            return {
                "hits": [
                    {
                        "objectID": "hn-1",
                        "title": "Show HN: browser agent with eval harnesses",
                        "url": "https://news.ycombinator.com/item?id=1",
                        "created_at": "2026-06-30T11:00:00Z",
                        "points": 180,
                        "num_comments": 44,
                    }
                ]
            }
        raise AssertionError(f"unexpected JSON url: {url}")

    def fake_text(url: str) -> str:
        assert "export.arxiv.org/api/query" in url
        return """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <id>http://arxiv.org/abs/2606.12345v1</id>
            <title>Agent Memory Benchmarks</title>
            <summary>Persistent context and benchmark evals for tool-using agents.</summary>
            <updated>2026-06-30T12:00:00Z</updated>
          </entry>
        </feed>
        """

    output_path = tmp_path / "raw-live.json"

    records = collect_ai_raw_records(
        output_path=output_path,
        query="agent memory eval harness",
        per_source_limit=1,
        fetch_json=fake_json,
        fetch_text=fake_text,
        apify_token="",
    )

    assert output_path.exists()
    assert [record["source_name"] for record in records] == [
        "github-ai-search",
        "hacker-news-ai",
        "arxiv-ai",
    ]
    normalized = normalize_raw_records(output_path)
    assert [record.entity for record in normalized] == [
        "GitHub Trending",
        "Hacker News AI Builders",
        "AI Research Papers",
    ]
    assert normalized[0].engagement["stars"] == 2400


def test_collect_ai_raw_records_x_apify_filters_retweets_and_caps_authors(tmp_path):
    config_path = _write_json(
        tmp_path / "sources.json",
        {
            "sources": [
                {
                    "enabled": True,
                    "type": "x_apify",
                    "name": "x-ai-builders",
                    "twitter_handles": ["simonw", "gregpr07"],
                    "days_back": 2,
                    "max_items": 10,
                    "per_author_cap": 1,
                }
            ]
        },
    )
    calls = []

    def fake_post_json(url: str, payload: dict, token: str) -> list[dict]:
        calls.append((url, payload, token))
        return [
            {
                "id": "tw-1",
                "text": "Agent memory eval harnesses are becoming table stakes.",
                "url": "https://x.example/simonw/status/1",
                "createdAt": "2026-06-30T10:00:00Z",
                "author": {"userName": "simonw"},
                "likeCount": 100,
                "retweetCount": 20,
            },
            {
                "id": "tw-2",
                "text": "Second simonw tweet should be capped.",
                "url": "https://x.example/simonw/status/2",
                "createdAt": "2026-06-30T11:00:00Z",
                "author": {"userName": "simonw"},
                "likeCount": 50,
                "retweetCount": 5,
            },
            {
                "id": "tw-3",
                "text": "RT @someone no original signal",
                "url": "https://x.example/greg/status/3",
                "createdAt": "2026-06-30T12:00:00Z",
                "author": {"userName": "gregpr07"},
                "isRetweet": True,
            },
            {
                "id": "tw-4",
                "text": "Claude Code MCP tools are everywhere this week.",
                "url": "https://x.example/greg/status/4",
                "createdAt": "2026-06-30T13:00:00Z",
                "author": {"userName": "gregpr07"},
                "likeCount": 80,
                "retweetCount": 8,
            },
        ]

    output_path = tmp_path / "x-raw.json"

    records = collect_ai_raw_records(
        output_path=output_path,
        sources_config_path=config_path,
        post_json=fake_post_json,
        apify_token="test-token",
    )

    assert output_path.exists()
    assert len(records) == 2
    assert calls[0][0].endswith("apidojo~tweet-scraper/run-sync-get-dataset-items")
    assert calls[0][1]["twitterHandles"] == ["simonw", "gregpr07"]
    assert calls[0][2] == "test-token"

    normalized = normalize_raw_records(output_path)
    assert [record.source_id for record in normalized] == ["tw-1", "tw-4"]
    assert [record.entity for record in normalized] == ["Builder Thread", "Builder Thread"]
    assert normalized[0].source == "x"
    assert normalized[0].engagement["likes"] == 100
    assert normalized[0].engagement["reposts"] == 20


def test_collect_ai_raw_records_x_apify_skips_without_token(tmp_path):
    config_path = _write_json(
        tmp_path / "sources.json",
        {
            "sources": [
                {
                    "enabled": True,
                    "type": "x_apify",
                    "name": "x-ai-builders",
                    "twitter_handles": ["simonw"],
                }
            ]
        },
    )

    records = collect_ai_raw_records(
        sources_config_path=config_path,
        post_json=lambda *_: pytest.fail("post_json should not run without token"),
        apify_token="",
    )

    assert records == []


def test_collect_ai_raw_records_reddit_uses_arctic_with_pullpush_fallback(tmp_path):
    config_path = _write_json(
        tmp_path / "sources.json",
        {
            "sources": [
                {
                    "enabled": True,
                    "type": "reddit_rss",
                    "name": "reddit-ai-builds",
                    "subreddits": ["ClaudeCode"],
                    "limit": 2,
                    "lookback_days": 35,
                }
            ]
        },
    )
    requested_urls = []

    def fake_json(url: str) -> dict:
        requested_urls.append(url)
        if "arctic-shift.photon-reddit.com/api/posts/search" in url:
            raise RuntimeError("arctic blocked")
        assert "api.pullpush.io/reddit/search/submission" in url
        return {
            "data": [
                {
                    "id": "rd-1",
                    "subreddit": "ClaudeCode",
                    "author": "builder",
                    "title": "MCP eval harness launch",
                    "selftext": "New agent eval harness pattern.",
                    "permalink": "/r/ClaudeCode/comments/rd1/mcp_eval_harness/",
                    "score": 42,
                    "num_comments": 7,
                    "created_utc": 1782900000,
                }
            ]
        }

    records = collect_ai_raw_records(
        sources_config_path=config_path,
        fetch_json=fake_json,
        fetch_text=lambda *_: pytest.fail("reddit collector must not use Reddit RSS"),
    )

    assert len(records) == 1
    assert records[0]["record_key"] == "rd-1"
    assert records[0]["summary"]["subreddit"] == "ClaudeCode"
    assert records[0]["summary"]["score"] == 42
    assert requested_urls[0].startswith("https://arctic-shift.photon-reddit.com/api/posts/search?")
    assert requested_urls[1].startswith("https://api.pullpush.io/reddit/search/submission?")


def test_collect_weekly_workflow_collects_then_writes_newsletter(tmp_path):
    watchlist_path = _write_yaml(
        tmp_path / "ai-watchlist.yaml",
        {
            "name": "AI Builds Radar",
            "theme_keywords": {"eval harnesses": ["eval harness", "benchmark eval"]},
            "entities": [
                {"name": "GitHub Trending", "category": "repos", "sources": {"github": ["trending"]}},
                {"name": "Hacker News AI Builders", "category": "community", "sources": {"hacker-news": ["show-hn"]}},
            ],
        },
    )

    def fake_collector(output_path: Path, query: str, per_source_limit: int) -> list[dict]:
        payload = [
            {
                "source_name": "github-ai-search",
                "record_key": "gh-1",
                "summary": {
                    "repo": "agent-labs/eval-memory",
                    "title": "Agent memory eval harness",
                    "description": "New benchmark evals",
                    "url": "https://github.com/agent-labs/eval-memory",
                },
            },
            {
                "source_name": "hacker-news-ai",
                "record_key": "hn-1",
                "summary": {
                    "title": "Show HN: eval harness for agents",
                    "description": "Regression eval harness for AI builds",
                    "url": "https://news.ycombinator.com/item?id=1",
                },
            },
        ]
        output_path.write_text(json.dumps(payload, indent=2))
        return payload

    report = run_collect_weekly_workflow(
        watchlist_path=watchlist_path,
        output_dir=tmp_path / "out",
        run_date="2026-06-30",
        week="2026-W27",
        query="agent memory eval harness",
        per_source_limit=2,
        collector=fake_collector,
    )

    assert [move.theme for move in report.market_moves] == ["eval harnesses"]
    assert (tmp_path / "out" / "competitive-intel" / "2026-06-30.raw.json").exists()
    assert (tmp_path / "out" / "competitive-intel" / "2026-06-30.md").exists()


def test_main_collect_weekly_subcommand_writes_outputs(tmp_path, monkeypatch):
    watchlist_path = _write_yaml(
        tmp_path / "ai-watchlist.yaml",
        {
            "name": "AI Builds Radar",
            "theme_keywords": {"eval harnesses": ["eval harness"]},
            "entities": [
                {"name": "GitHub Trending", "category": "repos", "sources": {"github": ["trending"]}},
                {"name": "Hacker News AI Builders", "category": "community", "sources": {"hacker-news": ["show-hn"]}},
            ],
        },
    )

    def fake_collect(output_path, query, per_source_limit, sources_config_path=None):
        payload = [
            {
                "source_name": "github-ai-search",
                "record_key": "gh-1",
                "summary": {
                    "repo": "agent-labs/evals",
                    "title": "Agent eval harness",
                    "url": "https://github.com/agent-labs/evals",
                },
            },
            {
                "source_name": "hacker-news-ai",
                "record_key": "hn-1",
                "summary": {
                    "title": "Show HN: eval harness",
                    "url": "https://news.ycombinator.com/item?id=1",
                },
            },
        ]
        Path(output_path).write_text(json.dumps(payload, indent=2))
        return payload

    monkeypatch.setattr("kipi_mcp.competitive_intel.collect_ai_raw_records", fake_collect)

    exit_code = main(
        [
            "collect-weekly",
            "--watchlist",
            str(watchlist_path),
            "--output-dir",
            str(tmp_path / "out"),
            "--run-date",
            "2026-06-30",
            "--week",
            "2026-W27",
            "--query",
            "eval harness",
            "--per-source-limit",
            "2",
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "out" / "competitive-intel" / "2026-06-30.raw.json").exists()
    assert (tmp_path / "out" / "competitive-intel" / "2026-06-30.md").exists()
