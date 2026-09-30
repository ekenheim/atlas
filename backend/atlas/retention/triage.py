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
   (forward-looking-statement legends, signatures, mine safety, `[Reserved]`, the 10-K
   summary) and sections with no content past their heading (`None.`, `Not applicable.`)
   are `skip`, without a call. Exhibit indexes (`Item 6. Exhibits`, `Item 9.01. Financial
   Statements and Exhibits`, `Exhibit Index`) are not boilerplate since `triage-rules-v2`:
   they can name material contracts (the first live audit found a 10-Q's index naming a
   supply agreement with Coherent), so the role reads them; they are short.
3. **The Triage role** (`atlas.roles.triage`, its prompt the versioned rubric) decides the
   rest from the document's metadata and each section's heading and text, read in
   **windows** of `triage_excerpt_chars` characters, each overlapping the previous one by
   `triage_window_overlap_chars` (so a sentence at a boundary is read whole in the next
   window; `window_spans`): at most `triage_windows_per_section` of them, the first always
   and the rest spread evenly over a section that has more,
   `triage_sections_per_call` windows to a call. A section is `retain` when any of its
   windows is (that window's category and reason, marked `part p/n`), `skip` when every
   window is. Until 2026-09-30 the role saw a section's first window only, so a capacity or
   customer detail later in a long Item was invisible to triage (Codex review, item 3).

**Hold and retry** (owner decision 2026-09-30): a failed triage retains nothing and decides
nothing by default. A section is undecided until a rule, its predecessor or the role decides
it, and the version's retain waits for every section:

- An outage or quota failure of LiteLLM fails the attempt as a `TransientFailure` (from the
  role caller): the queue pauses and requeues the job without using an attempt.
- The triage run's own token budget spent is not a provider failure: the job is requeued
  (`Requeue`) without using an attempt and without pausing anything. Its next attempt starts
  a fresh run once the `minimax` rolling-window budget has room (ticket 27 holds it till then).
- A quarantined answer, or one that leaves a section out, leaves those sections undecided;
  the other batches go on, then the attempt fails (`TriageIncomplete`, an ordinary failure),
  so the queue retries it up to the job's `max_attempts` and then fails it visibly. If the
  run's budget runs out after such a section, the attempt fails the same way (a requeue
  would ask the same batch again without ever using an attempt).
- A job failed after its attempts is re-enqueued by `retry_failed_triage` (`atlas triage
  retry`); `atlas_triage_failed_jobs` counts the versions waiting on one.

Decisions are inserted as they are made (insert-only, audited), so a retried or resumed job
decides only the sections still undecided and never duplicates one. Once every section is
decided the job enqueues the version's `retain` of its `retain` sections (none: nothing is
submitted).
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
from atlas.jobs.pacing import JobClass, Requeue
from atlas.jobs.queue import Artifacts, Job, JobQueue
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
    TRIAGE_KIND,
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

RULES_VERSION = "triage-rules-v2"
RUN_KIND = "triage"
ON_DEMAND_CATEGORY = "on_demand"

# Section headings that are boilerplate.
_ITEM = r"item\s+\S+?\s*[.:\-\N{EN DASH}\N{EM DASH}]?\s*"
_BOILERPLATE: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        ("forward-looking statements", r"forward[\s-]+looking\s+statements?"),
        ("signatures", rf"^(?:{_ITEM})?signatures?\.?$"),
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


class TriageIncomplete(RoleCallFailed):
    """The role left sections undecided (a quarantined answer, or sections left out); the
    attempt fails so the job is retried, and nothing is retained for them meanwhile."""


@dataclass(frozen=True)
class _Pending:
    section: Section
    text: str
    sha256: str


@dataclass(frozen=True)
class _Window:
    """One window of a pending section's text, as the role is asked about it."""

    pending: _Pending
    part: int  # 1-based, by position in the section's text
    parts: int  # how many windows the section has
    text: str

    @property
    def anchor(self) -> str:
        base = self.pending.section.anchor
        return base if self.part == 1 else f"{base}~{self.part}"


@dataclass(frozen=True)
class WindowSpan:
    """One window of a text: its 1-based position among the text's windows and its offsets."""

    part: int
    parts: int
    start: int
    end: int


def window_spans(length: int, size: int, overlap: int, cap: int | None = None) -> list[WindowSpan]:
    """The windows of `size` characters over a text of `length`, each starting `overlap`
    characters before the previous one ends (so a sentence at a boundary is read whole in the
    next window), and at most `cap` of them (None: all): the first always, the rest spread
    evenly over the text when it has more than `cap`. The last window ends at `length` and
    always reaches past the previous one's end."""
    if size < 1 or not 0 <= overlap < size:
        raise ValueError("a window needs size >= 1 and 0 <= overlap < size")
    stride = size - overlap
    parts = 1 if length <= size else 1 + -(-(length - size) // stride)
    if cap is None or parts <= cap or cap == 1:
        chosen: list[int] = list(range(1, parts + 1 if cap is None else min(parts, cap) + 1))
    else:
        chosen = sorted({1 + round(i * (parts - 1) / (cap - 1)) for i in range(cap)})
    return [
        WindowSpan(part, parts, (part - 1) * stride, min((part - 1) * stride + size, length))
        for part in chosen
    ]


def _windows(pending: _Pending, size: int, overlap: int, cap: int) -> list[_Window]:
    """The section's windows (`window_spans`) as the role is asked about them."""
    return [
        _Window(pending, span.part, span.parts, pending.text[span.start : span.end])
        for span in window_spans(len(pending.text), size, overlap, cap)
    ]


def _aggregate(
    windows: Sequence[_Window], answers: dict[str, tuple[TriageSectionDecision, uuid.UUID]]
) -> dict[str, object]:
    """The section's decision from its windows' answers: `retain` on the first window that
    retains (its category and reason, marked `part p/n` when the section has several), else
    `skip` as the first window said (marked with how many windows were read, when several)."""
    judged = [(window, *answers[window.anchor]) for window in windows]
    retaining = [each for each in judged if each[1].decision == "retain"]
    window, answer, role_call_id = retaining[0] if retaining else judged[0]
    reason = answer.reason.strip() or "no reason given"
    if retaining and window.parts > 1:
        reason = f"part {window.part}/{window.parts}: {reason}"
    elif not retaining and len(windows) > 1:
        reason = f"none of {len(windows)} windows read (of {window.parts}) retained: {reason}"
    return {
        "decision": answer.decision,
        "category": answer.category,
        "reason": reason,
        "method": "role",
        "role_call_id": role_call_id,
    }


def triage_document(version: SourceVersionInfo, universe: Universe) -> TriageDocument:
    """The document's metadata as the Triage role (and its judge) are told it."""
    company = None
    if version.company_slug is not None:
        config = universe.companies.get(version.company_slug)
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


def triage_themes(version: SourceVersionInfo, universe: Universe) -> list[TriageTheme]:
    """The themes of the version's company: the bottleneck questions triage judges against."""
    return [
        TriageTheme(theme_id=slug, title=theme.title, description=theme.description)
        for slug, theme in sorted(universe.themes.items())
        if version.company_slug is not None and version.company_slug in theme.companies
    ]


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
        windows_per_section: int,
        sections_per_call: int,
        window_overlap_chars: int,
    ) -> None:
        self._engine = engine
        self._archive = archive
        self._actor = actor
        self._universe = universe
        self._caller = caller
        self._runs = runs
        self._excerpt_chars = excerpt_chars
        self._windows_per_section = windows_per_section
        self._overlap = window_overlap_chars
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
        tally = {"inherited": 0, "rule": 0, "role": 0}
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
            tally["role"] += self._ask_role(version, undecided)
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

    def _ask_role(self, version: SourceVersionInfo, undecided: list[_Pending]) -> int:
        """Ask the role about the undecided sections, window by window and batch by batch,
        inserting a section's decision once every window of it is answered. Raises
        `TriageIncomplete` if any section is left undecided, and `Requeue` if the run's token
        budget ran out with nothing left undecided so far (see the module)."""
        if self._caller is None or self._runs is None:
            raise RoleCallFailed(
                "retention triage needs LiteLLM and Hindsight configured"
                " (ATLAS_LITELLM_URL, ATLAS_LITELLM_API_KEY, ATLAS_HINDSIGHT_URL),"
                " or ATLAS_RETENTION_TRIAGE=off"
            )
        run_id = self._runs.start(RUN_KIND).id
        by_role = 0
        windows = [
            window
            for each in undecided
            for window in _windows(
                each, self._excerpt_chars, self._overlap, self._windows_per_section
            )
        ]
        answers: dict[str, tuple[TriageSectionDecision, uuid.UUID]] = {}
        unanswered: dict[str, str] = {}  # window anchor -> why
        decided: set[str] = set()  # section anchors inserted
        exhausted: TokenBudgetExhausted | None = None
        try:
            for batch in _batches(windows, self._per_call):
                got, role_call_id, why = self._call(version, batch, run_id)
                for window in batch:
                    answer = got.get(window.anchor)
                    if answer is None or role_call_id is None:
                        unanswered[window.anchor] = why
                    else:
                        answers[window.anchor] = (answer, role_call_id)
                with self._engine.begin() as connection:
                    lock_decisions(connection, version.id)
                    for each in undecided:
                        if each.section.anchor in decided:
                            continue
                        mine = [w for w in windows if w.pending is each]
                        if all(w.anchor in answers for w in mine):
                            decided.add(each.section.anchor)
                            by_role += self._insert(
                                connection, version, each, **_aggregate(mine, answers)
                            )
        except TokenBudgetExhausted as error:
            exhausted = error
        finally:
            self._finish(run_id)
        left = [f"{anchor} ({why})" for anchor, why in unanswered.items()]
        if left:
            spent = f"; then {exhausted}" if exhausted is not None else ""
            raise TriageIncomplete(
                f"{len(left)} window(s) of Source Version {version.id} left undecided,"
                f" retried later and not retained meanwhile: {'; '.join(left)}{spent}"
            )
        if exhausted is not None:
            raise Requeue(
                f"retention triage of Source Version {version.id} continues in a fresh run:"
                f" the triage run's token budget is spent ({exhausted})"
            ) from exhausted
        return by_role

    def _call(
        self, version: SourceVersionInfo, batch: Sequence[_Window], run_id: uuid.UUID
    ) -> tuple[dict[str, TriageSectionDecision], uuid.UUID | None, str]:
        """The role's answers by window anchor (the first for each anchor it was asked
        about), the role call (None: quarantined), and why a window of the batch may be left
        undecided. `TokenBudgetExhausted` propagates to `_ask_role`."""
        assert self._caller is not None
        request = TriageRequest(
            document=triage_document(version, self._universe),
            themes=triage_themes(version, self._universe),
            sections=[
                TriageSection(
                    anchor=window.anchor,
                    heading=window.pending.section.heading,
                    length=len(window.pending.text),
                    part=window.part,
                    parts=window.parts,
                )
                for window in batch
            ],
        )
        retrieved = [
            QuotedText(
                id=window.anchor,
                source=f"{version.id}#{window.pending.section.anchor}",
                text=window.text,
            )
            for window in batch
        ]
        try:
            output, role_call_id = self._caller.call_recorded(
                TRIAGE, request, run_id=run_id, retrieved=retrieved
            )
        except RoleOutputQuarantined as quarantined:
            return {}, None, f"role call {quarantined.role_call_id} quarantined"
        asked = {window.anchor for window in batch}
        answers: dict[str, TriageSectionDecision] = {}
        for answer in output.decisions:
            if answer.anchor in asked:
                answers.setdefault(answer.anchor, answer)
        return (
            answers,
            role_call_id,
            f"role call {role_call_id} returned no decision for it",
        )

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


# --- retrying a failed triage -------------------------------------------------------------------

# Each Source Version's latest `triage` job (the one that says whether its triage is done).
LATEST_TRIAGE_JOBS = (
    "SELECT DISTINCT ON (payload->>'source_version_id') id, status, job_class, max_attempts,"
    " (payload->>'source_version_id')::uuid AS source_version_id FROM job WHERE kind = 'triage'"
    " ORDER BY payload->>'source_version_id', created_at DESC, id DESC"
)


class TriageRetryRefused(Exception):
    pass


def retry_failed_triage(
    engine: Engine, actor: Actor, source_version_id: uuid.UUID | None = None
) -> list[Job]:
    """Re-enqueue the triage of each Source Version whose latest `triage` job failed after its
    attempts (or of just `source_version_id`), in the failed job's class and with its
    `max_attempts`. The new job decides only the sections still undecided.

    Refused (`TriageRetryRefused`) for a version whose latest triage job didn't fail (or that
    has none). With no version given, every failed one is retried (none: an empty list).
    """
    queue = JobQueue(engine, actor=actor)
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    "SELECT l.*, (SELECT count(*) FROM job j WHERE j.kind = 'triage'"  # noqa: S608 (constant fragments)
                    "   AND j.payload->>'source_version_id' = l.source_version_id::text) AS jobs"
                    f" FROM ({LATEST_TRIAGE_JOBS}) AS l"
                    " WHERE CAST(:version AS uuid) IS NULL OR l.source_version_id = :version"
                    " ORDER BY l.source_version_id"
                ),
                {"version": source_version_id},
            )
            .mappings()
            .all()
        )
    if source_version_id is not None:
        if not rows:
            raise TriageRetryRefused(f"Source Version {source_version_id} has no triage job")
        if rows[0]["status"] != "failed":
            raise TriageRetryRefused(
                f"the latest triage job of Source Version {source_version_id}"
                f" is {rows[0]['status']}, not failed"
            )
    return [
        queue.enqueue(
            TRIAGE_KIND,
            f"triage:{row['source_version_id']}:retry:{row['jobs']}",
            retain_payload(row["source_version_id"]),
            max_attempts=row["max_attempts"],
            job_class=row["job_class"],
        ).job
        for row in rows
        if row["status"] == "failed"
    ]
