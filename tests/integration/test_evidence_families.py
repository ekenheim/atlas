"""The Evidence Family gate: syndicated copies of one announcement count as one witness.

Seam: `atlas ingest` (CLI) enqueues, one worker pass records the Source Versions, and the
families are observed through `/api/v1`, the audit trail, and `atlas ledger
assign-families` for versions recorded before this rule. The fixtures
(tests/fixtures/syndication/lumentum, see its manifest) hold the Q4 FY2026 release three
times: as recorded, re-filed byte for byte in an 8-K/A, and as a wire-service copy (a
near duplicate); plus an unrelated 10-Q.
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from atlas.api.app import create_app
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.settings import Settings
from tests.harness import REPO, THEMES, make_settings

SYNDICATION = REPO / "tests" / "fixtures" / "syndication"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data/1633978"
RELEASE = f"{ARCHIVES}/000162828026055726/lite_ex991xq4fy26.htm"
REFILED = f"{ARCHIVES}/000162828026900001/lite_ex991xq4fy26.htm"
WIRE_COPY = f"{ARCHIVES}/000162828026900002/lite_ex991xq4fy26wire.htm"
TEN_Q = f"{ARCHIVES}/000162828026030777/lite-20260328.htm"
FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001633978.json"
COPIES = {RELEASE, REFILED, WIRE_COPY}
THRESHOLD = 3  # spec Phase 3: SimHash Hamming ≤ 3
RULE = "simhash64-w3-blake2b-v1"


class Atlas:
    def __init__(self, database_url: str, tmp_path: Path, **env: str) -> None:
        self.database_url = database_url
        self.tmp_path = tmp_path
        self.archive = tmp_path / "archive"
        self.archive.mkdir(exist_ok=True)
        self.extra_env = env
        self.engine = create_engine(database_url)
        self.api = TestClient(create_app(self.settings()))

    def settings(self) -> Settings:
        return make_settings(
            self.archive,
            database_url=self.database_url,
            themes_config=THEMES,
            sec_fixtures_dir=SYNDICATION,
            **{k.removeprefix("ATLAS_").lower(): v for k, v in self.extra_env.items()},
        )

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.tmp_path),
            "ATLAS_DATABASE_URL": self.database_url,
            "ATLAS_ACTOR": "local-researcher",
            "ATLAS_ARCHIVE_ROOT": str(self.archive),
            "ATLAS_THEMES_CONFIG": str(THEMES),
            "ATLAS_SEC_FIXTURES_DIR": str(SYNDICATION),
            **self.extra_env,
        }
        return subprocess.run(
            [sys.executable, "-m", "atlas", *args],
            cwd=self.tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def ingest(self, key: str) -> None:
        enqueued = self.cli("ingest", "--company", "lumentum", "--key", key, "--all-history")
        assert enqueued.returncode == 0, enqueued.stderr
        job_id = json.loads(enqueued.stdout)["id"]
        Worker(JobQueue(self.engine), builtin_registry(self.settings())).run_once()
        job = self.get(f"/api/v1/jobs/{job_id}")
        assert job["status"] == "succeeded", job

    def get(self, path: str) -> Any:
        response = self.api.get(path, params={"limit": 100})
        assert response.status_code == 200, response.text
        return response.json()

    def versions(self) -> dict[str, dict[str, Any]]:
        """Each document's only Source Version, in full, by canonical URL."""
        company = next(c for c in self.get("/api/v1/companies")["items"] if c["slug"] == "lumentum")
        versions: dict[str, dict[str, Any]] = {}
        for document in self.get(f"/api/v1/companies/{company['id']}/sources")["items"]:
            (summary,) = self.get(f"/api/v1/sources/{document['id']}/versions")["items"]
            detail = self.get(f"/api/v1/source-versions/{summary['id']}")
            assert summary["evidence_family_id"] == (
                detail["evidence_family"] and detail["evidence_family"]["evidence_family_id"]
            )
            versions[document["canonical_url"]] = detail
        return versions

    def audit_actions(self) -> list[str]:
        with self.engine.connect() as connection:
            return list(
                connection.execute(text("SELECT action FROM audit_event ORDER BY id")).scalars()
            )


@pytest.fixture
def atlas(database_url: str, tmp_path: Path) -> Iterator[Atlas]:
    harness = Atlas(database_url, tmp_path)
    yield harness
    harness.engine.dispose()


def family_of(version: dict[str, Any]) -> str:
    return version["evidence_family"]["evidence_family_id"]


def test_syndicated_copies_of_one_announcement_are_one_evidence_family(atlas: Atlas) -> None:
    atlas.ingest("syndication")

    versions = atlas.versions()
    assert set(versions) == COPIES | {TEN_Q, FACTS}
    # The re-filed copy is an exact duplicate; the wire copy is not.
    assert versions[RELEASE]["content_sha256"] == versions[REFILED]["content_sha256"]
    assert versions[WIRE_COPY]["content_sha256"] != versions[RELEASE]["content_sha256"]

    # One witness: the three copies share a family; the 10-Q has its own.
    parsed = COPIES | {TEN_Q}
    assert len({family_of(versions[url]) for url in COPIES}) == 1
    assert len({family_of(versions[url]) for url in parsed}) == 2
    assert versions[FACTS]["parse_status"] == "not_applicable"
    assert versions[FACTS]["evidence_family"] is None

    family = atlas.get(f"/api/v1/evidence-families/{family_of(versions[RELEASE])}")
    assert family["simhash_rule"] == RULE
    assert family["max_hamming_distance"] == THRESHOLD
    assert family["member_count"] == 3
    assert {member["canonical_url"] for member in family["members"]} == COPIES
    by_version = {member["source_version_id"]: member for member in family["members"]}
    for url in COPIES:
        membership = versions[url]["evidence_family"]
        member = by_version[versions[url]["id"]]
        assert membership["member_count"] == 3
        assert membership["max_hamming_distance"] == THRESHOLD
        assert membership["simhash_rule"] == RULE
        assert membership["match"] == member["match"]
        assert membership["simhash"] == member["simhash"]
        assert len(membership["simhash"]) == 16
    # Whatever order the copies arrived in: the first founded the family, the exact copy
    # matched by content hash, the reworded one by SimHash within the threshold.
    founder, *joined = family["members"]
    assert founder["match"] == "founder"
    assert founder["matched_source_version_id"] is None
    assert founder["hamming_distance"] is None
    assert sorted(member["match"] for member in joined) == ["content_hash", "simhash"]
    for member in joined:
        matched = next(
            url for url in COPIES if versions[url]["id"] == member["matched_source_version_id"]
        )
        this = next(url for url in COPIES if versions[url]["id"] == member["source_version_id"])
        if member["match"] == "content_hash":
            assert versions[matched]["content_sha256"] == versions[this]["content_sha256"]
            assert member["hamming_distance"] == 0
        else:
            assert versions[matched]["content_sha256"] != versions[this]["content_sha256"]
            assert 0 < member["hamming_distance"] <= THRESHOLD

    ten_q = versions[TEN_Q]["evidence_family"]
    assert ten_q["match"] == "founder"
    assert ten_q["member_count"] == 1

    # Audited; and a second ingest of the same bytes adds nothing.
    actions = atlas.audit_actions()
    assert actions.count("evidence_family.created") == 2
    assert actions.count("evidence_family.member_added") == 4
    atlas.ingest("syndication-again")
    assert atlas.audit_actions().count("evidence_family.member_added") == 4
    assert atlas.cli("audit", "verify").returncode == 0


def test_a_family_is_append_only_and_an_unknown_one_is_404(atlas: Atlas) -> None:
    atlas.ingest("syndication")

    for statement in (
        "UPDATE evidence_family_member SET hamming_distance = 1",
        "DELETE FROM evidence_family_member",
        "TRUNCATE evidence_family_member CASCADE",
        "UPDATE evidence_family SET max_hamming_distance = 64",
        "DELETE FROM evidence_family",
    ):
        with pytest.raises(DBAPIError, match="immutable"), atlas.engine.begin() as connection:
            connection.execute(text(statement))
    response = atlas.api.get("/api/v1/evidence-families/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_each_family_keeps_the_threshold_it_was_founded_with(
    database_url: str, tmp_path: Path
) -> None:
    atlas = Atlas(database_url, tmp_path, ATLAS_EVIDENCE_FAMILY_MAX_HAMMING_DISTANCE="0")
    try:
        atlas.ingest("exact-only")
        versions = atlas.versions()
    finally:
        atlas.engine.dispose()

    # At threshold 0 the wire copy is not a near duplicate; the exact copies still group.
    assert family_of(versions[RELEASE]) == family_of(versions[REFILED])
    assert family_of(versions[WIRE_COPY]) != family_of(versions[RELEASE])
    for url in COPIES | {TEN_Q}:
        assert versions[url]["evidence_family"]["max_hamming_distance"] == 0


def insert_unassigned_copy(atlas: Atlas, url: str) -> str:
    """A copy of the document's version as recorded before Evidence Families: a new Source
    Document (its own URL) whose version has the same parse but no family."""
    version = atlas.versions()[url]
    with atlas.engine.begin() as connection:
        document_id = connection.execute(
            text(
                "INSERT INTO source_document (id, company_id, provider, canonical_url,"
                " origin_url, accession, form_type, document_type, source_type, title,"
                " publisher, source_tier, license_class, first_seen_at)"
                " SELECT gen_random_uuid(), company_id, provider, canonical_url || '#before',"
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
                    " media_type, content_sha256, parsed_object_uri, parser_version,"
                    " parse_status, available_at, available_at_basis, fetched_at,"
                    " fetch_status, metadata)"
                    " SELECT gen_random_uuid(), :document, 1, raw_sha256, comparison_sha256,"
                    " comparison_rule, object_uri, byte_size, media_type, content_sha256,"
                    " parsed_object_uri, parser_version, parse_status, available_at,"
                    " available_at_basis, fetched_at, fetch_status, metadata"
                    " FROM source_version WHERE id = :id RETURNING id"
                ),
                {"document": document_id, "id": version["id"]},
            ).scalar_one()
        )


def test_assign_families_backfills_versions_recorded_before_the_rule(atlas: Atlas) -> None:
    atlas.ingest("syndication")
    earlier = insert_unassigned_copy(atlas, TEN_Q)
    assert atlas.get(f"/api/v1/source-versions/{earlier}")["evidence_family"] is None

    backfilled = atlas.cli("ledger", "assign-families")

    assert backfilled.returncode == 0, backfilled.stderr
    assert json.loads(backfilled.stdout) == {"assigned": [earlier], "families_created": 0}
    membership = atlas.get(f"/api/v1/source-versions/{earlier}")["evidence_family"]
    assert membership["evidence_family_id"] == family_of(atlas.versions()[TEN_Q])
    assert membership["match"] == "content_hash"
    assert membership["member_count"] == 2
    # Idempotent.
    again = atlas.cli("ledger", "assign-families")
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout) == {"assigned": [], "families_created": 0}
    assert atlas.audit_actions().count("evidence_family.member_added") == 5
