"""The read side of role calls: what each role was asked and answered in a run, and its usage."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import Connection, text

from atlas.roles.contract import QuotedText

# `truncated` (ticket 16 of the memory-quality effort): the model stopped at the output cap.
RoleCallStatus = Literal[
    "running", "accepted", "quarantined", "truncated", "failed", "budget_exhausted"
]


class RunUsage(BaseModel):
    """A run's LLM tokens so far: the sum over every chat completion its roles made."""

    model_config = ConfigDict(frozen=True)

    tokens_in: int
    tokens_out: int

    @property
    def total(self) -> int:
        return self.tokens_in + self.tokens_out


class LLMAttempt(BaseModel):
    """One chat completion: the routed model, its usage, its raw content, why it failed
    validation (None: it validated) and the fields of its answer the role's response model
    doesn't name, which code dropped (each as its path in the answer; pilot-fixes ticket 26)."""

    model_config = ConfigDict(frozen=True)

    attempt: int
    response_model: str
    model_id: str | None
    tokens_in: int
    tokens_out: int
    content: str
    validation_errors: list[dict[str, JsonValue]] | None
    ignored_fields: list[list[str | int]]
    called_at: datetime


class RoleCallRecord(BaseModel):
    """One call of a role. A quarantined or truncated call's outputs are visible in its
    attempts only; `output` is set only for an accepted call."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    role: str
    prompt_name: str
    prompt_version: int
    prompt_sha256: str
    model: str
    request: dict[str, JsonValue]
    retrieved: list[QuotedText]
    status: RoleCallStatus
    output: dict[str, JsonValue] | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    attempts: list[LLMAttempt]


class RunRoleCalls(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: uuid.UUID
    tokens_in: int
    tokens_out: int
    # Repairs asked for, by role: the chat completions after a call's first (ticket 26).
    repairs: dict[str, int]
    role_calls: list[RoleCallRecord]


def run_usage(connection: Connection, run_id: uuid.UUID) -> RunUsage:
    row = (
        connection.execute(
            text(
                "SELECT coalesce(sum(tokens_in), 0) AS tokens_in,"
                " coalesce(sum(tokens_out), 0) AS tokens_out FROM llm_call WHERE run_id = :run"
            ),
            {"run": run_id},
        )
        .mappings()
        .one()
    )
    return RunUsage(tokens_in=int(row["tokens_in"]), tokens_out=int(row["tokens_out"]))


def run_repairs(connection: Connection, run_id: uuid.UUID) -> dict[str, int]:
    """How many repairs the run's role calls asked for, by role (a role with none left out)."""
    rows = connection.execute(
        text(
            "SELECT r.role, count(*) AS repairs FROM llm_call c JOIN role_call r"
            " ON r.id = c.role_call_id WHERE c.run_id = :run AND c.attempt > 1"
            " GROUP BY r.role ORDER BY r.role"
        ),
        {"run": run_id},
    ).all()
    return {str(row.role): int(row.repairs) for row in rows}


def run_role_calls(connection: Connection, run_id: uuid.UUID) -> RunRoleCalls | None:
    """Every role call of the run, oldest first, or None if there is no such run."""
    exists = connection.execute(
        text("SELECT 1 FROM run WHERE id = :run"), {"run": run_id}
    ).one_or_none()
    if exists is None:
        return None
    attempts: dict[uuid.UUID, list[LLMAttempt]] = {}
    for row in connection.execute(
        text("SELECT * FROM llm_call WHERE run_id = :run ORDER BY role_call_id, attempt"),
        {"run": run_id},
    ).mappings():
        attempts.setdefault(row["role_call_id"], []).append(LLMAttempt.model_validate(dict(row)))
    calls: list[RoleCallRecord] = []
    for row in connection.execute(
        text("SELECT * FROM role_call WHERE run_id = :run ORDER BY started_at, id"),
        {"run": run_id},
    ).mappings():
        values: dict[str, Any] = dict(row)
        values["attempts"] = attempts.get(row["id"], [])
        calls.append(RoleCallRecord.model_validate(values))
    usage = run_usage(connection, run_id)
    return RunRoleCalls(
        run_id=run_id,
        tokens_in=usage.tokens_in,
        tokens_out=usage.tokens_out,
        repairs=run_repairs(connection, run_id),
        role_calls=calls,
    )
