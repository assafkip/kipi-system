from __future__ import annotations

import pytest
import httpx

from kipi_mcp.executors import ExecutorResult
from kipi_mcp.executors.http_executor import execute


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides) -> dict:
    base = dict(
        url="https://api.example.com/data",
        verb="GET",
        headers={},
        body_template=None,
        records_path=[],
        pagination=None,
        is_rss=False,
        is_ga4=False,
    )
    base.update(overrides)
    return base


def _mock_transport(handler):
    """Return an httpx.MockTransport wrapping *handler*."""
    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_simple_get(monkeypatch):
    payload = [{"id": 1}, {"id": 2}]

    def handler(request: httpx.Request):
        assert request.method == "GET"
        return httpx.Response(200, json=payload)

    transport = _mock_transport(handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: httpx.AsyncClient(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}))

    # Simpler: just patch at module level
    monkeypatch.undo()  # undo the above

    import kipi_mcp.executors.http_executor as mod

    async def _patched_execute(config, cursor=None):
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await client.get(config["url"])
            data = resp.json()
            records = data if isinstance(data, list) else [data]
            return ExecutorResult(records=records)

    # Actually, let's just inject the transport properly.
    # We'll monkeypatch httpx.AsyncClient to always use our transport.
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        kwargs.pop("timeout", None)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    result = await execute(_make_config())
    assert result.error is None
    assert len(result.records) == 2
    assert result.records[0]["id"] == 1


@pytest.mark.asyncio
async def test_post_with_body(monkeypatch):
    def handler(request: httpx.Request):
        assert request.method == "POST"
        assert request.headers.get("content-type") == "application/json"
        import json
        body = json.loads(request.content)
        assert body == {"query": "test"}
        return httpx.Response(200, json=[{"result": "ok"}])

    transport = _mock_transport(handler)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        kwargs.pop("timeout", None)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    config = _make_config(
        verb="POST",
        headers={"Content-Type": "application/json"},
        body_template={"query": "test"},
    )
    result = await execute(config)
    assert result.error is None
    assert result.records == [{"result": "ok"}]


@pytest.mark.asyncio
async def test_pagination_cursor(monkeypatch):
    call_count = 0

    def handler(request: httpx.Request):
        nonlocal call_count
        call_count += 1
        url = str(request.url)
        if "cursor=" not in url:
            return httpx.Response(200, json={
                "items": [{"id": 1}],
                "next_cursor": "abc123",
                "has_more": True,
            })
        else:
            assert "cursor=abc123" in url
            return httpx.Response(200, json={
                "items": [{"id": 2}],
                "next_cursor": None,
                "has_more": False,
            })

    transport = _mock_transport(handler)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        kwargs.pop("timeout", None)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    config = _make_config(
        records_path=["items"],
        pagination={
            "type": "cursor",
            "cursor_field": "next_cursor",
            "has_more_field": "has_more",
            "cursor_param": "cursor",
        },
    )
    result = await execute(config)
    assert result.error is None
    assert len(result.records) == 2
    assert call_count == 2


@pytest.mark.asyncio
async def test_records_path_extraction(monkeypatch):
    def handler(request: httpx.Request):
        return httpx.Response(200, json={
            "data": {"items": [{"x": 1}, {"x": 2}, {"x": 3}]}
        })

    transport = _mock_transport(handler)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        kwargs.pop("timeout", None)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    config = _make_config(records_path=["data", "items"])
    result = await execute(config)
    assert result.error is None
    assert len(result.records) == 3
    assert result.records[0] == {"x": 1}


@pytest.mark.asyncio
async def test_rss_feed_parsing(monkeypatch):
    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Test Feed</title>
        <item>
          <title>Article 1</title>
          <link>https://example.com/1</link>
        </item>
        <item>
          <title>Article 2</title>
          <link>https://example.com/2</link>
        </item>
      </channel>
    </rss>"""

    def handler(request: httpx.Request):
        return httpx.Response(200, text=rss_xml, headers={"content-type": "application/xml"})

    transport = _mock_transport(handler)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        kwargs.pop("timeout", None)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    config = _make_config(is_rss=True)
    result = await execute(config)
    assert result.error is None
    assert len(result.records) == 2
    assert result.records[0]["title"] == "Article 1"
    assert result.records[1]["link"] == "https://example.com/2"


@pytest.mark.asyncio
async def test_ga4_client_call(monkeypatch):
    from unittest.mock import MagicMock, patch
    import asyncio

    mock_client_cls = MagicMock()
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client

    mock_row = MagicMock()
    mock_row.dimension_values = [MagicMock(value="page1")]
    mock_row.metric_values = [MagicMock(value="100")]

    mock_response = MagicMock()
    mock_response.rows = [mock_row]
    mock_response.dimension_headers = [MagicMock(name="pagePath")]
    mock_response.metric_headers = [MagicMock(name="sessions")]
    mock_client.run_report.return_value = mock_response

    with patch.dict("sys.modules", {
        "google.analytics.data_v1beta": MagicMock(BetaAnalyticsDataClient=mock_client_cls),
        "google.analytics.data_v1beta.types": MagicMock(),
        "google.analytics": MagicMock(),
        "google": MagicMock(),
    }):
        monkeypatch.setattr(
            "kipi_mcp.executors.http_executor._get_ga4_client",
            lambda: mock_client,
        )

        config = _make_config(
            is_ga4=True,
            url="properties/12345",
            body_template={
                "dimensions": [{"name": "pagePath"}],
                "metrics": [{"name": "sessions"}],
                "date_ranges": [{"start_date": "7daysAgo", "end_date": "today"}],
            },
        )
        result = await execute(config)

    assert result.error is None
    assert len(result.records) == 1
    mock_client.run_report.assert_called_once()


@pytest.mark.asyncio
async def test_retry_on_transient_error(monkeypatch):
    call_count = 0

    def handler(request: httpx.Request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json=[{"ok": True}])

    transport = _mock_transport(handler)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        kwargs.pop("timeout", None)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    result = await execute(_make_config())
    assert result.error is None
    assert len(result.records) == 1
    assert call_count == 2


@pytest.mark.asyncio
async def test_auth_header_injection(monkeypatch):
    def handler(request: httpx.Request):
        assert request.headers.get("authorization") == "Bearer secret-token"
        return httpx.Response(200, json=[{"authed": True}])

    transport = _mock_transport(handler)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        kwargs.pop("timeout", None)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    config = _make_config(headers={"Authorization": "Bearer secret-token"})
    result = await execute(config)
    assert result.error is None
    assert result.records[0]["authed"] is True


@pytest.mark.asyncio
async def test_timeout_handling(monkeypatch):
    def handler(request: httpx.Request):
        raise httpx.TimeoutException("timed out")

    transport = _mock_transport(handler)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        kwargs.pop("timeout", None)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    result = await execute(_make_config())
    assert result.error is not None
    assert "timeout" in result.error.lower() or "timed out" in result.error.lower()
    assert result.records == []


@pytest.mark.asyncio
async def test_empty_response(monkeypatch):
    def handler(request: httpx.Request):
        return httpx.Response(200, json=[])

    transport = _mock_transport(handler)
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        kwargs.pop("timeout", None)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    result = await execute(_make_config())
    assert result.error is None
    assert result.records == []
    assert result.cursor_after is None
