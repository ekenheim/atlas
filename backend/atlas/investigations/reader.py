"""The Reader's loop (bottleneck-argument ticket 03): one argument step of one question,
worked by a loop of `reader` role calls (`atlas.roles.reader`), each answering one action,
which code carries out and answers in the next call.

**The session.** One `reader_session` row per Reader: its run, the job or investigation task
it runs in (`key`), the step, the question, the as-of time and its progress (`state`), saved
after every action. A retried, paused or budget-resumed Reader continues where it stopped: the
calls made, the passages it was sent and the Facts it recorded are not made again.

**The actions** (each call's answer; anything refused comes back in the next call's result
with the reason, so the agent can correct it):

- `search_archive {query, company_slugs}`: the archive's term search (`atlas.research.
  archive_search`) over those companies' documents (none named: every company listed),
  available as of the session's time, at most `SEARCH_HITS` hits (two per document). Each hit
  is a passage `h<n>`: its text is sent in the next calls, its document, kind, date and section
  in the result.
- `recall {query}`: Memory across the theme, asked like a reading index (the shared builder,
  `atlas.research.service.reading_index_recall`) at budget high and
  `reader_recall_max_tokens`. Each memory whose provenance resolves to a section available as
  of the session's time is listed (`m<n>`, at most `MEMORIES_SHOWN`): Memory says where to
  read; its text is sent as low-trust data and is never a witness (a Fact quotes only a hit or
  a window).
- `read {ref | source_version_id + anchor, window?}`: one window (`atlas.claims.selection.
  cut_windows`, at most 3,000 characters cut at line breaks) of a section of the current parse
  (`atlas.ledger.current_parse`), as the passage `p<n>`: the window a hit, a memory's chunk or
  a window read is in, another window of that section (`window`, from 1), or a section named
  by its Source Version and anchor. A document available after the as-of time is never read.
- `record_fact {facts: [{passage_id, quote, company_slug, step, statement, quantity?, period?,
  status, challenges}, ...]}`: 1 to 8 Facts (one Fact's arguments alone are a list of one),
  each placed and recorded on its own, and the next result lists, Fact by Fact, what was
  recorded (`r<n>`) and what was refused with the reason. Each Fact's quote is placed as
  Claims are (`place_quote`: its one exact occurrence in the passage, else its one occurrence
  through the typographic fold, else the same in the whole parse); it must name the company
  unless the document is the company's own (`names_party`), and in a call transcript be the
  words of one of the transcript company's own people (`atlas.claims.speakers`); then it is
  recorded as a Fact (`atlas.facts`, with the investigation, the current parse's version,
  `company_claim` from the company's own document and `third_party_report` otherwise), whose
  own checks (the span, a quantity's number in the quote) can refuse it too. A quote recorded
  already for the same company and step is refused.
- `done {summary}`: the step is finished; but a `done` before the session has made a search or
  a recall is refused ("search first: ...") and counted as a call, not a stop.

**Bounds.** At most `max_calls` calls (`reader_max_calls`) and `max_passages` passages sent
(`reader_max_passages`: hits and windows; memories are not passages). A search or read past
the passage budget is refused. The run's token budget bounds every call: when it is spent the
session stops `budget_exhausted` (an investigation resumes it). Two quarantined answers in a
row stop the session (`bounded`, `quarantined`); a single one is reported in the next result.

**What is sent.** Each call's request is bounded: the step, the companies, one line per search,
recall and read so far, the Facts recorded (compact), the last `RESULTS_KEPT` results' items;
the retrieved data is the text of the last `RESULTS_IN_FULL` results' items (and the argument
Skeptic's challenged Facts' quotes).

`read_step` is the standalone job (pausable, `minimax`): one Reader in its own run, for a
theme, a question, a step and optional seed companies (`atlas jobs enqueue read_step`).
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, ValidationError
from sqlalchemy import Connection, Engine, text

from atlas.archive import Archive, open_archive
from atlas.assertions import AssertionRefused
from atlas.audit import Actor
from atlas.claims.predicates import company_names, fold, names_party
from atlas.claims.selection import cut_windows
from atlas.claims.speakers import TRANSCRIPT_SOURCE_TYPE, SpeakerRefusal, transcript_speaker
from atlas.companies import load_universe
from atlas.hindsight import HindsightGateway
from atlas.jobs.queue import Artifacts, Job
from atlas.ledger.reads import current_parse
from atlas.research.service import RecallResponse, Research, ResearchScope, reading_index_recall
from atlas.retention.sections import Section, split_sections
from atlas.roles.caller import (
    RoleCaller,
    RoleOutputQuarantined,
    TokenBudgetExhausted,
)
from atlas.roles.contract import QuotedText, Role
from atlas.roles.reader import (
    READER,
    READER_VERSION,
    STEPS,
    ArgumentStep,
    ChallengedFact,
    ReaderAction,
    ReaderCompany,
    ReaderFactSummary,
    ReaderRequest,
    ReaderResult,
    ReaderStep,
    RecordFact,
    ResultItem,
    StepDefinition,
)
from atlas.roles.records import run_usage
from atlas.runs import RunNotFound, RunRecorder
from atlas.settings import Settings

READER_ACTOR = Actor("atlas-reader")
READ_STEP_KIND = "read_step"
RUN_KIND = "read_step"
SEARCH_HITS = 6
SEARCH_HITS_PER_DOCUMENT = 2
MEMORIES_SHOWN = 8
MEMORY_TEXT_CHARS = 600
RESULTS_KEPT = 4
RESULTS_IN_FULL = 2
QUARANTINE_LIMIT = 2
_ANCHORS_SHOWN = 25

SessionStatus = Literal["running", "done", "bounded", "budget_exhausted"]


# --- the session's state ----------------------------------------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Passage(_Model):
    """A hit or a window the Reader was sent."""

    id: str
    kind: Literal["hit", "window"]
    source_version_id: uuid.UUID
    parser_version: str
    start: int
    end: int
    title: str
    company_slug: str | None
    document_kind: str | None
    date: str
    anchor: str | None
    note: str | None
    text: str


class Memory(_Model):
    id: str
    source_version_id: uuid.UUID
    anchor: str
    heading: str | None
    position: int | None  # where its chunk starts, when placed
    title: str
    company_slug: str | None
    document_kind: str | None
    date: str
    text: str


class RecordedFact(_Model):
    ref: str  # `r<n>`
    fact_id: uuid.UUID
    call: int
    passage_id: str
    source_version_id: uuid.UUID
    span_start: int
    span_end: int
    company_slug: str
    step: str
    status: str
    statement: str
    quantity: dict[str, JsonValue] | None
    period: str | None
    quote: str
    challenges: list[str] = Field(default_factory=list[str])
    # The argument Skeptic's: the IDs of the Facts its `challenges` name.
    challenged_fact_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])


class Refusal(_Model):
    call: int
    reason_code: str
    reason: str
    passage_id: str | None
    quote: str | None


class ReaderState(_Model):
    calls: int = 0
    quarantined_in_a_row: int = 0
    quarantined: int = 0
    passages_sent: int = 0
    next_id: dict[str, int] = Field(default_factory=dict[str, int])
    passages: dict[str, Passage] = Field(default_factory=dict[str, Passage])
    memories: dict[str, Memory] = Field(default_factory=dict[str, Memory])
    searches: list[dict[str, JsonValue]] = Field(default_factory=list[dict[str, JsonValue]])
    recalls: list[dict[str, JsonValue]] = Field(default_factory=list[dict[str, JsonValue]])
    reads: list[dict[str, JsonValue]] = Field(default_factory=list[dict[str, JsonValue]])
    facts: list[RecordedFact] = Field(default_factory=list[RecordedFact])
    refused: list[Refusal] = Field(default_factory=list[Refusal])
    results: list[ReaderResult] = Field(default_factory=list[ReaderResult])
    # The item ids of the last `RESULTS_IN_FULL` results that returned any: their text is sent.
    shown: list[list[str]] = Field(default_factory=list[list[str]])
    role_call_ids: list[str] = Field(default_factory=list[str])
    summary: str | None = None
    stop_reason: str | None = None

    def new_id(self, prefix: str) -> str:
        self.next_id[prefix] = self.next_id.get(prefix, 0) + 1
        return f"{prefix}{self.next_id[prefix]}"


@dataclass(frozen=True)
class Session:
    id: uuid.UUID
    run_id: uuid.UUID
    status: SessionStatus
    as_of: datetime
    state: ReaderState


def open_session(
    connection: Connection,
    *,
    key: str,
    run_id: Callable[[], uuid.UUID],
    role: Literal["reader", "skeptic"],
    step: ArgumentStep,
    question: str,
    as_of: datetime,
    job_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    investigation_id: uuid.UUID | None = None,
) -> Session:
    """The session with `key`, created (in `run_id()`'s run) if there is none yet."""
    row = (
        connection.execute(
            text("SELECT * FROM reader_session WHERE key = :key FOR UPDATE"), {"key": key}
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        row = (
            connection.execute(
                text(
                    "INSERT INTO reader_session (id, key, run_id, job_id, task_id,"
                    " investigation_id, role, step, question, as_of) VALUES (:id, :key, :run,"
                    " :job, :task, :investigation, :role, :step, :question, :as_of) RETURNING *"
                ),
                {
                    "id": uuid.uuid4(),
                    "key": key,
                    "run": run_id(),
                    "job": job_id,
                    "task": task_id,
                    "investigation": investigation_id,
                    "role": role,
                    "step": step,
                    "question": question,
                    "as_of": as_of,
                },
            )
            .mappings()
            .one()
        )
    return Session(
        id=row["id"],
        run_id=row["run_id"],
        status=row["status"],
        as_of=row["as_of"],
        state=ReaderState.model_validate(row["state"]),
    )


def _save(engine: Engine, session_id: uuid.UUID, state: ReaderState, status: SessionStatus) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE reader_session SET state = CAST(:state AS jsonb), status = :status,"
                " stop_reason = :reason, updated_at = now() WHERE id = :id"
            ),
            {
                "id": session_id,
                "state": state.model_dump_json(),
                "status": status,
                "reason": state.stop_reason,
            },
        )


# --- what the Reader is given -----------------------------------------------------------------


@dataclass(frozen=True)
class ReaderCompanyRow:
    id: uuid.UUID
    slug: str
    display_name: str
    legal_name: str
    layer: str | None
    seed: bool


def reader_companies(
    connection: Connection, seeds: Sequence[uuid.UUID], theme_slugs: Sequence[str]
) -> list[ReaderCompanyRow]:
    """The companies a Reader is given: the seeds in their order, then the theme's researched
    companies in its order, then the universe's other researched companies by slug."""
    rows = connection.execute(
        text(
            "SELECT id, slug, display_name, legal_name, layer FROM company"
            " WHERE role = 'researched' ORDER BY slug"
        )
    ).all()
    by_id = {row.id: row for row in rows}
    by_slug = {row.slug: row for row in rows}
    ordered = [by_id[each] for each in dict.fromkeys(seeds) if each in by_id]
    ordered += [by_slug[slug] for slug in theme_slugs if slug in by_slug]
    ordered += list(rows)
    seen: set[uuid.UUID] = set()
    companies: list[ReaderCompanyRow] = []
    for row in ordered:
        if row.id in seen:
            continue
        seen.add(row.id)
        companies.append(
            ReaderCompanyRow(
                row.id, row.slug, row.display_name, row.legal_name, row.layer, row.id in seeds
            )
        )
    return companies


@dataclass(frozen=True)
class ReaderSetup:
    """What one Reader works on."""

    question: str
    step: StepDefinition
    companies: list[ReaderCompanyRow]
    investigation_id: uuid.UUID | None = None
    # The argument Skeptic's: the Facts it challenges, and their quotes (by reference).
    challenge: list[ChallengedFact] = field(default_factory=list[ChallengedFact])
    challenge_quotes: list[QuotedText] = field(default_factory=list[QuotedText])
    challenge_ids: dict[str, uuid.UUID] = field(default_factory=dict[str, uuid.UUID])


@dataclass(frozen=True)
class ReaderOutcome:
    status: SessionStatus
    artifacts: dict[str, JsonValue]


# --- the documents --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Document:
    id: uuid.UUID
    title: str
    company_id: uuid.UUID | None
    company_slug: str | None
    company_names: list[str]
    form_type: str | None
    document_type: str | None
    source_type: str
    parser_version: str
    available_at: datetime
    text: str
    sections: tuple[Section, ...]

    @property
    def kind(self) -> str | None:
        return self.document_type or self.form_type


Recall = Callable[[str], RecallResponse]


class Reader:
    """Runs a Reader's session to its end, or until the run's token budget is spent."""

    def __init__(
        self,
        engine: Engine,
        archive: Archive,
        caller: RoleCaller,
        recall: Recall | None,
        *,
        role: Role[ReaderRequest, ReaderAction],
        extractor_version: str,
        actor: Actor,
        max_calls: int,
        max_passages: int,
    ) -> None:
        self._engine = engine
        self._archive = archive
        self._caller = caller
        self._recall = recall
        self._role = role
        self._extractor_version = extractor_version
        self._actor = actor
        self._max_calls = max_calls
        self._max_passages = max_passages
        self._documents: dict[uuid.UUID, _Document | None] = {}

    def run(self, session: Session, setup: ReaderSetup) -> ReaderOutcome:
        state = session.state
        if session.status in ("done", "bounded"):
            return ReaderOutcome(
                session.status, artifacts(session.id, setup, state, session.status)
            )
        self._as_of = session.as_of
        self._setup = setup
        self._skeptic = bool(setup.challenge)
        while True:
            if state.calls >= self._max_calls:
                state.stop_reason = "max_calls"
                return self._end(session, state, "bounded")
            request = self._request(state)
            retrieved = self._retrieved(state)
            try:
                action, role_call_id = self._caller.call_recorded(
                    self._role, request, run_id=session.run_id, retrieved=retrieved
                )
            except TokenBudgetExhausted:
                state.stop_reason = "token_budget"
                return self._end(session, state, "budget_exhausted")
            except RoleOutputQuarantined as failure:
                state.calls += 1
                state.quarantined += 1
                state.quarantined_in_a_row += 1
                state.role_call_ids.append(str(failure.role_call_id))
                self._result(
                    state,
                    "invalid",
                    ok=False,
                    message="your answer did not match the response schema twice and was set"
                    " aside: answer with one action, its arguments in the field of its name",
                )
                if state.quarantined_in_a_row >= QUARANTINE_LIMIT:
                    state.stop_reason = "quarantined"
                    return self._end(session, state, "bounded")
                _save(self._engine, session.id, state, "running")
                continue
            state.calls += 1
            state.quarantined_in_a_row = 0
            state.role_call_ids.append(str(role_call_id))
            if action.action == "done" and not (state.searches or state.recalls):
                # A step is never finished unsearched (0.5.1's invalidation Reader answered
                # done on its first call): refused, and the call counted.
                self._result(
                    state,
                    "done",
                    ok=False,
                    message="search first: you have not searched the archive or recalled yet."
                    " Search the seed companies' filings and calls with the words they would"
                    " use for this step, read what you find, and only then say done",
                )
                _save(self._engine, session.id, state, "running")
                continue
            if action.action == "done":
                assert action.done is not None
                state.summary = action.done.summary
                state.stop_reason = "done"
                return self._end(session, state, "done")
            self._act(state, action)
            _save(self._engine, session.id, state, "running")

    def _end(self, session: Session, state: ReaderState, status: SessionStatus) -> ReaderOutcome:
        _save(self._engine, session.id, state, status)
        return ReaderOutcome(status, artifacts(session.id, self._setup, state, status))

    # --- the request ----------------------------------------------------------------------

    def _request(self, state: ReaderState) -> ReaderRequest:
        step = self._setup.step
        return ReaderRequest(
            research_question=self._setup.question,
            as_of=self._as_of.astimezone(UTC).isoformat(),
            step=ReaderStep(
                key=step.key, title=step.title, asks=step.asks, looks_for=step.looks_for
            ),
            companies=[
                ReaderCompany(slug=c.slug, name=c.display_name, layer=c.layer, seed=c.seed)
                for c in self._setup.companies
            ],
            challenge=self._setup.challenge,
            searched=[str(each["line"]) for each in state.searches],
            recalled=[str(each["line"]) for each in state.recalls],
            read=[str(each["line"]) for each in state.reads],
            recorded=[
                ReaderFactSummary(
                    ref=fact.ref,
                    company_slug=fact.company_slug,
                    step=fact.step,
                    status=fact.status,
                    statement=fact.statement,
                    quantity=_quantity_text(fact.quantity),
                    period=fact.period,
                    challenges=fact.challenges,
                )
                for fact in state.facts
            ],
            refused=len(state.refused),
            results=state.results[-RESULTS_KEPT:],
            calls_left=max(self._max_calls - state.calls - 1, 0),
            passages_left=max(self._max_passages - state.passages_sent, 0),
        )

    def _retrieved(self, state: ReaderState) -> list[QuotedText]:
        quoted: list[QuotedText] = list(self._setup.challenge_quotes)
        for item_id in dict.fromkeys(each for ids in state.shown for each in ids):
            passage = state.passages.get(item_id)
            if passage is not None:
                quoted.append(
                    QuotedText(
                        id=passage.id,
                        source=f"{passage.source_version_id}#{passage.start}-{passage.end}",
                        text=passage.text,
                    )
                )
                continue
            memory = state.memories.get(item_id)
            if memory is not None:
                quoted.append(
                    QuotedText(
                        id=memory.id,
                        source=f"memory:{memory.source_version_id}#{memory.anchor}",
                        text=memory.text,
                    )
                )
        return quoted

    def _result(
        self,
        state: ReaderState,
        action: str,
        *,
        ok: bool,
        message: str,
        items: Sequence[ResultItem] = (),
    ) -> None:
        state.results.append(
            ReaderResult(call=state.calls, action=action, ok=ok, message=message, items=list(items))
        )
        del state.results[:-RESULTS_KEPT]
        if items:
            state.shown.append([item.id for item in items])
            del state.shown[:-RESULTS_IN_FULL]

    # --- the actions ----------------------------------------------------------------------

    def _act(self, state: ReaderState, action: ReaderAction) -> None:
        if action.search_archive is not None:
            self._search(state, action.search_archive.query, action.search_archive.company_slugs)
        elif action.recall is not None:
            self._recall_memory(state, action.recall.query)
        elif action.read is not None:
            read = action.read
            self._read(state, read.ref, read.source_version_id, read.anchor, read.window)
        elif action.record_fact is not None:
            self._record(state, action.record_fact.facts)

    def _passages_left(self, state: ReaderState) -> int:
        return max(self._max_passages - state.passages_sent, 0)

    def _search(self, state: ReaderState, query: str, slugs: Sequence[str]) -> None:
        companies = {c.slug: c for c in self._setup.companies}
        unknown = [slug for slug in slugs if slug not in companies]
        left = self._passages_left(state)
        refusal: str | None = None
        if not query.strip():
            refusal = "the query is empty"
        elif unknown:
            refusal = f"unknown company slugs: {', '.join(unknown)} (use the slugs listed)"
        elif left == 0:
            refusal = "the passage budget is spent: record what you have read, or say done"
        if refusal is not None:
            self._result(state, "search_archive", ok=False, message=refusal)
            return
        # Imported here: the archive search reuses atlas.evaluation's baseline, which imports
        # this package.
        from atlas.research.archive_search import archive_search

        chosen = [companies[slug] for slug in dict.fromkeys(slugs)] or self._setup.companies
        found = archive_search(
            self._engine,
            self._archive,
            query,
            [c.id for c in chosen],
            self._as_of,
            top=min(SEARCH_HITS, left),
            per_document=SEARCH_HITS_PER_DOCUMENT,
        )
        items: list[ResultItem] = []
        for hit in found.hits:
            passage = Passage(
                id=state.new_id("h"),
                kind="hit",
                source_version_id=hit.source_version_id,
                parser_version=hit.parser_version,
                start=hit.char_start,
                end=hit.char_end,
                title=hit.title,
                company_slug=hit.company,
                document_kind=hit.document_type or hit.form_type,
                date=hit.available_at.date().isoformat(),
                anchor=hit.section_anchor,
                note=None,
                text=hit.text,
            )
            state.passages[passage.id] = passage
            items.append(_item(passage))
        state.passages_sent += len(items)
        searched = "every company listed" if not slugs else ", ".join(c.slug for c in chosen)
        state.searches.append(
            {
                "call": state.calls,
                "query": query,
                "company_slugs": list[JsonValue](c.slug for c in chosen),
                "documents_searched": found.documents_searched,
                "hits": list[JsonValue](item.id for item in items),
                "line": f'"{query}" in {searched}: {len(items)} hits',
            }
        )
        message = (
            f"{len(items)} hits in {found.documents_searched} documents"
            if items
            else f"no hit in {found.documents_searched} documents: try the words a filing or a"
            " call would use, or other companies"
        )
        self._result(state, "search_archive", ok=True, message=message, items=items)

    def _recall_memory(self, state: ReaderState, query: str) -> None:
        if self._recall is None:
            self._result(state, "recall", ok=False, message="Memory is not available here")
            return
        if not query.strip():
            self._result(state, "recall", ok=False, message="the query is empty")
            return
        answer = self._recall(query)
        items: list[ResultItem] = []
        unresolved = 0
        for memory in answer.memories:
            if len(items) >= MEMORIES_SHOWN:
                break
            sources = [
                s
                for s in memory.provenance.sources
                if s.available_at.astimezone(UTC) <= self._as_of.astimezone(UTC)
            ]
            document = self._document(sources[0].source_version_id) if sources else None
            if memory.provenance.state != "resolved" or not sources or document is None:
                unresolved += 1
                continue
            source = sources[0]
            recalled = Memory(
                id=state.new_id("m"),
                source_version_id=source.source_version_id,
                anchor=source.section_anchor,
                heading=source.section_heading,
                position=source.chunk_char_start,
                title=document.title,
                company_slug=document.company_slug,
                document_kind=document.kind,
                date=document.available_at.date().isoformat(),
                text=memory.text[:MEMORY_TEXT_CHARS],
            )
            state.memories[recalled.id] = recalled
            items.append(
                ResultItem(
                    id=recalled.id,
                    source_version_id=str(recalled.source_version_id),
                    company_slug=recalled.company_slug,
                    title=recalled.title,
                    kind=recalled.document_kind,
                    date=recalled.date,
                    section=recalled.anchor,
                    note=recalled.heading,
                )
            )
        state.recalls.append(
            {
                "call": state.calls,
                "query": query,
                "memories": list[JsonValue](item.id for item in items),
                "unresolved": unresolved,
                "line": f'"{query}": {len(items)} memories',
            }
        )
        message = (
            f"{len(items)} memories point to sections (Memory is never a witness: read a"
            " section to quote it)"
            if items
            else "no memory points to a section available as of the question's time"
        )
        self._result(state, "recall", ok=True, message=message, items=items)

    def _read(
        self,
        state: ReaderState,
        ref: str | None,
        version: str | None,
        anchor: str | None,
        window: int | None,
    ) -> None:
        if self._passages_left(state) == 0:
            self._result(
                state,
                "read",
                ok=False,
                message="the passage budget is spent: record what you have read, or say done",
            )
            return
        position: int | None = None
        version_id: uuid.UUID | None = None
        if ref:
            passage = state.passages.get(ref)
            memory = state.memories.get(ref)
            if passage is not None:
                version_id, position = passage.source_version_id, passage.start
                anchor = anchor or (passage.anchor if passage.kind == "window" else None)
            elif memory is not None:
                version_id, anchor, position = (
                    memory.source_version_id,
                    memory.anchor,
                    memory.position,
                )
            else:
                self._result(state, "read", ok=False, message=f"no hit, memory or window {ref!r}")
                return
        elif version:
            try:
                version_id = uuid.UUID(version)
            except ValueError:
                self._result(
                    state, "read", ok=False, message=f"{version!r} is not a Source Version id"
                )
                return
        else:
            self._result(
                state,
                "read",
                ok=False,
                message="name a `ref` (h<n>, m<n>, p<n>) or a `source_version_id` and `anchor`",
            )
            return
        document = self._document(version_id)
        if document is None:
            self._result(
                state,
                "read",
                ok=False,
                message=f"no parsed document {version_id} available as of the question's time",
            )
            return
        section = _section(document, anchor, position)
        if section is None:
            shown = ", ".join(s.anchor for s in document.sections[:_ANCHORS_SHOWN])
            self._result(
                state,
                "read",
                ok=False,
                message=f"no section {anchor!r} in {document.title}; its sections: {shown}",
            )
            return
        windows = cut_windows(document.text, section.start, section.end) or [
            (section.start, section.end)
        ]
        if window is not None:
            if not 1 <= window <= len(windows):
                self._result(
                    state,
                    "read",
                    ok=False,
                    message=f"section {section.anchor} has {len(windows)} windows (1 to"
                    f" {len(windows)})",
                )
                return
            index = window - 1
        else:
            index = next(
                (
                    i
                    for i, (s, e) in enumerate(windows)
                    if position is not None and s <= position < e
                ),
                0,
            )
        start, end = windows[index]
        note = f"{section.heading or section.anchor}, window {index + 1} of {len(windows)}"
        passage = Passage(
            id=state.new_id("p"),
            kind="window",
            source_version_id=document.id,
            parser_version=document.parser_version,
            start=start,
            end=end,
            title=document.title,
            company_slug=document.company_slug,
            document_kind=document.kind,
            date=document.available_at.date().isoformat(),
            anchor=section.anchor,
            note=note,
            text=document.text[start:end],
        )
        state.passages[passage.id] = passage
        state.passages_sent += 1
        state.reads.append(
            {
                "call": state.calls,
                "passage_id": passage.id,
                "source_version_id": str(document.id),
                "title": document.title,
                "section": section.anchor,
                "window": index + 1,
                "windows": len(windows),
                "line": f"{passage.id}: {document.title}, {section.anchor}, window {index + 1}"
                f" of {len(windows)}",
            }
        )
        self._result(
            state, "read", ok=True, message=f"{document.title}: {note}", items=[_item(passage)]
        )

    def _record(self, state: ReaderState, proposed: Sequence[RecordFact]) -> None:
        """Place and record each proposed Fact on its own; one result says, Fact by Fact,
        which were recorded and which refused, and why."""
        outcomes: list[str] = []
        refused = 0
        for number, each in enumerate(proposed, start=1):
            done = self._recorded(state, each)
            if isinstance(done, RecordedFact):
                outcomes.append(
                    f"fact {number}: recorded as {done.ref} ({done.company_slug}, {done.step},"
                    f" {done.status})"
                )
                continue
            code, reason = done
            state.refused.append(
                Refusal(
                    call=state.calls,
                    reason_code=code,
                    reason=reason,
                    passage_id=each.passage_id,
                    quote=each.quote,
                )
            )
            outcomes.append(f"fact {number}: refused ({code}): {reason}")
            refused += 1
        if len(outcomes) == 1:
            # One Fact: the outcome alone, as `reader.v1`'s single-fact result read.
            message = outcomes[0].split(": ", 1)[1]
        else:
            counted = f"{len(outcomes) - refused} of {len(outcomes)} facts recorded"
            message = "; ".join([counted, *outcomes])
        self._result(state, "record_fact", ok=refused == 0, message=message)

    def _recorded(self, state: ReaderState, proposed: RecordFact) -> RecordedFact | tuple[str, str]:
        """Record the Fact (its record), or why not (a reason code and the reason in words)."""
        # Imported here: atlas.facts imports this package (the grounding check).
        from atlas.facts import FactCreate, Facts, Quantity

        passage = state.passages.get(proposed.passage_id)
        if passage is None:
            return (
                "unknown_passage",
                f"{proposed.passage_id!r} is not a hit or window you were sent: quote only"
                " from those (a memory is never a witness)",
            )
        companies = {c.slug: c for c in self._setup.companies}
        company = companies.get(proposed.company_slug)
        if company is None:
            return "unknown_company", f"unknown company slug {proposed.company_slug!r}"
        challenges: list[str] = []
        if self._skeptic:
            known = {fact.ref for fact in self._setup.challenge}
            unknown = [ref for ref in proposed.challenges if ref not in known]
            if unknown:
                return "unknown_fact", f"no Fact {', '.join(unknown)} to challenge"
            challenges = list(dict.fromkeys(proposed.challenges))
        document = self._document(passage.source_version_id)
        if document is None:
            return "unknown_passage", "the passage's document is no longer readable"
        placed = place_quote(document.text, passage.start, passage.end, proposed.quote)
        if isinstance(placed, QuoteRefused):
            return placed.code, placed.reason
        start, end = placed
        quote = document.text[start:end]
        own = document.company_id == company.id
        names = company_names(company.display_name, company.legal_name)
        if not names_party(quote, names, is_filer=own):
            return (
                "party_not_in_quote",
                f"the quote does not name {company.display_name}, and the document is not"
                " its own: quote the sentence that names it",
            )
        if document.source_type == TRANSCRIPT_SOURCE_TYPE:
            speaker = transcript_speaker(document.text, (start, end), document.company_names)
            if isinstance(speaker, SpeakerRefusal):
                return speaker.code, speaker.message
        for fact in state.facts:
            if (
                fact.source_version_id == document.id
                and (fact.span_start, fact.span_end) == (start, end)
                and fact.company_slug == company.slug
                and fact.step == proposed.step
            ):
                return "already_recorded", f"this quote is recorded already as {fact.ref}"
        try:
            request = FactCreate(
                subject_company_id=company.id,
                source_version_id=document.id,
                quote=quote,
                span_start=start,
                span_end=end,
                page_or_anchor=None,
                epistemic_type="company_claim" if own else "third_party_report",
                parser_version=document.parser_version,
                investigation_id=self._setup.investigation_id,
                step=proposed.step,
                statement=proposed.statement,
                quantity=(
                    Quantity(
                        value=proposed.quantity.value,
                        unit=proposed.quantity.unit,
                        metric=proposed.quantity.metric,
                    )
                    if proposed.quantity is not None
                    else None
                ),
                period=proposed.period,
                status=proposed.status,
            )
        except ValidationError as error:
            details = "; ".join(
                f"{'.'.join(str(p) for p in each['loc'])}: {each['msg']}"
                for each in error.errors(include_url=False)
            )
            return "invalid_fact", details
        try:
            recorded = Facts(self._engine, self._archive, self._actor).create(
                request, extractor_version=self._extractor_version
            )
        except AssertionRefused as refused:
            return refused.code, refused.message
        fact = RecordedFact(
            ref=state.new_id("r"),
            fact_id=recorded.fact.id,
            call=state.calls,
            passage_id=passage.id,
            source_version_id=document.id,
            span_start=start,
            span_end=end,
            company_slug=company.slug,
            step=proposed.step,
            status=proposed.status,
            statement=proposed.statement,
            quantity=(
                proposed.quantity.model_dump(mode="json") if proposed.quantity is not None else None
            ),
            period=proposed.period,
            quote=quote,
            challenges=challenges,
            challenged_fact_ids=[
                self._setup.challenge_ids[ref]
                for ref in challenges
                if ref in self._setup.challenge_ids
            ],
        )
        state.facts.append(fact)
        return fact

    # --- documents --------------------------------------------------------------------------

    def _document(self, version_id: uuid.UUID) -> _Document | None:
        """The Source Version's current parse and what the Reader shows of it, or None when it
        has no text or isn't available as of the session's time."""
        if version_id in self._documents:
            return self._documents[version_id]
        document: _Document | None = None
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT v.id, coalesce(d.title, d.canonical_url) AS title, d.company_id,"
                        " c.slug, c.display_name, c.legal_name, d.form_type, d.document_type,"
                        " d.source_type, a.available_at FROM source_version v"
                        " JOIN source_document d ON d.id = v.source_document_id"
                        " JOIN source_version_availability a ON a.source_version_id = v.id"
                        " LEFT JOIN company c ON c.id = d.company_id"
                        " WHERE v.id = :id AND a.available_at <= :as_of"
                    ),
                    {"id": version_id, "as_of": self._as_of},
                )
                .mappings()
                .one_or_none()
            )
            parse = current_parse(connection, version_id) if row is not None else None
        if (
            row is not None
            and parse is not None
            and parse.parse_status in ("parsed", "incomplete")
            and parse.parsed_object_uri is not None
        ):
            parsed = self._archive.get(parse.parsed_object_uri).decode("utf-8")
            primary = row["document_type"] is not None and row["document_type"] == row["form_type"]
            document = _Document(
                id=row["id"],
                title=row["title"],
                company_id=row["company_id"],
                company_slug=row["slug"],
                company_names=(
                    company_names(row["display_name"], row["legal_name"])
                    if row["display_name"]
                    else []
                ),
                form_type=row["form_type"],
                document_type=row["document_type"],
                source_type=row["source_type"],
                parser_version=parse.parser_version,
                available_at=row["available_at"],
                text=parsed,
                sections=tuple(split_sections(parsed, form=row["form_type"], primary=primary)),
            )
        self._documents[version_id] = document
        return document


# --- helpers --------------------------------------------------------------------------------


@dataclass(frozen=True)
class QuoteRefused:
    code: Literal["quote_ambiguous", "quote_not_found"]
    reason: str


def place_quote(parsed: str, start: int, end: int, quote: str) -> tuple[int, int] | QuoteRefused:
    """Where `quote` is: its one occurrence in the passage `parsed[start:end]`, else its one
    occurrence there through the typographic fold (`atlas.claims.predicates.fold`: one
    character for one, so the offsets are the text's own), else the same two steps in the whole
    parse. The span, or why not: `quote_ambiguous` (more than one occurrence where it was
    looked for) or `quote_not_found`."""
    if not quote.strip():
        return QuoteRefused("quote_not_found", "the quote is empty")
    for low, high in ((start, end), (0, len(parsed))):
        window = parsed[low:high]
        for haystack, needle in ((window, quote), (fold(window), fold(quote))):
            first = haystack.find(needle)
            if first < 0:
                continue
            if haystack.find(needle, first + 1) >= 0:
                where = "the passage" if (low, high) == (start, end) else "the document"
                return QuoteRefused(
                    "quote_ambiguous",
                    f"the quote occurs more than once in {where}: quote a longer, unique part",
                )
            return low + first, low + first + len(quote)
    return QuoteRefused(
        "quote_not_found",
        "the quote is not in the passage or its document as written: copy it exactly,"
        " one contiguous run of the passage's words",
    )


def _section(document: _Document, anchor: str | None, position: int | None) -> Section | None:
    if anchor:
        return next((s for s in document.sections if s.anchor == anchor), None)
    if position is not None:
        found = next((s for s in document.sections if s.start <= position < s.end), None)
        if found is not None:
            return found
    return document.sections[0] if document.sections else None


def _item(passage: Passage) -> ResultItem:
    return ResultItem(
        id=passage.id,
        source_version_id=str(passage.source_version_id),
        company_slug=passage.company_slug,
        title=passage.title,
        kind=passage.document_kind,
        date=passage.date,
        section=passage.anchor,
        note=passage.note,
    )


def _quantity_text(quantity: dict[str, Any] | None) -> str | None:
    if quantity is None:
        return None
    return f"{quantity.get('value')} {quantity.get('unit')} ({quantity.get('metric')})"


def artifacts(
    session_id: uuid.UUID, setup: ReaderSetup, state: ReaderState, status: SessionStatus
) -> dict[str, JsonValue]:
    """What a Reader did, for its job's or task's artifacts: what it searched, recalled,
    read, recorded and was refused, and why it stopped."""
    return {
        "reader_session_id": str(session_id),
        "step": setup.step.key,
        "reader_status": status,
        "stop_reason": state.stop_reason,
        "calls": state.calls,
        "quarantined": state.quarantined,
        "passages": state.passages_sent,
        "searches": [
            {
                "query": each["query"],
                "company_slugs": each["company_slugs"],
                "documents_searched": each["documents_searched"],
                "hits": len(each["hits"]) if isinstance(each["hits"], list) else 0,
            }
            for each in state.searches
        ],
        "recalls": [
            {
                "query": each["query"],
                "memories": len(each["memories"]) if isinstance(each["memories"], list) else 0,
                "unresolved": each["unresolved"],
            }
            for each in state.recalls
        ],
        "reads": [
            {
                key: each[key]
                for key in ("passage_id", "source_version_id", "title", "section", "window")
            }
            for each in state.reads
        ],
        "facts": [
            {
                "fact_id": str(fact.fact_id),
                "ref": fact.ref,
                "company": fact.company_slug,
                "step": fact.step,
                "status": fact.status,
                "statement": fact.statement,
                "source_version_id": str(fact.source_version_id),
                "challenges": list[JsonValue](str(each) for each in fact.challenged_fact_ids),
            }
            for fact in state.facts
        ],
        "refused": [
            {"reason_code": each.reason_code, "reason": each.reason, "quote": each.quote}
            for each in state.refused
        ],
        "facts_recorded": len(state.facts),
        "facts_refused": len(state.refused),
        "summary": state.summary,
    }


# --- the standalone job -----------------------------------------------------------------------


class ReadStepPayload(BaseModel):
    """`read_step`: one Reader in its own run."""

    model_config = ConfigDict(extra="forbid")

    theme: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=2000)
    step: ArgumentStep
    company_ids: list[uuid.UUID] = Field(
        default_factory=list[uuid.UUID], description="the seed companies (listed first)"
    )
    as_of: AwareDatetime | None = Field(
        default=None, description="nothing available later is read (default: the job's time)"
    )


class ReadStepRefused(ValueError):
    """A `read_step` payload that names an unknown theme or seed company."""


def run_read_step(
    settings: Settings,
    engine: Engine,
    gateway: HindsightGateway,
    runs: RunRecorder,
    caller: RoleCaller,
    job: Job,
) -> Artifacts:
    """The `read_step` job: one Reader in its own run (created with its session, finished
    when the Reader stops)."""
    payload = ReadStepPayload.model_validate(job.payload)
    universe = load_universe(settings.themes_config)
    theme = universe.themes.get(payload.theme)
    if theme is None:
        raise ReadStepRefused(f"no theme {payload.theme!r} in the universe config")
    with engine.begin() as connection:
        companies = reader_companies(connection, payload.company_ids, list(theme.companies))
        missing = sorted(
            str(each) for each in set(payload.company_ids) - {c.id for c in companies if c.seed}
        )
        if missing:
            raise ReadStepRefused(f"unknown or not researched seed companies: {', '.join(missing)}")
        session = open_session(
            connection,
            key=f"job:{job.id}",
            run_id=lambda: runs.start(RUN_KIND).id,
            role="reader",
            step=payload.step,
            question=payload.question,
            as_of=payload.as_of or job.created_at,
            job_id=job.id,
        )
    archive = open_archive(settings)
    research = Research(engine, archive, gateway, READER_ACTOR, lambda: universe)
    as_of = session.as_of

    def recall(query: str) -> RecallResponse:
        return research.recall(
            reading_index_recall(
                query,
                ResearchScope(theme_ids=[payload.theme]),
                max_tokens=settings.reader_recall_max_tokens,
                as_of=as_of,
            )
        )

    reader = Reader(
        engine,
        archive,
        caller,
        recall,
        role=READER,
        extractor_version=READER_VERSION,
        actor=READER_ACTOR,
        max_calls=settings.reader_max_calls,
        max_passages=settings.reader_max_passages,
    )
    outcome = reader.run(
        session,
        ReaderSetup(question=payload.question, step=STEPS[payload.step], companies=companies),
    )
    with engine.connect() as connection:
        usage = run_usage(connection, session.run_id)
    try:
        runs.finish(session.run_id, tokens_in=usage.tokens_in, tokens_out=usage.tokens_out)
    except RunNotFound:
        pass  # an earlier attempt finished it
    return {"run_id": str(session.run_id), **outcome.artifacts}
