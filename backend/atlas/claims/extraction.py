"""Claim extraction: the Investigator reads archived parsed text and proposes Claims; the
ones whose span and form check out become Assertions, the rest are recorded as rejected.

An `extract_claims` job names Source Versions (and optionally a question). One attempt:

1. **Passages** (`atlas.claims.selection`; memory-directed reading ticket 05). Each Source
   Version's parsed text is split into sections by the retention sectioner (so a section here
   is a memory document's section there), and each section into windows of at most
   `PASSAGE_CHARS` (3,000) characters, cut at line breaks. A window is a candidate when a
   selection chooses it: a **reading pointer** into the document (`pointer:<query_index>`:
   the window of the pointed section that best matches the pointer's Memory text; only inside
   an investigation, which passes its round's pointers and Scout queries as the `reading`), the
   **search** (`search`: it contains a term of the question or of the Scout's queries, scored
   by BM25), or an **entity tag** (`entity:<company_id>`: it names a known company other than
   the document's own); a document with no such window offers its **lead** windows instead
   (`lead`; its results sections first: a 10-Q's or 10-K's MD&A, an 8-K's Item 2.02). A
   window several selections choose is one passage recording them all. The `max_passages`
   budget is dealt across the documents by two channels in turn: one pointer window (by
   rank), then one search or entity window (by score), and so on, then lead windows; each
   periodic report, results release and results-call transcript with a candidate keeps one
   passage, and one document takes at most `max_document_share` of the budget while others
   have candidates. The extraction asks Memory nothing itself: no recall
   is made here. Pointer, search and entity candidates not sent are counted as dropped. The
   choice is stored with the extraction, so a resumed job sends the same passages; the job's
   artifacts count them per document (`passages_by_document`) and per kind of selection
   (`passages_by_selection`), and each Claim's read says which selections chose its passage.
2. **Calls.** Passages go to the Investigator `passages_per_call` at a time, within the
   extraction's run (its own `claim_extraction` run, or the caller's `run_id`). Each call is
   a batch; progress is stored per batch, so a job requeued by an LLM outage or quota
   resumes at the next batch in the same run. A quarantined answer counts as a batch with no
   Claims. When the run's token budget is spent, the extraction stops `budget_exhausted`.
3. **Checks**, per proposed Claim, in this order (the first failure is the rejection):
   the predicate is whitelisted (`predicate_not_whitelisted`); the layer, when one is
   proposed, is known (`unknown_layer`); the passage was sent in that call
   (`unknown_passage`); the subject and
   a company object are known companies (`unknown_company`), a product object is named
   (`missing_object`) and subject and object differ (`self_relationship`). **A company object
   may instead be named** (`object_name`, for a company outside the known ones): the quote
   must contain that name (`party_not_in_quote`), and the name must resolve to one company
   (`atlas.counterparties`: a company Atlas has, else exactly one SEC registrant or GLEIF
   record of that name; otherwise `unresolved_company` or `ambiguous_company`, as is every
   unknown name when entity resolution isn't configured). Then: the offsets lie
   inside the passage (`quote_outside_passage`); **the quote is placed**: if it is not
   exactly the text at the model's offsets it is searched for in the passage as an exact
   substring, and its one occurrence gives the span (`offset_source` `located`, else `model`;
   the model's offsets stay in `proposed`); a quote with no exact occurrence is tried again
   through the **typographic fold** (`atlas.claims.fold`: hyphens and dashes, curly quotation
   marks, no-break and narrow spaces, one character to one character; never whitespace runs,
   case or words), at the model's offsets and then by search (`offset_source` `folded`); no
   occurrence is `quote_mismatch` and more than one `quote_ambiguous`. From here on **the
   quote is the archived text at the span**: that is what the Claim and the Assertion store
   and what every later check reads (the model's spelling stays in `proposed`). **The
   Assertion span check** then runs on the final span (`quote_mismatch`); the quote names
   both parties (`party_not_in_quote`), **or leaves the filer unnamed** in a sentence of the
   filer's own document that names the other party (a company object) or the object product
   and no other company (`party_basis` `filer`, else `named`; a sentence naming another
   company besides is co-mention and stays `party_not_in_quote`); it uses language
   expressing the predicate (`no_directional_language`; co-mention is not a relation); and
   its wording doesn't give the relation the other way round (`wrong_direction`: `owns` runs
   from the holder of issued or purchased shares to their issuer, and the company whose
   purchase commitment it is is the buyer). A bottleneck predicate's product object must be
   named in the quote (`object_not_in_quote`) and be a particular input or product, not
   generic materials, components or capacity (`generic_object`); and for any product object
   the cue must be in a clause that names the object (`cue_in_other_clause`, pilot-fixes
   ticket 09). See `atlas.claims.predicates`.
   **The layer is not a check** (memory-directed reading ticket 08): a Claim may propose
   none, and a proposed layer is kept only when one of its taxonomy terms occurs in the object
   text or the quote (`atlas.claims.layer_term`; the Claim records the term, `layer_term`).
   Otherwise the accepted Claim and its Assertion have no layer and the Claim records why
   (`layer_reason` `layer_unsupported`; the proposal stays in `proposed`): "expanding our
   indium phosphide capacity in Sherman, Texas" proposed as `substrate` is accepted with no
   layer, and so is an ownership stake proposed with the question's layer.
4. **Outcome.** A Claim that passes becomes an Assertion (`extractor_version`
   `investigator.v<N>`, created by `atlas-investigator`, `value_json` holding the claim ID,
   layer, product and product object), recorded with its `claim` row in one transaction. A
   named company Atlas didn't have becomes a **counterparty company** in that transaction,
   only now that every check has passed (audited `company.counterparty_created`), and is a
   known company from the next batch on. Names are resolved before the transaction (the
   registries are network calls), once per name and extractor.
   Every Claim, accepted or rejected, is a `claim` row and an audit event (`claim.accepted`,
   `claim.rejected`). Nothing is ever inferred from a Claim: a `supplies` Claim is one
   `supplies` Assertion, never also a `buys_from`.

**The parse read** (pilot-fixes ticket 11). Each Source Version is read in its **current
parse**: its re-parse under the current parser (`source_parse`) when it has one with text,
else the parse it was recorded with. Each passage records that parse's `parser_version`, a
resumed or continued extraction reads the parse its passages name, and each Claim and its
Assertion record it: a span is checked against the parse it was made on, and only that one.

**Continuing.** An extraction that stopped `budget_exhausted` is finished; a new job whose
payload names it in `continues` (in the same, still unfinished run) sends only its remaining
passages, from its next batch on, so a resumed investigation never proposes from a passage
twice.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.archive import Archive
from atlas.assertions import AssertionCreate, Assertions, InvalidAssertion, check_quote
from atlas.audit import Actor, content_hash, record
from atlas.claims.predicates import (
    BOTTLENECK_PREDICATES,
    LAYER_NAMES,
    LAYERS,
    PREDICATES,
    company_names,
    direction_refusal,
    directional_cue,
    fold,
    is_generic_object,
    layer_term,
    mentions,
    names_object,
    names_party,
    object_clause_cue,
    predicate_refusal,
    stray_companies,
)
from atlas.claims.reads import ClaimExtraction, Passage, SkippedVersion, get_extraction
from atlas.claims.selection import Document, Reading, ceiling, select, selections
from atlas.counterparties import (
    NamedCompany,
    NewCounterparty,
    ensure_counterparty,
    resolve_named_company,
)
from atlas.identity import EntityResolver
from atlas.identity.normalize import normalize_name
from atlas.jobs.queue import Artifacts, Job
from atlas.ledger.reads import current_parse, get_parse
from atlas.roles import (
    QuotedText,
    RoleCaller,
    RoleCallFailed,
    RoleOutputQuarantined,
    TokenBudgetExhausted,
    run_usage,
)
from atlas.roles.contract import Role
from atlas.roles.investigator import (
    INVESTIGATOR,
    INVESTIGATOR_PROMPT_VERSION,
    InvestigatorClaims,
    InvestigatorRequest,
    KnownCompany,
    LayerOption,
    PassageInfo,
    PredicateDefinition,
    ProposedClaim,
)
from atlas.runs import RunNotFound, RunRecorder

EXTRACT_CLAIMS_KIND = "extract_claims"
EXTRACTOR_VERSION = f"investigator.v{INVESTIGATOR_PROMPT_VERSION}"
INVESTIGATOR_ACTOR = Actor("atlas-investigator")
RUN_KIND = "claim_extraction"
MAX_SOURCE_VERSIONS = 25  # the spec's per-run bound on fetched documents
# One document's largest share of the passage budget while others have candidates.
MAX_DOCUMENT_SHARE = 1 / 3
_PARSED = ("parsed", "incomplete")


class ExtractClaimsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_version_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_SOURCE_VERSIONS)
    question: str | None = Field(default=None, min_length=1, max_length=4000)
    run_id: uuid.UUID | None = Field(
        default=None, description="an unfinished run to call within; else the job starts one"
    )
    continues: uuid.UUID | None = Field(
        default=None,
        description="a budget-exhausted extraction in `run_id` to continue: its remaining"
        " passages only",
    )


def extract_claims_payload(
    source_version_ids: Sequence[uuid.UUID], question: str | None = None
) -> dict[str, Any]:
    return ExtractClaimsPayload(
        source_version_ids=list(source_version_ids), question=question
    ).model_dump(mode="json", exclude_none=True)


@dataclass(frozen=True)
class _Version:
    """A Source Version as read: `parse_status`, `parsed_object_uri` and `parser_version` are
    those of the parse read (the current one, or the one its passages name)."""

    id: uuid.UUID
    parse_status: str
    parsed_object_uri: str | None
    title: str
    form_type: str | None
    document_type: str | None
    company_id: uuid.UUID | None
    parser_version: str | None = None
    items: tuple[str, ...] = ()  # its filing's 8-K Items ("2.02", "9.01"), when recorded
    provider: str | None = None  # its Source Document's provider (`tradingview`: a transcript)


@dataclass(frozen=True)
class _Company:
    id: uuid.UUID
    names: list[str]


@dataclass(frozen=True)
class _Judged:
    """A Claim's resolved fields and outcome (`reason_code` None: accepted)."""

    source_version_id: uuid.UUID | None
    subject_company_id: uuid.UUID | None
    object_company_id: uuid.UUID | None
    span: tuple[int, int] | None
    cue: str | None
    assertion: AssertionCreate | None
    reason_code: str | None = None
    reason: str | None = None
    offset_source: str | None = None  # `model`, `located` or `folded`, once the quote is placed
    # The archived text at the span, once the quote is placed (the Claim's and the Assertion's
    # quote; the model's spelling stays in `proposed`).
    quote: str | None = None
    # How the quote identifies the parties, once it does: `named`, or `filer` when the filer
    # is the unnamed party of its own impersonal sentence.
    party_basis: str | None = None
    # The layer an accepted Claim keeps: the proposed one when a term of it (`layer_term`)
    # occurs in the object text or the quote; else None, with `layer_reason`
    # `layer_unsupported` when one was proposed.
    layer: str | None = None
    layer_term: str | None = None
    layer_reason: str | None = None
    # The named object company Atlas doesn't have yet: created when the Claim is accepted.
    counterparty: NewCounterparty | None = None


class ClaimExtractor:
    def __init__(
        self,
        engine: Engine,
        archive: Archive,
        caller: RoleCaller,
        runs: RunRecorder | None,
        *,
        max_passages: int,
        passages_per_call: int,
        max_document_share: float = MAX_DOCUMENT_SHARE,
        investigator: Role[InvestigatorRequest, InvestigatorClaims] = INVESTIGATOR,
        resolver: EntityResolver | None = None,
        ignored_ciks: frozenset[str] = frozenset(),
    ) -> None:
        """`max_passages` is the passage budget and `max_document_share` the share of it one
        document may take while others have candidates (atlas.claims.selection).
        `investigator` is the role called: the committed prompt, or a variant under
        measurement (`scripts/investigator_replay.py`); its prompt names the Assertions'
        `extractor_version`. `resolver` identifies a company object given by name (with the
        configured companies' `ignored_ciks`); without one, a name that is none of Atlas's
        companies is rejected as unresolved."""
        self._engine = engine
        self._archive = archive
        self._caller = caller
        self._runs = runs
        self._max_passages = max_passages
        self._max_document_share = max_document_share
        self._passages_per_call = passages_per_call
        self._investigator = investigator
        self._extractor_version = f"{investigator.prompt.name}.v{investigator.prompt.version}"
        self._resolver = resolver
        self._ignored_ciks = ignored_ciks
        self._assertions = Assertions(engine, archive, INVESTIGATOR_ACTOR)
        self._texts: dict[str, str] = {}  # by parsed object URI
        self._named: dict[str, NamedCompany] = {}  # by normalized name

    def extract(
        self,
        job: Job,
        payload: ExtractClaimsPayload | None = None,
        reading: Reading | None = None,
    ) -> Artifacts:
        """Run (or resume) the extraction of `job`: its payload's, or `payload` when a caller
        runs an extraction within its own job (an investigation's Investigator task), which
        also passes what directs the `reading` of the documents (the round's reading pointers
        into them and the Scout's queries); they choose passages when the extraction starts."""
        payload = payload or ExtractClaimsPayload.model_validate(job.payload)
        extraction = self._existing(job.id) or self._start(job.id, payload, reading)
        owned = payload.run_id is None
        if extraction.status != "running":
            return _artifacts(extraction)
        # The parse each version's passages were cut from (None: the recorded parse).
        pins = {p.source_version_id: p.parser_version for p in extraction.passages}
        versions = {
            version.id: version for version in self._versions(extraction.source_version_ids, pins)
        }
        size = extraction.passages_per_call
        batches = [
            extraction.passages[start : start + size]
            for start in range(0, len(extraction.passages), size)
        ]
        for index in range(extraction.batches_done, len(batches)):
            batch = batches[index]
            # Read per batch: a counterparty an earlier batch created is a known company now.
            companies = self._companies()
            request, retrieved = self._request(extraction.question, batch, versions, companies)
            try:
                output, role_call_id = self._caller.call_recorded(
                    self._investigator, request, run_id=extraction.run_id, retrieved=retrieved
                )
            except TokenBudgetExhausted:
                return self._finish(extraction, "budget_exhausted", owned=owned)
            except RoleOutputQuarantined:
                self._record(extraction, index, [], None, versions, companies, quarantined=True)
                continue
            claims = [(proposed, batch) for proposed in output.claims]
            self._resolve_named(output.claims, companies)  # before the transaction: network
            self._record(extraction, index, claims, role_call_id, versions, companies)
        return self._finish(extraction, "completed", owned=owned)

    # --- starting: passages and the run ---------------------------------------------------------

    def _existing(self, job_id: uuid.UUID) -> ClaimExtraction | None:
        with self._engine.connect() as connection:
            found = connection.execute(
                text("SELECT id FROM claim_extraction WHERE job_id = :job"), {"job": job_id}
            ).scalar_one_or_none()
            return None if found is None else get_extraction(connection, found)

    def _start(
        self, job_id: uuid.UUID, payload: ExtractClaimsPayload, reading: Reading | None
    ) -> ClaimExtraction:
        if payload.continues is not None:
            return self._continue(job_id, payload, payload.continues)
        requested = list(dict.fromkeys(payload.source_version_ids))
        found = {version.id: version for version in self._versions(requested)}
        skipped: list[SkippedVersion] = []
        usable: list[_Version] = []
        for version_id in requested:
            version = found.get(version_id)
            if version is None:
                skipped.append(SkippedVersion(source_version_id=version_id, reason="not found"))
            elif version.parse_status not in _PARSED or version.parsed_object_uri is None:
                reason = f"no parsed text (parse status {version.parse_status})"
                skipped.append(SkippedVersion(source_version_id=version_id, reason=reason))
            else:
                usable.append(version)
        passages, dropped = self._select(usable, self._companies(), payload.question, reading)
        passages = [
            passage.model_copy(
                update={"parser_version": found[passage.source_version_id].parser_version}
            )
            for passage in passages
        ]
        run_id = self._run_for(payload)
        extraction_id = uuid.uuid4()
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO claim_extraction (id, job_id, run_id, source_version_ids,"
                    " question, passages, passages_dropped, skipped, passages_per_call,"
                    " batches_total) VALUES (:id, :job, :run, :versions, :question,"
                    " CAST(:passages AS jsonb), :dropped, CAST(:skipped AS jsonb), :per_call,"
                    " :batches)"
                ),
                {
                    "id": extraction_id,
                    "job": job_id,
                    "run": run_id,
                    "versions": requested,
                    "question": payload.question,
                    "passages": json.dumps([p.model_dump(mode="json") for p in passages]),
                    "dropped": dropped,
                    "skipped": json.dumps([s.model_dump(mode="json") for s in skipped]),
                    "per_call": self._passages_per_call,
                    "batches": -(-len(passages) // self._passages_per_call),
                },
            )
            extraction = get_extraction(connection, extraction_id)
        assert extraction is not None
        return extraction

    def _continue(
        self, job_id: uuid.UUID, payload: ExtractClaimsPayload, continued_id: uuid.UUID
    ) -> ClaimExtraction:
        with self._engine.connect() as connection:
            earlier = get_extraction(connection, continued_id)
        if earlier is None or earlier.status != "budget_exhausted":
            raise RoleCallFailed(f"no budget-exhausted extraction {continued_id} to continue")
        if payload.run_id != earlier.run_id:
            raise RoleCallFailed(f"extraction {continued_id} continues only in its run")
        self._run_for(payload)  # the run must still be unfinished
        remaining = earlier.passages[earlier.batches_done * earlier.passages_per_call :]
        extraction_id = uuid.uuid4()
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO claim_extraction (id, job_id, run_id, source_version_ids,"
                    " question, passages, passages_per_call, batches_total, continues_id)"
                    " VALUES (:id, :job, :run, :versions, :question, CAST(:passages AS jsonb),"
                    " :per_call, :batches, :continues)"
                ),
                {
                    "id": extraction_id,
                    "job": job_id,
                    "run": earlier.run_id,
                    "versions": earlier.source_version_ids,
                    "question": earlier.question,
                    "passages": json.dumps([p.model_dump(mode="json") for p in remaining]),
                    "per_call": earlier.passages_per_call,
                    "batches": -(-len(remaining) // earlier.passages_per_call),
                    "continues": continued_id,
                },
            )
            extraction = get_extraction(connection, extraction_id)
        assert extraction is not None
        return extraction

    def _run_for(self, payload: ExtractClaimsPayload) -> uuid.UUID:
        if payload.run_id is not None:
            with self._engine.connect() as connection:
                open_run = connection.execute(
                    text("SELECT 1 FROM run WHERE id = :id AND finished_at IS NULL"),
                    {"id": payload.run_id},
                ).one_or_none()
            if open_run is None:
                raise RoleCallFailed(f"no unfinished run {payload.run_id} to extract claims in")
            return payload.run_id
        if self._runs is None:
            raise RoleCallFailed(
                "claim extraction records a run: it needs LiteLLM and Hindsight configured"
            )
        return self._runs.start(RUN_KIND).id

    def _select(
        self,
        versions: Sequence[_Version],
        companies: Sequence[_Company],
        question: str | None,
        reading: Reading | None,
    ) -> tuple[list[Passage], int]:
        """The passages, in reading order (atlas.claims.selection: pointer, search, entity and
        lead windows of the documents, in the documents' order, dealt within the budget,
        pointer and search windows alternately, with a floor for reports, results releases
        and call transcripts and a ceiling per document); and how many pointer, search and
        entity candidates were not sent."""
        chosen = select(
            [
                Document(
                    id=version.id,
                    text=self._text(version),
                    form_type=version.form_type,
                    document_type=version.document_type,
                    items=version.items,
                    company_id=version.company_id,
                    provider=version.provider,
                )
                for version in versions
            ],
            entities=[(company.id, company.names) for company in companies],
            question=question,
            reading=reading,
            budget=self._max_passages,
            ceiling=ceiling(self._max_passages, self._max_document_share),
        )
        passages = [
            Passage(
                id=f"p{index + 1}",
                source_version_id=each.source_version_id,
                section_anchor=each.section_anchor,
                char_start=each.char_start,
                char_end=each.char_end,
                selected_by=each.selected_by,
            )
            for index, each in enumerate(chosen.passages)
        ]
        return passages, chosen.dropped

    # --- calls ----------------------------------------------------------------------------------

    def _request(
        self,
        question: str | None,
        batch: Sequence[Passage],
        versions: dict[uuid.UUID, _Version],
        companies: Sequence[_Company],
    ) -> tuple[InvestigatorRequest, list[QuotedText]]:
        request = InvestigatorRequest(
            question=question,
            companies=[KnownCompany(company_id=str(c.id), names=c.names) for c in companies],
            predicates=[
                PredicateDefinition(name=p.name, object=p.object_kind, reads=p.reads)
                for p in PREDICATES.values()
            ],
            layers=[
                LayerOption(name=layer.name, covers=layer.covers, terms=list(layer.terms))
                for layer in LAYERS
            ],
            passages=[
                PassageInfo(
                    passage_id=passage.id,
                    source_version_id=str(passage.source_version_id),
                    filer_company_id=_str(versions[passage.source_version_id].company_id),
                    title=versions[passage.source_version_id].title,
                    section=passage.section_anchor,
                )
                for passage in batch
            ],
        )
        retrieved = [
            QuotedText(
                id=passage.id,
                source=f"{passage.source_version_id}#{passage.char_start}-{passage.char_end}",
                text=self._text(versions[passage.source_version_id])[
                    passage.char_start : passage.char_end
                ],
            )
            for passage in batch
        ]
        return request, retrieved

    # --- outcomes -------------------------------------------------------------------------------

    def _resolve_named(
        self, claims: Sequence[ProposedClaim], companies: Sequence[_Company]
    ) -> None:
        """Resolve each company object the Claims give by name (once per name; the registries
        are asked only for a name the quote contains and Atlas doesn't have)."""
        known = {str(company.id) for company in companies}
        for proposed in claims:
            rule = PREDICATES.get(proposed.predicate)
            name = (proposed.object_name or "").strip()
            key = normalize_name(name)
            if (
                rule is None
                or rule.object_kind != "company"
                or not name
                or proposed.object_company_id in known
                or key in self._named
                or not mentions(fold(proposed.quote), [fold(name)])
            ):
                continue
            with self._engine.connect() as connection:
                self._named[key] = resolve_named_company(
                    connection, self._resolver, name, ignored_ciks=self._ignored_ciks
                )

    def _record(
        self,
        extraction: ClaimExtraction,
        index: int,
        claims: Sequence[tuple[ProposedClaim, Sequence[Passage]]],
        role_call_id: uuid.UUID | None,
        versions: dict[uuid.UUID, _Version],
        companies: Sequence[_Company],
        *,
        quarantined: bool = False,
    ) -> None:
        """Record one batch's Claims and advance the extraction, in one transaction."""
        with self._engine.begin() as connection:
            done = connection.execute(
                text("SELECT batches_done FROM claim_extraction WHERE id = :id FOR UPDATE"),
                {"id": extraction.id},
            ).scalar_one()
            if done != index:
                return  # recorded by an earlier attempt
            for ordinal, (proposed, batch) in enumerate(claims):
                assert role_call_id is not None
                self._record_claim(
                    connection,
                    extraction,
                    role_call_id,
                    ordinal,
                    proposed,
                    {passage.id: passage for passage in batch},
                    versions,
                    companies,
                )
            connection.execute(
                text(
                    "UPDATE claim_extraction SET batches_done = batches_done + 1,"
                    " batches_quarantined = batches_quarantined + :quarantined WHERE id = :id"
                ),
                {"id": extraction.id, "quarantined": int(quarantined)},
            )

    def _record_claim(
        self,
        connection: Connection,
        extraction: ClaimExtraction,
        role_call_id: uuid.UUID,
        ordinal: int,
        proposed: ProposedClaim,
        passages: dict[str, Passage],
        versions: dict[uuid.UUID, _Version],
        companies: Sequence[_Company],
    ) -> None:
        claim_id = uuid.uuid4()
        judged = self._judge(claim_id, proposed, passages, versions, companies)
        assertion_id: uuid.UUID | None = None
        if judged.assertion is not None:
            counterparty_id: uuid.UUID | None = None
            try:
                # One savepoint: a refused Assertion leaves no counterparty behind.
                with connection.begin_nested():
                    assertion = judged.assertion
                    if judged.counterparty is not None:
                        counterparty_id = ensure_counterparty(
                            connection, INVESTIGATOR_ACTOR, judged.counterparty
                        )
                        assertion = assertion.model_copy(
                            update={"object_company_id": counterparty_id}
                        )
                    recorded = self._assertions.create_within(
                        connection, assertion, extractor_version=self._extractor_version
                    )
                assertion_id = recorded.assertion.id
                if counterparty_id is not None:
                    judged = replace(judged, object_company_id=counterparty_id)
            except InvalidAssertion as refusal:
                judged = _reject(judged, refusal.code, refusal.message)
        accepted = assertion_id is not None
        row = (
            connection.execute(
                text(
                    "INSERT INTO claim (id, extraction_id, run_id, role_call_id, ordinal,"
                    " proposed, passage_id, source_version_id, subject_company_id, predicate,"
                    " object_company_id, object_text, product, layer, quote, span_start,"
                    " span_end, epistemic_type, directional_cue, outcome, reason_code, reason,"
                    " assertion_id, offset_source, parser_version, party_basis, layer_term,"
                    " layer_reason) VALUES (:id, :extraction,"
                    " :run, :role_call, :ordinal, CAST(:proposed AS jsonb), :passage, :version,"
                    " :subject, :predicate, :object, :object_text, :product, :layer, :quote,"
                    " :span_start, :span_end, :epistemic_type, :cue, :outcome, :reason_code,"
                    " :reason, :assertion, :offset_source, :parser_version, :party_basis,"
                    " :layer_term, :layer_reason) RETURNING *"
                ),
                {
                    "id": claim_id,
                    "extraction": extraction.id,
                    "run": extraction.run_id,
                    "role_call": role_call_id,
                    "ordinal": ordinal,
                    "proposed": json.dumps(proposed.model_dump(mode="json")),
                    "passage": proposed.passage_id,
                    "version": judged.source_version_id,
                    "subject": judged.subject_company_id,
                    "predicate": proposed.predicate,
                    "object": judged.object_company_id,
                    "object_text": proposed.object_text,
                    "product": proposed.product,
                    # An accepted Claim's layer is the supported one; a rejected Claim keeps
                    # what was proposed.
                    "layer": judged.layer if accepted else _proposed_layer(proposed),
                    "layer_term": judged.layer_term if accepted else None,
                    "layer_reason": judged.layer_reason if accepted else None,
                    "quote": judged.quote if judged.quote is not None else proposed.quote,
                    "span_start": judged.span[0] if judged.span else None,
                    "span_end": judged.span[1] if judged.span else None,
                    "epistemic_type": proposed.epistemic_type,
                    "cue": judged.cue,
                    "outcome": "accepted" if accepted else "rejected",
                    "reason_code": judged.reason_code,
                    "reason": judged.reason,
                    "assertion": assertion_id,
                    "offset_source": judged.offset_source,
                    "parser_version": _parser_version(versions, judged.source_version_id),
                    "party_basis": judged.party_basis,
                },
            )
            .mappings()
            .one()
        )
        record(
            connection,
            INVESTIGATOR_ACTOR,
            "claim.accepted" if accepted else "claim.rejected",
            entity_type="claim",
            entity_id=str(claim_id),
            new_hash=content_hash(dict(row)),
        )

    def _judge(
        self,
        claim_id: uuid.UUID,
        proposed: ProposedClaim,
        passages: dict[str, Passage],
        versions: dict[uuid.UUID, _Version],
        companies: Sequence[_Company],
    ) -> _Judged:
        by_id = {str(company.id): company for company in companies}
        passage = passages.get(proposed.passage_id)
        subject = by_id.get(proposed.subject_company_id)
        target = by_id.get(proposed.object_company_id or "")
        object_id = target.id if target else None
        object_names = target.names if target else []
        counterparty: NewCounterparty | None = None
        span: tuple[int, int] | None = None
        if passage is not None and 0 <= proposed.quote_start <= proposed.quote_end:
            span = (
                passage.char_start + proposed.quote_start,
                passage.char_start + proposed.quote_end,
            )
        judged = _Judged(
            source_version_id=passage.source_version_id if passage else None,
            subject_company_id=subject.id if subject else None,
            object_company_id=target.id if target else None,
            span=span,
            cue=None,
            assertion=None,
        )
        if (refusal := predicate_refusal(proposed.predicate)) is not None:
            return _reject(judged, "predicate_not_whitelisted", refusal)
        rule = PREDICATES[proposed.predicate]
        proposed_layer = _proposed_layer(proposed)
        if proposed_layer is not None and proposed_layer not in LAYER_NAMES:
            layers = ", ".join(layer.name for layer in LAYERS)
            return _reject(
                judged,
                "unknown_layer",
                f"{proposed.layer!r} is not a layer; the layers are {layers}",
            )
        if passage is None or span is None:
            if passage is None:
                message = f"passage {proposed.passage_id!r} was not sent in this call"
                return _reject(judged, "unknown_passage", message)
            return _reject(
                judged, "quote_outside_passage", "the quote's offsets are negative or reversed"
            )
        if subject is None:
            message = f"subject {proposed.subject_company_id!r} is not a known company ID"
            return _reject(judged, "unknown_company", message)
        if rule.object_kind == "company":
            name = (proposed.object_name or "").strip()
            if target is None and name:
                # A company outside the known ones, by the name the quote uses for it.
                if not mentions(fold(proposed.quote), [fold(name)]):
                    message = f"the quote doesn't name the object ({name}, its `object_name`)"
                    return _reject(judged, "party_not_in_quote", message)
                named = self._named[normalize_name(name)]
                if named.refusal is not None:
                    return _reject(judged, *named.refusal)
                object_id, counterparty, object_names = named.company_id, named.new, [name]
                judged = replace(judged, object_company_id=object_id)
            elif not proposed.object_company_id:
                message = (
                    f"{rule.name} needs object_company_id or object_name: its object is a company"
                )
                return _reject(judged, "missing_object", message)
            elif target is None:
                message = f"object {proposed.object_company_id!r} is not a known company ID"
                return _reject(judged, "unknown_company", message)
            if object_id == subject.id:
                return _reject(judged, "self_relationship", "subject and object are one company")
        elif not (proposed.object_text or "").strip():
            message = (
                f"{rule.name} needs object_text: its object is a product, material or technology"
            )
            return _reject(judged, "missing_object", message)
        length = passage.char_end - passage.char_start
        if proposed.quote_end > length:
            message = (
                f"the offsets [{proposed.quote_start}, {proposed.quote_end}) run past the end of"
                f" passage {passage.id} ({length} characters)"
            )
            return _reject(judged, "quote_outside_passage", message)
        version = versions[passage.source_version_id]
        placed = _place(self._text(version), passage, proposed)
        if isinstance(placed, str):
            return _reject(judged, "quote_ambiguous", placed)
        offset_source: str | None = None
        # The quote every later check reads, and the Claim and its Assertion store: the
        # archived text at the span, which the fold may spell otherwise than the model did.
        quote = proposed.quote
        if placed is not None:
            span, offset_source = placed.span, placed.source
            quote = self._text(version)[span[0] : span[1]]
        object_text = (proposed.object_text or "").strip()
        # The layer is kept only when the object text or the quote names it.
        supporting: str | None = None
        if proposed_layer is not None:
            supporting = layer_term(
                proposed_layer, quote, object_text if rule.object_kind == "product" else None
            )
        layer = proposed_layer if supporting is not None else None
        layer_reason = "layer_unsupported" if layer is None and proposed_layer else None
        try:
            assertion = AssertionCreate(
                subject_company_id=subject.id,
                predicate=rule.name,
                # A counterparty not yet created gets its ID when the Claim is recorded.
                object_company_id=object_id if rule.object_kind == "company" else None,
                value_json={
                    "claim_id": str(claim_id),
                    "layer": layer,
                    "product": proposed.product,
                    "object_text": proposed.object_text if rule.object_kind == "product" else None,
                },
                source_version_id=version.id,
                quote=quote,
                span_start=span[0],
                span_end=span[1],
                page_or_anchor=passage.section_anchor,
                epistemic_type=proposed.epistemic_type,
                parser_version=version.parser_version,
            )
            check_quote(self._text(version), assertion)
        except ValidationError as error:
            return _reject(judged, "invalid_claim", _first_error(error))
        except InvalidAssertion as refusal:
            return _reject(judged, refusal.code, refusal.message)
        parties: list[tuple[str, Sequence[str]]] = [("subject", subject.names)]
        if rule.object_kind == "company":
            parties.append(("object", object_names))
        filer: Literal["subject", "object"] | None = None
        if subject.id == version.company_id:
            filer = "subject"
        elif rule.object_kind == "company" and object_id == version.company_id:
            filer = "object"
        party_basis = "named"
        for role, names in parties:
            if names_party(quote, names, is_filer=role == filer):
                continue
            if role != filer:
                message = f"the quote doesn't name the {role} ({names[0]})"
                return _reject(judged, "party_not_in_quote", message)
            # The filer, unnamed in an impersonal sentence or slide bullet of its own document.
            unnamed = _unnamed_filer_refusal(
                quote,
                role,
                names,
                counterparty=next((other for each, other in parties if each != role), None),
                object_text=object_text,
                others=[c.names for c in companies if c.id not in (subject.id, object_id)],
            )
            if unnamed is not None:
                return _reject(judged, "party_not_in_quote", unnamed)
            party_basis = "filer"
        cue = directional_cue(rule.name, quote)
        if cue is None:
            message = (
                f"the quote has no language expressing {rule.name} ({rule.reads});"
                " naming companies together is not a relation"
            )
            return _reject(judged, "no_directional_language", message)
        if rule.object_kind == "company":
            reversed_ = direction_refusal(
                rule.name, quote, subject.names, object_names, filer=filer
            )
            if reversed_ is not None:
                return _reject(judged, "wrong_direction", reversed_)
        if rule.object_kind == "product":
            if rule.name in BOTTLENECK_PREDICATES:
                if not names_object(quote, object_text):
                    message = (
                        f"{rule.name} needs the input or product named in the quote, and the"
                        f" quote doesn't contain {object_text!r} (its `object_text`)"
                    )
                    return _reject(judged, "object_not_in_quote", message)
                if is_generic_object(object_text):
                    tagged = f"layer {proposed_layer!r}" if proposed_layer else "any layer"
                    message = (
                        f"{object_text!r} names no particular input or product, so the quote"
                        f" shows nothing of {tagged}: generic materials,"
                        " components or suppliers are no Claim, and a Claim's layer is the"
                        " layer of the object its quote names"
                    )
                    return _reject(judged, "generic_object", message)
            cue = object_clause_cue(rule.name, quote, object_text)
            if cue is None:
                message = (
                    f"the words expressing {rule.name} are in another clause than the"
                    f" object ({object_text}): a verb in a neighbouring clause is no cue"
                )
                return _reject(judged, "cue_in_other_clause", message)
        return _Judged(
            source_version_id=version.id,
            subject_company_id=subject.id,
            object_company_id=judged.object_company_id,
            span=span,
            cue=cue,
            assertion=assertion,
            offset_source=offset_source,
            quote=quote,
            party_basis=party_basis,
            layer=layer,
            layer_term=supporting,
            layer_reason=layer_reason,
            counterparty=counterparty,
        )

    # --- finishing ------------------------------------------------------------------------------

    def _finish(self, extraction: ClaimExtraction, status: str, *, owned: bool) -> Artifacts:
        if owned and self._runs is not None:
            with self._engine.connect() as connection:
                usage = run_usage(connection, extraction.run_id)
            try:
                self._runs.finish(
                    extraction.run_id, tokens_in=usage.tokens_in, tokens_out=usage.tokens_out
                )
            except RunNotFound:
                pass  # finished by an earlier attempt that stopped before recording the status
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE claim_extraction SET status = :status, finished_at = now()"
                    " WHERE id = :id AND status = 'running'"
                ),
                {"id": extraction.id, "status": status},
            )
            finished = get_extraction(connection, extraction.id)
        assert finished is not None
        return _artifacts(finished)

    # --- reads ----------------------------------------------------------------------------------

    def _versions(
        self,
        ids: Sequence[uuid.UUID],
        pins: dict[uuid.UUID, str | None] | None = None,
    ) -> list[_Version]:
        """The versions, each in its current parse, or for a version in `pins` the parse
        named there (None: the recorded parse)."""
        pins = pins or {}
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT v.id, d.title, d.form_type, d.document_type, d.company_id,"
                    " d.provider, v.metadata -> 'items' AS items"
                    " FROM source_version v"
                    " JOIN source_document d ON d.id = v.source_document_id"
                    " WHERE v.id = ANY(:ids)"
                ),
                {"ids": list(ids)},
            ).mappings()
            versions: list[_Version] = []
            for row in rows:
                version_id: uuid.UUID = row["id"]
                if version_id in pins:
                    parse = get_parse(connection, version_id, pins[version_id])
                else:
                    parse = current_parse(connection, version_id)
                versions.append(
                    _Version(
                        **_row(row),
                        parse_status=parse.parse_status if parse else "not_applicable",
                        parsed_object_uri=parse.parsed_object_uri if parse else None,
                        parser_version=parse.parser_version if parse else None,
                    )
                )
            return versions

    def _companies(self) -> list[_Company]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text("SELECT id, display_name, legal_name FROM company ORDER BY slug")
            ).all()
        return [_Company(row.id, company_names(row.display_name, row.legal_name)) for row in rows]

    def _text(self, version: _Version) -> str:
        """The text of the parse `version` names (cached by that parse's archived object)."""
        assert version.parsed_object_uri is not None
        uri = version.parsed_object_uri
        if uri not in self._texts:
            self._texts[uri] = self._archive.get(uri).decode("utf-8")
        return self._texts[uri]


def _unnamed_filer_refusal(
    quote: str,
    role: str,
    names: Sequence[str],
    *,
    counterparty: Sequence[str] | None,
    object_text: str,
    others: Sequence[Sequence[str]],
) -> str | None:
    """Why the filer (`names`) can't be the unnamed `role` of `quote`, a sentence of its own
    document that doesn't name it; None when it can. The quote must name the other party by
    name (`counterparty`: the other company of a company-object predicate) or, for a product
    object, the product (`object_text`), and name no other company that could be the unnamed
    one (`others`: the companies Atlas has besides the Claim's two; and any name written with
    a legal form). The predicate's cue is checked next, as for every Claim."""
    unnamed = f"the quote doesn't name the {role} ({names[0]}), whose document it is"
    if counterparty is not None:
        if not names_party(quote, counterparty, is_filer=False):
            return f"{unnamed}, nor the other party ({counterparty[0]})"
    elif not names_object(quote, object_text):
        return f"{unnamed}, nor its object ({object_text})"
    strays = stray_companies(quote, [counterparty] if counterparty is not None else [], others)
    if strays:
        return (
            f"{unnamed}, and it names {', '.join(strays)}: a sentence naming other companies"
            " proves nothing about the filer (co-mention)"
        )
    return None


@dataclass(frozen=True)
class Placed:
    """Where a Claim's quote is in the parsed text, and how it was found there."""

    span: tuple[int, int]
    source: str  # `model`, `located` or `folded`


def _place(parsed: str, passage: Passage, proposed: ProposedClaim) -> Placed | str | None:
    """The quote at the model's offsets (`model`), else its one exact occurrence in the passage
    (`located`); else the same two steps through the typographic fold (`fold`: one character
    to one character, so the offsets are the passage's own), either of which is `folded`.
    More than one occurrence returns the `quote_ambiguous` message; none (or an empty quote)
    is None: the span check then rejects the model's span as `quote_mismatch`."""
    window = parsed[passage.char_start : passage.char_end]
    quote = proposed.quote
    if not quote:
        return None
    exact = _locate(window, quote, passage, proposed, at_offsets="model", found="located")
    if exact is not None:
        return exact
    folded_window, folded_quote = fold(window), fold(quote)
    if folded_window == window and folded_quote == quote:
        return None  # nothing typographic to fold
    return _locate(
        folded_window,
        folded_quote,
        passage,
        proposed,
        at_offsets="folded",
        found="folded",
        through=" once typographic hyphens, quotation marks and spaces are folded",
    )


def _locate(
    window: str,
    quote: str,
    passage: Passage,
    proposed: ProposedClaim,
    *,
    at_offsets: str,
    found: str,
    through: str = "",
) -> Placed | str | None:
    """`quote` in `window` (both as written, or both folded): at the model's offsets
    (`at_offsets`), else at its one occurrence (`found`); the `quote_ambiguous` message for
    several occurrences; None for none."""
    if window[proposed.quote_start : proposed.quote_end] == quote:
        start = passage.char_start + proposed.quote_start
        return Placed((start, start + len(quote)), at_offsets)
    first = window.find(quote)
    if first < 0:
        return None
    second = window.find(quote, first + 1)
    if second < 0:
        start = passage.char_start + first
        return Placed((start, start + len(quote)), found)
    occurrences: list[int] = []
    at = first
    while at >= 0:
        occurrences.append(at)
        at = window.find(quote, at + 1)
    shown = ", ".join(f"[{o}, {o + len(quote)})" for o in occurrences[:5])
    more = "" if len(occurrences) <= 5 else ", ..."
    return (
        f"the quote is not at the offsets [{proposed.quote_start}, {proposed.quote_end}) of"
        f" passage {passage.id}, and it has {len(occurrences)} occurrences in the passage"
        f"{through} (at {shown}{more}), so it cannot be located"
    )


def _reject(judged: _Judged, code: str, reason: str) -> _Judged:
    return _Judged(
        source_version_id=judged.source_version_id,
        subject_company_id=judged.subject_company_id,
        object_company_id=judged.object_company_id,
        span=judged.span,
        cue=judged.cue,
        assertion=None,
        reason_code=code,
        reason=reason,
    )


def _proposed_layer(proposed: ProposedClaim) -> str | None:
    """The layer the model proposed, or None when it left it out (null or blank)."""
    return (proposed.layer or "").strip() or None


def _first_error(error: ValidationError) -> str:
    first = error.errors(include_url=False, include_input=False)[0]
    return f"{'.'.join(str(part) for part in first['loc'])}: {first['msg']}"


def _artifacts(extraction: ClaimExtraction) -> Artifacts:
    return {
        "extraction_id": str(extraction.id),
        "run_id": str(extraction.run_id),
        "status": extraction.status,
        "passages": len(extraction.passages),
        "passages_by_document": passages_by_document(extraction.passages),
        "passages_by_selection": passages_by_selection(extraction.passages),
        "accepted": extraction.accepted,
        "rejected": extraction.rejected,
        "batches_quarantined": extraction.batches_quarantined,
    }


def passages_by_document(passages: Sequence[Passage]) -> dict[str, JsonValue]:
    """How many of `passages` each Source Version has, in the order they first appear."""
    counts: dict[str, int] = {}
    for passage in passages:
        key = str(passage.source_version_id)
        counts[key] = counts.get(key, 0) + 1
    return dict(counts)


def passages_by_selection(passages: Sequence[Passage]) -> dict[str, JsonValue]:
    """How many of `passages` each kind of selection chose (`pointer`, `search`, `entity`,
    `lead`); a passage several kinds chose counts under each."""
    counts: dict[str, int] = {}
    for passage in passages:
        for kind in selections(passage.selected_by):
            counts[kind] = counts.get(kind, 0) + 1
    return dict(counts)


def _parser_version(
    versions: dict[uuid.UUID, _Version], version_id: uuid.UUID | None
) -> str | None:
    """The parse a Claim's passage was cut from (None when it names no passage sent)."""
    version = versions.get(version_id) if version_id is not None else None
    return version.parser_version if version is not None else None


def _row(row: RowMapping) -> dict[str, Any]:
    """A version row as `_Version` takes it: its filing's Items a tuple of strings."""
    fields = dict(row)
    items: Any = fields.get("items")
    recorded = cast(list[Any], items) if isinstance(items, list) else []
    fields["items"] = tuple(str(item) for item in recorded)
    return fields


def _str(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)
