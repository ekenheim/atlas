"""Soitec from the AMF info-financière API end to end (Phase 3-6a ticket 06): discovery, the
fetch gate, fetch, ledger, PDF parse and retention (English only), with the committed site
register (the API is under the Licence Ouverte; Euronext and soitec.com are blocked).

Seams: `atlas ingest` (CLI) enqueues, one worker pass runs the ingest and its retains
against the served Hindsight fake, and everything is observed through `/api/v1`. The API is
replayed from the hand-written fixtures in `tests/fixtures/amf/soitec/`
(`scripts/make_amf_fixtures.py`; not recorded, documents synthetic). Expected values are
read off those fixtures by hand (API times are UTC).
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import REPO, Atlas

FIXTURES = REPO / "tests" / "fixtures" / "amf"
SITES = REPO / "configs" / "sources" / "sites.yaml"
SITE = "https://www.info-financiere.gouv.fr"
RECORDS = f"{SITE}/api/explore/v2.0/catalog/datasets/flux-amf-new-prod/records"
FILES = "https://fr.ftp.opendatasoft.com/datadila/INFOFI"
THRESHOLD = f"{FILES}/307/8888/01/FC307900001_20260824.pdf"
ESEF = f"{FILES}/MKW/2026/06/FCMKW119500_20260617.zip"
RESULTS_EN = f"{FILES}/MKW/2026/06/FCMKW119000_20260610.pdf"
RESULTS_FR = f"{FILES}/MKW/2026/06/FCMKW139000_20260610.pdf"
SOITEC_LEI = "969500ZR92SQCU9TST26"
RESULTS_AT = datetime(2026, 6, 10, 5, 45, 3, tzinfo=UTC)  # uin_dat_amf


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> Iterator[Atlas]:
    harness = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        exchange_fixtures_dir=FIXTURES,
        source_sites_config=SITES,
    )
    harness.apply_template()
    yield harness
    harness.engine.dispose()


def by_url(atlas: Atlas) -> dict[str, dict[str, Any]]:
    company = atlas.company("soitec")
    sources = atlas.get(f"/api/v1/companies/{company['id']}/sources", limit=100)["items"]
    return {source["canonical_url"]: source for source in sources}


def gate_decisions(atlas: Atlas) -> list[dict[str, Any]]:
    company = atlas.company("soitec")
    path = f"/api/v1/companies/{company['id']}/fetch-gate-decisions"
    return atlas.get(path, limit=100)["items"]


def test_soitec_is_ingested_from_the_amf_api_with_publication_timestamps(atlas: Atlas) -> None:
    job = atlas.ingest("soitec-1", "soitec")

    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["counts"] == {
        "new_version": 3,
        "unchanged": 0,
        "not_modified": 0,
        "blocked": 0,
    }
    documents = by_url(atlas)
    assert set(documents) == {THRESHOLD, RESULTS_EN, RESULTS_FR}  # not the ESEF package
    results = documents[RESULTS_EN]
    assert results["provider"] == "amf_info_financiere"
    assert results["publisher"] == "AMF info-financière"
    assert results["source_type"] == "exchange_announcement"
    assert results["source_tier"] == "A"
    assert results["license_class"] == "public_regulatory"
    assert results["title"] == "Soitec reports full-year 2026 results"
    assert results["document_type"] == "Annual financial information"

    expected = {
        RESULTS_EN: (RESULTS_AT, "en"),
        RESULTS_FR: (RESULTS_AT, "fr"),
        THRESHOLD: (datetime(2026, 8, 24, 14, 6, 22, tzinfo=UTC), "fr"),
    }
    for url, (published, language) in expected.items():
        version = atlas.version(url, "soitec")
        assert datetime.fromisoformat(version["available_at"]) == published
        assert version["available_at_basis"] == "publisher_timestamp"
        assert datetime.fromisoformat(version["published_at"]) == published
        assert version["media_type"] == "application/pdf"
        assert version["parse_status"] == "parsed"
        assert version["language"] == language
        announcement = version["metadata"]["announcement"]
        assert announcement["issuer_code"] == SOITEC_LEI
        # The Licence Ouverte's credit: the source and the date of its last update.
        assert announcement["attribution"].startswith(
            "Source: Autorité des marchés financiers (AMF), info-financiere.gouv.fr (DILA),"
            " dataset flux-amf-new-prod, record "
        )
        assert announcement["attribution"].endswith(
            "Licence Ouverte / Open Licence 2.0 (Etalab),"
            " https://www.etalab.gouv.fr/licence-ouverte-open-licence/"
        )
    english = atlas.version(RESULTS_EN, "soitec")
    assert english["page_anchors"]  # parsed as a PDF, page by page
    assert "Soitec reports full-year 2026 results" in atlas.parsed(english["id"])
    french = atlas.version(RESULTS_FR, "soitec")
    assert "Soitec publie ses résultats annuels 2026" in atlas.parsed(french["id"])


def test_only_the_english_results_are_retained(atlas: Atlas) -> None:
    job = atlas.ingest("soitec-1", "soitec")

    retain_jobs = [atlas.get(f"/api/v1/jobs/{j}") for j in job["artifacts"]["retain_jobs"]]
    retained = {j["payload"]["source_version_id"] for j in retain_jobs}
    assert retained == {atlas.version(RESULTS_EN, "soitec")["id"]}
    memory = atlas.memory(atlas.version(RESULTS_EN, "soitec")["id"])
    assert memory["retained"]
    assert {d["retain_state"] for d in memory["documents"]} == {"completed"}
    for url in (RESULTS_FR, THRESHOLD):  # archived in French, never retained
        french = atlas.memory(atlas.version(url, "soitec")["id"])
        assert not french["retained"], url
        assert french["documents"] == [], url


def test_each_request_records_the_api_client_gate_decision(atlas: Atlas) -> None:
    atlas.ingest("soitec-1", "soitec")

    version = atlas.version(RESULTS_EN, "soitec")
    (fetch,) = version["fetches"]
    decision = atlas.get(f"/api/v1/fetch-gate-decisions/{fetch['gate_decision_id']}")
    assert decision["status"] == "allowed"
    assert decision["url"] == RESULTS_EN
    assert decision["purpose"] == "document"
    assert decision["provider"] == "amf_info_financiere"
    assert decision["site"] == "amf-info-financiere"
    assert decision["terms"]["automation"] == "allowed"
    assert decision["terms"]["url"] == "https://www.data.gouv.fr/dataservices/api-info-financiere"
    assert decision["terms"]["checked_on"] == "2026-09-29"
    # robots.txt is read and recorded; it addresses crawlers, not the documented API's client.
    assert decision["robots"]["url"] == "https://fr.ftp.opendatasoft.com/robots.txt"
    assert decision["robots"]["status"] == 200
    assert decision["robots"]["rule"] == "Disallow: / (line 2)"
    assert decision["reason"].startswith(
        "terms allow automation; documented API client, not a crawler"
    )

    everything = gate_decisions(atlas)
    assert len(everything) == 4  # the search and three files; never the ESEF package
    assert {d["status"] for d in everything} == {"allowed"}
    (search,) = [d for d in everything if d["purpose"] == "discovery"]
    assert search["url"].startswith(f"{RECORDS}?")
    assert search["robots"]["url"] == f"{SITE}/robots.txt"
    assert search["robots"]["rule"] == "Disallow: /api/ (line 13)"
    assert ESEF not in {d["url"] for d in everything}


def test_a_second_ingest_records_observations_without_new_versions(atlas: Atlas) -> None:
    atlas.ingest("soitec-1", "soitec")

    job = atlas.ingest("soitec-2", "soitec")

    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["counts"]["new_version"] == 0
    assert job["artifacts"]["counts"]["not_modified"] == 3  # conditional, on the ETag
    assert len(atlas.versions(RESULTS_EN, "soitec")) == 1
