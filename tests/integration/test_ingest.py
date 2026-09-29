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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from atlas.api.app import create_app
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.settings import Settings
from tests.harness import EDGAR_FIXTURES, REPO, THEMES, Metrics, make_settings, scrape_metrics

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


def labels(**pairs: str) -> frozenset[tuple[str, str]]:
    return frozenset(pairs.items())


def acceptance_of(accession: str) -> datetime:
    recent = SUBMISSIONS["filings"]["recent"]
    index = recent["accessionNumber"].index(accession)
    return datetime.fromisoformat(recent["acceptanceDateTime"][index])


# --- the harness: a fresh database, the CLI, one worker pass and the API ---


class Atlas:
    def __init__(
        self,
        database_url: str,
        tmp_path: Path,
        fixtures: Path,
        eight_k_items: str = "*",
        exhibits_only_items: str = "",
    ) -> None:
        # By default no 8-K selection: ledger mechanics use every recorded document.
        self.eight_k_items = eight_k_items
        self.exhibits_only_items = exhibits_only_items
        self.database_url = database_url
        self.tmp_path = tmp_path
        self.archive = tmp_path / "archive"
        self.archive.mkdir(exist_ok=True)
        self.fixtures = fixtures
        self.engine = create_engine(database_url)
        self.api = TestClient(create_app(self.settings()))

    def settings(self) -> Settings:
        return make_settings(
            self.archive,
            database_url=self.database_url,
            themes_config=THEMES,
            sec_fixtures_dir=self.fixtures,
            sec_8k_items=self.eight_k_items,
            sec_8k_exhibits_only_items=self.exhibits_only_items,
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
            "ATLAS_SEC_8K_ITEMS": self.eight_k_items,
            "ATLAS_SEC_8K_EXHIBITS_ONLY_ITEMS": self.exhibits_only_items,
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

    def metrics(self) -> Metrics:
        return scrape_metrics(self.api)

    def audit_events(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("SELECT actor, action, entity_type, entity_id FROM audit_event ORDER BY id")
            )
            return [dict(row._mapping) for row in rows]  # pyright: ignore[reportPrivateUsage]


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
    # The revision's bytes weren't public at the filing's acceptance: it is available from
    # when Atlas observed it (spec story 31), while the first version keeps its acceptance.
    assert original["available_at_basis"] == "sec_acceptance"
    assert detail["available_at_basis"] == "observed_revision"
    assert detail["available_at"] == detail["fetched_at"]
    assert datetime.fromisoformat(detail["available_at"]) > datetime.fromisoformat(
        original["fetched_at"]
    )
    assert detail["metadata"]["acceptance_datetime"] == original["metadata"]["acceptance_datetime"]
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


# When EDGAR disseminated each fixture filing (docs/decisions.md): the 10-K (Monday 16:03 EDT)
# and the 8-K (Tuesday 16:24 EDT) within the window, at acceptance; the 10-Q, accepted Tuesday
# 2026-05-05 at 18:03 EDT, at 06:00 EDT on Wednesday, its filing date.
DISSEMINATED = {
    URL_10K: (datetime(2026, 8, 17, 20, 3, 17, tzinfo=UTC), "sec_acceptance"),
    URL_8K: (datetime(2026, 8, 11, 20, 24, 11, tzinfo=UTC), "sec_acceptance"),
    URL_EX991: (datetime(2026, 8, 11, 20, 24, 11, tzinfo=UTC), "sec_acceptance"),
    URL_10Q: (datetime(2026, 5, 6, 10, 0, tzinfo=UTC), "sec_dissemination"),
}


def test_available_at_is_when_edgar_disseminated_and_the_clocks_stay_distinct(
    atlas: Atlas,
) -> None:
    started = datetime.now(UTC)
    job = atlas.ingest("first")
    finished = datetime.fromisoformat(job["finished_at"])
    documents = atlas.documents()

    for url in FILING_URLS:
        version = atlas.version(url)
        accepted = acceptance_of(documents[url]["accession"])
        available, basis = DISSEMINATED[url]
        assert datetime.fromisoformat(version["available_at"]) == available
        assert version["available_at_basis"] == basis
        # Nothing corrected: what the ledger shows is what the version recorded.
        assert version["recorded_available_at"] == version["available_at"]
        assert version["recorded_available_at_basis"] == basis
        assert version["metadata"]["acceptance_datetime"] == accepted.isoformat()
        assert version["published_at"] is None
        assert version["event_at"] is None
        first_seen = datetime.fromisoformat(version["source_document"]["first_seen_at"])
        fetched = datetime.fromisoformat(version["fetched_at"])
        ingested = datetime.fromisoformat(version["ingested_at"])
        assert accepted <= available < started < first_seen <= fetched <= ingested <= finished
    facts = atlas.version(URL_FACTS)
    assert facts["available_at_basis"] == "observed_discovery"
    assert facts["available_at"] == documents[URL_FACTS]["first_seen_at"]


def insert_phase_1_version(atlas: Atlas, url: str) -> str:
    """A copy of the document's version as Phase 1 recorded it: available at acceptance.

    It is a new Source Document (its own URL), since existing rows can't be changed."""
    version = atlas.version(url)
    accepted = version["metadata"]["acceptance_datetime"]
    with atlas.engine.begin() as connection:
        document_id = connection.execute(
            text(
                "INSERT INTO source_document (id, company_id, provider, canonical_url,"
                " origin_url, accession, form_type, document_type, source_type, title,"
                " publisher, source_tier, license_class, first_seen_at)"
                " SELECT gen_random_uuid(), company_id, provider, canonical_url || '#phase-1',"
                " origin_url, accession, form_type, document_type, source_type, title,"
                " publisher, source_tier, license_class, first_seen_at"
                " FROM source_document WHERE id = :document RETURNING id"
            ),
            {"document": version["source_document"]["id"]},
        ).scalar_one()
        return str(
            connection.execute(
                text(
                    "INSERT INTO source_version (id, source_document_id, version_number,"
                    " raw_sha256, comparison_sha256, comparison_rule, object_uri, byte_size,"
                    " media_type, parse_status, available_at, available_at_basis, fetched_at,"
                    " fetch_status, metadata)"
                    " SELECT gen_random_uuid(), :document, 1, raw_sha256, comparison_sha256,"
                    " comparison_rule, object_uri, byte_size, media_type, 'not_applicable',"
                    " CAST(:accepted AS timestamptz), 'sec_acceptance', fetched_at,"
                    " fetch_status, metadata FROM source_version WHERE id = :id RETURNING id"
                ),
                {"document": document_id, "accepted": accepted, "id": version["id"]},
            ).scalar_one()
        )


def test_phase_1_versions_are_corrected_by_a_recorded_correction_never_by_an_edit(
    atlas: Atlas,
) -> None:
    atlas.ingest("first")
    held = insert_phase_1_version(atlas, URL_10Q)  # accepted after hours
    in_window = insert_phase_1_version(atlas, URL_10K)
    current = atlas.version(URL_10Q)["id"]  # already recorded as sec_dissemination
    stored = "SELECT available_at, available_at_basis, metadata FROM source_version WHERE id = :id"
    with atlas.engine.connect() as connection:
        before = connection.execute(text(stored), {"id": held}).one()

    corrected = atlas.cli("ledger", "correct-availability")

    assert corrected.returncode == 0, corrected.stderr
    summary = json.loads(corrected.stdout)
    assert summary["corrected"] == [held]
    assert summary["out_of_calendar"] == []
    version = atlas.get(f"/api/v1/source-versions/{held}")
    accepted = acceptance_of(version["metadata"]["accession_number"])
    assert datetime.fromisoformat(version["available_at"]) == DISSEMINATED[URL_10Q][0]
    assert version["available_at_basis"] == "sec_dissemination"
    assert datetime.fromisoformat(version["recorded_available_at"]) == accepted
    assert version["recorded_available_at_basis"] == "sec_acceptance"
    assert version["metadata"]["acceptance_datetime"] == accepted.isoformat()
    history = atlas.get(f"/api/v1/sources/{version['source_document']['id']}/versions")
    assert history["items"][0]["available_at"] == version["available_at"]
    # The version row itself is untouched.
    with atlas.engine.connect() as connection:
        assert connection.execute(text(stored), {"id": held}).one() == before
    # Within the window, or already right: nothing to correct.
    unchanged = atlas.get(f"/api/v1/source-versions/{in_window}")
    assert unchanged["available_at_basis"] == "sec_acceptance"
    assert unchanged["available_at"] == unchanged["recorded_available_at"]
    assert atlas.get(f"/api/v1/source-versions/{current}")["recorded_available_at_basis"] == (
        "sec_dissemination"
    )
    # Audited, idempotent, and the correction itself is append-only.
    events = [
        e for e in atlas.audit_events() if e["action"] == "source_version.availability_corrected"
    ]
    assert [e["entity_id"] for e in events] == [held]
    again = atlas.cli("ledger", "correct-availability")
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)["corrected"] == []
    for statement in (
        "UPDATE source_version_availability_correction SET available_at = now()",
        "DELETE FROM source_version_availability_correction",
        "TRUNCATE source_version_availability_correction",
    ):
        with pytest.raises(DBAPIError), atlas.engine.begin() as connection:
            connection.execute(text(statement))
    # A correction can only make a version later, never earlier.
    with pytest.raises(DBAPIError, match="later"), atlas.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO source_version_availability_correction (id, source_version_id,"
                " available_at, available_at_basis, reason)"
                " VALUES (gen_random_uuid(), :id, '2000-01-01', 'sec_dissemination', 'test')"
            ),
            {"id": in_window},
        )


def test_the_parse_is_deterministic_archived_separately_and_versioned(atlas: Atlas) -> None:
    atlas.ingest("first")

    golden = GOLDEN_PARSES["text-v2"]
    for url in FILING_URLS:
        version = atlas.version(url)
        response = atlas.api.get(
            f"/api/v1/source-versions/{version['id']}/content", params={"kind": "parsed"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert version["parse_status"] == "parsed"
        assert version["parser_version"] == "text-v2"
        assert version["language"] == "en"  # EDGAR filings are in English (Reg. S-T 306)
        assert version["page_anchors"] is None  # HTML has no pages
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
    jobs = [atlas.ingest("first"), atlas.ingest("second")]

    events = atlas.audit_events()
    company = atlas.company()
    universe = atlas.get("/api/v1/companies", limit=100)["items"]  # the 12 seeded companies
    documents = atlas.documents()
    versions = [atlas.version(url) for url in ALL_URLS]
    fetches = [fetch for version in versions for fetch in version["fetches"]]
    # Each parsed version (the four filing documents; not companyfacts) joins an Evidence
    # Family, here each its own: none of them duplicates another.
    families = [version["evidence_family"] for version in versions if version["evidence_family"]]
    assert len(families) == len(FILING_URLS)
    assert {family["match"] for family in families} == {"founder"}
    expected = Counter(
        [("company", seeded["id"]) for seeded in universe]
        + [("security", security["id"]) for security in company["securities"]]
        + [("source_document", document["id"]) for document in documents.values()]
        + [("source_version", version["id"]) for version in versions]
        + [("fetch_observation", fetch["id"]) for fetch in fetches]
        + [("job", job["id"]) for job in jobs]
        + [("evidence_family", family["evidence_family_id"]) for family in families]
        + [
            ("source_version", url_version["id"])
            for url_version in versions
            if url_version["evidence_family"]
        ]
        # The companyfacts version is normalized once (atlas.financials; ticket 18).
        + [("financial_normalization", jobs[0]["artifacts"]["financial_normalization"]["id"])]
    )

    assert Counter((e["entity_type"], e["entity_id"]) for e in events) == expected
    assert len(fetches) == 10
    assert {e["actor"] for e in events} == {"local-researcher"}
    assert Counter(e["action"] for e in events) == {
        "company.created": 12,
        "security.created": 1,
        "source_document.created": 5,
        "source_version.created": 5,
        "fetch.new_version": 5,
        "fetch.not_modified": 4,
        "fetch.unchanged": 1,
        "job.enqueued": 2,  # by `atlas ingest`; running them is the jobs' own history
        "evidence_family.created": 4,
        "evidence_family.member_added": 4,
        "financial_normalization.created": 1,
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
    # The photonics universe's 12 companies plus Lumentum's security (test_universe.py
    # covers the rest of the universe).
    assert len(atlas.audit_events()) == events_after_first == 13
    page = atlas.get("/api/v1/companies", limit=100)
    assert page["total"] == 12
    assert [
        (c["slug"], c["cik"]) for c in page["items"] if c["slug"] in ("coherent", "lumentum")
    ] == [
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


def test_a_company_without_fixtures_fails_its_ingest_visibly(
    database_url: str, tmp_path: Path
) -> None:
    fixtures = editable_fixtures(tmp_path)
    shutil.rmtree(fixtures / "coherent")
    atlas = Atlas(database_url, tmp_path, fixtures)

    job = atlas.ingest("coherent-first", company="coherent")

    assert job["status"] == "failed"
    assert "no recorded EDGAR fixtures for coherent" in job["last_error"]
    assert atlas.get(f"/api/v1/companies/{atlas.company('coherent')['id']}/sources")["total"] == 0
    atlas.engine.dispose()


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


# --- metrics (spec story 8) ---


def throttle_once(root: Path, url: str) -> None:
    """SEC answers the first request for `url` with a 429 (Retry-After: 0), then as recorded:
    a URL listed twice in the manifest is replayed in order."""
    manifest_path = root / "lumentum" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    throttled = root / "lumentum" / "throttled.html"
    throttled.write_text("<html><body>Request Rate Threshold Exceeded</body></html>")
    entry = {"url": url, "file": "throttled.html", "status": 429, "headers": {"retry-after": "0"}}
    index = next(i for i, e in enumerate(manifest["responses"]) if e["url"] == url)
    manifest["responses"].insert(index, entry)
    manifest_path.write_text(json.dumps(manifest, indent=2))


def test_metrics_count_fetches_parses_retries_and_archive_writes(
    database_url: str, tmp_path: Path
) -> None:
    fixtures = editable_fixtures(tmp_path)
    throttle_once(fixtures, URL_8K)
    shutil.rmtree(fixtures / "coherent")
    atlas = Atlas(database_url, tmp_path, fixtures)
    empty = atlas.metrics()
    for outcome in ("new_version", "unchanged", "not_modified"):
        assert empty[("atlas_fetches_total", labels(outcome=outcome))] == 0
    for status in ("parsed", "incomplete", "failed", "unsupported", "not_applicable"):
        assert empty[("atlas_parses_total", labels(status=status))] == 0
    assert empty[("atlas_archive_writes_total", labels(namespace="raw"))] == 0
    assert empty[("atlas_archive_writes_total", labels(namespace="parsed"))] == 0
    assert empty[("atlas_fetch_retries_total", labels())] == 0

    atlas.ingest("first")

    first = atlas.metrics()
    versions = [atlas.version(url) for url in ALL_URLS]
    assert first[("atlas_fetches_total", labels(outcome="new_version"))] == len(ALL_URLS)
    parsed = sum(v["parse_status"] == "parsed" for v in versions)
    assert parsed == len(FILING_URLS)
    assert first[("atlas_parses_total", labels(status="parsed"))] == parsed
    assert first[("atlas_parses_total", labels(status="not_applicable"))] == 1  # companyfacts
    assert first[("atlas_archive_writes_total", labels(namespace="raw"))] == len(ALL_URLS)
    assert first[("atlas_archive_writes_total", labels(namespace="parsed"))] == parsed
    assert first[("atlas_fetch_retries_total", labels())] == 1  # the 8-K's 429
    assert atlas.version(URL_8K)["fetches"][0]["attempts"] == 2

    atlas.ingest("second")

    second = atlas.metrics()
    assert second[("atlas_fetches_total", labels(outcome="new_version"))] == len(ALL_URLS)
    assert second[("atlas_fetches_total", labels(outcome="not_modified"))] == len(FILING_URLS)
    assert second[("atlas_fetches_total", labels(outcome="unchanged"))] == 1
    assert second[("atlas_archive_writes_total", labels(namespace="raw"))] == len(ALL_URLS)
    assert second[("atlas_fetch_retries_total", labels())] == 2  # throttled again, then 304

    # A job's failed attempts that were retried, and its final failure.
    failed = atlas.ingest("coherent", company="coherent")
    assert (failed["status"], failed["attempts"]) == ("failed", 3)
    last = atlas.metrics()
    assert last[("atlas_job_retries_total", labels(kind="ingest"))] == 2
    assert last[("atlas_jobs_failed_total", labels(kind="ingest"))] == 1
    atlas.engine.dispose()


def test_ingest_since_fetches_only_filings_accepted_after_that_date(atlas: Atlas) -> None:
    enqueued = atlas.cli(
        "ingest", "--company", "lumentum", "--key", "since", "--since", "2026-06-01"
    )
    assert enqueued.returncode == 0, enqueued.stderr
    atlas.worker_pass()

    forms = sorted({doc["form_type"] for doc in atlas.documents().values() if doc["form_type"]})

    # The fixture's 10-K (2026-08-17) and 8-K (2026-08-11) are inside; the 10-Q (2026-05-05) is not.
    assert "10-Q" not in forms
    assert {"10-K", "8-K"} <= set(forms)


def test_ingest_defaults_to_a_rolling_lookback_from_settings(atlas: Atlas) -> None:
    enqueued = atlas.cli("ingest", "--company", "lumentum", "--key", "lookback")
    assert enqueued.returncode == 0, enqueued.stderr

    payload = json.loads(enqueued.stdout)["payload"]

    since = datetime.fromisoformat(payload["since"])
    expected = datetime.now(UTC) - timedelta(days=730)  # the default ATLAS_INGEST_LOOKBACK_DAYS
    assert abs((since - expected).total_seconds()) < 120


def test_ingest_all_history_sets_no_lookback(atlas: Atlas) -> None:
    enqueued = atlas.cli("ingest", "--company", "lumentum", "--key", "all", "--all-history")
    assert enqueued.returncode == 0, enqueued.stderr

    assert "since" not in json.loads(enqueued.stdout)["payload"]


def test_by_default_only_the_press_release_exhibit_of_a_results_8k_is_ingested(
    database_url: str, tmp_path: Path
) -> None:
    defaults = Settings.model_fields
    atlas = Atlas(
        database_url,
        tmp_path,
        EDGAR_FIXTURES,
        eight_k_items=defaults["sec_8k_items"].default,
        exhibits_only_items=defaults["sec_8k_exhibits_only_items"].default,
    )

    atlas.ingest("default-selection")

    documents = atlas.documents()
    # The fixture 8-K is items 2.02,9.01: its earnings release is kept, its cover is not.
    assert URL_EX991 in documents
    assert URL_8K not in documents
    assert {URL_10K, URL_10Q} <= set(documents)
