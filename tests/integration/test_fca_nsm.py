"""IQE from the FCA National Storage Mechanism end to end (Phase 3-6a ticket 05): discovery,
the fetch gate, fetch, ledger, HTML and PDF parse and retention, with the committed site
register (the NSM's terms allow automation).

Seams: `atlas ingest` (CLI) enqueues, one worker pass runs the ingest and its retains
against the served Hindsight fake, and everything is observed through `/api/v1`. The NSM is
replayed from the hand-written fixtures in `tests/fixtures/fca-nsm/iqe/`
(`scripts/make_fca_nsm_fixtures.py`; not recorded, documents synthetic). Expected values
are read off those fixtures by hand (NSM times are UTC).
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import REPO, Atlas

FIXTURES = REPO / "tests" / "fixtures" / "fca-nsm"
SITES = REPO / "configs" / "sources" / "sites.yaml"
ARTEFACTS = "https://data.fca.org.uk/artefacts"
INTERIM = f"{ARTEFACTS}/NSM/RNS/5a1f0c3e-0000-4000-8000-000000000001.html"
VOTING = f"{ARTEFACTS}/NSM/RNS/5a1f0c3e-0000-4000-8000-000000000002.html"
FORM_83 = f"{ARTEFACTS}/NSM/RNS/5a1f0c3e-0000-4000-8000-000000000003.html"
ANNUAL = f"{ARTEFACTS}/NSM/Portal/NI-000900001/NI-000900001.pdf"
SEARCH = "https://api.data.fca.org.uk/search?index=nsm-search"


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
    company = atlas.company("iqe")
    sources = atlas.get(f"/api/v1/companies/{company['id']}/sources", limit=100)["items"]
    return {source["canonical_url"]: source for source in sources}


def gate_decisions(atlas: Atlas) -> list[dict[str, Any]]:
    company = atlas.company("iqe")
    path = f"/api/v1/companies/{company['id']}/fetch-gate-decisions"
    return atlas.get(path, limit=100)["items"]


def test_iqe_is_ingested_from_the_nsm_with_publication_timestamps(atlas: Atlas) -> None:
    job = atlas.ingest("iqe-1", "iqe")

    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["counts"] == {
        "new_version": 3,
        "unchanged": 0,
        "not_modified": 0,
        "blocked": 0,
    }
    documents = by_url(atlas)
    assert set(documents) == {INTERIM, VOTING, ANNUAL}  # not the holder's Form 8.3
    interim = documents[INTERIM]
    assert interim["provider"] == "fca_nsm"
    assert interim["publisher"] == "FCA National Storage Mechanism"
    assert interim["source_type"] == "exchange_announcement"
    assert interim["source_tier"] == "A"
    assert interim["license_class"] == "public_regulatory"
    assert interim["title"] == "IQE plc: H1 2026 Interim Results"
    assert interim["document_type"] == "Half-year Financial Report"
    assert documents[ANNUAL]["document_type"] == "Annual Financial Report"

    expected = {
        INTERIM: (datetime(2026, 9, 7, 6, 0, 6, tzinfo=UTC), "text/html"),
        VOTING: (datetime(2026, 9, 1, 15, 0, tzinfo=UTC), "text/html"),
        ANNUAL: (datetime(2026, 5, 29, 14, 30, tzinfo=UTC), "application/pdf"),
    }
    for url, (published, media_type) in expected.items():
        version = atlas.version(url, "iqe")
        assert datetime.fromisoformat(version["available_at"]) == published
        assert version["available_at_basis"] == "publisher_timestamp"
        assert datetime.fromisoformat(version["published_at"]) == published
        assert version["media_type"] == media_type
        assert version["parse_status"] == "parsed"
        assert version["language"] == "en"
        assert version["metadata"]["announcement"]["issuer_code"] == "213800Y33WHD3ESJJP16"
    annual = atlas.version(ANNUAL, "iqe")
    assert annual["page_anchors"]  # parsed as a PDF, page by page
    assert "Annual Report and Accounts 2025" in atlas.parsed(annual["id"])


def test_the_annual_report_and_results_are_retained(atlas: Atlas) -> None:
    job = atlas.ingest("iqe-1", "iqe")

    retain_jobs = [atlas.get(f"/api/v1/jobs/{j}") for j in job["artifacts"]["retain_jobs"]]
    retained = {j["payload"]["source_version_id"] for j in retain_jobs}
    assert retained == {atlas.version(url, "iqe")["id"] for url in (INTERIM, VOTING, ANNUAL)}
    for url in (INTERIM, ANNUAL):
        memory = atlas.memory(atlas.version(url, "iqe")["id"])
        assert memory["retained"], url
        assert memory["documents"], url
        assert {d["retain_state"] for d in memory["documents"]} == {"completed"}, url


def test_each_request_records_the_nsm_terms_gate(atlas: Atlas) -> None:
    atlas.ingest("iqe-1", "iqe")

    version = atlas.version(ANNUAL, "iqe")
    (fetch,) = version["fetches"]
    decision = atlas.get(f"/api/v1/fetch-gate-decisions/{fetch['gate_decision_id']}")
    assert decision["status"] == "allowed"
    assert decision["url"] == ANNUAL
    assert decision["purpose"] == "document"
    assert decision["provider"] == "fca_nsm"
    assert decision["site"] == "fca-nsm"
    assert decision["terms"]["automation"] == "allowed"
    assert decision["terms"]["url"] == "https://data.fca.org.uk/artefacts/NSM_Terms_of_Use.pdf"
    assert decision["terms"]["checked_on"] == "2026-09-29"
    # The NSM serves no robots.txt (403): nothing is restricted.
    assert decision["robots"]["url"] == "https://data.fca.org.uk/robots.txt"
    assert decision["robots"]["status"] == 403
    assert decision["reason"].startswith("terms allow automation; robots.txt:")

    everything = gate_decisions(atlas)
    assert len(everything) == 4  # the search and three documents; never the Form 8.3
    assert {d["status"] for d in everything} == {"allowed"}
    (search,) = [d for d in everything if d["purpose"] == "discovery"]
    assert search["url"] == SEARCH
    assert search["robots"]["url"] == "https://api.data.fca.org.uk/robots.txt"
    assert FORM_83 not in {d["url"] for d in everything}


def test_a_second_ingest_records_observations_without_new_versions(atlas: Atlas) -> None:
    atlas.ingest("iqe-1", "iqe")

    job = atlas.ingest("iqe-2", "iqe")

    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["counts"]["new_version"] == 0
    assert job["artifacts"]["counts"]["not_modified"] == 3  # conditional, on Last-Modified
    assert len(atlas.versions(INTERIM, "iqe")) == 1
