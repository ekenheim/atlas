"""Memory holds what was found (beliefs ticket 06; `docs/decisions.md`, "Memory holds what was
found"; `docs/runbooks.md`, "Bulk retention").

A Belief the owner or an author has judged (`proven`, `disproven`, `undecidable`) is retained
into the conclusions bank (`Settings.hindsight_beliefs_bank_id`, ticket 12; the research bank
before it) as a document of its own, `belief:<id>`, by a `retain_belief` job
(pausable; the retain kinds' provider: Codex, or MiniMax with `ATLAS_RETAIN_EXTRACTOR`). The
document carries the statement, the as-of time, the judgement and confidence, the load-bearing
Facts' statements and quotes and the session. It is tagged `belief`, `judgement:<value>`,
`step:<value>`, the theme and company scope tags a recall is scoped by, and names the
companies as entities; its observation scope is the theme, like every section's.

- **Replacement.** A re-judgement or a supersession deletes the document first and retains it
  again; a Belief judged `unproven` again is only taken out. Every deletion is a
  `belief_memory_replacement` row with the memories the document held, so a citation of an old
  memory reads `unverified` (`memory_replaced`), not `broken`.
- **One job, one pass.** The job submits the retain, waits for its operation (the section
  retain's timeout; a job that times out resumes the same operation on its next attempt) and
  records the facts Hindsight stored. A quota or outage failure pauses the queue and leaves the
  row `pending` to be submitted again; any other failure is `failed` and recorded.
- **Moving banks.** A Belief whose document still stands in the research bank (retained before
  the conclusions bank existed) has it deleted there when the job next runs, recorded as a
  `moved_bank` replacement; `atlas memory beliefs re-retain` enqueues that for every judged
  Belief.
- **Never Evidence.** The provenance resolver labels a memory from this document `belief` and
  resolves it to the Belief (`GET /api/v1/beliefs/{id}`), never to a section.
"""

import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.audit import Actor, content_hash, record
from atlas.hindsight import (
    HindsightGateway,
    HindsightNotFound,
    RetainEntity,
    RetainItem,
)
from atlas.jobs.budget import RetainExtractor
from atlas.jobs.pacing import TransientFailure
from atlas.jobs.queue import Artifacts, JobQueue
from atlas.retention.context import ENTITY_TYPE
from atlas.retention.service import EXTRACTOR_METADATA_KEY, retain_error_class

if TYPE_CHECKING:
    from atlas.beliefs.service import Belief

# The same literal as `atlas.beliefs.memory_jobs.RETAIN_BELIEF_KIND` (importing that package
# here would close an import cycle through the sessions and investigations packages).
RETAIN_BELIEF_KIND = "retain_belief"
BELIEF_DOCUMENT_PREFIX = "belief:"
# The states in which a document may stand in Hindsight.
HELD_STATES = ("pending", "completed", "zero_fact")


def belief_document_id(belief_id: uuid.UUID) -> str:
    return f"{BELIEF_DOCUMENT_PREFIX}{belief_id}"


class RetainBeliefPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    belief_id: uuid.UUID


def enqueue_reretain(engine: Engine, queue: JobQueue, run: str) -> list[uuid.UUID]:
    """One `retain_belief` job for every judged Belief (any judgement but `unproven`), keyed by
    the run: each retains the Belief into the conclusions bank, deleting its document from the
    research bank first if it stands there (ticket 12). A rerun with the same key adds nothing.
    Returns the Belief IDs."""
    with engine.connect() as connection:
        ids = list(
            connection.execute(
                text(
                    "SELECT b.id FROM belief b JOIN LATERAL ("
                    " SELECT judgement FROM belief_judgement x WHERE x.belief_id = b.id"
                    " ORDER BY x.at DESC, x.id DESC LIMIT 1) j ON true"
                    " WHERE j.judgement <> 'unproven' ORDER BY b.created_at, b.id"
                )
            ).scalars()
        )
    for belief_id in ids:
        queue.enqueue(
            RETAIN_BELIEF_KIND,
            f"{RETAIN_BELIEF_KIND}:rebank:{run}:{belief_id}",
            {"belief_id": str(belief_id)},
            max_attempts=5,
        )
    return ids


class BeliefTimings(BaseModel):
    poll_timeout: float
    poll_interval: float


def belief_tags(belief: "Belief") -> list[str]:
    tags = ["belief", f"judgement:{belief.judgement.judgement}", f"step:{belief.step}"]
    tags.append(f"theme:{belief.theme}")
    tags += [f"company:{company.id}" for company in belief.companies]
    return tags


def belief_content(belief: "Belief", legal_names: dict[uuid.UUID, str]) -> str:
    """The text Hindsight extracts facts from: the proposition and what stands behind it."""
    judged = belief.judgement
    companies = ", ".join(legal_names.get(c.id, c.display_name) for c in belief.companies)
    lines = [
        f"Belief ({belief.status}): {belief.statement}",
        f"As of {belief.as_of.date().isoformat()}. Step of the bottleneck argument: {belief.step}."
        + (f" Companies: {companies}." if companies else ""),
        f"Judgement: {judged.judgement}, confidence {judged.confidence:g}, by {judged.actor}."
        f" Reason: {judged.reason}",
    ]
    if belief.superseded_by:
        lines.append("Superseded by: " + "; ".join(link.statement for link in belief.superseded_by))
    if belief.session is not None:
        lines.append(
            f"Session {belief.session.id} ({belief.session.kind}), question: "
            f"{belief.session.question}"
        )
    bearing = [c for c in belief.citations if c.weight == "load_bearing"]
    if bearing:
        lines.append("Load-bearing Facts:")
    for citation in bearing:
        stance = "for" if citation.valence > 0 else "against"
        statement = citation.statement or citation.quote
        lines.append(
            f'- ({stance}) {statement} Quote: "{citation.quote}" '
            f"[{citation.company_name}, {citation.source_title or 'untitled'}, "
            f"available {citation.available_at.date().isoformat()}]"
        )
    return "\n".join(lines)


class BeliefRetention:
    def __init__(
        self,
        engine: Engine,
        gateway: HindsightGateway,
        actor: Actor,
        timings: BeliefTimings,
        *,
        extractor: RetainExtractor | None = None,
        legacy: HindsightGateway | None = None,
    ) -> None:
        """`gateway` is the conclusions bank's; `legacy` the research bank's, where a Belief
        retained before the conclusions bank existed has its document: it is deleted from
        there (a `moved_bank` replacement) when the Belief is next retained."""
        self._engine = engine
        self._gateway = gateway
        self._legacy = legacy if legacy is not None and legacy.bank_id != gateway.bank_id else None
        self._actor = actor
        self._timings = timings
        self._extractor = extractor

    @property
    def bank_id(self) -> str:
        return self._gateway.bank_id

    def run(self, belief_id: uuid.UUID) -> Artifacts:
        from atlas.beliefs.service import get_belief

        with self._engine.connect() as connection:
            belief = get_belief(connection, belief_id)
            held = self._row(connection, belief_id)
            old = (
                self._row(connection, belief_id, self._legacy.bank_id)
                if self._legacy is not None
                else None
            )
            names = _legal_names(connection)
        base: Artifacts = {"belief_id": str(belief_id)}
        if belief is None:
            return base | {"outcome": "missing"}
        if old is not None and old["state"] != "removed" and self._legacy is not None:
            self._settle_inflight(old, self._legacy)
            self._delete(old, "moved_bank", self._legacy)
            base |= {"moved_from": old["bank_id"]}
        current = belief.judgement
        wanted = current.judgement != "unproven"
        same = (
            held is not None
            and wanted
            and held["judgement_id"] == current.id
            and held["belief_status"] == belief.status
        )
        if same and held is not None:
            if held["state"] in ("completed", "zero_fact"):
                return base | {"outcome": "already_retained", "state": held["state"]}
            if held["state"] == "pending" and held["operation_id"] is not None:
                return base | self._finish(belief, held)  # resumes the operation
        if held is not None and (
            held["state"] in ("completed", "zero_fact")
            or (held["state"] == "pending" and held["operation_id"] is not None)
        ):
            self._settle_inflight(held, self._gateway)
            reason = (
                "unproven"
                if not wanted
                else "superseded"
                if belief.status == "superseded" and held["belief_status"] != "superseded"
                else "rejudged"
            )
            self._delete(held, reason, self._gateway)
            base |= {"replaced": reason}
        if not wanted:
            return base | {"outcome": "removed" if "replaced" in base else "nothing_to_retain"}
        item = RetainItem(
            content=belief_content(belief, names),
            document_id=belief_document_id(belief_id),
            timestamp=belief.as_of,
            context=f"A judged Belief of the {belief.theme} research and the Facts it rests on.",
            metadata=self._metadata(belief),
            tags=belief_tags(belief),
            entities=[
                RetainEntity(text=names[c.id], type=ENTITY_TYPE)
                for c in belief.companies
                if c.id in names
            ]
            or None,
            resolve_entities=False if belief.companies else None,
            observation_scopes=[[f"theme:{belief.theme}"]],
        )
        submitted = self._gateway.retain_batch([item])
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        "INSERT INTO belief_memory (id, belief_id, bank_id, hindsight_document_id,"
                        " state, judgement_id, belief_status, operation_id, extractor)"
                        " VALUES (:id, :belief, :bank, :document, 'pending', :judgement, :status,"
                        " :operation, :extractor)"
                        " ON CONFLICT (belief_id, bank_id) DO UPDATE SET state = 'pending',"
                        " judgement_id = :judgement, belief_status = :status,"
                        " operation_id = :operation, extractor = :extractor, fact_count = NULL,"
                        " memory_ids = '[]'::jsonb, error = NULL, updated_at = now()"
                        " RETURNING *"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "belief": belief_id,
                        "bank": self.bank_id,
                        "document": belief_document_id(belief_id),
                        "judgement": current.id,
                        "status": belief.status,
                        "operation": submitted.operation_id,
                        "extractor": self._extractor,
                    },
                )
                .mappings()
                .one()
            )
            self._audit(connection, "belief_memory.submitted", row)
        return base | self._finish(belief, row)

    # --- the operation -----------------------------------------------------------------------

    def _finish(self, belief: "Belief", row: RowMapping) -> Artifacts:
        """Wait for the row's operation and record what Hindsight stored."""
        operation_id = row["operation_id"]
        assert operation_id is not None
        operation = self._gateway.wait_for_operation(
            operation_id,
            timeout=self._timings.poll_timeout,
            poll_interval=self._timings.poll_interval,
        )
        if not operation.succeeded:
            error_class = retain_error_class(operation)
            error = operation.error_message or f"the operation ended {operation.status}"
            if error_class in ("quota", "unavailable", "transient"):
                self._update(row, "state = 'pending', operation_id = NULL, error = :error", error)
                raise TransientFailure(
                    "unavailable" if error_class == "transient" else error_class,
                    f"Hindsight operation {operation_id} {operation.status}: {error}",
                )
            self._update(row, "state = 'failed', error = :error", error, "belief_memory.failed")
            return {"outcome": "failed", "error": error, "error_class": error_class}
        document = belief_document_id(belief.id)
        try:
            count = self._gateway.get_document(document).memory_unit_count
        except HindsightNotFound:
            count = 0
        memory_ids = (
            [memory.id for memory in self._gateway.document_memories(document)] if count else []
        )
        state = "completed" if count else "zero_fact"
        self._update(
            row,
            "state = :state, fact_count = :count, memory_ids = CAST(:memory_ids AS jsonb),"
            " error = NULL",
            None,
            f"belief_memory.{state}",
            state=state,
            count=count,
            memory_ids=json.dumps(memory_ids),
        )
        return {"outcome": state, "facts": count, "operation_id": operation_id}

    def _settle_inflight(self, held: RowMapping, gateway: HindsightGateway) -> None:
        """A document still being retained is let finish before it is deleted."""
        if held["state"] != "pending" or held["operation_id"] is None:
            return
        gateway.wait_for_operation(
            held["operation_id"],
            timeout=self._timings.poll_timeout,
            poll_interval=self._timings.poll_interval,
        )

    def _delete(self, held: RowMapping, reason: str, gateway: HindsightGateway) -> None:
        """Delete the document (a document Hindsight no longer has is no error) and record
        the memories it held, in one transaction with the row's new state."""
        document = held["hindsight_document_id"]
        try:
            gateway.delete_document(document)
        except HindsightNotFound:
            pass
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO belief_memory_replacement (id, belief_id, bank_id,"
                    " hindsight_document_id, reason, from_judgement_id, replaced_memory_ids)"
                    " VALUES (:id, :belief, :bank, :document, :reason, :judgement,"
                    " CAST(:memories AS jsonb))"
                ),
                {
                    "id": uuid.uuid4(),
                    "belief": held["belief_id"],
                    "bank": held["bank_id"],
                    "document": document,
                    "reason": reason,
                    "judgement": held["judgement_id"],
                    "memories": json.dumps(held["memory_ids"]),
                },
            )
            row = (
                connection.execute(
                    text(
                        "UPDATE belief_memory SET state = 'removed', memory_ids = '[]'::jsonb,"
                        " operation_id = NULL, updated_at = now() WHERE id = :id RETURNING *"
                    ),
                    {"id": held["id"]},
                )
                .mappings()
                .one()
            )
            self._audit(connection, f"belief_memory.replaced_{reason}", row)

    # --- helpers -----------------------------------------------------------------------------

    def _metadata(self, belief: "Belief") -> dict[str, str]:
        metadata = {
            "belief_id": str(belief.id),
            "available_at": belief.as_of.isoformat(),
            "judgement": belief.judgement.judgement,
            "step": belief.step,
        }
        if self._extractor is not None:
            metadata[EXTRACTOR_METADATA_KEY] = self._extractor
        return metadata

    def _row(
        self, connection: Connection, belief_id: uuid.UUID, bank_id: str | None = None
    ) -> RowMapping | None:
        return (
            connection.execute(
                text("SELECT * FROM belief_memory WHERE belief_id = :id AND bank_id = :bank"),
                {"id": belief_id, "bank": bank_id or self.bank_id},
            )
            .mappings()
            .one_or_none()
        )

    def _update(
        self,
        row: RowMapping,
        assignments: str,
        error: str | None,
        action: str | None = None,
        **params: Any,
    ) -> None:
        with self._engine.begin() as connection:
            new = (
                connection.execute(
                    text(
                        f"UPDATE belief_memory SET {assignments}, updated_at = now()"  # noqa: S608 (constant fragments)
                        " WHERE id = :id AND operation_id IS NOT DISTINCT FROM :operation"
                        " RETURNING *"
                    ),
                    {"id": row["id"], "operation": row["operation_id"], "error": error, **params},
                )
                .mappings()
                .one_or_none()
            )
            if new is not None and action is not None:
                self._audit(connection, action, new)

    def _audit(self, connection: Connection, action: str, row: RowMapping) -> None:
        record(
            connection,
            self._actor,
            action,
            entity_type="belief_memory",
            entity_id=str(row["id"]),
            new_hash=content_hash(_plain(dict(row))),
        )


def _plain(row: dict[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, uuid.UUID | datetime) else v) for k, v in row.items()}


def _legal_names(connection: Connection) -> dict[uuid.UUID, str]:
    return {
        row.id: row.legal_name
        for row in connection.execute(text("SELECT id, legal_name FROM company"))
        if row.legal_name
    }
