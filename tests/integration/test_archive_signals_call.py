"""Archive bottleneck signals in a call transcript (atlas-beliefs ticket 18): a hit carries the
speaker whose words it is.

Seam: the `atlas` CLI enqueues the TradingView catalog (which records the synthetic call
transcript, `tests/fixtures/tradingview/view-syn-view-1001-t.json`) and the `scan_signals` job,
single worker passes run them, and the lead is read through `/api/v1/leads`. TradingView is the
transport-level fake of its MCP server. The transcript's paragraphs carry the speaker labels
production transcripts carry: the company's officers "Name (Title, Firm)", an analyst who repeats
the CEO's words, and "Operator" with no affiliation. The scorer's treatment of an analyst's
sentence against management's is pinned on hand-written sentences in `tests/unit/test_signals.py`.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.serve import Served, serve
from tests.fakes.tradingview import ACCESS_TOKEN, FakeTradingView
from tests.harness import Atlas

CEO = "Alex Example (President and CEO, Lumentum Holdings Inc)"
CONSTRAINT = (
    "In this fictional quarter our indium phosphide laser capacity was the constraint on"
    " shipments of 1.6T transceivers, and we are expanding our indium phosphide wafer fab"
    " capacity in the synthetic plant."
)


@pytest.fixture
def tradingview() -> Iterator[tuple[FakeTradingView, Served]]:
    fake = FakeTradingView()
    with serve(fake.handle) as served:
        yield fake, served
        served.raise_errors()


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, tradingview: tuple[FakeTradingView, Served]
) -> Iterator[Atlas]:
    served = tradingview[1]
    # No Hindsight: nothing is retained, so a worker pass runs the jobs under test alone.
    harness = Atlas(
        database_url,
        tmp_path,
        "",
        tradingview_enabled=True,
        tradingview_mcp_url=f"{served.url}/mcp",
        tradingview_access_token=ACCESS_TOKEN,  # the cluster proxy's way: no token file
        tradingview_token_file=tmp_path / "no-token-file.json",
        tradingview_rate_per_s=1.0,
        signal_scan_lag_seconds=0,
    )
    yield harness
    harness.engine.dispose()


def transcript(atlas: Atlas) -> str:
    """Record the synthetic call transcript through the TradingView catalog; its version ID."""
    payload = json.dumps({"company": "lumentum"})
    catalog_id = atlas.enqueue(
        "jobs", "enqueue", "tradingview_catalog", "--key", "lite", "--payload", payload
    )
    atlas.worker_pass()
    catalog = atlas.get(f"/api/v1/jobs/{catalog_id}")
    assert catalog["status"] == "succeeded", catalog["failures"]
    transcripts = atlas.get(f"/api/v1/jobs/{catalog['artifacts']['transcripts_job_id']}")
    assert transcripts["status"] == "succeeded", transcripts["failures"]
    [version_id] = transcripts["artifacts"]["source_versions"]
    return version_id


def test_a_call_transcripts_sentence_carries_its_speaker(atlas: Atlas) -> None:
    version_id = transcript(atlas)

    job_id = atlas.enqueue("signals", "scan", "--key", "call")
    atlas.worker_pass()
    job: dict[str, Any] = atlas.get(f"/api/v1/jobs/{job_id}")

    # The CEO's sentence: capacity "was the constraint" 1.5, x 1.25 for the company's own
    # officer. The analyst repeating the CEO's words (a longer sentence), the CFO's "backlog is
    # broad" and the operator's welcome are no hits.
    assert job["status"] == "succeeded", job["failures"]
    assert (job["artifacts"]["hits"], job["artifacts"]["stored"]) == (1, 1)
    [lead] = atlas.get("/api/v1/leads", origin="archive_signal")["items"]
    signal = lead["signal"]
    assert (signal["quote"], signal["score"]) == (CONSTRAINT, 1.88)
    assert (signal["speaker"], signal["speaker_kind"]) == (CEO, "management")
    assert signal["families"] == ["capacity"]
    assert signal["factors"] == {"families": 1.5, "speaker": 1.25}
    assert signal["source_version_id"] == version_id
    parsed = atlas.parsed(version_id)
    assert parsed[signal["char_start"] : signal["char_end"]] == CONSTRAINT
