"""The recorded fake's derived retains change only the fields its docstring names."""

from datetime import UTC, datetime

import pytest

from atlas.hindsight import HindsightGateway, HindsightNotFound, RetainItem, TagScope
from tests.fakes.hindsight import (
    DERIVED_DOCUMENT,
    DERIVED_FACT,
    DERIVED_OBSERVATION,
    DERIVED_RECALL,
    DERIVED_REFLECT,
    DERIVED_RETAIN,
    DERIVED_RETAIN_FINAL,
    ChunkContent,
    RecordedHindsight,
    UnrecordedRequest,
)

BANK = "atlas-research-test"
ITEMS = [
    RetainItem(
        content=f"Section {anchor} text.",
        document_id=f"srcv:00000000-0000-4000-8000-000000000001:{anchor}",
        timestamp=datetime(2026, 8, 11, 20, 24, 11, tzinfo=UTC),
        metadata={"source_version_id": "00000000-0000-4000-8000-000000000001"},
        tags=["company:x", "form:8-K"],
    )
    for anchor in ("cover", "item-2-02")
]


def gateway(fake: RecordedHindsight) -> HindsightGateway:
    return HindsightGateway("http://hindsight.test", BANK, transport=fake.transport)


def test_unrecorded_retains_are_refused_unless_derivation_is_on() -> None:
    with pytest.raises(UnrecordedRequest):
        gateway(RecordedHindsight()).retain_batch(ITEMS)


def test_a_derived_retain_changes_only_its_identity_fields() -> None:
    fake = RecordedHindsight()
    fake.derive_retains()
    client = gateway(fake)

    submitted = client.retain_batch(ITEMS)
    again = client.retain_batch(ITEMS)
    other = client.retain_batch(ITEMS[:1])
    operation = client.operation(submitted.operation_id)
    document = client.get_document(ITEMS[1].document_id)

    # Each submission is its own operation, even of an identical batch (a resubmission), and
    # the IDs are the same from one fake to the next.
    assert again.operation_id != submitted.operation_id
    fresh = RecordedHindsight()
    fresh.derive_retains()
    assert gateway(fresh).retain_batch(ITEMS).operation_id == submitted.operation_id
    assert other.operation_id != submitted.operation_id
    assert (submitted.bank_id, submitted.items_count) == (BANK, 2)
    recorded_retain = fake.recording(DERIVED_RETAIN).response_object()
    served = fake.calls[0]
    assert served.url.path == f"/v1/default/banks/{BANK}/memories"
    final = fake.recording(DERIVED_RETAIN_FINAL).response_object()
    assert operation.operation_id == submitted.operation_id
    assert operation.status == final["status"] == "completed"
    assert operation.result_metadata == final["result_metadata"]
    recorded_document = fake.recording(DERIVED_DOCUMENT).response_object()
    assert document.id == ITEMS[1].document_id
    assert document.tags == ITEMS[1].tags
    assert document.document_metadata == ITEMS[1].metadata
    assert document.memory_unit_count == recorded_document["memory_unit_count"]
    assert document.nodes_by_fact_type == recorded_document["nodes_by_fact_type"]
    assert set(recorded_retain) >= {"bank_id", "items_count", "operation_id"}
    assert fake.served == [
        f"{DERIVED_RETAIN} (derived)",
        f"{DERIVED_RETAIN} (derived)",
        f"{DERIVED_RETAIN} (derived)",
        f"{DERIVED_RETAIN_FINAL} (derived)",
        f"{DERIVED_DOCUMENT} (derived)",
    ]
    assert [len(batch) for batch in fake.retained()] == [2, 2, 1]


def test_zero_facts_and_held_retains_are_derived_on_request() -> None:
    fake = RecordedHindsight()
    fake.derive_retains()
    fake.report_zero_facts(lambda document_id: document_id.endswith(":cover"))
    fake.hold_retains("failed", where=lambda ids: len(ids) == 1)
    client = gateway(fake)

    kept = client.retain_batch(ITEMS)
    held = client.retain_batch(ITEMS[:1])

    assert client.operation(kept.operation_id).status == "completed"
    assert client.operation(held.operation_id).status == "failed"
    assert client.get_document(ITEMS[0].document_id).memory_unit_count == 0
    assert set(client.get_document(ITEMS[0].document_id).nodes_by_fact_type.values()) == {0}
    assert client.get_document(ITEMS[1].document_id).memory_unit_count > 0


def test_unknown_documents_and_operations_are_still_unrecorded() -> None:
    fake = RecordedHindsight()
    fake.derive_retains()

    with pytest.raises(UnrecordedRequest):
        gateway(fake).get_document("srcv:never-retained:cover")
    with pytest.raises(UnrecordedRequest):
        gateway(fake).operation("00000000-0000-4000-8000-00000000dead")


def test_a_held_retain_can_carry_an_error_message_for_its_first_batches_only() -> None:
    fake = RecordedHindsight()
    fake.derive_retains()
    fake.hold_retains(
        "failed", where=lambda ids: True, error_message="Error code: 429 - rate limit", times=1
    )
    client = gateway(fake)

    failed = client.operation(client.retain_batch(ITEMS).operation_id)
    resubmitted = client.operation(client.retain_batch(ITEMS).operation_id)

    assert (failed.status, failed.error_message) == ("failed", "Error code: 429 - rate limit")
    final = fake.recording(DERIVED_RETAIN_FINAL).response_object()
    assert (resubmitted.status, resubmitted.error_message) == (
        final["status"],
        final["error_message"],
    )


# --- derived memories, recall and reflect ---


def derived_memories() -> tuple[RecordedHindsight, HindsightGateway]:
    fake = RecordedHindsight()
    fake.derive_memories()
    client = gateway(fake)
    client.retain_batch(ITEMS)
    return fake, client


def test_a_derived_fact_changes_only_its_identity_and_content_fields() -> None:
    fake, client = derived_memories()
    fact_id = fake.derived_fact(ITEMS[0].document_id)

    fact = client.get_memory(fact_id)

    recorded = fake.recording(DERIVED_FACT).response_object()
    assert fact.id == fact_id != recorded["id"]
    assert fact.type == recorded["type"] == "world"
    assert fact.document_id == ITEMS[0].document_id
    assert fact.metadata == ITEMS[0].metadata
    assert fact.tags == ITEMS[0].tags
    assert fact.text == ITEMS[0].content
    assert fact.occurred_start is not None  # as recorded
    assert fact.state == recorded["state"]


def test_a_derived_observation_lists_its_source_facts() -> None:
    fake, client = derived_memories()
    sources = [fake.derived_fact(item.document_id) for item in ITEMS]
    observation_id = fake.derive_observation([item.document_id for item in ITEMS])

    observation = client.get_memory(observation_id)

    assert observation.type == "observation"
    assert observation.document_id is None
    assert observation.source_memory_ids == sources
    assert [m.id for m in observation.source_memories] == sources
    assert observation.tags == ITEMS[0].tags
    assert fake.served[-1] == f"{DERIVED_OBSERVATION} (derived)"


def test_a_derived_recall_matches_tags_strictly_and_forgotten_memories_are_404() -> None:
    fake, client = derived_memories()
    observation_id = fake.derive_observation([ITEMS[0].document_id])
    forgotten = fake.derived_fact(ITEMS[1].document_id)
    fake.forget(forgotten)

    in_scope = client.recall("q", scope=TagScope(["company:x"], "any_strict"))
    all_of = client.recall("q", scope=TagScope(["company:x", "form:10-K"], "all_strict"))
    out_of_scope = client.recall("q", scope=TagScope(["company:y"], "any_strict"))

    assert [m.id for m in in_scope.memories] == [
        observation_id,
        fake.derived_fact(ITEMS[0].document_id),
    ]
    assert all_of.memories == [] and out_of_scope.memories == []
    assert fake.served[-1] == f"{DERIVED_RECALL} (derived)"
    with pytest.raises(HindsightNotFound):
        client.get_memory(forgotten)
    assert client.get_memory(observation_id).source_memory_ids == [
        fake.derived_fact(ITEMS[0].document_id)
    ]


def test_a_scripted_reflect_changes_only_its_answer_and_citations() -> None:
    fake, client = derived_memories()
    fact_id = fake.derived_fact(ITEMS[0].document_id)
    fake.script_reflect("An answer.", [fact_id, ChunkContent(ITEMS[1].document_id)])

    answer = client.reflect("q", scope=TagScope(["company:x"], "any_strict"))

    recorded = fake.recording(DERIVED_REFLECT).response_object()
    assert answer.text == "An answer."
    assert [(m.id, m.type) for m in answer.memories] == [(fact_id, "world"), (None, None)]
    assert answer.memories[1].text == ITEMS[1].content
    assert answer.usage is not None
    assert answer.usage.model_dump() == recorded["usage"]
    with pytest.raises(UnrecordedRequest):  # one scripted answer, one reflect
        client.reflect("q", scope=TagScope(["company:x"], "any_strict"))
