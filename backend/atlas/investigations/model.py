"""What an investigation is, as the API shows it: its §7.2 request, budgets and usage, the plan
(premises and role tasks), the leads and documents it took, the Skeptic's counterevidence,
the Editor's research card, and the event log."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Connection, RowMapping, text

from atlas.roles import run_usage

INVESTIGATION_TASK_KIND = "investigation_task"
RUN_KIND = "investigation"

StopReason = Literal[
    "answered",
    "no_new_independent_evidence",
    "budget_exhausted",
    "needs_review",
    "premise_disproven",
]
STOP_REASONS: tuple[StopReason, ...] = (
    "answered",
    "no_new_independent_evidence",
    "budget_exhausted",
    "needs_review",
    "premise_disproven",
)
InvestigationStatus = Literal["running", "stopped"]
TaskRole = Literal["scout", "investigator", "skeptic", "financial_analyst", "editor"]
TaskStatus = Literal[
    "pending",
    "queued",
    "running",
    "succeeded",
    "skipped",
    "cancelled",
    "failed",
    "budget_exhausted",
]
# A task in one of these states will not run again (a budget-exhausted one only on resume).
DONE: frozenset[str] = frozenset(
    {"succeeded", "skipped", "cancelled", "failed", "budget_exhausted"}
)
PremiseStatus = Literal["open", "disproven"]

# The §7.2 request's fixed parts: what an investigation's roles may read and use.
ALLOWED_SOURCE_TIERS = ["A", "C"]  # Tier A archived sources as Evidence; Tier C only as leads
APPROVED_TOOLS = ["searxng_search", "source_ledger_read", "hindsight_recall"]


class Budgets(BaseModel):
    """Per-run limits (spec §7.4)."""

    model_config = ConfigDict(frozen=True)

    max_rounds: int
    max_leads: int
    max_documents: int
    token_budget: int


class Usage(BaseModel):
    """How much of each budget the investigation has used."""

    model_config = ConfigDict(frozen=True)

    rounds: int
    leads: int
    documents: int
    tokens_in: int
    tokens_out: int


class InvestigationRequest(BaseModel):
    """The shared agent contract's request (spec §7.2), as every role of the run works to."""

    model_config = ConfigDict(frozen=True)

    run_id: uuid.UUID | None  # None until the first task starts the run
    research_question: str
    theme_id: str
    seed_entity_ids: list[uuid.UUID]
    as_of_utc: datetime
    allowed_source_tiers: list[str]
    available_budget: Budgets
    max_depth: int  # rounds
    max_new_leads: int
    approved_tool_list: list[str]
    relevant_hindsight_bank: str
    hypothesis_id: uuid.UUID | None


class Premise(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    statement: str
    company_id: uuid.UUID | None
    status: PremiseStatus
    reason: str | None
    disproven_by: str | None
    disproven_at: datetime | None


class Task(BaseModel):
    """One role task of the plan. `depends_on` names tasks of the same round by key; a task
    runs once each of them is done, and is cancelled when one of its premises is disproven or
    every task it depends on was cancelled."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    round: int
    position: int
    key: str
    role: TaskRole
    company_id: uuid.UUID | None
    depends_on: list[str]
    premise_keys: list[str]
    status: TaskStatus
    generation: int  # how many times it has been resumed
    job_id: uuid.UUID | None
    detail: str | None  # why it was skipped, cancelled, failed or ran out of budget
    artifacts: dict[str, JsonValue]
    created_at: datetime
    updated_at: datetime


class InvestigationLead(BaseModel):
    """A Tier C lead the Scout found and the investigation kept (never Evidence)."""

    model_config = ConfigDict(frozen=True)

    rank: int
    lead_id: uuid.UUID
    discovery_id: uuid.UUID
    url: str
    canonical_url: str
    title: str
    snippet: str
    tier: Literal["C"]


class InvestigationDocument(BaseModel):
    """A Source Version an Investigator task read (counted against `max_documents`)."""

    model_config = ConfigDict(frozen=True)

    source_version_id: uuid.UUID
    task_key: str
    company_id: uuid.UUID | None
    title: str
    available_at: datetime


class SourceSpan(BaseModel):
    model_config = ConfigDict(frozen=True)

    claim_id: uuid.UUID
    assertion_id: uuid.UUID
    source_version_id: uuid.UUID
    span_start: int
    span_end: int
    quote: str
    verification_status: str  # the Assertion's review state


class ValidityDates(BaseModel):
    model_config = ConfigDict(frozen=True)

    # The latest availability among the cited Source Versions: the finding couldn't be known
    # before it. How long the finding holds is not established (always None for now).
    evidence_available_at: datetime
    valid_until: datetime | None


class CardFinding(BaseModel):
    """A research card finding in the §7.2 claim shape. The statement is the Editor's; every
    other field is filled in by code from the accepted Claims it cites."""

    model_config = ConfigDict(frozen=True)

    claim_text: str
    epistemic_type: Literal["agent_inference"]  # the Editor's synthesis of the cited Claims
    cited_epistemic_types: list[str]
    claim_ids: list[uuid.UUID]
    original_source_version_ids: list[uuid.UUID]
    source_spans: list[SourceSpan]
    independent_evidence_families: list[str]  # a family ID, or a lone Source Version's ID
    entity_ids: list[uuid.UUID]
    validity_dates: ValidityDates
    limitations: list[str]
    # The Skeptic's accepted, independent counterevidence against a cited Claim (ticket 15).
    counterevidence_ids: list[uuid.UUID]
    # Until every cited Assertion is corroborated, and while counterevidence contradicts it.
    needs_review: bool
    open_questions: list[str]


CounterevidenceOutcome = Literal["accepted", "rejected"]


class Counterevidence(BaseModel):
    """One item the Skeptic proposed and its outcome (like a Claim). An accepted item is an
    Assertion (predicate `counterevidence`) on a Source Version the Skeptic chose; `independent`
    says whether its Evidence Family differs from every supporting Claim's (a Source Version
    outside any family is its own). `proposed` is the item exactly as the model answered."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    round: int
    task_key: str
    role_call_id: uuid.UUID
    checklist_item: str
    passage_id: str
    statement: str
    subject_company_id: uuid.UUID | None
    source_version_id: uuid.UUID | None
    quote: str
    span_start: int | None
    span_end: int | None
    epistemic_type: str
    contradicts_claim_ids: list[uuid.UUID]
    disproves_premise: str | None
    outcome: CounterevidenceOutcome
    reason_code: str | None
    reason: str | None
    assertion_id: uuid.UUID | None
    evidence_family: str | None  # a family ID, or a lone Source Version's ID
    independent: bool | None  # None when rejected
    independence_detail: str | None
    proposed: dict[str, JsonValue]
    created_at: datetime


class CardContradiction(BaseModel):
    """Accepted counterevidence, as the research card and a Hypothesis carry it."""

    model_config = ConfigDict(frozen=True)

    counterevidence_id: uuid.UUID
    checklist_item: str
    statement: str
    subject_company_id: uuid.UUID
    contradicts_claim_ids: list[uuid.UUID]
    disproves_premise: str | None
    source_span: SourceSpan  # its Assertion's quote and span (`claim_id` is the item's ID)
    evidence_family: str
    independent: bool
    independence_detail: str
    evidence_available_at: datetime


class UnsupportedFinding(BaseModel):
    """A finding the Editor wrote that cites no accepted Claim of the investigation (or cites
    something else): recorded, never shown as a finding."""

    model_config = ConfigDict(frozen=True)

    statement: str
    claim_ids: list[str]
    reason: str


class ResearchCard(BaseModel):
    """The Editor's structured research card: always a draft (spec §7.1, §7.3 step 10)."""

    model_config = ConfigDict(frozen=True)

    status: Literal["draft"]
    question: str
    findings: list[CardFinding]
    open_questions: list[str]
    unsupported_findings: list[UnsupportedFinding]
    editor_verdict: Literal["answered", "needs_review"]
    claims_considered: int
    lead_ids: list[uuid.UUID]
    disproven_premises: list[str]
    editor_role_call_id: uuid.UUID
    # The Skeptic's accepted counterevidence (independent or not); cards drawn before ticket 15
    # have none.
    contradictions: list[CardContradiction] = Field(default_factory=list[CardContradiction])


class Investigation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    theme: str
    question: str
    status: InvestigationStatus
    stop_reason: StopReason | None
    stop_detail: str | None
    paused: bool  # running, with a task held back by the queue pause (LLM quota or outage)
    resumable: bool  # stopped by the token budget: `POST .../resume` with a larger one
    run_id: uuid.UUID | None
    request: InvestigationRequest
    budgets: Budgets
    usage: Usage
    premises: list[Premise]
    tasks: list[Task]
    leads: list[InvestigationLead]
    documents: list[InvestigationDocument]
    counterevidence: list[Counterevidence]
    research_card: ResearchCard | None
    created_by: str
    created_at: datetime
    stopped_at: datetime | None


class InvestigationEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    type: str
    round: int | None
    task_key: str | None
    detail: dict[str, JsonValue]
    at: datetime


def get_investigation(
    connection: Connection, investigation_id: uuid.UUID, *, queue_paused: bool
) -> Investigation | None:
    """The investigation, or None. `queue_paused`: the queue pause holds back its task kind."""
    row = (
        connection.execute(
            text("SELECT * FROM investigation WHERE id = :id"), {"id": investigation_id}
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    params = {"id": investigation_id}
    premises = [
        Premise.model_validate(dict(each))
        for each in connection.execute(
            text(
                "SELECT p.* FROM investigation_premise p"
                " JOIN investigation i ON i.id = p.investigation_id WHERE i.id = :id"
                " ORDER BY array_position(i.seed_company_ids, p.company_id) NULLS FIRST, p.key"
            ),
            params,
        ).mappings()
    ]
    tasks = [
        Task.model_validate(dict(each))
        for each in connection.execute(
            text(
                "SELECT * FROM investigation_task WHERE investigation_id = :id"
                " ORDER BY round, position"
            ),
            params,
        ).mappings()
    ]
    leads = [
        InvestigationLead.model_validate(dict(each))
        for each in connection.execute(
            text(
                "SELECT il.rank, il.lead_id, il.discovery_id, l.url, l.canonical_url, l.title,"
                " l.snippet, l.tier FROM investigation_lead il JOIN lead l ON l.id = il.lead_id"
                " WHERE il.investigation_id = :id ORDER BY il.rank"
            ),
            params,
        ).mappings()
    ]
    documents = [
        InvestigationDocument.model_validate(dict(each))
        for each in connection.execute(
            text(
                "SELECT doc.source_version_id, t.key AS task_key, d.company_id, d.title,"
                " v.available_at FROM investigation_document doc"
                " JOIN investigation_task t ON t.id = doc.task_id"
                " JOIN source_version v ON v.id = doc.source_version_id"
                " JOIN source_document d ON d.id = v.source_document_id"
                " WHERE doc.investigation_id = :id ORDER BY t.round, t.position,"
                " v.available_at DESC, v.id"
            ),
            params,
        ).mappings()
    ]
    counterevidence = [
        Counterevidence.model_validate(dict(each))
        for each in connection.execute(
            text(
                "SELECT c.*, t.round, t.key AS task_key FROM counterevidence c"
                " JOIN skeptic_search s ON s.id = c.search_id"
                " JOIN investigation_task t ON t.id = s.task_id"
                " WHERE c.investigation_id = :id"
                " ORDER BY t.round, c.batch, c.ordinal"
            ),
            params,
        ).mappings()
    ]
    return _investigation(
        row, premises, tasks, leads, documents, counterevidence, connection, queue_paused
    )


def _investigation(
    row: RowMapping,
    premises: list[Premise],
    tasks: list[Task],
    leads: list[InvestigationLead],
    documents: list[InvestigationDocument],
    counterevidence: list[Counterevidence],
    connection: Connection,
    queue_paused: bool,
) -> Investigation:
    budgets = Budgets(
        max_rounds=row["max_rounds"],
        max_leads=row["max_leads"],
        max_documents=row["max_documents"],
        token_budget=row["token_budget"],
    )
    run_id: uuid.UUID | None = row["run_id"]
    tokens_in = tokens_out = 0
    if run_id is not None:
        usage = run_usage(connection, run_id)
        tokens_in, tokens_out = usage.tokens_in, usage.tokens_out
    running = row["status"] == "running"
    card: Any = row["research_card"]
    return Investigation(
        id=row["id"],
        theme=row["theme"],
        question=row["question"],
        status=row["status"],
        stop_reason=row["stop_reason"],
        stop_detail=row["stop_detail"],
        paused=running and queue_paused and any(t.status == "queued" for t in tasks),
        resumable=row["stop_reason"] == "budget_exhausted",
        run_id=run_id,
        request=InvestigationRequest(
            run_id=run_id,
            research_question=row["question"],
            theme_id=row["theme"],
            seed_entity_ids=row["seed_company_ids"],
            as_of_utc=row["as_of"],
            allowed_source_tiers=ALLOWED_SOURCE_TIERS,
            available_budget=budgets,
            max_depth=row["max_rounds"],
            max_new_leads=row["max_leads"],
            approved_tool_list=APPROVED_TOOLS,
            relevant_hindsight_bank=row["bank_id"],
            hypothesis_id=None,
        ),
        budgets=budgets,
        usage=Usage(
            rounds=row["round"],
            leads=len(leads),
            documents=len(documents),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        ),
        premises=premises,
        tasks=tasks,
        leads=leads,
        documents=documents,
        counterevidence=counterevidence,
        research_card=None if card is None else ResearchCard.model_validate(card),
        created_by=row["created_by"],
        created_at=row["created_at"],
        stopped_at=row["stopped_at"],
    )


def list_events(
    connection: Connection, investigation_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[InvestigationEvent], int] | None:
    """The investigation's events in order, or None if there is no such investigation."""
    exists = connection.execute(
        text("SELECT 1 FROM investigation WHERE id = :id"), {"id": investigation_id}
    ).one_or_none()
    if exists is None:
        return None
    params = {"id": investigation_id, "limit": limit, "offset": offset}
    total = connection.execute(
        text("SELECT count(*) FROM investigation_event WHERE investigation_id = :id"), params
    ).scalar_one()
    rows = connection.execute(
        text(
            "SELECT seq, type, round, task_key, detail, at FROM investigation_event"
            " WHERE investigation_id = :id ORDER BY seq LIMIT :limit OFFSET :offset"
        ),
        params,
    ).mappings()
    return [InvestigationEvent.model_validate(dict(each)) for each in rows], int(total)
