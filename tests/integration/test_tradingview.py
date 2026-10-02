"""TradingView as an owner-override source (ticket 31; off by default): the catalog, the
transcripts and the news leads, the per-job bound and the `tradingview` budget.

Seams: the `atlas` CLI enqueues, single worker passes run the jobs (the retains against the
served Hindsight fake), and everything is observed through `/api/v1` and the requests the
TradingView fake received. TradingView is the transport-level fake of its MCP server
(`tests/fakes/tradingview.py`, served on localhost) over synthetic fixtures; nothing live is
called.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry
from atlas.tradingview import TokenSet, write_token_file
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served, serve
from tests.fakes.tradingview import ACCESS_TOKEN, REFRESH_TOKEN, FakeTradingView
from tests.harness import Atlas

OVERRIDE = (
    "TradingView terms (display-only) overridden by the owner for private non-commercial use"
    " (2026-09-30)"
)
TRANSCRIPT_URL = "https://mcp.tradingview.com/documents/syn-doc-1001/views/syn-view-1001-t"
STORY_URL = (
    "https://www.tradingview.com/news/example-wire:syn1:0-synthetic-example-laser-maker-adds"
    "-capacity/"
)
LINK_ONLY_URL = "https://daily.example.test/markets/optical-transceivers-note"


@pytest.fixture
def tradingview() -> Iterator[tuple[FakeTradingView, Served]]:
    fake = FakeTradingView()
    with serve(fake.handle) as served:
        yield fake, served
        served.raise_errors()


def enabled(served: Served, tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    token_file = tmp_path / "tradingview-token.json"
    write_token_file(
        token_file,
        TokenSet(
            access_token=ACCESS_TOKEN,
            refresh_token=REFRESH_TOKEN,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            token_endpoint=f"{served.url}/auth/token",
            client_id="fake-registered-client",
            resource=f"{served.url}/mcp",
        ),
    )
    return {
        "tradingview_enabled": True,
        "tradingview_mcp_url": f"{served.url}/mcp",
        "tradingview_token_file": token_file,
        "tradingview_rate_per_s": 1.0,
    } | overrides


@pytest.fixture
def atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    tradingview: tuple[FakeTradingView, Served],
) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path, hindsight[1].url, **enabled(tradingview[1], tmp_path))
    harness.apply_template()
    yield harness
    harness.engine.dispose()


def enqueue(atlas: Atlas, kind: str, key: str, company: str = "lumentum") -> str:
    payload = json.dumps({"company": company})
    return atlas.enqueue("jobs", "enqueue", kind, "--key", key, "--payload", payload)


def paced_pass(atlas: Atlas) -> int:
    settings = atlas.settings()
    queue = JobQueue(atlas.engine, pacing=Pacing.from_settings(settings))
    return Worker(queue, builtin_registry(settings)).run_once()


def test_off_by_default_nothing_calls_tradingview(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    tradingview: tuple[FakeTradingView, Served],
) -> None:
    atlas = Atlas(database_url, tmp_path, hindsight[1].url)
    job_id = enqueue(atlas, "tradingview_catalog", "off")

    atlas.worker_pass()

    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert job["status"] != "succeeded"
    assert "ATLAS_TRADINGVIEW_ENABLED=false" in job["failures"][0]["error"]
    assert tradingview[0].calls == []
    atlas.engine.dispose()


def test_the_catalog_the_transcripts_and_the_news_leads(
    atlas: Atlas, tradingview: tuple[FakeTradingView, Served]
) -> None:
    fake = tradingview[0]
    catalog_id = enqueue(atlas, "tradingview_catalog", "lite")

    atlas.worker_pass()  # the catalog, then the transcripts it enqueued, then the retain

    catalog = atlas.get(f"/api/v1/jobs/{catalog_id}")
    assert catalog["status"] == "succeeded", catalog["failures"]
    artifacts = catalog["artifacts"]
    assert artifacts["documents"] == {"listed": 3, "new": 3}
    assert artifacts["news"] == {"listed": 2, "new_leads": 2}
    assert (artifacts["transcripts_pending"], artifacts["tool_calls"]) == (1, 2)
    transcripts = atlas.get(f"/api/v1/jobs/{artifacts['transcripts_job_id']}")
    assert transcripts["status"] == "succeeded", transcripts["failures"]
    assert [name for name, _ in fake.tool_calls] == [
        "mcp-tv-get-documents",
        "mcp-tv-get-news",
        "mcp-tv-get-document-view",
    ]
    assert fake.tool_calls[2][1] == {"view_id": "syn-view-1001-t"}

    # The catalog: metadata only, every entry marked with the override.
    company_id = atlas.company("lumentum")["id"]
    entries = atlas.get("/api/v1/tradingview/catalog", company_id=company_id)
    assert entries["total"] == 3
    first = entries["items"][0]
    assert {k: first[k] for k in ("document_id", "category", "fiscal_period", "fiscal_year")} == {
        "document_id": "syn-doc-1002",
        "category": "Annual report",
        "fiscal_period": None,
        "fiscal_year": "2026",
    }
    assert (first["form"], first["upstream_provider"]) == ("10-K", "Quartr")
    assert first["reported_at"] == "2026-08-20T21:05:00Z"
    assert all(entry["owner_override"] == OVERRIDE for entry in entries["items"])
    with_transcript = atlas.get(
        "/api/v1/tradingview/catalog", company_id=company_id, has_transcript=True
    )
    assert [e["document_id"] for e in with_transcript["items"]] == ["syn-doc-1001", "syn-doc-0901"]
    views = {v["id"]: v for v in with_transcript["items"][0]["views"]}
    assert views["syn-view-1001-s"]["source_version_id"] is None  # summaries are never stored
    version_id = views["syn-view-1001-t"]["source_version_id"]
    assert version_id == transcripts["artifacts"]["source_versions"][0]
    # The 2019 call is outside the lookback: never fetched.
    assert with_transcript["items"][1]["views"][0]["source_version_id"] is None

    # The transcript: a Tier B Source Version, available at the event's reported time.
    version = atlas.get(f"/api/v1/source-versions/{version_id}")
    document = version["source_document"]
    assert {
        k: document[k]
        for k in ("provider", "canonical_url", "source_type", "source_tier", "publisher")
    } == {
        "provider": "tradingview",
        "canonical_url": TRANSCRIPT_URL,
        "source_type": "transcript",
        "source_tier": "B",
        "publisher": "Quartr via TradingView",
    }
    assert document["title"] == "SYNTHETIC Q4 FY2026 earnings call transcript"
    assert (version["available_at"], version["available_at_basis"]) == (
        "2026-08-11T20:30:00Z",
        "publisher_timestamp",
    )
    assert (version["media_type"], version["parser_version"], version["language"]) == (
        "application/x-tradingview-transcript+json",
        "tradingview-transcript-v1",
        "en",
    )
    assert version["metadata"]["owner_override"] == OVERRIDE
    assert version["metadata"]["tradingview"]["upstream_provider"] == "Quartr"
    assert version["metadata"]["tradingview"]["view_published_at"] == "2026-08-11T23:00:00Z"
    [fetch] = version["fetches"]
    assert fetch["owner_override"] == OVERRIDE
    parsed = atlas.parsed(version_id)
    assert parsed.startswith("Operator: Good afternoon and welcome to this synthetic call.")
    assert "\nAlex Example (President and CEO, Lumentum Holdings Inc): Thank you." in parsed
    assert len(transcripts["artifacts"]["retain_jobs"]) == 1
    retain = atlas.get(f"/api/v1/jobs/{transcripts['artifacts']['retain_jobs'][0]}")
    assert retain["status"] == "succeeded", retain["failures"]

    # The news: Tier C leads, metadata only, in the company's theme.
    leads = atlas.get("/api/v1/leads", theme="photonics")["items"]
    by_url = {lead["url"]: lead for lead in leads}
    assert set(by_url) == {STORY_URL, LINK_ONLY_URL}
    story = by_url[STORY_URL]
    assert {k: story[k] for k in ("tier", "origin", "snippet", "query", "theme", "engines")} == {
        "tier": "C",
        "origin": "tradingview_news",
        "snippet": "",
        "query": None,
        "theme": "photonics",
        "engines": ["tradingview"],
    }
    assert story["title"] == "SYNTHETIC: Example laser maker adds indium phosphide capacity"
    assert story["headline"] == {
        "headline_id": "syn-news-1",
        "company_id": company_id,
        "symbol": "NASDAQ:LITE",
        "publisher": "Example Newswire",
        "publisher_url": "https://newswire.example.test/2026/08/12/example-laser-capacity",
        "published_at": "2026-08-12T13:00:00Z",
        "related_symbols": ["NASDAQ:LITE", "NASDAQ:AAOI"],
        "owner_override": OVERRIDE,
    }
    assert by_url[LINK_ONLY_URL]["headline"]["publisher_url"] is None


def test_a_rerun_adds_nothing_new_and_fetches_no_transcript_again(
    atlas: Atlas, tradingview: tuple[FakeTradingView, Served]
) -> None:
    enqueue(atlas, "tradingview_catalog", "first")
    atlas.worker_pass()
    again = enqueue(atlas, "tradingview_catalog", "second")

    atlas.worker_pass()

    artifacts = atlas.get(f"/api/v1/jobs/{again}")["artifacts"]
    assert artifacts["documents"] == {"listed": 3, "new": 0}
    assert artifacts["news"] == {"listed": 2, "new_leads": 0}
    assert artifacts["transcripts_pending"] == 0
    assert "transcripts_job_id" not in artifacts
    views = [a for name, a in tradingview[0].tool_calls if name == "mcp-tv-get-document-view"]
    assert len(views) == 1
    assert atlas.get("/api/v1/tradingview/catalog")["total"] == 3


def test_a_job_makes_at_most_its_bound_of_calls(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    tradingview: tuple[FakeTradingView, Served],
) -> None:
    atlas = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        **enabled(tradingview[1], tmp_path, tradingview_max_calls_per_job=1),
    )
    catalog_id = enqueue(atlas, "tradingview_catalog", "bounded")

    atlas.worker_pass()

    artifacts = atlas.get(f"/api/v1/jobs/{catalog_id}")["artifacts"]
    assert (artifacts["tool_calls"], artifacts["bounded"]) == (1, True)
    assert artifacts["news"] == {"listed": 0, "new_leads": 0}  # news wasn't reached
    assert [name for name, _ in tradingview[0].tool_calls] == [
        "mcp-tv-get-documents",
        "mcp-tv-get-document-view",  # the transcripts job's own single call
    ]
    atlas.engine.dispose()


def test_tool_calls_count_against_the_tradingview_budget(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    tradingview: tuple[FakeTradingView, Served],
) -> None:
    atlas = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        **enabled(tradingview[1], tmp_path, tradingview_budget_requests=2),
    )
    catalog_id = enqueue(atlas, "tradingview_catalog", "budget")

    paced_pass(atlas)

    transcripts_id = atlas.get(f"/api/v1/jobs/{catalog_id}")["artifacts"]["transcripts_job_id"]
    assert atlas.get(f"/api/v1/jobs/{transcripts_id}")["status"] == "queued"  # held
    queue = atlas.get("/api/v1/queue")
    (budget,) = [b for b in queue["budgets"] if b["provider"] == "tradingview"]
    assert {k: budget[k] for k in ("unit", "used", "budget", "interactive_held", "kinds")} == {
        "unit": "requests",
        "used": 2,
        "budget": 2,
        "interactive_held": True,
        "kinds": ["tradingview_catalog", "tradingview_transcripts"],
    }
    (pending,) = [p for p in queue["pending"] if p["kind"] == "tradingview_transcripts"]
    assert pending["budget_held"] == 1
    assert len(tradingview[0].tool_calls) == 2
    atlas.engine.dispose()


def test_a_view_that_is_not_retrievable_fails_the_attempt_and_is_listed(
    atlas: Atlas, tradingview: tuple[FakeTradingView, Served]
) -> None:
    catalog_id = enqueue(atlas, "tradingview_catalog", "innolight", company="innolight")

    atlas.worker_pass()

    catalog = atlas.get(f"/api/v1/jobs/{catalog_id}")
    assert catalog["status"] == "succeeded", catalog["failures"]
    transcripts = atlas.get(f"/api/v1/jobs/{catalog['artifacts']['transcripts_job_id']}")
    assert transcripts["status"] != "succeeded"
    assert (
        "1 of 1 transcript views not fetched"
        " (syn-view-2001-t: mcp-tv-get-document-view: view not retrievable)"
    ) in transcripts["failures"][0]["error"]
