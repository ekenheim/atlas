"""The investigation state machine: the plan, advancing it on the job queue, stops, premises
and resume (spec Phase 4, "Research workflow"; §7.3, §7.4).

**The plan** (round 1) is fixed and visible from the start:

    scout -> investigator:<company> (one per seed company) -> skeptic || financial_analyst -> editor

The Skeptic and Financial Analyst are slots, skipped until their tickets build them. Each
task depends on premises: every task on the question itself (`question`), and each
Investigator task also on its company belonging in the question (`company:<slug>`).

**Advancing.** Every state change happens under a lock on the investigation row, in the
transaction that records it. Advancing cancels the unstarted tasks whose premise was
disproven, then the ones whose every (non-skipped) dependency was cancelled, then enqueues an
`investigation_task` job for each pending task whose dependencies are all done, in the same
transaction. When every task is done the investigation stops: with the Editor's verdict
(`answered` or `needs_review`), `no_new_independent_evidence` (the Editor had no new
independent Evidence to edit), or `premise_disproven` (the Editor was cancelled).

**Stops.** Each stop records its reason in the investigation and as a `stopped` event. A
final stop finishes the run with its token totals, cancels what hadn't started and, in the
same transaction, enqueues `review_relationships` for the Assertions the Investigator tasks'
accepted Claims created (`relationship_review_queued`; the review starts its own run). A
`budget_exhausted` stop (the run's token budget ran out) is resumable: its run stays open
and its unfinished tasks stay as they were, and `resume` with a larger budget continues them
in the same run. An LLM quota or outage is not a stop: the task's job is requeued by the
queue pause and the investigation continues when it lifts.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import JsonValue
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.audit import Actor, content_hash, record
from atlas.companies import Universe
from atlas.investigations.model import (
    DONE,
    INVESTIGATION_TASK_KIND,
    Budgets,
    StopReason,
    TaskRole,
)
from atlas.jobs.queue import JobQueue
from atlas.relationships.review import MAX_ASSERTIONS, REVIEW_RELATIONSHIPS_KIND
from atlas.roles import run_usage

QUESTION_PREMISE = "question"
_DETAIL_LIMIT = 1000


class InvestigationError(Exception):
    """A request the investigation can't honour; `code` and `status` for the API."""

    code = "invalid_investigation"
    status = 422

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnknownTheme(InvestigationError):
    code = "unknown_theme"


class InvalidSeeds(InvestigationError):
    code = "invalid_seed_companies"


class InvestigationNotFound(InvestigationError):
    code = "not_found"
    status = 404


class InvestigationConflict(InvestigationError):
    code = "conflict"
    status = 409


@dataclass(frozen=True)
class _Seed:
    id: uuid.UUID
    slug: str
    name: str


@dataclass(frozen=True)
class _PlannedTask:
    key: str
    role: TaskRole
    depends_on: list[str]
    premise_keys: list[str]
    company_id: uuid.UUID | None = None
    skipped: str | None = None  # why a slot is skipped


def plan(seeds: Sequence[_Seed]) -> list[_PlannedTask]:
    """Round 1's DAG (see the module)."""
    investigators = [f"investigator:{seed.slug}" for seed in seeds]
    return [
        _PlannedTask("scout", "scout", [], [QUESTION_PREMISE]),
        *(
            _PlannedTask(
                key,
                "investigator",
                ["scout"],
                [QUESTION_PREMISE, f"company:{seed.slug}"],
                company_id=seed.id,
            )
            for key, seed in zip(investigators, seeds, strict=True)
        ),
        _PlannedTask(
            "skeptic",
            "skeptic",
            investigators,
            [QUESTION_PREMISE],
            skipped="not built yet: the Skeptic's independent counterevidence search joins later",
        ),
        _PlannedTask(
            "financial_analyst",
            "financial_analyst",
            investigators,
            [QUESTION_PREMISE],
            skipped="not built yet: the Financial Analyst's scenario inputs join later",
        ),
        _PlannedTask(
            "editor",
            "editor",
            [*investigators, "skeptic", "financial_analyst"],
            [QUESTION_PREMISE],
        ),
    ]


@dataclass
class _Task:
    id: uuid.UUID
    round: int
    key: str
    role: str
    depends_on: list[str]
    premise_keys: list[str]
    status: str
    generation: int
    detail: str | None
    artifacts: dict[str, Any] = field(default_factory=dict[str, Any])


class Investigations:
    """Creates investigations and changes their state (see the module)."""

    def __init__(self, engine: Engine, queue: JobQueue) -> None:
        self._engine = engine
        self._queue = queue

    # --- the API's actions ------------------------------------------------------------------

    def create(
        self,
        actor: Actor,
        universe: Universe,
        *,
        theme: str,
        question: str,
        seed_company_ids: Sequence[uuid.UUID] | None,
        as_of: datetime,
        budgets: Budgets,
        bank_id: str,
    ) -> uuid.UUID:
        theme_config = universe.themes.get(theme)
        if theme_config is None:
            raise UnknownTheme(f"no theme {theme!r} in the universe config")
        investigation_id = uuid.uuid4()
        with self._engine.begin() as connection:
            seeds = _seeds(connection, list(theme_config.companies), seed_company_ids)
            row = (
                connection.execute(
                    text(
                        "INSERT INTO investigation (id, theme, question, seed_company_ids, as_of,"
                        " bank_id, max_rounds, max_leads, max_documents, token_budget,"
                        " created_by) VALUES (:id, :theme, :question, :seeds, :as_of, :bank,"
                        " :rounds, :leads, :documents, :tokens, :actor) RETURNING *"
                    ),
                    {
                        "id": investigation_id,
                        "theme": theme,
                        "question": question,
                        "seeds": [seed.id for seed in seeds],
                        "as_of": as_of,
                        "bank": bank_id,
                        "rounds": budgets.max_rounds,
                        "leads": budgets.max_leads,
                        "documents": budgets.max_documents,
                        "tokens": budgets.token_budget,
                        "actor": actor.name,
                    },
                )
                .mappings()
                .one()
            )
            premises = [(QUESTION_PREMISE, question, None)] + [
                (
                    f"company:{seed.slug}",
                    f"{seed.name} is part of the supply chain the question is about",
                    seed.id,
                )
                for seed in seeds
            ]
            for key, statement, company_id in premises:
                connection.execute(
                    text(
                        "INSERT INTO investigation_premise (id, investigation_id, key, statement,"
                        " company_id) VALUES (:id, :investigation, :key, :statement, :company)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "investigation": investigation_id,
                        "key": key,
                        "statement": statement,
                        "company": company_id,
                    },
                )
            planned = plan(seeds)
            for position, task in enumerate(planned, start=1):
                connection.execute(
                    text(
                        "INSERT INTO investigation_task (id, investigation_id, round, position,"
                        " key, role, company_id, depends_on, premise_keys, status, detail)"
                        " VALUES (:id, :investigation, 1, :position, :key, :role, :company,"
                        " :depends_on, :premises, :status, :detail)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "investigation": investigation_id,
                        "position": position,
                        "key": task.key,
                        "role": task.role,
                        "company": task.company_id,
                        "depends_on": task.depends_on,
                        "premises": task.premise_keys,
                        "status": "skipped" if task.skipped else "pending",
                        "detail": task.skipped,
                    },
                )
            event(
                connection,
                investigation_id,
                "created",
                round=1,
                theme=theme,
                question=question,
                seed_company_ids=[str(seed.id) for seed in seeds],
                plan=[task.key for task in planned],
                budgets=budgets.model_dump(),
            )
            for task in planned:
                if task.skipped:
                    event(
                        connection,
                        investigation_id,
                        "task_skipped",
                        round=1,
                        task_key=task.key,
                        reason=task.skipped,
                    )
            record(
                connection,
                actor,
                "investigation.created",
                entity_type="investigation",
                entity_id=str(investigation_id),
                new_hash=content_hash(dict(row)),
            )
            self.advance(connection, investigation_id)
        return investigation_id

    def disprove(
        self, actor: Actor, investigation_id: uuid.UUID, premise_key: str, reason: str
    ) -> None:
        """Mark a premise disproven and cancel only the unstarted tasks that depend on it."""
        with self._engine.begin() as connection:
            investigation = lock(connection, investigation_id)
            if investigation["status"] != "running":
                raise InvestigationConflict("the investigation has stopped")
            premise = (
                connection.execute(
                    text(
                        "SELECT * FROM investigation_premise"
                        " WHERE investigation_id = :id AND key = :key"
                    ),
                    {"id": investigation_id, "key": premise_key},
                )
                .mappings()
                .one_or_none()
            )
            if premise is None:
                raise InvestigationNotFound(f"premise {premise_key!r} not found")
            if premise["status"] == "disproven":
                raise InvestigationConflict(f"premise {premise_key!r} is already disproven")
            new = (
                connection.execute(
                    text(
                        "UPDATE investigation_premise SET status = 'disproven', reason = :reason,"
                        " disproven_by = :actor, disproven_at = now() WHERE id = :id RETURNING *"
                    ),
                    {"id": premise["id"], "reason": reason, "actor": actor.name},
                )
                .mappings()
                .one()
            )
            event(
                connection,
                investigation_id,
                "premise_disproven",
                premise=premise_key,
                statement=premise["statement"],
                reason=reason,
                by=actor.name,
            )
            record(
                connection,
                actor,
                "investigation.premise_disproven",
                entity_type="investigation_premise",
                entity_id=str(premise["id"]),
                old_hash=content_hash(dict(premise)),
                new_hash=content_hash(dict(new)),
            )
            self.advance(connection, investigation_id)

    def resume(self, actor: Actor, investigation_id: uuid.UUID, token_budget: int) -> None:
        """Continue a budget-exhausted investigation with a larger token budget, in its run."""
        with self._engine.begin() as connection:
            investigation = lock(connection, investigation_id)
            if investigation["stop_reason"] != "budget_exhausted":
                raise InvestigationConflict(
                    "only an investigation stopped by its token budget can be resumed"
                )
            old_budget = investigation["token_budget"]
            if token_budget <= old_budget:
                raise InvestigationError(
                    f"the new token budget must exceed the old one ({old_budget})"
                )
            new = (
                connection.execute(
                    text(
                        "UPDATE investigation SET status = 'running', stop_reason = NULL,"
                        " stop_detail = NULL, stopped_at = NULL, token_budget = :tokens"
                        " WHERE id = :id RETURNING *"
                    ),
                    {"id": investigation_id, "tokens": token_budget},
                )
                .mappings()
                .one()
            )
            resumed = connection.execute(
                text(
                    "UPDATE investigation_task SET status = 'pending',"
                    " generation = generation + 1, updated_at = now()"
                    " WHERE investigation_id = :id AND status = 'budget_exhausted'"
                    " RETURNING key"
                ),
                {"id": investigation_id},
            ).scalars()
            event(
                connection,
                investigation_id,
                "resumed",
                token_budget_before=investigation["token_budget"],
                token_budget=token_budget,
                tasks=list(resumed),
                by=actor.name,
            )
            record(
                connection,
                actor,
                "investigation.resumed",
                entity_type="investigation",
                entity_id=str(investigation_id),
                old_hash=content_hash(dict(investigation)),
                new_hash=content_hash(dict(new)),
            )
            self.advance(connection, investigation_id)

    # --- advancing (under the investigation's lock) -----------------------------------------------

    def advance(self, connection: Connection, investigation_id: uuid.UUID) -> None:
        """Cancel, enqueue and finish as the plan says (see the module). The caller holds the
        investigation's lock (or created it in this transaction)."""
        investigation = lock(connection, investigation_id)
        if investigation["status"] != "running":
            return
        round_ = investigation["round"]
        tasks = _tasks(connection, investigation_id, round_)
        disproven = dict(
            connection.execute(
                text(
                    "SELECT key, reason FROM investigation_premise"
                    " WHERE investigation_id = :id AND status = 'disproven'"
                ),
                {"id": investigation_id},
            ).all()
        )
        changed = True
        while changed:
            changed = False
            for task in tasks.values():
                if task.status not in ("pending", "queued"):
                    continue
                hit = [key for key in task.premise_keys if key in disproven]
                if hit:
                    reason = f"premise {hit[0]!r} was disproven: {disproven[hit[0]]}"
                    self._cancel(connection, investigation_id, task, reason)
                    changed = True
                    continue
                deps = [tasks[key] for key in task.depends_on]
                live = [dep for dep in deps if dep.status != "skipped"]
                if task.status == "pending" and live and all(d.status == "cancelled" for d in live):
                    reason = "every task it depends on was cancelled"
                    self._cancel(connection, investigation_id, task, reason)
                    changed = True
        for task in tasks.values():
            if task.status != "pending":
                continue
            deps = [tasks[key] for key in task.depends_on]
            if all(dep.status in ("succeeded", "skipped", "cancelled") for dep in deps):
                self._enqueue(connection, investigation_id, task)
        if all(task.status in DONE for task in tasks.values()):
            reason, detail = _outcome(tasks["editor"])
            stop(connection, investigation_id, reason, detail)

    def _cancel(
        self, connection: Connection, investigation_id: uuid.UUID, task: _Task, reason: str
    ) -> None:
        connection.execute(
            text(
                "UPDATE investigation_task SET status = 'cancelled', detail = :reason,"
                " updated_at = now() WHERE id = :id"
            ),
            {"id": task.id, "reason": reason},
        )
        task.status, task.detail = "cancelled", reason
        event(
            connection,
            investigation_id,
            "task_cancelled",
            round=task.round,
            task_key=task.key,
            reason=reason,
        )

    def _enqueue(self, connection: Connection, investigation_id: uuid.UUID, task: _Task) -> None:
        key = f"{investigation_id}:{task.round}:{task.key}:{task.generation}"
        job = self._queue.enqueue_within(
            connection, INVESTIGATION_TASK_KIND, key, {"task_id": str(task.id)}
        ).job
        connection.execute(
            text(
                "UPDATE investigation_task SET status = 'queued', job_id = :job,"
                " updated_at = now() WHERE id = :id"
            ),
            {"id": task.id, "job": job.id},
        )
        task.status = "queued"
        event(
            connection,
            investigation_id,
            "task_queued",
            round=task.round,
            task_key=task.key,
            job_id=str(job.id),
            generation=task.generation,
        )


# --- shared helpers -------------------------------------------------------------------------------


def lock(connection: Connection, investigation_id: uuid.UUID) -> RowMapping:
    row = (
        connection.execute(
            text("SELECT * FROM investigation WHERE id = :id FOR UPDATE"),
            {"id": investigation_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise InvestigationNotFound("investigation not found")
    return row


def event(
    connection: Connection,
    investigation_id: uuid.UUID,
    type_: str,
    *,
    round: int | None = None,
    task_key: str | None = None,
    **detail: JsonValue,
) -> None:
    connection.execute(
        text(
            "INSERT INTO investigation_event (investigation_id, type, round, task_key, detail)"
            " VALUES (:id, :type, :round, :task, CAST(:detail AS jsonb))"
        ),
        {
            "id": investigation_id,
            "type": type_,
            "round": round,
            "task": task_key,
            "detail": json.dumps(detail),
        },
    )


def stop(
    connection: Connection, investigation_id: uuid.UUID, reason: StopReason, detail: str
) -> None:
    """Stop the investigation (its lock held) with `reason`. A final stop cancels the tasks
    that hadn't started and finishes the run with its token totals; a `budget_exhausted` stop
    leaves both for `resume`."""
    detail = detail[:_DETAIL_LIMIT]
    row = (
        connection.execute(
            text(
                "UPDATE investigation SET status = 'stopped', stop_reason = :reason,"
                " stop_detail = :detail, stopped_at = now()"
                " WHERE id = :id AND status = 'running' RETURNING run_id"
            ),
            {"id": investigation_id, "reason": reason, "detail": detail},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return
    tokens: tuple[int, int] | None = None
    if reason != "budget_exhausted":
        for key, round_ in connection.execute(
            text(
                "UPDATE investigation_task SET status = 'cancelled', detail = :detail,"
                " updated_at = now() WHERE investigation_id = :id"
                " AND status IN ('pending', 'queued') RETURNING key, round"
            ),
            {"id": investigation_id, "detail": f"the investigation stopped: {reason}"},
        ).all():
            event(
                connection,
                investigation_id,
                "task_cancelled",
                round=round_,
                task_key=key,
                reason=f"the investigation stopped: {reason}",
            )
        run_id: uuid.UUID | None = row["run_id"]
        if run_id is not None:
            totals = run_usage(connection, run_id)
            connection.execute(
                text(
                    "UPDATE run SET tokens_in = :tokens_in, tokens_out = :tokens_out,"
                    " finished_at = now() WHERE id = :id AND finished_at IS NULL"
                ),
                {"id": run_id, "tokens_in": totals.tokens_in, "tokens_out": totals.tokens_out},
            )
            tokens = (totals.tokens_in, totals.tokens_out)
            _queue_relationship_review(connection, investigation_id, run_id)
    event(
        connection,
        investigation_id,
        "stopped",
        reason=reason,
        detail=detail,
        tokens_in=tokens[0] if tokens else None,
        tokens_out=tokens[1] if tokens else None,
    )


def _queue_relationship_review(
    connection: Connection, investigation_id: uuid.UUID, run_id: uuid.UUID
) -> None:
    """Enqueue `review_relationships` for the Assertions the Investigator tasks' accepted
    Claims created (at most `MAX_ASSERTIONS` a job), in the stop's transaction. The review
    starts its own run: the investigation's is finished by then."""
    assertion_ids = [
        str(each)
        for each in connection.execute(
            text(
                "SELECT c.assertion_id FROM claim c"
                " JOIN investigation_document doc ON doc.investigation_id = :id"
                "  AND doc.source_version_id = c.source_version_id"
                " WHERE c.run_id = :run AND c.outcome = 'accepted'"
                " ORDER BY c.created_at, c.id"
            ),
            {"id": investigation_id, "run": run_id},
        ).scalars()
    ]
    if not assertion_ids:
        return
    queue = JobQueue(connection.engine)
    job_ids: list[JsonValue] = []
    for start in range(0, len(assertion_ids), MAX_ASSERTIONS):
        chunk: list[JsonValue] = [*assertion_ids[start : start + MAX_ASSERTIONS]]
        job = queue.enqueue_within(
            connection,
            REVIEW_RELATIONSHIPS_KIND,
            f"investigation:{investigation_id}:{start // MAX_ASSERTIONS}",
            {"assertion_ids": chunk},
        ).job
        job_ids.append(str(job.id))
    event(
        connection,
        investigation_id,
        "relationship_review_queued",
        assertions=len(assertion_ids),
        job_ids=job_ids,
    )


def _outcome(editor: _Task) -> tuple[StopReason, str]:
    if editor.status == "succeeded":
        reason = str(editor.artifacts.get("stop_reason", "needs_review"))
        detail = str(editor.artifacts.get("stop_detail", ""))
        if reason == "answered":
            return "answered", detail
        return "needs_review", detail
    if editor.status == "skipped":
        return "no_new_independent_evidence", editor.detail or "no new independent Evidence"
    if editor.status == "cancelled":
        return "premise_disproven", editor.detail or "a premise was disproven"
    return "needs_review", editor.detail or f"the Editor task ended {editor.status}"


def _tasks(connection: Connection, investigation_id: uuid.UUID, round_: int) -> dict[str, _Task]:
    rows = connection.execute(
        text(
            "SELECT id, round, key, role, depends_on, premise_keys, status, generation, detail,"
            " artifacts FROM investigation_task WHERE investigation_id = :id AND round = :round"
            " ORDER BY position FOR UPDATE"
        ),
        {"id": investigation_id, "round": round_},
    ).mappings()
    return {row["key"]: _Task(**dict(row)) for row in rows}


def _seeds(
    connection: Connection, theme_slugs: list[str], requested: Sequence[uuid.UUID] | None
) -> list[_Seed]:
    rows = connection.execute(
        text("SELECT id, slug, display_name FROM company ORDER BY slug")
    ).all()
    by_id = {row.id: _Seed(row.id, row.slug, row.display_name) for row in rows}
    if requested:
        wanted = list(dict.fromkeys(requested))
        unknown = [str(each) for each in wanted if each not in by_id]
        if unknown:
            raise InvalidSeeds(f"unknown seed companies: {', '.join(unknown)}")
        return [by_id[each] for each in wanted]
    by_slug = {seed.slug: seed for seed in by_id.values()}
    seeds = [by_slug[slug] for slug in theme_slugs if slug in by_slug]
    if not seeds:
        raise InvalidSeeds(
            "none of the theme's companies is in the database: run `atlas companies seed`"
        )
    return seeds
