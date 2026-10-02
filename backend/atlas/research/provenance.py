"""The provenance resolver: from Memory back to Source Versions (spec Part B stories 17-22).

Memory is never Evidence (CONTEXT.md). A memory leads to Evidence only when it resolves, hop
by hop, to a section of an archived Source Version:

- an **observation** is followed through its `source_memory_ids` to the facts it was
  consolidated from (Hindsight 0.10.1 gives observations no `document_id`; the feature
  matrix's two-hop path). A recall asked with `include.source_facts` (0.10.2) carries an
  observation's source IDs and its source facts in the same answer, and they are used
  as they are; a source the answer lists but leaves out is asked for, so the states are
  the same either way (memory-quality ticket 07)
- a **world fact** maps via its `document_id` (`srcv:<source_version_uuid>:<anchor>`,
  ADR-0001) to the ledger's `memory_document` row, and its `metadata.source_version_id` (and
  `metadata.section_anchor`) must agree with that row. A world fact a 0.10.2 reflect answer
  cites carries both, so it is resolved from the answer itself, without looking it up
  (memory-quality ticket 10); one cited without them (a mental model's `based_on`) is
  looked up first
- a **mental model** a reflect answer read is reported as one (kind `mental_model`,
  `unverified`): it is Hindsight's own synthesis, never resolved to a section
- each **quote** in an answer must occur in the archived parsed text of a section the answer's
  resolved citations lead to (`atlas.research.quotes` holds the normalization rule)

Every citation gets one state:

- **resolved**: every hop reached a Source Version section (and a quote matched in one)
- **unverified**: content without memory identity (a raw chunk), a memory whose document is
  not an Atlas section or disagrees with the ledger, an observation with no sources, or a
  quote that matches no cited section
- **broken**: the memory, or one of an observation's source memories, is gone

An observation takes its worst hop's state (broken, then unverified). Only resolved
citations are presented as `Evidence`.
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.archive import Archive
from atlas.hindsight import (
    CitedMemory,
    CitedMentalModel,
    HindsightGateway,
    HindsightNotFound,
    Memory,
    RecallResult,
)
from atlas.research.quotes import extract_quotes, find_quote

type CitationState = Literal["resolved", "unverified", "broken"]
type CitationKind = Literal["memory", "chunk", "quote", "mental_model"]
type UnresolvedReason = Literal[
    "mental_model",
    "no_memory_id",
    "memory_not_found",
    "source_memory_not_found",
    "no_source_memories",
    "not_an_atlas_document",
    "unknown_document",
    "metadata_mismatch",
    "too_many_hops",
    "quote_mismatch",
]
CITATION_STATES: tuple[CitationState, ...] = ("resolved", "unverified", "broken")

# Observations of observations are followed this deep, then left unverified.
MAX_HOPS = 3
_SEVERITY: dict[CitationState, int] = {"resolved": 0, "unverified": 1, "broken": 2}


class CitationSource(BaseModel):
    """A world fact resolved to the Source Version section it was extracted from."""

    memory_id: str
    document_id: str
    source_version_id: uuid.UUID
    source_document_id: uuid.UUID
    company_id: uuid.UUID | None
    form_type: str | None
    section_anchor: str
    section_heading: str | None
    section_char_start: int
    section_char_end: int
    available_at: datetime
    available_at_basis: str


class QuoteSpan(BaseModel):
    """A quote matched in the archived parsed text: code-point offsets, like an Assertion's."""

    quoted: str  # as it appears in the answer
    source_version_id: uuid.UUID
    char_start: int
    char_end: int
    archived_text: str  # the parsed text at [char_start, char_end)


class Citation(BaseModel):
    kind: CitationKind
    state: CitationState
    reason: UnresolvedReason | None
    detail: str | None
    memory_id: str | None  # for a quote: the resolved citation whose section matched it
    memory_type: str | None
    text: str  # the memory's or chunk's text as Hindsight gave it, or the quote
    sources: list[CitationSource]
    missing_memory_ids: list[str]
    quote: QuoteSpan | None


class Evidence(BaseModel):
    """A Source Version section that resolved citations lead to (Evidence, not Memory)."""

    source_version_id: uuid.UUID
    source_document_id: uuid.UUID
    company_id: uuid.UUID | None
    form_type: str | None
    section_anchor: str
    section_heading: str | None
    section_char_start: int
    section_char_end: int
    available_at: datetime
    available_at_basis: str
    memory_ids: list[str]  # the resolved memories and facts that lead here
    quotes: list[QuoteSpan]  # the answer's quotes matched in this section


def evidence_from(citations: Sequence[Citation]) -> list[Evidence]:
    """The sections behind the resolved citations only, in first-cited order."""
    found: dict[tuple[uuid.UUID, str], Evidence] = {}
    for citation in citations:
        if citation.state != "resolved":
            continue
        for source in citation.sources:
            key = (source.source_version_id, source.section_anchor)
            if key not in found:
                fields = source.model_dump(exclude={"memory_id", "document_id"})
                found[key] = Evidence(**fields, memory_ids=[], quotes=[])
            evidence = found[key]
            for memory_id in (citation.memory_id, source.memory_id):
                if memory_id and memory_id not in evidence.memory_ids:
                    evidence.memory_ids.append(memory_id)
            if citation.quote is not None:
                evidence.quotes.append(citation.quote)
    return list(found.values())


def state_counts(citations: Sequence[Citation]) -> dict[CitationState, int]:
    counts: dict[CitationState, int] = dict.fromkeys(CITATION_STATES, 0)
    for citation in citations:
        counts[citation.state] += 1
    return counts


@dataclass
class _Outcome:
    state: CitationState
    reason: UnresolvedReason | None = None
    detail: str | None = None
    sources: list[CitationSource] = field(default_factory=list[CitationSource])
    missing: list[str] = field(default_factory=list[str])


@dataclass(frozen=True)
class _Section:
    source: CitationSource
    parsed_object_uri: str | None


# A document's section: a row with the columns `ledger_sections` selects, or None.
type SectionLookup = Callable[[Connection, str], RowMapping | None]


def ledger_sections(bank_id: str) -> SectionLookup:
    """The ledger's sections of `bank_id`: its `memory_document` rows."""

    def lookup(connection: Connection, document_id: str) -> RowMapping | None:
        return (
            connection.execute(
                text(
                    "SELECT m.hindsight_document_id, m.source_version_id,"
                    " m.section_anchor, m.section_heading, m.char_start, m.char_end,"
                    " v.source_document_id, a.available_at, a.available_at_basis,"
                    " v.parsed_object_uri, d.company_id, d.form_type"
                    " FROM memory_document m"
                    " JOIN source_version v ON v.id = m.source_version_id"
                    " JOIN source_version_availability a ON a.source_version_id = v.id"
                    " JOIN source_document d ON d.id = v.source_document_id"
                    " WHERE m.hindsight_document_id = :document AND m.bank_id = :bank"
                ),
                {"document": document_id, "bank": bank_id},
            )
            .mappings()
            .one_or_none()
        )

    return lookup


class ProvenanceResolver:
    """Resolves one recall's or answer's memories; caches memories and texts for its life."""

    def __init__(
        self,
        engine: Engine,
        archive: Archive,
        gateway: HindsightGateway,
        *,
        sections: SectionLookup | None = None,
    ) -> None:
        """`sections` finds a document's section (default: the ledger's `memory_document`
        rows of the gateway's bank; a replay passes its own, `atlas.replay`)."""
        self._engine = engine
        self._archive = archive
        self._gateway = gateway
        self._sections = sections or ledger_sections(gateway.bank_id)
        self._memories: dict[str, Memory | None] = {}
        self._parsed: dict[uuid.UUID, str | None] = {}
        self._uris: dict[uuid.UUID, str | None] = {}

    def resolve_recalled(self, memory: Memory, answer: RecallResult | None = None) -> Citation:
        """A recalled memory's provenance (the recall result carries a fact's document).

        With `answer`, the recall it came from: an observation's sources that the answer
        carries (`include.source_facts`) are taken from it, so the observation resolves with
        no request of its own; a source it lists but leaves out (the answer's
        `source_facts_truncated`, or a source that no longer exists) is asked for as before,
        so every citation state is the one the per-memory requests would give."""
        if answer is not None:
            for fact_id, fact in answer.source_facts.items():
                self._memories.setdefault(fact_id, fact)
        outcome = self._resolve(memory, depth=0)
        return _citation("memory", outcome, memory.id, memory.type, memory.text)

    def resolve_answer(
        self,
        answer: str,
        cited: Sequence[CitedMemory],
        mental_models: Sequence[CitedMentalModel] = (),
    ) -> list[Citation]:
        """The answer's cited memories and chunks, the mental models it read, then each of
        its quotes."""
        citations: list[Citation] = []
        for memory in cited:
            if memory.id is None:
                outcome = _Outcome(
                    "unverified",
                    "no_memory_id",
                    "content drawn from a raw chunk, with no memory identity to follow",
                )
                citations.append(_citation("chunk", outcome, None, memory.type, memory.text))
                continue
            if memory.type != "observation" and memory.document_id:
                # 0.10.2: the cited fact names its document and metadata; one hop.
                outcome = self._resolve_fact(_as_memory(memory))
            else:
                found = self._memory(memory.id)
                if found is None:
                    outcome = _Outcome(
                        "broken", "memory_not_found", "the cited memory no longer exists"
                    )
                    outcome.missing.append(memory.id)
                else:
                    outcome = self._resolve(found, depth=0)
            citations.append(_citation("memory", outcome, memory.id, memory.type, memory.text))
        for model in mental_models:
            outcome = _Outcome(
                "unverified",
                "mental_model",
                "a mental model is Hindsight's own synthesis; it never resolves to a section",
            )
            citations.append(_citation("mental_model", outcome, model.id, None, model.text))
        citations.extend(self._quotes(answer, citations))
        return citations

    # --- hops ----------------------------------------------------------------------------------

    def _memory(self, memory_id: str) -> Memory | None:
        if memory_id not in self._memories:
            try:
                self._memories[memory_id] = self._gateway.get_memory(memory_id)
            except HindsightNotFound:
                self._memories[memory_id] = None
        return self._memories[memory_id]

    def _resolve(self, memory: Memory, *, depth: int) -> _Outcome:
        if memory.type == "observation":
            return self._resolve_observation(memory, depth=depth)
        return self._resolve_fact(memory)

    def _resolve_observation(self, memory: Memory, *, depth: int) -> _Outcome:
        if depth >= MAX_HOPS:
            return _Outcome("unverified", "too_many_hops", f"more than {MAX_HOPS} hops deep")
        source_ids = memory.source_memory_ids
        if not source_ids:
            # A recall result carries no source IDs; the memory lookup does.
            looked_up = self._memory(memory.id)
            source_ids = looked_up.source_memory_ids if looked_up is not None else []
        if not source_ids:
            return _Outcome(
                "unverified", "no_source_memories", "the observation lists no source memories"
            )
        combined = _Outcome("resolved")
        for source_id in source_ids:
            source = self._memory(source_id)
            if source is None:
                hop = _Outcome(
                    "broken",
                    "source_memory_not_found",
                    "a memory the observation was consolidated from no longer exists",
                )
                hop.missing.append(source_id)
            else:
                hop = self._resolve(source, depth=depth + 1)
            combined.sources.extend(hop.sources)
            combined.missing.extend(hop.missing)
            if _SEVERITY[hop.state] > _SEVERITY[combined.state]:
                combined.state, combined.reason, combined.detail = hop.state, hop.reason, hop.detail
        return combined

    def _resolve_fact(self, memory: Memory) -> _Outcome:
        document_id = memory.document_id
        if not document_id or not document_id.startswith("srcv:"):
            return _Outcome(
                "unverified",
                "not_an_atlas_document",
                f"document {document_id!r} is not an Atlas Source Version section",
            )
        section = self._section(document_id, memory.id)
        if section is None:
            return _Outcome(
                "unverified",
                "unknown_document",
                f"no memory document {document_id!r} is recorded in the ledger",
            )
        source = section.source
        claimed_version = memory.metadata.get("source_version_id")
        claimed_anchor = memory.metadata.get("section_anchor", source.section_anchor)
        if claimed_version != str(source.source_version_id) or (
            claimed_anchor != source.section_anchor
        ):
            return _Outcome(
                "unverified",
                "metadata_mismatch",
                f"the memory's metadata (source_version_id={claimed_version!r},"
                f" section_anchor={claimed_anchor!r}) disagrees with the ledger's"
                f" {source.source_version_id}/{source.section_anchor}",
            )
        return _Outcome("resolved", sources=[source])

    def _section(self, document_id: str, memory_id: str) -> _Section | None:
        with self._engine.connect() as connection:
            row = self._sections(connection, document_id)
        if row is None:
            return None
        self._uris[row["source_version_id"]] = row["parsed_object_uri"]
        source = CitationSource(
            memory_id=memory_id,
            document_id=row["hindsight_document_id"],
            source_version_id=row["source_version_id"],
            source_document_id=row["source_document_id"],
            company_id=row["company_id"],
            form_type=row["form_type"],
            section_anchor=row["section_anchor"],
            section_heading=row["section_heading"],
            section_char_start=row["char_start"],
            section_char_end=row["char_end"],
            available_at=row["available_at"],
            available_at_basis=row["available_at_basis"],
        )
        return _Section(source, row["parsed_object_uri"])

    # --- quotes --------------------------------------------------------------------------------

    def _quotes(self, answer: str, cited: Sequence[Citation]) -> list[Citation]:
        sections: list[tuple[Citation, CitationSource]] = []
        seen: set[tuple[uuid.UUID, str]] = set()
        for citation in cited:
            if citation.state != "resolved":
                continue
            for source in citation.sources:
                key = (source.source_version_id, source.section_anchor)
                if key not in seen:
                    seen.add(key)
                    sections.append((citation, source))
        quotes: list[Citation] = []
        for quote in extract_quotes(answer):
            quotes.append(self._quote(quote, sections))
        return quotes

    def _quote(self, quote: str, sections: Sequence[tuple[Citation, CitationSource]]) -> Citation:
        for citation, source in sections:
            parsed = self._parsed_text(source.source_version_id)
            if parsed is None:
                continue
            section = parsed[source.section_char_start : source.section_char_end]
            span = find_quote(quote, section, offset=source.section_char_start)
            if span is None:
                continue
            start, end = span
            return Citation(
                kind="quote",
                state="resolved",
                reason=None,
                detail=None,
                memory_id=citation.memory_id,
                memory_type=citation.memory_type,
                text=quote,
                sources=[source],
                missing_memory_ids=[],
                quote=QuoteSpan(
                    quoted=quote,
                    source_version_id=source.source_version_id,
                    char_start=start,
                    char_end=end,
                    archived_text=parsed[start:end],
                ),
            )
        where = (
            f"any of the {len(sections)} cited sections"
            if sections
            else "a cited section (no citation resolved to one)"
        )
        return Citation(
            kind="quote",
            state="unverified",
            reason="quote_mismatch",
            detail=f"the quote does not occur in the archived parsed text of {where}",
            memory_id=None,
            memory_type=None,
            text=quote,
            sources=[],
            missing_memory_ids=[],
            quote=None,
        )

    def _parsed_text(self, version_id: uuid.UUID) -> str | None:
        if version_id not in self._parsed:
            uri = self._uris.get(version_id)
            self._parsed[version_id] = (
                None if uri is None else self._archive.get(uri).decode("utf-8")
            )
        return self._parsed[version_id]


def _as_memory(cited: CitedMemory) -> Memory:
    """A cited fact as the memory it names (the fields a fact's resolution reads)."""
    return Memory(
        id=cited.id or "",
        text=cited.text,
        type=cited.type or "world",
        context=cited.context,
        document_id=cited.document_id,
        chunk_id=cited.chunk_id,
        tags=cited.tags,
        metadata=cited.metadata,
        occurred_start=cited.occurred_start,
        occurred_end=cited.occurred_end,
        mentioned_at=cited.mentioned_at,
    )


def _citation(
    kind: CitationKind,
    outcome: _Outcome,
    memory_id: str | None,
    memory_type: str | None,
    text: str,
) -> Citation:
    return Citation(
        kind=kind,
        state=outcome.state,
        reason=outcome.reason,
        detail=outcome.detail,
        memory_id=memory_id,
        memory_type=memory_type,
        text=text,
        sources=outcome.sources if outcome.state == "resolved" else [],
        missing_memory_ids=outcome.missing,
        quote=None,
    )
