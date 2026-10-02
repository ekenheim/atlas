"""The recorded fake's derived retains change only the fields its docstring names."""

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from atlas.hindsight import (
    HindsightGateway,
    HindsightHTTPError,
    HindsightNotFound,
    RetainItem,
    TagScope,
)
from tests.fakes.hindsight import (
    DERIVED_CHUNKS,
    DERIVED_CONSOLIDATE,
    DERIVED_CONSOLIDATE_FINAL,
    DERIVED_DOCUMENT,
    DERIVED_FACT,
    DERIVED_MEMORY_LIST,
    DERIVED_MENTAL_MODEL,
    DERIVED_OBSERVATION,
    DERIVED_RECALL,
    DERIVED_REFLECT,
    DERIVED_RETAIN,
    DERIVED_RETAIN_FINAL,
    DERIVED_TEMPLATE_DRY_RUN,
    DERIVED_TEMPLATE_IMPORT,
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


def test_a_failed_recall_is_answered_by_query_for_its_first_times_only() -> None:
    fake, client = derived_memories()
    scope = TagScope(["company:x"], "any_strict")
    fake.fail_recalls(lambda query: query == "broken", status=500)
    fake.fail_recalls(lambda query: query == "down", status=503, times=1)

    with pytest.raises(HindsightHTTPError) as broken:
        client.recall("broken", scope=scope)
    with pytest.raises(HindsightHTTPError) as down:
        client.recall("down", scope=scope)
    assert fake.served[-1] == "memories/recall 503 (derived, hand-written body)"
    recovered = client.recall("down", scope=scope)
    with pytest.raises(HindsightHTTPError):
        client.recall("broken", scope=scope)  # every time

    assert (broken.value.status_code, down.value.status_code) == (500, 503)
    assert len(recovered.memories) == len(client.recall("other", scope=scope).memories) == 2


def test_a_scripted_fact_text_changes_only_the_fact_s_text() -> None:
    fake, client = derived_memories()
    scope = TagScope(["company:x"], "any_strict")
    fact_id = fake.derived_fact(ITEMS[0].document_id)
    before = client.get_memory(fact_id)

    fake.script_fact_text(ITEMS[0].document_id, "A paraphrase, in Hindsight's own words.")

    after = client.get_memory(fact_id)
    assert after.text == "A paraphrase, in Hindsight's own words."
    assert after.model_dump(exclude={"text"}) == before.model_dump(exclude={"text"})
    recalled = {memory.id: memory.text for memory in client.recall("q", scope=scope).memories}
    assert recalled[fact_id] == after.text
    other = fake.derived_fact(ITEMS[1].document_id)
    assert recalled[other] == ITEMS[1].content  # the other document's fact is as derived


CHUNKED = RetainItem(
    content=(
        "Item 1. Business\n\nWe make lasers for data centers.\n\n"
        "Our customers include hyperscalers, and demand outpaces supply this year.\n"
    ),
    document_id="srcv:00000000-0000-4000-8000-000000000002:part-i-item-1",
    timestamp=datetime(2026, 8, 11, 20, 24, 11, tzinfo=UTC),
    metadata={"source_version_id": "00000000-0000-4000-8000-000000000002"},
    tags=["company:x", "form:10-K"],
)


def test_derived_chunks_are_verbatim_slices_listed_and_recalled_by_chunk_id() -> None:
    # Memory-quality ticket 08. Without `derive_chunks` a derived document lists no chunk and
    # a recall carries none.
    fake = RecordedHindsight()
    fake.derive_memories()
    client = gateway(fake)
    client.retain_batch([CHUNKED])
    scope = TagScope(["company:x"], "any_strict")
    assert client.document_chunks(CHUNKED.document_id) == []
    assert client.recall("q", scope=scope, include_chunks=True).chunks == {}

    fake.derive_chunks(size=40)
    fake.script_fact_chunk(CHUNKED.document_id, 2)

    listed = client.document_chunks(CHUNKED.document_id)
    texts = [
        "Item 1. Business",
        "We make lasers for data centers.",
        "Our customers include hyperscalers, and",
        "demand outpaces supply this year.",
    ]
    assert [c.chunk_text for c in listed] == texts == fake.derived_chunks(CHUNKED.document_id)
    assert all(text in CHUNKED.content for text in texts)
    assert [c.chunk_id for c in listed] == [f"{BANK}_{CHUNKED.document_id}_{i}" for i in range(4)]
    served = fake.recording(DERIVED_CHUNKS).name + " (derived)"
    assert served in fake.served
    answer = client.recall("q", scope=scope, include_chunks=True)
    [fact] = answer.memories
    assert fact.chunk_id == f"{BANK}_{CHUNKED.document_id}_2"
    assert {key: (c.text, c.chunk_index, c.truncated) for key, c in answer.chunks.items()} == {
        fact.chunk_id: (texts[2], 2, False)
    }

    fake.script_chunk_text(CHUNKED.document_id, 2, "Not a slice.")
    assert client.document_chunks(CHUNKED.document_id)[2].chunk_text == "Not a slice."


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


# --- the template import and mental models (derived by default) ---------------------------------

MENTAL_MODEL = {
    "id": "theme-status",
    "name": "Theme status",
    "source_query": "What are the developments?",
    "max_tokens": 1024,
    "trigger": {
        "refresh_after_consolidation": False,
        "refresh_cron": "0 6 * * *",
        "min_refresh_interval_seconds": 43200,
    },
}
REFRESHED_AT = datetime(2026, 10, 1, 6, 30, tzinfo=UTC)


def imported(fake: RecordedHindsight, client: HindsightGateway) -> None:
    manifest = fake.recording(DERIVED_TEMPLATE_IMPORT).request_object()
    client.apply_bank_template({**manifest, "mental_models": [MENTAL_MODEL]})


def test_a_template_import_differing_only_in_mental_models_is_derived() -> None:
    fake = RecordedHindsight()
    client = gateway(fake)
    manifest = fake.recording(DERIVED_TEMPLATE_IMPORT).request_object()

    applied = client.apply_bank_template({**manifest, "mental_models": [MENTAL_MODEL]})

    recorded = fake.recording(DERIVED_TEMPLATE_IMPORT).response_object()
    assert fake.served == [
        f"{DERIVED_TEMPLATE_DRY_RUN} (derived)",
        f"{DERIVED_TEMPLATE_IMPORT} (derived)",
    ]
    assert applied.applied.bank_id == BANK
    assert applied.applied.mental_models_created == ["theme-status"]
    assert applied.applied.directives_created == recorded["directives_created"]
    assert applied.dry_run.operation_ids == []
    assert len(applied.applied.operation_ids) == 1
    with pytest.raises(UnrecordedRequest):  # anything else changed: not derived
        client.apply_bank_template({**manifest, "directives": [], "mental_models": []})


def test_a_template_import_with_other_bank_fields_is_derived_if_the_0_10_2_schema_takes_them() -> (
    None
):
    fake = RecordedHindsight()
    client = gateway(fake)
    manifest = fake.recording(DERIVED_TEMPLATE_IMPORT).request_object()
    bank = cast(dict[str, Any], manifest["bank"])
    labels = [{"key": "layer", "type": "multi-values", "tag": True, "values": [{"value": "epi"}]}]

    applied = client.apply_bank_template(
        {**manifest, "bank": {**bank, "retain_mission": "Other.", "entity_labels": labels}}
    )

    assert applied.applied.config_applied is True
    assert fake.served[-1] == f"{DERIVED_TEMPLATE_IMPORT} (derived)"
    for refused in (
        {**bank, "retain_mision": "A misspelt field."},  # not a field of the schema
        {**bank, "entity_labels": [{"type": "value"}]},  # a label group needs its key
    ):
        with pytest.raises(UnrecordedRequest):
            client.apply_bank_template({**manifest, "bank": refused})


LAYER_GROUP = {
    "key": "layer",
    "type": "multi-values",
    "optional": True,
    "tag": True,
    "values": [{"value": "chip-laser"}, {"value": "module"}],
}


def labelled(labels: list[dict[str, Any]] | None) -> tuple[RecordedHindsight, HindsightGateway]:
    """Derived memories in a bank whose imported template has these entity labels."""
    fake, client = derived_memories()
    manifest = fake.recording(DERIVED_TEMPLATE_IMPORT).request_object()
    bank = cast(dict[str, Any], manifest["bank"])
    client.apply_bank_template({**manifest, "bank": {**bank, "entity_labels": labels}})
    return fake, client


def test_scripted_labels_of_a_tag_group_are_tags_on_the_derived_fact() -> None:
    fake, client = labelled([LAYER_GROUP])
    laser, module = (fake.derived_fact(item.document_id) for item in ITEMS)
    before = client.get_memory(module)

    # "layer:foundry" is no value of the group and "grade:a" no group: dropped, as the docs say
    # of a value outside an enum group's list.
    fake.script_fact_labels(ITEMS[0].document_id, ["layer:chip-laser", "layer:foundry"])
    fake.script_fact_labels(ITEMS[1].document_id, ["layer:module", "layer:chip-laser", "grade:a"])

    # As recorded (entity_labels/04): the item's tags, then the fact's label tags.
    tags = ["company:x", "form:8-K"]  # every item's
    assert client.get_memory(laser).tags == [*tags, "layer:chip-laser"]
    after = client.get_memory(module)
    assert after.tags == [*tags, "layer:module", "layer:chip-laser"]
    assert after.model_dump(exclude={"tags"}) == before.model_dump(exclude={"tags"})
    listed = client.document_memories(ITEMS[0].document_id)
    assert [m.tags for m in listed] == [[*tags, "layer:chip-laser"]]


def test_a_recall_filtered_by_a_label_tag_returns_only_the_facts_carrying_it() -> None:
    fake, client = labelled([LAYER_GROUP])
    fake.script_fact_labels(ITEMS[0].document_id, ["layer:chip-laser"])
    fake.script_fact_labels(ITEMS[1].document_id, ["layer:module"])

    chip_laser = client.recall("q", scope=TagScope(["layer:chip-laser"], "any_strict"))
    with_company = client.recall("q", scope=TagScope(["company:x", "layer:module"], "all_strict"))
    other_layer = client.recall("q", scope=TagScope(["layer:epi"], "any_strict"))

    assert [m.id for m in chip_laser.memories] == [fake.derived_fact(ITEMS[0].document_id)]
    assert [m.id for m in with_company.memories] == [fake.derived_fact(ITEMS[1].document_id)]
    assert other_layer.memories == []


def test_labels_become_tags_only_in_a_bank_whose_group_has_tag_true() -> None:
    untagged, untagged_client = labelled([{**LAYER_GROUP, "tag": False}])
    unlabelled, unlabelled_client = labelled(None)
    for fake, client in ((untagged, untagged_client), (unlabelled, unlabelled_client)):
        fake.script_fact_labels(ITEMS[0].document_id, ["layer:chip-laser"])

        assert client.get_memory(fake.derived_fact(ITEMS[0].document_id)).tags == ITEMS[0].tags
        assert client.recall("q", scope=TagScope(["layer:chip-laser"], "any_strict")).memories == []


def test_an_imported_mental_model_is_derived_until_and_after_its_refreshes() -> None:
    fake, client = derived_memories()
    imported(fake, client)
    fact_id = fake.derived_fact(ITEMS[0].document_id)
    observation_id = fake.derive_observation([ITEMS[1].document_id])

    before = client.get_mental_model("theme-status")
    assert client.mental_model_history("theme-status") == []
    with pytest.raises(UnrecordedRequest):  # a refresh nobody scripted
        client.refresh_mental_model("theme-status")
    fake.script_refresh(
        "theme-status", "First.", [fact_id, observation_id], refreshed_at=REFRESHED_AT
    )
    submitted = client.refresh_mental_model("theme-status")
    fake.hold_operation(submitted.operation_id, "processing", polls=1)
    processing = client.operation(submitted.operation_id)
    unchanged = client.get_mental_model("theme-status")
    done = client.operation(submitted.operation_id)
    after = client.get_mental_model("theme-status")

    recorded = fake.recording(DERIVED_MENTAL_MODEL).response_object()
    assert (before.name, before.source_query, before.content) == (
        "Theme status",
        "What are the developments?",
        "Generating content...\n",
    )
    assert before.trigger.refresh_cron == "0 6 * * *"
    assert before.trigger.min_refresh_interval_seconds == 43200
    assert before.trigger.refresh_after_consolidation is False
    assert (before.last_refreshed_at, before.is_stale, before.based_on) == (None, True, [])
    assert before.created_at == datetime.fromisoformat(str(recorded["created_at"]))
    assert (processing.status, unchanged.content) == ("processing", before.content)
    assert done.status == "completed"
    assert done.result_metadata["mental_model_id"] == "theme-status"
    assert done.result_metadata["content_len"] == len("First.")
    assert (after.content, after.last_refreshed_at, after.is_stale) == (
        "First.",
        REFRESHED_AT,
        False,
    )
    assert [(m.id, m.type) for m in after.based_on] == [
        (fact_id, "world"),
        (observation_id, "observation"),
    ]
    [revision] = client.mental_model_history("theme-status")
    assert (revision.previous_content, revision.changed_at, revision.based_on) == (
        "Generating content...\n",
        REFRESHED_AT,
        [],
    )

    fake.apply_refresh(
        "theme-status", "Second.", [fact_id], refreshed_at=REFRESHED_AT.replace(day=2)
    )
    newest, oldest = client.mental_model_history("theme-status")
    assert newest.previous_content == "First."
    assert [m.id for m in newest.based_on] == [fact_id, observation_id]
    assert oldest.previous_content == "Generating content...\n"
    client.retain_batch(ITEMS[:1])  # a later write makes it stale
    assert client.get_mental_model("theme-status").is_stale is True
    assert fake.refreshes_requested() == ["theme-status", "theme-status"]


def test_a_derived_documents_memories_are_listed_by_document() -> None:
    fake = RecordedHindsight()
    fake.derive_retains()
    fake.report_zero_facts(lambda document_id: document_id.endswith(":cover"))
    client = gateway(fake)
    client.retain_batch(ITEMS)

    listed = client.document_memories(ITEMS[1].document_id)
    empty = client.document_memories(ITEMS[0].document_id)

    recorded = fake.recording(DERIVED_MEMORY_LIST).response_object()
    first = cast(list[dict[str, Any]], recorded["items"])[0]
    (fact,) = listed
    assert fact.id == fake.derived_fact(ITEMS[1].document_id) != first["id"]
    assert (fact.type, fact.document_id) == ("world", ITEMS[1].document_id)
    assert (fact.tags, fact.metadata) == (ITEMS[1].tags, ITEMS[1].metadata)
    assert fact.source_memory_ids == []
    assert fact.state == first["state"]  # as recorded
    assert empty == []  # a zero-fact document holds no memories
    assert fake.served[-1] == f"{DERIVED_MEMORY_LIST} (derived)"
    with pytest.raises(UnrecordedRequest):
        client.document_memories("srcv:never-retained:cover")


def test_derived_banks_are_separate_and_a_deleted_bank_is_gone() -> None:
    fake = RecordedHindsight()
    fake.derive_memories()
    research, replay = (
        gateway(fake),
        HindsightGateway("http://hindsight.test", "atlas-replay-test", transport=fake.transport),
    )
    research.retain_batch(ITEMS)
    replay.retain_batch(ITEMS[:1])
    research_fact = fake.derived_fact(ITEMS[1].document_id)
    scope = TagScope(["company:x"], "any_strict")

    recalled = replay.recall("anything", scope=scope)
    with pytest.raises(HindsightNotFound):
        replay.get_memory(research_fact)
    with pytest.raises(KeyError):
        fake.derived_fact(ITEMS[0].document_id)  # held by both banks: name one
    replay_fact = fake.derived_fact(ITEMS[0].document_id, "atlas-replay-test")
    deleted = replay.delete_bank()

    assert [m.document_id for m in recalled.memories] == [ITEMS[0].document_id]
    assert recalled.memories[0].id == replay_fact
    assert recalled.memories[0].id != fake.derived_fact(ITEMS[0].document_id, BANK)
    assert deleted.success is True
    assert deleted.deleted_count == 1
    assert fake.deleted_banks == ["atlas-replay-test"]
    assert fake.bank_documents("atlas-replay-test") == []
    assert fake.bank_documents(BANK) == [item.document_id for item in ITEMS]
    with pytest.raises(HindsightNotFound):
        replay.get_memory(replay_fact)  # gone with its bank
    assert len(fake.retained("atlas-replay-test")) == 1


def test_a_derived_consolidation_changes_only_its_operation_id() -> None:
    fake = RecordedHindsight()
    client = gateway(fake)

    submitted = client.consolidate()
    operation = client.operation(submitted.operation_id)
    fake.hold_consolidations("processing", polls=1)
    held = client.consolidate()

    recorded = fake.recording(DERIVED_CONSOLIDATE_FINAL).response_object()
    assert (
        submitted.operation_id
        != fake.recording(DERIVED_CONSOLIDATE).response_object()["operation_id"]
    )
    assert operation.status == recorded["status"] == "completed"
    assert operation.operation_type == recorded["operation_type"]
    assert client.operation(held.operation_id).status == "processing"
    assert client.operation(held.operation_id).status == "completed"
