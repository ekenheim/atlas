"""Gateway behaviour at the transport boundary: pinned-version rules, polling, auth, settings."""

from datetime import datetime
from pathlib import Path
from typing import Any, cast

import httpx2
import pytest
from pydantic import ValidationError

from atlas.hindsight import (
    HindsightGateway,
    HindsightRuleViolation,
    HindsightUnavailable,
    OperationTimeout,
    RetainItem,
    TagScope,
)
from atlas.settings import Settings
from tests.fakes.hindsight import RecordedHindsight

BANK = "atlas-fm-1790615064"
RETAIN_OPERATION = "b77ff7af-0eef-4f06-a368-49bd408313e1"  # retain/05-batch-final


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def gateway(
    fake: RecordedHindsight, clock: FakeClock | None = None, **kwargs: Any
) -> HindsightGateway:
    clock = clock or FakeClock()
    return HindsightGateway(
        base_url="http://hindsight.test",
        bank_id=kwargs.pop("bank_id", BANK),
        transport=fake.transport,
        clock=clock,
        sleep=clock.sleep,
        **kwargs,
    )


# --- operation outcomes: status only, with a polling timeout -----------------------------------


def test_waiting_polls_until_the_operation_reaches_a_terminal_status() -> None:
    fake = RecordedHindsight()
    fake.hold_operation(RETAIN_OPERATION, "pending", polls=1)
    clock = FakeClock()

    operation = gateway(fake, clock).wait_for_operation(
        RETAIN_OPERATION, timeout=60, poll_interval=5
    )

    assert operation.status == "completed" and operation.succeeded
    assert len(fake.calls) == 2
    assert clock.sleeps == [5]


def test_waiting_times_out_with_the_last_status_when_the_operation_never_finishes() -> None:
    fake = RecordedHindsight()
    fake.hold_operation(RETAIN_OPERATION, "processing")
    clock = FakeClock()

    with pytest.raises(OperationTimeout) as raised:
        gateway(fake, clock).wait_for_operation(RETAIN_OPERATION, timeout=30, poll_interval=10)

    assert raised.value.operation_id == RETAIN_OPERATION
    assert raised.value.last_status == "processing"
    assert clock.now <= 30
    assert len(fake.calls) == 4  # at t = 0, 10, 20 and 30


def test_a_failed_status_is_a_failure_even_without_an_error_message() -> None:
    fake = RecordedHindsight()
    fake.hold_operation(RETAIN_OPERATION, "failed")

    operation = gateway(fake).wait_for_operation(RETAIN_OPERATION, timeout=60, poll_interval=1)

    assert operation.status == "failed"
    assert operation.is_terminal and not operation.succeeded
    assert operation.error_message is None  # the recorded body carries none; status decides


def test_retain_returns_only_the_operation_handle_not_an_outcome() -> None:
    fake = RecordedHindsight()
    recording = fake.recording("retain/02-async")
    items = [
        RetainItem.model_validate(i) for i in cast(list[Any], recording.request_object()["items"])
    ]

    submitted = gateway(fake).retain_batch(items)

    # the submit response says `success: true` before anything is extracted
    assert recording.response_object()["success"] is True
    assert not hasattr(submitted, "success")
    assert submitted.operation_id == recording.response_object()["operation_id"]


# --- pinned-version rules, enforced before any call --------------------------------------------


@pytest.mark.parametrize("match", ["any", "all", "exact"])
def test_only_strict_tag_matching_is_accepted(match: str) -> None:
    with pytest.raises(HindsightRuleViolation, match="tags_match"):
        TagScope(tags=["company:aurora"], match=cast(Any, match))


def test_reflect_rejects_a_non_strict_scope_before_any_call() -> None:
    fake = RecordedHindsight()
    scope = TagScope(tags=["company:aurora"], match="any_strict")
    object.__setattr__(scope, "match", "any")  # e.g. a scope built without validation

    with pytest.raises(HindsightRuleViolation, match="tags_match"):
        gateway(fake).reflect("Is Aurora capacity constrained?", scope=scope)

    assert fake.calls == []


def test_an_empty_tag_scope_is_rejected() -> None:
    with pytest.raises(HindsightRuleViolation, match="at least one tag"):
        TagScope(tags=[], match="all_strict")


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": {"n": {"type": ["number", "null"]}}},
        {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"x": {"type": ["string", "integer"]}},
                    },
                }
            },
        },
        {"type": "object", "properties": {"n": {"anyOf": [{"type": "number"}, {"type": "null"}]}}},
        {
            "type": "object",
            "properties": {"n": {"oneOf": [{"type": "number"}, {"type": "string"}]}},
        },
    ],
)
def test_union_types_anywhere_in_a_response_schema_are_rejected_before_any_call(
    schema: dict[str, Any],
) -> None:
    fake = RecordedHindsight()

    with pytest.raises(HindsightRuleViolation, match="union"):
        gateway(fake).reflect("How many wafers per year?", scope=None, response_schema=schema)

    assert fake.calls == []


def test_a_known_flag_schema_without_unions_is_accepted() -> None:
    fake = RecordedHindsight()
    recording = fake.recording("reflect/03-structured")
    schema = cast(dict[str, Any], recording.request_object()["response_schema"])

    answer = gateway(fake).reflect(
        str(recording.request_object()["query"]),
        scope=None,
        response_schema=schema,
        include_facts=False,
    )

    assert answer.structured_output is not None


def test_a_template_with_a_union_type_mental_model_schema_is_rejected_before_the_dry_run() -> None:
    fake = RecordedHindsight()
    manifest = {
        "version": "1",
        "mental_models": [
            {
                "id": "bottlenecks",
                "name": "Bottlenecks",
                "source_query": "Which inputs lack a qualified second source?",
                "trigger": {
                    "response_schema": {
                        "type": "object",
                        "properties": {"n": {"type": ["number", "null"]}},
                    }
                },
            }
        ],
    }

    with pytest.raises(HindsightRuleViolation, match="union"):
        gateway(fake, bank_id="atlas-fm-template-1790615064").apply_bank_template(manifest)

    assert fake.calls == []


def test_an_empty_retain_batch_is_rejected_before_any_call() -> None:
    fake = RecordedHindsight()

    with pytest.raises(ValueError, match="at least one item"):
        gateway(fake).retain_batch([])

    assert fake.calls == []


def test_retain_items_need_a_document_id_and_a_timezone_aware_timestamp() -> None:
    with pytest.raises(ValidationError):
        RetainItem.model_validate({"content": "text"})
    with pytest.raises(ValidationError):
        RetainItem(content="text", document_id="srcv:x:item-1", timestamp=datetime(2026, 1, 1))


# --- transport ---------------------------------------------------------------------------------


def test_the_api_key_is_sent_as_a_bearer_token() -> None:
    fake = RecordedHindsight()

    gateway(fake, api_key="tenant-key").llm_request_stats()

    assert fake.calls[0].headers["authorization"] == "Bearer tenant-key"


def test_no_authorization_header_without_an_api_key() -> None:
    fake = RecordedHindsight()

    gateway(fake).llm_request_stats()

    assert "authorization" not in fake.calls[0].headers


def test_an_unreachable_hindsight_raises_unavailable() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    client = HindsightGateway(
        base_url="http://hindsight.test", bank_id=BANK, transport=httpx2.MockTransport(refuse)
    )

    with pytest.raises(HindsightUnavailable):
        client.operation(RETAIN_OPERATION)


# --- settings ----------------------------------------------------------------------------------


def settings(tmp_path: Path, **values: str) -> Settings:
    return Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        database_url="postgresql+psycopg://atlas:atlas@db/atlas",
        actor="local-researcher",
        archive_root=tmp_path,
        **values,  # pyright: ignore[reportArgumentType]
    )


def test_no_gateway_when_hindsight_is_not_configured(tmp_path: Path) -> None:
    assert HindsightGateway.from_settings(settings(tmp_path)) is None


def test_the_gateway_uses_the_configured_bank_and_key(tmp_path: Path) -> None:
    fake = RecordedHindsight()
    configured = settings(
        tmp_path,
        hindsight_url="http://hindsight.test",
        hindsight_api_key="tenant-key",
        hindsight_bank_id=BANK,
    )

    client = HindsightGateway.from_settings(configured, transport=fake.transport)
    assert client is not None
    client.llm_request_stats()

    assert fake.served == ["llm_requests/01-stats"]
    assert fake.calls[0].headers["authorization"] == "Bearer tenant-key"


def test_the_research_bank_is_the_default_bank(tmp_path: Path) -> None:
    assert settings(tmp_path).hindsight_bank_id == "atlas-ai-infrastructure"
    assert settings(tmp_path).hindsight_api_key is None
