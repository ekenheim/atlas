"""The Phase 1 gate: ingest Lumentum's recorded EDGAR filings end to end.

Seam: `atlas ingest` (CLI) enqueues, one worker pass runs the job, and everything is
observed through `/api/v1`, the archived bytes and the audit trail, on a fresh database.
Expected values come from the recorded fixtures (tests/fixtures/edgar/lumentum).
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from atlas.api.app import create_app
from atlas.db.migrate import upgrade
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.settings import Settings

REPO = Path(__file__).parents[2]
THEMES = REPO / "configs" / "themes" / "ai-infrastructure.yaml"
EDGAR_FIXTURES = REPO / "tests" / "fixtures" / "edgar"
LUMENTUM_FIXTURES = EDGAR_FIXTURES / "lumentum"
MANIFEST = json.loads((LUMENTUM_FIXTURES / "manifest.json").read_text())
SUBMISSIONS = json.loads(
    (LUMENTUM_FIXTURES / "data.sec.gov" / "submissions" / "CIK0001633978.json").read_bytes()
)
GOLDEN_PARSES = json.loads((REPO / "tests" / "fixtures" / "parser" / "golden.json").read_text())

ARCHIVES = "https://www.sec.gov/Archives/edgar/data/1633978"
URL_8K = f"{ARCHIVES}/000162828026055726/lite-20260811.htm"
URL_EX991 = f"{ARCHIVES}/000162828026055726/lite_ex991xq4fy26.htm"
URL_10K = f"{ARCHIVES}/000162828026057358/lite-20260627.htm"
URL_10Q = f"{ARCHIVES}/000162828026030777/lite-20260328.htm"
URL_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001633978.json"
FILING_URLS = {URL_8K, URL_EX991, URL_10K, URL_10Q}
ALL_URLS = FILING_URLS | {URL_FACTS}
SEC_EDGE_SCRIPT = b'<script type="text/javascript"  src="/KSRe0AD3p8BYYbpDUqIn/'


def recorded(url: str) -> dict[str, Any]:
    return next(entry for entry in MANIFEST["responses"] if entry["url"] == url)


def recorded_bytes(url: str, root: Path = LUMENTUM_FIXTURES) -> bytes:
    return (root / recorded(url)["file"]).read_bytes()


def acceptance_of(accession: str) -> datetime:
    recent = SUBMISSIONS["filings"]["recent"]
    index = recent["accessionNumber"].index(accession)
    return datetime.fromisoformat(recent["acceptanceDateTime"][index])


# --- the harness: a fresh database, the CLI, one worker pass and the API ---


class Atlas:
    def __init__(self, database_url: str, tmp_path: Path, fixtures: Path) -> None:
        self.database_url = database_url
        self.tmp_path = tmp_path
        self.archive = tmp_path / "archive"
        self.archive.mkdir(exist_ok=True)
        self.fixtures = fixtures
        self.engine = create_engine(database_url)
        self.api = TestClient(create_app(self.settings()))

    def settings(self) -> Settings:
        return Settings.model_validate(
            {
                "database_url": self.database_url,
                "actor": "local-researcher",
                "archive_root": self.archive,
                "themes_config": THEMES,
                "sec_fixtures_dir": self.fixtures,
            }
        )

    def env(self) -> dict[str, str]:
        return {
            "PATH": os.environ["PATH"],
            "HOME": str(self.tmp_path),
            "ATLAS_DATABASE_URL": self.database_url,
            "ATLAS_ACTOR": "local-researcher",
            "ATLAS_ARCHIVE_ROOT": str(self.archive),
            "ATLAS_THEMES_CONFIG": str(THEMES),
            "ATLAS_SEC_FIXTURES_DIR": str(self.fixtures),
        }

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "atlas", *args],
            cwd=self.tmp_path,
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=120,
        )

    def worker_pass(self) -> int:
        return Worker(JobQueue(self.engine), builtin_registry(self.settings())).run_once()

    def ingest(
        self, key: str, company: str = "lumentum", *, cli_worker: bool = False
    ) -> dict[str, Any]:
        """`atlas ingest`, then one worker pass; returns the job as the API shows it."""
        enqueued = self.cli("ingest", "--company", company, "--key", key)
        assert enqueued.returncode == 0, enqueued.stderr
        job_id = json.loads(enqueued.stdout)["id"]
        if cli_worker:
            worker = self.cli("worker", "--once")
            assert worker.returncode == 0, worker.stderr
        else:
            self.worker_pass()
        return self.get(f"/api/v1/jobs/{job_id}")

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def company(self, slug: str = "lumentum") -> dict[str, Any]:
        companies = self.get("/api/v1/companies")["items"]
        return next(company for company in companies if company["slug"] == slug)

    def documents(self) -> dict[str, dict[str, Any]]:
        """The company's Source Documents by canonical URL."""
        page = self.get(f"/api/v1/companies/{self.company()['id']}/sources", limit=100)
        assert page["total"] == len(page["items"])
        return {document["canonical_url"]: document for document in page["items"]}

    def versions(self, url: str) -> list[dict[str, Any]]:
        document = self.documents()[url]
        page = self.get(f"/api/v1/sources/{document['id']}/versions")
        return page["items"]

    def version(self, url: str) -> dict[str, Any]:
        """The only Source Version of a document, in full."""
        versions = self.versions(url)
        assert len(versions) == 1
        return self.get(f"/api/v1/source-versions/{versions[0]['id']}")

    def audit_events(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT actor, action, entity_type, entity_id FROM audit_event ORDER BY id")
            )
            return [dict(row._mapping) for row in rows]  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
def database_url(empty_database_url: str) -> str:
    upgrade(empty_database_url)
    return empty_database_url


@pytest.fixture
def atlas(database_url: str, tmp_path: Path) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path, EDGAR_FIXTURES)
    yield harness
    harness.engine.dispose()


def editable_fixtures(tmp_path: Path) -> Path:
    """A private copy of the EDGAR fixtures that a test may change."""
    root = tmp_path / "edgar"
    shutil.copytree(EDGAR_FIXTURES, root)
    return root


def change_recorded_document(
    root: Path, url: str, old: bytes, new: bytes, last_modified: str
) -> bytes:
    """Change a recorded body as SEC would serve a changed file: new bytes, new Last-Modified."""
    manifest_path = root / "lumentum" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entry = next(entry for entry in manifest["responses"] if entry["url"] == url)
    entry["headers"]["last-modified"] = last_modified
    manifest_path.write_text(json.dumps(manifest, indent=2))
    body = root / "lumentum" / entry["file"]
    original = body.read_bytes()
    assert original.count(old) == 1
    changed = original.replace(old, new)
    body.write_bytes(changed)
    return changed


# --- the Phase 1 gate ---


def test_atlas_ingest_enqueues_a_job_that_one_worker_pass_turns_into_source_versions(
    atlas: Atlas,
) -> None:
    job = atlas.ingest("lumentum-first", cli_worker=True)

    assert job["kind"] == "ingest"
    assert job["payload"]["company"] == "lumentum"
    assert job["status"] == "succeeded", job["failures"]
    company = atlas.company()
    assert company["cik"] == "0001633978"
    assert company["legal_name"] == "Lumentum Holdings Inc."
    assert [
        (s["ticker"], s["exchange_mic"], s["valid_from"], s["valid_to"])
        for s in company["securities"]
    ] == [("LITE", "XNAS", "2015-08-04", None)]
    documents = atlas.documents()
    assert set(documents) == ALL_URLS
    assert {url: documents[url]["accession"] for url in FILING_URLS} == {
        URL_8K: "0001628280-26-055726",
        URL_EX991: "0001628280-26-055726",
        URL_10K: "0001628280-26-057358",
        URL_10Q: "0001628280-26-030777",
    }
    assert documents[URL_FACTS]["accession"] is None
    assert documents[URL_EX991]["document_type"] == "EX-99.1"
    assert documents[URL_EX991]["form_type"] == "8-K"
    assert {d["license_class"] for d in documents.values()} == {"public_regulatory"}
    assert all(len(atlas.versions(url)) == 1 for url in ALL_URLS)
    artifacts = job["artifacts"]
    assert artifacts["company_id"] == company["id"]
    assert artifacts["counts"] == {"new_version": 5, "unchanged": 0, "not_modified": 0}
    assert sorted(artifacts["source_versions"]) == sorted(
        atlas.versions(url)[0]["id"] for url in ALL_URLS
    )


def test_an_unchanged_filing_fetched_twice_yields_exactly_one_source_version(
    atlas: Atlas,
) -> None:
    atlas.ingest("first")
    first_ids = {url: atlas.version(url)["id"] for url in ALL_URLS}

    second = atlas.ingest("second")

    assert second["status"] == "succeeded", second["failures"]
    # Archives documents answer the conditional re-check with 304; companyfacts has no
    # validators, so it is refetched and found unchanged by its hash.
    assert second["artifacts"]["counts"] == {"new_version": 0, "unchanged": 1, "not_modified": 4}
    assert second["artifacts"]["source_versions"] == []
    for url in ALL_URLS:
        version = atlas.version(url)
        assert version["id"] == first_ids[url]
        assert [fetch["outcome"] for fetch in version["fetches"]] == [
            "new_version",
            "unchanged" if url == URL_FACTS else "not_modified",
        ]


def test_a_changed_filing_yields_a_new_source_version_linked_via_supersedes(
    database_url: str, tmp_path: Path
) -> None:
    fixtures = editable_fixtures(tmp_path)
    atlas = Atlas(database_url, tmp_path, fixtures)
    atlas.ingest("before")
    original = atlas.version(URL_8K)
    changed = change_recorded_document(
        fixtures,
        URL_8K,
        b"fourth quarter and full fiscal year",
        b"third quarter",
        "Wed, 12 Aug 2026 09:00:00 GMT",
    )

    job = atlas.ingest("after")

    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["counts"] == {"new_version": 1, "unchanged": 1, "not_modified": 3}
    versions = atlas.versions(URL_8K)
    assert [v["version_number"] for v in versions] == [1, 2]
    first, second = versions
    assert first["id"] == original["id"]
    assert second["supersedes_version_id"] == first["id"]
    assert first["superseded_by_version_id"] == second["id"]
    assert second["superseded_by_version_id"] is None
    assert job["artifacts"]["source_versions"] == [second["id"]]
    detail = atlas.get(f"/api/v1/source-versions/{second['id']}")
    assert detail["raw_sha256"] == hashlib.sha256(changed).hexdigest()
    assert detail["available_at"] == original["available_at"]  # same filing, same acceptance
    raw = atlas.api.get(f"/api/v1/source-versions/{second['id']}/content", params={"kind": "raw"})
    assert raw.content == changed
    parsed = atlas.api.get(
        f"/api/v1/source-versions/{second['id']}/content", params={"kind": "parsed"}
    )
    assert "reported results for its third quarter ended June 27, 2026" in parsed.text
    for url in ALL_URLS - {URL_8K}:
        assert len(atlas.versions(url)) == 1
    atlas.engine.dispose()


def test_a_varying_sec_edge_script_alone_is_not_a_new_source_version(
    database_url: str, tmp_path: Path
) -> None:
    fixtures = editable_fixtures(tmp_path)
    atlas = Atlas(database_url, tmp_path, fixtures)
    atlas.ingest("before")
    original = atlas.version(URL_10K)
    varied = change_recorded_document(
        fixtures,
        URL_10K,
        SEC_EDGE_SCRIPT,
        b'<script type="text/javascript"  src="/ZZotherEdgeToken/',
        "Tue, 18 Aug 2026 09:00:00 GMT",
    )

    job = atlas.ingest("after")

    assert job["status"] == "succeeded", job["failures"]
    assert job["artifacts"]["counts"] == {"new_version": 0, "unchanged": 2, "not_modified": 3}
    version = atlas.version(URL_10K)
    assert version["id"] == original["id"]
    assert version["raw_sha256"] == hashlib.sha256(recorded_bytes(URL_10K)).hexdigest()
    assert version["comparison_rule"] == "sec-edge-script-v1"
    refetch = version["fetches"][-1]
    assert refetch["outcome"] == "unchanged"
    # The exact bytes of that fetch are still hashed and recorded.
    assert refetch["raw_sha256"] == hashlib.sha256(varied).hexdigest()
    assert refetch["raw_sha256"] != version["raw_sha256"]
    assert refetch["comparison_sha256"] == version["comparison_sha256"]
    assert refetch["last_modified"] == "Tue, 18 Aug 2026 09:00:00 GMT"
    raw = atlas.api.get(f"/api/v1/source-versions/{version['id']}/content", params={"kind": "raw"})
    assert raw.content == recorded_bytes(URL_10K)
    atlas.engine.dispose()


def test_original_bytes_are_returned_exactly_and_match_raw_sha256(atlas: Atlas) -> None:
    atlas.ingest("first")

    for url in ALL_URLS:
        version = atlas.version(url)
        response = atlas.api.get(
            f"/api/v1/source-versions/{version['id']}/content", params={"kind": "raw"}
        )

        assert response.status_code == 200
        assert response.content == recorded_bytes(url)
        assert hashlib.sha256(response.content).hexdigest() == version["raw_sha256"]
        assert version["byte_size"] == len(response.content)
        assert response.headers["content-type"] == recorded(url)["headers"]["content-type"]
        assert response.headers["x-content-sha256"] == version["raw_sha256"]
        # Raw source is untrusted: downloaded, never rendered on the app origin.
        assert response.headers["content-disposition"].startswith("attachment")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in response.headers["content-security-policy"]
        assert version["object_uri"] == f"archive://raw/sha256/{version['raw_sha256']}"


def test_available_at_is_the_acceptance_datetime_and_the_clocks_stay_distinct(
    atlas: Atlas,
) -> None:
    started = datetime.now(UTC)
    job = atlas.ingest("first")
    finished = datetime.fromisoformat(job["finished_at"])
    documents = atlas.documents()

    for url in FILING_URLS:
        version = atlas.version(url)
        accepted = acceptance_of(documents[url]["accession"])
        assert datetime.fromisoformat(version["available_at"]) == accepted
        assert version["available_at_basis"] == "sec_acceptance"
        assert version["metadata"]["acceptance_datetime"] == accepted.isoformat()
        assert version["published_at"] is None
        assert version["event_at"] is None
        first_seen = datetime.fromisoformat(version["source_document"]["first_seen_at"])
        fetched = datetime.fromisoformat(version["fetched_at"])
        ingested = datetime.fromisoformat(version["ingested_at"])
        assert accepted < started < first_seen <= fetched <= ingested <= finished
    facts = atlas.version(URL_FACTS)
    assert facts["available_at_basis"] == "observed_discovery"
    assert facts["available_at"] == documents[URL_FACTS]["first_seen_at"]


def test_the_parse_is_deterministic_archived_separately_and_versioned(atlas: Atlas) -> None:
    atlas.ingest("first")

    golden = GOLDEN_PARSES["html-text-v1"]
    for url in FILING_URLS:
        version = atlas.version(url)
        response = atlas.api.get(
            f"/api/v1/source-versions/{version['id']}/content", params={"kind": "parsed"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert version["parse_status"] == "parsed"
        assert version["parser_version"] == "html-text-v1"
        assert hashlib.sha256(response.content).hexdigest() == version["content_sha256"]
        assert version["content_sha256"] == golden[url.rsplit("/", 1)[1]]
        assert (
            version["parsed_object_uri"] == f"archive://parsed/sha256/{version['content_sha256']}"
        )
        assert version["parsed_object_uri"] != version["object_uri"]
    facts = atlas.version(URL_FACTS)
    assert facts["parse_status"] == "not_applicable"
    assert facts["content_sha256"] is None
    missing = atlas.api.get(
        f"/api/v1/source-versions/{facts['id']}/content", params={"kind": "parsed"}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_every_mutation_is_audited_in_one_chain_that_verifies(atlas: Atlas) -> None:
    assert atlas.cli("companies", "seed").returncode == 0
    atlas.ingest("first")
    atlas.ingest("second")

    events = atlas.audit_events()
    company = atlas.company()
    coherent = atlas.company("coherent")
    documents = atlas.documents()
    versions = [atlas.version(url) for url in ALL_URLS]
    fetches = [fetch for version in versions for fetch in version["fetches"]]
    expected = Counter(
        [("company", company["id"]), ("company", coherent["id"])]
        + [("security", security["id"]) for security in company["securities"]]
        + [("source_document", document["id"]) for document in documents.values()]
        + [("source_version", version["id"]) for version in versions]
        + [("fetch_observation", fetch["id"]) for fetch in fetches]
    )

    assert Counter((e["entity_type"], e["entity_id"]) for e in events) == expected
    assert len(fetches) == 10
    assert {e["actor"] for e in events} == {"local-researcher"}
    assert Counter(e["action"] for e in events) == {
        "company.created": 2,
        "security.created": 1,
        "source_document.created": 5,
        "source_version.created": 5,
        "fetch.new_version": 5,
        "fetch.not_modified": 4,
        "fetch.unchanged": 1,
    }
    verify = atlas.cli("audit", "verify")
    assert verify.returncode == 0, verify.stderr
    assert f"{len(events)} events" in verify.stdout


# --- companies from config ---


def test_companies_are_seeded_from_config_idempotently(atlas: Atlas) -> None:
    first = atlas.cli("companies", "seed")
    events_after_first = len(atlas.audit_events())
    second = atlas.cli("companies", "seed")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert len(atlas.audit_events()) == events_after_first == 3
    page = atlas.get("/api/v1/companies")
    assert page["total"] == 2
    assert [(c["slug"], c["cik"]) for c in page["items"]] == [
        ("coherent", "0000820318"),
        ("lumentum", "0001633978"),
    ]
    coherent = atlas.get(f"/api/v1/companies/{atlas.company('coherent')['id']}")
    assert coherent["legal_name"] == "Coherent Corp."
    assert coherent["securities"] == []


def test_ingest_cli_rejects_a_company_that_is_not_configured(atlas: Atlas) -> None:
    result = atlas.cli("ingest", "--company", "nvidia", "--key", "k")

    assert result.returncode == 2
    assert "nvidia" in result.stderr
    assert "lumentum" in result.stderr


def test_a_company_without_fixtures_fails_its_ingest_visibly(atlas: Atlas) -> None:
    job = atlas.ingest("coherent-first", company="coherent")

    assert job["status"] == "failed"
    assert "no recorded EDGAR fixtures for coherent" in job["last_error"]
    assert atlas.get(f"/api/v1/companies/{atlas.company('coherent')['id']}/sources")["total"] == 0


# --- read API errors ---


def test_unknown_ids_are_404_with_the_error_envelope(atlas: Atlas) -> None:
    missing = uuid.uuid4()
    for path in (
        f"/api/v1/companies/{missing}",
        f"/api/v1/companies/{missing}/sources",
        f"/api/v1/sources/{missing}",
        f"/api/v1/sources/{missing}/versions",
        f"/api/v1/source-versions/{missing}",
        f"/api/v1/source-versions/{missing}/content?kind=raw",
    ):
        response = atlas.api.get(path)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "not_found"


def test_content_kind_must_be_raw_or_parsed(atlas: Atlas) -> None:
    atlas.ingest("first")
    version = atlas.version(URL_8K)

    response = atlas.api.get(
        f"/api/v1/source-versions/{version['id']}/content", params={"kind": "html"}
    )

    assert response.status_code == 422


def test_lists_are_paginated(atlas: Atlas) -> None:
    atlas.ingest("first")
    company_id = atlas.company()["id"]

    first = atlas.get(f"/api/v1/companies/{company_id}/sources", limit=2, offset=0)
    rest = atlas.get(f"/api/v1/companies/{company_id}/sources", limit=10, offset=2)

    assert (first["total"], first["limit"], first["offset"]) == (5, 2, 0)
    assert len(first["items"]) == 2
    assert len(rest["items"]) == 3
    assert {d["id"] for d in first["items"]}.isdisjoint(d["id"] for d in rest["items"])


# --- ledger invariants, enforced by the database itself ---


def test_source_versions_cannot_be_changed_or_removed_in_the_database(atlas: Atlas) -> None:
    atlas.ingest("first")
    version = atlas.version(URL_8K)
    other = atlas.version(URL_10K)
    statements = [
        "UPDATE source_version SET raw_sha256 = repeat('0', 64) WHERE id = :id",
        "UPDATE source_version SET available_at = now() WHERE id = :id",
        "UPDATE source_version SET content_sha256 = repeat('0', 64) WHERE id = :id",
        "DELETE FROM source_version WHERE id = :id",
        "UPDATE source_document SET canonical_url = 'https://example.com' "
        "WHERE id = (SELECT source_document_id FROM source_version WHERE id = :id)",
        "DELETE FROM fetch_observation WHERE source_version_id = :id",
        "TRUNCATE source_version CASCADE",
    ]

    for statement in statements:
        with pytest.raises(DBAPIError), atlas.engine.begin() as connection:
            connection.execute(text(statement), {"id": version["id"]})
    with pytest.raises(IntegrityError), atlas.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO source_version (id, source_document_id, version_number, raw_sha256,"
                " comparison_sha256, comparison_rule, object_uri, byte_size, media_type,"
                " parse_status, available_at, available_at_basis, fetched_at,"
                " supersedes_version_id, fetch_status)"
                " SELECT gen_random_uuid(), source_document_id, 2, raw_sha256, comparison_sha256,"
                " comparison_rule, object_uri, byte_size, media_type, 'pending', available_at,"
                " available_at_basis, fetched_at, id, fetch_status"
                " FROM source_version WHERE id = :id"
            ),
            {"id": version["id"]},
        )
    with pytest.raises(DBAPIError, match="previous version of the same document"):
        with atlas.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO source_version (id, source_document_id, version_number,"
                    " raw_sha256, comparison_sha256, comparison_rule, object_uri, byte_size,"
                    " media_type, parse_status, available_at, available_at_basis, fetched_at,"
                    " supersedes_version_id, fetch_status)"
                    " SELECT gen_random_uuid(), source_document_id, 2, repeat('1', 64),"
                    " repeat('1', 64), comparison_rule, object_uri, byte_size, media_type,"
                    " 'pending', available_at, available_at_basis, fetched_at, :other,"
                    " fetch_status FROM source_version WHERE id = :id"
                ),
                {"id": version["id"], "other": other["id"]},
            )
    with pytest.raises(IntegrityError), atlas.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO source_version (id, source_document_id, version_number, raw_sha256,"
                " comparison_sha256, comparison_rule, object_uri, byte_size, media_type,"
                " parse_status, fetched_at, fetch_status)"
                " SELECT gen_random_uuid(), source_document_id, 9, repeat('2', 64),"
                " repeat('2', 64), comparison_rule, object_uri, byte_size, media_type,"
                " 'pending', fetched_at, fetch_status FROM source_version WHERE id = :id"
            ),
            {"id": version["id"]},
        )
    assert atlas.version(URL_8K) == version


def test_securities_cannot_overlap_for_the_same_listing(atlas: Atlas) -> None:
    atlas.cli("companies", "seed")
    lumentum, coherent = atlas.company(), atlas.company("coherent")

    with pytest.raises(IntegrityError), atlas.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO security (id, company_id, ticker, exchange_mic, instrument_type,"
                " currency, valid_from) VALUES (gen_random_uuid(), :company, 'LITE', 'XNAS',"
                " 'common', 'USD', '2020-01-01')"
            ),
            {"company": coherent["id"]},
        )
    assert len(atlas.get(f"/api/v1/companies/{lumentum['id']}")["securities"]) == 1
