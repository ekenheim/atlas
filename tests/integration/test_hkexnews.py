"""Innolight from HKEXnews end to end (Phase 3-6a ticket 04): discovery, the fetch gate,
fetch, ledger, PDF parse and retention, and `blocked` fetches visible in the API.

Seams: `atlas ingest` (CLI) enqueues, one worker pass runs the ingest and its retains
against the served Hindsight fake, and everything is observed through `/api/v1`. HKEXnews
is replayed from the hand-written fixtures in `tests/fixtures/hkexnews/innolight/`
(`scripts/make_hkexnews_fixtures.py`; not recorded). Expected values are read off those
fixtures by hand (DATE_TIME is Hong Kong time, UTC+8).

The repo's site register records that HKEXnews' terms forbid automated access with no
consent, so these tests use a copy of it with a **synthetic** consent for HKEXnews (no
such consent exists) to exercise the path a real consent would open; one test uses the
register as committed.
"""

import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import REPO, Atlas

FIXTURES = REPO / "tests" / "fixtures" / "hkexnews"
SITES = REPO / "configs" / "sources" / "sites.yaml"
BASE = "https://www1.hkexnews.hk/listedco/listconews/sehk/2026"
INTERIM = f"{BASE}/0821/2026082101227.pdf"
OVERSEAS = f"{BASE}/0904/2026090400456.pdf"
ALLOTMENT = f"{BASE}/0729/2026072900123.pdf"
SEARCH = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
SYNTHETIC_CONSENT = {
    "reference": "SYNTHETIC TEST CONSENT: no consent from HKEX exists",
    "granted_on": "2026-09-29",
    "scope": "tests only",
}


def register_with_consent(tmp_path: Path) -> Path:
    register = yaml.safe_load(SITES.read_text())
    register["sites"]["hkexnews"]["consent"] = SYNTHETIC_CONSENT
    path = tmp_path / "sites-with-test-consent.yaml"
    path.write_text(yaml.safe_dump(register))
    return path


def fixtures_with_robots(tmp_path: Path, robots: bytes) -> Path:
    """A copy of the fixtures whose HKEXnews robots.txt is `robots` (served with 200)."""
    root = tmp_path / "hkexnews"
    shutil.copytree(FIXTURES, root)
    (root / "innolight" / "robots.txt").write_bytes(robots)
    manifest = root / "innolight" / "manifest.json"
    manifest.write_text(
        manifest.read_text().replace(
            '"file": "robots-404.html",\n      "status": 404,', '"file": "robots.txt",'
        )
    )
    assert '"file": "robots.txt"' in manifest.read_text()
    return root


def make_atlas(
    database_url: str, tmp_path: Path, hindsight: Served, sites: Path, fixtures: Path = FIXTURES
) -> Atlas:
    atlas = Atlas(
        database_url,
        tmp_path,
        hindsight.url,
        exchange_fixtures_dir=fixtures,
        source_sites_config=sites,
    )
    atlas.apply_template()
    return atlas


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> Iterator[Atlas]:
    harness = make_atlas(database_url, tmp_path, hindsight[1], register_with_consent(tmp_path))
    yield harness
    harness.engine.dispose()


def by_url(atlas: Atlas) -> dict[str, dict[str, Any]]:
    """Innolight's Source Documents by canonical URL."""
    company = atlas.company("innolight")
    sources = atlas.get(f"/api/v1/companies/{company['id']}/sources", limit=100)["items"]
    return {source["canonical_url"]: source for source in sources}


def gate_decisions(atlas: Atlas, **params: Any) -> list[dict[str, Any]]:
    company = atlas.company("innolight")
    path = f"/api/v1/companies/{company['id']}/fetch-gate-decisions"
    return atlas.get(path, limit=100, **params)["items"]


def test_innolight_is_ingested_from_hkexnews_with_publisher_timestamps(atlas: Atlas) -> None:
    job = atlas.ingest("innolight-1", "innolight")

    assert job["status"] == "succeeded", job["failures"]
    artifacts = job["artifacts"]
    assert artifacts["counts"] == {
        "new_version": 3,
        "unchanged": 0,
        "not_modified": 0,
        "blocked": 0,
    }
    documents = by_url(atlas)
    assert set(documents) == {INTERIM, OVERSEAS, ALLOTMENT}
    interim = documents[INTERIM]
    assert interim["provider"] == "hkexnews"
    assert interim["publisher"] == "HKEXnews"
    assert interim["source_type"] == "exchange_announcement"
    assert interim["source_tier"] == "A"
    assert interim["license_class"] == "public_regulatory"
    assert interim["title"] == "INTERIM RESULTS ANNOUNCEMENT FOR THE SIX MONTHS ENDED 30 JUNE 2026"
    assert interim["document_type"] == "Announcements and Notices - [Interim Results]"
    assert interim["accession"] is None

    expected = {
        INTERIM: (datetime(2026, 8, 21, 14, 30, tzinfo=UTC), "en", "21/08/2026 22:30"),
        OVERSEAS: (datetime(2026, 9, 4, 11, 5, tzinfo=UTC), "zh", "04/09/2026 19:05"),
        ALLOTMENT: (datetime(2026, 7, 29, 15, 0, tzinfo=UTC), "en", "29/07/2026 23:00"),
    }
    for url, (published, language, local) in expected.items():
        version = atlas.version(url, "innolight")
        assert datetime.fromisoformat(version["available_at"]) == published
        assert version["available_at_basis"] == "publisher_timestamp"
        assert datetime.fromisoformat(version["published_at"]) == published
        assert version["media_type"] == "application/pdf"
        assert version["parse_status"] == "parsed"
        assert version["language"] == language
        assert version["page_anchors"]
        assert version["metadata"]["announcement"]["published_local"] == local
        assert version["metadata"]["announcement"]["issuer_code"] == "03308"


def test_retains_are_enqueued_for_the_english_documents_only(atlas: Atlas) -> None:
    job = atlas.ingest("innolight-1", "innolight")

    retain_jobs = [atlas.get(f"/api/v1/jobs/{j}") for j in job["artifacts"]["retain_jobs"]]
    retained = {j["payload"]["source_version_id"] for j in retain_jobs}
    english = {atlas.version(url, "innolight")["id"] for url in (INTERIM, ALLOTMENT)}
    assert retained == english
    for url in (INTERIM, ALLOTMENT):
        memory = atlas.memory(atlas.version(url, "innolight")["id"])
        assert memory["retained"], url
        assert memory["documents"], url
        assert {d["retain_state"] for d in memory["documents"]} == {"completed"}, url
    chinese = atlas.memory(atlas.version(OVERSEAS, "innolight")["id"])
    assert chinese["retained"] is False
    assert chinese["documents"] == []


def test_each_fetch_records_the_gate_that_allowed_it(atlas: Atlas) -> None:
    atlas.ingest("innolight-1", "innolight")

    version = atlas.version(INTERIM, "innolight")
    (fetch,) = version["fetches"]
    decision = atlas.get(f"/api/v1/fetch-gate-decisions/{fetch['gate_decision_id']}")
    assert decision["status"] == "allowed"
    assert decision["blocked_by"] is None
    assert decision["url"] == INTERIM
    assert decision["purpose"] == "document"
    assert decision["provider"] == "hkexnews"
    assert decision["site"] == "hkexnews"
    assert decision["user_agent_token"] == "AtlasResearch"
    assert decision["terms"]["automation"] == "forbidden"
    assert decision["terms"]["consent"]["reference"] == SYNTHETIC_CONSENT["reference"]
    assert decision["terms"]["url"] == (
        "https://www.hkex.com.hk/Global/Exchange/Terms-of-Use?sc_lang=en"
    )
    # HKEXnews serves no robots.txt (the fixture's 404): nothing is restricted.
    assert decision["robots"]["url"] == "https://www1.hkexnews.hk/robots.txt"
    assert decision["robots"]["status"] == 404
    assert decision["robots"]["rule"] is None
    assert decision["reason"].startswith("consent; robots.txt:")

    everything = gate_decisions(atlas)
    assert {(d["purpose"], d["status"]) for d in everything} == {
        ("discovery", "allowed"),
        ("document", "allowed"),
    }
    (search,) = [d for d in everything if d["purpose"] == "discovery"]
    assert search["url"].startswith(f"{SEARCH}?")
    assert len(everything) == 4  # the search and three documents


def test_a_path_robots_txt_disallows_is_blocked_and_visible(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    robots = b"User-agent: *\nDisallow: /listedco/listconews/sehk/2026/0904/\n"
    atlas = make_atlas(
        database_url,
        tmp_path,
        hindsight[1],
        register_with_consent(tmp_path),
        fixtures_with_robots(tmp_path, robots),
    )

    job = atlas.ingest("innolight-1", "innolight")

    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["counts"]["new_version"] == 2
    assert job["artifacts"]["counts"]["blocked"] == 1
    (blocked,) = job["artifacts"]["blocked"]
    assert blocked["url"] == OVERSEAS
    assert blocked["blocked_by"] == "robots"
    assert set(by_url(atlas)) == {INTERIM, ALLOTMENT}  # never fetched, so no document

    (decision,) = gate_decisions(atlas, status="blocked")
    assert decision["id"] == blocked["gate_decision_id"]
    assert decision["url"] == OVERSEAS
    assert decision["purpose"] == "document"
    assert decision["blocked_by"] == "robots"
    assert decision["reason"] == (
        "robots.txt: Disallow: /listedco/listconews/sehk/2026/0904/ (line 2) disallows it"
    )
    assert decision["robots"]["status"] == 200
    assert decision["robots"]["group"] == "*"
    with atlas.engine.connect() as connection:
        observed = connection.execute(
            text("SELECT count(*) FROM fetch_observation WHERE url = :url"), {"url": OVERSEAS}
        ).scalar_one()
    assert observed == 0
    atlas.engine.dispose()


def test_with_the_committed_register_hkexnews_is_blocked_by_its_terms(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    atlas = make_atlas(database_url, tmp_path, hindsight[1], SITES)

    job = atlas.ingest("innolight-1", "innolight")

    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["counts"] == {
        "new_version": 0,
        "unchanged": 0,
        "not_modified": 0,
        "blocked": 1,
    }
    (decision,) = gate_decisions(atlas)
    assert decision["status"] == "blocked"
    assert decision["blocked_by"] == "terms"
    assert decision["purpose"] == "discovery"
    assert decision["url"].startswith(f"{SEARCH}?")
    assert decision["reason"] == (
        "blocked: HKEX Terms of Use prohibit automated access"
        " (IIS licence or written consent required)"
    )
    assert decision["robots"] is None  # not even robots.txt was requested
    assert decision["terms"]["checked_on"] == "2026-09-29"
    assert by_url(atlas) == {}
    with atlas.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM fetch_observation")).scalar() == 0
    atlas.engine.dispose()


def test_a_second_ingest_records_observations_without_new_versions(atlas: Atlas) -> None:
    atlas.ingest("innolight-1", "innolight")

    job = atlas.ingest("innolight-2", "innolight")

    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["counts"]["new_version"] == 0
    assert job["artifacts"]["counts"]["not_modified"] == 3  # conditional, on Last-Modified
    assert len(atlas.versions(INTERIM, "innolight")) == 1
    (fetch_1, fetch_2) = atlas.version(INTERIM, "innolight")["fetches"]
    assert fetch_1["gate_decision_id"] != fetch_2["gate_decision_id"]


def test_the_ledger_refuses_a_fetch_under_a_blocked_decision(atlas: Atlas) -> None:
    atlas.ingest("innolight-1", "innolight")
    with atlas.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO fetch_gate_decision (id, provider, purpose, url, status, blocked_by,"
                " reason, user_agent_token, decided_at) VALUES (gen_random_uuid(), 'hkexnews',"
                " 'document', :url, 'blocked', 'robots', 'test', 'AtlasResearch', now())"
            ),
            {"url": INTERIM},
        )
    with pytest.raises(DBAPIError, match="needs an allowed gate decision"):
        with atlas.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO fetch_observation (id, source_document_id, source_version_id,"
                    " outcome, url, fetched_at, raw_sha256, comparison_sha256, attempts,"
                    " gate_decision_id) SELECT gen_random_uuid(), o.source_document_id,"
                    " o.source_version_id, 'unchanged', o.url, now(), o.raw_sha256,"
                    " o.comparison_sha256, 1, (SELECT id FROM fetch_gate_decision"
                    " WHERE status = 'blocked') FROM fetch_observation o LIMIT 1"
                )
            )


def test_the_cli_refuses_forms_for_an_exchange_company(atlas: Atlas) -> None:
    result = atlas.cli("ingest", "--company", "innolight", "--forms", "10-K")

    assert result.returncode == 2
    assert "--forms applies to SEC filers only" in result.stderr
