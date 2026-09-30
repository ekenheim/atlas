"""The `check_contradictions` job: deterministic, no LLM (so not pausable).

It reads the event its hook enqueued (atlas.proposed_updates.triggers) and works out the
contradicting Evidence and the Assertions it bears on:

- `assertion_reviewed`: the Assertion, if it is still disputed, rejected or superseded (a
  superseded one's successor is where the contradicting statement is);
- `relationship_rejected`: the Relationship's supporting Assertions, if it is still rejected;
- `source_revised`: the Assertions quoting an earlier version of the revised Source Document
  whose quote the new version's parsed text **no longer contains** (a revision that still
  states them contradicts nothing; one without parsed text can't be compared, and proposes
  nothing);
- `counterevidence`: the Assertions stating the span (same Source Version and offsets) of a
  Claim the accepted, independent counterevidence contradicts.

Each Hypothesis whose **latest published version** depends on one of those Assertions gets
one proposed update for the event (unique per version and event, so a retried job adds
nothing), listing the Evidence, the findings it bears on and the open Candidates it concerns
(those committed as the Hypothesis's related companies or the contradicted Assertions'
parties, in its theme). It's audited `proposed_update.created`. The published version and its
Research Snapshot are only read.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast, get_args

from pydantic import JsonValue
from sqlalchemy import Connection, Engine, RowMapping, text

from atlas.archive import Archive, open_archive
from atlas.audit import Actor, content_hash, record
from atlas.db.engine import create_engine
from atlas.hypotheses.model import version_from_row
from atlas.jobs.handlers import HandlerRegistry
from atlas.jobs.queue import Artifacts, Job
from atlas.proposed_updates.model import AffectedFinding, ContradictingEvidence
from atlas.proposed_updates.triggers import (
    CHECK_CONTRADICTIONS_KIND,
    CONTRADICTING_STATES,
    Trigger,
    trigger_key,
)
from atlas.settings import Settings

DETECTOR_ACTOR = Actor("atlas-contradictions")
_PARSED = ("parsed", "incomplete")


@dataclass(frozen=True)
class _Found:
    """The event's Evidence, and a one-line summary (`{version}` is the version's number)."""

    evidence: list[ContradictingEvidence]
    summary: str


class ContradictionCheck:
    def __init__(self, engine: Engine, archive: Archive) -> None:
        self._engine = engine
        self._archive = archive

    def run(self, job: Job) -> Artifacts:
        named = job.payload.get("trigger")
        if named not in get_args(Trigger):
            raise ValueError(f"unknown trigger {named!r}: one of {', '.join(get_args(Trigger))}")
        trigger = cast(Trigger, named)
        ref = uuid.UUID(str(job.payload["id"]))
        state = job.payload.get("state")
        key = trigger_key(trigger, ref, None if state is None else str(state))
        with self._engine.begin() as connection:
            found, skipped = self._find(connection, trigger, ref)
            if found is None:
                return {"proposed_update_ids": [], "skipped": skipped}
            created = self._propose(connection, job, trigger, key, found)
        return {"proposed_update_ids": [str(each) for each in created], "skipped": None}

    # --- the events' Evidence ---------------------------------------------------------------------

    def _find(
        self, connection: Connection, trigger: Trigger, ref: uuid.UUID
    ) -> tuple[_Found | None, str | None]:
        if trigger == "assertion_reviewed":
            return _reviewed_assertion(connection, ref)
        if trigger == "relationship_rejected":
            return _rejected_relationship(connection, ref)
        if trigger == "source_revised":
            return self._revised_source(connection, ref)
        return _counterevidence(connection, ref)

    def _revised_source(
        self, connection: Connection, version_id: uuid.UUID
    ) -> tuple[_Found | None, str | None]:
        new = (
            connection.execute(
                text(
                    "SELECT v.id, v.version_number, v.source_document_id, v.parse_status,"
                    " v.parsed_object_uri, coalesce(d.title, d.canonical_url) AS title"
                    " FROM source_version v JOIN source_document d ON d.id = v.source_document_id"
                    " WHERE v.id = :id"
                ),
                {"id": version_id},
            )
            .mappings()
            .one()
        )
        cited = list(
            connection.execute(
                text(
                    "SELECT DISTINCT a.id, a.quote, a.source_version_id"
                    " FROM hypothesis_dependency d"
                    " JOIN assertion a ON a.id = d.ref_id"
                    " JOIN source_version old ON old.id = a.source_version_id"
                    " WHERE d.kind = 'assertion' AND old.source_document_id = :document"
                    " AND old.version_number < :number ORDER BY a.id"
                ),
                {"document": new["source_document_id"], "number": new["version_number"]},
            ).mappings()
        )
        if not cited:
            return None, "no published version quotes an earlier version of the document"
        if new["parse_status"] not in _PARSED or new["parsed_object_uri"] is None:
            return None, f"the revision has no parsed text ({new['parse_status']}) to compare"
        revised = self._archive.get(new["parsed_object_uri"]).decode("utf-8")
        withdrawn = [each for each in cited if each["quote"] not in revised]
        if not withdrawn:
            return None, "the revision still states every quote the published versions cite"
        evidence = [
            ContradictingEvidence(
                kind="source_version",
                id=new["id"],
                description=f"Version {new['version_number']} of {new['title']} no longer"
                f" contains the quoted statement: {each['quote']!r}",
                state=None,
                note=None,
                assertion_id=None,
                source_version_id=new["id"],
                quote=None,
                revises_source_version_id=each["source_version_id"],
                contradicts_assertion_ids=[each["id"]],
            )
            for each in withdrawn
        ]
        count = len(withdrawn)
        return _Found(
            evidence,
            f"A revised version of {new['title']} no longer states {count} quote"
            f"{'s' if count > 1 else ''} version {{version}} cites.",
        ), None

    # --- proposing --------------------------------------------------------------------------------

    def _propose(
        self, connection: Connection, job: Job, trigger: Trigger, key: str, found: _Found
    ) -> list[uuid.UUID]:
        contradicted = list(
            dict.fromkeys(a for e in found.evidence for a in e.contradicts_assertion_ids)
        )
        targets = connection.execute(
            text(
                "WITH latest AS (SELECT DISTINCT ON (hypothesis_id) * FROM hypothesis_version"
                "  WHERE published_at IS NOT NULL ORDER BY hypothesis_id, version DESC)"
                " SELECT l.* FROM latest l WHERE EXISTS (SELECT FROM hypothesis_dependency d"
                "  WHERE d.hypothesis_version_id = l.id AND d.kind = 'assertion'"
                "  AND d.ref_id = ANY(CAST(:ids AS uuid[])))"
                " ORDER BY l.hypothesis_id"
            ),
            {"ids": contradicted},
        ).mappings()
        created: list[uuid.UUID] = []
        for row in list(targets):
            proposed = self._propose_one(connection, job, trigger, key, found, row)
            if proposed is not None:
                created.append(proposed)
        return created

    def _propose_one(
        self,
        connection: Connection,
        job: Job,
        trigger: Trigger,
        key: str,
        found: _Found,
        row: RowMapping,
    ) -> uuid.UUID | None:
        version = version_from_row(row)
        depends = {span.assertion_id for f in version.content.findings for span in f.source_spans}
        evidence = [
            each.model_copy(
                update={
                    "contradicts_assertion_ids": [
                        a for a in each.contradicts_assertion_ids if a in depends
                    ]
                }
            )
            for each in found.evidence
        ]
        evidence = [each for each in evidence if each.contradicts_assertion_ids]
        against = {a for each in evidence for a in each.contradicts_assertion_ids}
        affected = [
            AffectedFinding(
                index=index,
                claim_text=finding.claim_text,
                assertion_ids=list(
                    dict.fromkeys(
                        s.assertion_id for s in finding.source_spans if s.assertion_id in against
                    )
                ),
            )
            for index, finding in enumerate(version.content.findings)
            if any(s.assertion_id in against for s in finding.source_spans)
        ]
        hypothesis = (
            connection.execute(
                text("SELECT theme_id, related_company_ids FROM hypothesis WHERE id = :id"),
                {"id": row["hypothesis_id"]},
            )
            .mappings()
            .one()
        )
        candidates = list(
            connection.execute(
                text(
                    "SELECT id FROM candidate WHERE theme = :theme"
                    " AND state NOT IN ('rejected', 'closed') AND company_id IN ("
                    "  SELECT unnest(CAST(:related AS uuid[]))"
                    "  UNION SELECT subject_company_id FROM assertion"
                    "   WHERE id = ANY(CAST(:ids AS uuid[]))"
                    "  UNION SELECT object_company_id FROM assertion"
                    "   WHERE id = ANY(CAST(:ids AS uuid[])))"
                    " ORDER BY created_at, id"
                ),
                {
                    "theme": hypothesis["theme_id"],
                    "related": hypothesis["related_company_ids"],
                    "ids": list(against),
                },
            ).scalars()
        )
        inserted = (
            connection.execute(
                text(
                    "INSERT INTO proposed_update (id, hypothesis_id, hypothesis_version_id,"
                    " trigger, trigger_key, summary, evidence, affected_findings, candidate_ids,"
                    " detected_by_job_id) VALUES (:id, :hypothesis, :version, :trigger, :key,"
                    " :summary, CAST(:evidence AS jsonb), CAST(:affected AS jsonb), :candidates,"
                    " :job) ON CONFLICT (hypothesis_version_id, trigger_key) DO NOTHING"
                    " RETURNING *"
                ),
                {
                    "id": uuid.uuid4(),
                    "hypothesis": row["hypothesis_id"],
                    "version": version.id,
                    "trigger": trigger,
                    "key": key,
                    "summary": found.summary.format(version=version.version),
                    "evidence": _json([e.model_dump(mode="json") for e in evidence]),
                    "affected": _json([a.model_dump(mode="json") for a in affected]),
                    "candidates": candidates,
                    "job": job.id,
                },
            )
            .mappings()
            .one_or_none()
        )
        if inserted is None:
            return None  # an earlier attempt proposed it
        record(
            connection,
            DETECTOR_ACTOR,
            "proposed_update.created",
            entity_type="proposed_update",
            entity_id=str(inserted["id"]),
            new_hash=content_hash(dict(inserted)),
        )
        return inserted["id"]


def _reviewed_assertion(
    connection: Connection, assertion_id: uuid.UUID
) -> tuple[_Found | None, str | None]:
    row = (
        connection.execute(
            text(
                "SELECT a.id, a.verification_status, a.superseded_by, a.source_version_id,"
                " a.quote, a.reviewer_id, s.source_version_id AS successor_source_version_id,"
                " s.quote AS successor_quote FROM assertion a"
                " LEFT JOIN assertion s ON s.id = a.superseded_by WHERE a.id = :id"
            ),
            {"id": assertion_id},
        )
        .mappings()
        .one()
    )
    state = row["verification_status"]
    if state not in CONTRADICTING_STATES:
        return None, f"the Assertion is {state} again"
    successor = row["superseded_by"]
    description = (
        f"The Assertion was superseded by Assertion {successor}: {row['successor_quote']!r}"
        if successor is not None
        else f"The Assertion {row['quote']!r} was reviewed {state} by {row['reviewer_id']}"
    )
    evidence = ContradictingEvidence(
        kind="assertion",
        id=row["id"],
        description=description,
        state=state,
        note=None,
        assertion_id=successor,
        source_version_id=row["successor_source_version_id"]
        if successor is not None
        else row["source_version_id"],
        quote=row["successor_quote"] if successor is not None else row["quote"],
        revises_source_version_id=None,
        contradicts_assertion_ids=[row["id"]],
    )
    return _Found([evidence], f"An Assertion version {{version}} cites is now {state}."), None


def _rejected_relationship(
    connection: Connection, relationship_id: uuid.UUID
) -> tuple[_Found | None, str | None]:
    row = (
        connection.execute(
            text(
                "SELECT r.id, r.review_state, r.reviewed_by, r.review_note, r.predicate,"
                " s.display_name AS subject, coalesce(o.display_name, r.object_text) AS object,"
                " array_agg(ra.assertion_id ORDER BY ra.assertion_id) AS assertion_ids"
                " FROM relationship r JOIN company s ON s.id = r.subject_company_id"
                " LEFT JOIN company o ON o.id = r.object_company_id"
                " JOIN relationship_assertion ra ON ra.relationship_id = r.id"
                " WHERE r.id = :id GROUP BY r.id, s.display_name, o.display_name"
            ),
            {"id": relationship_id},
        )
        .mappings()
        .one()
    )
    if row["review_state"] != "rejected":
        return None, f"the Relationship is {row['review_state']} again"
    edge = f"{row['subject']} {row['predicate']} {row['object']}"
    evidence = ContradictingEvidence(
        kind="relationship",
        id=row["id"],
        description=f"The owner ({row['reviewed_by']}) rejected the Relationship {edge}",
        state="rejected",
        note=row["review_note"],
        assertion_id=None,
        source_version_id=None,
        quote=None,
        revises_source_version_id=None,
        contradicts_assertion_ids=list(row["assertion_ids"]),
    )
    return _Found(
        [evidence], f"The owner rejected the Relationship {edge} version {{version}} depends on."
    ), None


def _counterevidence(
    connection: Connection, counterevidence_id: uuid.UUID
) -> tuple[_Found | None, str | None]:
    row = (
        connection.execute(
            text(
                "SELECT id, assertion_id, source_version_id, quote, statement, checklist_item,"
                " independent, outcome, contradicts_claim_ids FROM counterevidence WHERE id = :id"
            ),
            {"id": counterevidence_id},
        )
        .mappings()
        .one()
    )
    if row["outcome"] != "accepted" or not row["independent"]:
        return None, "the counterevidence is not accepted and independent"
    # The Assertions stating the contradicted Claims' spans (in any investigation).
    stating: Sequence[uuid.UUID] = list(
        connection.execute(
            text(
                "SELECT DISTINCT da.id FROM claim c JOIN assertion ca ON ca.id = c.assertion_id"
                " JOIN assertion da ON da.source_version_id = ca.source_version_id"
                "  AND da.span_start = ca.span_start AND da.span_end = ca.span_end"
                " WHERE c.id = ANY(CAST(:claims AS uuid[])) ORDER BY da.id"
            ),
            {"claims": row["contradicts_claim_ids"]},
        ).scalars()
    )
    evidence = ContradictingEvidence(
        kind="counterevidence",
        id=row["id"],
        description=f"Independent counterevidence ({row['checklist_item']}): {row['statement']}",
        state=None,
        note=None,
        assertion_id=row["assertion_id"],
        source_version_id=row["source_version_id"],
        quote=row["quote"],
        revises_source_version_id=None,
        contradicts_assertion_ids=list(stating),
    )
    return _Found(
        [evidence],
        f"Independent counterevidence ({row['checklist_item']}) contradicts a statement"
        " version {version} cites.",
    ), None


def _json(value: JsonValue) -> str:
    return json.dumps(value)


def register_proposed_update_handlers(registry: HandlerRegistry, settings: Settings) -> None:
    def check_contradictions(job: Job) -> Artifacts:
        engine = create_engine(settings)
        try:
            return ContradictionCheck(engine, open_archive(settings)).run(job)
        finally:
            engine.dispose()

    # Deterministic: no LLM or Hindsight call, so never paused.
    registry.register(CHECK_CONTRADICTIONS_KIND, check_contradictions)
