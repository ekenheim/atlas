"""What an investigation is, as the API shows it: its Â§7.2 request, budgets and usage, the plan
(premises and role tasks), the leads and documents it took, its reading pointers (where
Memory pointed) and the companies they name (which of them are read), the Skeptic's
counterevidence, the Editor's research card, and the event log."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Connection, RowMapping, text

from atlas.claims.reads import PASSAGE_SELECTED_BY
from atlas.investigations.companies import POINTED_COMPANIES
from atlas.investigations.companies import Outcome as PointedOutcome
from atlas.roles import run_repairs, run_usage
from atlas.roles.skeptic import ContradictionHow, CounterevidenceKind

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
TaskRole = Literal["scout", "investigator", "skeptic", "financial_analyst", "editor", "reader"]
# Which plan an investigation runs (bottleneck-argument ticket 05): `default`, Scout ->
# Investigators -> Skeptic || Financial Analyst -> Editor; `argument`, Scout -> one Reader per
# argument step -> Skeptic || Financial Analyst -> the Editor writing the argument.
PlanName = Literal["default", "argument"]
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

# The Â§7.2 request's fixed parts: what an investigation's roles may read and use.
ALLOWED_SOURCE_TIERS = ["A", "C"]  # Tier A archived sources as Evidence; Tier C only as leads
APPROVED_TOOLS = ["searxng_search", "source_ledger_read", "hindsight_recall"]


class Budgets(BaseModel):
    """Per-run limits (spec Â§7.4)."""

    model_config = ConfigDict(frozen=True)

    max_rounds: int
    max_leads: int
    max_documents: int
    # Investigators a round, the seeds counted (atlas.investigations.companies).
    max_companies: int
    token_budget: int


class Usage(BaseModel):
    """How much of each budget the investigation has used."""

    model_config = ConfigDict(frozen=True)

    rounds: int
    leads: int
    documents: int
    companies: int  # the current round's Investigators: its seeds' and the added ones
    tokens_in: int
    tokens_out: int
    # Schema repairs the run's role calls asked for, by role (pilot-fixes ticket 26).
    repairs: dict[str, int]


class InvestigationRequest(BaseModel):
    """The shared agent contract's request (spec Â§7.2), as every role of the run works to."""

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
    # Why it was kept (atlas.discovery.ranking): its relevance score to the query whose
    # result scored best, the reasons in words, and the ranking config's version. None (and
    # no reasons) for a lead kept before leads were ranked.
    score: float | None
    reasons: list[str]
    query: str | None
    ranking_version: int | None


class InvestigationDocument(BaseModel):
    """A Source Version an Investigator or Skeptic task read first (counted against
    `max_documents`)."""

    model_config = ConfigDict(frozen=True)

    source_version_id: uuid.UUID
    task_key: str
    company_id: uuid.UUID | None
    title: str
    available_at: datetime


class ReadingPointer(BaseModel):
    """A recalled Memory resolved to a Source Version section, with the query that recalled
    it (CONTEXT.md, "Reading pointer"; atlas.investigations.pointers): where Memory says to
    read. `memory_text` is Memory as Hindsight returned it: an index entry, never Evidence,
    never quoted. The Scout's pointers (`query_kind` `scout`) direct the Investigators'
    reading; the Skeptic's (`bear_checklist`: one query per bear-checklist item for each
    company the accepted Claims name) direct its own."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    round: int
    task_key: str  # the task that asked: `scout` or `skeptic`
    # `entity`: an entity pointer (memory-quality ticket 09; atlas.investigations.entity_hop):
    # a fact carrying the entity of `query_company_id` (the company the hop was made for; its
    # canonical name is `query`), from a document of another company, `company_id`. Its
    # `query_index` is the company's place in the hop, its `rank` the pointer's among its own.
    query_kind: Literal["scout", "bear_checklist", "entity"]
    # A Scout's: 0 for the round's question, n for its nth query. A Skeptic's: the query's
    # position among its task's queries, from 1 (companies in order, each in checklist order).
    query_index: int
    query: str
    # A bear-checklist query's item and the company it asks about (which need not be the
    # company the pointer leads to, `company_id`); None for a Scout's query.
    checklist_item: str | None
    query_company_id: uuid.UUID | None
    query_company_name: str | None
    rank: int  # the memory's place in the recall's results, from 1
    memory_id: str
    memory_type: str  # world, experience or observation
    memory_text: str
    source_version_id: uuid.UUID
    source_title: str
    section_anchor: str
    section_heading: str | None
    section_char_start: int  # code-point offsets into the parsed text: [start, end)
    section_char_end: int
    company_id: uuid.UUID | None
    company_name: str | None
    available_at: datetime  # the Source Version's, at or before the investigation's as-of time
    citation_state: Literal["resolved"]  # only resolved citations make pointers
    created_at: datetime
    # The recall's final score (relative to its own recall only) and the entity names of the
    # memory (memory-quality ticket 07); None for pointers recorded before it.
    score: float | None = None
    entity_names: list[str] | None = None
    # Which rule placed its window (memory-quality ticket 08): `chunk`, the window the chunk
    # its memory's fact was extracted from starts in, that chunk located verbatim in the
    # section at [chunk_char_start, chunk_char_end) of the parsed text; or `match`, the window
    # its Memory text matches best (every pointer recorded before ticket 08). The chunk's ID,
    # never its text; null when the fact named none, and before ticket 08.
    placed_by: Literal["chunk", "match"] = "match"
    chunk_id: str | None = None
    chunk_char_start: int | None = None
    chunk_char_end: int | None = None
    # An entity pointer's: the Hindsight entity its fact was listed by. None for the others.
    entity_id: str | None = None
    # Which recall made it (memory-quality ticket 13): `theme`, across the theme as every
    # pointer was made before; or `theme_layer`, the second recall of a Scout query that
    # carries a layer, limited to the facts labelled with `layer`.
    scope: Literal["theme", "theme_layer"] = "theme"
    layer: str | None = None


class EntityHop(BaseModel):
    """What the entity hop (memory-quality ticket 09) did for one company of a round: the
    entity it found by the company's canonical name, the facts that carry it, and why each
    made an entity pointer or not. `outcome`: `listed`; `no_entity` (no entity of exactly
    that name in Memory); `listing_failed` (the memory listing failed: an event says why);
    `entities_unavailable` (the entity listing failed, so no company was hopped)."""

    model_config = ConfigDict(frozen=True)

    round: int
    company_id: uuid.UUID
    company_name: str
    slug: str
    entity_name: str  # the company's canonical name, which its documents send
    entity_id: str | None
    outcome: Literal["listed", "no_entity", "listing_failed", "entities_unavailable"]
    facts_listed: int  # memories carrying the entity in the theme
    pointers: int  # the entity pointers it made
    own_documents: int  # facts from the company's own documents: no pointer
    after_as_of: int  # facts from a Source Version available after the as-of time
    already_pointed: int  # facts from a section a recall pointer of the round points at
    unresolved: int  # memories that resolve to no section
    beyond_limit: int  # sections past the per-company bound (ATLAS_ENTITY_HOP_MAX_FACTS)


class PointedCompany(BaseModel):
    """A company a round's reading pointers name, and what the plan did with it
    (atlas.investigations.companies): ranked by `score`, the sum of 1 / rank over the Scout's
    pointers that name it. A `seed` has its Investigator whatever its rank; another company
    got one (`added`, `task_key` its task) while the company budget had room; the rest were
    not read (`no_room`, or `premise_disproven` when its premise already was)."""

    model_config = ConfigDict(frozen=True)

    round: int
    company_id: uuid.UUID
    company_name: str
    slug: str
    pointers: int  # how many of the round's Scout recall pointers name it
    score: float  # with its entity pointers' weight (memory-quality ticket 09)
    # The best rank among its recall pointers (1: the top of a recall); None for a company
    # only the entity hop reached.
    best_rank: int | None
    outcome: PointedOutcome
    task_key: str | None  # its Investigator task; None when it was not read
    # How many of the round's entity pointers name it (0 before memory-quality ticket 09).
    entity_pointers: int = 0


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
    """A research card finding in the Â§7.2 claim shape. The statement is the Editor's; every
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
    # The Skeptic's accepted, independent contradictions of a cited Claim (ticket 15); bear
    # context never marks a finding.
    counterevidence_ids: list[uuid.UUID]
    # Until every cited Assertion is corroborated, and while a contradiction stands against it.
    needs_review: bool
    open_questions: list[str]
    # The grounding check (pilot-fixes ticket 21): every number, capitalised name and quoted
    # phrase of the statement occurs in its cited Claims (an ungrounded finding is never a
    # finding: it is listed under `unsupported_findings`). None: drawn before the check (or a
    # Hypothesis's finding, which it doesn't apply to).
    grounded: bool | None = None
    # The finding judge (bottleneck-argument ticket 04): True, it found the statement and
    # limitations say only what the cited quotes say (perhaps after one rewrite; a misstated
    # finding is never a finding). None: not judged (drawn before the judge, the judge off, or
    # its call failed, when the finding needs review). The verdicts are the card's `judged`.
    judged: bool | None = None


CounterevidenceOutcome = Literal["accepted", "rejected"]


class Counterevidence(BaseModel):
    """One item the Skeptic proposed and its outcome (like a Claim). An accepted item is an
    Assertion (predicate `counterevidence`) on a Source Version the Skeptic chose, of one
    `kind`: a contradiction of the Claims in `contradicts_claim_ids` (and `how`), or bear
    context, attached to no Claim (`kind_reason` when the Skeptic proposed it as a
    contradiction and code stored it as bear context). `independent`, a contradiction's only,
    says whether its Evidence Family differs from every supporting Claim's (a Source Version
    outside any family is its own). A rejected item keeps the kind proposed. `proposed` is the
    item exactly as the model answered."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    round: int
    task_key: str
    role_call_id: uuid.UUID
    kind: CounterevidenceKind
    kind_reason: str | None
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
    how: ContradictionHow | None  # None before migration 0053, and for bear context
    # The figure a quoted table row states, and its period (None for any other quote).
    figure_name: str | None
    figure_period: str | None
    disproves_premise: str | None
    outcome: CounterevidenceOutcome
    reason_code: str | None
    reason: str | None
    assertion_id: uuid.UUID | None
    evidence_family: str | None  # a family ID, or a lone Source Version's ID
    # None when rejected, and for bear context (kept for rows recorded before 0053).
    independent: bool | None
    independence_detail: str | None
    proposed: dict[str, JsonValue]
    created_at: datetime


class CardContradiction(BaseModel):
    """An accepted contradiction of the Claims it names, as the research card and a Hypothesis
    carry it. (Cards drawn before the kinds list every accepted item here, some naming no
    Claim, and have no `how`.)"""

    model_config = ConfigDict(frozen=True)

    counterevidence_id: uuid.UUID
    checklist_item: str
    statement: str
    subject_company_id: uuid.UUID
    contradicts_claim_ids: list[uuid.UUID]
    how: ContradictionHow | None = None
    disproves_premise: str | None
    source_span: SourceSpan  # its Assertion's quote and span (`claim_id` is the item's ID)
    evidence_family: str
    independent: bool
    independence_detail: str
    evidence_available_at: datetime


class CardBearContextItem(BaseModel):
    """One accepted bear-context item: what the quote says, and its span."""

    model_config = ConfigDict(frozen=True)

    counterevidence_id: uuid.UUID
    statement: str
    source_span: SourceSpan  # its Assertion's quote and span (`claim_id` is the item's ID)
    evidence_available_at: datetime
    # The figure a quoted table row states, and its period (None for any other quote).
    figure_name: str | None
    figure_period: str | None
    # Why code stored it as bear context, when the Skeptic proposed a contradiction.
    reason: str | None


class CardBearContext(BaseModel):
    """The bear context about one company under one bear-checklist item: what the Skeptic
    found on the checklist that contradicts no Claim. It marks no finding."""

    model_config = ConfigDict(frozen=True)

    checklist_item: str
    company_id: uuid.UUID
    company_name: str
    items: list[CardBearContextItem]


class UnsupportedFinding(BaseModel):
    """A finding the Editor wrote that cites no accepted Claim of the investigation (or cites
    something else), or whose statement says what its Claims don't even after it was asked
    again (`reason` "ungrounded: <terms>", pilot-fixes ticket 21): recorded, never shown as a
    finding."""

    model_config = ConfigDict(frozen=True)

    statement: str
    claim_ids: list[str]
    reason: str


class CardClause(BaseModel):
    """One clause of a judged statement and its basis, as the finding judge gave them
    (`finding_judge.v3`): the clause as written, the cited reference whose quote states it and
    that quote's words (None: the judge found none)."""

    model_config = ConfigDict(frozen=True)

    text: str
    ref: str | None
    basis: str | None


class CardJudgement(BaseModel):
    """One verdict of the finding judge on a finding (bottleneck-argument ticket 04): the
    statement it judged, `supported` or `misstated` with the words that go beyond the quotes
    (`beyond`), their kinds and the judge's reason; `failed` when its call gave no answer
    (`reason` says why). `attempt` 2 judges the Editor's rewrite of a misstated finding;
    `outcome` what came of the finding at this attempt. With several votes, each is a verdict
    of its own (`vote`, 1-based), the one the rule took marked `decided`. Since
    `finding_judge.v3` each carries its `clauses` and those whose basis code could not find in
    its quote (`unverified`): a `supported` vote with any is recorded `misstated`."""

    model_config = ConfigDict(frozen=True)

    finding: str  # `f1`, `f2`, ...: the finding's place among those judged
    attempt: Literal[1, 2]
    statement: str
    limitations: list[str]
    claim_ids: list[uuid.UUID]
    verdict: Literal["supported", "misstated", "failed"]
    beyond: list[str]
    kinds: list[str]
    reason: str
    outcome: Literal["kept", "sent_back", "dropped", "kept_unjudged"]
    role_call_id: uuid.UUID | None
    judge: str  # the prompt, e.g. `finding_judge.v3`
    vote: int = 1
    decided: bool = True
    clauses: list[CardClause] = Field(default_factory=list[CardClause])
    unverified: list[str] = Field(default_factory=list[str])


class CardQuery(BaseModel):
    """One query the Scout searched."""

    model_config = ConfigDict(frozen=True)

    query: str
    purpose: str | None


class CardSearch(BaseModel):
    """What one round's Scout searched: its queries, how many leads they found, and the
    leads the investigation took (in rank order; Tier C, never Evidence)."""

    model_config = ConfigDict(frozen=True)

    round: int
    discovery_id: uuid.UUID
    queries: list[CardQuery]
    leads_found: int
    lead_ids: list[uuid.UUID]


class CardDocumentRead(BaseModel):
    """A Source Version an Investigator or Skeptic task read, and the sections of the
    passages it was sent."""

    model_config = ConfigDict(frozen=True)

    source_version_id: uuid.UUID
    title: str
    sections: list[str]  # section anchors, in the order sent
    # How many passages of it were sent (0 for a card stored before pilot fix 10).
    passages: int = 0
    # How its passages sent were selected, as passages per kind of selection (`pointer`,
    # `entity_pointer` (the entity hop's channel; memory-quality ticket 09), `search`,
    # `entity`, `lead`; atlas.claims.selection; the Skeptic's have no `entity`). A
    # passage several kinds chose counts under each, so the counts can add up to more than
    # `passages`. Empty for a document none of whose passages was sent, and on cards stored
    # before memory-directed reading ticket 05 (the Skeptic's documents: before ticket 07).
    selections: dict[str, int] = Field(default_factory=dict[str, int])
    # How the pointers that chose its passages sent were placed (memory-quality ticket 08):
    # passages per rule, `chunk` (the window its fact's chunk starts in) or `match` (the
    # window its Memory text matches best); a passage pointers of both rules chose counts
    # under each. Empty when no pointer chose one, and on cards stored before ticket 08.
    pointers_placed_by: dict[str, int] = Field(default_factory=dict[str, int])
    # The Skeptic's documents: where its reading pointers led (`pointer`), matched by its
    # search, or chosen by code's fallback for a company Memory pointed at nothing of (pilot
    # fix 06; ticket 07). `plan`: chosen by its plan call, on cards stored before ticket 07.
    # None for an Investigator's.
    selected_by: Literal["pointer", "plan", "search", "fallback"] | None = None
    # An Investigator's document chosen by its document floor (its company's latest periodic
    # report or results release; pilot fix 24). False for the Skeptic's, and on cards stored
    # before it.
    floor: bool = False


class CardReading(BaseModel):
    """What one Investigator or Skeptic task read and what came of it, so a card with no
    finding (or no contradiction) still says why. For an Investigator the counts are its
    extraction's Claims; for the Skeptic (pilot fix 06) its proposed counterevidence items."""

    model_config = ConfigDict(frozen=True)

    round: int
    task_key: str
    company_id: uuid.UUID | None  # None for the Skeptic
    company_name: str | None
    status: str  # the task's status
    detail: str | None  # why it read nothing (the budget spent, nothing available), if so
    documents: list[CardDocumentRead]
    documents_dropped: int  # available but left out by the document budget
    passages: int
    claims_proposed: int  # the Skeptic's: counterevidence items proposed
    claims_accepted: int  # the Skeptic's: counterevidence items accepted
    rejected: dict[str, int]  # reason code -> how many proposed items it rejected
    # Cards drawn before pilot fix 06 have only Investigators' rows.
    role: Literal["investigator", "skeptic"] = "investigator"
    # The Skeptic's: code chose documents for a company the Claims name that Memory pointed
    # at nothing of (before ticket 07: that its plan chose nothing of).
    documents_fallback: bool = False


class CardCompanyNotRead(BaseModel):
    """A company a round's reading pointers name that got no Investigator, so the next
    investigation can seed it (atlas.investigations.companies)."""

    model_config = ConfigDict(frozen=True)

    round: int
    company_id: uuid.UUID
    company_name: str
    pointers: int  # how many of the round's Scout recall pointers name it
    score: float  # the sum of 1 / rank over them, and its entity pointers' weight
    best_rank: int | None  # None: only the entity hop reached it
    reason: str  # the company budget had no room, or its premise was disproven
    # How many entity pointers name it, and the channels that reached it: `recall` (the
    # Scout's recall pointers) and `entity` (the entity hop; memory-quality ticket 09).
    entity_pointers: int = 0
    channels: list[Literal["recall", "entity"]] = Field(
        default_factory=list[Literal["recall", "entity"]]
    )


class CardSkepticDocument(BaseModel):
    """A document the Skeptic read for a company, and how much of it."""

    model_config = ConfigDict(frozen=True)

    source_version_id: uuid.UUID
    title: str
    passages: int  # the passages of it the Skeptic was sent


class CardSkepticCompany(BaseModel):
    """What the Skeptic did for one company the accepted Claims name (pilot-fixes ticket 25,
    the disclosure part): `checked` (it was sent passages of at least one document of the
    company; its outcome is how many items it accepted) or `not_checked` with the reason.
    Written by code from the Skeptic's records, so "no contradiction" on the card never
    stands for a company it did not read."""

    model_config = ConfigDict(frozen=True)

    company_id: uuid.UUID
    company_name: str
    claims: int  # the accepted Claims that name it (as subject or object)
    outcome: Literal["checked", "not_checked"]
    documents: list[CardSkepticDocument]
    passages: int
    contradictions: int  # accepted items about it of each kind
    bear_context: int
    # Set when not checked: a code, and the reason in words.
    reason_code: (
        Literal["skeptic_not_run", "no_budget", "only_tier_b_pointed", "no_document", "not_chosen"]
        | None
    ) = None
    reason: str | None = None


class CardClaimSummary(BaseModel):
    """An accepted Claim as the card lists it when the Editor failed: what it states and
    where (its quote and span are in the Evidence tray)."""

    model_config = ConfigDict(frozen=True)

    claim_id: uuid.UUID
    predicate: str
    object: str  # the object company's name, or the product/material/technology named
    layer: str | None
    source_version_id: uuid.UUID
    source_title: str


class CardCompanyClaims(BaseModel):
    """A company's accepted Claims (as their subject), as the card lists them when the
    Editor failed."""

    model_config = ConfigDict(frozen=True)

    company_id: uuid.UUID
    company_name: str
    claims: list[CardClaimSummary]


CardStepStatus = Literal["supported", "disputed", "unknown"]


class CardFactQuantity(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: float
    unit: str
    metric: str


class CardFactRelation(BaseModel):
    """What a Skeptic Fact does to one Fact it challenges, as the counter-judge labelled it
    (`atlas.roles.counter_judge`): `contradicts`, `limits`, `dates`, `qualifies`, `supports`,
    `unrelated`, or `unjudged` when no label could be had (its call failed, or it was never
    asked)."""

    model_config = ConfigDict(frozen=True)

    fact_id: uuid.UUID  # the challenged Fact
    relation: str
    reason: str | None


class CardFact(BaseModel):
    """A Fact (`atlas.facts`) as the argument card shows it: what its quote states, with the
    quantity, period and status the Reader recorded, and its quote's span (`source_span`;
    `claim_id` and `assertion_id` are both the Fact's ID). A Skeptic's Fact names the Facts it
    speaks against (`against`: those the counter-judge found it contradicts, limits or dates, or
    could not judge) and what it does to each Fact it challenges (`relations`, pilot-review
    T3)."""

    model_config = ConfigDict(frozen=True)

    fact_id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    step: str
    status: str  # in_effect, planned, in_development, hedged, regulatory, reported_by_third_party
    statement: str
    quantity: CardFactQuantity | None
    period: str | None
    source_title: str
    source_span: SourceSpan
    evidence_available_at: datetime
    against: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])
    relations: list[CardFactRelation] = Field(default_factory=list[CardFactRelation])


class CardStepStatement(BaseModel):
    """One of a step's statements that passed the grounding check and the finding judge, with
    the Facts it cites (`facts`) and the counterevidence it weighs (`counterevidence`)."""

    model_config = ConfigDict(frozen=True)

    statement: str
    facts: list[CardFact]
    counterevidence: list[CardFact]
    judged: bool | None  # True: the judge found it supported; None: kept unjudged


class CardArgumentStep(BaseModel):
    """One step of the argument (bottleneck-argument ticket 05): its status, the Editor's
    statements (each held to its Facts' quotes by the grounding check and the finding judge
    on its own; the ones that passed, `statements`; `statement` is the first of them, or None,
    kept for older readers), the Facts behind it, the Skeptic's counterevidence, and what
    remains unchecked. The status is code's: `unknown` without a statement that passed or
    without a Fact; `disputed` when a Skeptic Fact contradicts, limits or dates one of the
    step's Facts (or the Facts its statements cite), or could not be judged against it; else
    `supported`. `contested`: a judged contradiction stands against the step's Facts, whatever
    its status. `editor_status` is what the Editor proposed."""

    model_config = ConfigDict(frozen=True)

    step: str
    title: str
    asks: str
    status: CardStepStatus
    editor_status: CardStepStatus | None
    statement: str | None
    statements: list[CardStepStatement] = Field(default_factory=list[CardStepStatement])
    facts: list[CardFact]
    counterevidence: list[CardFact]
    unchecked: list[str]
    grounded: bool | None
    judged: bool | None
    # What its Reader did: the queries searched, the documents read, the Facts it recorded and
    # had refused, its summary, and why it stopped.
    searched: list[str] = Field(default_factory=list[str])
    documents_read: list[str] = Field(default_factory=list[str])
    facts_refused: int = 0
    reader_summary: str | None = None
    reader_stop: str | None = None
    # Whether the Skeptic was sent this step's Facts to challenge.
    skeptic_checked: bool = False
    # Whether a Skeptic Fact was judged to contradict, limit or date one of its Facts.
    contested: bool = False


class ResearchCard(BaseModel):
    """The Editor's structured research card: always a draft (spec Â§7.1, Â§7.3 step 10).

    When the Editor fails (its answer cut off at its output cap's bound, or quarantined), the
    card is code's alone: no finding, `editor_failure` saying why, the accepted Claims by
    company (`claims_by_company`) and, as on every card, the contradictions, bear context and
    what was searched and read (memory-quality ticket 16)."""

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
    # The Skeptic's accepted contradictions (independent or not); cards drawn before ticket 15
    # have none.
    contradictions: list[CardContradiction] = Field(default_factory=list[CardContradiction])
    # The Skeptic's accepted bear context, by checklist item (in checklist order) and company;
    # cards drawn before the kinds have none (their `contradictions` hold every accepted item).
    bear_context: list[CardBearContext] = Field(default_factory=list[CardBearContext])
    # What the investigation searched and read, and why nothing was accepted (pilot fix 01);
    # cards drawn before it have neither.
    searched: list[CardSearch] = Field(default_factory=list[CardSearch])
    read: list[CardReading] = Field(default_factory=list[CardReading])
    # The companies the reading pointers name that no Investigator read, every round, best
    # ranked first (memory-directed reading ticket 06); cards drawn before it have none.
    not_read: list[CardCompanyNotRead] = Field(default_factory=list[CardCompanyNotRead])
    # What the Skeptic read for each company the accepted Claims name, and which it did not
    # check (pilot-fixes ticket 25, disclosure); cards drawn before it have none.
    skeptic_coverage: list[CardSkepticCompany] = Field(default_factory=list[CardSkepticCompany])
    # The limit of the grounding check (pilot-fixes ticket 21), stated on the card; None on
    # cards drawn before it.
    grounding_limit: str | None = None
    # The finding judge's verdicts, every finding and attempt in order (bottleneck-argument
    # ticket 04); empty on cards drawn before it or with the judge off.
    judged: list[CardJudgement] = Field(default_factory=list[CardJudgement])
    # Why the Editor wrote no card (None: it did); then the card lists the accepted Claims by
    # company instead of findings. Cards drawn before memory-quality ticket 16 have neither.
    editor_failure: str | None = None
    claims_by_company: list[CardCompanyClaims] = Field(default_factory=list[CardCompanyClaims])
    # The plan that drew it, and the argument plan's steps (bottleneck-argument ticket 05; its
    # card has no `findings`: each step's statement is its finding).
    plan: PlanName = "default"
    steps: list[CardArgumentStep] = Field(default_factory=list[CardArgumentStep])


class EvidenceItem(BaseModel):
    """An accepted Claim of the investigation (the Evidence tray): the Assertion it became and
    its source span. `excluded`: read by a task whose premise was disproven, so the Editor
    leaves it out."""

    model_config = ConfigDict(frozen=True)

    claim_id: uuid.UUID
    assertion_id: uuid.UUID
    round: int
    task_key: str
    subject_company_id: uuid.UUID
    subject_name: str
    predicate: str
    object_company_id: uuid.UUID | None
    object_name: str | None
    object_text: str | None
    product: str | None
    layer: str | None  # null: the Claim's quote names no layer (`atlas.claims.layer_term`)
    epistemic_type: str
    quote: str
    source_version_id: uuid.UUID
    span_start: int
    span_end: int
    source_title: str
    available_at: datetime
    evidence_family: str  # a family ID, or a lone Source Version's ID
    verification_status: str  # the Assertion's review state
    excluded: bool
    # The selections that chose the passage the Claim quotes (its `selected_by`): which of
    # pointer, search, entity or lead found it (atlas.claims.selection).
    passage_selected_by: list[str] = Field(default_factory=list[str])
    # Who says the quoted words, when the document is a call or conference transcript: the
    # paragraph's speaker label, one of the company's own people (`atlas.claims.speakers`).
    # Null for every other document.
    speaker: str | None = None


class FollowUp(BaseModel):
    """A follow-up round: the open question it pursues, and the research card as it stood
    when the round began."""

    model_config = ConfigDict(frozen=True)

    round: int
    question: str
    requested_by: str
    requested_at: datetime
    card_before: ResearchCard


class Investigation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    theme: str
    question: str
    plan: PlanName
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
    # Where Memory pointed, by round, asking task (the Scout, then the Skeptic), query and
    # rank (Memory as an index, never Evidence). Recall pointers only: the entity hop's are
    # `entity_pointers`.
    pointers: list[ReadingPointer]
    # The companies those pointers and the entity pointers name, by round and weight, and
    # which of them are read: the seeds, the ones an Investigator was added for, the ones left
    # out. Empty for a round until its Scout has succeeded.
    pointed_companies: list[PointedCompany]
    # The entity hop (memory-quality ticket 09): its pointers, by round, company hopped and
    # rank (a reason to read, never an edge or Evidence), and what it did for each company.
    entity_pointers: list[ReadingPointer] = Field(default_factory=list[ReadingPointer])
    entity_hops: list[EntityHop] = Field(default_factory=list[EntityHop])
    documents: list[InvestigationDocument]
    counterevidence: list[Counterevidence]
    research_card: ResearchCard | None
    evidence: list[EvidenceItem]  # the Evidence tray
    follow_ups: list[FollowUp]
    created_by: str
    created_at: datetime
    stopped_at: datetime | None


class InvestigationSummary(BaseModel):
    """An investigation as the workbench lists it."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    theme: str
    question: str
    plan: PlanName
    seed_company_ids: list[uuid.UUID]
    round: int
    status: InvestigationStatus
    stop_reason: StopReason | None
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
                # The question, the seeds in their order, then the added companies' by key.
                " ORDER BY p.company_id IS NOT NULL,"
                " array_position(i.seed_company_ids, p.company_id) NULLS LAST, p.key"
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
                " l.snippet, l.tier, il.score, il.reasons, il.query, il.ranking_version"
                " FROM investigation_lead il JOIN lead l ON l.id = il.lead_id"
                " WHERE il.investigation_id = :id ORDER BY il.rank"
            ),
            params,
        ).mappings()
    ]
    pointers = [
        ReadingPointer.model_validate(dict(each))
        for each in connection.execute(
            text(
                "SELECT p.id, p.round, t.key AS task_key, p.query_kind, p.query_index,"
                " p.query, p.checklist_item, p.query_company_id,"
                " qc.display_name AS query_company_name, p.rank,"
                " p.memory_id, p.memory_type, p.memory_text, p.source_version_id,"
                " d.title AS source_title, p.section_anchor, p.section_heading,"
                " p.section_char_start, p.section_char_end, p.company_id,"
                " c.display_name AS company_name, p.available_at, p.citation_state,"
                " p.created_at, p.score, p.entity_names, p.placed_by, p.chunk_id,"
                " p.chunk_char_start, p.chunk_char_end, p.entity_id, p.scope, p.layer"
                " FROM reading_pointer p"
                " JOIN investigation_task t ON t.id = p.task_id"
                " JOIN source_version v ON v.id = p.source_version_id"
                " JOIN source_document d ON d.id = v.source_document_id"
                " LEFT JOIN company c ON c.id = p.company_id"
                " LEFT JOIN company qc ON qc.id = p.query_company_id"
                " WHERE p.investigation_id = :id"
                " ORDER BY p.round, t.position, p.query_index, p.scope, p.rank,"
                " p.source_version_id,"
                " p.section_char_start, p.section_anchor"
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
    follow_ups = [
        FollowUp.model_validate(dict(each))
        for each in connection.execute(
            text(
                "SELECT round, question, requested_by, requested_at, card_before"
                " FROM investigation_follow_up WHERE investigation_id = :id ORDER BY round"
            ),
            params,
        ).mappings()
    ]
    hypothesis_id: uuid.UUID | None = connection.execute(
        text("SELECT id FROM hypothesis WHERE investigation_id = :id"), params
    ).scalar_one_or_none()
    return _investigation(
        row,
        _Parts(
            premises=premises,
            tasks=tasks,
            leads=leads,
            pointers=pointers,
            documents=documents,
            counterevidence=counterevidence,
            evidence=_evidence(connection, investigation_id, row["run_id"]),
            follow_ups=follow_ups,
            hypothesis_id=hypothesis_id,
        ),
        connection,
        queue_paused,
    )


@dataclass(frozen=True)
class _Parts:
    premises: list[Premise]
    tasks: list[Task]
    leads: list[InvestigationLead]
    pointers: list[ReadingPointer]
    documents: list[InvestigationDocument]
    counterevidence: list[Counterevidence]
    evidence: list[EvidenceItem]
    follow_ups: list[FollowUp]
    hypothesis_id: uuid.UUID | None


def _evidence(
    connection: Connection, investigation_id: uuid.UUID, run_id: uuid.UUID | None
) -> list[EvidenceItem]:
    """The run's accepted Claims on the investigation's documents, oldest first."""
    if run_id is None:
        return []
    rows = connection.execute(
        text(
            "SELECT c.id AS claim_id, c.assertion_id, t.round, t.key AS task_key,"  # noqa: S608 (constant fragments)
            " c.subject_company_id, s.display_name AS subject_name, c.predicate,"
            " c.object_company_id, o.display_name AS object_name, c.object_text, c.product,"
            " c.layer, c.epistemic_type, c.quote, c.source_version_id, c.span_start,"
            " c.span_end, c.speaker, d.title AS source_title, v.available_at,"
            " coalesce('family:' || m.evidence_family_id::text,"
            "  'version:' || c.source_version_id::text) AS evidence_family,"
            " a.verification_status,"
            " EXISTS (SELECT FROM investigation_premise p WHERE p.investigation_id = :id"
            "  AND p.status = 'disproven' AND p.key = ANY(t.premise_keys)) AS excluded,"
            f" {PASSAGE_SELECTED_BY} AS passage_selected_by"
            " FROM claim c"
            " JOIN investigation_document doc ON doc.investigation_id = :id"
            "  AND doc.source_version_id = c.source_version_id"
            " JOIN investigation_task t ON t.id = doc.task_id"
            " JOIN assertion a ON a.id = c.assertion_id"
            " JOIN source_version v ON v.id = c.source_version_id"
            " JOIN source_document d ON d.id = v.source_document_id"
            " JOIN company s ON s.id = c.subject_company_id"
            " LEFT JOIN company o ON o.id = c.object_company_id"
            " LEFT JOIN evidence_family_member m ON m.source_version_id = c.source_version_id"
            " WHERE c.run_id = :run AND c.outcome = 'accepted'"
            " ORDER BY c.created_at, c.id"
        ),
        {"id": investigation_id, "run": run_id},
    ).mappings()
    return [EvidenceItem.model_validate(dict(each)) for each in rows]


def _pointed_companies(tasks: list[Task]) -> list[PointedCompany]:
    """Each round's ranking of the companies its pointers name, as its Scout task recorded
    it when the plan grew (atlas.investigations.service); rounds in order, best ranked first."""
    pointed: list[PointedCompany] = []
    for task in tasks:
        recorded = task.artifacts.get(POINTED_COMPANIES) if task.role == "scout" else None
        if isinstance(recorded, list):
            pointed.extend(
                PointedCompany.model_validate({"round": task.round} | dict(each))
                for each in recorded
                if isinstance(each, dict)
            )
    return pointed


def _entity_hops(tasks: list[Task]) -> list[EntityHop]:
    """Each round's entity hop, as its Scout task recorded it; rounds in order, the companies
    in the order hopped."""
    hops: list[EntityHop] = []
    for task in tasks:
        recorded = task.artifacts.get("entity_hop") if task.role == "scout" else None
        if isinstance(recorded, list):
            hops.extend(
                EntityHop.model_validate({"round": task.round} | dict(each))
                for each in recorded
                if isinstance(each, dict)
            )
    return hops


def _investigation(
    row: RowMapping, parts: _Parts, connection: Connection, queue_paused: bool
) -> Investigation:
    tasks = parts.tasks
    budgets = Budgets(
        max_rounds=row["max_rounds"],
        max_leads=row["max_leads"],
        max_documents=row["max_documents"],
        max_companies=row["max_companies"],
        token_budget=row["token_budget"],
    )
    run_id: uuid.UUID | None = row["run_id"]
    tokens_in = tokens_out = 0
    repairs: dict[str, int] = {}
    if run_id is not None:
        usage = run_usage(connection, run_id)
        tokens_in, tokens_out = usage.tokens_in, usage.tokens_out
        repairs = run_repairs(connection, run_id)
    running = row["status"] == "running"
    card: Any = row["research_card"]
    return Investigation(
        id=row["id"],
        theme=row["theme"],
        question=row["question"],
        plan=row["plan"],
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
            hypothesis_id=parts.hypothesis_id,
        ),
        budgets=budgets,
        usage=Usage(
            rounds=row["round"],
            leads=len(parts.leads),
            documents=len(parts.documents),
            companies=sum(1 for t in tasks if t.role == "investigator" and t.round == row["round"]),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            repairs=repairs,
        ),
        premises=parts.premises,
        tasks=tasks,
        leads=parts.leads,
        pointers=[p for p in parts.pointers if p.query_kind != "entity"],
        pointed_companies=_pointed_companies(tasks),
        entity_pointers=[p for p in parts.pointers if p.query_kind == "entity"],
        entity_hops=_entity_hops(tasks),
        documents=parts.documents,
        counterevidence=parts.counterevidence,
        research_card=None if card is None else ResearchCard.model_validate(card),
        evidence=parts.evidence,
        follow_ups=parts.follow_ups,
        created_by=row["created_by"],
        created_at=row["created_at"],
        stopped_at=row["stopped_at"],
    )


def list_investigations(
    connection: Connection, *, limit: int, offset: int
) -> tuple[list[InvestigationSummary], int]:
    """Investigations, newest first."""
    total = connection.execute(text("SELECT count(*) FROM investigation")).scalar_one()
    rows = connection.execute(
        text(
            "SELECT id, theme, question, plan, seed_company_ids, round, status, stop_reason,"
            " created_by, created_at, stopped_at FROM investigation"
            " ORDER BY created_at DESC, id LIMIT :limit OFFSET :offset"
        ),
        {"limit": limit, "offset": offset},
    ).mappings()
    return [InvestigationSummary.model_validate(dict(each)) for each in rows], int(total)


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
