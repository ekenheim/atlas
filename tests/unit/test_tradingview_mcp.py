"""The TradingView MCP client at its transport boundary (ticket 31): the streamable-HTTP
handshake, JSON and SSE answers, sessions, the owner's OAuth token and its refresh, errors,
the per-job call bound and pacing.

TradingView is the transport-level fake (`tests/fakes/tradingview.py`) over the synthetic
fixtures in `tests/fixtures/tradingview/`. Nothing live is called.
"""

import json
import logging
import math
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from atlas.parsing import ParsedText, parse
from atlas.settings import Settings
from atlas.sources import TokenBucket
from atlas.tradingview import (
    CallBoundReached,
    McpClient,
    McpToolError,
    TokenSet,
    TokenStore,
    TradingViewAuthError,
    TradingViewClient,
    TradingViewUnavailable,
    write_token_file,
)
from tests.fakes.tradingview import ACCESS_TOKEN, REFRESH_TOKEN, FakeTradingView, fixture_text
from tests.harness import make_settings

MCP_URL = "https://mcp.tradingview.test/mcp"
TOKEN_URL = "https://mcp.tradingview.test/auth/token"
NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)


def settings_with_file(tmp_path: Path, **token: Any) -> Settings:
    path = tmp_path / "tokens" / "tradingview.json"
    values: dict[str, Any] = {
        "access_token": ACCESS_TOKEN,
        "refresh_token": REFRESH_TOKEN,
        "expires_at": NOW + timedelta(hours=1),
        "token_endpoint": TOKEN_URL,
        "client_id": "fake-registered-client",
        "resource": MCP_URL,
    }
    write_token_file(path, TokenSet(**(values | token)))
    return make_settings(tmp_path, tradingview_mcp_url=MCP_URL, tradingview_token_file=path)


def mcp(settings: Settings, fake: FakeTradingView, rate: float = math.inf) -> McpClient:
    tokens = TokenStore(settings, transport=fake.transport, clock=lambda: NOW)
    return McpClient(
        MCP_URL,
        tokens,
        limiter=TokenBucket(rate_per_s=rate),
        timeout=5,
        user_agent="AtlasResearch",
        transport=fake.transport,
    )


def tools(
    client: McpClient, max_calls: int = 10
) -> tuple[TradingViewClient, list[tuple[str, str | None]]]:
    recorded: list[tuple[str, str | None]] = []

    def record(tool: str, error: str | None) -> None:
        recorded.append((tool, error))

    return TradingViewClient(client, max_calls=max_calls, on_call=record), recorded


def documents(client: TradingViewClient) -> Any:
    return client.documents("NASDAQ:LITE", start=NOW - timedelta(days=730), end=NOW, limit=100)


def test_a_session_initializes_then_calls_the_tool_with_its_session_and_version(
    tmp_path: Path,
) -> None:
    fake = FakeTradingView()
    with mcp(settings_with_file(tmp_path), fake) as session:
        listed = documents(tools(session)[0])

    initialize, initialized, call, delete = fake.calls
    assert json.loads(initialize.content)["method"] == "initialize"
    assert json.loads(initialize.content)["params"]["protocolVersion"] == "2025-06-18"
    assert "mcp-session-id" not in initialize.headers
    assert json.loads(initialized.content) == {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }
    for request in (initialized, call, delete):
        assert request.headers["mcp-session-id"] == "fake-session-1"
        assert request.headers["mcp-protocol-version"] == "2025-06-18"
    for request in fake.calls:
        assert request.headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
        assert request.headers["accept"] == "application/json, text/event-stream"
        assert request.headers["user-agent"] == "AtlasResearch"
    assert delete.method == "DELETE"
    assert fake.tool_calls == [
        (
            "mcp-tv-get-documents",
            {
                "symbol": "NASDAQ:LITE",
                "start_date": "2024-09-30T12:00:00Z",
                "end_date": "2026-09-30T12:00:00Z",
                "limit": 100,
            },
        )
    ]
    assert [item.id for item in listed.items] == ["syn-doc-1001", "syn-doc-1002", "syn-doc-0901"]
    call_1001 = listed.items[0]
    assert (call_1001.category and call_1001.category.title) == "Earnings call"
    assert call_1001.fiscal_year == "2026"
    assert call_1001.reported_at == datetime(2026, 8, 11, 20, 30, tzinfo=UTC)
    assert [v.id for v in call_1001.transcript_views()] == ["syn-view-1001-t"]
    assert (listed.items[1].form and listed.items[1].form.id) == "10-K"


def test_answers_on_an_event_stream_are_read_past_other_messages(tmp_path: Path) -> None:
    fake = FakeTradingView(sse=True)
    with mcp(settings_with_file(tmp_path), fake) as session:
        text, view = tools(session)[0].document_view("syn-view-1001-t")

    assert text == fixture_text("view-syn-view-1001-t")  # exactly as received
    assert view.title == "SYNTHETIC Q4 FY2026 earnings call transcript"
    assert view.published_at == datetime(2026, 8, 11, 23, tzinfo=UTC)


def test_news_headlines_keep_publisher_link_story_and_related_symbols(tmp_path: Path) -> None:
    fake = FakeTradingView()
    with mcp(settings_with_file(tmp_path), fake) as session:
        first, second = tools(session)[0].news("NASDAQ:LITE", lang="en", limit=50)

    assert fake.tool_calls[0] == (
        "mcp-tv-get-news",
        {"symbol": "NASDAQ:LITE", "lang": "en", "limit": 50, "offset": 0},
    )
    assert (
        first.story_path == "/news/example-wire:syn1:0-synthetic-example-laser-maker-adds-capacity/"
    )
    assert (first.provider and first.provider.name) == "Example Newswire"
    assert [s.symbol for s in first.related_symbols] == ["NASDAQ:LITE", "NASDAQ:AAOI"]
    assert first.published_at == datetime(2026, 8, 12, 13, tzinfo=UTC)
    assert second.story_path is None
    assert second.link == "https://daily.example.test/markets/optical-transceivers-note"


def test_a_401_refreshes_the_token_once_and_the_file_keeps_the_rotated_tokens(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    fake = FakeTradingView(access_tokens=set())  # the stored access token was revoked
    settings = settings_with_file(tmp_path)
    with mcp(settings, fake) as session:
        documents(tools(session)[0])

    [refresh] = fake.token_requests
    assert refresh == {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": "fake-registered-client",
        "resource": MCP_URL,
    }
    stored = json.loads(settings.tradingview_token_file.read_text())
    assert (stored["access_token"], stored["refresh_token"]) == (
        "fake-access-token-2",
        "fake-refresh-token-2",
    )
    assert stored["expires_at"] == (NOW + timedelta(hours=1)).isoformat()
    assert stat.S_IMODE(settings.tradingview_token_file.stat().st_mode) == 0o600
    assert fake.tool_calls  # the retried request went through
    logged = caplog.text
    for secret in (ACCESS_TOKEN, REFRESH_TOKEN, "fake-access-token-2", "fake-refresh-token-2"):
        assert secret not in logged


def test_an_expired_token_is_refreshed_before_the_first_request(tmp_path: Path) -> None:
    fake = FakeTradingView()
    settings = settings_with_file(tmp_path, expires_at=NOW - timedelta(minutes=5))
    with mcp(settings, fake) as session:
        documents(tools(session)[0])

    assert [r["grant_type"] for r in fake.token_requests] == ["refresh_token"]
    assert fake.calls[0].url.path == "/auth/token"
    assert fake.mcp_requests()[0].headers["authorization"] == "Bearer fake-access-token-2"


def test_a_refused_token_that_cannot_be_refreshed_is_a_clear_error(tmp_path: Path) -> None:
    fake = FakeTradingView(access_tokens=set())
    settings = make_settings(
        tmp_path,
        tradingview_mcp_url=MCP_URL,
        tradingview_token_file=tmp_path / "absent.json",
        tradingview_access_token="an-expired-secret-token",
    )
    with pytest.raises(TradingViewAuthError) as refused, mcp(settings, fake) as session:
        documents(tools(session)[0])

    assert "HTTP 401" in str(refused.value)
    assert "atlas tradingview login" in str(refused.value)
    assert "an-expired-secret-token" not in str(refused.value)


def test_a_rejected_refresh_token_asks_for_a_new_login(tmp_path: Path) -> None:
    fake = FakeTradingView(access_tokens=set(), refresh_tokens=set())
    with pytest.raises(TradingViewAuthError) as refused:
        with mcp(settings_with_file(tmp_path), fake) as session:
            documents(tools(session)[0])

    assert "invalid_grant" in str(refused.value)
    assert "atlas tradingview login" in str(refused.value)


def test_no_token_at_all_is_a_clear_error_and_nothing_is_sent(tmp_path: Path) -> None:
    fake = FakeTradingView()
    settings = make_settings(
        tmp_path, tradingview_mcp_url=MCP_URL, tradingview_token_file=tmp_path / "absent.json"
    )
    with pytest.raises(TradingViewAuthError, match="no TradingView token"):
        with mcp(settings, fake) as session:
            documents(tools(session)[0])

    assert fake.calls == []


def test_an_ended_session_is_reopened_and_the_request_retried(tmp_path: Path) -> None:
    fake = FakeTradingView()
    with mcp(settings_with_file(tmp_path), fake) as session:
        client = tools(session)[0]
        documents(client)
        fake.ended_sessions.add("fake-session-1")
        client.news("NASDAQ:LITE", lang="en", limit=5)

    assert fake.sessions == 2
    assert [name for name, _ in fake.tool_calls] == ["mcp-tv-get-documents", "mcp-tv-get-news"]
    assert fake.calls[-1].headers["mcp-session-id"] == "fake-session-2"


def test_a_tool_error_and_an_outage_are_distinguished(tmp_path: Path) -> None:
    settings = settings_with_file(tmp_path)
    with mcp(settings, FakeTradingView()) as session:
        with pytest.raises(McpToolError, match="not retrievable"):
            tools(session)[0].document_view("syn-view-2001-t")
    with mcp(settings, FakeTradingView(unavailable=True)) as session:
        with pytest.raises(TradingViewUnavailable, match="503"):
            documents(tools(session)[0])


def test_each_call_is_recorded_and_a_job_makes_at_most_its_bound(tmp_path: Path) -> None:
    fake = FakeTradingView()
    with mcp(settings_with_file(tmp_path), fake) as session:
        client, recorded = tools(session, max_calls=2)
        documents(client)
        with pytest.raises(McpToolError):
            client.document_view("syn-view-2001-t")
        with pytest.raises(CallBoundReached):
            client.news("NASDAQ:LITE", lang="en", limit=5)

    assert [name for name, _ in fake.tool_calls] == [
        "mcp-tv-get-documents",
        "mcp-tv-get-document-view",
    ]
    assert recorded[0] == ("mcp-tv-get-documents", None)
    assert recorded[1][0] == "mcp-tv-get-document-view"
    assert "not retrievable" in (recorded[1][1] or "")
    assert client.calls == 2


def test_requests_are_paced_at_most_one_a_second(tmp_path: Path) -> None:
    fake = FakeTradingView()
    with mcp(settings_with_file(tmp_path), fake, rate=1.0) as session:
        documents(tools(session)[0])

    gaps = [later - earlier for earlier, later in zip(fake.times, fake.times[1:], strict=False)]
    assert len(gaps) == 3  # initialize, initialized, the tool call, DELETE
    assert min(gaps) >= 0.95


def test_a_transcript_view_parses_to_speaker_lines() -> None:
    raw = fixture_text("view-syn-view-1001-t").encode()

    parsed = parse(raw, "application/x-tradingview-transcript+json")

    assert isinstance(parsed, ParsedText)
    assert parsed.parser_version == "tradingview-transcript-v1"
    assert parsed.language == "en"
    assert parsed.text == (
        "Operator: Good afternoon and welcome to this synthetic call. It is a hand-written test"
        " fixture and not the record of a real call.\n"
        "Chief Executive Officer: Thank you. In this fictional quarter our indium phosphide laser"
        " capacity was the constraint on shipments of 1.6T transceivers, and we expect the new"
        " line to be qualified by the end of the year.\n"
        "Analyst: How much of the demand comes from\n"
        "the largest customer?\n"
        "Chief Financial Officer: We do not break that out, but the backlog is broad and it is"
        " spread across several customers.\n"
    )
    assert parse(raw, "application/x-tradingview-transcript+json") == parsed  # deterministic
