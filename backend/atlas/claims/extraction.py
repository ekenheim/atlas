"""Claim extraction: the Investigator reads archived parsed text and proposes Claims; the
ones whose span and form check out become Assertions, the rest are recorded as rejected.

An `extract_claims` job names Source Versions (and optionally a question). One attempt:

1. **Passages.** Each Source Version's parsed text is split into sections by the retention
   sectioner (so a section here is a memory document's section there), and each section
   into windows of at most `PASSAGE_CHARS` characters, cut at line breaks. A window is chosen
   when it names a known company other than the document's own (an **entity tag**), or when
   a recall for the question (scoped to the documents' companies) resolves to its section
   (a **recall hit**). Within a document, entity-tagged windows come first, then recall-only
   ones; a document with neither offers its **lead** windows instead (its results sections
   first: a 10-Q's or 10-K's MD&A, an 8-K's Item 2.02). The `max_passages` budget is spread
   over the documents (pilot fix 10): passages are dealt one per document per round, in the
   documents' order, so each gets an equal share (the remainder to the earlier ones) and a
   share a document can't use passes on. Tagged and recall-only windows not sent are counted
   as dropped. The choice is stored with the extraction, so a resumed job sends the same
   passages; the job's artifacts count them per document (`passages_by_document`).
2. **Calls.** Passages go to the Investigator `passages_per_call` at a time, within the
   extraction's run (its own `claim_extraction` run, or the caller's `run_id`). Each call is
   a batch; progress is stored per batch, so a job requeued by an LLM outage or quota
   resumes at the next batch in the same run. A quarantined answer counts as a batch with no
   Claims. When the run's token budget is spent, the extraction stops `budget_exhausted`.
3. **Checks**, per proposed Claim, in this order (the first failure is the rejection):
   the predicate is whitelisted (`predicate_not_whitelisted`); the layer is known
   (`unknown_layer`); the passage was sent in that call (`unknown_passage`); the subject and
   a company object are known companies (`unknown_company`), a product object is named
   (`missing_object`) and subject and object differ (`self_relationship`). **A company object
   may instead be named** (`object_name`, for a company outside the known ones): the quote
   must contain that name (`party_not_in_quote`), and the name must resolve to one company
   (`atlas.counterparties`: a company Atlas has, else exactly one SEC registrant or GLEIF
   record of that name; otherwise `unresolved_company` or `ambiguous_company`, as is every
   unknown name when entity resolution isn't configured). Then: the offsets lie
   inside the passage (`quote_outside_passage`); **the quote is placed**: if it is not
   exactly the text at the model's offsets it is searched for in the passage as an exact
   substring (no folding of whitespace, quotes or dashes), and its one occurrence gives the
   span (`offset_source` `located`, else `model`; the model's offsets stay in `proposed`); no
   occurrence is `quote_mismatch` and more than one `quote_ambiguous`; **the Assertion span
   check** then runs on the final span (`quote_mismatch`); the quote names both parties
   (`party_not_in_quote`); and it uses language expressing the predicate
   (`no_directional_language`; co-mention is not a relation). A bottleneck predicate's
   product object must be named in the quote (`object_not_in_quote`) and be a particular
   input or product, not generic materials or components (`generic_object`); and for any
   product object the cue must be in a clause that names the object (`cue_in_other_clause`,
   pilot-fixes ticket 09). See `atlas.claims.predicates`.
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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

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
    directional_cue,
    is_generic_object,
    mentions,
    names_object,
    names_party,
    object_clause_cue,
    predicate_refusal,
)
from atlas.claims.reads import ClaimExtraction, Passage, SkippedVersion, get_extraction
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
from atlas.research.provenance import Evidence
from atlas.retention.sections import Section, split_sections
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
PASSAGE_CHARS = 3000
MAX_SOURCE_VERSIONS = 25  # the spec's per-run bound on fetched documents
_PARSED = ("parsed", "incomplete")

# (question, company IDs) -> the sections a scoped recall resolved to.
Recall = Callable[[str, list[uuid.UUID]], list[Evidence]]
# A window considered for a passage: (Source Version, section anchor, start, end, selected_by).
_Candidate = tuple[uuid.UUID, str, int, int, list[str]]
# `selected_by` of a lead window (`_lead`): sent for its document's share, not for a match.
LEAD = "lead"
# The sections read first among a document's lead windows, by form: the results sections.
_LEAD_FIRST: dict[str, tuple[str, ...]] = {
    "10-Q": ("part-i-item-2",),  # Management's Discussion and Analysis
    "10-K": ("part-ii-item-7",),  # Management's Discussion and Analysis
    "8-K": ("item-2-02", "item-7-01", "item-8-01"),  # results; Regulation FD; other events
}


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
    offset_source: str | None = None  # `model` or `located`, once the quote is placed
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
        recall: Recall | None,
        max_passages: int,
        passages_per_call: int,
        investigator: Role[InvestigatorRequest, InvestigatorClaims] = INVESTIGATOR,
        resolver: EntityResolver | None = None,
        ignored_ciks: frozenset[str] = frozenset(),
    ) -> None:
        """`investigator` is the role called: the committed prompt, or a variant under
        measurement (`scripts/investigator_replay.py`); its prompt names the Assertions'
        `extractor_version`. `resolver` identifies a company object given by name (with the
        configured companies' `ignored_ciks`); without one, a name that is none of Atlas's
        companies is rejected as unresolved."""
        self._engine = engine
        self._archive = archive
        self._caller = caller
        self._runs = runs
        self._recall = recall
        self._max_passages = max_passages
        self._passages_per_call = passages_per_call
        self._investigator = investigator
        self._extractor_version = f"{investigator.prompt.name}.v{investigator.prompt.version}"
        self._resolver = resolver
        self._ignored_ciks = ignored_ciks
        self._assertions = Assertions(engine, archive, INVESTIGATOR_ACTOR)
        self._texts: dict[str, str] = {}  # by parsed object URI
        self._named: dict[str, NamedCompany] = {}  # by normalized name

    def extract(self, job: Job, payload: ExtractClaimsPayload | None = None) -> Artifacts:
        """Run (or resume) the extraction of `job`: its payload's, or `payload` when a caller
        runs an extraction within its own job (an investigation's Investigator task)."""
        payload = payload or ExtractClaimsPayload.model_validate(job.payload)
        extraction = self._existing(job.id) or self._start(job.id, payload)
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

    def _start(self, job_id: uuid.UUID, payload: ExtractClaimsPayload) -> ClaimExtraction:
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
        hits = self._recall_hits(payload.question, usable)
        passages, dropped = self._select(usable, self._companies(), hits)
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

    def _recall_hits(
        self, question: str | None, versions: Sequence[_Version]
    ) -> set[tuple[uuid.UUID, str]]:
        company_ids = list(dict.fromkeys(v.company_id for v in versions if v.company_id))
        if question is None or self._recall is None or not company_ids:
            return set()
        wanted = {version.id for version in versions}
        return {
            (evidence.source_version_id, evidence.section_anchor)
            for evidence in self._recall(question, company_ids)
            if evidence.source_version_id in wanted
        }

    def _select(
        self,
        versions: Sequence[_Version],
        companies: Sequence[_Company],
        hits: set[tuple[uuid.UUID, str]],
    ) -> tuple[list[Passage], int]:
        """The passages, the budget spread over the documents (pilot fix 10): each document's
        candidates are its entity-tagged windows, then its recall-only ones, or, when it has
        neither, its lead windows (`_lead`). Passages are dealt one per document per round, in
        the documents' order (an investigation's are newest first), until the budget is spent
        or no document has a candidate left: so each document gets an equal share, the
        remainder going to the earlier ones, and a share a document can't use passes on.
        Counted as dropped: the tagged and recall-only windows not sent."""
        candidates: list[list[_Candidate]] = []
        preferred_total = 0
        for version in versions:
            parsed = self._text(version)
            others = [company for company in companies if company.id != version.company_id]
            primary = (
                version.document_type is not None and version.document_type == version.form_type
            )
            sections = split_sections(parsed, form=version.form_type, primary=primary)
            tagged: list[_Candidate] = []
            recalled: list[_Candidate] = []
            for section in sections:
                hit = (version.id, section.anchor) in hits
                for start, end in _windows(parsed, section.start, section.end):
                    window = parsed[start:end]
                    if not window.strip():
                        continue
                    named = [f"entity:{c.id}" for c in others if mentions(window, c.names)]
                    selected_by = named + (["recall"] if hit else [])
                    if named:
                        tagged.append((version.id, section.anchor, start, end, selected_by))
                    elif hit:
                        recalled.append((version.id, section.anchor, start, end, selected_by))
            preferred = [*tagged, *recalled]
            preferred_total += len(preferred)
            candidates.append(preferred or _lead(version, parsed, sections))
        chosen = _deal(candidates, self._max_passages)
        passages = [
            Passage(
                id=f"p{index + 1}",
                source_version_id=version_id,
                section_anchor=anchor,
                char_start=start,
                char_end=end,
                selected_by=selected_by,
            )
            for index, (version_id, anchor, start, end, selected_by) in enumerate(chosen)
        ]
        sent_preferred = sum(1 for passage in passages if passage.selected_by != [LEAD])
        return passages, preferred_total - sent_preferred

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
            layers=[LayerOption(name=layer.name, covers=layer.covers) for layer in LAYERS],
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
                or not mentions(proposed.quote, [name])
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
        row = (
            connection.execute(
                text(
                    "INSERT INTO claim (id, extraction_id, run_id, role_call_id, ordinal,"
                    " proposed, passage_id, source_version_id, subject_company_id, predicate,"
                    " object_company_id, object_text, product, layer, quote, span_start,"
                    " span_end, epistemic_type, directional_cue, outcome, reason_code, reason,"
                    " assertion_id, offset_source, parser_version) VALUES (:id, :extraction,"
                    " :run, :role_call, :ordinal, CAST(:proposed AS jsonb), :passage, :version,"
                    " :subject, :predicate, :object, :object_text, :product, :layer, :quote,"
                    " :span_start, :span_end, :epistemic_type, :cue, :outcome, :reason_code,"
                    " :reason, :assertion, :offset_source, :parser_version)"
                    " RETURNING *"
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
                    "layer": proposed.layer,
                    "quote": proposed.quote,
                    "span_start": judged.span[0] if judged.span else None,
                    "span_end": judged.span[1] if judged.span else None,
                    "epistemic_type": proposed.epistemic_type,
                    "cue": judged.cue,
                    "outcome": "accepted" if assertion_id else "rejected",
                    "reason_code": judged.reason_code,
                    "reason": judged.reason,
                    "assertion": assertion_id,
                    "offset_source": judged.offset_source,
                    "parser_version": _parser_version(versions, judged.source_version_id),
                },
            )
            .mappings()
            .one()
        )
        record(
            connection,
            INVESTIGATOR_ACTOR,
            "claim.accepted" if assertion_id else "claim.rejected",
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
        if proposed.layer not in LAYER_NAMES:
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
                if not mentions(proposed.quote, [name]):
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
        if placed is not None:
            span, offset_source = placed.span, placed.source
        try:
            assertion = AssertionCreate(
                subject_company_id=subject.id,
                predicate=rule.name,
                # A counterparty not yet created gets its ID when the Claim is recorded.
                object_company_id=object_id if rule.object_kind == "company" else None,
                value_json={
                    "claim_id": str(claim_id),
                    "layer": proposed.layer,
                    "product": proposed.product,
                    "object_text": proposed.object_text if rule.object_kind == "product" else None,
                },
                source_version_id=version.id,
                quote=proposed.quote,
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
        quote = proposed.quote
        parties = [(subject.names, subject.id == version.company_id, "subject")]
        if rule.object_kind == "company":
            parties.append((object_names, object_id == version.company_id, "object"))
        for names, is_filer, role in parties:
            if not names_party(quote, names, is_filer=is_filer):
                message = f"the quote doesn't name the {role} ({names[0]})"
                return _reject(judged, "party_not_in_quote", message)
        cue = directional_cue(rule.name, quote)
        if cue is None:
            message = (
                f"the quote has no language expressing {rule.name} ({rule.reads});"
                " naming companies together is not a relation"
            )
            return _reject(judged, "no_directional_language", message)
        if rule.object_kind == "product":
            object_text = (proposed.object_text or "").strip()
            if rule.name in BOTTLENECK_PREDICATES:
                if not names_object(quote, object_text):
                    message = (
                        f"{rule.name} needs the input or product named in the quote, and the"
                        f" quote doesn't contain {object_text!r} (its `object_text`)"
                    )
                    return _reject(judged, "object_not_in_quote", message)
                if is_generic_object(object_text):
                    message = (
                        f"{object_text!r} names no particular input or product, so the quote"
                        f" shows nothing of layer {proposed.layer!r}: generic materials,"
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
                    "SELECT v.id, d.title, d.form_type, d.document_type, d.company_id"
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


def _lead(version: _Version, parsed: str, sections: Sequence[Section]) -> list[_Candidate]:
    """A document's lead windows, for one with no entity-tagged or recalled window (a press
    release naming no other known company, say): its results sections first (a 10-Q's MD&A,
    a 10-K's MD&A, an 8-K's results or Regulation FD items), then the rest in text order;
    the cover only when there is nothing else. Tagged `lead`."""
    first = _LEAD_FIRST.get((version.form_type or "").upper().removesuffix("/A"), ())
    ordered = sorted(
        (section for section in sections if section.anchor != "cover"),
        key=lambda section: section.anchor not in first,  # stable: text order otherwise
    ) or list(sections)
    return [
        (version.id, section.anchor, start, end, [LEAD])
        for section in ordered
        for start, end in _windows(parsed, section.start, section.end)
        if parsed[start:end].strip()
    ]


def _deal(candidates: Sequence[Sequence[_Candidate]], budget: int) -> list[_Candidate]:
    """One candidate per document per round, in document order, until `budget` are dealt or
    every document's candidates are: an equal share each, the remainder to the earlier
    documents, and a share a document can't use going to the others."""
    dealt: list[_Candidate] = []
    taken = [0] * len(candidates)
    while len(dealt) < budget:
        progress = False
        for index, each in enumerate(candidates):
            if taken[index] < len(each) and len(dealt) < budget:
                dealt.append(each[taken[index]])
                taken[index] += 1
                progress = True
        if not progress:
            break
    return dealt


def _windows(parsed: str, start: int, end: int) -> list[tuple[int, int]]:
    """[start, end) cut into windows of at most PASSAGE_CHARS, each ending at a line break
    when it has one past its first half."""
    windows: list[tuple[int, int]] = []
    position = start
    while position < end:
        limit = min(position + PASSAGE_CHARS, end)
        if limit < end:
            cut = parsed.rfind("\n", position + PASSAGE_CHARS // 2, limit)
            if cut >= 0:
                limit = cut + 1
        windows.append((position, limit))
        position = limit
    return windows


@dataclass(frozen=True)
class Placed:
    """Where a Claim's quote is in the parsed text, and whether the model's offsets said so."""

    span: tuple[int, int]
    source: str  # `model` or `located`


def _place(parsed: str, passage: Passage, proposed: ProposedClaim) -> Placed | str | None:
    """The quote at the model's offsets (`model`), else its one exact occurrence in the passage
    (`located`). More than one occurrence returns the `quote_ambiguous` message; none (or an
    empty quote) is None: the span check then rejects the model's span as `quote_mismatch`."""
    window = parsed[passage.char_start : passage.char_end]
    quote = proposed.quote
    if not quote:
        return None
    if window[proposed.quote_start : proposed.quote_end] == quote:
        start = passage.char_start + proposed.quote_start
        return Placed((start, start + len(quote)), "model")
    first = window.find(quote)
    if first < 0:
        return None
    second = window.find(quote, first + 1)
    if second < 0:
        start = passage.char_start + first
        return Placed((start, start + len(quote)), "located")
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
        f" (at {shown}{more}), so it cannot be located"
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


def _parser_version(
    versions: dict[uuid.UUID, _Version], version_id: uuid.UUID | None
) -> str | None:
    """The parse a Claim's passage was cut from (None when it names no passage sent)."""
    version = versions.get(version_id) if version_id is not None else None
    return version.parser_version if version is not None else None


def _row(row: RowMapping) -> dict[str, Any]:
    return dict(row)


def _str(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)
