"""The EDGAR full-text search client (pilot fix 12): the request it sends (the phrase quoted,
the forms, the date range, SEC's User-Agent) and how it reads the answer, at the transport
seam with the fake over the recorded fixture (`tests/fixtures/edgar-fts/`). Nothing live."""

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas.discovery.edgar_fts import (
    FORMS,
    EdgarFullTextSearch,
    FilingSearchFailed,
    filing_phrases,
    filing_query,
)
from atlas.roles.scout import SCOUT
from atlas.roles.skeptic import SKEPTIC_PLAN
from atlas.sources.sec_http import TokenBucket
from tests.fakes.edgar_fts import FakeEdgarFullTextSearch, FilingReply
from tests.harness import make_settings

UA = "Atlas Research ops@example.com"
INP = '"InP substrates"'
START, END = date(2025, 6, 1), date(2026, 9, 30)


def client(fake: FakeEdgarFullTextSearch, **options: object) -> EdgarFullTextSearch:
    return EdgarFullTextSearch(
        UA,
        transport=fake.transport,
        limiter=TokenBucket(rate_per_s=1000),
        backoff_base_s=0.0,
        **options,  # pyright: ignore[reportArgumentType]
    )


def test_a_search_quotes_the_phrase_and_names_the_forms_the_dates_and_sec_s_user_agent() -> None:
    fake = FakeEdgarFullTextSearch().script(INP, FilingReply.of("inp-substrates-10k"))

    client(fake).search(["InP substrates"], start=START, end=END)

    [call] = fake.calls
    assert (call.method, call.url.host, call.url.path) == (
        "GET",
        "efts.sec.gov",
        "/LATEST/search-index",
    )
    assert fake.searches() == [
        {
            "q": '"InP substrates"',
            "forms": "10-K,10-Q,8-K,20-F,6-K,40-F",
            "dateRange": "custom",
            "startdt": "2025-06-01",
            "enddt": "2026-09-30",
        }
    ]
    assert fake.user_agents() == [UA]


def test_several_phrases_are_each_quoted() -> None:
    assert filing_query(["sole source", "InP substrates"]) == '"sole source" "InP substrates"'
    assert filing_phrases('"sole source"  and "InP  substrates"') == [
        "sole source",
        "InP substrates",
    ]
    assert filing_phrases("  InP   substrates ") == ["InP substrates"]
    assert filing_phrases('"') == []
    assert filing_phrases("") == []
    assert filing_phrases(None) == []
    with pytest.raises(ValueError, match="at least one phrase"):
        filing_query([])


def test_the_recorded_answer_becomes_filing_hits_with_archive_urls() -> None:
    fake = FakeEdgarFullTextSearch().script(INP, FilingReply.of("inp-substrates-10k"))

    found = client(fake).search(["InP substrates"], start=START, end=END)

    assert (found.query, found.total) == (INP, 4)
    assert [
        (h.position, h.cik, h.filer, h.ticker, h.form, h.file_date.isoformat(), h.accession)
        for h in found.hits
    ] == [
        (1, "0001051627", "AXT INC", "AXTI", "10-K", "2026-03-17", "0001437749-26-008612"),
        (2, "0001828805", "Aeluma, Inc.", "ALMU", "10-K", "2026-09-16", "0001213900-26-100584"),
        (3, "0001828805", "Aeluma, Inc.", "ALMU", "10-K", "2025-09-09", "0001213900-25-086227"),
        (4, "0000820318", "COHERENT CORP.", "COHR", "10-K", "2026-08-14", "0000820318-26-000020"),
    ]
    axt, _, _, coherent = found.hits
    assert axt.url == (
        "https://www.sec.gov/Archives/edgar/data/1051627/000143774926008612/axti20251231_10k.htm"
    )
    assert axt.document == "axti20251231_10k.htm"
    assert axt.period_ending == date(2025, 12, 31)
    assert axt.title == "AXT INC 10-K filed 2026-03-17"
    # The same URL the EDGAR adapter gives Coherent's ingested 10-K.
    assert coherent.url == (
        "https://www.sec.gov/Archives/edgar/data/820318/000082031826000020/iivi-20260630.htm"
    )


def test_at_most_max_hits_are_kept() -> None:
    fake = FakeEdgarFullTextSearch().script(INP, FilingReply.of("inp-substrates-10k"))

    found = client(fake, max_hits=2).search(["InP substrates"], start=START, end=END)

    assert found.total == 4
    assert [hit.filer for hit in found.hits] == ["AXT INC", "Aeluma, Inc."]


def test_no_hits_is_an_empty_answer_not_a_failure() -> None:
    fake = FakeEdgarFullTextSearch().script(INP, FilingReply.of("no-hits"))

    found = client(fake).search(["InP substrates"], start=START, end=END)

    assert (found.total, found.hits) == (0, [])


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (FilingReply.error(404), "returned 404"),
        (FilingReply.error(503), "gave up after 3 attempts"),
        (FilingReply.unreachable(), "gave up after 3 attempts"),
        (FilingReply(body={"error": "no hits key"}), "unexpected response"),
    ],
    ids=["client-error", "server-error-retried", "unreachable-retried", "not-its-json"],
)
def test_a_failed_search_raises_filing_search_failed(reply: FilingReply, message: str) -> None:
    fake = FakeEdgarFullTextSearch().script(INP, reply, reply, reply)

    with pytest.raises(FilingSearchFailed, match=message):
        client(fake).search(["InP substrates"], start=START, end=END)


def test_the_channel_is_on_with_sec_s_user_agent_unless_turned_off(tmp_path: Path) -> None:
    on = EdgarFullTextSearch.from_settings(make_settings(tmp_path, sec_user_agent=UA))
    assert on is not None
    assert (on.user_agent, on.forms, on.max_hits) == (UA, FORMS, 10)
    assert (
        EdgarFullTextSearch.from_settings(
            make_settings(tmp_path, sec_user_agent=UA, discovery_edgar_max_hits=3)
        )
        or on
    ).max_hits == 3
    assert EdgarFullTextSearch.from_settings(make_settings(tmp_path)) is None
    off = make_settings(tmp_path, sec_user_agent=UA, discovery_edgar_fts="off")
    assert EdgarFullTextSearch.from_settings(off) is None
    with pytest.raises(ValidationError, match="ATLAS_SEC_USER_AGENT"):
        make_settings(tmp_path, discovery_edgar_fts="on")


def test_the_scout_and_skeptic_plan_ask_for_a_nullable_filing_phrase() -> None:
    # Strict mode sends every property as required; an answer recorded before the field
    # existed still parses, as null.
    for role, item in ((SCOUT, "ScoutQuery"), (SKEPTIC_PLAN, "PlannedQuery")):
        schema = role.response_schema()["$defs"][item]
        assert "filing_phrase" in schema["required"]
        assert "default" not in schema["properties"]["filing_phrase"]
    old = SCOUT.response.model_validate({"queries": [{"query": "InP wafers", "purpose": None}]})
    assert old.queries[0].filing_phrase is None
    new = SCOUT.response.model_validate(
        {"queries": [{"query": "InP wafers", "purpose": None, "filing_phrase": "InP substrates"}]}
    )
    assert new.queries[0].filing_phrase == "InP substrates"
