"""Contract tests: the gateway against every Hindsight recording (0.10.1, and 0.10.2's
memory-quality features).

Each test drives the gateway through the recorded fake with the inputs of a recorded request, so
the fake answers only when the gateway sends exactly what the real server was sent. It then
checks the typed result against the recorded response. Expected values are read from the
recordings, never recomputed. `test_every_recording_is_classified` keeps this file honest: a new
recording must be exercised here, or listed as a route Atlas deliberately doesn't call.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, cast

import httpx2
import pytest
from pydantic import JsonValue

from atlas.bank_template import BankTemplate
from atlas.hindsight import (
    HindsightGateway,
    HindsightNotFound,
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
    # the gateway sends an item's explicit observation scopes (memory-quality ticket 06)
    "observation_scopes/01-retain-one-scope",
    "observation_scopes/05-retain-two-scopes",
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
    # dispositions, directives). 1.1.0 added the mental models and 1.2.0 changed the bank
    # config (missions, entity labels; 1.3.0 reflect fields, 1.4.0 `enable_auto_consolidation:
    # false`, 1.5.0 the pinned server defaults, 1.6.0 the consolidation
    # parallelism), whose import the fake derives from that recording when 0.10.2's recorded
    # template schema takes it (tests/fakes/hindsight.py);
    # editing the directives or the manifest version fails here until its dry run is
    # re-recorded.
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


# --- 0.10.2: the memory-quality features (memory-quality ticket 01) ---------------------------
#
# Recorded against 0.10.2 by `spikes/hindsight/feature_check_0102.py` (docs/hindsight-feature-
# matrix.md, "0.10.2"). The gateway doesn't send these fields yet (no Atlas behaviour changed in
# that ticket), so each test replays its recording's exact request through the fake's transport,
# the one the gateway is built on, and checks the field the later tickets will rely on.


def replay(fake: RecordedHindsight, name: str) -> dict[str, JsonValue]:
    """Send the recording's own request through the fake; return the (2xx) JSON answer."""
    recording = fake.recording(name)
    params: list[tuple[str, str | int | float | bool | None]] = []
    for key, value in (recording.query or {}).items():
        for one in value if isinstance(value, list) else [value]:
            params.append((key, str(one)))
    with httpx2.Client(base_url="http://hindsight.test", transport=fake.transport) as client:
        response = client.request(
            recording.method,
            recording.path,
            params=params,
            json=recording.body if recording.body is not None else None,
        )
    assert response.status_code == recording.status == 200, name
    assert fake.served[-1] == name
    return cast(dict[str, JsonValue], response.json())


def results(answer: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    return as_list(answer["results"])


def items(answer: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    return as_list(answer["items"])


def tags_of(memory: dict[str, JsonValue]) -> list[str]:
    return [str(t) for t in as_list(memory["tags"])] if memory["tags"] is not None else []


def request_of(name: str) -> dict[str, JsonValue]:
    return RECORDINGS[name].request_object()


def first_item(name: str) -> dict[str, JsonValue]:
    return as_dict(as_list(request_of(name)["items"])[0])


@pytest.mark.parametrize(
    ("name", "scopes"),
    [
        ("observation_scopes/01-retain-one-scope", [["company:aurora"]]),
        ("observation_scopes/05-retain-two-scopes", [["company:borealis"], ["theme:photonics"]]),
    ],
)
def test_a_retain_with_explicit_observation_scopes_is_accepted(
    name: str, scopes: list[list[str]]
) -> None:
    fake = RecordedHindsight()

    answer = replay(fake, name)

    assert first_item(name)["observation_scopes"] == scopes
    assert answer["operation_id"] == RECORDINGS[name].response_object()["operation_id"]


def test_the_scopes_listing_has_one_scope_per_explicit_scope_not_per_tag_set() -> None:
    # the two-scope item was tagged company:borealis + theme:photonics + form:8-K: its facts
    # consolidated into each scope it named, and no scope carries the form tag
    fake = RecordedHindsight()

    answer = replay(fake, "observation_scopes/09-list-scopes")

    scopes = {tuple(as_list(s["tags"])): s["count"] for s in as_list(answer["scopes"])}
    assert set(scopes) == {("company:aurora",), ("company:borealis",), ("theme:photonics",), ()}
    assert all(isinstance(count, int) and count > 0 for count in scopes.values())
    assert answer["total"] == len(scopes)


def test_recall_returns_a_score_breakdown_on_every_result() -> None:
    fake = RecordedHindsight()

    answer = replay(fake, "recall_options/01-max-tokens-8192")

    for result in results(answer):
        scores = as_dict(result["scores"])
        assert isinstance(scores["final"], float)
        assert set(scores) == {"final", "reranker", "semantic", "keyword"}


def test_recall_max_tokens_bounds_how_many_results_come_back() -> None:
    fake = RecordedHindsight()

    wide = replay(fake, "recall_options/01-max-tokens-8192")
    narrow = replay(fake, "recall_options/02-max-tokens-128")

    assert request_of("recall_options/02-max-tokens-128")["max_tokens"] == 128
    assert 0 < len(results(narrow)) < len(results(wide))


def test_recall_types_returns_only_the_requested_fact_type() -> None:
    fake = RecordedHindsight()

    answer = replay(fake, "recall_options/03-types-world")

    assert request_of("recall_options/03-types-world")["types"] == ["world"]
    assert results(answer) and {str(r["type"]) for r in results(answer)} == {"world"}


def test_prefer_observations_drops_facts_an_observation_in_the_answer_was_built_from() -> None:
    fake = RecordedHindsight()
    # source_fact_ids come only with include.source_facts: take them from that recording
    with_sources = replay(fake, "recall_options/06-include-source-facts")
    sources_of = {
        str(r["id"]): {str(i) for i in as_list(r["source_fact_ids"] or [])}
        for r in results(with_sources)
        if r["type"] == "observation"
    }

    preferred = replay(fake, "recall_options/04-prefer-observations")
    plain = replay(fake, "recall_options/05-no-prefer-observations")

    def duplicates(answer: dict[str, JsonValue]) -> int:
        observed = set[str]().union(
            *(
                sources_of.get(str(r["id"]), set[str]())
                for r in results(answer)
                if r["type"] == "observation"
            )
        )
        return sum(str(r["id"]) in observed for r in results(answer) if r["type"] == "world")

    assert duplicates(plain) > 0
    assert duplicates(preferred) == 0


def test_include_source_facts_returns_each_observation_s_sources_in_the_same_answer() -> None:
    fake = RecordedHindsight()

    answer = replay(fake, "recall_options/06-include-source-facts")

    source_facts = as_dict(answer["source_facts"])
    observations = [r for r in results(answer) if r["type"] == "observation"]
    assert observations and answer["source_facts_truncated"] is False
    for observation in observations:
        ids = as_list(observation["source_fact_ids"])
        assert ids and all(i in source_facts for i in ids)
    for fact in source_facts.values():
        assert as_dict(fact)["type"] == "world" and as_dict(fact)["document_id"]


def test_include_chunks_returns_the_chunk_of_every_fact_keyed_by_its_chunk_id() -> None:
    fake = RecordedHindsight()

    answer = replay(fake, "recall_options/07-include-chunks")

    chunks = as_dict(answer["chunks"])
    with_chunk = [r for r in results(answer) if r["chunk_id"] is not None]
    assert with_chunk and all(r["chunk_id"] in chunks for r in with_chunk)
    for chunk_id, chunk in chunks.items():
        assert as_dict(chunk)["id"] == chunk_id and as_dict(chunk)["truncated"] is False


def test_query_timestamp_reranks_the_same_memories() -> None:
    fake = RecordedHindsight()

    then = replay(fake, "recall_options/08-query-timestamp-2024")
    now = replay(fake, "recall_options/09-query-timestamp-none")

    assert request_of("recall_options/08-query-timestamp-2024")["query_timestamp"] == (
        "2024-04-01T00:00:00Z"
    )
    then_ids = [r["id"] for r in results(then)]
    now_ids = [r["id"] for r in results(now)]
    assert sorted(map(str, then_ids)) == sorted(map(str, now_ids)) and then_ids != now_ids


def test_a_pointer_recall_with_every_option_stays_in_scope_and_brings_its_sources() -> None:
    fake = RecordedHindsight()

    answer = replay(fake, "recall_options/10-pointer-recall")

    request = request_of("recall_options/10-pointer-recall")
    assert (request["budget"], request["prefer_observations"]) == ("high", True)
    assert all("company:aurora" in tags_of(r) for r in results(answer))
    assert as_dict(answer["source_facts"]) and as_dict(answer["chunks"])
    assert all(isinstance(as_dict(r["scores"])["final"], float) for r in results(answer))


def test_entities_given_unresolved_are_taken_as_written_beside_the_extracted_ones() -> None:
    fake = RecordedHindsight()
    item = first_item("entities/01-retain-entities-unresolved")
    given = [str(as_dict(e)["text"]) for e in as_list(item["entities"])]

    replay(fake, "entities/01-retain-entities-unresolved")
    listed = replay(fake, "entities/03-list-entities")
    memories = replay(fake, "entities/04-document-memories")

    assert item["resolve_entities"] is False
    assert given == ["Aurora Optics Inc.", "Halcyon Networks"]
    names = {str(as_dict(e)["canonical_name"]) for e in items(listed)}
    assert set(given) <= names
    # the text says only "Aurora" and "Halcyon": the extractor's short forms stay entities
    # of their own, so a given name does not merge them
    assert {"Aurora", "Halcyon"} <= names
    for memory in items(memories):
        entities = {e.strip() for e in str(memory["entities"]).split(",")}
        assert set(given) <= entities


@pytest.mark.parametrize(
    "name", ["entity_memories/01-by-entity-and-tag", "entity_memories/02-by-entity-tag-and-date"]
)
def test_the_memory_list_by_entity_returns_the_facts_naming_it_within_tag_and_dates(
    name: str,
) -> None:
    fake = RecordedHindsight()
    query = cast(dict[str, JsonValue], RECORDINGS[name].query)
    entity = replay(fake, "entity_memories/03-entity-detail")

    answer = replay(fake, name)

    assert query["entity_id"] == entity["id"]
    assert items(answer)
    for memory in items(answer):
        assert str(entity["canonical_name"]) in str(memory["entities"])
        assert str(query["tags"]) in tags_of(memory)
        if "start_date" in query:
            assert str(query["start_date"]) <= str(memory["mentioned_at"]) < str(query["end_date"])


def test_an_entity_label_group_with_tag_true_tags_each_fact_and_filters_recall() -> None:
    fake = RecordedHindsight()

    config = replay(fake, "entity_labels/01-config-layer-labels")
    facts = replay(fake, "entity_labels/04-document-memories")
    recalled = replay(fake, "entity_labels/05-recall-by-label-tag")

    group = as_dict(as_list(as_dict(config["config"])["entity_labels"])[0])
    assert (group["key"], group["type"], group["tag"]) == ("layer", "multi-values", True)
    allowed = {f"layer:{as_dict(v)['value']}" for v in as_list(group["values"])}
    labels = [t for f in items(facts) for t in tags_of(f) if t.startswith("layer:")]
    assert labels and set(labels) <= allowed
    wanted = str(as_list(request_of("entity_labels/05-recall-by-label-tag")["tags"])[0])
    assert results(recalled) and all(wanted in tags_of(r) for r in results(recalled))


def test_dry_run_extract_returns_facts_and_chunks_without_storing_anything() -> None:
    fake = RecordedHindsight()

    answer = replay(fake, "dry_run_extract/01-dry-run-extract")

    facts = items({"items": answer["facts"]})
    assert facts and all(f["fact_type"] == "world" for f in facts)
    # the bank's layer labels apply to a dry run too
    assert any(str(e).startswith("layer:") for f in facts for e in as_list(f["entities"]))
    assert len(as_list(answer["chunks"])) == 1
    assert as_dict(answer["usage"])


def test_a_tag_scoped_reflect_with_a_budget_sees_the_tagged_mental_model() -> None:
    fake = RecordedHindsight()

    model = replay(fake, "tagged_mental_model/03-get")
    answer = replay(fake, "reflect_options/01-budget-mid-tag-scoped")

    request = request_of("reflect_options/01-budget-mid-tag-scoped")
    assert request["budget"] == "mid" and request["tags"] == model["tags"] == ["company:aurora"]
    based_on = as_dict(answer["based_on"])
    assert [as_dict(m)["id"] for m in as_list(based_on["mental_models"])] == [model["id"]]
    # 0.10.2: a cited memory carries its document, chunk, tags and Atlas metadata
    for memory in as_list(based_on["memories"]):
        assert {"document_id", "chunk_id", "metadata", "tags"} <= set(as_dict(memory))


def test_exclude_mental_models_keeps_the_tagged_model_out_of_a_reflect() -> None:
    fake = RecordedHindsight()

    answer = replay(fake, "reflect_options/02-exclude-mental-models")

    assert request_of("reflect_options/02-exclude-mental-models")["exclude_mental_models"] is True
    based_on = as_dict(answer["based_on"])
    assert as_list(based_on["mental_models"]) == [] and as_list(based_on["memories"])


def test_a_tagged_mental_model_keeps_its_tags_and_its_trigger() -> None:
    fake = RecordedHindsight()

    replay(fake, "tagged_mental_model/01-create")
    model = replay(fake, "tagged_mental_model/03-get")

    sent = as_dict(request_of("tagged_mental_model/01-create")["trigger"])
    trigger = as_dict(model["trigger"])
    assert model["tags"] == request_of("tagged_mental_model/01-create")["tags"]
    assert {k: trigger[k] for k in sent} == sent
    assert model["content"]


def test_reprocess_re_extracts_a_stored_document_under_the_bank_s_new_labels() -> None:
    fake = RecordedHindsight()

    submitted = replay(fake, "reprocess/01-reprocess-document")
    after = replay(fake, "reprocess/03-memories-after-reprocess")

    assert submitted["success"] is True and submitted["operation_id"]
    # the document was retained before the labels were configured; after reprocess its facts
    # carry them, and keep the context they were retained with
    assert all(any(t.startswith("layer:") for t in tags_of(m)) for m in items(after))
    context = str(first_item("chunks/01-retain-chunked")["context"])
    assert {str(m["context"]) for m in items(after)} == {context}


def test_retaining_the_same_content_again_changes_tags_but_not_context_or_facts() -> None:
    fake = RecordedHindsight()
    again = first_item("reprocess/04-retain-again-same-id")

    before = replay(fake, "reprocess/03-memories-after-reprocess")
    after = replay(fake, "reprocess/06-memories-after-retain-again")

    assert again["content"] == first_item("chunks/01-retain-chunked")["content"]
    assert [m["id"] for m in items(after)] == [m["id"] for m in items(before)]
    assert all("theme:photonics" in tags_of(m) for m in items(after))
    contexts = {str(m["context"]) for m in items(after)}
    assert contexts == {str(m["context"]) for m in items(before)}
    assert str(again["context"]) not in contexts


def test_scopes_sent_with_the_second_retain_are_the_ones_consolidation_used() -> None:
    fake = RecordedHindsight()

    answer = replay(fake, "reprocess/09-list-scopes")

    sent = as_list(first_item("reprocess/04-retain-again-same-id")["observation_scopes"])
    assert sorted(tuple(as_list(s["tags"])) for s in as_list(answer["scopes"])) == sorted(
        tuple(as_list(s)) for s in sent
    )


def test_a_chunk_is_a_verbatim_slice_of_the_retained_content_in_order() -> None:
    fake = RecordedHindsight()
    content = str(first_item("chunks/01-retain-chunked")["content"])

    listed = replay(fake, "chunks/03-list-chunks")
    one = replay(fake, "chunks/04-get-chunk")
    document = replay(fake, "chunks/05-get-document")

    chunks = sorted(items(listed), key=lambda c: cast(int, c["chunk_index"]))
    assert len(chunks) > 1
    cursor = 0
    for chunk in chunks:
        text = str(chunk["chunk_text"])
        at = content.find(text, cursor)
        assert at >= cursor  # verbatim, and after the previous chunk
        cursor = at + len(text)
    assert one == chunks[0]
    assert document["original_text"] == content


def test_recall_chunks_are_the_stored_chunks_text() -> None:
    fake = RecordedHindsight()
    stored = {c["chunk_id"]: c["chunk_text"] for c in items(replay(fake, "chunks/03-list-chunks"))}

    answer = replay(fake, "chunks/06-recall-include-chunks")

    chunks = as_dict(answer["chunks"])
    assert chunks and {k: as_dict(v)["text"] for k, v in chunks.items()} == {
        k: stored[k] for k in chunks
    }


RECORDED_0102_BY_GATEWAY = {
    "chunks/01-retain-chunked",
    "entity_labels/02-retain-labelled",
    "delete_and_retain/01-retain-first",
    "delete_and_retain/14-retain-second",
}


@pytest.mark.parametrize("name", sorted(RECORDED_0102_BY_GATEWAY))
def test_a_0_10_2_retain_without_new_fields_goes_through_the_gateway(name: str) -> None:
    fake = RecordedHindsight()
    recording = fake.recording(name)
    retain_items = [
        RetainItem.model_validate(item) for item in as_list(recording.request_object()["items"])
    ]

    submitted = gateway_for(fake, recording).retain_batch(retain_items)

    assert fake.served == [name]
    assert submitted.operation_id == recording.response_object()["operation_id"]


OPERATION_STATUSES_0102 = [
    "chunks/02-retain-chunked-final",
    "entities/02-retain-entities-unresolved-final",
    "entity_labels/03-retain-labelled-final",
    "observation_scopes/02-retain-one-scope-final",
    "observation_scopes/04-consolidate-one-scope-final",
    "observation_scopes/06-retain-two-scopes-final",
    "observation_scopes/08-consolidate-two-scopes-final",
    "reprocess/02-reprocess-document-final",
    "reprocess/05-retain-again-same-id-final",
    "reprocess/08-consolidate-final",
    "tagged_mental_model/02-create-final",
    "delete_and_retain/02-retain-first-final",
    "delete_and_retain/04-consolidate-first-final",
    "delete_and_retain/15-retain-second-final",
    "delete_and_retain/21-consolidate-second-final",
]


@pytest.mark.parametrize("name", OPERATION_STATUSES_0102)
def test_the_gateway_parses_every_0_10_2_operation(name: str) -> None:
    fake = RecordedHindsight()
    recording = fake.recording(name)

    operation = gateway_for(fake, recording).operation(recording.path.rsplit("/", 1)[-1])

    expected = recording.response_object()
    assert fake.served == [name]
    assert operation.status == expected["status"] == "completed" and operation.succeeded
    assert operation.operation_type == expected["operation_type"]


CONSOLIDATIONS_0102 = [
    "observation_scopes/03-consolidate-one-scope",
    "observation_scopes/07-consolidate-two-scopes",
    "reprocess/07-consolidate",
    "delete_and_retain/03-consolidate-first",
    "delete_and_retain/20-consolidate-second",
]


def test_the_gateway_s_consolidate_is_what_0_10_2_was_sent() -> None:
    # the two consolidations of the main bank are the same request; replayed in recorded order
    fake = RecordedHindsight()

    submitted = [
        gateway_for(fake, fake.recording(name)).consolidate().operation_id
        for name in CONSOLIDATIONS_0102
    ]

    assert fake.served == CONSOLIDATIONS_0102
    assert submitted == [
        RECORDINGS[n].response_object()["operation_id"] for n in CONSOLIDATIONS_0102
    ]


LLM_STATS_0102 = [
    "llm_requests_0102/01-stats-main",
    "llm_requests_0102/02-stats-labels",
    "llm_requests_0102/03-stats-import",
    "llm_requests_0102/04-stats-template",
]


@pytest.mark.parametrize("name", LLM_STATS_0102)
def test_the_gateway_reads_the_0_10_2_llm_request_stats(name: str) -> None:
    fake = RecordedHindsight()
    recording = fake.recording(name)

    stats = gateway_for(fake, recording).llm_request_stats(period="1d")

    assert fake.served == [name]
    assert sum(b.total for b in stats.buckets) == sum(
        cast(int, as_dict(b)["total"]) for b in as_list(recording.response_object()["buckets"])
    )


DELETE_AND_RETAIN = sorted(n for n in RECORDINGS if n.startswith("delete_and_retain/"))


def test_the_delete_and_retain_sequence_replays_in_recorded_order() -> None:
    # Identical requests (the document read before and after the delete) are served in
    # recorded order, so the whole sequence is replayed once, as it happened. `GET
    # .../observations` is 405 on 0.10.2 as on 0.10.1 (observations are the memory list's
    # `fact_type: observation` rows); the 405 is evidence.
    fake = RecordedHindsight()
    with httpx2.Client(base_url="http://hindsight.test", transport=fake.transport) as client:
        for name in DELETE_AND_RETAIN:
            recording = fake.recording(name)
            params: list[tuple[str, str | int | float | bool | None]] = [
                (k, str(v)) for k, v in (recording.query or {}).items()
            ]
            response = client.request(
                recording.method, recording.path, params=params, json=recording.body
            )
            assert response.status_code == recording.status, name
            assert fake.served[-1] == name
    assert len(DELETE_AND_RETAIN) == 25


def test_the_gateway_deletes_a_document_as_0_10_2_answered() -> None:
    fake = RecordedHindsight()
    recording = fake.recording("delete_and_retain/09-delete-document")
    gateway = gateway_for(fake, recording)

    gateway.get_document("doc-delete-retain")  # the recorded read before the delete
    deleted = gateway.delete_document("doc-delete-retain")

    expected = recording.response_object()
    assert fake.served[-1] == "delete_and_retain/09-delete-document"
    assert deleted.success is True
    assert deleted.document_id == expected["document_id"] == "doc-delete-retain"
    assert deleted.memory_units_deleted == expected["memory_units_deleted"] == 2
    # Then the document reads 404, and no fact is left.
    with pytest.raises(HindsightNotFound):
        gateway.get_document("doc-delete-retain")
    gone = fake.recording("delete_and_retain/10-after-delete-memories").response_object()
    assert gone["items"] == [] and gone["total"] == 0


def test_a_document_retained_again_after_its_delete_holds_new_memories_with_the_new_context() -> (
    None
):
    before = as_list(fake_items("delete_and_retain/05-before-memories"))
    after = as_list(fake_items("delete_and_retain/16-after-retain-memories"))
    retained = as_list(RECORDINGS["delete_and_retain/14-retain-second"].request_object()["items"])[
        0
    ]

    new_context = str(retained["context"])
    assert not {str(m["id"]) for m in before} & {str(m["id"]) for m in after}  # new memory IDs
    assert {str(m["context"]) for m in after} == {new_context}  # the new context
    assert {str(m["context"]) for m in before if m["fact_type"] == "world"} != {new_context}


def fake_items(name: str) -> JsonValue:
    return RECORDINGS[name].response_object()["items"]


REPLAYED_0102 = {
    *DELETE_AND_RETAIN,
    "observation_scopes/01-retain-one-scope",
    "observation_scopes/05-retain-two-scopes",
    "observation_scopes/09-list-scopes",
    *(
        f"recall_options/{n}"
        for n in (
            "01-max-tokens-8192",
            "02-max-tokens-128",
            "03-types-world",
            "04-prefer-observations",
            "05-no-prefer-observations",
            "06-include-source-facts",
            "07-include-chunks",
            "08-query-timestamp-2024",
            "09-query-timestamp-none",
            "10-pointer-recall",
        )
    ),
    "entities/01-retain-entities-unresolved",
    "entities/03-list-entities",
    "entities/04-document-memories",
    "entity_memories/01-by-entity-and-tag",
    "entity_memories/02-by-entity-tag-and-date",
    "entity_memories/03-entity-detail",
    "entity_labels/01-config-layer-labels",
    "entity_labels/04-document-memories",
    "entity_labels/05-recall-by-label-tag",
    "dry_run_extract/01-dry-run-extract",
    "tagged_mental_model/01-create",
    "tagged_mental_model/03-get",
    "reflect_options/01-budget-mid-tag-scoped",
    "reflect_options/02-exclude-mental-models",
    "reprocess/01-reprocess-document",
    "reprocess/03-memories-after-reprocess",
    "reprocess/06-memories-after-retain-again",
    "reprocess/09-list-scopes",
    "chunks/03-list-chunks",
    "chunks/04-get-chunk",
    "chunks/05-get-document",
    "chunks/06-recall-include-chunks",
}

NOT_REPLAYED_0102 = {
    "reprocess/04-retain-again-same-id": "its request is read by the retain-again tests; the "
    "submit itself answers like any retain",
    "entity_labels/06-list-entities": "evidence for the matrix (the label entities); the entity "
    "listing is replayed from entities/03",
}


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


EXERCISED_0102 = {
    *REPLAYED_0102,
    *RECORDED_0102_BY_GATEWAY,
    *OPERATION_STATUSES_0102,
    *CONSOLIDATIONS_0102,
    *LLM_STATS_0102,
}


def test_every_recording_is_classified() -> None:
    assert len(RECORDINGS) == 63 + 57 + 25  # 0.10.1, 0.10.2 (ticket 01), delete_and_retain (12)
    assert EXERCISED.isdisjoint(NOT_CALLED_BY_ATLAS)
    assert EXERCISED_0102.isdisjoint(NOT_REPLAYED_0102)
    assert (EXERCISED | EXERCISED_0102).isdisjoint(
        set(NOT_CALLED_BY_ATLAS) | set(NOT_REPLAYED_0102)
    )
    assert EXERCISED | set(NOT_CALLED_BY_ATLAS) | EXERCISED_0102 | set(NOT_REPLAYED_0102) == set(
        RECORDINGS
    )
