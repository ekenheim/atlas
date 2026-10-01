"""The investigation state machine: the plan, advancing it on the job queue, stops, premises
and resume (spec Phase 4, "Research workflow"; §7.3, §7.4).

**The plan** (round 1) is fixed and visible from the start:

    scout -> investigator:<company> (one per seed company) -> skeptic || financial_analyst -> editor

The Skeptic (atlas.investigations.skeptic) searches independently for counterevidence; the
Financial Analyst proposes scenario inputs (atlas.scenarios.analyst). Each task depends on
premises: every task on the question itself (`question`), and each Investigator task also on
its company belonging in the question (`company:<slug>`). A premise is disproven by the
researcher, or by the Skeptic's accepted, independent contradiction of a Claim (a company
premise only; `atlas-skeptic`; bear context disproves nothing).

**Advancing.** Every state change happens under a lock on the investigation row, in the
transaction that records it. Advancing cancels the unstarted tasks whose premise was
disproven, then the ones whose every (non-skipped) dependency was cancelled, then enqueues an
`investigation_task` job for each pending task whose dependencies are all done, in the same
transaction. When every task is done the investigation stops: with the Editor's verdict
(`answered` or `needs_review`), `no_new_independent_evidence` (the Investigators accepted no
Claim, so the Editor's card has no finding, or a follow-up round's Editor had no new
independent Evidence to edit), or `premise_disproven` (the Editor was cancelled).

**Stops.** Each stop records its reason in the investigation and as a `stopped` event. A
final stop finishes the run with its token totals, cancels what hadn't started and, in the
same transaction, enqueues `review_relationships` for the Assertions the Investigator tasks'
accepted Claims created (`relationship_review_queued`; the review starts its own run). A
`budget_exhausted` stop (the run's token budget ran out) is resumable: its run stays open
and its unfinished tasks stay as they were, and `resume` with a larger budget continues them
in the same run (a parallel sibling whose job the worker reached after the stop gets a new
job). An LLM quota or outage is not a stop: the task's job is requeued by the
queue pause and the investigation continues when it lifts.

**Follow-up round.** A stopped investigation (stopped `answered`, `needs_review` or
`no_new_independent_evidence`, not yet saved as a Hypothesis) with rounds and tokens left
takes one follow-up round on one of its research card's open questions (`follow_up`,
audited): an `investigation_follow_up` row records the question and the card as it stood,
the investigation runs again with the next round's plan (the same DAG, the same premises),
and the run is reopened, so the round spends what is left of the run's budgets. The round's
Scout searches for the open question, its Investigators read only Source Versions the
investigation hasn't read (with the open question for recall), and its Editor redrafts the
card only from new independent Evidence; otherwise the round stops
`no_new_independent_evidence` and the earlier card stands.
"""

import json
import uuid
from collections.abc import Mapping, Sequence
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


class FollowUpNotAllowed(InvestigationConflict):
    code = "follow_up_not_allowed"


class RoundBudgetSpent(InvestigationConflict):
    code = "round_budget_spent"


class HypothesisSaved(InvestigationConflict):
    code = "hypothesis_saved"


class UnknownOpenQuestion(InvestigationError):
    code = "unknown_open_question"


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
        _PlannedTask("skeptic", "skeptic", investigators, [QUESTION_PREMISE]),
        _PlannedTask("financial_analyst", "financial_analyst", investigators, [QUESTION_PREMISE]),
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
            _insert_tasks(connection, investigation_id, 1, planned)
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
            self.disprove_within(connection, actor, investigation_id, premise_key, reason)

    def disprove_within(
        self,
        connection: Connection,
        actor: Actor,
        investigation_id: uuid.UUID,
        premise_key: str,
        reason: str,
        *,
        counterevidence_ids: list[str] | None = None,
    ) -> None:
        """`disprove` in the caller's transaction, which holds the investigation's lock (the
        Skeptic's disproof names the counterevidence it rests on)."""
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
        statement: str = premise["statement"]
        if counterevidence_ids is None:
            event(
                connection,
                investigation_id,
                "premise_disproven",
                premise=premise_key,
                statement=statement,
                reason=reason,
                by=actor.name,
            )
        else:
            cited: list[JsonValue] = [*counterevidence_ids]
            event(
                connection,
                investigation_id,
                "premise_disproven",
                premise=premise_key,
                statement=statement,
                reason=reason,
                by=actor.name,
                counterevidence_ids=cited,
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
            # The budget-exhausted tasks, and any sibling left queued whose job the worker
            # finished without running it (it was claimed after the stop, e.g. the Financial
            # Analyst after the Skeptic spent the budget): both need a new job.
            resumed = connection.execute(
                text(
                    "UPDATE investigation_task SET status = 'pending',"
                    " generation = generation + 1, updated_at = now()"
                    " WHERE investigation_id = :id AND (status = 'budget_exhausted'"
                    "  OR (status = 'queued' AND job_id IN"
                    "   (SELECT id FROM job WHERE status IN ('succeeded', 'failed'))))"
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

    def follow_up(self, actor: Actor, investigation_id: uuid.UUID, question: str) -> int:
        """Start the investigation's follow-up round on one of its research card's open
        questions (see the module); returns the round."""
        with self._engine.begin() as connection:
            investigation = lock(connection, investigation_id)
            reason: str | None = investigation["stop_reason"]
            if investigation["status"] == "running":
                raise FollowUpNotAllowed("the investigation is still running")
            if reason == "budget_exhausted":
                raise FollowUpNotAllowed(
                    "the investigation stopped on its token budget: resume it instead"
                )
            if reason == "premise_disproven":
                raise FollowUpNotAllowed("the investigation stopped on a disproven premise")
            round_: int = investigation["round"]
            if round_ >= investigation["max_rounds"]:
                raise RoundBudgetSpent(
                    f"the investigation's {investigation['max_rounds']} rounds are spent"
                )
            saved = connection.execute(
                text("SELECT id FROM hypothesis WHERE investigation_id = :id"),
                {"id": investigation_id},
            ).scalar_one_or_none()
            if saved is not None:
                raise HypothesisSaved(
                    f"the investigation is saved as Hypothesis {saved}; its card is drawn on"
                )
            card: dict[str, Any] | None = investigation["research_card"]
            if card is None or question not in open_questions(card):
                raise UnknownOpenQuestion(
                    "a follow-up pursues one of the research card's open questions"
                )
            run_id: uuid.UUID | None = investigation["run_id"]
            spent = run_usage(connection, run_id).total if run_id is not None else 0
            if spent >= investigation["token_budget"]:
                raise FollowUpNotAllowed(
                    f"the run's token budget is spent ({spent} of"
                    f" {investigation['token_budget']} tokens)"
                )
            next_round = round_ + 1
            connection.execute(
                text(
                    "INSERT INTO investigation_follow_up (investigation_id, round, question,"
                    " requested_by, card_before) VALUES (:id, :round, :question, :actor,"
                    " CAST(:card AS jsonb))"
                ),
                {
                    "id": investigation_id,
                    "round": next_round,
                    "question": question,
                    "actor": actor.name,
                    "card": json.dumps(card),
                },
            )
            new = (
                connection.execute(
                    text(
                        "UPDATE investigation SET round = :round, status = 'running',"
                        " stop_reason = NULL, stop_detail = NULL, stopped_at = NULL"
                        " WHERE id = :id RETURNING *"
                    ),
                    {"id": investigation_id, "round": next_round},
                )
                .mappings()
                .one()
            )
            if run_id is not None:
                # The round's role calls belong to the investigation's run; its next stop
                # finishes it again with the totals.
                connection.execute(
                    text("UPDATE run SET finished_at = NULL WHERE id = :id"), {"id": run_id}
                )
            seeds = _seeds(connection, [], investigation["seed_company_ids"])
            planned = plan(seeds)
            _insert_tasks(connection, investigation_id, next_round, planned)
            event(
                connection,
                investigation_id,
                "follow_up_started",
                round=next_round,
                question=question,
                by=actor.name,
                plan=[task.key for task in planned],
                tokens_spent=spent,
            )
            for task in planned:
                if task.skipped:
                    event(
                        connection,
                        investigation_id,
                        "task_skipped",
                        round=next_round,
                        task_key=task.key,
                        reason=task.skipped,
                    )
            record(
                connection,
                actor,
                "investigation.follow_up_started",
                entity_type="investigation",
                entity_id=str(investigation_id),
                old_hash=content_hash(dict(investigation)),
                new_hash=content_hash(dict(new)),
            )
            self.advance(connection, investigation_id)
        return next_round

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
                " WHERE id = :id AND status = 'running' RETURNING run_id, round"
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
            _queue_relationship_review(connection, investigation_id, run_id, row["round"])
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
    connection: Connection, investigation_id: uuid.UUID, run_id: uuid.UUID, round_: int
) -> None:
    """Enqueue `review_relationships` for the Assertions the round's Investigator tasks'
    accepted Claims created (at most `MAX_ASSERTIONS` a job), in the stop's transaction. The
    review starts its own run: the investigation's is finished by then."""
    assertion_ids = [
        str(each)
        for each in connection.execute(
            text(
                "SELECT c.assertion_id FROM claim c"
                " JOIN investigation_document doc ON doc.investigation_id = :id"
                "  AND doc.source_version_id = c.source_version_id"
                " JOIN investigation_task t ON t.id = doc.task_id AND t.round = :round"
                " WHERE c.run_id = :run AND c.outcome = 'accepted'"
                " ORDER BY c.created_at, c.id"
            ),
            {"id": investigation_id, "run": run_id, "round": round_},
        ).scalars()
    ]
    if not assertion_ids:
        return
    # Round 1's keys are as before follow-up rounds existed.
    prefix = f"investigation:{investigation_id}" + (f":round-{round_}" if round_ > 1 else "")
    queue = JobQueue(connection.engine)
    job_ids: list[JsonValue] = []
    for start in range(0, len(assertion_ids), MAX_ASSERTIONS):
        chunk: list[JsonValue] = [*assertion_ids[start : start + MAX_ASSERTIONS]]
        job = queue.enqueue_within(
            connection,
            REVIEW_RELATIONSHIPS_KIND,
            f"{prefix}:{start // MAX_ASSERTIONS}",
            {"assertion_ids": chunk},
        ).job
        job_ids.append(str(job.id))
    event(
        connection,
        investigation_id,
        "relationship_review_queued",
        round=round_,
        assertions=len(assertion_ids),
        job_ids=job_ids,
    )


def _outcome(editor: _Task) -> tuple[StopReason, str]:
    if editor.status == "succeeded":
        reason = str(editor.artifacts.get("stop_reason", "needs_review"))
        detail = str(editor.artifacts.get("stop_detail", ""))
        if reason == "answered":
            return "answered", detail
        if reason == "no_new_independent_evidence":  # a card with no finding
            return "no_new_independent_evidence", detail
        return "needs_review", detail
    if editor.status == "skipped":
        return "no_new_independent_evidence", editor.detail or "no new independent Evidence"
    if editor.status == "cancelled":
        return "premise_disproven", editor.detail or "a premise was disproven"
    return "needs_review", editor.detail or f"the Editor task ended {editor.status}"


def _insert_tasks(
    connection: Connection, investigation_id: uuid.UUID, round_: int, planned: list[_PlannedTask]
) -> None:
    for position, task in enumerate(planned, start=1):
        connection.execute(
            text(
                "INSERT INTO investigation_task (id, investigation_id, round, position,"
                " key, role, company_id, depends_on, premise_keys, status, detail)"
                " VALUES (:id, :investigation, :round, :position, :key, :role, :company,"
                " :depends_on, :premises, :status, :detail)"
            ),
            {
                "id": uuid.uuid4(),
                "investigation": investigation_id,
                "round": round_,
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


def open_questions(card: Mapping[str, Any]) -> list[str]:
    """A research card's open questions: the card's own, then its findings', each once."""
    questions: list[str] = [*card.get("open_questions", [])]
    for finding in card.get("findings", []):
        questions.extend(finding.get("open_questions", []))
    return list(dict.fromkeys(questions))


def round_question(connection: Connection, investigation: RowMapping, round_: int) -> str:
    """The question a round pursues: the investigation's in round 1, a follow-up's after."""
    if round_ == 1:
        return investigation["question"]
    return connection.execute(
        text(
            "SELECT question FROM investigation_follow_up"
            " WHERE investigation_id = :id AND round = :round"
        ),
        {"id": investigation["id"], "round": round_},
    ).scalar_one()


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
        text("SELECT id, slug, display_name, role FROM company ORDER BY slug")
    ).all()
    # A counterparty is only the other end of an edge: it is never researched, so never a seed.
    by_id = {
        row.id: _Seed(row.id, row.slug, row.display_name)
        for row in rows
        if row.role == "researched"
    }
    if requested:
        wanted = list(dict.fromkeys(requested))
        counterparties = {row.id: row.slug for row in rows if row.role == "counterparty"}
        refused = [counterparties[each] for each in wanted if each in counterparties]
        if refused:
            raise InvalidSeeds(
                f"a counterparty can't be a seed company: {', '.join(refused)} (counterparties"
                " are never researched; add the company to the theme config or commit its"
                " Candidate first)"
            )
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
