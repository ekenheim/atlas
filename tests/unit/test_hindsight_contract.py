"""Contract tests: the gateway against every Hindsight 0.10.1 recording.

Each test drives the gateway through the recorded fake with the inputs of a recorded request, so
the fake answers only when the gateway sends exactly what the real server was sent. It then
checks the typed result against the recorded response. Expected values are read from the
recordings, never recomputed. `test_every_recording_is_classified` keeps this file honest: a new
recording must be exercised here, or listed as a route Atlas deliberately doesn't call.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import JsonValue

from atlas.bank_template import BankTemplate
from atlas.hindsight import (
    HindsightGateway,
    HindsightRuleViolation,
    MentalModelDefinition,
    MentalModelTrigger,
    RetainItem,
    TagScope,
)
from tests.fakes.hindsight import RecordedHindsight, Recording, load_recordings

RECORDINGS = load_recordings()
REPO_ROOT = Path(__file__).resolve().parents[2]


def gateway_for(fake: RecordedHindsight, recording: Recording) -> HindsightGateway:
    return HindsightGateway(
        base_url="http://hindsight.test",
        bank_id=recording.bank_id,
        transport=fake.transport,
    )


def when(value: JsonValue) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def as_list(value: JsonValue) -> list[dict[str, JsonValue]]:
    assert isinstance(value, list)
    return cast(list[dict[str, JsonValue]], value)


def as_dict(value: JsonValue) -> dict[str, JsonValue]:
    assert isinstance(value, dict)
    return value


# --- retain: one async batch per call ----------------------------------------------------------

RETAIN_SUBMITS = [
    "retain/02-async",
    "retain/04-batch",
    "upsert/01-v1",
    "upsert/03-v2-same-document-id",
    "upsert/05-v1-own-id",
    "upsert/07-v2-own-id",
]


@pytest.mark.parametrize("name", RETAIN_SUBMITS)
def test_retain_batch_submits_the_recorded_batch_and_returns_its_operation(name: str) -> None:
    fake = RecordedHindsight()
    recording = fake.recording(name)
    items = [
        RetainItem.model_validate(item) for item in as_list(recording.request_object()["items"])
    ]

    submitted = gateway_for(fake, recording).retain_batch(items)

    expected = recording.response_object()
    assert fake.served == [name]
    assert submitted.operation_id == expected["operation_id"]
    assert submitted.items_count == expected["items_count"] == len(items)


# --- operation status --------------------------------------------------------------------------

OPERATION_STATUSES = [
    "retain/03-async-final",
    "retain/05-batch-final",
    "upsert/02-v1-final",
    "upsert/04-v2-same-document-id-final",
    "upsert/06-v1-own-id-final",
    "upsert/08-v2-own-id-final",
    "mental_models/02-create-final",
    "mental_models/05-refresh-final",
    "observations/02-consolidate-final",
    "knowledge_pages/02-create-final",
    "export_import/02-export-final",
    "export_import/05-import-final",
]


@pytest.mark.parametrize("name", OPERATION_STATUSES)
def test_operation_status_parses_every_recorded_operation(name: str) -> None:
    fake = RecordedHindsight()
    recording = fake.recording(name)
    operation_id = recording.path.rsplit("/", 1)[-1]

    operation = gateway_for(fake, recording).operation(operation_id)

    expected = recording.response_object()
    assert fake.served == [name]
    assert operation.operation_id == expected["operation_id"]
    assert operation.status == expected["status"] == "completed"
    assert operation.succeeded and operation.is_terminal
    assert operation.operation_type == expected["operation_type"]
    assert operation.error_message == expected["error_message"]
    assert operation.retry_count == expected["retry_count"]
    assert operation.completed_at == when(expected["completed_at"])
    assert operation.result_metadata == expected["result_metadata"]
    children = expected["child_operations"]
    assert [c.status for c in operation.child_operations] == [
        c["status"] for c in (as_list(children) if children is not None else [])
    ]


def test_waiting_on_a_recorded_operation_returns_its_terminal_status() -> None:
    fake = RecordedHindsight()
    recording = fake.recording("retain/05-batch-final")
    sleeps: list[float] = []
    gateway = HindsightGateway(
        base_url="http://hindsight.test",
        bank_id=recording.bank_id,
        transport=fake.transport,
        sleep=sleeps.append,
    )

    operation = gateway.wait_for_operation(
        str(recording.response_object()["operation_id"]), timeout=60, poll_interval=1
    )

    assert operation.succeeded
    assert fake.served == ["retain/05-batch-final"]
    assert sleeps == []


# --- recall ------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["tags/02-tags-any_strict", "tags/03-tags-all_strict"])
def test_scoped_recall_with_strict_tags_returns_the_recorded_memories(name: str) -> None:
    fake = RecordedHindsight()
    recording = fake.recording(name)
    request = recording.request_object()
    scope = TagScope(
        tags=[str(t) for t in cast(list[str], request["tags"])],
        match=cast(Any, request["tags_match"]),
    )

    result = gateway_for(fake, recording).recall(str(request["query"]), scope=scope)

    assert fake.served == [name]
    assert_memories_match(result.memories, as_list(recording.response_object()["results"]))


def test_unscoped_recall_returns_the_recorded_memories() -> None:
    fake = RecordedHindsight()
    recording = fake.recording("tags/05-no-tags")

    result = gateway_for(fake, recording).recall(
        str(recording.request_object()["query"]), scope=None
    )

    assert fake.served == ["tags/05-no-tags"]
    assert_memories_match(result.memories, as_list(recording.response_object()["results"]))


@pytest.mark.parametrize("name", ["tags/01-tags-any", "tags/04-tags-exact"])
def test_non_strict_tag_matching_is_rejected_before_any_call(name: str) -> None:
    fake = RecordedHindsight()
    recording = fake.recording(name)
    request = recording.request_object()
    gateway = gateway_for(fake, recording)

    with pytest.raises(HindsightRuleViolation, match="tags_match"):
        gateway.recall(
            str(request["query"]),
            scope=TagScope(tags=["company:aurora"], match=cast(Any, request["tags_match"])),
        )

    assert fake.calls == []


def assert_memories_match(memories: list[Any], recorded: list[dict[str, JsonValue]]) -> None:
    assert [m.id for m in memories] == [r["id"] for r in recorded]
    for memory, raw in zip(memories, recorded, strict=True):
        assert memory.text == raw["text"]
        assert memory.type == raw["type"]
        assert memory.document_id == raw["document_id"]
        assert memory.chunk_id == raw["chunk_id"]
        assert memory.tags == raw["tags"]
        assert memory.metadata == (raw["metadata"] or {})
        assert memory.occurred_start == when(raw["occurred_start"])
    # the recordings hold both kinds: observations (no document) and world facts (Atlas metadata)
    assert {m.type for m in memories} == {"observation", "world"}
    world = [m for m in memories if m.type == "world"]
    assert all(m.document_id and "source_version_id" in m.metadata for m in world)


# --- reflect -----------------------------------------------------------------------------------


def test_reflect_with_facts_returns_the_answer_and_its_cited_memories() -> None:
    fake = RecordedHindsight()
    recording = fake.recording("reflect/01-provenance")

    answer = gateway_for(fake, recording).reflect(
        str(recording.request_object()["query"]), scope=None
    )

    expected = recording.response_object()
    based_on = as_dict(expected["based_on"])
    assert fake.served == ["reflect/01-provenance"]
    assert answer.text == expected["text"]
    assert [(m.id, m.type, m.text) for m in answer.memories] == [
        (m["id"], m["type"], m["text"]) for m in as_list(based_on["memories"])
    ]
    assert answer.structured_output is None
    assert answer.structured_output_error is None
    usage = as_dict(expected["usage"])
    assert answer.usage is not None
    assert (answer.usage.input_tokens, answer.usage.output_tokens) == (
        usage["input_tokens"],
        usage["output_tokens"],
    )


def test_reflect_with_a_response_schema_returns_the_structured_output() -> None:
    fake = RecordedHindsight()
    recording = fake.recording("reflect/03-structured")
    request = recording.request_object()

    answer = gateway_for(fake, recording).reflect(
        str(request["query"]),
        scope=None,
        response_schema=as_dict(request["response_schema"]),
        include_facts=False,
    )

    expected = recording.response_object()
    assert fake.served == ["reflect/03-structured"]
    assert answer.structured_output == expected["structured_output"]
    assert answer.structured_output_error is None
    assert answer.memories == []


def test_a_union_type_response_schema_is_rejected_before_any_call() -> None:
    fake = RecordedHindsight()
    recording = fake.recording("reflect/04-structured-union-type")
    assert recording.status == 500  # what 0.10.1 does with it
    request = recording.request_object()

    with pytest.raises(HindsightRuleViolation, match="union"):
        gateway_for(fake, recording).reflect(
            str(request["query"]),
            scope=None,
            response_schema=as_dict(request["response_schema"]),
            include_facts=False,
        )

    assert fake.calls == []


# --- memory lookup (provenance hops) -----------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "reflect/02-resolve-memory",
        "reflect/05-resolve-observation",
        "reflect/06-resolve-source-memory",
        "reflect/07-resolve-source-memory",
    ],
)
def test_memory_lookup_returns_the_recorded_memory(name: str) -> None:
    fake = RecordedHindsight()
    recording = fake.recording(name)

    memory = gateway_for(fake, recording).get_memory(recording.path.rsplit("/", 1)[-1])

    expected = recording.response_object()
    assert fake.served == [name]
    assert (memory.id, memory.type, memory.text) == (
        expected["id"],
        expected["type"],
        expected["text"],
    )
    assert memory.document_id == expected["document_id"]
    assert memory.chunk_id == expected["chunk_id"]
    assert memory.metadata == expected["metadata"]
    assert memory.tags == expected["tags"]
    assert memory.source_memory_ids == expected.get("source_memory_ids", [])
    assert [s.id for s in memory.source_memories] == [
        s["id"] for s in as_list(expected.get("source_memories", []))
    ]


def test_observation_to_world_fact_hops_reach_atlas_metadata() -> None:
    fake = RecordedHindsight()
    observation_rec = fake.recording("reflect/05-resolve-observation")
    gateway = gateway_for(fake, observation_rec)

    observation = gateway.get_memory(observation_rec.path.rsplit("/", 1)[-1])
    facts = [gateway.get_memory(memory_id) for memory_id in observation.source_memory_ids]

    assert observation.type == "observation" and observation.document_id is None
    for fact, name in zip(
        facts, ["reflect/06-resolve-source-memory", "reflect/07-resolve-source-memory"], strict=True
    ):
        expected = fake.recording(name).response_object()
        assert fact.type == "world"
        assert fact.document_id == expected["document_id"]
        assert (
            fact.metadata["source_version_id"] == as_dict(expected["metadata"])["source_version_id"]
        )


# --- listing routes that differ from the docs --------------------------------------------------


def test_observations_are_listed_via_the_memory_list_not_the_405_route() -> None:
    fake = RecordedHindsight()
    recording = fake.recording("observations/04-list-via-memories")
    assert fake.recording("observations/03-list").status == 405

    page = gateway_for(fake, recording).list_observations()

    expected = recording.response_object()
    assert fake.served == ["observations/04-list-via-memories"]
    assert [call.url.path.rsplit("/", 2)[-2:] for call in fake.calls] == [["memories", "list"]]
    assert page.total == expected["total"]
    assert [(m.id, m.type) for m in page.items] == [
        (i["id"], i["fact_type"]) for i in as_list(expected["items"])
    ]
    assert [m.source_memory_ids for m in page.items] == [
        i["source_memory_ids"] for i in as_list(expected["items"])
    ]


def test_knowledge_pages_are_listed_via_the_tree_not_the_405_route() -> None:
    fake = RecordedHindsight()
    recording = fake.recording("knowledge_pages/04-tree")
    assert fake.recording("knowledge_pages/03-list").status == 405

    roots = gateway_for(fake, recording).knowledge_page_tree()

    expected = as_list(recording.response_object()["roots"])
    assert fake.served == ["knowledge_pages/04-tree"]
    assert [(n.id, n.kind, n.name, n.mental_model_id) for n in roots] == [
        (n["id"], n["kind"], n["name"], n["mental_model_id"]) for n in expected
    ]
    assert [len(n.children) for n in roots] == [len(as_list(n["children"])) for n in expected]


# --- documents ---------------------------------------------------------------------------------


def test_document_lookup_returns_its_memory_count_and_atlas_metadata() -> None:
    fake = RecordedHindsight()
    recording = fake.recording("upsert/09-get-document")

    document = gateway_for(fake, recording).get_document("doc-upsert")

    expected = recording.response_object()
    assert fake.served == ["upsert/09-get-document"]
    assert document.id == expected["id"]
    assert document.memory_unit_count == expected["memory_unit_count"]
    assert document.nodes_by_fact_type == expected["nodes_by_fact_type"]
    assert document.document_metadata == expected["document_metadata"]
    assert document.tags == expected["tags"]


# --- bank template and config ------------------------------------------------------------------


def test_bank_template_is_applied_by_dry_run_then_import() -> None:
    fake = RecordedHindsight()
    dry = fake.recording("bank_templates/03-import-dry-run")
    real = fake.recording("bank_templates/04-import")

    applied = gateway_for(fake, dry).apply_bank_template(dry.request_object())

    assert fake.served == ["bank_templates/03-import-dry-run", "bank_templates/04-import"]
    for result, recording in [(applied.dry_run, dry), (applied.applied, real)]:
        expected = recording.response_object()
        assert result.dry_run == expected["dry_run"]
        assert result.config_applied == expected["config_applied"]
        assert result.mental_models_created == expected["mental_models_created"]
        assert result.operation_ids == expected["operation_ids"]


def test_the_research_bank_template_file_is_what_the_server_was_sent() -> None:
    # spikes/hindsight/record_bank_template.py recorded template 1.0.0 (missions,
    # dispositions, directives). 1.1.0 added only the mental models, whose import the fake
    # derives from that recording (tests/fakes/hindsight.py); editing anything else in the
    # template fails here until its dry run is re-recorded.
    fake = RecordedHindsight()
    dry = fake.recording("research_template/01-import-dry-run")
    real = fake.recording("research_template/02-import")
    template = BankTemplate.load(REPO_ROOT / "configs" / "hindsight" / "bank-template.json")
    model_ids = [model.id for model in template.mental_models]

    applied = gateway_for(fake, dry).apply_bank_template(template.manifest)

    assert fake.served == [
        "research_template/01-import-dry-run (derived)",
        "research_template/02-import (derived)",
    ]
    assert model_ids == ["theme-status", "bottlenecks"]
    for result, recording in [(applied.dry_run, dry), (applied.applied, real)]:
        expected = recording.response_object()
        assert result.dry_run == expected["dry_run"]
        assert result.config_applied == expected["config_applied"]
        assert result.directives_created == expected["directives_created"]
        assert result.mental_models_created == model_ids
    # The dry run queues nothing; the import queues one refresh per model (as recorded in
    # bank_templates/03-import-dry-run and 04-import).
    assert applied.dry_run.operation_ids == []
    assert len(set(applied.applied.operation_ids)) == len(model_ids)


@pytest.mark.parametrize(
    "name",
    [
        "bank_config/02-get-config",
        "bank_templates/05-imported-config",
        "research_template/03-imported-config",
    ],
)
def test_bank_config_returns_the_resolved_config(name: str) -> None:
    fake = RecordedHindsight()
    recording = fake.recording(name)

    config = gateway_for(fake, recording).bank_config()

    expected = recording.response_object()
    assert fake.served == [name]
    assert config.bank_id == expected["bank_id"]
    assert config.config == expected["config"]
    assert config.overrides == expected["overrides"]


# --- mental models -----------------------------------------------------------------------------


def test_mental_model_create_submits_the_definition_and_returns_its_operation() -> None:
    fake = RecordedHindsight()
    recording = fake.recording("mental_models/01-create")
    request = recording.request_object()
    trigger = as_dict(request["trigger"])
    definition = MentalModelDefinition(
        id=str(request["id"]),
        name=str(request["name"]),
        source_query=str(request["source_query"]),
        trigger=MentalModelTrigger(
            refresh_after_consolidation=bool(trigger["refresh_after_consolidation"]),
            min_refresh_interval_seconds=cast(int, trigger["min_refresh_interval_seconds"]),
        ),
    )

    submitted = gateway_for(fake, recording).create_mental_model(definition)

    expected = recording.response_object()
    assert fake.served == ["mental_models/01-create"]
    assert submitted.mental_model_id == expected["mental_model_id"]
    assert submitted.operation_id == expected["operation_id"]


def test_mental_model_refresh_returns_its_operation() -> None:
    fake = RecordedHindsight()
    recording = fake.recording("mental_models/04-refresh")

    submitted = gateway_for(fake, recording).refresh_mental_model("theme-status")

    assert fake.served == ["mental_models/04-refresh"]
    assert submitted.operation_id == recording.response_object()["operation_id"]


def test_mental_model_get_returns_content_trigger_and_citations() -> None:
    fake = RecordedHindsight()
    recording = fake.recording("mental_models/03-get")

    model = gateway_for(fake, recording).get_mental_model("theme-status")

    expected = recording.response_object()
    trigger = as_dict(expected["trigger"])
    based_on = as_dict(as_dict(expected["reflect_response"])["based_on"])
    assert fake.served == ["mental_models/03-get"]
    assert (model.id, model.name, model.content) == (
        expected["id"],
        expected["name"],
        expected["content"],
    )
    assert model.last_refreshed_at == when(expected["last_refreshed_at"])
    assert model.is_stale is expected["is_stale"]
    assert model.trigger.refresh_after_consolidation is trigger["refresh_after_consolidation"]
    assert model.trigger.min_refresh_interval_seconds == trigger["min_refresh_interval_seconds"]
    cited = [
        (m["id"], m["type"]) for m in as_list(based_on["world"]) + as_list(based_on["observation"])
    ]
    assert sorted((m.id, m.type) for m in model.based_on) == sorted(cited)


@pytest.mark.parametrize("name", ["mental_models/06-history", "mental_models/07-history-check"])
def test_mental_model_history_returns_each_previous_revision(name: str) -> None:
    # both recordings answer the same request; serve only the one under test
    other = {"mental_models/06-history", "mental_models/07-history-check"} - {name}
    fake = RecordedHindsight({k: v for k, v in RECORDINGS.items() if k not in other})
    recording = fake.recording(name)

    history = gateway_for(fake, recording).mental_model_history("theme-status")

    expected = as_list(recording.response_body)
    assert fake.served == [name]
    assert [(h.previous_content, h.changed_at) for h in history] == [
        (e["previous_content"], when(e["changed_at"])) for e in expected
    ]
    assert [len(h.based_on) for h in history] == [
        sum(
            len(as_list(v))
            for k, v in as_dict(as_dict(e["previous_reflect_response"])["based_on"]).items()
            if k not in ("directives", "mental-models")
        )
        if e["previous_reflect_response"] is not None
        else 0
        for e in expected
    ]


# --- LLM request log ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["llm_requests/01-stats", "export_import/06-import-llm-requests"])
def test_llm_request_stats_returns_the_recorded_buckets(name: str) -> None:
    fake = RecordedHindsight()
    recording = fake.recording(name)

    stats = gateway_for(fake, recording).llm_request_stats()

    expected = recording.response_object()
    assert fake.served == [name]
    assert (stats.bank_id, stats.period) == (expected["bank_id"], expected["period"])
    assert [
        (b.total, b.statuses, b.tokens.input, b.tokens.output, b.tokens.cached)
        for b in stats.buckets
    ] == [
        (
            b["total"],
            b["statuses"],
            as_dict(b["tokens"])["input"],
            as_dict(b["tokens"])["output"],
            as_dict(b["tokens"])["cached"],
        )
        for b in as_list(expected["buckets"])
    ]


# --- server: health and version ---------------------------------------------------------------


def server_gateway(fake: RecordedHindsight) -> HindsightGateway:
    # /health and /version aren't bank-scoped; any bank will do.
    return HindsightGateway(
        "http://hindsight.test", "atlas-ai-infrastructure", transport=fake.transport
    )


def test_server_health_reports_a_healthy_server() -> None:
    fake = RecordedHindsight()
    expected = fake.recording("monitoring/01-health").response_object()

    health = server_gateway(fake).server_health()

    assert fake.served == ["monitoring/01-health"]
    assert (health.status, health.database) == (expected["status"], expected["database"])
    assert health.is_healthy


def test_server_version_reports_the_pinned_api_version() -> None:
    fake = RecordedHindsight()
    expected = fake.recording("monitoring/02-version").response_object()

    version = server_gateway(fake).server_version()

    assert fake.served == ["monitoring/02-version"]
    assert version.api_version == expected["api_version"] == "0.10.1"
    assert version.features == expected["features"]


# --- completeness ------------------------------------------------------------------------------

EXERCISED = {
    *RETAIN_SUBMITS,
    *OPERATION_STATUSES,
    "tags/01-tags-any",
    "tags/02-tags-any_strict",
    "tags/03-tags-all_strict",
    "tags/04-tags-exact",
    "tags/05-no-tags",
    "reflect/01-provenance",
    "reflect/02-resolve-memory",
    "reflect/03-structured",
    "reflect/04-structured-union-type",
    "reflect/05-resolve-observation",
    "reflect/06-resolve-source-memory",
    "reflect/07-resolve-source-memory",
    "observations/03-list",
    "observations/04-list-via-memories",
    "knowledge_pages/03-list",
    "knowledge_pages/04-tree",
    "upsert/09-get-document",
    "bank_templates/03-import-dry-run",
    "bank_templates/04-import",
    "bank_templates/05-imported-config",
    "bank_config/02-get-config",
    "research_template/01-import-dry-run",
    "research_template/02-import",
    "research_template/03-imported-config",
    "monitoring/01-health",
    "monitoring/02-version",
    "mental_models/01-create",
    "mental_models/03-get",
    "mental_models/04-refresh",
    "mental_models/06-history",
    "mental_models/07-history-check",
    "llm_requests/01-stats",
    "export_import/06-import-llm-requests",
}

NOT_CALLED_BY_ATLAS = {
    "bank_config/01-create-bank": "bank config comes from the template import, not the config API",
    "bank_templates/01-schema": "the template is versioned in the repo; the schema isn't fetched",
    "bank_templates/02-export": "Atlas applies its template; it doesn't export one",
    "export_import/01-export": "document transfer is a Phase 6a question",
    "export_import/03-download": "document transfer is a Phase 6a question (binary not recorded)",
    "export_import/04-import": "document transfer is a Phase 6a question",
    "knowledge_pages/01-create": "no knowledge pages in Phase 2",
    "knowledge_pages/05-get-page": "no knowledge pages in Phase 2",
    "observations/01-consolidate": "consolidation runs automatically in the bank",
    "operations/01-list": "Atlas tracks each operation it submitted by ID",
    "retain/01-sync": "Atlas retains only asynchronously, tracked as an operation",
    "temporal/01-window-2024": "the temporal window is not a hard filter in 0.10.1",
}


def test_every_recording_is_classified() -> None:
    assert len(RECORDINGS) == 63
    assert EXERCISED.isdisjoint(NOT_CALLED_BY_ATLAS)
    assert EXERCISED | set(NOT_CALLED_BY_ATLAS) == set(RECORDINGS)
