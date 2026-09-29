"""Evaluation runs and results in the database, and their read side (`GET /api/v1/evaluations`).

A run is recorded when `atlas evaluate` starts (`running`), each case's result as soon as it
is scored (an `evaluation` row, insert-only), and the run's totals when it ends (`completed`,
or `failed` when it couldn't finish, with the error).
"""

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import Connection, Engine, RowMapping, text

Mode = Literal["fake", "live"]
RunStatus = Literal["running", "completed", "failed"]


class Check(BaseModel):
    """One gold expectation, what was observed, and whether it held."""

    key: str  # the gold key, e.g. `relationships[0]`
    metric: str
    expected: Any
    observed: Any
    passed: bool


class CaseResult(BaseModel):
    id: uuid.UUID
    case_id: str
    case_sha256: str
    category: str
    title: str
    temporal_convention: str | None
    passed: bool
    scores: dict[str, float]  # per metric: the share of its checks that held
    checks: list[Check]
    predicted: dict[str, Any]
    error: str | None
    duration_ms: int
    evaluated_at: datetime


class EvaluationRunSummary(BaseModel):
    id: uuid.UUID
    mode: Mode
    status: RunStatus
    model: str
    code_version: str
    gold_manifest_sha256: str
    case_ids: list[str]
    cases_total: int
    cases_passed: int
    actor: str
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class EvaluationRun(EvaluationRunSummary):
    # Per category: cases passed and total (reports are never only an aggregate).
    categories: dict[str, dict[str, int]]
    results: list[CaseResult]


def start_run(
    engine: Engine,
    *,
    mode: Mode,
    model: str,
    code_version: str,
    manifest_sha256: str,
    case_ids: list[str],
    actor: str,
) -> uuid.UUID:
    run_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO evaluation_run (id, mode, model, code_version,"
                " gold_manifest_sha256, case_ids, actor) VALUES (:id, :mode, :model, :code,"
                " :manifest, :cases, :actor)"
            ),
            {
                "id": run_id,
                "mode": mode,
                "model": model,
                "code": code_version,
                "manifest": manifest_sha256,
                "cases": case_ids,
                "actor": actor,
            },
        )
    return run_id


def record_result(engine: Engine, run_id: uuid.UUID, result: CaseResult) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO evaluation (id, evaluation_run_id, case_id, case_sha256, category,"
                " title, temporal_convention, passed, scores, checks, predicted, error,"
                " duration_ms, evaluated_at) VALUES (:id, :run, :case_id, :sha, :category,"
                " :title, :convention, :passed, CAST(:scores AS jsonb), CAST(:checks AS jsonb),"
                " CAST(:predicted AS jsonb), :error, :duration, :evaluated_at)"
            ),
            {
                "id": result.id,
                "run": run_id,
                "case_id": result.case_id,
                "sha": result.case_sha256,
                "category": result.category,
                "title": result.title,
                "convention": result.temporal_convention,
                "passed": result.passed,
                "scores": json.dumps(result.scores),
                "checks": json.dumps([c.model_dump(mode="json") for c in result.checks]),
                "predicted": json.dumps(result.predicted),
                "error": result.error,
                "duration": result.duration_ms,
                "evaluated_at": result.evaluated_at,
            },
        )


def finish_run(engine: Engine, run_id: uuid.UUID, *, error: str | None = None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE evaluation_run SET status = :status, error = :error, finished_at = now(),"
                " cases_total = (SELECT count(*) FROM evaluation WHERE evaluation_run_id = :id),"
                " cases_passed = (SELECT count(*) FROM evaluation"
                "  WHERE evaluation_run_id = :id AND passed) WHERE id = :id"
            ),
            {"id": run_id, "status": "failed" if error else "completed", "error": error},
        )


def list_runs(
    connection: Connection, *, limit: int, offset: int
) -> tuple[list[EvaluationRunSummary], int]:
    """Runs, newest first."""
    rows = connection.execute(
        text(
            "SELECT * FROM evaluation_run ORDER BY started_at DESC, id LIMIT :limit OFFSET :offset"
        ),
        {"limit": limit, "offset": offset},
    ).mappings()
    items = [EvaluationRunSummary.model_validate(dict(row)) for row in rows]
    total = connection.execute(text("SELECT count(*) FROM evaluation_run")).scalar_one()
    return items, total


def get_run(connection: Connection, run_id: uuid.UUID) -> EvaluationRun | None:
    row = (
        connection.execute(text("SELECT * FROM evaluation_run WHERE id = :id"), {"id": run_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    results = [
        _result(each)
        for each in connection.execute(
            text("SELECT * FROM evaluation WHERE evaluation_run_id = :id ORDER BY case_id"),
            {"id": run_id},
        ).mappings()
    ]
    categories: dict[str, dict[str, int]] = {}
    for result in results:
        tally = categories.setdefault(result.category, {"passed": 0, "total": 0})
        tally["total"] += 1
        tally["passed"] += int(result.passed)
    return EvaluationRun.model_validate(
        dict(row) | {"categories": dict(sorted(categories.items())), "results": results}
    )


def _result(row: RowMapping) -> CaseResult:
    values: dict[str, Any] = dict(row)
    return CaseResult.model_validate(values)
