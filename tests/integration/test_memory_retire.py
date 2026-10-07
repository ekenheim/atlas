"""Memory holds the intake window (pilot-review ticket 23).

`atlas memory retire --before <date>` enqueues one `memory_retire` job per company; the worker
deletes the Hindsight document of every section of a Source Version available before the date,
sets the section `retired` and records its memories, then asks for a consolidation. The Source
Versions stay in the ledger and the archive.

Seams: the `atlas` CLI, single worker passes, `/api/v1` (`source-versions/{id}/memory`,
`memory/health`, `memory/recall`, `memory/reconciliations`, `jobs/{id}`) and the requests the
recorded Hindsight fake received. The delete is recorded on 0.10.2 (the fake derives it from
`recordings/delete_and_retain/`, `memory_units_deleted` included). Nothing live is called; a
failed section and a retired one are arranged in the database.
"""

import json
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from atlas.api.app import create_app
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import BANK, LITE_10K, TEMPLATE, Atlas

LITE = "https://www.sec.gov/Archives/edgar/data/1633978"
LITE_10Q = f"{LITE}/000162828026030777/lite-20260328.htm"
LITE_8K = f"{LITE}/000162828026055726/lite-20260811.htm"
LITE_8K_EX991 = f"{LITE}/000162828026055726/lite_ex991xq4fy26.htm"


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    return fake


class Retiring(Atlas):
    def __init__(self, database_url: str, tmp_path: Path, hindsight: str) -> None:
        super().__init__(
            database_url,
            tmp_path,
            hindsight,
            hindsight_template_path=TEMPLATE,
            backfill_window="",
            consolidate_poll_timeout_seconds=0.2,
            consolidate_poll_interval_seconds=0.01,
            mental_model_refresh_at="",
            consolidate_at="",
            reconcile_at="",
        )
        self.api = TestClient(create_app(self.settings()))

    def sql(self, statement: str, **params: Any) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(statement), params)

    def documents(self, url: str) -> dict[str, dict[str, Any]]:
        memory = self.memory(self.version(url)["id"])
        return {d["section_anchor"]: d for d in memory["documents"]}

    def sections_before(self, cut: str) -> list[str]:
        """The document IDs of the sections of versions available before `cut`, newest
        version first and in section order within a version."""
        with self.engine.connect() as connection:
            return list(
                connection.execute(
                    text(
                        "SELECT m.hindsight_document_id FROM memory_document m"
                        " JOIN source_version_availability a"
                        "   ON a.source_version_id = m.source_version_id"
                        " WHERE a.available_at < CAST(:cut AS timestamptz)"
                        " AND m.hindsight_document_id IS NOT NULL"
                        " ORDER BY a.available_at DESC, m.source_version_id, m.char_start"
                    ),
                    {"cut": cut},
                ).scalars()
            )

    def available(self, url: str) -> str:
        return str(self.version(url)["available_at"])

    def retire(self, *args: str) -> dict[str, Any]:
        result = self.cli("memory", "retire", *args)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def health(self) -> dict[str, Any]:
        return self.get("/api/v1/memory/health")

    def company_counts(self, slug: str = "lumentum") -> dict[str, Any]:
        (found,) = [c for c in self.health()["companies"] if c["slug"] == slug]
        return found["sections"]

    def jobs(self, kind: str) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.exec_driver_sql(
                "SELECT id FROM job WHERE kind = %(kind)s ORDER BY created_at, id", {"kind": kind}
            ).all()
        return [self.get(f"/api/v1/jobs/{row[0]}") for row in rows]

    def retirements(self) -> list[tuple[Any, ...]]:
        with self.engine.connect() as connection:
            return list(
                connection.exec_driver_sql(
                    "SELECT hindsight_document_id, from_state, retired_memory_ids,"
                    " document_deleted, memory_units_deleted, run_key FROM memory_retirement"
                    " ORDER BY hindsight_document_id"
                ).all()
            )


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> Iterator[Retiring]:
    fake, served = hindsight
    fake.script_observation_scopes([])
    fake.script_entities([])
    harness = Retiring(database_url, tmp_path, served.url)
    harness.apply_template()
    harness.ingest_company("lumentum")
    yield harness
    harness.engine.dispose()


def deleted(fake: RecordedHindsight) -> list[str]:
    """The document IDs Hindsight was asked to delete, in order."""
    return [
        unquote(request.url.path.rsplit("/documents/", 1)[1])
        for request in fake.calls
        if request.method == "DELETE" and "/documents/" in request.url.path
    ]


def consolidations(fake: RecordedHindsight) -> int:
    return len(fake.requests("POST", "consolidate"))


# --- the retirement ---------------------------------------------------------------------------


def test_sections_before_the_date_leave_memory_the_rest_stay_and_the_versions_stay_citable(
    atlas: Retiring, fake: RecordedHindsight
) -> None:
    eight_k = atlas.documents(LITE_8K)
    ten_q = atlas.documents(LITE_10Q)
    ten_k = atlas.documents(LITE_10K)
    ten_k_before = {a: d["retain_state"] for a, d in ten_k.items()}
    old_facts = {d["document_id"]: fake.derived_fact(d["document_id"]) for d in ten_q.values()}
    cut = atlas.available(LITE_10K)  # the 10-K is newer than the 8-K and the 10-Q
    old_ids = atlas.sections_before(cut)
    assert {d["document_id"] for d in [*eight_k.values(), *ten_q.values()]} <= set(old_ids)
    kept_total = atlas.company_counts()["completed"] - len(old_ids)
    consolidations_before = consolidations(fake)
    batches_before = len(fake.retained())

    plan = atlas.retire("--before", cut, "--company", "lumentum", "--key", "run-1")
    atlas.worker_pass()

    (company,) = plan["companies"]
    old_sections = len(old_ids)
    assert (company["company"], company["sections_before_window"], company["allotted"]) == (
        "lumentum",
        old_sections,
        old_sections,
    )
    assert plan["dry_count"] is False
    # Every old section's document was deleted in Hindsight; the 10-K's were not.
    assert set(deleted(fake)) == set(old_ids)
    assert len(deleted(fake)) == old_sections
    # The sections read `retired`, with no new retain; the 10-K is as it was.
    for url in (LITE_8K, LITE_10Q):
        assert {d["retain_state"] for d in atlas.documents(url).values()} == {"retired"}
    assert {a: d["retain_state"] for a, d in atlas.documents(LITE_10K).items()} == ten_k_before
    assert len(fake.retained()) == batches_before
    # Each retirement records its memories, the bound, the state it had and what Hindsight said.
    rows = atlas.retirements()
    assert len(rows) == old_sections
    by_document = {r[0]: r for r in rows}
    for document_id, fact in old_facts.items():
        row = by_document[document_id]
        assert (row[1], row[2], row[3], row[4], row[5]) == (
            "completed",
            [fact],
            True,
            1,
            "run-1",
        )
    # Health counts them, per company and for the bank; the sections still total.
    counts = atlas.company_counts()
    assert counts["retired"] == old_sections
    assert counts["completed"] == kept_total
    assert atlas.health()["sections"]["retired"] == old_sections
    memory = atlas.memory(atlas.version(LITE_8K)["id"])
    assert memory["counts"]["retired"] == len(eight_k)
    # The job names what it did, with the bank's pending consolidation before and after.
    (job,) = atlas.jobs("memory_retire")
    artifacts = job["artifacts"]
    assert artifacts["sections_retired"] == old_sections
    assert artifacts["retired_by_state"] == {"completed": old_sections}
    assert artifacts["memory_units_deleted"] == old_sections
    assert artifacts["sections_left"] == 0
    assert {"pending_consolidation_before", "pending_consolidation_after"} <= set(artifacts)
    # A consolidation followed (backfill class), so the invalidated observations are rebuilt.
    assert consolidations(fake) == consolidations_before + 1
    (consolidate,) = atlas.jobs("consolidate")
    assert consolidate["job_class"] == "backfill"
    assert consolidate["artifacts"]["outcome"] == "completed"
    # The Source Versions stay in the ledger and the archive.
    content = atlas.api.get(
        f"/api/v1/source-versions/{atlas.version(LITE_8K)['id']}/content",
        params={"kind": "parsed"},
    )
    assert content.status_code == 200 and content.text

    # A rerun takes nothing and deletes nothing.
    deleted_before = len(deleted(fake))
    rerun = atlas.retire("--before", cut, "--company", "lumentum", "--key", "run-2")
    atlas.worker_pass()
    assert rerun["companies"][0]["sections_before_window"] == 0
    assert rerun["companies"][0]["job"] is None
    assert len(deleted(fake)) == deleted_before


def test_max_sections_zero_counts_and_deletes_nothing(
    atlas: Retiring, fake: RecordedHindsight
) -> None:
    cut = atlas.available(LITE_10K)
    old_sections = len(atlas.sections_before(cut))

    plan = atlas.retire("--before", cut, "--max-sections", "0")
    atlas.worker_pass()

    assert plan["dry_count"] is True
    (company,) = [c for c in plan["companies"] if c["company"] == "lumentum"]
    assert (company["sections_before_window"], company["allotted"], company["job"]) == (
        old_sections,
        0,
        None,
    )
    assert atlas.jobs("memory_retire") == []
    assert deleted(fake) == []
    assert atlas.retirements() == []
    assert atlas.company_counts()["retired"] == 0


def test_max_sections_bounds_each_run_newest_first_and_failed_ones_are_taken_too(
    atlas: Retiring, fake: RecordedHindsight
) -> None:
    eight_k = atlas.documents(LITE_8K)
    ten_q = atlas.documents(LITE_10Q)
    version = atlas.version(LITE_8K)["id"]
    atlas.sql(
        "UPDATE memory_document SET retain_state = 'failed', error = 'boom',"
        " error_class = 'permanent', fact_count = NULL, memory_ids = NULL"
        " WHERE source_version_id = :version AND section_anchor = 'item-2-02'",
        version=version,
    )
    # The newest document first (the 8-K), in section order; then the 10-Q.
    cut = atlas.available(LITE_10K)
    order = atlas.sections_before(cut)
    # The 8-K's filing, the newest of the old documents, comes first: the 8-K and its
    # EX-99.1 share an available_at, so which of the two leads is the version ID's order.
    # Within the 8-K, section order.
    newest = {
        d["document_id"] for d in [*eight_k.values(), *atlas.documents(LITE_8K_EX991).values()]
    }
    assert set(order[: len(newest)]) == newest
    assert [o for o in order if o in {d["document_id"] for d in eight_k.values()}] == [
        d["document_id"] for d in sorted(eight_k.values(), key=lambda d: d["char_start"])
    ]
    assert set(order) >= {d["document_id"] for d in ten_q.values()}

    atlas.retire("--before", cut, "--company", "lumentum", "--key", "n1", "--max-sections", "2")
    atlas.worker_pass()
    assert deleted(fake) == order[:2]

    atlas.retire("--before", cut, "--company", "lumentum", "--key", "n2", "--max-sections", "2")
    atlas.worker_pass()
    assert deleted(fake) == order[:4]

    atlas.retire("--before", cut, "--company", "lumentum", "--key", "n3")
    atlas.worker_pass()
    assert deleted(fake) == order
    states = {r[0]: r[1] for r in atlas.retirements()}
    failed_document = eight_k["item-2-02"]["document_id"]
    assert states[failed_document] == "failed"
    assert atlas.company_counts()["retired"] == len(order)


def test_a_document_hindsight_no_longer_has_is_retired_without_error(
    atlas: Retiring, fake: RecordedHindsight
) -> None:
    ten_q = atlas.documents(LITE_10Q)
    gone = ten_q["cover"]["document_id"]
    request = urllib.request.Request(
        f"{atlas.hindsight_url}/v1/default/banks/{BANK}/documents/{quote(gone, safe='')}",
        method="DELETE",
    )
    with urllib.request.urlopen(request) as response:
        assert response.status == 200
    assert gone not in fake.bank_documents(BANK)

    atlas.retire("--before", atlas.available(LITE_10K), "--company", "lumentum", "--key", "r")
    atlas.worker_pass()

    (job,) = atlas.jobs("memory_retire")
    assert job["status"] == "succeeded"
    assert job["artifacts"]["documents_absent"] == 1
    (row,) = [r for r in atlas.retirements() if r[0] == gone]
    assert (row[3], row[4]) == (False, None)
    assert atlas.documents(LITE_10Q)["cover"]["retain_state"] == "retired"


# --- what a retired memory reads as -----------------------------------------------------------


def test_a_memory_that_was_retired_reads_retired_not_broken(
    atlas: Retiring, fake: RecordedHindsight
) -> None:
    eight_k = atlas.documents(LITE_8K)["cover"]
    ten_q = atlas.documents(LITE_10Q)["cover"]
    observation_id = fake.derive_observation([eight_k["document_id"], ten_q["document_id"]])
    old_fact = fake.derived_fact(ten_q["document_id"])
    company = atlas.company("lumentum")["id"]

    atlas.retire("--before", atlas.available(LITE_10K), "--company", "lumentum", "--key", "r")
    atlas.worker_pass()

    recalled = atlas.recall("capacity", company_ids=[company])
    found = [m for m in recalled["memories"] if m["memory_id"] == observation_id]
    # The observation cited deleted facts: Hindsight invalidated it, so recall no longer has it;
    # a lookup of the retired fact reads as retired.
    for memory in found:
        assert memory["provenance"]["state"] == "unverified"
        assert memory["provenance"]["reason"] == "memory_retired"
    assert recalled["counts"]["broken"] == 0
    answer = atlas.api.post(
        "/api/v1/memory/recall",
        json={
            "query": "capacity",
            "scope": {"company_ids": [company]},
            "include_source_facts": True,
        },
    )
    assert answer.status_code == 200
    assert old_fact in {row[2][0] for row in atlas.retirements() if row[2]}


# --- nothing takes a retired section back -----------------------------------------------------


def test_nothing_takes_a_retired_section_back(atlas: Retiring, fake: RecordedHindsight) -> None:
    cut = atlas.available(LITE_10K)
    retired_version = atlas.version(LITE_10Q)["id"]
    atlas.retire("--before", cut, "--company", "lumentum", "--key", "r")
    atlas.worker_pass()
    deleted_before = len(deleted(fake))
    batches_before = len(fake.retained())
    # A retired section under an older profile: the backfill does not take it.
    atlas.sql(
        "UPDATE memory_document SET retain_profile = 'retain-v1', updated_at = now()"
        " - interval '3 days' WHERE retain_state = 'retired'"
    )

    backfill = atlas.cli("memory", "backfill", "--company", "lumentum", "--key", "b")
    assert backfill.returncode == 0, backfill.stderr
    assert json.loads(backfill.stdout)["companies"][0]["sections_below"] == 0
    # `retention retry-failed` has nothing to enqueue.
    retry = atlas.cli("retention", "retry-failed", "--all-history")
    assert retry.returncode == 0, retry.stderr
    # A retain of the version submits nothing.
    enqueue = atlas.cli(
        "jobs",
        "enqueue",
        "retain",
        "--key",
        "again",
        "--payload",
        json.dumps({"source_version_id": retired_version}),
    )
    assert enqueue.returncode == 0, enqueue.stderr
    atlas.worker_pass()

    assert len(deleted(fake)) == deleted_before
    assert len(fake.retained()) == batches_before
    assert atlas.company_counts()["retired"] > 0
    assert atlas.company_counts()["pending"] == 0
    assert {d["retain_state"] for d in atlas.documents(LITE_10Q).values()} == {"retired"}


def test_retired_sections_are_not_missing_and_a_delete_that_did_not_take_is_drift(
    atlas: Retiring, fake: RecordedHindsight
) -> None:
    atlas.retire("--before", atlas.available(LITE_10K), "--company", "lumentum", "--key", "r")
    atlas.worker_pass()

    clean = reconcile(atlas)
    assert clean["counts"]["section_missing"] == 0
    assert clean["counts"]["document_unrecorded"] == 0

    # A section marked retired whose document Hindsight still holds: the delete did not take.
    held = atlas.documents(LITE_10K)["cover"]
    atlas.sql(
        "UPDATE memory_document SET retain_state = 'retired', fact_count = NULL, memory_ids = NULL"
        " WHERE hindsight_document_id = :document",
        document=held["document_id"],
    )
    drift = reconcile(atlas)
    assert drift["counts"]["document_unrecorded"] == 1
    assert drift["counts"]["section_missing"] == 0
    assert drift["samples"]["document_unrecorded"] == [held["document_id"]]
    assert drift["details"]["document_unrecorded"] == {"retired": 1}


def reconcile(atlas: Retiring) -> dict[str, Any]:
    result = atlas.cli("memory", "reconcile", "--key", f"rec-{datetime.now(UTC).timestamp()}")
    assert result.returncode == 0, result.stderr
    enqueued = json.loads(result.stdout)
    atlas.worker_pass()
    job = atlas.get(f"/api/v1/jobs/{enqueued['id']}")
    assert job["status"] == "succeeded", job["failures"]
    return atlas.get(f"/api/v1/memory/reconciliations/{job['artifacts']['reconciliation_id']}")


def test_the_command_refuses_a_bad_date_and_an_unknown_company(atlas: Retiring) -> None:
    bad = atlas.cli("memory", "retire", "--before", "last week")
    assert bad.returncode == 2 and "not an ISO date" in bad.stderr
    unknown = atlas.cli("memory", "retire", "--before", "2024-10-06", "--company", "nope")
    assert unknown.returncode == 2 and "no company 'nope'" in unknown.stderr
    missing = atlas.cli("memory", "retire")
    assert missing.returncode == 2


def test_the_job_is_backfill_class(atlas: Retiring) -> None:
    atlas.retire("--before", atlas.available(LITE_10K), "--company", "lumentum", "--key", "r")
    atlas.worker_pass()
    (job,) = atlas.jobs("memory_retire")
    assert (job["job_class"], job["status"]) == ("backfill", "succeeded")
