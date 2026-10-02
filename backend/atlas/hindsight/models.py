"""Typed requests and results of the Hindsight gateway, shaped by the 0.10.1 recordings.

Results ignore fields Atlas doesn't use, so additive server changes don't break parsing, but a
missing required field or a wrong type does (as `HindsightProtocolError`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import (
    AliasChoices,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from atlas.hindsight.errors import HindsightRuleViolation

type Budget = Literal["low", "mid", "high"]
type TagMatch = Literal["any_strict", "all_strict"]
type OperationStatus = Literal[
    "pending", "processing", "completed", "failed", "cancelled", "not_found"
]

# 0.10.1: `any` (the server default) also returns untagged memories, and `all`/`exact` aren't
# part of Atlas's scoping model. Only the strict modes are allowed through the gateway.
STRICT_TAG_MATCHES: frozenset[str] = frozenset({"any_strict", "all_strict"})
TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled", "not_found"})

# Keys of a mental model's `based_on` that aren't memories.
_NON_MEMORY_BASED_ON = frozenset({"directives", "mental-models"})


# --- rules -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TagScope:
    """Which memories a recall or reflect may see: `tags` combined with a strict `match`."""

    tags: Sequence[str]
    match: TagMatch

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", tuple(self.tags))
        check_tag_scope(self)


def check_tag_scope(scope: TagScope) -> None:
    if scope.match not in STRICT_TAG_MATCHES:
        raise HindsightRuleViolation(
            f"tags_match={scope.match!r} is not allowed: 0.10.1 only scopes strictly with "
            f"{sorted(STRICT_TAG_MATCHES)} (`any` also returns untagged memories)"
        )
    if not scope.tags:
        raise HindsightRuleViolation("a tag scope needs at least one tag; use scope=None for all")


def check_response_schema(schema: Mapping[str, Any], where: str = "response_schema") -> None:
    """Reject union types anywhere in a JSON Schema (0.10.1 returns HTTP 500 on them)."""
    for path, node in _schema_nodes(schema, where):
        if isinstance(node.get("type"), list):
            raise HindsightRuleViolation(
                f"{path} uses a union type {node['type']!r}; 0.10.1 fails on union types, "
                "so use a single type plus an explicit `*_known` boolean"
            )
        for keyword in ("anyOf", "oneOf"):
            if isinstance(node.get(keyword), list):
                raise HindsightRuleViolation(
                    f"{path} uses {keyword} (a union type); use a single type plus an explicit "
                    "`*_known` boolean"
                )


def check_template_schemas(manifest: Mapping[str, Any]) -> None:
    """Apply the union-type rule to the response schemas of a template's mental models."""
    models = cast(list[Mapping[str, Any]], manifest.get("mental_models") or [])
    for index, model in enumerate(models):
        trigger = cast(Mapping[str, Any], model.get("trigger") or {})
        schema = cast(Mapping[str, Any] | None, trigger.get("response_schema"))
        if schema is not None:
            check_response_schema(schema, f"mental_models/{index}/trigger/response_schema")


def _schema_nodes(node: object, path: str) -> list[tuple[str, Mapping[str, Any]]]:
    found: list[tuple[str, Mapping[str, Any]]] = []
    if isinstance(node, Mapping):
        mapping = cast(Mapping[str, Any], node)
        found.append((path, mapping))
        for key, value in mapping.items():
            found.extend(_schema_nodes(value, f"{path}/{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(cast(list[Any], node)):
            found.extend(_schema_nodes(value, f"{path}/{index}"))
    return found


# --- requests ----------------------------------------------------------------------------------


class RetainItem(BaseModel):
    """One document of a retain batch (for Atlas: one section of a Source Version)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    document_id: str
    timestamp: AwareDatetime
    context: str | None = None
    metadata: dict[str, str] | None = None
    tags: list[str] | None = None


class MentalModelTrigger(BaseModel):
    """When Hindsight refreshes a mental model. `refresh_after_consolidation` is always sent."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    refresh_after_consolidation: bool = False
    min_refresh_interval_seconds: int | None = None
    refresh_cron: str | None = None


class MentalModelDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    source_query: str
    trigger: MentalModelTrigger = MentalModelTrigger()
    tags: list[str] | None = None
    max_tokens: int | None = None


# --- results -----------------------------------------------------------------------------------


class _Result(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


def _none_to_empty_list(value: object) -> object:
    return [] if value is None else value


def _none_to_empty_dict(value: object) -> object:
    return {} if value is None else value


class TokenUsage(_Result):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    thoughts_tokens: int = 0


class RetainSubmitted(_Result):
    """An accepted async retain. It says nothing about the outcome; poll the operation."""

    bank_id: str
    items_count: int
    operation_id: str


class OperationSubmitted(_Result):
    operation_id: str
    status: str | None = None


class ConsolidationSubmitted(OperationSubmitted):
    """`POST .../consolidate`: the operation, and whether Hindsight reused a pending one."""

    deduplicated: bool = False


class ChildOperation(_Result):
    operation_id: str
    status: str
    sub_batch_index: int | None = None
    items_count: int | None = None
    error_message: str | None = None


class Operation(_Result):
    """An operation's state. Its outcome is decided by `status` alone."""

    operation_id: str
    status: OperationStatus
    operation_type: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    retry_count: int | None = None
    next_retry_at: datetime | None = None
    result_metadata: dict[str, JsonValue] = {}
    child_operations: list[ChildOperation] = []

    null_dicts = field_validator("result_metadata", mode="before")(_none_to_empty_dict)
    null_lists = field_validator("child_operations", mode="before")(_none_to_empty_list)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def succeeded(self) -> bool:
        return self.status == "completed"


class SourceMemory(_Result):
    """A memory an observation was consolidated from (as embedded in a memory lookup)."""

    id: str
    text: str
    type: str | None = None
    context: str | None = None
    occurred_start: datetime | None = None
    mentioned_at: datetime | None = None


class Memory(_Result):
    """A memory unit: a world/experience fact (with `document_id`) or an observation."""

    id: str
    text: str
    type: str = Field(validation_alias=AliasChoices("type", "fact_type"))
    context: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    tags: list[str] = []
    metadata: dict[str, str] = {}
    occurred_start: datetime | None = None
    occurred_end: datetime | None = None
    mentioned_at: datetime | None = None
    state: str | None = None
    source_memory_ids: list[str] = []
    source_memories: list[SourceMemory] = []  # filled by a memory lookup only

    null_dicts = field_validator("metadata", mode="before")(_none_to_empty_dict)
    null_lists = field_validator("tags", "source_memory_ids", "source_memories", mode="before")(
        _none_to_empty_list
    )


class RecallResult(_Result):
    memories: list[Memory] = Field(validation_alias="results")


class CitedMemory(_Result):
    """A memory an answer is based on. `id` can be missing (content without memory identity)."""

    id: str | None = None
    text: str
    type: str | None = None
    context: str | None = None
    occurred_start: datetime | None = None
    occurred_end: datetime | None = None


class CitedMentalModel(_Result):
    id: str
    text: str
    context: str | None = None


class ReflectAnswer(_Result):
    text: str
    memories: list[CitedMemory] = []
    mental_models: list[CitedMentalModel] = []
    structured_output: dict[str, JsonValue] | None = None
    structured_output_error: str | None = None
    usage: TokenUsage | None = None

    @model_validator(mode="before")
    @classmethod
    def _flatten_based_on(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        raw = cast(dict[str, Any], data)
        based_on = cast(dict[str, Any], raw.get("based_on") or {})
        return {
            **raw,
            "memories": based_on.get("memories") or [],
            "mental_models": based_on.get("mental_models") or [],
        }


def _memories_in_based_on(based_on: object) -> list[Any]:
    """A mental model's `based_on` groups memories by fact type; flatten them."""
    if not isinstance(based_on, dict):
        return []
    groups = cast(dict[str, Any], based_on)
    flat: list[Any] = []
    for key, items in groups.items():
        if key not in _NON_MEMORY_BASED_ON and isinstance(items, list):
            flat.extend(cast(list[Any], items))
    return flat


class MentalModel(_Result):
    id: str
    bank_id: str
    name: str
    source_query: str | None = None
    content: str | None = None
    tags: list[str] = []
    trigger: MentalModelTrigger = MentalModelTrigger()
    last_refreshed_at: datetime | None = None
    created_at: datetime | None = None
    # A memory in the model's scope is newer than its last refresh (Hindsight's staleness rule).
    is_stale: bool | None = None
    based_on: list[CitedMemory] = []

    @model_validator(mode="before")
    @classmethod
    def _flatten_reflect_response(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        raw = cast(dict[str, Any], data)
        response = cast(dict[str, Any], raw.get("reflect_response") or {})
        return {
            **raw,
            "trigger": raw.get("trigger") or {},
            "based_on": _memories_in_based_on(response.get("based_on")),
        }


class MentalModelRevision(_Result):
    """One history entry: the content (and its citations) before a change, newest first."""

    previous_content: str | None = None
    changed_at: datetime
    based_on: list[CitedMemory] = []

    @model_validator(mode="before")
    @classmethod
    def _flatten_previous_response(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        raw = cast(dict[str, Any], data)
        response = cast(dict[str, Any], raw.get("previous_reflect_response") or {})
        return {**raw, "based_on": _memories_in_based_on(response.get("based_on"))}


class MentalModelSubmitted(_Result):
    mental_model_id: str | None = None
    operation_id: str


class ObservationPage(_Result):
    """A page of the memory list (`memories/list`), of observations or of a document's facts."""

    items: list[Memory]
    total: int
    limit: int
    offset: int


class ObservationScope(_Result):
    """One distinct observation scope: the exact tag set observations were consolidated
    under (normalized order; empty: the untagged scope) and how many live there."""

    tags: list[str]
    count: int


class ObservationScopePage(_Result):
    """A page of `GET .../observations/scopes` (most populous first; `total` counts all)."""

    scopes: list[ObservationScope]
    total: int
    limit: int
    offset: int


class EntitySummary(_Result):
    """One entity of the bank's entity list (`GET .../entities`)."""

    id: str
    canonical_name: str
    mention_count: int


class EntityPage(_Result):
    """A page of `GET .../entities` (ordered by mention count; `total` counts all)."""

    items: list[EntitySummary]
    total: int
    limit: int
    offset: int


class KnowledgeNode(_Result):
    id: str
    kind: str
    name: str
    parent_id: str | None = None
    mental_model_id: str | None = None
    children: list["KnowledgeNode"] = []


class RetainedDocument(_Result):
    id: str
    bank_id: str
    memory_unit_count: int
    nodes_by_fact_type: dict[str, int] = {}
    tags: list[str] = []
    document_metadata: dict[str, str] = {}
    content_hash: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    null_dicts = field_validator("nodes_by_fact_type", "document_metadata", mode="before")(
        _none_to_empty_dict
    )
    null_lists = field_validator("tags", mode="before")(_none_to_empty_list)


class TemplateImportResult(_Result):
    bank_id: str
    config_applied: bool
    dry_run: bool = False
    mental_models_created: list[str] = []
    mental_models_updated: list[str] = []
    directives_created: list[str] = []
    directives_updated: list[str] = []
    operation_ids: list[str] = []


class TemplateApplication(_Result):
    dry_run: TemplateImportResult
    applied: TemplateImportResult


class BankConfig(_Result):
    bank_id: str
    config: dict[str, JsonValue]
    overrides: dict[str, JsonValue] = {}


class LlmTokenSums(_Result):
    input: int = 0
    output: int = 0
    cached: int = 0
    total: int = 0


class LlmRequestBucket(_Result):
    time: datetime
    total: int
    statuses: dict[str, int]
    tokens: LlmTokenSums


class LlmRequestStats(_Result):
    """Per-bank LLM request counts and token sums, bucketed over a period."""

    bank_id: str
    period: str
    trunc: str
    start: datetime
    buckets: list[LlmRequestBucket]


# --- server (not bank-scoped) ------------------------------------------------------------------


class ServerHealth(_Result):
    """`GET /health`: whether the server can reach its database (an error status when not)."""

    status: str
    database: str | None = None

    @property
    def is_healthy(self) -> bool:
        return self.status == "healthy"


class ServerVersion(_Result):
    """`GET /version`: the API version (e.g. `0.10.1`) and its enabled feature flags."""

    api_version: str
    features: dict[str, bool] = {}


class BankDeleted(_Result):
    """`DELETE /banks/{id}`'s `DeleteResponse` (never recorded; the documented shape)."""

    success: bool
    message: str | None = None
    deleted_count: int | None = None
