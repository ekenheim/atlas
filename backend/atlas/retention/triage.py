"""Retention triage: read first, retain only what adds durable value (ticket 30).

Nothing goes into Hindsight just because it was ingested. With triage on
(`ATLAS_RETENTION_TRIAGE`), a new Source Version's `retain` job hands it to a `triage` job
(payload `{"source_version_id"}`, `minimax`-budgeted and pausable), which decides each section
before any section is retained:

1. **Inherited:** a section whose text hashes (SHA-256) the same as a section of the
   version's **predecessor** copies that section's effective decision. The predecessor is the
   most recent earlier triaged Source Version of the same Source Document, else of the same
   company, form and document type (last year's 10-K for this year's), available no later.
2. **Rules** (`RULES_VERSION`, on Item headings only): known boilerplate headings
   (forward-looking-statement legends, signatures, exhibit indexes, mine safety,
   `[Reserved]`, the 10-K summary) and sections with no content past their heading
   (`None.`, `Not applicable.`) are `skip`, without a call.
3. **The Triage role** (`atlas.roles.triage`, its prompt the versioned rubric) decides the
   rest, `triage_sections_per_call` sections to a call, from each section's heading and first
   `triage_excerpt_chars` characters and the document's metadata. A section the answer
   leaves out, or whose call was quarantined or ran out of the run's token budget, is
   retained (`default`): triage never loses evidence by failing.

Decisions are inserted as they are made (insert-only, audited), so a job paused by a quota
failure resumes with the sections still undecided. Once every section is decided the job
enqueues the version's `retain` of its `retain` sections (none: nothing is submitted).
Skipped sections stay archived and citable: the source viewer and Assertions work on the
parsed text, not on memory. `request_retain` retains one later, on demand, recorded with
who asked (and the investigation, when one did) and why.
"""

import re
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.archive import Archive
from atlas.audit import Actor
from atlas.companies import Universe
from atlas.jobs.pacing import JobClass
from atlas.jobs.queue import Artifacts, JobQueue
from atlas.retention.decisions import (
    TriageDecision,
    effective_decisions,
    get_decision,
    has_decision,
    insert_decision,
    lock_decisions,
    section_sha256,
)
from atlas.retention.sections import SECTIONER_VERSION, Section
from atlas.retention.service import (
    RETAIN_KIND,
    SourceVersionInfo,
    is_retainable,
    load_version,
    retain_payload,
    version_sections,
)
from atlas.roles import QuotedText, RoleCaller, RoleCallFailed, TokenBudgetExhausted
from atlas.roles.caller import RoleOutputQuarantined
from atlas.roles.records import run_usage
from atlas.roles.triage import (
    TRIAGE,
    TRIAGE_RUBRIC_VERSION,
    TriageDocument,
    TriageRequest,
    TriageSection,
    TriageSectionDecision,
    TriageTheme,
)
from atlas.runs import RunNotFound, RunRecorder

RULES_VERSION = "triage-rules-v1"
RUN_KIND = "triage"
ON_DEMAND_CATEGORY = "on_demand"
DEFAULT_CATEGORY = "unclassified"

# Section headings that are boilerplate.
_ITEM = r"item\s+\S+?\s*[.:\-\N{EN DASH}\N{EM DASH}]?\s*"
_BOILERPLATE: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        ("forward-looking statements", r"forward[\s-]+looking\s+statements?"),
        ("signatures", rf"^(?:{_ITEM})?signatures?\.?$"),
        ("exhibit index", r"exhibit\s+index|index\s+to\s+exhibits"),
        ("exhibits", rf"^{_ITEM}(?:financial\s+statements\s+and\s+)?exhibits"),
        ("mine safety", r"mine\s+safety\s+disclosures?"),
        ("reserved", r"\[\s*reserved\s*\]"),
        ("form 10-k summary", r"form\s+10-k\s+summary"),
    )
)
_PART = re.compile(r"PART\s+[IV]+\b.*", re.IGNORECASE)
# A section whose body (past its heading, page numbers dropped) is only one of these.
_EMPTY_BODIES = frozenset({"", "none", "none.", "not applicable", "not applicable.", "n/a"})


def boilerplate_rule(heading: str | None, section_text: str) -> str | None:
    """The rule that makes a section boilerplate (as its reason), or None.

    Only sections with a heading (an SEC Item) are judged: a bounded chunk's first line is
    wherever the chunk happened to start, not a heading.
    """
    if heading is None:
        return None
    for name, pattern in _BOILERPLATE:
        if pattern.search(heading):
            return f"boilerplate heading ({name}): {heading[:120]}"
    body = [
        line
        for raw in section_text.splitlines()
        if (line := raw.strip())
        and line != heading
        and not _PART.fullmatch(line)
        and not line.isdigit()
    ]
    if " ".join(body).casefold() in _EMPTY_BODIES:
        return f"no content past its heading: {heading[:120]}"
    return None


@dataclass(frozen=True)
class _Pending:
    section: Section
    text: str
    sha256: str


class Triage:
    """Runs one `triage` job: decides every undecided section of a Source Version."""

    def __init__(
        self,
        engine: Engine,
        archive: Archive,
        actor: Actor,
        universe: Universe,
        caller: RoleCaller | None,
        runs: RunRecorder | None,
        *,
        excerpt_chars: int,
        sections_per_call: int,
    ) -> None:
        self._engine = engine
        self._archive = archive
        self._actor = actor
        self._universe = universe
        self._caller = caller
        self._runs = runs
        self._excerpt_chars = excerpt_chars
        self._per_call = sections_per_call
        self._queue = JobQueue(engine, actor=actor)

    def triage(self, source_version_id: uuid.UUID, job_class: JobClass) -> Artifacts:
        version = load_version(self._engine, source_version_id)
        base: Artifacts = {"source_version_id": str(version.id)}
        if not is_retainable(version):
            return base | {"outcome": "not_retainable"}
        assert version.parsed_object_uri is not None
        parsed = self._archive.get(version.parsed_object_uri).decode("utf-8")
        with self._engine.connect() as connection:
            decided = effective_decisions(connection, version.id)
        pending = [
            _Pending(section, body, section_sha256(body))
            for section in version_sections(version, parsed)
            if section.anchor not in decided
            for body in [parsed[section.start : section.end]]
        ]
        tally = {"inherited": 0, "rule": 0, "role": 0, "default": 0}
        with self._engine.begin() as connection:
            lock_decisions(connection, version.id)
            inherited = self._predecessor_decisions(connection, version)
            undecided: list[_Pending] = []
            for each in pending:
                if (source := inherited.get(each.sha256)) is not None:
                    tally["inherited"] += self._insert(
                        connection,
                        version,
                        each,
                        decision=source["decision"],
                        category=source["category"],
                        reason=source["reason"],
                        method="inherited",
                        inherited_from_id=source["id"],
                    )
                elif (reason := boilerplate_rule(each.section.heading, each.text)) is not None:
                    tally["rule"] += self._insert(
                        connection,
                        version,
                        each,
                        decision="skip",
                        category="boilerplate",
                        reason=reason,
                        method="rule",
                    )
                else:
                    undecided.append(each)
        if undecided:
            role, default = self._ask_role(version, undecided)
            tally["role"] += role
            tally["default"] += default
        retain_job = self._enqueue_retain(version, job_class)
        return base | {"outcome": "triaged", **tally, "retain_job": retain_job}

    # --- inheritance ---------------------------------------------------------------------------

    def _predecessor_decisions(
        self, connection: Connection, version: SourceVersionInfo
    ) -> dict[str, RowMapping]:
        """The predecessor's effective decisions by content hash (see the module)."""
        predecessor = connection.execute(
            text(
                "SELECT v.id FROM source_version v"
                " JOIN source_version_availability a ON a.source_version_id = v.id"
                " JOIN source_document d ON d.id = v.source_document_id,"
                " source_version me"
                " JOIN source_version_availability ma ON ma.source_version_id = me.id"
                " JOIN source_document md ON md.id = me.source_document_id"
                " WHERE me.id = :version AND v.id <> me.id AND a.available_at <= ma.available_at"
                " AND EXISTS (SELECT FROM triage_decision t WHERE t.source_version_id = v.id)"
                " AND (d.id = md.id OR (md.company_id IS NOT NULL"
                "   AND d.company_id = md.company_id"
                "   AND d.form_type IS NOT DISTINCT FROM md.form_type"
                "   AND d.document_type IS NOT DISTINCT FROM md.document_type))"
                " ORDER BY (d.id = md.id) DESC, a.available_at DESC, v.ingested_at DESC, v.id"
                " LIMIT 1"
            ),
            {"version": version.id},
        ).scalar_one_or_none()
        if predecessor is None:
            return {}
        by_hash: dict[str, RowMapping] = {}
        for row in effective_decisions(connection, predecessor).values():
            by_hash.setdefault(row["content_sha256"], row)
        return by_hash

    # --- the role ------------------------------------------------------------------------------

    def _ask_role(self, version: SourceVersionInfo, undecided: list[_Pending]) -> tuple[int, int]:
        if self._caller is None or self._runs is None:
            raise RoleCallFailed(
                "retention triage needs LiteLLM and Hindsight configured"
                " (ATLAS_LITELLM_URL, ATLAS_LITELLM_API_KEY, ATLAS_HINDSIGHT_URL),"
                " or ATLAS_RETENTION_TRIAGE=off"
            )
        run_id = self._runs.start(RUN_KIND).id
        by_role = by_default = 0
        try:
            for batch in _batches(undecided, self._per_call):
                answers, role_call_id, fallback = self._call(version, batch, run_id)
                with self._engine.begin() as connection:
                    lock_decisions(connection, version.id)
                    for each in batch:
                        answer = answers.get(each.section.anchor)
                        if answer is not None and role_call_id is not None:
                            by_role += self._insert(
                                connection,
                                version,
                                each,
                                decision=answer.decision,
                                category=answer.category,
                                reason=answer.reason.strip() or "no reason given",
                                method="role",
                                role_call_id=role_call_id,
                            )
                        else:
                            by_default += self._insert(
                                connection,
                                version,
                                each,
                                decision="retain",
                                category=DEFAULT_CATEGORY,
                                reason=fallback,
                                method="default",
                            )
        finally:
            self._finish(run_id)
        return by_role, by_default

    def _call(
        self, version: SourceVersionInfo, batch: Sequence[_Pending], run_id: uuid.UUID
    ) -> tuple[dict[str, TriageSectionDecision], uuid.UUID | None, str]:
        """The role's answers by anchor (the first for each anchor it was asked about), the
        role call, and the reason recorded for a section it left undecided."""
        assert self._caller is not None
        request = TriageRequest(
            document=self._document(version),
            themes=self._themes(version),
            sections=[
                TriageSection(
                    anchor=each.section.anchor,
                    heading=each.section.heading,
                    length=len(each.text),
                )
                for each in batch
            ],
        )
        retrieved = [
            QuotedText(
                id=each.section.anchor,
                source=f"{version.id}#{each.section.anchor}",
                text=each.text[: self._excerpt_chars],
            )
            for each in batch
        ]
        try:
            output, role_call_id = self._caller.call_recorded(
                TRIAGE, request, run_id=run_id, retrieved=retrieved
            )
        except RoleOutputQuarantined as quarantined:
            reason = f"retained by default: role call {quarantined.role_call_id} quarantined"
            return {}, None, reason
        except TokenBudgetExhausted:
            return {}, None, "retained by default: the triage run's token budget was exhausted"
        asked = {each.section.anchor for each in batch}
        answers: dict[str, TriageSectionDecision] = {}
        for answer in output.decisions:
            if answer.anchor in asked:
                answers.setdefault(answer.anchor, answer)
        return (
            answers,
            role_call_id,
            f"retained by default: role call {role_call_id} returned no decision for it",
        )

    def _document(self, version: SourceVersionInfo) -> TriageDocument:
        company = None
        if version.company_slug is not None:
            config = self._universe.companies.get(version.company_slug)
            company = config.display_name if config is not None else version.company_slug
        return TriageDocument(
            source_version_id=str(version.id),
            company=company,
            title=version.title,
            form_type=version.form_type,
            document_type=version.document_type,
            provider=version.provider,
            source_type=version.source_type,
            available_at=version.available_at.isoformat(),
        )

    def _themes(self, version: SourceVersionInfo) -> list[TriageTheme]:
        return [
            TriageTheme(theme_id=slug, title=theme.title, description=theme.description)
            for slug, theme in sorted(self._universe.themes.items())
            if version.company_slug is not None and version.company_slug in theme.companies
        ]

    def _finish(self, run_id: uuid.UUID) -> None:
        assert self._runs is not None
        with self._engine.connect() as connection:
            usage = run_usage(connection, run_id)
        try:
            self._runs.finish(run_id, tokens_in=usage.tokens_in, tokens_out=usage.tokens_out)
        except RunNotFound:
            pass

    # --- shared --------------------------------------------------------------------------------

    def _insert(
        self,
        connection: Connection,
        version: SourceVersionInfo,
        pending: _Pending,
        **fields: object,
    ) -> bool:
        """Insert the section's decision unless it has one by now (an on-demand retain may
        have been recorded meanwhile); the caller holds `lock_decisions`."""
        if has_decision(connection, version.id, pending.section.anchor):
            return False
        insert_decision(
            connection,
            self._actor,
            source_version_id=version.id,
            section_anchor=pending.section.anchor,
            section_heading=pending.section.heading,
            char_start=pending.section.start,
            char_end=pending.section.end,
            sectioner_version=SECTIONER_VERSION,
            content_sha256=pending.sha256,
            rubric_version=TRIAGE_RUBRIC_VERSION,
            rules_version=RULES_VERSION,
            **fields,
        )
        return True

    def _enqueue_retain(self, version: SourceVersionInfo, job_class: JobClass) -> str | None:
        """The version's retain, once there is something to retain (None: every section is
        skipped, so nothing is submitted)."""
        with self._engine.connect() as connection:
            decisions = effective_decisions(connection, version.id)
        if not any(row["decision"] == "retain" for row in decisions.values()):
            return None
        return str(
            self._queue.enqueue(
                RETAIN_KIND,
                f"retain:{version.id}:triaged",
                retain_payload(version.id),
                job_class=job_class,
            ).job.id
        )


def _batches[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


# --- retain on demand ---------------------------------------------------------------------------


class RetainOnDemand(BaseModel):
    """Why a section should be retained now, and (optionally) the investigation asking."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
    investigation_id: uuid.UUID | None = None


class RetainRequested(BaseModel):
    """The on-demand decision recorded and the retain job that carries it out."""

    decision: TriageDecision
    retain_job_id: uuid.UUID


class RetainRefused(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def request_retain(
    engine: Engine,
    archive: Archive,
    actor: Actor,
    source_version_id: uuid.UUID,
    anchor: str,
    request: RetainOnDemand,
    *,
    bank_id: str,
) -> RetainRequested:
    """Record an on-demand `retain` decision for one section and enqueue its retain.

    Refused (`RetainRefused`) with 404 for an unknown version, section or investigation, and
    409 `not_retainable` (no English parse), `linked` (the version's memory is another
    version's) or `already_retained` (the section already has a memory document).
    """
    reason = request.reason.strip()
    if not reason:
        raise RetainRefused(422, "invalid_request", "reason: must not be blank")
    try:
        version = load_version(engine, source_version_id)
    except LookupError:
        raise RetainRefused(404, "not_found", "source version not found") from None
    if not is_retainable(version):
        raise RetainRefused(
            409, "not_retainable", "only a parsed Source Version in English can be retained"
        )
    assert version.parsed_object_uri is not None
    parsed = archive.get(version.parsed_object_uri).decode("utf-8")
    section = next((s for s in version_sections(version, parsed) if s.anchor == anchor), None)
    if section is None:
        raise RetainRefused(404, "not_found", "section not found")
    queue = JobQueue(engine, actor=actor)
    with engine.begin() as connection:
        lock_decisions(connection, version.id)
        if request.investigation_id is not None:
            investigation = connection.execute(
                text("SELECT 1 FROM investigation WHERE id = :id"),
                {"id": request.investigation_id},
            ).one_or_none()
            if investigation is None:
                raise RetainRefused(404, "not_found", "investigation not found")
        documents = connection.execute(
            text(
                "SELECT section_anchor, retain_state FROM memory_document"
                " WHERE source_version_id = :version AND bank_id = :bank FOR UPDATE"
            ),
            {"version": version.id, "bank": bank_id},
        ).all()
        if any(state == "linked" for _, state in documents):
            raise RetainRefused(
                409,
                "linked",
                "this Source Version's memory is linked to an identical retained version",
            )
        if any(section_anchor == anchor for section_anchor, _ in documents):
            raise RetainRefused(409, "already_retained", "the section is already retained")
        row = insert_decision(
            connection,
            actor,
            source_version_id=version.id,
            section_anchor=section.anchor,
            section_heading=section.heading,
            char_start=section.start,
            char_end=section.end,
            sectioner_version=SECTIONER_VERSION,
            content_sha256=section_sha256(parsed[section.start : section.end]),
            decision="retain",
            category=ON_DEMAND_CATEGORY,
            reason=reason,
            method="on_demand",
            rubric_version=TRIAGE_RUBRIC_VERSION,
            rules_version=RULES_VERSION,
            requested_by=actor.name,
            investigation_id=request.investigation_id,
        )
        job = queue.enqueue_within(
            connection,
            RETAIN_KIND,
            f"retain:{version.id}:on-demand:{row['id']}",
            retain_payload(version.id),
        ).job
        decision = get_decision(connection, row["id"])
    assert decision is not None
    return RetainRequested(decision=decision, retain_job_id=job.id)
