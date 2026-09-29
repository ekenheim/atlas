"""The AMF info-financière adapter (Phase 3-6a ticket 06) at the transport boundary, and the
committed site register's decisions for Soitec's sources.

The responses are the hand-written fixtures in `tests/fixtures/amf/soitec/`
(`scripts/make_amf_fixtures.py`: the documented Explore API v2.0 records shape and field
names as served on 2026-09-29, not recorded; identifiers and documents synthetic; the two
robots.txt bodies as served). Expected values are read off the fixture rows by hand (API
times are UTC).
"""

import asyncio
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from atlas.sources import FetchError, SearchQuery, SecHttpClient, SourceCandidate, TokenBucket
from atlas.sources.amf import AmfInfoFinanciereAdapter
from atlas.sources.gate import FetchBlocked, FetchGate, GatedHttpClient, load_site_register

REPO = Path(__file__).parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "amf" / "soitec"
SITES = REPO / "configs" / "sources" / "sites.yaml"
SITE = "https://www.info-financiere.gouv.fr"
RECORDS = f"{SITE}/api/explore/v2.0/catalog/datasets/flux-amf-new-prod/records"
FILES = "https://fr.ftp.opendatasoft.com/datadila/INFOFI"
THRESHOLD = f"{FILES}/307/8888/01/FC307900001_20260824.pdf"
ESEF = f"{FILES}/MKW/2026/06/FCMKW119500_20260617.zip"
RESULTS_EN = f"{FILES}/MKW/2026/06/FCMKW119000_20260610.pdf"
RESULTS_FR = f"{FILES}/MKW/2026/06/FCMKW139000_20260610.pdf"
SOITEC_LEI = "969500ZR92SQCU9TST26"
NOW = datetime(2026, 9, 29, 3, 0, 0, tzinfo=UTC)
UA = "AtlasResearch"
AMF_TIME = datetime(2026, 6, 10, 5, 45, 3, tzinfo=UTC)  # uin_dat_amf, after inf_dat_emt


class Amf:
    """Serves the records search (a different body per request, if given), the files and
    both hosts' robots.txt; records every request."""

    def __init__(self, pages: list[bytes] | None = None) -> None:
        self.pages = pages or [(FIXTURES / "records.json").read_bytes()]
        self.requests: list[str] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        self.requests.append(url)
        if url == f"{SITE}/robots.txt":
            body = (FIXTURES / "robots-info-financiere.txt").read_bytes()
            return httpx2.Response(200, content=body)
        if url == "https://fr.ftp.opendatasoft.com/robots.txt":
            return httpx2.Response(200, content=(FIXTURES / "robots-opendatasoft.txt").read_bytes())
        if url.startswith(f"{RECORDS}?"):
            body = self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]
            return httpx2.Response(200, content=body, headers={"Content-Type": "application/json"})
        path = FIXTURES / url.removeprefix(f"{FILES}/")
        if url.startswith(FILES) and path.is_file():
            return httpx2.Response(
                200, content=path.read_bytes(), headers={"Content-Type": "application/pdf"}
            )
        return httpx2.Response(404)

    def searches(self) -> list[dict[str, list[str]]]:
        return [parse_qs(urlsplit(u).query) for u in self.requests if u.startswith(RECORDS)]


def client(amf: Amf) -> SecHttpClient:
    return SecHttpClient(
        UA,
        transport=httpx2.MockTransport(amf.handle),
        limiter=TokenBucket(math.inf),
        require_contact=False,
    )


def run(amf: Amf, query: SearchQuery, fetch: bool = False) -> Any:
    async def go() -> Any:
        async with client(amf) as http:
            adapter = AmfInfoFinanciereAdapter(http, lei=SOITEC_LEI, now=lambda: NOW)
            candidates = await adapter.discover(query)
            if fetch:
                return [await adapter.fetch(c) for c in candidates]
            return candidates

    return asyncio.run(go())


def fixture_records() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "records.json").read_bytes())["records"]


def answer(records: list[dict[str, Any]], total: int | None = None) -> bytes:
    value = len(records) if total is None else total
    return json.dumps({"total_count": value, "links": [], "records": records}).encode()


def with_fields(record: dict[str, Any], **fields: Any) -> dict[str, Any]:
    inner = record["record"]
    return record | {"record": inner | {"fields": inner["fields"] | fields}}


def test_discovery_lists_soitecs_filings_with_the_amf_publication_time() -> None:
    candidates: list[SourceCandidate] = run(Amf(), SearchQuery())

    # The ESEF package (.zip) is not a document Atlas parses.
    assert [(c.url, c.available_at, c.language) for c in candidates] == [
        (THRESHOLD, datetime(2026, 8, 24, 14, 6, 22, tzinfo=UTC), "fr"),
        (RESULTS_EN, AMF_TIME, "en"),
        (RESULTS_FR, AMF_TIME, "fr"),
    ]
    results = candidates[1]
    assert results.provider_id == "amf_info_financiere"
    assert results.kind == "exchange_announcement"
    assert results.available_at_basis == "publisher_timestamp"
    assert results.title == "Soitec reports full-year 2026 results"
    assert results.document_type == "Annual financial information"
    assert results.discovered_at == NOW
    announcement = results.announcement
    assert announcement is not None
    assert announcement.publisher == "AMF info-financière"
    assert announcement.announcement_id == "119000_20260610"
    assert announcement.issuer_code == SOITEC_LEI
    assert announcement.issuer_name == "SOITEC"
    assert announcement.category == "Informations réglementées continues"
    assert announcement.file_type == "PDF"
    assert announcement.published_local == "2026-06-10T05:45:03+00:00"
    assert announcement.published_at == AMF_TIME
    assert announcement.timezone == "UTC"
    assert announcement.attribution == (
        "Source: Autorité des marchés financiers (AMF), info-financiere.gouv.fr (DILA),"
        " dataset flux-amf-new-prod, record 2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e,"
        " updated 2026-06-10T06:00:00Z. Licence Ouverte / Open Licence 2.0 (Etalab),"
        " https://www.etalab.gouv.fr/licence-ouverte-open-licence/"
    )
    threshold = candidates[0]
    assert threshold.document_type == "Décision de franchissement de seuil"  # English "NULL"


def test_the_search_is_the_documented_records_query_for_the_lei() -> None:
    amf = Amf()

    run(amf, SearchQuery())

    assert amf.searches() == [
        {
            "where": [f'identificationsociete_iso_cd_lei="{SOITEC_LEI}"'],
            "order_by": ["informationdeposee_inf_dat_emt desc"],
            "limit": ["100"],
            "offset": ["0"],
        }
    ]


def test_since_and_limit_bound_discovery() -> None:
    after_july = run(Amf(), SearchQuery(since=datetime(2026, 7, 1, tzinfo=UTC)))
    newest = run(Amf(), SearchQuery(limit=2))

    assert [c.url for c in after_july] == [THRESHOLD]
    assert [c.url for c in newest] == [THRESHOLD, RESULTS_EN]


def test_the_transmission_time_or_discovery_is_used_without_an_amf_time() -> None:
    records = fixture_records()
    records[2] = with_fields(records[2], uin_dat_amf=None)
    records[3] = with_fields(records[3], uin_dat_amf="", informationdeposee_inf_dat_emt=None)

    candidates = run(Amf([answer(records)]), SearchQuery())

    english, french = candidates[1], candidates[2]
    assert english.available_at == datetime(2026, 6, 10, 5, 45, tzinfo=UTC)
    assert english.available_at_basis == "publisher_timestamp"
    assert english.announcement is not None
    assert english.announcement.published_local == "2026-06-10T05:45:00+00:00"
    assert french.available_at == NOW
    assert french.available_at_basis == "observed_discovery"
    assert french.announcement is not None
    assert french.announcement.published_at is None


def test_other_languages_are_left_to_the_parse() -> None:
    records = fixture_records()
    records[2] = with_fields(records[2], informationdeposee_inf_lng_inf="Bilingue")

    candidates = run(Amf([answer(records)]), SearchQuery())

    assert candidates[1].language is None


def test_rows_for_another_lei_or_without_a_document_are_skipped() -> None:
    records = fixture_records()
    records[0] = with_fields(records[0], identificationsociete_iso_cd_lei="969500OTHER0000000")
    records[3] = with_fields(records[3], url_de_recuperation=None)

    candidates = run(Amf([answer(records)]), SearchQuery())

    assert [c.url for c in candidates] == [RESULTS_EN]


def own_record(index: int, transmitted: datetime) -> dict[str, Any]:
    stamp = transmitted.isoformat()
    return with_fields(
        fixture_records()[2],
        uin_idt_uin=f"row-{index}",
        url_de_recuperation=f"{FILES}/MKW/2026/01/row-{index}.pdf",
        uin_dat_amf=stamp,
        informationdeposee_inf_dat_emt=stamp,
    )


def test_pages_are_asked_for_until_since_is_reached() -> None:
    first = [own_record(i, datetime(2026, 9, 1, tzinfo=UTC)) for i in range(100)]
    second = [own_record(100, datetime(2026, 8, 1, tzinfo=UTC))] + [
        own_record(101 + i, datetime(2026, 5, 1, tzinfo=UTC)) for i in range(99)
    ]
    amf = Amf([answer(first, 277), answer(second, 277)])

    candidates = run(amf, SearchQuery(since=datetime(2026, 6, 1, tzinfo=UTC)))

    assert [s["offset"] for s in amf.searches()] == [["0"], ["100"]]  # not the rest
    assert len(candidates) == 101


def test_the_last_page_ends_discovery() -> None:
    rows = [own_record(i, datetime(2026, 9, 1, tzinfo=UTC)) for i in range(100)]
    amf = Amf([answer(rows, 130), answer(rows[:30], 130)])

    candidates = run(amf, SearchQuery())

    assert [s["offset"] for s in amf.searches()] == [["0"], ["100"]]
    assert len(candidates) == 130


def test_more_than_ten_api_calls_fails_rather_than_dropping_filings() -> None:
    rows = [own_record(i, datetime(2026, 9, 1, tzinfo=UTC)) for i in range(100)]
    amf = Amf([answer(rows, 5000)])

    with pytest.raises(FetchError, match="more than 1000 filings"):
        run(amf, SearchQuery())

    assert len(amf.searches()) == 10


@pytest.mark.parametrize(
    "body",
    [
        b"<html>maintenance</html>",
        b'{"total_count": 3}',
        b'{"total_count": 1, "records": [{"record": {"id": "x", "fields": 3}}]}',
    ],
)
def test_an_unexpected_answer_fails_discovery(body: bytes) -> None:
    with pytest.raises(FetchError, match="the info-financière API answered something unexpected"):
        run(Amf([body]), SearchQuery())


def test_fetch_returns_the_files_as_served() -> None:
    fetched = run(Amf(), SearchQuery(), fetch=True)

    results = fetched[1]
    assert results.url == RESULTS_EN
    assert results.media_type == "application/pdf"
    assert results.content == (FIXTURES / RESULTS_EN.removeprefix(f"{FILES}/")).read_bytes()


# --- the committed site register ---


def gated(amf: Amf, url: str) -> Any:
    """The gate's decision for one GET under the committed register."""

    async def go() -> Any:
        async with client(amf) as http:
            gate = FetchGate(load_site_register(SITES), http, now=lambda: NOW)
            gated_client = GatedHttpClient(http, gate)
            try:
                await gated_client.get(url)
            except FetchBlocked as blocked:
                return blocked.decision
            except FetchError:
                pass
            (decision,) = gated_client.take_decisions()
            return decision

    return asyncio.run(go())


def test_the_documented_api_and_its_files_are_allowed_as_an_api_client() -> None:
    amf = Amf()
    search_url = f"{RECORDS}?where=x&limit=100&offset=0"

    search = gated(amf, search_url)
    document = gated(amf, RESULTS_EN)

    for decision in (search, document):
        assert decision.status == "allowed"
        assert decision.site == "amf-info-financiere"
        assert decision.terms.automation == "allowed"
        assert decision.terms.url == "https://www.data.gouv.fr/dataservices/api-info-financiere"
        assert "Licence Ouverte / Open Licence 2.0" in decision.terms.note
        assert decision.robots.status == 200  # read, archived-hash recorded, not obeyed here
        assert decision.reason.startswith(
            "terms allow automation; documented API client, not a crawler"
            " (https://www.data.gouv.fr/dataservices/api-info-financiere): robots.txt"
        )
    assert search.robots.url == f"{SITE}/robots.txt"
    assert search.robots.rule == "Disallow: /api/ (line 13)"
    assert document.robots.url == "https://fr.ftp.opendatasoft.com/robots.txt"
    assert document.robots.rule == "Disallow: / (line 2)"
    assert search_url in amf.requests and RESULTS_EN in amf.requests


@pytest.mark.parametrize(
    ("url", "rule"),
    [
        # the site's pages and feeds: Atlas never crawls them
        (f"{SITE}/explore/dataset/flux-amf-new-prod/rss/", "Disallow: /explore/dataset/*/rss/"),
        # another dataset, and the exports, are outside the API client's prefixes
        (f"{SITE}/api/explore/v2.0/catalog/datasets/codes-lei/records", "Disallow: /api/"),
        (f"{SITE}/api/explore/v2.0/catalog/datasets/flux-amf-new-prod/../x/", "Disallow: /api/"),
        ("https://fr.ftp.opendatasoft.com/otherdomain/file.pdf", "Disallow: /"),
    ],
)
def test_anything_else_on_those_hosts_is_blocked_by_robots_txt(url: str, rule: str) -> None:
    amf = Amf()

    decision = gated(amf, url)

    assert decision.status == "blocked"
    assert decision.blocked_by == "robots"
    assert decision.robots.rule.startswith(rule)
    assert url not in amf.requests


@pytest.mark.parametrize(
    ("url", "site", "reason"),
    [
        (
            "https://live.euronext.com/en/listview/company-press-release/62020",
            "euronext",
            "blocked: Euronext Terms of Use prohibit robots and systematic retrieval"
            " (Euronext's prior written permission required)",
        ),
        (
            "https://www.euronext.com/en/markets/paris",
            "euronext",
            "blocked: Euronext Terms of Use prohibit robots and systematic retrieval"
            " (Euronext's prior written permission required)",
        ),
        (
            "https://www.soitec.com/en/investors/regulated-information",
            "soitec",
            "blocked: soitec.com's terms forbid reuse of the site's elements (Soitec's prior"
            " written permission required)",
        ),
    ],
)
def test_euronext_and_soitec_com_are_blocked_by_their_terms_without_a_request(
    url: str, site: str, reason: str
) -> None:
    amf = Amf()

    decision = gated(amf, url)

    assert decision.status == "blocked"
    assert decision.blocked_by == "terms"
    assert decision.site == site
    assert decision.reason == reason
    assert decision.terms.automation == "forbidden"
    assert decision.robots is None
    assert amf.requests == []
