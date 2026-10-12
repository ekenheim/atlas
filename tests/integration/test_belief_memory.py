"""Memory holds what was found (beliefs ticket 06).

A judged Belief is retained into the research bank as the document `belief:<id>` by a
`retain_belief` job; a re-judgement or a supersession deletes it and retains it again; a recall
labels its memories `belief` (never a section) and takes `available_by`; `ATLAS_BULK_RETENTION=off`
holds the ingest's section retains, triage and the daily consolidation while Beliefs still reach
Memory.

Seams: the `/api/v1` API (beliefs, facts, `memory/recall`, `memory/health`), single worker passes
and the requests the recorded Hindsight fake received. The CLI is not spawned (the template is
applied and the ingest enqueued in process), so these run on any platform. Nothing live is called.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
from sqlalchemy import text

from atlas.audit import Actor
from atlas.beliefs.memory_jobs import RETAIN_BELIEF_KIND as TRIGGER_KIND
from atlas.cli import run_apply_template
from atlas.jobs import JobQueue, Worker, builtin_registry
from atlas.jobs.pacing import Pacing
from atlas.ledger.ingest import INGEST_KIND, ingest_payload
from atlas.retention.beliefs import RETAIN_BELIEF_KIND
from tests.fakes.hindsight import RecordedHindsight
from tests.harness import TEMPLATE, Atlas

URL_EX991 = (
    "https://www.sec.gov/Archives/edgar/data/1633978/000162828026055726/lite_ex991xq4fy26.htm"
)
QUARTER = "Net revenue for the fourth quarter of fiscal year 2026 was $1.01 billion"
YEAR = "Net revenue for fiscal year 2026 was $3.01 billion"
BELIEF = "Lumentum's revenue is growing fast enough to strain its laser capacity."
AS_OF = "2026-09-30T00:00:00Z"
STATEMENTS = {
    QUARTER: ("Lumentum's fourth-quarter fiscal 2026 net revenue was $1.01 billion.", 1.01),
    YEAR: ("Lumentum's fiscal 2026 net revenue was $3.01 billion.", 3.01),
}


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    return fake


class Memory(Atlas):
    def __init__(self, database_url: str, tmp_path: Path, hindsight: str, **settings: Any) -> None:
        super().__init__(
            database_url,
            tmp_path,
            hindsight,
            hindsight_template_path=TEMPLATE,
            backfill_window="",
            consolidate_at="",
            reconcile_at="",
            mental_model_refresh_at="",
            consolidate_poll_timeout_seconds=0.2,
            consolidate_poll_interval_seconds=0.01,
            **settings,
        )
        assert run_apply_template(self.settings(), TEMPLATE) == 0
        self.actor = Actor("belief-memory-test")

    def worker_pass(self) -> int:
        """A worker with the settings' pacing, so the queue's holds are in force."""
        settings = self.settings()
        queue = JobQueue(self.engine, pacing=Pacing.from_settings(settings))
        return Worker(queue, builtin_registry(settings)).run_once()

    def drain(self) -> int:
        return self.worker_pass()

    def ingest_lumentum(self) -> None:
        JobQueue(self.engine, actor=self.actor).enqueue(
            INGEST_KIND, "lumentum", ingest_payload("lumentum", ["8-K"], None)
        )
        self.drain()

    def post(self, path: str, body: dict[str, Any], status: int = 200) -> Any:
        response = self.api.post(path, json=body)
        assert response.status_code == status, response.text
        return response.json()

    def fact(self, quote: str = QUARTER) -> str:
        version = self.version(URL_EX991)["id"]
        parsed = self.parsed(version)
        start = parsed.index(quote)
        statement, value = STATEMENTS[quote]
        recorded = self.post(
            "/api/v1/facts",
            {
                "subject_company_id": self.company("lumentum")["id"],
                "source_version_id": version,
                "quote": quote,
                "span_start": start,
                "span_end": start + len(quote),
                "epistemic_type": "company_claim",
                "step": "context",
                "statement": statement,
                "quantity": {"value": value, "unit": "USD", "metric": "figure"},
                "period": "FY2026",
                "status": "in_effect",
            },
            status=201,
        )
        return recorded["fact"]["id"]

    def propose(self, fact: str, statement: str = BELIEF, as_of: str = AS_OF) -> str:
        return self.post(
            "/api/v1/beliefs",
            {
                "statement": statement,
                "theme": "photonics",
                "step": "constraint",
                "company_ids": [self.company("lumentum")["id"]],
                "as_of": as_of,
                "actor": "claude-session",
                "citations": [{"ref_id": fact, "valence": 0.9, "weight": "load_bearing"}],
            },
            status=201,
        )["id"]

    def judge(self, belief: str, judgement: str = "proven", confidence: float = 0.8) -> None:
        self.post(
            f"/api/v1/beliefs/{belief}/judge",
            {
                "actor": "owner",
                "judgement": judgement,
                "confidence": confidence,
                "reason": f"judged {judgement}",
            },
        )

    def supersede(self, old: str, new: str) -> None:
        self.post(
            f"/api/v1/beliefs/{old}/supersede",
            {"by": [new], "reason": "a finer proposition", "actor": "owner"},
        )

    def rows(self, statement: str, **params: Any) -> list[Any]:
        with self.engine.connect() as connection:
            return list(connection.execute(text(statement), params).all())

    def jobs(self, kind: str = RETAIN_BELIEF_KIND) -> list[Any]:
        return self.rows("SELECT status FROM job WHERE kind = :kind ORDER BY created_at", kind=kind)

    def recall_beliefs(self, **extra: Any) -> dict[str, Any]:
        response = self.api.post(
            "/api/v1/memory/recall",
            json={"query": "laser capacity", "scope": {"theme_ids": ["photonics"]}, **extra},
        )
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, object]
) -> Iterator[Memory]:
    fake, served = hindsight
    fake.script_observation_scopes([])
    fake.script_entities([])
    harness = Memory(database_url, tmp_path, served.url)  # type: ignore[attr-defined]
    harness.ingest_lumentum()
    yield harness
    harness.engine.dispose()


def belief_batches(fake: RecordedHindsight, belief: str) -> list[dict[str, Any]]:
    """The retain items for `belief:<belief>` Hindsight received, in order."""
    return [
        item
        for batch in fake.retained()
        for item in batch
        if item["document_id"] == f"belief:{belief}"
    ]


def deleted(fake: RecordedHindsight) -> list[str]:
    return [
        unquote(request.url.path.rsplit("/documents/", 1)[1])
        for request in fake.calls
        if request.method == "DELETE" and "/documents/" in request.url.path
    ]


def test_the_trigger_and_the_handler_agree_on_the_job_kind() -> None:
    assert TRIGGER_KIND == RETAIN_BELIEF_KIND == "retain_belief"


# --- retain on judgement ----------------------------------------------------------------------


def test_a_judged_belief_is_retained_as_its_own_document_and_an_unproven_one_is_not(
    atlas: Memory, fake: RecordedHindsight
) -> None:
    fact = atlas.fact()
    belief = atlas.propose(fact)
    atlas.drain()
    assert atlas.jobs() == []
    assert belief_batches(fake, belief) == []

    atlas.judge(belief, "proven", 0.8)
    atlas.drain()

    (job,) = atlas.jobs()
    assert job.status == "succeeded"
    (item,) = belief_batches(fake, belief)
    company = atlas.company("lumentum")
    assert item["tags"] == [
        "belief",
        "judgement:proven",
        "step:constraint",
        "theme:photonics",
        f"company:{company['id']}",
    ]
    assert item["observation_scopes"] == [["theme:photonics"]]
    assert item["timestamp"].startswith("2026-09-30")
    assert [e["text"] for e in item["entities"]] == [company["legal_name"]]
    content = item["content"]
    assert BELIEF in content
    assert "proven" in content and "0.8" in content
    assert QUARTER in content  # the load-bearing Fact's quote
    assert "fourth-quarter fiscal 2026 net revenue" in content  # and its statement
    assert item["metadata"]["belief_id"] == belief
    (memory,) = atlas.rows(
        "SELECT state, fact_count, memory_ids FROM belief_memory WHERE belief_id = :id",
        id=belief,
    )
    assert (memory.state, memory.fact_count) == ("completed", 1)
    assert memory.memory_ids == [fake.derived_fact(f"belief:{belief}")]
    health = atlas.get("/api/v1/memory/health")
    assert health["beliefs"]["in_memory"] == 1
    assert health["beliefs"]["themes"] == [
        {"theme": "photonics", "in_memory": 1, "pending": 0, "failed": 0, "zero_fact": 0}
    ]
    assert health["bulk_retention"] == "on"


def test_the_same_judgement_is_not_retained_twice(atlas: Memory, fake: RecordedHindsight) -> None:
    belief = atlas.propose(atlas.fact())
    atlas.judge(belief)
    atlas.drain()
    atlas.drain()
    assert len(belief_batches(fake, belief)) == 1
    assert deleted(fake) == []


# --- replacement ------------------------------------------------------------------------------


def test_a_rejudgement_deletes_the_document_records_its_memories_and_retains_again(
    atlas: Memory, fake: RecordedHindsight
) -> None:
    belief = atlas.propose(atlas.fact())
    atlas.judge(belief, "proven", 0.8)
    atlas.drain()
    old_fact = fake.derived_fact(f"belief:{belief}")

    atlas.judge(belief, "disproven", 0.6)
    atlas.drain()

    assert deleted(fake) == [f"belief:{belief}"]
    first, second = belief_batches(fake, belief)
    assert "judgement:proven" in first["tags"] and "judgement:disproven" in second["tags"]
    assert "disproven" in second["content"]
    (replacement,) = atlas.rows(
        "SELECT reason, replaced_memory_ids, hindsight_document_id FROM belief_memory_replacement"
        " WHERE belief_id = :id",
        id=belief,
    )
    assert (replacement.reason, replacement.replaced_memory_ids) == ("rejudged", [old_fact])
    assert replacement.hindsight_document_id == f"belief:{belief}"
    (memory,) = atlas.rows("SELECT state FROM belief_memory WHERE belief_id = :id", id=belief)
    assert memory.state == "completed"
    health = atlas.get("/api/v1/memory/health")
    assert health["beliefs"]["in_memory"] == 1


def test_a_belief_judged_unproven_again_is_taken_out_of_memory(
    atlas: Memory, fake: RecordedHindsight
) -> None:
    belief = atlas.propose(atlas.fact())
    atlas.judge(belief)
    atlas.drain()

    atlas.judge(belief, "unproven", 0.0)
    atlas.drain()

    assert deleted(fake) == [f"belief:{belief}"]
    assert len(belief_batches(fake, belief)) == 1
    (memory,) = atlas.rows("SELECT state FROM belief_memory WHERE belief_id = :id", id=belief)
    assert memory.state == "removed"
    assert atlas.get("/api/v1/memory/health")["beliefs"]["in_memory"] == 0


def test_a_supersession_replaces_the_old_beliefs_document(
    atlas: Memory, fake: RecordedHindsight
) -> None:
    old = atlas.propose(atlas.fact())
    new = atlas.propose(atlas.fact(YEAR), statement="Lumentum's laser capacity is sold out.")
    atlas.judge(old)
    atlas.drain()

    atlas.supersede(old, new)
    atlas.drain()

    assert deleted(fake) == [f"belief:{old}"]
    _, again = belief_batches(fake, old)
    assert "Lumentum's laser capacity is sold out." in again["content"]  # Superseded by
    assert "superseded" in again["content"]
    (replacement,) = atlas.rows(
        "SELECT reason FROM belief_memory_replacement WHERE belief_id = :id", id=old
    )
    assert replacement.reason == "superseded"
    # The successor was never judged: Memory does not hold it.
    assert belief_batches(fake, new) == []


# --- recall -----------------------------------------------------------------------------------


def test_a_recalled_beliefs_memory_is_labelled_belief_and_resolves_to_the_belief_not_a_section(
    atlas: Memory, fake: RecordedHindsight
) -> None:
    belief = atlas.propose(atlas.fact())
    atlas.judge(belief)
    atlas.drain()
    fact_id = fake.derived_fact(f"belief:{belief}")

    answer = atlas.recall_beliefs()

    (memory,) = [m for m in answer["memories"] if m["memory_id"] == fact_id]
    provenance = memory["provenance"]
    assert provenance["state"] == "belief"
    assert provenance["sources"] == []
    (cited,) = provenance["beliefs"]
    assert cited["id"] == belief
    assert (cited["judgement"], cited["statement"]) == ("proven", BELIEF)
    assert answer["counts"]["belief"] == 1
    # Never Evidence: no section stands behind it.
    assert fact_id not in [m for e in answer["evidence"] for m in e["memory_ids"]]
    others = [m for m in answer["memories"] if m["memory_id"] != fact_id]
    assert others and all(m["provenance"]["state"] == "resolved" for m in others)
    # The Belief it resolves to is the one the API serves.
    assert atlas.get(f"/api/v1/beliefs/{cited['id']}")["statement"] == BELIEF


def section_document(atlas: Memory) -> str:
    documents = atlas.memory(atlas.version(URL_EX991)["id"])["documents"]
    return str(documents[0]["document_id"])


def test_an_observation_built_from_a_section_and_a_belief_stays_resolved_with_the_belief_listed(
    atlas: Memory, fake: RecordedHindsight
) -> None:
    belief = atlas.propose(atlas.fact())
    atlas.judge(belief)
    atlas.drain()
    section = section_document(atlas)
    mixed = fake.derive_observation([section, f"belief:{belief}"])
    only_belief = fake.derive_observation([f"belief:{belief}"])

    answer = atlas.recall_beliefs(include_source_facts=True)

    by_id = {m["memory_id"]: m["provenance"] for m in answer["memories"]}
    # Its section is still Evidence (the reading pointers take it); the Belief rides alongside.
    assert by_id[mixed]["state"] == "resolved"
    assert [s["document_id"] for s in by_id[mixed]["sources"]] == [section]
    assert [b["id"] for b in by_id[mixed]["beliefs"]] == [belief]
    # With no section behind it, only the Belief: the observation reads `belief`.
    assert by_id[only_belief]["state"] == "belief"
    assert by_id[only_belief]["sources"] == []


def test_a_replaced_beliefs_old_memory_reads_replaced_not_broken(
    atlas: Memory, fake: RecordedHindsight
) -> None:
    belief = atlas.propose(atlas.fact())
    atlas.judge(belief)
    atlas.drain()
    old_fact = fake.derived_fact(f"belief:{belief}")
    observation = fake.derive_observation([section_document(atlas), f"belief:{belief}"])

    atlas.judge(belief, "disproven", 0.6)
    atlas.drain()

    assert fake.derived_fact(f"belief:{belief}") != old_fact  # the new document's new fact
    answer = atlas.recall_beliefs(include_source_facts=True)
    (memory,) = [m for m in answer["memories"] if m["memory_id"] == observation]
    # Consolidated from the deleted document's fact: not broken, replaced.
    assert memory["provenance"]["state"] == "unverified"
    assert memory["provenance"]["reason"] == "memory_replaced"


def test_available_by_drops_memories_nothing_of_which_was_available_and_counts_them(
    atlas: Memory, fake: RecordedHindsight
) -> None:
    belief = atlas.propose(atlas.fact())  # as of 2026-09-30
    atlas.judge(belief)
    atlas.drain()
    fact_id = fake.derived_fact(f"belief:{belief}")
    everything = atlas.recall_beliefs()
    assert everything["dropped_future"] == 0
    sections = [m for m in everything["memories"] if m["provenance"]["state"] == "resolved"]
    assert sections
    newest = max(s["available_at"] for m in sections for s in m["provenance"]["sources"])

    before_the_belief = atlas.recall_beliefs(available_by="2026-09-01T00:00:00Z")
    assert fact_id not in [m["memory_id"] for m in before_the_belief["memories"]]
    assert "belief" not in before_the_belief["counts"]
    assert before_the_belief["dropped_future"] >= 1
    kept = before_the_belief["memories"]
    assert all(
        s["available_at"] <= "2026-09-01T00:00:00Z"
        for m in kept
        for s in m["provenance"]["sources"]
    )
    assert before_the_belief["dropped_future"] == len(everything["memories"]) - len(kept)

    after = atlas.recall_beliefs(available_by="2026-10-01T00:00:00Z")
    assert fact_id in [m["memory_id"] for m in after["memories"]]
    assert after["dropped_future"] == len(everything["memories"]) - len(after["memories"])
    assert newest <= "2026-10-01T00:00:00Z"


# --- bulk retention ---------------------------------------------------------------------------


def test_bulk_retention_off_holds_section_retains_and_triage_but_not_beliefs(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Any]
) -> None:
    fake, served = hindsight
    fake.script_observation_scopes([])
    fake.script_entities([])
    harness = Memory(database_url, tmp_path, served.url, bulk_retention="off")
    try:
        harness.ingest_lumentum()
        # The ingest ran; its section retains wait behind the switch.
        queued = {row.kind for row in harness.rows("SELECT kind FROM job WHERE status = 'queued'")}
        assert "retain" in queued
        assert not any(
            item["document_id"].startswith("srcv:") for batch in fake.retained() for item in batch
        )
        held = harness.get("/api/v1/queue")
        (retain,) = [p for p in held["pending"] if p["kind"] == "retain"]
        assert retain["budget_held"] == retain["queued"] > 0
        health = harness.get("/api/v1/memory/health")
        assert health["bulk_retention"] == "off"

        belief = harness.propose(harness.fact())
        harness.judge(belief)
        harness.drain()

        assert len(belief_batches(fake, belief)) == 1
        assert not any(
            item["document_id"].startswith("srcv:") for batch in fake.retained() for item in batch
        )
        assert harness.get("/api/v1/memory/health")["beliefs"]["in_memory"] == 1
    finally:
        harness.engine.dispose()


def test_bulk_retention_off_holds_the_daily_consolidation_but_not_one_asked_for(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Any]
) -> None:
    from atlas.retention.consolidation import CONSOLIDATE_KIND

    _, served = hindsight
    harness = Memory(database_url, tmp_path, served.url, bulk_retention="off")
    try:
        queue = JobQueue(harness.engine, actor=harness.actor)
        queue.enqueue(CONSOLIDATE_KIND, "daily", {}, job_class="backfill")
        queue.enqueue(CONSOLIDATE_KIND, "by-hand", {})
        harness.drain()
        status = {
            row.key: row.status
            for row in harness.rows(
                "SELECT idempotency_key AS key, status FROM job WHERE kind = :k", k=CONSOLIDATE_KIND
            )
        }
        assert status["daily"] == "queued"
        assert status["by-hand"] != "queued"
    finally:
        harness.engine.dispose()


def test_a_belief_retain_failing_for_quota_pauses_and_resubmits(
    atlas: Memory, fake: RecordedHindsight
) -> None:
    fake.hold_retains(
        "failed",
        where=lambda ids: any(i.startswith("belief:") for i in ids),
        error_message="Error code: 429 - rate limit exceeded",
        times=1,
    )
    belief = atlas.propose(atlas.fact())
    atlas.judge(belief)
    atlas.drain()
    (memory,) = atlas.rows(
        "SELECT state, operation_id FROM belief_memory WHERE belief_id = :id", id=belief
    )
    assert (memory.state, memory.operation_id) == ("pending", None)
    (job,) = atlas.jobs()
    assert job.status == "queued"
