"""The recorded fake's derived retains change only the fields its docstring names."""

from datetime import UTC, datetime

import pytest

from atlas.hindsight import HindsightGateway, RetainItem
from tests.fakes.hindsight import (
    DERIVED_DOCUMENT,
    DERIVED_RETAIN,
    DERIVED_RETAIN_FINAL,
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

    assert again.operation_id == submitted.operation_id  # an identical request, the same answer
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
