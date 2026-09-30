"""The Hindsight gateway: the only code that speaks HTTP to Hindsight (pinned to 0.10.1).

It exposes typed operations on one bank and enforces the pinned-version rules from
`docs/hindsight-feature-matrix.md`:

- only strict tag matching (`any_strict`, `all_strict`); anything else is rejected before a call
- no union types in response schemas (0.10.1 returns HTTP 500 on them); rejected before a call
- an operation's outcome is decided only by its `status`, polled with a timeout
- the listing routes that work in 0.10.1: observations via `memories/list?type=observation`,
  knowledge pages via `knowledge-base/tree` (`/observations` and `/knowledge-base/pages` are 405)
"""

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, Self, cast
from urllib.parse import quote

import httpx2
from pydantic import JsonValue, TypeAdapter, ValidationError

from atlas.hindsight.errors import (
    HindsightHTTPError,
    HindsightNotFound,
    HindsightProtocolError,
    HindsightRuleViolation,
    HindsightUnavailable,
    OperationTimeout,
)
from atlas.hindsight.models import (
    BankConfig,
    BankDeleted,
    Budget,
    KnowledgeNode,
    LlmRequestStats,
    Memory,
    MentalModel,
    MentalModelDefinition,
    MentalModelRevision,
    MentalModelSubmitted,
    ObservationPage,
    Operation,
    OperationSubmitted,
    RecallResult,
    ReflectAnswer,
    RetainedDocument,
    RetainItem,
    RetainSubmitted,
    ServerHealth,
    ServerVersion,
    TagScope,
    TemplateApplication,
    TemplateImportResult,
    check_response_schema,
    check_tag_scope,
    check_template_schemas,
)
from atlas.settings import Settings

# Hindsight's own LLM timeouts are raised to 300 s; a synchronous reflect can take that long.
DEFAULT_REQUEST_TIMEOUT = 300.0
# Health and version reads are cheap; a readiness probe must not hang for minutes.
SERVER_CHECK_TIMEOUT = 5.0

# Banks Atlas creates for a replay and deletes afterwards (§9.2; the only banks it deletes).
REPLAY_BANK_PREFIX = "atlas-replay-"

_KNOWLEDGE_TREE = TypeAdapter(list[KnowledgeNode])
_HISTORY = TypeAdapter(list[MentalModelRevision])


class HindsightGateway:
    def __init__(
        self,
        base_url: str,
        bank_id: str,
        api_key: str | None = None,
        *,
        transport: httpx2.BaseTransport | None = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.bank_id = bank_id
        self._bank_path = f"/v1/default/banks/{_segment(bank_id)}"
        self._client = httpx2.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=request_timeout,
            transport=transport,
        )
        self._clock = clock
        self._sleep = sleep

    @classmethod
    def from_settings(
        cls, settings: Settings, *, transport: httpx2.BaseTransport | None = None
    ) -> "HindsightGateway | None":
        """The gateway for the configured research bank, or None when Hindsight is disabled."""
        if not settings.hindsight_url:
            return None
        return cls(
            settings.hindsight_url,
            settings.hindsight_bank_id,
            settings.hindsight_api_key,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # --- retain and operations -----------------------------------------------------------------

    def retain_batch(self, items: Sequence[RetainItem]) -> RetainSubmitted:
        """Submit items as one async batch (one operation). Poll it for the outcome."""
        if not items:
            raise ValueError("a retain batch needs at least one item")
        body = {
            "items": [item.model_dump(mode="json", exclude_none=True) for item in items],
            "async": True,
        }
        return self._parse(RetainSubmitted, self._post("/memories", body))

    def operation(self, operation_id: str) -> Operation:
        return self._parse(Operation, self._get(f"/operations/{_segment(operation_id)}"))

    def wait_for_operation(
        self, operation_id: str, *, timeout: float, poll_interval: float = 2.0
    ) -> Operation:
        """Poll until the operation's status is terminal; its `status` alone is the outcome.

        Raises `OperationTimeout` if it's still pending or processing after `timeout` seconds.
        """
        deadline = self._clock() + timeout
        while True:
            operation = self.operation(operation_id)
            if operation.is_terminal:
                return operation
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise OperationTimeout(operation_id, operation.status, timeout)
            self._sleep(min(poll_interval, remaining))

    # --- recall, reflect and memories ----------------------------------------------------------

    def recall(self, query: str, *, scope: TagScope | None, budget: Budget = "mid") -> RecallResult:
        """Recall memories for a query, strictly scoped by tags (scope=None: the whole bank)."""
        body: dict[str, JsonValue] = {"query": query, "budget": budget, **_scope_fields(scope)}
        return self._parse(RecallResult, self._post("/memories/recall", body))

    def reflect(
        self,
        query: str,
        *,
        scope: TagScope | None,
        response_schema: Mapping[str, Any] | None = None,
        include_facts: bool = True,
    ) -> ReflectAnswer:
        """Ask a reflect question; with `include_facts`, the answer lists the memories cited."""
        body: dict[str, Any] = {"query": query, **_scope_fields(scope)}
        if include_facts:
            body["include"] = {"facts": {}}
        if response_schema is not None:
            check_response_schema(response_schema)
            body["response_schema"] = dict(response_schema)
        return self._parse(ReflectAnswer, self._post("/reflect", body))

    def get_memory(self, memory_id: str) -> Memory:
        """One memory, with `source_memory_ids`/`source_memories` for an observation.

        Raises `HindsightNotFound` when the memory is gone.
        """
        return self._parse(Memory, self._get(f"/memories/{_segment(memory_id)}"))

    def list_observations(self, *, limit: int = 100, offset: int = 0) -> ObservationPage:
        # 0.10.1: GET /observations is 405; the memory list filtered by type works.
        params: dict[str, str | int] = {"type": "observation", "limit": limit}
        if offset:
            params["offset"] = offset
        return self._parse(ObservationPage, self._get("/memories/list", params=params))

    def document_memories(self, document_id: str, *, page_size: int = 100) -> list[Memory]:
        """Every memory extracted from a retained document (the memory list, filtered by
        `document_id`, page by page). Observations carry no `document_id`, so they aren't in it.
        """
        memories: list[Memory] = []
        while True:
            params: dict[str, str | int] = {"document_id": document_id, "limit": page_size}
            if memories:
                params["offset"] = len(memories)
            page = self._parse(ObservationPage, self._get("/memories/list", params=params))
            memories.extend(page.items)
            if not page.items or len(memories) >= page.total:
                return memories

    def get_document(self, document_id: str) -> RetainedDocument:
        """A retained document, with its memory count per fact type."""
        return self._parse(RetainedDocument, self._get(f"/documents/{_segment(document_id)}"))

    def knowledge_page_tree(self) -> list[KnowledgeNode]:
        # 0.10.1: GET /knowledge-base/pages is 405; the tree lists the pages.
        data = self._get("/knowledge-base/tree")
        roots = data.get("roots") if isinstance(data, dict) else None
        return self._parse(_KNOWLEDGE_TREE, roots)

    # --- bank configuration --------------------------------------------------------------------

    def apply_bank_template(self, manifest: Mapping[str, Any]) -> TemplateApplication:
        """Validate the template with a dry run, then import it.

        Nothing is applied if the dry run fails.
        """
        check_template_schemas(manifest)
        body = dict(manifest)
        dry_run = self._parse(
            TemplateImportResult, self._post("/import", body, params={"dry_run": "true"})
        )
        applied = self._parse(TemplateImportResult, self._post("/import", body))
        return TemplateApplication(dry_run=dry_run, applied=applied)

    def bank_config(self) -> BankConfig:
        return self._parse(BankConfig, self._get("/config"))

    def consolidate(self) -> OperationSubmitted:
        """Ask for consolidation now (`POST .../consolidate`); poll the operation it returns."""
        return self._parse(OperationSubmitted, self._post("/consolidate", {}))

    def delete_bank(self) -> BankDeleted:
        """Delete the whole bank (`DELETE /banks/{id}`): only a replay bank, never another.

        Raises `HindsightRuleViolation` before any call for a bank whose ID doesn't start with
        `REPLAY_BANK_PREFIX`, and `HindsightNotFound` if the bank doesn't exist.
        """
        if not self.bank_id.startswith(REPLAY_BANK_PREFIX):
            raise HindsightRuleViolation(
                f"only a replay bank ({REPLAY_BANK_PREFIX}*) may be deleted, not {self.bank_id!r}"
            )
        data = self._request("DELETE", "", params=None)
        return self._parse(BankDeleted, data)

    # --- mental models -------------------------------------------------------------------------

    def create_mental_model(self, definition: MentalModelDefinition) -> MentalModelSubmitted:
        body = definition.model_dump(mode="json", exclude_none=True)
        return self._parse(MentalModelSubmitted, self._post("/mental-models", body))

    def refresh_mental_model(self, mental_model_id: str) -> OperationSubmitted:
        path = f"/mental-models/{_segment(mental_model_id)}/refresh"
        return self._parse(OperationSubmitted, self._post(path, {}))

    def get_mental_model(self, mental_model_id: str) -> MentalModel:
        return self._parse(MentalModel, self._get(f"/mental-models/{_segment(mental_model_id)}"))

    def mental_model_history(self, mental_model_id: str) -> list[MentalModelRevision]:
        path = f"/mental-models/{_segment(mental_model_id)}/history"
        return self._parse(_HISTORY, self._get(path))

    # --- server (not bank-scoped) --------------------------------------------------------------

    def server_health(self) -> ServerHealth:
        """`GET /health`. Raises `HindsightUnavailable` or `HindsightHTTPError` when it isn't up."""
        data = self._request("GET", "/health", scoped=False, timeout=SERVER_CHECK_TIMEOUT)
        return self._parse(ServerHealth, data)

    def server_version(self) -> ServerVersion:
        """`GET /version`: the running Hindsight's API version, e.g. `0.10.1`."""
        data = self._request("GET", "/version", scoped=False, timeout=SERVER_CHECK_TIMEOUT)
        return self._parse(ServerVersion, data)

    # --- LLM request log -----------------------------------------------------------------------

    def llm_request_stats(
        self, *, period: Literal["1d", "7d", "30d"] | None = None
    ) -> LlmRequestStats:
        """The bank's LLM request counts and tokens (server default period: 7d)."""
        params = {"period": period} if period else None
        return self._parse(LlmRequestStats, self._get("/llm-requests/stats", params=params))

    # --- transport -----------------------------------------------------------------------------

    def _get(self, path: str, *, params: Mapping[str, str | int] | None = None) -> JsonValue:
        return self._request("GET", path, params=params)

    def _post(
        self, path: str, body: Mapping[str, Any], *, params: Mapping[str, str] | None = None
    ) -> JsonValue:
        return self._request("POST", path, params=params, body=body)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        body: Mapping[str, Any] | None = None,
        scoped: bool = True,
        timeout: float | None = None,
    ) -> JsonValue:
        url = f"{self._bank_path}{path}" if scoped else path
        extra: dict[str, Any] = {} if timeout is None else {"timeout": timeout}
        try:
            response = self._client.request(method, url, params=params, json=body, **extra)
        except httpx2.TransportError as error:
            raise HindsightUnavailable(f"{method} {url}: {error}") from error
        if response.status_code == 404:
            raise HindsightNotFound(method, url, 404, response.text)
        if not response.is_success:
            raise HindsightHTTPError(method, url, response.status_code, response.text)
        try:
            return cast(JsonValue, response.json())
        except ValueError as error:
            raise HindsightProtocolError(f"{method} {url}: response is not JSON") from error

    def _parse[T](self, target: type[T] | TypeAdapter[T], data: JsonValue) -> T:
        adapter = target if isinstance(target, TypeAdapter) else TypeAdapter(target)
        try:
            return adapter.validate_python(data)
        except ValidationError as error:
            name = getattr(target, "__name__", str(target))
            raise HindsightProtocolError(
                f"unexpected Hindsight response for {name}: {error}"
            ) from error


def _scope_fields(scope: TagScope | None) -> dict[str, JsonValue]:
    if scope is None:
        return {}
    check_tag_scope(scope)  # again at call time, however the scope was built
    return {"tags": list(scope.tags), "tags_match": scope.match}


def _segment(value: str) -> str:
    """Quote one path segment (Atlas document IDs contain colons)."""
    if not value:
        raise HindsightRuleViolation("an empty ID can't address a Hindsight resource")
    return quote(value, safe="")
