"""The Skeptic's task (spec "Research workflow"; build plan §7.1 Skeptical Reviewer): an
independent search for counterevidence, driven by the bear checklist (atlas.roles.skeptic).
What it finds is recorded as one of two kinds, never both: a **contradiction** of a named
supporting Claim, or **bear context** about a company (memory-directed reading, ticket 03).

It runs after every Investigator task, beside the Financial Analyst (in either order), in the
investigation's run and within its budgets. The task runner skips it, without an LLM call,
when the Investigators accepted no Claim (there is nothing to challenge). Otherwise one
`skeptic_search` row holds its progress, so a retried, paused or budget-resumed task
continues where it stopped:

1. **Memory chooses what it reads** (memory-directed reading, ticket 07). Before any LLM
   call, one scoped recall per bear-checklist item for each company the supporting Claims
   name: their subjects, and their object companies that are researched universe companies
   (a counterparty has no archive). The recall is across the investigation's theme
   (atlas.research; no LLM call, counted against no budget), so another company's filing
   that names the company can answer. The query is deterministic text
   (`atlas.roles.skeptic.bear_query`): the company's name, the item's words and the objects
   of the Claims that name the company. At most `MAX_RECALL_COMPANIES` companies are asked
   about (the seed companies among them first, in seed order, then the others in the Claims'
   order): at most 36 recalls. What resolves is stored as the task's **reading pointers**
   (atlas.investigations.pointers: `query_kind` `bear_checklist`, with the checklist item
   and the company asked about), with the same failure rules as the Scout's (a Hindsight
   quota or outage pauses the task before anything is spent).
   **No Memory is sent to the Skeptic; Memory chooses what it reads.** A pointer's text finds
   a window and goes no further: no role request carries it, and Memory is never a witness.
2. **Plan.** One `skeptic` call (`SKEPTIC_PLAN`) is sent the question, the checklist, the
   supporting Claims as request fields (what to challenge, never quoted data) and the seed
   companies, and answers its own web queries. Code keeps the first `max_queries` distinct
   ones. The plan chooses no document, so an empty answer (pilot investigation 1 on 0.2.5),
   or one quarantined after its repair (`skeptic_plan_quarantined`), only means that nothing
   is searched: the Skeptic still reads.
3. **Search.** Each query is searched once with SearXNG, and its `filing_phrase`, when it has
   one and the channel is on, with EDGAR full-text search over the 18 months before the
   as-of time (atlas.discovery.edgar_fts), the results stored as Tier C leads in a discovery
   of the run (atlas.discovery.leads): a lead is never Evidence. A failed search is recorded
   on its query and the others proceed.
4. **Documents**, in reading order, each once, with who chose it (`selected_by`):
   - `pointer`: the Source Versions the task's pointers lead to, best pointer first (its
     rank in its recall, then the earlier query). Only a parsed Tier A version is followed:
     the Skeptic's witnesses are Tier A archived documents, as before.
   - `search`: a search result whose canonical URL is a catalog document's (an EDGAR filing
     hit on an archived filing, say). The catalog is the latest parsed Tier A version of
     each Source Document of the investigation's and theme's companies available at the
     as-of time (newest first, at most `CATALOG_LIMIT`).
   - `fallback` (pilot fix 06, now per company): for each company the Claims name that no
     pointer document was chosen of and that has one archived, its latest 10-K and latest
     10-Q (its latest two primary documents when it has neither), and, when none of those is
     one the investigation already read, the newest document of it the investigation read
     (which costs no budget, so the company is read even when the Investigators spent the
     budget). A `skeptic_documents_fallback` event and the task's `documents_fallback` say
     Memory pointed at nothing of those companies.
   A document the investigation hasn't read yet is counted against the document budget, the
   rest dropped (`document_budget_reached`). A follow-up round's pointer and fallback
   documents leave out the ones an earlier round's Skeptic read.
5. **Passages** (atlas.claims.selection, as the Investigator's): each chosen document's
   parsed text is cut into sections and windows; the windows the pointers lead to (by rank)
   and the windows a term search ranks highest for the bear-checklist queries (by score) are
   taken alternately, at most `investigator_max_passages`, with a floor of one passage for
   each periodic report and results release and a ceiling per document; a document with
   neither kind of window gives its lead windows last. Each passage records every selection
   that chose it (`pointer:<checklist item>`, `search`, `lead`) and the checklist items
   whose cues its text matches (a hint for the reading; possibly none). Pointer and search
   candidates not taken are counted as dropped.
6. **Reading.** The passages go to `SKEPTIC` `investigator_passages_per_call` at a time, their
   text as quoted, low-trust data. Progress is stored per batch; a quarantined answer counts
   as a batch with nothing proposed. A spent token budget stops the task `budget_exhausted`.
7. **Checks** per proposed item, the first failure being the rejection: the checklist item is
   known (`unknown_checklist_item`); **the passage is one sent in that call**
   (`not_a_witness`: Memory, a lead, another role's Claim or anything else is never a
   witness); the subject is a known company (`unknown_company`); every contradicted Claim is a
   supporting Claim (`unknown_claim`); a premise it disproves is an open company premise
   (`unknown_premise`); the offsets lie in the passage (`quote_outside_passage`); the quote is
   at the offsets or has exactly one occurrence in the passage (`quote_mismatch`,
   `quote_ambiguous`); the Assertion span check; in a call or conference transcript, the quote
   is one speaker's words and that speaker one of the document's company's own people, as
   for the Investigator's Claims (`speaker_mixed`, `analyst_speaking`, `speaker_unknown`;
   `atlas.claims.speakers`, pilot-fixes ticket 22); the quote names the subject unless the
   document is the subject's own (`party_not_in_quote`); and a quote that is a table row with
   no words (a label and its figures: "Inventories 2,126,823 1,437,636", `is_table_row`)
   comes with its figure's name and period (`table_row_without_figure`).
8. **The kind** of an item that passed, decided by code from what the Skeptic proposed:
   - a **contradiction** names at least one supporting Claim and says how it contradicts it
     (`how`: `denies`, `limits` or `dates`), and its quote names that Claim's subject company
     or its object: the object company by name, or the Claim's object text (as the
     Investigator's object check reads it, `names_object`; an object text of generic words
     names nothing). The filer's "we" is not a name here: a risk factor in the subject's own
     filing would otherwise contradict every Claim about it. It is kept against the Claims its
     quote names; the others it listed are left out.
   - everything else is **bear context**: a checklist item, a company and a span, attached to
     no Claim. An item proposed as a contradiction that names no Claim, doesn't say how, quotes
     a table row, or whose quote names neither the subject nor the object of any Claim it
     listed is stored as bear context, with the reason (`kind_reason`). Bear context disproves
     no premise.
9. **Accepted** counterevidence of either kind is an Assertion (predicate `counterevidence`,
   extractor `skeptic.v<N>`, created by `atlas-skeptic`), recorded with its `counterevidence`
   row and audited (`counterevidence.accepted` / `.rejected`). **Independence** is a property
   of contradictions: its Evidence Family (a Source Version outside any family is its own)
   against the supporting Claims' families: the same family is not an independent witness,
   however many copies say it. Bear context records its family and no independence. Only an
   independent contradiction marks a finding contradicted (`counterevidence_by_claim`) and
   may flag a published Hypothesis version (atlas.proposed_updates).
10. **Premises.** When the task finishes, each open company premise named by an accepted,
   independent contradiction is disproven by `atlas-skeptic` (the task runner applies it
   under the investigation's lock, cancelling only what depends on it). The question premise
   stays the researcher's to disprove.
"""

import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.archive import Archive
from atlas.assertions import AssertionCreate, Assertions, InvalidAssertion, check_quote
from atlas.audit import Actor, content_hash, record
from atlas.claims.predicates import company_names, is_generic_object, mentions, names_object
from atlas.claims.selection import Document, Pointer, Reading, ceiling, select, selections
from atlas.claims.speakers import TRANSCRIPT_SOURCE_TYPE, SpeakerRefusal, transcript_speaker
from atlas.discovery.edgar_fts import EdgarFullTextSearch
from atlas.discovery.leads import canonical_url
from atlas.discovery.searxng import SearXNGClient
from atlas.discovery.service import add_query, filing_window, run_searches
from atlas.investigations.model import (
    CardBearContext,
    CardBearContextItem,
    CardContradiction,
    SourceSpan,
)
from atlas.investigations.pointers import (
    BEAR_CHECKLIST_QUERY,
    PointerQuery,
    Recall,
    SkepticPointer,
    record_pointers,
    skeptic_pointers,
)
from atlas.investigations.service import event
from atlas.proposed_updates.triggers import on_counterevidence
from atlas.roles import QuotedText, RoleCaller, RoleOutputQuarantined, TokenBudgetExhausted
from atlas.roles.skeptic import (
    BEAR_CHECKLIST,
    CHECKLIST_NAMES,
    SKEPTIC,
    SKEPTIC_PLAN,
    SKEPTIC_PROMPT_VERSION,
    ChecklistOption,
    ContradictionHow,
    CounterevidenceKind,
    KnownCompany,
    PassageInfo,
    PremiseOption,
    ProposedCounterevidence,
    SeedCompany,
    SkepticPlanRequest,
    SkepticRequest,
    SupportingClaim,
    bear_query,
    checklist_matches,
)

SKEPTIC_ACTOR = Actor("atlas-skeptic")
EXTRACTOR_VERSION = f"skeptic.v{SKEPTIC_PROMPT_VERSION}"
COUNTEREVIDENCE_PREDICATE = "counterevidence"
FALLBACK_EVENT = "skeptic_documents_fallback"
PLAN_QUARANTINED_EVENT = "skeptic_plan_quarantined"
CATALOG_LIMIT = 60
# The companies the Skeptic asks Memory about, at most: one recall per bear-checklist item
# each, so at most 6 x 6 = 36 recalls a task (the Scout makes at most 11).
MAX_RECALL_COMPANIES = 6
# The Skeptic's witnesses: Tier A archived documents.
_WITNESS_TIER = "A"
_PARSED = ("parsed", "incomplete")
_ERROR_LIMIT = 500
_SPACE = re.compile(r"\s+")


# Who chose a document: Memory's pointers, the Skeptic's search, or code's fallback (`plan`:
# the plan call, before memory-directed reading ticket 07).
type Selection = Literal["pointer", "plan", "search", "fallback"]


class SkepticDocument(BaseModel):
    """A Source Version the Skeptic chose to read, and why."""

    model_config = ConfigDict(frozen=True)

    source_version_id: uuid.UUID
    checklist_item: str | None
    selected_by: Selection
    counted: bool  # new to the investigation: counted against the document budget


class SkepticPassage(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    source_version_id: uuid.UUID
    section_anchor: str
    char_start: int
    char_end: int
    checklist_items: list[str]  # the checklist items whose cues its text matches
    # Every selection that chose it (atlas.claims.selection): `pointer:<checklist item>`,
    # `search`, `lead`. Empty for a passage chosen before memory-directed reading ticket 07.
    selected_by: list[str] = Field(default_factory=list[str])


@dataclass(frozen=True)
class Disproof:
    premise_key: str
    reason: str
    counterevidence_ids: list[uuid.UUID]


@dataclass
class SkepticOutcome:
    status: Literal["succeeded", "budget_exhausted"]
    detail: str | None = None
    artifacts: dict[str, JsonValue] = field(default_factory=dict[str, JsonValue])
    disproofs: list[Disproof] = field(default_factory=list[Disproof])


@dataclass(frozen=True)
class _Version:
    id: uuid.UUID
    company_id: uuid.UUID | None
    company: str | None
    title: str
    form_type: str | None
    document_type: str | None
    available_at: datetime
    canonical_url: str
    parsed_object_uri: str
    source_tier: str
    provider: str | None
    source_type: str  # its Source Document's (`transcript`: a call or conference transcript)
    items: tuple[str, ...]  # its filing's 8-K Items


# A version's columns, as `_version` reads them (aliases `v`, `d` and `c`).
_VERSION_COLUMNS = (
    "v.id, d.company_id, c.display_name AS company, d.title, d.form_type, d.document_type,"
    " v.available_at, d.canonical_url, v.parsed_object_uri, d.source_tier, d.provider,"
    " d.source_type, v.metadata -> 'items' AS items"
)


def _version(row: RowMapping) -> _Version:
    fields = dict(row)
    items: Any = fields.pop("items")
    recorded = cast(list[Any], items) if isinstance(items, list) else []
    return _Version(**fields, items=tuple(str(item) for item in recorded))


@dataclass(frozen=True)
class _Company:
    id: uuid.UUID
    names: list[str]


@dataclass(frozen=True)
class _Named:
    """A researched company the supporting Claims name, and what those Claims say it is
    related to: the other party's name or the object text, and the product, in the Claims'
    order."""

    id: uuid.UUID
    name: str
    objects: list[str]


@dataclass(frozen=True)
class _Judged:
    """A proposed item as code judged it. Rejected by a check (a `reason_code`), it keeps
    what was proposed; accepted (an `assertion`), its kind, Claims and premise are code's
    (step 8)."""

    source_version_id: uuid.UUID | None
    subject_company_id: uuid.UUID | None
    span: tuple[int, int] | None
    contradicts: list[uuid.UUID]
    kind: CounterevidenceKind
    how: ContradictionHow | None
    disproves_premise: str | None
    kind_reason: str | None = None  # why an accepted item is bear context, when code made it so
    assertion: AssertionCreate | None = None
    reason_code: str | None = None
    reason: str | None = None


class Skeptic:
    """One Skeptic task's work (see the module), with the caller's clients."""

    def __init__(
        self,
        engine: Engine,
        archive: Archive,
        caller: RoleCaller,
        searxng: SearXNGClient,
        recall: Recall,
        *,
        max_queries: int,
        max_passages: int,
        max_document_share: float,
        passages_per_call: int,
        edgar: EdgarFullTextSearch | None = None,
    ) -> None:
        self._engine = engine
        self._archive = archive
        self._caller = caller
        self._searxng = searxng
        self._recall = recall  # across the investigation's theme
        self._edgar = edgar
        self._max_queries = max_queries
        self._max_passages = max_passages
        self._max_document_share = max_document_share
        self._passages_per_call = passages_per_call
        self._assertions = Assertions(engine, archive, SKEPTIC_ACTOR)
        self._texts: dict[uuid.UUID, str] = {}

    def run(
        self,
        investigation: RowMapping,
        task: RowMapping,
        run_id: uuid.UUID,
        *,
        theme_title: str,
        company_ids: Sequence[uuid.UUID],
        claims: Sequence[RowMapping],
        supporting_families: set[str],
    ) -> SkepticOutcome:
        """`company_ids`: the investigation's and the theme's companies, whose archived
        documents a search result may match (the catalog)."""
        search = self._open(investigation, task, run_id)
        named = self._named(investigation, claims)
        queries = _queries(named)
        # Before any LLM call: a Hindsight quota or outage pauses the task with nothing spent,
        # and a later attempt finds the pointers recorded and asks nothing again.
        record_pointers(
            self._engine, self._recall, investigation, task, queries, actor=SKEPTIC_ACTOR
        )
        if search["phase"] == "planning":
            self._plan(investigation, task, search, theme_title, claims)
            search = self._load(search["id"])
        if search["phase"] == "searching":
            catalog = self._catalog(investigation, company_ids)
            self._search(investigation, task, search, catalog, named, queries)
            search = self._load(search["id"])
        if search["phase"] == "reading":
            stopped = self._read(investigation, search, claims, supporting_families)
            search = self._load(search["id"])
            if stopped:
                return SkepticOutcome(
                    "budget_exhausted",
                    detail="the run's token budget ran out during the Skeptic's reading",
                    artifacts=self._artifacts(search, named),
                )
            with self._engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE skeptic_search SET phase = 'completed', finished_at = now()"
                        " WHERE id = :id AND phase = 'reading'"
                    ),
                    {"id": search["id"]},
                )
            search = self._load(search["id"])
        return SkepticOutcome(
            "succeeded",
            detail=_read_nothing(investigation, task, search),
            artifacts=self._artifacts(search, named),
            disproofs=self._disproofs(search["id"]),
        )

    # --- the search row ---------------------------------------------------------------------

    def _open(self, investigation: RowMapping, task: RowMapping, run_id: uuid.UUID) -> RowMapping:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO skeptic_search (id, investigation_id, task_id, run_id,"
                    " passages_per_call) VALUES (:id, :investigation, :task, :run, :per_call)"
                    " ON CONFLICT (task_id) DO NOTHING"
                ),
                {
                    "id": uuid.uuid4(),
                    "investigation": investigation["id"],
                    "task": task["id"],
                    "run": run_id,
                    "per_call": self._passages_per_call,
                },
            )
            return (
                connection.execute(
                    text("SELECT * FROM skeptic_search WHERE task_id = :task"),
                    {"task": task["id"]},
                )
                .mappings()
                .one()
            )

    def _load(self, search_id: uuid.UUID) -> RowMapping:
        with self._engine.connect() as connection:
            return (
                connection.execute(
                    text("SELECT * FROM skeptic_search WHERE id = :id"), {"id": search_id}
                )
                .mappings()
                .one()
            )

    def _catalog(
        self, investigation: RowMapping, company_ids: Sequence[uuid.UUID]
    ) -> list[_Version]:
        """The archived Tier A documents a search result may match (see the module)."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT * FROM (SELECT DISTINCT ON (v.source_document_id)"  # noqa: S608 (constant SQL)
                    f" {_VERSION_COLUMNS}"
                    " FROM source_version v JOIN source_document d ON d.id = v.source_document_id"
                    " LEFT JOIN company c ON c.id = d.company_id"
                    " WHERE d.company_id = ANY(:companies) AND d.source_tier = :tier"
                    " AND v.available_at <= :as_of AND v.parse_status IN ('parsed', 'incomplete')"
                    " AND v.parsed_object_uri IS NOT NULL"
                    " ORDER BY v.source_document_id, v.available_at DESC, v.id) latest"
                    " ORDER BY available_at DESC, id LIMIT :limit"
                ),
                {
                    "companies": list(company_ids),
                    "tier": _WITNESS_TIER,
                    "as_of": investigation["as_of"],
                    "limit": CATALOG_LIMIT,
                },
            ).mappings()
            return [_version(row) for row in rows]

    def _named(self, investigation: RowMapping, claims: Sequence[RowMapping]) -> list[_Named]:
        """The researched companies the supporting Claims name (their subjects and their
        object companies; never a counterparty), each with its Claims' objects: the seed
        companies among them first, in seed order, then the others in the Claims' order."""
        objects: dict[uuid.UUID, list[str]] = {}
        for claim in claims:
            other: str | None = claim["object_name"] or claim["object_text"]
            product: str | None = claim["product"]
            objects.setdefault(claim["subject_company_id"], []).extend(
                each for each in (other, product) if each
            )
            if claim["object_company_id"] is not None:
                objects.setdefault(claim["object_company_id"], []).extend(
                    each for each in (claim["subject_name"], product) if each
                )
        with self._engine.connect() as connection:
            names = {
                row.id: row.display_name
                for row in connection.execute(
                    text(
                        "SELECT id, display_name FROM company WHERE id = ANY(:ids)"
                        " AND role = 'researched'"
                    ),
                    {"ids": list(objects)},
                )
            }
        seeds = [each for each in investigation["seed_company_ids"] if each in objects]
        ordered = dict.fromkeys([*seeds, *objects])
        return [_Named(each, names[each], objects[each]) for each in ordered if each in names]

    # --- 2. the plan ------------------------------------------------------------------------

    def _plan(
        self,
        investigation: RowMapping,
        task: RowMapping,
        search: RowMapping,
        theme_title: str,
        claims: Sequence[RowMapping],
    ) -> None:
        companies = self._companies()
        seeds = set(investigation["seed_company_ids"])
        request = SkepticPlanRequest(
            research_question=investigation["question"],
            theme_id=investigation["theme"],
            theme_title=theme_title,
            checklist=_checklist(),
            supporting_claims=_supporting(claims),
            companies=[
                SeedCompany(company_id=str(c.id), names=c.names) for c in companies if c.id in seeds
            ],
            max_queries=self._max_queries,
        )
        quarantined = False
        try:
            plan, role_call_id = self._caller.call_recorded(
                SKEPTIC_PLAN, request, run_id=search["run_id"]
            )
            proposed = plan.queries
        except RoleOutputQuarantined as error:
            # The plan only adds searches: without one the Skeptic reads where Memory points.
            proposed, role_call_id, quarantined = [], error.role_call_id, True
        queries: list[tuple[str, str, str | None]] = []
        seen: set[str] = set()
        for each in proposed:
            query = _SPACE.sub(" ", each.query).strip()
            if query and query.casefold() not in seen:
                seen.add(query.casefold())
                queries.append((query, each.checklist_item, each.filing_phrase))
        queries = queries[: self._max_queries]
        with self._engine.begin() as connection:
            _lock(connection, investigation["id"])
            discovery_id: uuid.UUID | None = None
            if queries:
                discovery_id = uuid.uuid4()
                connection.execute(
                    text(
                        "INSERT INTO discovery (id, run_id, theme, question, engines, max_queries,"
                        " queries_proposed, status) VALUES (:id, :run, :theme, :question,"
                        " :engines, :max, :proposed, 'searching')"
                    ),
                    {
                        "id": discovery_id,
                        "run": search["run_id"],
                        "theme": investigation["theme"],
                        "question": investigation["question"],
                        "engines": self._searxng.engines,
                        "max": self._max_queries,
                        "proposed": len(proposed),
                    },
                )
                window = filing_window(investigation["as_of"])
                for position, (query, item, phrase) in enumerate(queries, start=1):
                    add_query(
                        connection,
                        discovery_id,
                        position,
                        query,
                        f"skeptic: {item}",
                        phrase,
                        edgar=self._edgar,
                        window=window,
                    )
            if quarantined:
                event(
                    connection,
                    investigation["id"],
                    PLAN_QUARANTINED_EVENT,
                    round=task["round"],
                    task_key=task["key"],
                    role_call_id=str(role_call_id),
                )
            connection.execute(
                text(
                    "UPDATE skeptic_search SET phase = 'searching', plan_role_call_id = :call,"
                    " discovery_id = :discovery, queries_proposed = :queries"
                    " WHERE id = :id AND phase = 'planning'"
                ),
                {
                    "id": search["id"],
                    "call": role_call_id,
                    "discovery": discovery_id,
                    "queries": len(proposed),
                },
            )

    # --- 3. the search, 4. the documents, 5. the passages ---------------------------------------

    def _search(
        self,
        investigation: RowMapping,
        task: RowMapping,
        search: RowMapping,
        catalog: Sequence[_Version],
        named: Sequence[_Named],
        queries: Sequence[PointerQuery],
    ) -> None:
        discovery_id: uuid.UUID | None = search["discovery_id"]
        found_urls: list[str] = []
        if discovery_id is not None:
            run_searches(self._engine, discovery_id, self._searxng, self._edgar)
            with self._engine.connect() as connection:
                found_urls = list(
                    connection.execute(
                        text(
                            "SELECT l.canonical_url FROM lead_sighting s"
                            " JOIN discovery_query q ON q.id = s.discovery_query_id"
                            " JOIN lead l ON l.id = s.lead_id WHERE q.discovery_id = :discovery"
                            " ORDER BY q.position, s.position"
                        ),
                        {"discovery": discovery_id},
                    ).scalars()
                )
        by_url = {canonical_url(v.canonical_url): v for v in catalog}
        matched: list[tuple[uuid.UUID, str | None, Selection]] = []
        for url in found_urls:
            version = by_url.get(url)
            if version is not None and version.id not in {m[0] for m in matched}:
                matched.append((version.id, None, "search"))
        # Where Memory pointed, best pointer first: each Source Version once, for the checklist
        # item of its best pointer.
        with self._engine.connect() as connection:
            pointers = skeptic_pointers(connection, task["id"])
            read_before = _read_before(connection, investigation["id"], task["id"])
        best: dict[uuid.UUID, SkepticPointer] = {}
        for pointer in pointers:
            best.setdefault(pointer.source_version_id, pointer)
        witnesses = {
            version.id: version
            for version in self._versions(list(best)).values()
            if version.source_tier == _WITNESS_TIER
        }
        pointed: list[tuple[uuid.UUID, str | None, Selection]] = [
            (version_id, pointer.checklist_item, "pointer")
            for version_id, pointer in best.items()
            if version_id in witnesses and version_id not in read_before
        ]
        with self._engine.begin() as connection:
            _lock(connection, investigation["id"])
            current = [SkepticDocument.model_validate(d) for d in search["documents"]]
            documents, dropped = _take_documents(
                connection, investigation, task, current, [*pointed, *matched]
            )
            # The fallback: a company the Claims name that no pointer document was chosen of.
            fallback, uncovered = _fallback(
                connection,
                investigation,
                companies=[company.id for company in named],
                covered={
                    company
                    for d in documents
                    if d.selected_by == "pointer"
                    and (company := witnesses[d.source_version_id].company_id) is not None
                },
                chosen={d.source_version_id for d in documents},
                read_before=read_before,
            )
            if uncovered:
                documents, more = _take_documents(
                    connection, investigation, task, documents, fallback
                )
                dropped += more
                event(
                    connection,
                    investigation["id"],
                    FALLBACK_EVENT,
                    round=task["round"],
                    task_key=task["key"],
                    company_ids=[str(each) for each in uncovered],
                    documents=sum(1 for d in documents if d.selected_by == "fallback"),
                )
            _budget_event(connection, investigation, task, dropped)
            if discovery_id is not None:
                connection.execute(
                    text(
                        "UPDATE discovery SET status = 'completed', finished_at = now()"
                        " WHERE id = :id AND status <> 'completed'"
                    ),
                    {"id": discovery_id},
                )
        passages, passages_dropped = self._passages(documents, pointers, queries)
        size = search["passages_per_call"]
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE skeptic_search SET phase = 'reading', documents = CAST(:docs AS jsonb),"
                    " documents_dropped = documents_dropped + :dropped,"
                    " passages = CAST(:passages AS jsonb), passages_dropped = :passages_dropped,"
                    " batches_total = :batches WHERE id = :id AND phase = 'searching'"
                ),
                {
                    "id": search["id"],
                    "docs": _dump(documents),
                    "dropped": dropped,
                    "passages": _dump(passages),
                    "passages_dropped": passages_dropped,
                    "batches": -(-len(passages) // size),
                },
            )

    def _passages(
        self,
        documents: Sequence[SkepticDocument],
        pointers: Sequence[SkepticPointer],
        queries: Sequence[PointerQuery],
    ) -> tuple[list[SkepticPassage], int]:
        """The passages of the chosen documents, in reading order (atlas.claims.selection):
        the windows the pointers lead to and the windows the term search ranks highest for
        the bear-checklist queries, alternately, within the passage budget, with the floor
        and the ceiling per document; and how many pointer and search candidates were not
        taken. The Memory text of a pointer only finds its window."""
        versions = self._versions([d.source_version_id for d in documents])
        readable = [
            versions[d.source_version_id] for d in documents if d.source_version_id in versions
        ]
        texts = {version.id: self._text(version) for version in readable}
        chosen = select(
            [
                Document(
                    id=version.id,
                    text=texts[version.id],
                    form_type=version.form_type,
                    document_type=version.document_type,
                    items=version.items,
                    company_id=version.company_id,
                    provider=version.provider,
                )
                for version in readable
            ],
            reading=Reading(
                pointers=[
                    Pointer(
                        source_version_id=pointer.source_version_id,
                        section_anchor=pointer.section_anchor,
                        rank=pointer.rank,
                        query_index=pointer.query_index,
                        memory_text=pointer.memory_text,
                        label=pointer.checklist_item,
                        # Placed by its fact's chunk, when it was (memory-quality ticket 08).
                        section_char_start=pointer.section_char_start,
                        section_char_end=pointer.section_char_end,
                        chunk_char_start=pointer.chunk_char_start,
                    )
                    for pointer in pointers
                ],
                queries=[query.text for query in queries],
            ),
            budget=self._max_passages,
            ceiling=ceiling(self._max_passages, self._max_document_share),
        )
        passages = [
            SkepticPassage(
                id=f"s{index}",
                source_version_id=each.source_version_id,
                section_anchor=each.section_anchor,
                char_start=each.char_start,
                char_end=each.char_end,
                checklist_items=checklist_matches(
                    texts[each.source_version_id][each.char_start : each.char_end]
                ),
                selected_by=each.selected_by,
            )
            for index, each in enumerate(chosen.passages, start=1)
        ]
        return passages, chosen.dropped

    # --- 6. reading, 7. checks, 8. the kind, 9. outcomes ---------------------------------------

    def _read(
        self,
        investigation: RowMapping,
        search: RowMapping,
        claims: Sequence[RowMapping],
        supporting_families: set[str],
    ) -> bool:
        """Send the remaining batches; True when the token budget stopped it."""
        passages = [SkepticPassage.model_validate(p) for p in search["passages"]]
        size = search["passages_per_call"]
        batches = [passages[start : start + size] for start in range(0, len(passages), size)]
        versions = self._versions(list(dict.fromkeys(p.source_version_id for p in passages)))
        companies = self._companies()
        premises = self._premises(investigation["id"])
        for index in range(search["batches_done"], len(batches)):
            batch = batches[index]
            request = SkepticRequest(
                research_question=investigation["question"],
                checklist=_checklist(),
                companies=[KnownCompany(company_id=str(c.id), names=c.names) for c in companies],
                supporting_claims=_supporting(claims),
                premises=[PremiseOption(key=key, statement=s) for key, s in premises.items()],
                passages=[
                    PassageInfo(
                        passage_id=p.id,
                        source_version_id=str(p.source_version_id),
                        filer_company_id=_str(versions[p.source_version_id].company_id),
                        title=versions[p.source_version_id].title,
                        section=p.section_anchor,
                        checklist_items=p.checklist_items,
                    )
                    for p in batch
                ],
            )
            retrieved = [
                QuotedText(
                    id=p.id,
                    source=f"{p.source_version_id}#{p.char_start}-{p.char_end}",
                    text=self._text(versions[p.source_version_id])[p.char_start : p.char_end],
                )
                for p in batch
            ]
            try:
                output, role_call_id = self._caller.call_recorded(
                    SKEPTIC, request, run_id=search["run_id"], retrieved=retrieved
                )
            except TokenBudgetExhausted:
                return True
            except RoleOutputQuarantined:
                self._record(
                    search,
                    index,
                    [],
                    None,
                    batch,
                    versions,
                    companies,
                    claims,
                    premises,
                    supporting_families,
                    quarantined=True,
                )
                continue
            self._record(
                search,
                index,
                output.counterevidence,
                role_call_id,
                batch,
                versions,
                companies,
                claims,
                premises,
                supporting_families,
            )
        return False

    def _record(
        self,
        search: RowMapping,
        index: int,
        proposed: Sequence[ProposedCounterevidence],
        role_call_id: uuid.UUID | None,
        batch: Sequence[SkepticPassage],
        versions: dict[uuid.UUID, _Version],
        companies: Sequence[_Company],
        claims: Sequence[RowMapping],
        premises: dict[str, str],
        supporting_families: set[str],
        *,
        quarantined: bool = False,
    ) -> None:
        """Record one batch's items and advance the search, in one transaction."""
        with self._engine.begin() as connection:
            done = connection.execute(
                text("SELECT batches_done FROM skeptic_search WHERE id = :id FOR UPDATE"),
                {"id": search["id"]},
            ).scalar_one()
            if done != index:
                return  # recorded by an earlier attempt
            passages = {p.id: p for p in batch}
            by_id = {str(c["id"]): c for c in claims}
            for ordinal, item in enumerate(proposed):
                assert role_call_id is not None
                judged = self._judge(item, passages, versions, companies, by_id, premises)
                self._insert(
                    connection,
                    search,
                    index,
                    ordinal,
                    item,
                    role_call_id,
                    judged,
                    supporting_families,
                )
            connection.execute(
                text(
                    "UPDATE skeptic_search SET batches_done = batches_done + 1,"
                    " batches_quarantined = batches_quarantined + :quarantined WHERE id = :id"
                ),
                {"id": search["id"], "quarantined": int(quarantined)},
            )

    def _judge(
        self,
        item: ProposedCounterevidence,
        passages: dict[str, SkepticPassage],
        versions: dict[uuid.UUID, _Version],
        companies: Sequence[_Company],
        claims: dict[str, RowMapping],
        premises: dict[str, str],
    ) -> _Judged:
        passage = passages.get(item.passage_id)
        subject = next((c for c in companies if str(c.id) == item.subject_company_id), None)
        listed = [claims[c] for c in dict.fromkeys(item.contradicts_claim_ids) if c in claims]
        judged = _Judged(
            source_version_id=passage.source_version_id if passage else None,
            subject_company_id=subject.id if subject else None,
            span=None,
            contradicts=[c["id"] for c in listed],
            kind=item.kind,
            how=item.how if item.kind == "contradiction" else None,
            disproves_premise=item.disproves_premise,
        )
        if item.checklist_item not in CHECKLIST_NAMES:
            return _reject(
                judged,
                "unknown_checklist_item",
                f"{item.checklist_item!r} is not a checklist item; the items are"
                f" {', '.join(CHECKLIST_NAMES)}",
            )
        if passage is None:
            return _reject(
                judged,
                "not_a_witness",
                f"{item.passage_id!r} is not a passage of an archived Source Version sent in this"
                " call: only those are witnesses (Memory, leads and other roles' output never"
                " are)",
            )
        if subject is None:
            message = f"subject {item.subject_company_id!r} is not a known company ID"
            return _reject(judged, "unknown_company", message)
        unknown = [c for c in item.contradicts_claim_ids if c not in claims]
        if unknown:
            return _reject(
                judged,
                "unknown_claim",
                "contradicts what isn't a supporting Claim of this investigation: "
                + ", ".join(unknown),
            )
        if item.disproves_premise is not None and item.disproves_premise not in premises:
            return _reject(
                judged,
                "unknown_premise",
                f"{item.disproves_premise!r} is not an open company premise of this investigation",
            )
        version = versions[passage.source_version_id]
        parsed = self._text(version)
        length = passage.char_end - passage.char_start
        if not 0 <= item.quote_start <= item.quote_end <= length:
            return _reject(
                judged,
                "quote_outside_passage",
                f"the offsets [{item.quote_start}, {item.quote_end}) are not inside passage"
                f" {passage.id} ({length} characters)",
            )
        placed = _place(parsed[passage.char_start : passage.char_end], item)
        if isinstance(placed, _Unplaced):
            return _reject(judged, placed.code, placed.reason)
        span = (passage.char_start + placed[0], passage.char_start + placed[1])
        judged = replace(judged, span=span)
        try:
            assertion = AssertionCreate(
                subject_company_id=subject.id,
                predicate=COUNTEREVIDENCE_PREDICATE,
                object_company_id=None,
                value_json=None,  # written below, once the kind is settled
                source_version_id=version.id,
                quote=item.quote,
                span_start=span[0],
                span_end=span[1],
                page_or_anchor=passage.section_anchor,
                epistemic_type=item.epistemic_type,
            )
            check_quote(parsed, assertion)
        except ValidationError as error:
            first = error.errors(include_url=False, include_input=False)[0]
            where = ".".join(str(part) for part in first["loc"])
            return _reject(judged, "invalid_counterevidence", f"{where}: {first['msg']}")
        except InvalidAssertion as refusal:
            return _reject(judged, refusal.code, refusal.message)
        if version.source_type == TRANSCRIPT_SOURCE_TYPE:
            # The rule of the Investigator's Claims: only the company's own people speak for it.
            filer = next((c for c in companies if c.id == version.company_id), None)
            said = transcript_speaker(parsed, span, filer.names if filer is not None else [])
            if isinstance(said, SpeakerRefusal):
                return _reject(judged, said.code, said.message)
        if subject.id != version.company_id and not mentions(item.quote, subject.names):
            return _reject(
                judged,
                "party_not_in_quote",
                f"the quote doesn't name {subject.names[0]}, and the document isn't its own",
            )
        table_row = is_table_row(item.quote)
        figure_name, figure_period = _stated(item.figure_name), _stated(item.figure_period)
        if table_row and (figure_name is None or figure_period is None):
            return _reject(
                judged,
                "table_row_without_figure",
                "the quote is a table row with no words: it is accepted only as bear context,"
                " and only when the item states the figure's name (`figure_name`) and its"
                " period (`figure_period`)",
            )
        names = {c.id: c.names for c in companies}
        kind, against, kind_reason = _settle(item, listed, names, table_row=table_row)
        contradiction = kind == "contradiction"
        how = item.how if contradiction else None
        premise = item.disproves_premise if contradiction else None
        if not contradiction and item.disproves_premise is not None:
            left_out = "bear context disproves no premise: `disproves_premise` is left out"
            kind_reason = f"{kind_reason}; {left_out}" if kind_reason else left_out
        value: dict[str, JsonValue] = {
            "kind": kind,
            "checklist_item": item.checklist_item,
            "statement": item.statement,
            "contradicts_claim_ids": [str(c) for c in against],
            "how": how,
            "disproves_premise": premise,
        }
        if figure_name is not None or figure_period is not None:
            value |= {"figure_name": figure_name, "figure_period": figure_period}
        return replace(
            judged,
            contradicts=against,
            kind=kind,
            how=how,
            disproves_premise=premise,
            kind_reason=kind_reason,
            assertion=assertion.model_copy(update={"value_json": value}),
        )

    def _insert(
        self,
        connection: Connection,
        search: RowMapping,
        batch: int,
        ordinal: int,
        item: ProposedCounterevidence,
        role_call_id: uuid.UUID,
        judged: _Judged,
        supporting_families: set[str],
    ) -> None:
        counterevidence_id = uuid.uuid4()
        assertion_id: uuid.UUID | None = None
        family: str | None = None
        independent: bool | None = None
        detail: str | None = None
        if judged.assertion is not None:
            request = judged.assertion.model_copy(
                update={
                    "value_json": {
                        "counterevidence_id": str(counterevidence_id),
                        "investigation_id": str(search["investigation_id"]),
                        **_object(judged.assertion.value_json),
                    }
                }
            )
            try:
                recorded = self._assertions.create_within(
                    connection, request, extractor_version=EXTRACTOR_VERSION
                )
                assertion_id = recorded.assertion.id
            except InvalidAssertion as refusal:
                judged = _reject(judged, refusal.code, refusal.message)
        if assertion_id is not None:
            assert judged.source_version_id is not None
            family = _family_of(connection, judged.source_version_id)
        if family is not None and judged.kind == "contradiction":
            # Independence is a property of contradictions; bear context has none.
            independent = family not in supporting_families
            detail = (
                f"its Evidence Family ({family}) is none of the supporting Claims'"
                if independent
                else f"it shares Evidence Family {family} with the supporting Claims' Evidence:"
                " not an independent witness"
            )
        row = (
            connection.execute(
                text(
                    "INSERT INTO counterevidence (id, search_id, investigation_id, run_id,"
                    " role_call_id, batch, ordinal, proposed, checklist_item, passage_id,"
                    " source_version_id, subject_company_id, statement, quote, span_start,"
                    " span_end, epistemic_type, contradicts_claim_ids, disproves_premise,"
                    " outcome, reason_code, reason, assertion_id, evidence_family, independent,"
                    " independence_detail, kind, how, kind_reason, figure_name, figure_period)"
                    " VALUES (:id, :search, :investigation, :run,"
                    " :role_call, :batch, :ordinal, CAST(:proposed AS jsonb), :item, :passage,"
                    " :version, :subject, :statement, :quote, :span_start, :span_end,"
                    " :epistemic_type, :contradicts, :premise, :outcome, :reason_code, :reason,"
                    " :assertion, :family, :independent, :detail, :kind, :how, :kind_reason,"
                    " :figure_name, :figure_period) RETURNING *"
                ),
                {
                    "id": counterevidence_id,
                    "search": search["id"],
                    "investigation": search["investigation_id"],
                    "run": search["run_id"],
                    "role_call": role_call_id,
                    "batch": batch,
                    "ordinal": ordinal,
                    "proposed": json.dumps(item.model_dump(mode="json")),
                    "item": item.checklist_item,
                    "passage": item.passage_id,
                    "version": judged.source_version_id,
                    "subject": judged.subject_company_id,
                    "statement": item.statement,
                    "quote": item.quote,
                    "span_start": judged.span[0] if judged.span else None,
                    "span_end": judged.span[1] if judged.span else None,
                    "epistemic_type": item.epistemic_type,
                    "contradicts": judged.contradicts,
                    "premise": judged.disproves_premise,
                    "outcome": "accepted" if assertion_id else "rejected",
                    "reason_code": judged.reason_code,
                    "reason": judged.reason,
                    "assertion": assertion_id,
                    "family": family,
                    "independent": independent,
                    "detail": detail,
                    "kind": judged.kind,
                    "how": judged.how,
                    "kind_reason": judged.kind_reason if assertion_id else None,
                    "figure_name": _stated(item.figure_name),
                    "figure_period": _stated(item.figure_period),
                },
            )
            .mappings()
            .one()
        )
        record(
            connection,
            SKEPTIC_ACTOR,
            "counterevidence.accepted" if assertion_id else "counterevidence.rejected",
            entity_type="counterevidence",
            entity_id=str(counterevidence_id),
            new_hash=content_hash(dict(row)),
        )
        if independent:
            # An independent contradiction of a statement a published Hypothesis version
            # cites (ticket 21).
            on_counterevidence(connection, counterevidence_id)

    # --- 10. premises, artifacts ----------------------------------------------------------------

    def _disproofs(self, search_id: uuid.UUID) -> list[Disproof]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT id, disproves_premise, statement FROM counterevidence"
                    " WHERE search_id = :id AND outcome = 'accepted' AND kind = 'contradiction'"
                    " AND independent AND disproves_premise IS NOT NULL ORDER BY batch, ordinal"
                ),
                {"id": search_id},
            ).all()
        by_premise: dict[str, list[tuple[uuid.UUID, str]]] = {}
        for row in rows:
            by_premise.setdefault(row.disproves_premise, []).append((row.id, row.statement))
        return [
            Disproof(
                premise_key=key,
                reason="the Skeptic's independent counterevidence: "
                + items[0][1]
                + (f" (and {len(items) - 1} more)" if len(items) > 1 else ""),
                counterevidence_ids=[each[0] for each in items],
            )
            for key, items in by_premise.items()
        ]

    def _artifacts(self, search: RowMapping, named: Sequence[_Named]) -> dict[str, JsonValue]:
        with self._engine.connect() as connection:
            counts = connection.execute(
                text(
                    "SELECT count(*) FILTER (WHERE outcome = 'accepted') AS accepted,"
                    " count(*) FILTER (WHERE outcome = 'rejected') AS rejected,"
                    " count(*) FILTER (WHERE outcome = 'accepted' AND kind = 'contradiction')"
                    " AS contradictions,"
                    " count(*) FILTER (WHERE outcome = 'accepted' AND kind = 'bear_context')"
                    " AS bear_context,"
                    " count(*) FILTER (WHERE outcome = 'accepted' AND kind = 'bear_context'"
                    "  AND proposed ->> 'kind' = 'contradiction') AS demoted,"
                    " count(*) FILTER (WHERE kind = 'contradiction' AND independent)"
                    " AS independent,"
                    " count(DISTINCT evidence_family)"
                    "  FILTER (WHERE kind = 'contradiction' AND independent)"
                    " AS independent_families"
                    " FROM counterevidence WHERE search_id = :id"
                ),
                {"id": search["id"]},
            ).one()
            queries = connection.execute(
                text(
                    "SELECT count(*) FILTER (WHERE status = 'searched'),"
                    " count(*) FILTER (WHERE status = 'failed'), coalesce(sum(new_leads), 0)"
                    " FROM discovery_query WHERE discovery_id = :id"
                ),
                {"id": search["discovery_id"]},
            ).one()
            fell_back = used_fallback(connection, search["task_id"])
        documents = [SkepticDocument.model_validate(d) for d in search["documents"]]
        by_selection: dict[str, int] = {}
        for passage in search["passages"]:
            for kind in selections(passage.get("selected_by") or []):
                by_selection[kind] = by_selection.get(kind, 0) + 1
        return {
            "skeptic_search_id": str(search["id"]),
            # The companies Memory was asked about, and those the cap left out.
            "recall_companies": min(len(named), MAX_RECALL_COMPANIES),
            "recall_companies_dropped": max(len(named) - MAX_RECALL_COMPANIES, 0),
            "plan_role_call_id": _str(search["plan_role_call_id"]),
            "discovery_id": _str(search["discovery_id"]),
            "queries_searched": int(queries[0]),
            "queries_failed": int(queries[1]),
            "new_leads": int(queries[2]),
            "documents": len(documents),
            "documents_from_pointers": sum(1 for d in documents if d.selected_by == "pointer"),
            "documents_from_search": sum(1 for d in documents if d.selected_by == "search"),
            "documents_fallback": fell_back,
            "documents_from_fallback": sum(1 for d in documents if d.selected_by == "fallback"),
            "documents_dropped": search["documents_dropped"],
            "passages": len(search["passages"]),
            "passages_by_selection": dict[str, JsonValue](by_selection),
            "passages_dropped": search["passages_dropped"],
            "batches_done": search["batches_done"],
            "batches_total": search["batches_total"],
            "counterevidence_accepted": int(counts.accepted),
            "counterevidence_rejected": int(counts.rejected),
            "contradictions_accepted": int(counts.contradictions),
            "bear_context_accepted": int(counts.bear_context),
            # Proposed as contradictions, stored as bear context (step 8).
            "contradictions_demoted": int(counts.demoted),
            "counterevidence_independent": int(counts.independent),
            "independent_evidence_families": int(counts.independent_families),
        }

    # --- reads --------------------------------------------------------------------------------

    def _versions(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, _Version]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT {_VERSION_COLUMNS}"  # noqa: S608 (constant SQL)
                    " FROM source_version v JOIN source_document d ON d.id = v.source_document_id"
                    " LEFT JOIN company c ON c.id = d.company_id WHERE v.id = ANY(:ids)"
                    " AND v.parse_status IN ('parsed', 'incomplete')"
                    " AND v.parsed_object_uri IS NOT NULL"
                ),
                {"ids": list(ids)},
            ).mappings()
            return {row["id"]: _version(row) for row in rows}

    def _companies(self) -> list[_Company]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text("SELECT id, display_name, legal_name FROM company ORDER BY slug")
            ).all()
        return [_Company(row.id, company_names(row.display_name, row.legal_name)) for row in rows]

    def _premises(self, investigation_id: uuid.UUID) -> dict[str, str]:
        """The open company premises: the ones counterevidence may disprove."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT key, statement FROM investigation_premise"
                    " WHERE investigation_id = :id AND status = 'open'"
                    " AND company_id IS NOT NULL ORDER BY key"
                ),
                {"id": investigation_id},
            ).all()
        return {row.key: row.statement for row in rows}

    def _text(self, version: _Version) -> str:
        if version.id not in self._texts:
            self._texts[version.id] = self._archive.get(version.parsed_object_uri).decode("utf-8")
        return self._texts[version.id]


# --- the read side: counterevidence on the research card and Hypotheses ---------------------


_ACCEPTED = (
    "SELECT c.id, c.checklist_item, c.statement, c.subject_company_id, co.display_name,"
    " c.contradicts_claim_ids, c.disproves_premise, c.source_version_id, c.quote,"
    " c.span_start, c.span_end, c.assertion_id, c.evidence_family, c.independent,"
    " c.independence_detail, c.how, c.kind_reason, c.figure_name, c.figure_period,"
    " a.verification_status, v.available_at"
    " FROM counterevidence c JOIN skeptic_search s ON s.id = c.search_id"
    " JOIN investigation_task t ON t.id = s.task_id"
    " JOIN assertion a ON a.id = c.assertion_id"
    " JOIN source_version v ON v.id = c.source_version_id"
    " JOIN company co ON co.id = c.subject_company_id"
    " WHERE c.investigation_id = :id AND c.outcome = 'accepted' AND c.kind = :kind"
    " ORDER BY t.round, c.batch, c.ordinal"
)


def _span(row: RowMapping) -> SourceSpan:
    """An accepted item's Assertion span (`claim_id` is the item's ID)."""
    return SourceSpan(
        claim_id=row["id"],
        assertion_id=row["assertion_id"],
        source_version_id=row["source_version_id"],
        span_start=row["span_start"],
        span_end=row["span_end"],
        quote=row["quote"],
        verification_status=row["verification_status"],
    )


def contradictions(connection: Connection, investigation_id: uuid.UUID) -> list[CardContradiction]:
    """The investigation's accepted contradictions, independent or not, in the order found."""
    rows = connection.execute(
        text(_ACCEPTED), {"id": investigation_id, "kind": "contradiction"}
    ).mappings()
    return [
        CardContradiction(
            counterevidence_id=row["id"],
            checklist_item=row["checklist_item"],
            statement=row["statement"],
            subject_company_id=row["subject_company_id"],
            contradicts_claim_ids=row["contradicts_claim_ids"],
            how=row["how"],
            disproves_premise=row["disproves_premise"],
            source_span=_span(row),
            evidence_family=row["evidence_family"],
            independent=row["independent"],
            independence_detail=row["independence_detail"],
            evidence_available_at=row["available_at"],
        )
        for row in rows
    ]


def bear_context(connection: Connection, investigation_id: uuid.UUID) -> list[CardBearContext]:
    """The investigation's accepted bear context, grouped by checklist item (in checklist
    order) and company (in the order found); each group's items in the order found."""
    rows = connection.execute(
        text(_ACCEPTED), {"id": investigation_id, "kind": "bear_context"}
    ).mappings()
    items: dict[tuple[str, uuid.UUID], list[CardBearContextItem]] = {}
    companies: dict[uuid.UUID, str] = {}
    for row in rows:
        companies[row["subject_company_id"]] = row["display_name"]
        items.setdefault((row["checklist_item"], row["subject_company_id"]), []).append(
            CardBearContextItem(
                counterevidence_id=row["id"],
                statement=row["statement"],
                source_span=_span(row),
                evidence_available_at=row["available_at"],
                figure_name=row["figure_name"],
                figure_period=row["figure_period"],
                reason=row["kind_reason"],
            )
        )
    order = {name: index for index, name in enumerate(CHECKLIST_NAMES)}
    return [
        CardBearContext(
            checklist_item=item, company_id=company, company_name=companies[company], items=found
        )
        for (item, company), found in sorted(
            items.items(), key=lambda group: order.get(group[0][0], len(order))
        )
    ]


def counterevidence_by_claim(
    found: Sequence[CardContradiction],
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Claim ID -> the independent contradictions of it (what a finding lists)."""
    by_claim: dict[uuid.UUID, list[uuid.UUID]] = {}
    for each in found:
        if each.independent:
            for claim_id in each.contradicts_claim_ids:
                by_claim.setdefault(claim_id, []).append(each.counterevidence_id)
    return by_claim


# --- helpers ------------------------------------------------------------------------------------


def _queries(named: Sequence[_Named]) -> list[PointerQuery]:
    """What the Skeptic asks Memory: for each of the first `MAX_RECALL_COMPANIES` named
    companies, one query per bear-checklist item (`bear_query`), numbered from 1."""
    asked = [(company, item) for company in named[:MAX_RECALL_COMPANIES] for item in BEAR_CHECKLIST]
    return [
        PointerQuery(
            index,
            bear_query(item, company.name, company.objects),
            kind=BEAR_CHECKLIST_QUERY,
            checklist_item=item.name,
            company_id=company.id,
        )
        for index, (company, item) in enumerate(asked, start=1)
    ]


def _checklist() -> list[ChecklistOption]:
    return [ChecklistOption(name=item.name, covers=item.covers) for item in BEAR_CHECKLIST]


def _supporting(claims: Sequence[RowMapping]) -> list[SupportingClaim]:
    return [
        SupportingClaim(
            claim_id=str(c["id"]),
            subject=c["subject_name"],
            predicate=c["predicate"],
            object=c["object_name"] or c["object_text"] or "",
            source_version_id=str(c["source_version_id"]),
            source_title=c["source_title"],
        )
        for c in claims
    ]


def _lock(connection: Connection, investigation_id: uuid.UUID) -> None:
    connection.execute(
        text("SELECT 1 FROM investigation WHERE id = :id FOR UPDATE"), {"id": investigation_id}
    )


def _take_documents(
    connection: Connection,
    investigation: RowMapping,
    task: RowMapping,
    current: list[SkepticDocument],
    wanted: Sequence[tuple[uuid.UUID, str | None, Selection]],
) -> tuple[list[SkepticDocument], int]:
    """`current` plus the `wanted` Source Versions not in it: one the investigation already
    read costs nothing; a new one is recorded for the task while the document budget has
    room, else dropped. The caller holds the investigation's lock."""
    held = set(
        connection.execute(
            text(
                "SELECT source_version_id FROM investigation_document WHERE investigation_id = :id"
            ),
            {"id": investigation["id"]},
        ).scalars()
    )
    room = max(investigation["max_documents"] - len(held), 0)
    documents = list(current)
    have = {d.source_version_id for d in documents}
    dropped = 0
    for version_id, item, selected_by in wanted:
        if version_id in have:
            continue
        counted = version_id not in held
        if counted:
            if room <= 0:
                dropped += 1
                continue
            connection.execute(
                text(
                    "INSERT INTO investigation_document (investigation_id, source_version_id,"
                    " task_id) VALUES (:id, :version, :task)"
                ),
                {"id": investigation["id"], "version": version_id, "task": task["id"]},
            )
            held.add(version_id)
            room -= 1
        have.add(version_id)
        documents.append(
            SkepticDocument(
                source_version_id=version_id,
                checklist_item=item,
                selected_by=selected_by,
                counted=counted,
            )
        )
    return documents, dropped


_FALLBACK_FORMS = ("10-K", "10-Q")


def _read_before(
    connection: Connection, investigation_id: uuid.UUID, task_id: uuid.UUID
) -> set[uuid.UUID]:
    """The Source Versions an earlier round's Skeptic of the investigation read: a follow-up
    round's pointer and fallback documents leave them out."""
    return set(
        connection.execute(
            text(
                "SELECT CAST(d ->> 'source_version_id' AS uuid) FROM skeptic_search s,"
                " jsonb_array_elements(s.documents) d"
                " WHERE s.investigation_id = :id AND s.task_id <> :task"
            ),
            {"id": investigation_id, "task": task_id},
        ).scalars()
    )


def _fallback(
    connection: Connection,
    investigation: RowMapping,
    *,
    companies: Sequence[uuid.UUID],
    covered: set[uuid.UUID],
    chosen: set[uuid.UUID],
    read_before: set[uuid.UUID],
) -> tuple[list[tuple[uuid.UUID, str | None, Selection]], list[uuid.UUID]]:
    """The documents code chooses for the `companies` (the ones the Claims name) that Memory
    pointed at nothing of (not in `covered`) and that have one archived (see the module), in
    reading order; and those companies. The caller holds the investigation's lock."""
    wanted = [each for each in dict.fromkeys(companies) if each not in covered]
    if not wanted:
        return [], []
    rows = connection.execute(
        text(
            "SELECT * FROM (SELECT DISTINCT ON (v.source_document_id) v.id, d.company_id,"
            " d.form_type, d.document_type, v.available_at"
            " FROM source_version v JOIN source_document d ON d.id = v.source_document_id"
            " WHERE d.company_id = ANY(:companies) AND d.source_tier = :tier"
            " AND d.source_type <> 'xbrl_companyfacts' AND v.available_at <= :as_of"
            " AND v.parse_status IN ('parsed', 'incomplete') AND v.parsed_object_uri IS NOT NULL"
            " ORDER BY v.source_document_id, v.available_at DESC, v.id) latest"
            " ORDER BY available_at DESC, id"
        ),
        {"companies": wanted, "tier": _WITNESS_TIER, "as_of": investigation["as_of"]},
    ).all()
    held = set(
        connection.execute(
            text(
                "SELECT source_version_id FROM investigation_document WHERE investigation_id = :id"
            ),
            {"id": investigation["id"]},
        ).scalars()
    )
    by_company: dict[uuid.UUID, list[Any]] = {}
    for row in rows:
        if row.id not in read_before:
            by_company.setdefault(row.company_id, []).append(row)
    uncovered = [each for each in wanted if by_company.get(each)]

    def primary(row: Any) -> bool:  # a filing's own document, not an exhibit
        return row.document_type is None or row.document_type == row.form_type

    picks: list[uuid.UUID] = []
    for company in uncovered:
        documents = by_company[company]
        filings = [row for row in documents if primary(row)] or documents
        mine = [
            first.id
            for form in _FALLBACK_FORMS
            if (first := next((row for row in filings if row.form_type == form), None))
        ] or [row.id for row in filings[:2]]
        if not held.intersection(mine):
            # Read already by the investigation, so free: the company is read even when the
            # Investigators spent the document budget.
            read = next((row.id for row in documents if row.id in held), None)
            if read is not None:
                mine.append(read)
        picks += mine
    return [(each, None, "fallback") for each in dict.fromkeys(picks) if each not in chosen], (
        uncovered
    )


def used_fallback(connection: Connection, task_id: uuid.UUID) -> bool:
    """Whether the Skeptic task's documents include ones code chose because Memory pointed
    at nothing of a company the Claims name (before memory-directed reading ticket 07:
    because its plan chose none of a seed company's): the `skeptic_documents_fallback`
    event."""
    return bool(
        connection.execute(
            text(
                "SELECT EXISTS (SELECT FROM investigation_event e JOIN investigation_task t"
                " ON t.investigation_id = e.investigation_id AND t.round = e.round"
                " AND t.key = e.task_key WHERE t.id = :task AND e.type = :type)"
            ),
            {"task": task_id, "type": FALLBACK_EVENT},
        ).scalar_one()
    )


def _read_nothing(investigation: RowMapping, task: RowMapping, search: RowMapping) -> str | None:
    """Why the Skeptic read no passage, when it read none (for its task and the card)."""
    documents = len(search["documents"])
    if documents == 0 and search["documents_dropped"]:
        return (
            f"the Skeptic read nothing: the document budget ({investigation['max_documents']})"
            f" was spent, and {search['documents_dropped']} documents were left out"
        )
    if documents == 0:
        return (
            "the Skeptic read nothing: Memory pointed at no archived document for the"
            " bear checklist, its search matched none, and no company the Claims name has a"
            f" parsed Tier A Source Version available as of {investigation['as_of'].isoformat()}"
            + (" that an earlier round's Skeptic hasn't read" if task["round"] > 1 else "")
        )
    if not search["passages"]:
        return (
            "the Skeptic read no passage: the"
            f" {documents} document{'s' if documents != 1 else ''} it chose"
            f" ha{'ve' if documents != 1 else 's'} no text to read"
        )
    return None


def _budget_event(
    connection: Connection, investigation: RowMapping, task: RowMapping, dropped: int
) -> None:
    if not dropped:
        return
    event(
        connection,
        investigation["id"],
        "document_budget_reached",
        round=task["round"],
        task_key=task["key"],
        max_documents=investigation["max_documents"],
        dropped=dropped,
    )


def _family_of(connection: Connection, version_id: uuid.UUID) -> str:
    family = connection.execute(
        text("SELECT evidence_family_id FROM evidence_family_member WHERE source_version_id = :v"),
        {"v": version_id},
    ).scalar_one_or_none()
    return f"family:{family}" if family is not None else f"version:{version_id}"


@dataclass(frozen=True)
class _Unplaced:
    code: str
    reason: str


def _place(window: str, item: ProposedCounterevidence) -> tuple[int, int] | _Unplaced:
    """The quote's span in the passage: at the model's offsets, else its one exact occurrence
    (no folding of whitespace, quotes or dashes); otherwise why it can't be placed."""
    quote = item.quote
    if not quote:
        return _Unplaced("quote_mismatch", "the quote is empty")
    if window[item.quote_start : item.quote_end] == quote:
        return item.quote_start, item.quote_end
    count = window.count(quote)
    if count == 1:
        first = window.find(quote)
        return first, first + len(quote)
    at = f"the quote is not at the offsets [{item.quote_start}, {item.quote_end})"
    if count == 0:
        return _Unplaced("quote_mismatch", f"{at} and does not occur in the passage")
    return _Unplaced(
        "quote_ambiguous",
        f"{at}, and it has {count} occurrences in the passage, so it cannot be located",
    )


def _reject(judged: _Judged, code: str, reason: str) -> _Judged:
    return replace(judged, assertion=None, reason_code=code, reason=reason[:_ERROR_LIMIT])


# A figure cell of a table row: a number (with its sign, currency, percent or parentheses),
# or a dash standing for none; a lone currency or percent sign between cells is filler.
_NUMBER = re.compile(r"^[(\[]?[-+]?[$€£¥]?(?:\d[\d,.]*\d|\d)%?[)\]]?$")
_DASH = re.compile(r"^[\u2014\u2013-]$")  # an em dash, an en dash or a hyphen
_FILLER = re.compile(r"^[$€£¥%]$")


def is_table_row(quote: str) -> bool:
    """Whether `quote` is a table row with no words: a label (or none) followed only by
    figures, at least two cells of them ("Inventories 2,126,823 1,437,636", "Diluted 96.2 69.3
    87.4 68.8", "Short-term investments 825,000 —"). A sentence that ends in a number isn't
    one, nor is a label with a single figure."""
    cells: list[str] = []
    for token in reversed(quote.split()):
        if _NUMBER.match(token) or _DASH.match(token):
            cells.append(token)
        elif not _FILLER.match(token):
            break
    return len(cells) >= 2 and any(_NUMBER.match(cell) for cell in cells)


def _names_claim(quote: str, claim: RowMapping, names: dict[uuid.UUID, list[str]]) -> bool:
    """Whether `quote` names the Claim's subject company or its object: the object company by
    one of its names, or the Claim's object text (a generic one names nothing). The filer's
    "we" is not a name."""
    if mentions(quote, names.get(claim["subject_company_id"], [claim["subject_name"]])):
        return True
    if claim["object_company_id"] is not None:
        known = names.get(claim["object_company_id"], [claim["object_name"] or ""])
        return mentions(quote, [name for name in known if name])
    object_text: str = (claim["object_text"] or "").strip()
    return (
        bool(object_text)
        and not is_generic_object(object_text)
        and names_object(quote, object_text)
    )


def _settle(
    item: ProposedCounterevidence,
    listed: Sequence[RowMapping],
    names: dict[uuid.UUID, list[str]],
    *,
    table_row: bool,
) -> tuple[CounterevidenceKind, list[uuid.UUID], str | None]:
    """An accepted item's kind (the module's step 8): the kind, the Claims it contradicts,
    and why it is bear context when the Skeptic proposed otherwise."""
    if item.kind == "bear_context":
        reason = (
            "bear context is attached to no Claim: the Claim IDs it listed are left out"
            if listed
            else None
        )
        return "bear_context", [], reason
    proposed = "proposed as a contradiction, but"
    if not listed:
        return "bear_context", [], f"{proposed} it names no Claim"
    if item.how is None:
        return (
            "bear_context",
            [],
            f"{proposed} it doesn't say how it contradicts the Claim (denies, limits or dates it)",
        )
    if table_row:
        return (
            "bear_context",
            [],
            f"{proposed} its quote is a table row, which states nothing that could deny,"
            " limit or date a Claim",
        )
    named = [claim for claim in listed if _names_claim(item.quote, claim, names)]
    if not named:
        claims = "; ".join(_claim_label(claim) for claim in listed)
        return (
            "bear_context",
            [],
            f"{proposed} its quote names neither the subject nor the object of the Claim"
            f" it lists ({claims})"[:_ERROR_LIMIT],
        )
    return "contradiction", [claim["id"] for claim in named], None


def _claim_label(claim: RowMapping) -> str:
    return (
        f"{claim['subject_name']} {claim['predicate']}"
        f" {claim['object_name'] or claim['object_text'] or ''}"
    ).strip()


def _stated(value: str | None) -> str | None:
    """A stated name or period, or None when it is absent or blank."""
    return (value or "").strip() or None


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}  # pyright: ignore[reportUnknownArgumentType]


def _dump(items: Sequence[BaseModel]) -> str:
    return json.dumps([each.model_dump(mode="json") for each in items])


def _str(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)
