"""Changing Hypotheses: saving an investigation's result, lifecycle transitions, corrections
as new versions, and publishing a version behind the publish gate (spec §5.6).

- **Save.** `create` records a Hypothesis (status `draft`) for a stopped investigation that
  has a research card with a finding (one Hypothesis per investigation) and, in the same
  transaction, enqueues the `draft_hypothesis` job: the Editor drafts version 1
  (atlas.hypotheses.drafting).
- **Lifecycle.** `transition` moves the status along `TRANSITIONS`; `reviewed` is reached
  only by `publish`. Every change is an insert-only `hypothesis_transition` row and an audit
  event.
- **Versions never change.** `correct` writes a new version from the latest one with the
  researcher's changes and a note (audited `hypothesis.corrected` when it corrects a
  published version). Findings it names must cite accepted Claims of the investigation, or
  it is refused: nothing unsupported is promoted.
- **Publish.** `publish` stamps the latest version published (the database refuses any later
  change to it) if every check of the gate passes; otherwise `PublishRefused` lists every
  failed check by code. The gate is pluggable: the default requires at least one falsifier,
  one unresolved question, and the owner's approval of every Relationship the version depends
  on (those its findings' Assertions support; an Assertion not yet machine-reviewed holds it
  too). `hooks` run in the publishing transaction: the API's writes the Research Snapshot
  (atlas.snapshots), so a version is published with its snapshot or not at all.
"""

import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.audit import Actor, content_hash, record
from atlas.hypotheses.findings import ProposedFinding, resolve_findings
from atlas.hypotheses.model import (
    DRAFT_HYPOTHESIS_KIND,
    PUBLISHABLE_FROM,
    TRANSITIONS,
    HypothesisContent,
    HypothesisStatus,
    HypothesisVersion,
    Mechanism,
    VersionProvenance,
    version_from_row,
)
from atlas.investigations.skeptic import counterevidence_by_claim
from atlas.investigations.tasks import accepted_claims
from atlas.jobs.queue import JobQueue
from atlas.proposed_updates.triggers import record_dependencies


class HypothesisError(Exception):
    """A request the Hypothesis can't honour; `code` and `status` for the API."""

    code = "invalid_hypothesis"
    status = 422

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class HypothesisNotFound(HypothesisError):
    code = "not_found"
    status = 404


class HypothesisConflict(HypothesisError):
    code = "conflict"
    status = 409


class InvalidTransition(HypothesisError):
    code = "invalid_transition"
    status = 409


class UnsupportedFindings(HypothesisError):
    code = "unsupported_finding"


class PublishRefused(HypothesisError):
    """The publish gate refused: `failures` lists every check that failed."""

    code = "publish_gate_failed"

    def __init__(self, version: int, failures: Sequence["GateFailure"]) -> None:
        self.failures = list(failures)
        reasons = "; ".join(f"{each.code}: {each.message}" for each in failures)
        super().__init__(f"the publish gate refused version {version}: {reasons}")


# --- the publish gate -------------------------------------------------------------------------


@dataclass(frozen=True)
class GateFailure:
    code: str
    message: str
    # The Relationships (or, pending review, Assertions) the failure is about, if any.
    relationship_ids: tuple[uuid.UUID, ...] = ()
    assertion_ids: tuple[uuid.UUID, ...] = ()


# A check of the publish gate: it reads what it needs within the publishing transaction and
# returns why the version can't be published, or None.
PublishCheck = Callable[[Connection, RowMapping, HypothesisVersion], GateFailure | None]
# Runs after the checks pass, in the publishing transaction (ticket 20: the snapshot).
PublishHook = Callable[[Connection, RowMapping, HypothesisVersion, Actor], None]


def requires_falsifier(
    _connection: Connection, _hypothesis: RowMapping, version: HypothesisVersion
) -> GateFailure | None:
    if any(each.strip() for each in version.content.falsifiers):
        return None
    return GateFailure("no_falsifier", "a published Hypothesis needs at least one falsifier")


def requires_unresolved_question(
    _connection: Connection, _hypothesis: RowMapping, version: HypothesisVersion
) -> GateFailure | None:
    if any(each.strip() for each in version.content.unresolved_questions):
        return None
    return GateFailure(
        "no_unresolved_question", "a published Hypothesis needs at least one unresolved question"
    )


def dependent_assertion_ids(version: HypothesisVersion) -> list[uuid.UUID]:
    """The Assertions a version's findings rest on (their spans'), in finding order."""
    return list(
        dict.fromkeys(
            span.assertion_id
            for finding in version.content.findings
            for span in finding.source_spans
        )
    )


def _dependencies(connection: Connection, version: HypothesisVersion) -> list[RowMapping]:
    """Per dependent Assertion: the Relationship it supports (with its review state), and
    whether it has been machine-reviewed at all."""
    assertion_ids = dependent_assertion_ids(version)
    if not assertion_ids:
        return []
    return list(
        connection.execute(
            text(
                "SELECT a.id AS assertion_id, ra.relationship_id, r.review_state,"
                " rr.id IS NOT NULL AS reviewed"
                " FROM unnest(CAST(:ids AS uuid[])) WITH ORDINALITY AS a(id, n)"
                " LEFT JOIN relationship_assertion ra ON ra.assertion_id = a.id"
                " LEFT JOIN relationship r ON r.id = ra.relationship_id"
                " LEFT JOIN relationship_review rr ON rr.assertion_id = a.id"
                " ORDER BY a.n"
            ),
            {"ids": assertion_ids},
        ).mappings()
    )


def requires_approved_relationships(
    connection: Connection, _hypothesis: RowMapping, version: HypothesisVersion
) -> GateFailure | None:
    """Every Relationship the version depends on (those its findings' Assertions support) is
    approved by the owner (`machine_reviewed` is not enough; `rejected` never is)."""
    unapproved: dict[uuid.UUID, str] = {
        row["relationship_id"]: row["review_state"]
        for row in _dependencies(connection, version)
        if row["relationship_id"] is not None and row["review_state"] != "approved"
    }
    if not unapproved:
        return None
    listed = ", ".join(f"{each} ({state})" for each, state in unapproved.items())
    return GateFailure(
        "relationship_not_approved",
        f"the owner hasn't approved every Relationship the version depends on: {listed}",
        relationship_ids=tuple(unapproved),
    )


def requires_reviewed_assertions(
    connection: Connection, _hypothesis: RowMapping, version: HypothesisVersion
) -> GateFailure | None:
    """Every Assertion the version depends on has been machine-reviewed: until then it may
    still form a Relationship the owner hasn't seen. One reviewed `not_eligible` (no layer,
    co-mention) supports no edge and holds nothing."""
    pending = tuple(
        row["assertion_id"]
        for row in _dependencies(connection, version)
        if row["relationship_id"] is None and not row["reviewed"]
    )
    if not pending:
        return None
    return GateFailure(
        "relationship_review_pending",
        "Assertions the version depends on haven't been reviewed into Relationships yet: "
        + ", ".join(str(each) for each in pending),
        assertion_ids=pending,
    )


DEFAULT_PUBLISH_GATE: tuple[PublishCheck, ...] = (
    requires_falsifier,
    requires_unresolved_question,
    requires_approved_relationships,
    requires_reviewed_assertions,
)


# --- corrections ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Correction:
    """The researcher's changes for a new version; None keeps the base version's value."""

    based_on_version: int
    note: str
    thesis_statement: str | None = None
    mechanism: Mechanism | None = None
    measurable_predictions: list[str] | None = None
    catalysts: list[str] | None = None
    falsifiers: list[str] | None = None
    required_evidence: list[str] | None = None
    alternative_explanations: list[str] | None = None
    unresolved_questions: list[str] | None = None
    findings: list[ProposedFinding] | None = None


class Hypotheses:
    def __init__(
        self,
        engine: Engine,
        queue: JobQueue,
        *,
        gate: Sequence[PublishCheck] = DEFAULT_PUBLISH_GATE,
        hooks: Sequence[PublishHook] = (),
    ) -> None:
        self._engine = engine
        self._queue = queue
        self._gate = tuple(gate)
        self._hooks = tuple(hooks)

    def create(self, actor: Actor, investigation_id: uuid.UUID) -> uuid.UUID:
        """Save the investigation's result: a `draft` Hypothesis and its drafting job."""
        with self._engine.begin() as connection:
            investigation = (
                connection.execute(
                    text("SELECT * FROM investigation WHERE id = :id FOR UPDATE"),
                    {"id": investigation_id},
                )
                .mappings()
                .one_or_none()
            )
            if investigation is None:
                raise HypothesisNotFound("investigation not found")
            if investigation["status"] != "stopped":
                raise HypothesisConflict("the investigation is still running")
            card = investigation["research_card"]
            if card is None or not card.get("findings"):
                # A card with no finding reports what was searched and read: nothing to save.
                raise HypothesisConflict(
                    f"the investigation stopped {investigation['stop_reason']} without a"
                    " research card finding: there is nothing to save"
                )
            existing = connection.execute(
                text("SELECT id FROM hypothesis WHERE investigation_id = :id"),
                {"id": investigation_id},
            ).scalar_one_or_none()
            if existing is not None:
                raise HypothesisConflict(
                    f"the investigation is already saved as Hypothesis {existing}"
                )
            hypothesis_id = uuid.uuid4()
            job = self._queue.enqueue_within(
                connection,
                DRAFT_HYPOTHESIS_KIND,
                f"hypothesis:{hypothesis_id}",
                {"hypothesis_id": str(hypothesis_id)},
            ).job
            related = list(
                connection.execute(
                    text(
                        "SELECT seed FROM unnest(CAST(:seeds AS uuid[]))"
                        " WITH ORDINALITY AS s(seed, n)"
                        " WHERE NOT EXISTS (SELECT FROM investigation_premise p"
                        "  WHERE p.investigation_id = :id AND p.company_id = s.seed"
                        "  AND p.status = 'disproven') ORDER BY n"
                    ),
                    {"id": investigation_id, "seeds": investigation["seed_company_ids"]},
                ).scalars()
            )
            row = (
                connection.execute(
                    text(
                        "INSERT INTO hypothesis (id, theme_id, investigation_id,"
                        " related_company_ids, author, draft_job_id) VALUES (:id, :theme,"
                        " :investigation, :related, :author, :job) RETURNING *"
                    ),
                    {
                        "id": hypothesis_id,
                        "theme": investigation["theme"],
                        "investigation": investigation_id,
                        "related": related,
                        "author": actor.name,
                        "job": job.id,
                    },
                )
                .mappings()
                .one()
            )
            record(
                connection,
                actor,
                "hypothesis.created",
                entity_type="hypothesis",
                entity_id=str(hypothesis_id),
                new_hash=content_hash(dict(row)),
            )
        return hypothesis_id

    def transition(
        self, actor: Actor, hypothesis_id: uuid.UUID, to: HypothesisStatus, note: str | None
    ) -> None:
        with self._engine.begin() as connection:
            hypothesis = _lock(connection, hypothesis_id)
            current: HypothesisStatus = hypothesis["status"]
            if to == "reviewed":
                raise InvalidTransition(
                    "a Hypothesis becomes reviewed only by publishing a version"
                )
            if to not in TRANSITIONS[current]:
                allowed = ", ".join(TRANSITIONS[current]) or "none (it is final)"
                raise InvalidTransition(f"{current} -> {to} is not allowed; allowed: {allowed}")
            if to == "evidence_ready" and _latest(connection, hypothesis_id) is None:
                raise InvalidTransition("the Editor hasn't drafted a version yet")
            _set_status(connection, actor, hypothesis, to, "transition", None, note)

    def correct(self, actor: Actor, hypothesis_id: uuid.UUID, correction: Correction) -> int:
        """A new version from the latest one with the researcher's changes; its number."""
        with self._engine.begin() as connection:
            hypothesis = _lock(connection, hypothesis_id)
            if hypothesis["status"] in ("closed", "rejected"):
                raise HypothesisConflict(f"the Hypothesis is {hypothesis['status']}")
            base = _latest(connection, hypothesis_id)
            if base is None:
                raise HypothesisConflict("the Editor hasn't drafted a version yet")
            if correction.based_on_version != base.version:
                raise HypothesisConflict(
                    f"version {correction.based_on_version} is not the latest ({base.version})"
                )
            content = base.content
            findings = content.findings
            if correction.findings is not None:
                run_id = connection.execute(
                    text("SELECT run_id FROM investigation WHERE id = :id"),
                    {"id": hypothesis["investigation_id"]},
                ).scalar_one()
                claims = (
                    []
                    if run_id is None
                    else accepted_claims(connection, hypothesis["investigation_id"], run_id)
                )
                findings, unsupported = resolve_findings(
                    correction.findings, claims, counterevidence_by_claim(content.contradictions)
                )
                if unsupported:
                    raise UnsupportedFindings(
                        "every finding must cite accepted Claims of the investigation: "
                        + "; ".join(f"{u.statement!r} {u.reason}" for u in unsupported)
                    )
            changes = {
                name: value
                for name, value in (
                    ("thesis_statement", correction.thesis_statement),
                    ("mechanism", correction.mechanism),
                    ("measurable_predictions", correction.measurable_predictions),
                    ("catalysts", correction.catalysts),
                    ("falsifiers", correction.falsifiers),
                    ("required_evidence", correction.required_evidence),
                    ("alternative_explanations", correction.alternative_explanations),
                    ("unresolved_questions", correction.unresolved_questions),
                )
                if value is not None
            }
            new_content = HypothesisContent.model_validate(
                content.model_dump() | changes | {"findings": findings}
            )
            number = base.version + 1
            version = insert_version(
                connection,
                hypothesis_id,
                number,
                origin="correction",
                based_on=base.version,
                content=new_content,
                provenance=base.provenance.model_copy(
                    update={"draft_run_id": None, "editor_role_call_id": None}
                ),
                note=correction.note,
                created_by=actor.name,
            )
            _touch(connection, hypothesis_id)
            record(
                connection,
                actor,
                "hypothesis.corrected" if base.published else "hypothesis.version_created",
                entity_type="hypothesis_version",
                entity_id=str(version.id),
                old_hash=base.content_sha256,
                new_hash=version.content_sha256,
            )
        return number

    def publish(
        self, actor: Actor, hypothesis_id: uuid.UUID, version_number: int, note: str | None
    ) -> None:
        with self._engine.begin() as connection:
            hypothesis = _lock(connection, hypothesis_id)
            latest = _latest(connection, hypothesis_id)
            if latest is None or latest.version != version_number:
                raise HypothesisConflict(
                    f"only the latest version ({latest.version if latest else 'none'})"
                    " can be published"
                )
            if latest.published:
                raise HypothesisConflict(f"version {version_number} is already published")
            current: HypothesisStatus = hypothesis["status"]
            if current not in PUBLISHABLE_FROM:
                raise InvalidTransition(
                    f"a {current} Hypothesis can't be published: it must be evidence_ready"
                    " (or, for a correction, reviewed or paper_tracking)"
                )
            failures = [
                failure
                for check in self._gate
                if (failure := check(connection, hypothesis, latest)) is not None
            ]
            if failures:
                raise PublishRefused(version_number, failures)
            published = (
                connection.execute(
                    text(
                        "UPDATE hypothesis_version SET published_at = now(),"
                        " published_by = :actor WHERE id = :id RETURNING *"
                    ),
                    {"id": latest.id, "actor": actor.name},
                )
                .mappings()
                .one()
            )
            connection.execute(
                text(
                    "UPDATE hypothesis SET first_published_at = coalesce(first_published_at,"
                    " :at) WHERE id = :id"
                ),
                {"id": hypothesis_id, "at": published["published_at"]},
            )
            to: HypothesisStatus = "reviewed" if current == "evidence_ready" else current
            _set_status(connection, actor, hypothesis, to, "publish", version_number, note)
            record(
                connection,
                actor,
                "hypothesis.version_published",
                entity_type="hypothesis_version",
                entity_id=str(latest.id),
                new_hash=latest.content_sha256,
            )
            # What it depends on: later Evidence against it proposes an update (ticket 21).
            record_dependencies(connection, latest)
            for hook in self._hooks:
                hook(connection, hypothesis, version_from_row(published), actor)

    def check_gate(self, hypothesis_id: uuid.UUID) -> "GateCheck":
        """What publishing the latest version would meet now, without publishing: why it
        can't be published at all (`blocked`), and every failed check of the gate."""
        with self._engine.connect() as connection:
            hypothesis = (
                connection.execute(
                    text("SELECT * FROM hypothesis WHERE id = :id"), {"id": hypothesis_id}
                )
                .mappings()
                .one_or_none()
            )
            if hypothesis is None:
                raise HypothesisNotFound("hypothesis not found")
            status: HypothesisStatus = hypothesis["status"]
            latest = _latest(connection, hypothesis_id)
            if latest is None:
                return GateCheck(None, status, "no_version", ())
            failures = tuple(
                failure
                for check in self._gate
                if (failure := check(connection, hypothesis, latest)) is not None
            )
        blocked: GateBlock | None = None
        if latest.published:
            blocked = "already_published"
        elif status not in PUBLISHABLE_FROM:
            blocked = "status_not_publishable"
        return GateCheck(latest.version, status, blocked, failures)


GateBlock = Literal["no_version", "already_published", "status_not_publishable"]


@dataclass(frozen=True)
class GateCheck:
    """The publish gate read for the latest version: `version` (None: no version yet),
    `blocked` (why it can't be published whatever the gate says) and the failed checks."""

    version: int | None
    status: HypothesisStatus
    blocked: GateBlock | None
    failures: tuple[GateFailure, ...]


# --- shared helpers -------------------------------------------------------------------------------


def insert_version(
    connection: Connection,
    hypothesis_id: uuid.UUID,
    number: int,
    *,
    origin: str,
    based_on: int | None,
    content: HypothesisContent,
    provenance: VersionProvenance,
    note: str | None,
    created_by: str,
) -> HypothesisVersion:
    row = (
        connection.execute(
            text(
                "INSERT INTO hypothesis_version (id, hypothesis_id, version, based_on_version,"
                " origin, content, content_sha256, provenance, note, created_by) VALUES (:id,"
                " :hypothesis, :version, :based_on, :origin, CAST(:content AS jsonb), :sha,"
                " CAST(:provenance AS jsonb), :note, :by) RETURNING *"
            ),
            {
                "id": uuid.uuid4(),
                "hypothesis": hypothesis_id,
                "version": number,
                "based_on": based_on,
                "origin": origin,
                "content": json.dumps(content.model_dump(mode="json")),
                "sha": content.sha256(),
                "provenance": provenance.model_dump_json(),
                "note": note,
                "by": created_by,
            },
        )
        .mappings()
        .one()
    )
    return version_from_row(row)


def _lock(connection: Connection, hypothesis_id: uuid.UUID) -> RowMapping:
    row = (
        connection.execute(
            text("SELECT * FROM hypothesis WHERE id = :id FOR UPDATE"), {"id": hypothesis_id}
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HypothesisNotFound("hypothesis not found")
    return row


def _latest(connection: Connection, hypothesis_id: uuid.UUID) -> HypothesisVersion | None:
    row = (
        connection.execute(
            text(
                "SELECT * FROM hypothesis_version WHERE hypothesis_id = :id"
                " ORDER BY version DESC LIMIT 1"
            ),
            {"id": hypothesis_id},
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else version_from_row(row)


def _touch(connection: Connection, hypothesis_id: uuid.UUID) -> None:
    connection.execute(
        text("UPDATE hypothesis SET updated_at = now() WHERE id = :id"), {"id": hypothesis_id}
    )


def _set_status(
    connection: Connection,
    actor: Actor,
    hypothesis: RowMapping,
    to: HypothesisStatus,
    action: str,
    version: int | None,
    note: str | None,
) -> None:
    new = (
        connection.execute(
            text(
                "UPDATE hypothesis SET status = :to, updated_at = now() WHERE id = :id RETURNING *"
            ),
            {"id": hypothesis["id"], "to": to},
        )
        .mappings()
        .one()
    )
    connection.execute(
        text(
            "INSERT INTO hypothesis_transition (hypothesis_id, from_status, to_status, action,"
            " version, actor, note) VALUES (:id, :from_status, :to, :action, :version, :actor,"
            " :note)"
        ),
        {
            "id": hypothesis["id"],
            "from_status": hypothesis["status"],
            "to": to,
            "action": action,
            "version": version,
            "actor": actor.name,
            "note": note,
        },
    )
    if action == "transition":
        record(
            connection,
            actor,
            "hypothesis.transitioned",
            entity_type="hypothesis",
            entity_id=str(hypothesis["id"]),
            old_hash=content_hash(dict(hypothesis)),
            new_hash=content_hash(dict(new)),
        )
