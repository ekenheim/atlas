"""The corpus already in Memory, brought to the current standard (memory-quality ticket 12).

`atlas memory backfill` enqueues one `memory_backfill` job per company; the worker deletes the
Hindsight document of each section below the current retain profile (and of the failed and
cancelled ones) and retains it again under the same ID, then asks for a consolidation.

Seams: the `atlas` CLI, single worker passes (on a controllable clock for the quota pause) and
`/api/v1` (`source-versions/{id}/memory`, `memory/health`, `memory/recall`), and the requests
the recorded Hindsight fake received. The delete-then-retain path is recorded
(`spikes/hindsight/recordings/delete_and_retain/`, 4 LLM requests on the local 0.10.2) and the
fake derives it from that recording (tests/fakes/hindsight.py, "Document deletion"). Nothing
live is called; an old profile or a failed section is arranged in the database, since a section
under `retain-v1` can no longer be produced.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from atlas.api.app import create_app
from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import LITE_10K, QUOTA_ERROR, TEN_K_ANCHORS, Atlas, Clock

LITE = "https://www.sec.gov/Archives/edgar/data/1633978"
LITE_10Q = f"{LITE}/000162828026030777/lite-20260328.htm"
LITE_8K = f"{LITE}/000162828026055726/lite-20260811.htm"
RETAIN_PROFILE = "retain-v2"  # atlas.retention.context.RETAIN_PROFILE
OLD_PROFILE = "retain-v1"
CANCELLED_ERROR = "Hindsight reported the operation cancelled with no error message"


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    return fake


class Backfilling(Atlas):
    def __init__(self, database_url: str, tmp_path: Path, hindsight: str, clock: Clock) -> None:
        super().__init__(database_url, tmp_path, hindsight, backfill_window="")
        self.clock = clock
        self.api = TestClient(create_app(self.settings(), clock=clock))

    def timed_pass(self) -> int:
        settings = self.settings()
        queue = JobQueue(self.engine, pacing=Pacing.from_settings(settings), clock=self.clock)
        return Worker(queue, builtin_registry(settings, clock=self.clock)).run_once()

    def sql(self, statement: str, **params: Any) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(statement), params)

    def age(self, url: str, anchors: list[str] | None = None) -> None:
        """The sections were retained under `retain-v1`: the context sent was not recorded."""
        version = self.version(url)["id"]
        self.sql(
            "UPDATE memory_document SET retain_profile = 'retain-v1', retain_context = NULL,"
            " retain_entities = NULL WHERE source_version_id = :version"
            " AND (CAST(:anchors AS text[]) IS NULL OR section_anchor = ANY(:anchors))",
            version=version,
            anchors=anchors,
        )

    def mark(self, url: str, anchor: str, state: str) -> None:
        version = self.version(url)["id"]
        error, error_class = (
            ("boom", "permanent") if state == "failed" else (CANCELLED_ERROR, "cancelled")
        )
        self.sql(
            "UPDATE memory_document SET retain_state = :state, error = :error,"
            " error_class = :error_class, fact_count = NULL, memory_ids = NULL"
            " WHERE source_version_id = :version AND section_anchor = :anchor",
            version=version,
            state=state,
            error=error,
            error_class=error_class,
            anchor=anchor,
        )

    def documents(self, url: str) -> dict[str, dict[str, Any]]:
        memory = self.memory(self.version(url)["id"])
        return {d["section_anchor"]: d for d in memory["documents"]}

    def backfill(self, *args: str) -> dict[str, Any]:
        result = self.cli("memory", "backfill", *args)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def health(self) -> dict[str, Any]:
        return self.get("/api/v1/memory/health")

    def company_counts(self, slug: str = "lumentum") -> dict[str, Any]:
        (found,) = [c for c in self.health()["companies"] if c["slug"] == slug]
        return found["sections"]


@pytest.fixture
def clock() -> Clock:
    # Real time, so the database's lease clock and the pacing clock start together.
    return Clock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> Iterator[Backfilling]:
    fake, served = hindsight
    fake.script_observation_scopes([])
    fake.script_entities([])
    harness = Backfilling(database_url, tmp_path, served.url, clock)
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


def anchors(document_ids: list[str]) -> list[str]:
    return [d.rsplit(":", 1)[1] for d in document_ids]


def consolidations(fake: RecordedHindsight) -> int:
    return len(fake.requests("POST", "consolidate"))


# --- the backfill -----------------------------------------------------------------------------


def test_sections_below_the_profile_and_failed_ones_are_retained_again_the_current_one_is_left(
    atlas: Backfilling, fake: RecordedHindsight
) -> None:
    atlas.age(LITE_10Q)  # both sections of the 10-Q: below the profile
    atlas.mark(LITE_10K, "part-i-item-1a", "failed")
    ten_q_before = atlas.documents(LITE_10Q)
    ten_k_before = atlas.documents(LITE_10K)
    assert atlas.company_counts()["below_profile"] == len(ten_q_before)
    batches_before = len(fake.retained())
    consolidations_before = consolidations(fake)

    plan = atlas.backfill("--company", "lumentum", "--key", "run-1")
    atlas.worker_pass()

    (company,) = plan["companies"]
    assert (company["company"], company["sections_below"], company["allotted"]) == (
        "lumentum",
        len(ten_q_before) + 1,
        len(ten_q_before) + 1,
    )
    # Only those sections were deleted from Hindsight and retained again, under the same IDs.
    redone = {ten_q_before[a]["document_id"] for a in ten_q_before} | {
        ten_k_before["part-i-item-1a"]["document_id"]
    }
    assert set(deleted(fake)) == redone
    sent = [item for batch in fake.retained()[batches_before:] for item in batch]
    assert {item["document_id"] for item in sent} == redone
    for item in sent:
        assert "Lumentum is speaking" in item["context"]  # the current profile's context
        assert item["entities"]
    # They are completed under the current profile, with new memories; the others are as they were.
    ten_q = atlas.documents(LITE_10Q)
    ten_k = atlas.documents(LITE_10K)
    for anchor, document in ten_q.items():
        assert document["retain_state"] == "completed"
        assert document["retain_profile"] == RETAIN_PROFILE
        assert document["memory_ids"] == [fake.derived_fact(document["document_id"])]
        assert document["memory_ids"] != ten_q_before[anchor]["memory_ids"]
    assert ten_k["part-i-item-1a"]["retain_state"] == "completed"
    assert ten_k["part-i-item-1a"]["retain_profile"] == RETAIN_PROFILE
    for anchor in set(TEN_K_ANCHORS) - {"part-i-item-1a"}:
        assert ten_k[anchor] == ten_k_before[anchor]
    # The company reads complete in the health read, and a consolidation followed.
    counts = atlas.company_counts()
    assert (counts["below_profile"], counts["failed"], counts["pending"]) == (0, 0, 0)
    assert counts["at_profile"] == counts["completed"] + counts["zero_fact"]
    assert consolidations(fake) == consolidations_before + 1
    assert atlas.health()["consolidation"]["last_requested"]["status"] == "completed"
    # The backfill job names what it did.
    (job,) = [j for j in jobs(atlas, "memory_backfill") if j["artifacts"]["step"] == "take"]
    assert job["artifacts"]["sections_taken"] == len(redone)
    assert job["artifacts"]["counts_before"]["below_profile"] == len(ten_q_before)
    assert job["artifacts"]["counts_after"]["pending"] == len(redone)
    finish = [j for j in jobs(atlas, "memory_backfill") if j["artifacts"]["step"] == "finish"]
    assert finish[-1]["artifacts"]["outcome"] == "consolidation_requested"

    # A rerun does nothing: no delete, no retain, no consolidation.
    deleted_before = len(deleted(fake))
    rerun = atlas.backfill("--company", "lumentum", "--key", "run-2")
    atlas.worker_pass()
    assert rerun["companies"][0]["sections_below"] == 0
    assert rerun["companies"][0]["job"] is None
    assert len(deleted(fake)) == deleted_before
    assert len(fake.retained()) == batches_before + 2  # the 10-Q's batch and the 10-K's
    assert consolidations(fake) == consolidations_before + 1


def jobs(atlas: Backfilling, kind: str) -> list[dict[str, Any]]:
    with atlas.engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT id FROM job WHERE kind = %(kind)s ORDER BY created_at, id", {"kind": kind}
        ).all()
    return [atlas.get(f"/api/v1/jobs/{row[0]}") for row in rows]


def test_the_failed_come_first_then_the_newest_and_max_sections_bounds_each_run(
    atlas: Backfilling, fake: RecordedHindsight
) -> None:
    atlas.age(LITE_10Q)
    atlas.age(LITE_8K)
    atlas.mark(LITE_10K, "part-i-item-1a", "cancelled")
    ten_k = atlas.documents(LITE_10K)
    eight_k = atlas.documents(LITE_8K)
    ten_q = atlas.documents(LITE_10Q)
    # Sections in the order a backfill takes them: the cancelled one; the 8-K (the newest
    # document) in section order; then the 10-Q.
    order = [
        ten_k["part-i-item-1a"]["document_id"],
        *(eight_k[a]["document_id"] for a in ("cover", "item-2-02", "item-9-01")),
        *(ten_q[a]["document_id"] for a in ("cover", "part-i-item-1")),
    ]

    first = atlas.backfill("--company", "lumentum", "--key", "night-1", "--max-sections", "2")
    atlas.worker_pass()

    assert first["companies"][0]["sections_below"] == len(order)
    assert first["companies"][0]["allotted"] == 2
    assert deleted(fake) == order[:2]
    assert atlas.company_counts()["below_profile"] == len(order) - 2

    # A rerun takes the next sections, never more than N.
    atlas.backfill("--company", "lumentum", "--key", "night-2", "--max-sections", "3")
    atlas.worker_pass()
    assert deleted(fake) == order[:5]

    atlas.backfill("--company", "lumentum", "--key", "night-3", "--max-sections", "3")
    atlas.worker_pass()
    assert deleted(fake) == order
    counts = atlas.company_counts()
    assert (counts["below_profile"], counts["failed"], counts["pending"]) == (0, 0, 0)

    # Nothing is left: a further run takes nothing.
    atlas.backfill("--company", "lumentum", "--key", "night-4")
    atlas.worker_pass()
    assert deleted(fake) == order


def test_a_quota_pause_holds_the_backfill_and_it_resumes(
    atlas: Backfilling, fake: RecordedHindsight, clock: Clock
) -> None:
    atlas.age(LITE_10Q)
    ten_q = atlas.documents(LITE_10Q)
    ids = {d["document_id"] for d in ten_q.values()}
    fake.hold_retains(
        "failed",
        where=lambda docs: bool(ids & set(docs)),
        error_message=QUOTA_ERROR,
        times=1,
    )
    consolidations_before = consolidations(fake)
    atlas.backfill("--company", "lumentum", "--key", "run-1")

    atlas.timed_pass()

    # The retain failed with a 429: the queue is paused, the sections wait, and no
    # consolidation was asked for.
    pause = atlas.get("/api/v1/queue")["pause"]
    assert (pause["paused"], pause["error_class"]) == (True, "quota")
    assert {d["retain_state"] for d in atlas.documents(LITE_10Q).values()} == {"pending"}
    assert consolidations(fake) == consolidations_before

    clock.advance(seconds=61)
    atlas.timed_pass()

    assert {d["retain_state"] for d in atlas.documents(LITE_10Q).values()} == {"completed"}
    assert {d["retain_profile"] for d in atlas.documents(LITE_10Q).values()} == {RETAIN_PROFILE}
    assert atlas.company_counts()["below_profile"] == 0
    assert consolidations(fake) == consolidations_before + 1
    # It took each section once: the resubmission after the pause is not a second backfill.
    assert sorted(deleted(fake)) == sorted(ids)


# --- what an older memory reads as ------------------------------------------------------------


def test_a_memory_the_backfill_replaced_reads_replaced_not_broken(
    atlas: Backfilling, fake: RecordedHindsight
) -> None:
    ten_k = atlas.documents(LITE_10K)["part-i-item-1"]
    ten_q = atlas.documents(LITE_10Q)["cover"]
    observation_id = fake.derive_observation([ten_k["document_id"], ten_q["document_id"]])
    old_fact = fake.derived_fact(ten_q["document_id"])
    company = atlas.company("lumentum")["id"]
    atlas.age(LITE_10Q, ["cover"])

    atlas.backfill("--company", "lumentum", "--key", "run-1")
    atlas.worker_pass()

    new_fact = fake.derived_fact(ten_q["document_id"])
    assert new_fact != old_fact  # Hindsight gave the section's new fact a new ID
    recalled = atlas.recall("capacity", company_ids=[company])
    (observation,) = [m for m in recalled["memories"] if m["memory_id"] == observation_id]
    # The observation was consolidated from the replaced fact: not broken, replaced.
    assert observation["provenance"]["state"] == "unverified"
    assert observation["provenance"]["reason"] == "memory_replaced"
    assert (
        old_fact in observation["provenance"]["detail"]
        or "replaced" in (observation["provenance"]["detail"])
    )
    assert observation["provenance"]["missing_memory_ids"] == []
    assert recalled["counts"]["broken"] == 0
    # The replaced memory is recorded, insert-only.
    with atlas.engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT hindsight_document_id, from_profile, replaced_memory_ids"
            " FROM memory_replacement"
        ).all()
    assert [(r[0], r[1], r[2]) for r in rows] == [(ten_q["document_id"], OLD_PROFILE, [old_fact])]


# --- the command ------------------------------------------------------------------------------


def test_the_command_takes_companies_or_a_theme_not_both_nor_neither(atlas: Backfilling) -> None:
    neither = atlas.cli("memory", "backfill")
    both = atlas.cli("memory", "backfill", "--company", "lumentum", "--theme", "photonics")
    unknown = atlas.cli("memory", "backfill", "--company", "no-such-company")

    assert neither.returncode == 2
    assert both.returncode == 2
    assert unknown.returncode == 2
    assert "no company 'no-such-company'" in unknown.stderr


def test_a_theme_runs_its_companies_seeds_first_and_thinnest_first(
    atlas: Backfilling,
) -> None:
    atlas.ingest_company("coherent")
    ids = {slug: atlas.company(slug)["id"] for slug in ("lumentum", "coherent")}
    with atlas.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE memory_document SET retain_profile = 'retain-v1', retain_context = NULL"
                " WHERE retain_state = 'completed'"
            )
        )
    completed = {slug: atlas.company_counts(slug)["completed"] for slug in ids}
    assert completed["lumentum"] != completed["coherent"]
    thinner, thicker = sorted(ids, key=lambda slug: completed[slug])

    # No investigation yet: the thinnest in Memory first.
    plan = atlas.backfill("--theme", "photonics", "--key", "run-1")
    assert [c["company"] for c in plan["companies"] if c["job"] is not None] == [thinner, thicker]

    # The thicker one seeded an investigation of the pilot: the seeds first.
    with atlas.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO investigation (id, theme, question, seed_company_ids, as_of, bank_id,"
                " max_rounds, max_leads, max_documents, max_companies, token_budget, created_by)"
                " VALUES (gen_random_uuid(), 'photonics', 'q', ARRAY[CAST(:company AS uuid)],"
                " now(), :bank, 1, 1, 1, 1, 1, 'test')"
            ),
            {"company": ids[thicker], "bank": atlas.settings().hindsight_bank_id},
        )
    plan = atlas.backfill("--theme", "photonics", "--key", "run-2")
    assert [c["company"] for c in plan["companies"] if c["job"] is not None] == [thicker, thinner]

    # Naming companies runs them in the order named, whatever their Memory holds.
    plan = atlas.backfill("--company", thinner, "--company", thicker, "--key", "run-3")
    assert [c["company"] for c in plan["companies"]] == [thinner, thicker]
