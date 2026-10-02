"""An analyst's words are not the company's statement (pilot-fixes ticket 22).

Seam: the `atlas` CLI enqueues the TradingView catalog (which records the synthetic call
transcript, `tests/fixtures/tradingview/view-syn-view-1001-t.json`) and an `extract_claims` job,
single worker passes run them, and the Claims are read through `/api/v1/claims`. TradingView is
the transport-level fake of its MCP server, Hindsight the recorded fake and LiteLLM the scripted
chat fake: the Investigator's answers are written here, quoting the synthetic transcript. Its
paragraphs carry the speaker labels production transcripts carry: the company's officers
"Name (Title, Lumentum Holdings Inc)", an analyst "Name (... Analyst, Example Securities)" who
repeats the CEO's sentence word for word, and "Operator" with no affiliation.
"""

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from atlas.tradingview import TokenSet, write_token_file
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.serve import Served, serve
from tests.fakes.tradingview import ACCESS_TOKEN, REFRESH_TOKEN, FakeTradingView
from tests.harness import Atlas

CEO = "Alex Example (President and CEO, Lumentum Holdings Inc)"
ANALYST = "Sam Sample (Managing Director and Equity Research Analyst, Example Securities)"
# Said by the CEO, then repeated word for word in the analyst's question.
EXPANSION = "we are expanding our indium phosphide wafer fab capacity in the synthetic plant"
# The end of the CEO's paragraph and the start of the analyst's.
ACROSS = f"in the synthetic plant.\n{ANALYST}: You said that we are expanding"
OPERATOR = "welcome to this synthetic call"


@pytest.fixture
def llm() -> FakeLiteLLM:
    return FakeLiteLLM()


@pytest.fixture
def litellm(llm: FakeLiteLLM) -> Iterator[Served]:
    with serve(llm.handle) as served:
        yield served
        served.raise_errors()


@pytest.fixture
def tradingview() -> Iterator[tuple[FakeTradingView, Served]]:
    fake = FakeTradingView()
    with serve(fake.handle) as served:
        yield fake, served
        served.raise_errors()


@pytest.fixture
def atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    litellm: Served,
    tradingview: tuple[FakeTradingView, Served],
) -> Iterator[Atlas]:
    served = tradingview[1]
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
    harness = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        litellm.url,
        tradingview_enabled=True,
        tradingview_mcp_url=f"{served.url}/mcp",
        tradingview_token_file=token_file,
        tradingview_rate_per_s=1.0,
        investigator_passages_per_call=50,
    )
    harness.apply_template()
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


def quoting(*claims: tuple[dict[str, JsonValue], int]) -> Callable[[dict[str, Any]], JsonValue]:
    """An Investigator answer quoting the passage that holds each quote, at its `n`th
    occurrence there (the same words said twice are two places)."""

    def respond(body: dict[str, Any]) -> JsonValue:
        passages = json.loads(body["messages"][1]["content"])["retrieved_data"]
        answered: list[JsonValue] = []
        for proposed, nth in claims:
            quote = str(proposed["quote"])
            [passage] = [p for p in passages if quote in p["text"]]
            start = -1
            for _ in range(nth + 1):
                start = passage["text"].index(quote, start + 1)
            answered.append(
                proposed
                | {
                    "passage_id": passage["id"],
                    "quote_start": start,
                    "quote_end": start + len(quote),
                }
            )
        return {"claims": answered}

    return respond


def expansion(subject: str, quote: str, object_text: str) -> dict[str, JsonValue]:
    return {
        "subject_company_id": subject,
        "predicate": "expands_capacity_for",
        "object_company_id": None,
        "object_name": None,
        "object_text": object_text,
        "product": None,
        "layer": None,
        "epistemic_type": "company_claim",
        "quote": quote,
    }


def test_only_the_companys_own_people_make_its_statements(atlas: Atlas, llm: FakeLiteLLM) -> None:
    version_id = transcript(atlas)
    lumentum = atlas.company("lumentum")["id"]
    parsed = atlas.parsed(version_id)
    assert parsed.count(EXPANSION) == 2 and parsed.count(ACROSS) == 1
    inp = "indium phosphide wafer fab capacity"
    llm.script_chat(
        ChatReply.answer(
            quoting(
                (expansion(lumentum, EXPANSION, inp), 0),  # the CEO's paragraph
                (expansion(lumentum, EXPANSION, inp), 1),  # the analyst's, the same words
                (expansion(lumentum, ACROSS, inp), 0),  # the end of one, the start of the other
                (expansion(lumentum, OPERATOR, "synthetic call"), 0),  # the operator's
            )
        )
    )

    job_id = atlas.enqueue(
        "jobs",
        "enqueue",
        "extract_claims",
        "--key",
        "speakers",
        "--payload",
        json.dumps({"source_version_ids": [version_id], "question": "indium phosphide capacity"}),
    )
    atlas.worker_pass()

    job = atlas.get(f"/api/v1/jobs/{job_id}")
    assert job["status"] == "succeeded", job["failures"]
    claims = atlas.get("/api/v1/claims", extraction_id=job["artifacts"]["extraction_id"], limit=50)[
        "items"
    ]
    ceo, analyst, across, operator = claims
    assert (ceo["outcome"], ceo["reason_code"]) == ("accepted", None), ceo["reason"]
    assert ceo["speaker"] == CEO
    assert atlas.get(f"/api/v1/claims/{ceo['id']}")["speaker"] == CEO
    assert parsed[ceo["span_start"] : ceo["span_end"]] == EXPANSION
    assert (analyst["outcome"], analyst["reason_code"]) == ("rejected", "analyst_speaking")
    assert ANALYST in analyst["reason"]
    assert analyst["speaker"] is None and analyst["assertion_id"] is None
    assert (across["outcome"], across["reason_code"]) == ("rejected", "speaker_mixed")
    assert CEO in across["reason"] and ANALYST in across["reason"]
    assert (operator["outcome"], operator["reason_code"]) == ("rejected", "speaker_unknown")
    assert job["artifacts"]["accepted"] == 1
