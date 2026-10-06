"""Every parsed Source Version reaches Memory, and a gap shows (pilot-review ticket 22).

On production (0.4.5, 2026-10-06) 89 English parsed versions were never offered to Memory (an
ingest cut short by `--max-retains`) and 9 had failed triage, and nothing showed it: memory
health counted recorded sections only and the night's reconciliation was clean. Now health
counts **versions** (`versions`), the reconciliation reports `version_not_in_memory`, the
gauge `atlas_versions_not_in_memory{company,reason}` counts them and `atlas memory backfill`
takes them.

Seams: the `atlas` CLI (`companies seed`, `memory reconcile`, `memory backfill`), single
worker passes, `/api/v1/memory/health`, `/api/v1/memory/reconciliations`, `/api/v1/jobs` and
`/metrics`. Source Versions, their triage decisions, memory documents and jobs are arranged in
the database (the ledger's rows with archive URIs that are never read: nothing here reads a
document), the way the backfill's tests arrange an old profile; Hindsight is the recorded fake.
"""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from atlas.api.app import create_app
from atlas.jobs import JobQueue
from atlas.retention.context import RETAIN_PROFILE
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import BANK, Atlas, Clock, Metrics, scrape_metrics

SHA = "a" * 64
NOW = datetime.now(UTC).replace(microsecond=0)


class Coverage(Atlas):
    def __init__(self, database_url: str, tmp_path: Path, hindsight: str, clock: Clock) -> None:
        super().__init__(
            database_url,
            tmp_path,
            hindsight,
            backfill_window="",
            mental_model_refresh_at="",
            consolidate_at="",
            reconcile_at="",
        )
        self.clock = clock
        self.api = TestClient(create_app(self.settings(), clock=clock))
        self.counter = 0

    def sql(self, statement: str, **params: Any) -> Any:
        with self.engine.begin() as connection:
            return connection.execute(text(statement), params)

    def add_version(
        self,
        company: str,
        title: str,
        *,
        language: str = "en",
        parse_status: str = "parsed",
        days_ago: int = 1,
    ) -> str:
        """A Source Version of the company's, with the ledger's rows only."""
        self.counter += 1
        document, version = uuid.uuid4(), uuid.uuid4()
        parsed = parse_status == "parsed"
        url = f"https://example.com/{self.counter}"
        available = NOW - timedelta(days=days_ago)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO source_document (id, company_id, provider, canonical_url,"
                    " origin_url, source_type, title, publisher, source_tier, license_class,"
                    " first_seen_at) VALUES (:id, (SELECT id FROM company WHERE slug = :slug),"
                    " 'sec', :url, :url, 'filing', :title, 'SEC', 'A', 'public_regulatory',"
                    " :at)"
                ),
                {"id": document, "slug": company, "url": url, "title": title, "at": available},
            )
            connection.execute(
                text(
                    "INSERT INTO source_version (id, source_document_id, version_number,"
                    " raw_sha256, comparison_sha256, comparison_rule, object_uri, byte_size,"
                    " media_type, content_sha256, parsed_object_uri, parser_version,"
                    " parse_status, language, available_at, available_at_basis, fetched_at,"
                    " fetch_status) VALUES (:id, :document, 1, :sha, :sha, 'none',"
                    " :raw, 10, 'text/html', :content, :parsed_uri, :parser, :status,"
                    " :language, :at, 'sec_acceptance', :at, 'ok')"
                ),
                {
                    "id": version,
                    "document": document,
                    "sha": f"{self.counter:064x}",
                    "raw": f"archive://raw/sha256/{SHA}",
                    "content": SHA if parsed else None,
                    "parsed_uri": f"archive://parsed/sha256/{SHA}" if parsed else None,
                    "parser": "text-v3" if parsed else None,
                    "status": parse_status,
                    "language": language,
                    "at": available,
                },
            )
        return str(version)

    def supersede(self, version: str) -> str:
        """A later version of the same document (a changed filing), which supersedes it."""
        return str(
            self.sql(
                "INSERT INTO source_version (id, source_document_id, version_number, raw_sha256,"
                " comparison_sha256, comparison_rule, object_uri, byte_size, media_type,"
                " content_sha256, parsed_object_uri, parser_version, parse_status, language,"
                " available_at, available_at_basis, fetched_at, fetch_status,"
                " supersedes_version_id)"
                " SELECT gen_random_uuid(), source_document_id, version_number + 1, :sha, :sha,"
                " comparison_rule, object_uri, byte_size, media_type, content_sha256,"
                " parsed_object_uri, parser_version, parse_status, language, now(),"
                " available_at_basis, now(), fetch_status, id"
                " FROM source_version WHERE id = :id RETURNING id",
                id=version,
                sha=f"{uuid.uuid4().int:064x}"[-64:],
            ).scalar_one()
        )

    def memory_document(self, version: str, state: str = "completed") -> None:
        """A section of the version in the bank. For the reconciliation, `failed`: a completed
        one would be missing from the (empty) fake Hindsight, a difference of another kind."""
        self.sql(
            "INSERT INTO memory_document (id, source_version_id, section_anchor, char_start,"
            " char_end, sectioner_version, hindsight_document_id, bank_id, retain_state,"
            " fact_count, error, error_class, retain_profile, template_version)"
            " VALUES (:id, :version, 'cover', 0, 10, 'v1',"
            " :document, :bank, :state, CASE WHEN :state = 'completed' THEN 3 END,"
            " CASE WHEN :state = 'failed' THEN 'boom' END,"
            " CASE WHEN :state = 'failed' THEN 'permanent' END, :profile, '1.5.0')",
            state=state,
            profile=RETAIN_PROFILE,
            id=uuid.uuid4(),
            version=version,
            document=f"srcv:{version}:cover",
            bank=BANK,
        )

    def decide(self, version: str, anchor: str, decision: str) -> None:
        self.sql(
            "INSERT INTO triage_decision (id, source_version_id, section_anchor, char_start,"
            " char_end, sectioner_version, content_sha256, decision, category, reason, method,"
            " rubric_version, rules_version) VALUES (:id, :version, :anchor, 0, 10, 'v1', :sha,"
            " :decision, 'test', 'test', 'rule', 'triage.v3', 'triage-rules-v2')",
            id=uuid.uuid4(),
            version=version,
            anchor=anchor,
            sha=SHA,
            decision=decision,
        )

    def job(self, kind: str, version: str, status: str) -> None:
        """A job of the version in `status` (a running one holds a lease no worker will wait
        for, a failed one has spent its attempts)."""
        queue = JobQueue(self.engine)
        enqueued = queue.enqueue(
            kind, f"{kind}:{version}", {"source_version_id": version}, max_attempts=3
        )
        if status == "failed":
            self.sql(
                "UPDATE job SET status = 'failed', attempts = max_attempts, finished_at = now(),"
                " last_error = 'HTTP 529: overloaded_error' WHERE id = :id",
                id=enqueued.job.id,
            )
        elif status == "running":
            self.sql(
                "UPDATE job SET status = 'running', lease_owner = 'someone',"
                " lease_expires_at = now() + interval '1 day' WHERE id = :id",
                id=enqueued.job.id,
            )

    def health(self, **params: Any) -> dict[str, Any]:
        return self.get("/api/v1/memory/health", **params)

    def company_versions(self, slug: str) -> dict[str, Any]:
        (found,) = [c for c in self.health()["companies"] if c["slug"] == slug]
        return found["versions"]

    def reconciled(self) -> dict[str, Any]:
        enqueued = self.cli("memory", "reconcile")
        assert enqueued.returncode == 0, enqueued.stderr
        job_id = json.loads(enqueued.stdout)["id"]
        self.worker_pass()
        job = self.get(f"/api/v1/jobs/{job_id}")
        assert job["status"] == "succeeded", job["failures"]
        return self.get(f"/api/v1/memory/reconciliations/{job['artifacts']['reconciliation_id']}")

    def metrics(self) -> Metrics:
        return scrape_metrics(self.api)


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> Iterator[Coverage]:
    fake, served = hindsight
    fake.derive_memories()
    fake.script_observation_scopes([])
    fake.script_entities([])
    harness = Coverage(database_url, tmp_path, served.url, clock)
    harness.apply_template()
    seeded = harness.cli("companies", "seed")
    assert seeded.returncode == 0, seeded.stderr
    yield harness
    harness.engine.dispose()


class Arranged:
    """Lumentum's versions in every state, and Coherent's one in memory."""

    def __init__(self, atlas: Coverage, state: str = "completed") -> None:
        self.in_memory = atlas.add_version("lumentum", "10-K FY2025", days_ago=30)
        atlas.memory_document(self.in_memory, state)
        self.all_skipped = atlas.add_version("lumentum", "8-K exhibit index", days_ago=20)
        atlas.decide(self.all_skipped, "cover", "skip")
        atlas.decide(self.all_skipped, "item-9-01", "skip")
        self.triage_failed = atlas.add_version("lumentum", "Call transcript Q2", days_ago=10)
        atlas.job("triage", self.triage_failed, "failed")
        self.in_flight = atlas.add_version("lumentum", "10-Q Q3", days_ago=5)
        atlas.job("retain", self.in_flight, "running")
        self.newer = atlas.add_version("lumentum", "10-Q Q4", days_ago=2)
        self.older = atlas.add_version("lumentum", "10-Q Q2", days_ago=40)
        # Not Memory's to hold: a French document and a companyfacts version (no parse).
        atlas.add_version("lumentum", "Rapport financier", language="fr")
        atlas.add_version("lumentum", "companyfacts", parse_status="not_applicable")
        self.coherent = atlas.add_version("coherent", "10-K FY2025")
        atlas.memory_document(self.coherent, state)


def test_health_counts_versions_by_what_became_of_them_and_samples_the_gaps(
    atlas: Coverage,
) -> None:
    arranged = Arranged(atlas)

    health = atlas.health()

    lumentum = atlas.company_versions("lumentum")
    assert {k: lumentum[k] for k in lumentum if not k.endswith("samples")} == {
        "total": 6,
        "in_memory": 1,
        "all_skipped": 1,
        "triage_failed": 1,
        "in_flight": 1,
        "not_submitted": 2,
    }
    # Newest first, with the title and the day it became public.
    assert [s["source_version_id"] for s in lumentum["not_submitted_samples"]] == [
        arranged.newer,
        arranged.older,
    ]
    assert lumentum["not_submitted_samples"][0]["title"] == "10-Q Q4"
    assert lumentum["not_submitted_samples"][0]["available_at"]
    assert [s["source_version_id"] for s in lumentum["triage_failed_samples"]] == [
        arranged.triage_failed
    ]
    coherent = atlas.company_versions("coherent")
    assert (coherent["total"], coherent["in_memory"], coherent["not_submitted"]) == (1, 1, 0)
    # The bank: both companies.
    bank = health["versions"]
    assert (bank["total"], bank["in_memory"], bank["not_submitted"]) == (7, 2, 2)
    assert bank["triage_failed"] == 1
    assert len(bank["not_submitted_samples"]) == 2
    # Sections alone show none of it (what the health read said on production).
    assert health["sections"]["failed"] == 0 and health["sections"]["pending"] == 0
    # A company filter reads that company's versions, as the bank's.
    only = atlas.health(company_id=atlas.company("lumentum")["id"])
    assert only["versions"]["total"] == 6


def test_only_a_document_s_current_version_counts(atlas: Coverage) -> None:
    old = atlas.add_version("lumentum", "10-K, as first filed")
    current = atlas.supersede(old)
    atlas.memory_document(current)

    versions = atlas.company_versions("lumentum")

    # v1 never reached Memory but was superseded by v2, which did: no gap.
    assert (versions["total"], versions["in_memory"], versions["not_submitted"]) == (1, 1, 0)
    assert versions["not_submitted_samples"] == []


def test_samples_are_bounded_at_twenty(atlas: Coverage) -> None:
    for number in range(23):
        atlas.add_version("lumentum", f"10-Q {number}", days_ago=number + 1)

    versions = atlas.company_versions("lumentum")

    assert versions["not_submitted"] == 23
    assert len(versions["not_submitted_samples"]) == 20


def test_a_later_triage_that_succeeded_or_is_queued_is_not_a_failure(atlas: Coverage) -> None:
    retried = atlas.add_version("lumentum", "Call transcript Q1")
    atlas.job("triage", retried, "failed")
    atlas.sql(
        "INSERT INTO job (id, kind, idempotency_key, payload, status, attempts, max_attempts,"
        " created_at) VALUES (:id, 'triage', :key, CAST(:payload AS jsonb), 'queued', 0, 3,"
        " now() + interval '1 minute')",
        id=uuid.uuid4(),
        key=f"triage:{retried}:retry:1",
        payload=json.dumps({"source_version_id": retried}),
    )

    versions = atlas.company_versions("lumentum")

    assert (versions["in_flight"], versions["triage_failed"], versions["not_submitted"]) == (
        1,
        0,
        0,
    )


def test_the_reconciliation_reports_the_gaps_as_drift_with_their_reasons(
    atlas: Coverage,
) -> None:
    arranged = Arranged(atlas, "failed")

    run = atlas.reconciled()

    assert run["status"] == "drift"
    assert run["counts"]["version_not_in_memory"] == 3
    assert {k: v for k, v in run["counts"].items() if k != "version_not_in_memory"} == {
        k: 0 for k in run["counts"] if k != "version_not_in_memory"
    }
    assert run["samples"]["version_not_in_memory"] == sorted(
        [
            f"{arranged.newer}:not_submitted",
            f"{arranged.older}:not_submitted",
            f"{arranged.triage_failed}:triage_failed",
        ]
    )
    assert run["details"]["version_not_in_memory"] == {"not_submitted": 2, "triage_failed": 1}
    health = atlas.health()["reconciliation"]
    assert health["counts"]["version_not_in_memory"] == 3
    gauge = atlas.metrics()[("atlas_memory_drift", frozenset({("kind", "version_not_in_memory")}))]
    assert gauge == 3


def test_the_reconciliation_is_clean_when_every_version_is_in_memory_or_skipped(
    atlas: Coverage,
) -> None:
    atlas.memory_document(atlas.add_version("lumentum", "10-K"), "failed")
    skipped = atlas.add_version("lumentum", "Exhibit index")
    atlas.decide(skipped, "cover", "skip")
    atlas.add_version("lumentum", "Rapport", language="fr")

    run = atlas.reconciled()

    assert run["counts"]["version_not_in_memory"] == 0
    assert run["status"] == "clean", run


def test_the_gauge_counts_gaps_by_company_and_reason(atlas: Coverage) -> None:
    Arranged(atlas)

    metrics = atlas.metrics()

    def gap(company: str, reason: str) -> float:
        labels = frozenset({("company", company), ("reason", reason)})
        return metrics[("atlas_versions_not_in_memory", labels)]

    assert gap("lumentum", "not_submitted") == 2
    assert gap("lumentum", "triage_failed") == 1
    assert gap("coherent", "not_submitted") == 0
    assert gap("coherent", "triage_failed") == 0


def jobs_of(atlas: Coverage, kind: str) -> list[dict[str, Any]]:
    with atlas.engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT id FROM job WHERE kind = %(kind)s ORDER BY created_at, id", {"kind": kind}
        ).all()
    return [atlas.get(f"/api/v1/jobs/{row[0]}") for row in rows]


def test_the_backfill_offers_never_submitted_versions_and_retries_failed_triage(
    atlas: Coverage,
) -> None:
    arranged = Arranged(atlas)

    result = atlas.cli("memory", "backfill", "--company", "lumentum", "--key", "run-1")
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    atlas.worker_pass()

    (company,) = plan["companies"]
    assert (company["sections_below"], company["versions_below"], company["allotted"]) == (0, 3, 3)
    (take,) = [j for j in jobs_of(atlas, "memory_backfill") if j["artifacts"]["step"] == "take"]
    artifacts = take["artifacts"]
    assert artifacts["versions_taken"] == 3
    assert len(artifacts["version_retain_jobs"]) == 2
    assert len(artifacts["version_triage_jobs"]) == 1
    retains = {j["payload"]["source_version_id"]: j for j in jobs_of(atlas, "retain")}
    for version in (arranged.newer, arranged.older):
        assert retains[version]["job_class"] == "backfill"
        assert retains[version]["idempotency_key"] == f"retain:{version}:backfill:run-1"
    triages = [
        j
        for j in jobs_of(atlas, "triage")
        if j["payload"]["source_version_id"] == arranged.triage_failed
    ]
    assert [j["idempotency_key"] for j in triages] == [
        f"triage:{arranged.triage_failed}",
        f"triage:{arranged.triage_failed}:retry:1",
    ]
    # The ones in memory, skipped or in flight are left alone.
    for version in (arranged.in_memory, arranged.all_skipped, arranged.in_flight):
        assert version not in retains or version == arranged.in_flight


def test_max_sections_bounds_the_versions_a_run_takes_newest_first(atlas: Coverage) -> None:
    arranged = Arranged(atlas)
    # The older version was triaged: three sections to retain, so it counts as three.
    for anchor in ("cover", "part-i-item-1", "part-i-item-2"):
        atlas.decide(arranged.older, anchor, "retain")

    bounded = atlas.cli(
        "memory", "backfill", "--company", "lumentum", "--key", "n2", "--max-sections", "1"
    )
    assert bounded.returncode == 0, bounded.stderr
    (company,) = json.loads(bounded.stdout)["companies"]
    assert (company["versions_below"], company["allotted"]) == (1 + 1 + 3, 1)
    atlas.worker_pass()

    (take,) = [j for j in jobs_of(atlas, "memory_backfill") if j["artifacts"]["step"] == "take"]
    # One section's worth: the newest gap version only; the rest wait for a rerun.
    assert take["artifacts"]["versions_taken"] == 1
    assert take["artifacts"]["version_retain_jobs"] != []
    assert take["artifacts"]["versions_left"] == 2
