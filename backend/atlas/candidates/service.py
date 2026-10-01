"""Candidates: the read side, and the owner's commit and reject (spec §8.3; ticket 09).

- **Commit** (only a `lead`): the company joins the universe stored in the database (a
  `company` row, keyed like a config company, and a `universe_company` row in the
  Candidate's theme: atlas.companies `extend_universe`), and the Candidate becomes
  `investigating`. With a CIK its source path is `sec` and its `ingest` job is enqueued in
  the same transaction; without one the company has no source path and the Candidate
  records that no automated source exists yet. The owner may name the slug, display name,
  country (required when resolution found none) and layer, and, for a Candidate whose
  resolution offered several SEC entities, which CIK. The company's LEI and listings stay
  with identity review (ticket 02): a commit applies no CIK↔LEI link (a company without a
  CIK keeps the LEI that identified its Candidate). The ingest looks back
  `ATLAS_INGEST_LOOKBACK_DAYS`, like `atlas ingest`. When the company is already known as a
  **counterparty** (the same CIK, or the same LEI for a Candidate without a CIK), the commit
  promotes that row to a researched company instead of adding one (audited
  `company.promoted`): its ID, and so its Assertions and Relationships, stay; it keeps its
  slug and names unless the owner gives others.
- **Reject** (only a `lead`): the Candidate becomes `rejected` with the owner's reason.
- Candidates are never deleted (a database trigger refuses it), rejected ones included.
  Both actions are audited in their transaction.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine, text

from atlas.audit import Actor, content_hash, record
from atlas.companies import Layer, Universe, company_id_from, default_slug
from atlas.identity import Resolution
from atlas.jobs.queue import JobQueue
from atlas.ledger.ingest import INGEST_KIND, ingest_payload

type CandidateState = Literal[
    "lead",
    "investigating",
    "evidence_ready",
    "needs_more_evidence",
    "paper_tracking",
    "rejected",
    "closed",
]
CANDIDATE_STATES: tuple[CandidateState, ...] = (
    "lead",
    "investigating",
    "evidence_ready",
    "needs_more_evidence",
    "paper_tracking",
    "rejected",
    "closed",
)
_SLUG = r"^[a-z0-9][a-z0-9-]*$"


class CandidateLead(BaseModel):
    """A lead that named the Candidate's company, and how it named it."""

    lead_id: uuid.UUID
    canonical_url: str
    title: str
    snippet: str
    mentioned_as: str = Field(description="the name as the lead wrote it")
    ticker: str | None
    exchange: str | None
    mic: str | None = Field(description="the exchange's MIC, when Atlas knows the exchange")
    examined_at: datetime


class Candidate(BaseModel):
    id: uuid.UUID
    theme: str
    state: CandidateState
    name: str = Field(description="the resolved entity's name, else the name the lead used")
    identity_key: str = Field(description="cik:, lei: or (no single entity) name:")
    cik: str | None
    lei: str | None = Field(description="only when no CIK identified it")
    country: str | None
    tier: Literal["exact", "corroborated", "candidate", "conflict"]
    source_path: Literal["sec"] | None = Field(
        description="`sec` when a CIK was resolved; None: no automated source yet"
    )
    resolution: Resolution
    company_id: uuid.UUID | None = Field(description="the universe company, once committed")
    counterparty_company_id: uuid.UUID | None = Field(
        description=(
            "the counterparty company with this Candidate's CIK (else its LEI): the company a"
            " commit promotes"
        )
    )
    ingest_job_id: uuid.UUID | None
    ingest_note: str | None = Field(description="why no ingest was enqueued at commit")
    reject_reason: str | None
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime
    updated_at: datetime
    leads: list[CandidateLead]


class CandidateCommit(BaseModel):
    slug: str | None = Field(default=None, pattern=_SLUG, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"\S")
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    layer: Layer | None = None
    cik: str | None = Field(
        default=None,
        pattern=r"^[0-9]{10}$",
        description="which of the resolution's SEC entities, when it offered several",
    )
    note: str | None = Field(default=None, max_length=2000)


class CandidateReject(BaseModel):
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class CandidateDecided(BaseModel):
    candidate: Candidate
    audit_event_id: int


class CandidateRefused(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# --- reads ---


def _leads(connection: Connection, ids: list[uuid.UUID]) -> dict[uuid.UUID, list[CandidateLead]]:
    found: dict[uuid.UUID, list[CandidateLead]] = {each: [] for each in ids}
    if not ids:
        return found
    rows = connection.execute(
        text(
            "SELECT DISTINCT ON (m.candidate_id, m.lead_id) m.candidate_id, m.lead_id,"
            " l.canonical_url, l.title, l.snippet, m.name AS mentioned_as, m.ticker,"
            " m.exchange, m.mic, e.examined_at FROM lead_mention m"
            " JOIN lead l ON l.id = m.lead_id JOIN lead_examination e ON e.lead_id = m.lead_id"
            " WHERE m.candidate_id = ANY(:ids)"
            " ORDER BY m.candidate_id, m.lead_id, m.position"
        ),
        {"ids": ids},
    ).mappings()
    for row in rows:
        found[row["candidate_id"]].append(CandidateLead.model_validate(dict(row)))
    for leads in found.values():
        leads.sort(key=lambda lead: (lead.examined_at, str(lead.lead_id)))
    return found


def _candidate(row: Any, leads: list[CandidateLead]) -> Candidate:
    return Candidate.model_validate(dict(row) | {"leads": leads})


# A Candidate with the counterparty company it names, if any: the one `commit` promotes (the
# same CIK, or the same LEI for a Candidate without a CIK).
_CANDIDATES = """
    SELECT candidate.*, (
        SELECT k.id FROM company k WHERE k.role = 'counterparty' AND CASE
            WHEN candidate.cik IS NOT NULL THEN k.cik = candidate.cik
            ELSE k.lei = candidate.lei END
        ORDER BY k.created_at, k.id LIMIT 1) AS counterparty_company_id
    FROM candidate
"""


def get_candidate(connection: Connection, candidate_id: uuid.UUID) -> Candidate | None:
    row = (
        connection.execute(text(f"{_CANDIDATES} WHERE id = :id"), {"id": candidate_id})
        .mappings()
        .one_or_none()
    )
    return None if row is None else _candidate(row, _leads(connection, [candidate_id])[row["id"]])


def list_candidates(
    connection: Connection,
    *,
    state: CandidateState | None,
    theme: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Candidate], int]:
    """Candidates, newest first, optionally in one state or theme; and how many in all."""
    where = (
        " WHERE (CAST(:state AS text) IS NULL OR state = :state)"
        " AND (CAST(:theme AS text) IS NULL OR theme = :theme)"
    )
    params = {"state": state, "theme": theme}
    total = connection.execute(
        text(f"SELECT count(*) FROM candidate{where}"),  # noqa: S608 (constant SQL)
        params,
    ).scalar_one()
    rows = (
        connection.execute(
            text(f"{_CANDIDATES}{where} ORDER BY created_at DESC, id LIMIT :limit OFFSET :offset"),
            params | {"limit": limit, "offset": offset},
        )
        .mappings()
        .all()
    )
    leads = _leads(connection, [row["id"] for row in rows])
    return [_candidate(row, leads[row["id"]]) for row in rows], int(total)


# --- the owner's decisions ---


_STATE_COLUMNS = ("state", "company_id", "ingest_job_id", "ingest_note", "reject_reason")


class Candidates:
    def __init__(
        self,
        engine: Engine,
        actor: Actor,
        universe: Universe,
        *,
        ingest_lookback_days: int,
        queue: JobQueue | None = None,
    ) -> None:
        self._engine = engine
        self._actor = actor
        self._universe = universe
        self._lookback = timedelta(days=ingest_lookback_days)
        self._queue = queue or JobQueue(engine, actor=actor)

    def _lead(self, connection: Connection, candidate_id: uuid.UUID) -> dict[str, Any]:
        row = (
            connection.execute(
                text("SELECT * FROM candidate WHERE id = :id FOR UPDATE"), {"id": candidate_id}
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise CandidateRefused(404, "not_found", "candidate not found")
        if row["state"] != "lead":
            raise CandidateRefused(
                409,
                "invalid_transition",
                f"the Candidate is {row['state']}; only a lead can be committed or rejected",
            )
        return dict(row)

    def _decide(
        self,
        connection: Connection,
        before: dict[str, Any],
        action: str,
        changes: dict[str, Any],
        note: str | None,
    ) -> int:
        connection.execute(
            text(
                "UPDATE candidate SET state = :state, company_id = :company_id,"
                " ingest_job_id = :ingest_job_id, ingest_note = :ingest_note,"
                " reject_reason = :reject_reason, decided_by = :actor, decided_at = now(),"
                " decision_note = :note, updated_at = now() WHERE id = :id"
            ),
            {
                **{column: before[column] for column in _STATE_COLUMNS},
                **changes,
                "actor": self._actor.name,
                "note": note,
                "id": before["id"],
            },
        )
        old = {column: before[column] for column in _STATE_COLUMNS}
        return record(
            connection,
            self._actor,
            f"candidate.{action}",
            entity_type="candidate",
            entity_id=str(before["id"]),
            old_hash=content_hash(old),
            new_hash=content_hash(old | changes | {"note": note}),
        ).id

    def _decided(self, candidate_id: uuid.UUID, event_id: int) -> CandidateDecided:
        with self._engine.connect() as connection:
            found = get_candidate(connection, candidate_id)
        assert found is not None
        return CandidateDecided(candidate=found, audit_event_id=event_id)

    def reject(self, candidate_id: uuid.UUID, request: CandidateReject) -> CandidateDecided:
        with self._engine.begin() as connection:
            before = self._lead(connection, candidate_id)
            reason = request.reason.strip()
            event_id = self._decide(
                connection, before, "rejected", {"state": "rejected", "reject_reason": reason}, None
            )
        return self._decided(candidate_id, event_id)

    def commit(self, candidate_id: uuid.UUID, request: CandidateCommit) -> CandidateDecided:
        with self._engine.begin() as connection:
            before = self._lead(connection, candidate_id)
            resolution = Resolution.model_validate(before["resolution"])
            cik = self._cik(before, resolution, request.cik)
            name: str = before["name"]
            if request.cik is not None and cik != before["cik"]:
                chosen = [c for c in resolution.candidates if c.cik == cik]
                name = chosen[0].name if chosen else name
            counterparty = self._counterparty(connection, cik, before["lei"])
            country = request.country or before["country"]
            if country is None and counterparty is not None:
                country = counterparty["country"]
            if country is None:
                raise CandidateRefused(
                    409,
                    "country_required",
                    "entity resolution found no country for this company: name one (`country`)",
                )
            if counterparty is not None:
                company_id, slug = self._promote(connection, counterparty, request, cik, country)
            else:
                slug = request.slug or default_slug(request.display_name or name)
                self._not_in_universe(connection, slug, cik)
                company_id = company_id_from(slug, cik)
                company: dict[str, Any] = {
                    "slug": slug,
                    "legal_name": name,
                    "display_name": request.display_name or name,
                    "cik": cik,
                    "lei": None if cik else before["lei"],
                    "country": country,
                    "layer": request.layer,
                    "source_path": "sec" if cik else None,
                }
                connection.execute(
                    text(
                        "INSERT INTO company (id, slug, legal_name, display_name, cik, lei,"
                        " country, layer, source_path) VALUES (:id, :slug, :legal_name,"
                        " :display_name, :cik, :lei, :country, :layer, :source_path)"
                    ),
                    {"id": company_id, **company},
                )
                record(
                    connection,
                    self._actor,
                    "company.created",
                    entity_type="company",
                    entity_id=str(company_id),
                    new_hash=content_hash(company),
                )
            connection.execute(
                text(
                    "INSERT INTO universe_company (theme, company_id, candidate_id, added_by)"
                    " VALUES (:theme, :company, :candidate, :actor)"
                ),
                {
                    "theme": before["theme"],
                    "company": company_id,
                    "candidate": candidate_id,
                    "actor": self._actor.name,
                },
            )
            changes: dict[str, Any] = {"state": "investigating", "company_id": company_id}
            if cik is not None:
                enqueued = self._queue.enqueue_within(
                    connection,
                    INGEST_KIND,
                    f"candidate-commit:{candidate_id}",
                    # The lookback `atlas ingest` uses by default (ATLAS_INGEST_LOOKBACK_DAYS).
                    ingest_payload(slug, None, None, datetime.now(UTC) - self._lookback),
                )
                changes["ingest_job_id"] = enqueued.job.id
            else:
                changes["ingest_note"] = (
                    "no automated source exists yet: entity resolution found no CIK (not an"
                    " SEC filer), and exchange feeds are ingested only for configured companies"
                )
            event_id = self._decide(connection, before, "committed", changes, request.note)
        return self._decided(candidate_id, event_id)

    def _cik(
        self, candidate: dict[str, Any], resolution: Resolution, requested: str | None
    ) -> str | None:
        if requested is None or requested == candidate["cik"]:
            return candidate["cik"]
        offered = {c.cik for c in resolution.candidates if c.cik}
        if candidate["cik"] is not None or requested not in offered:
            raise CandidateRefused(
                409,
                "cik_not_offered",
                f"CIK {requested} isn't one of the SEC entities entity resolution offered"
                f" ({', '.join(sorted(offered)) or 'none'})",
            )
        return requested

    def _counterparty(
        self, connection: Connection, cik: str | None, lei: str | None
    ) -> dict[str, Any] | None:
        """The counterparty company the Candidate's identifier names (its CIK, else its LEI)."""
        row = (
            connection.execute(
                text(
                    "SELECT id, slug, display_name, country, layer, source_path, role"
                    " FROM company WHERE role = 'counterparty' AND CASE"
                    " WHEN CAST(:cik AS text) IS NOT NULL THEN cik = :cik ELSE lei = :lei END"
                    " ORDER BY created_at, id LIMIT 1 FOR UPDATE"
                ),
                {"cik": cik, "lei": lei},
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else dict(row)

    def _promote(
        self,
        connection: Connection,
        counterparty: dict[str, Any],
        request: CandidateCommit,
        cik: str | None,
        country: str,
    ) -> tuple[uuid.UUID, str]:
        """Make the counterparty a researched company in place; its ID and slug."""
        company_id: uuid.UUID = counterparty.pop("id")
        slug: str = request.slug or counterparty["slug"]
        after: dict[str, Any] = {
            "slug": slug,
            "display_name": request.display_name or counterparty["display_name"],
            "country": country,
            "layer": request.layer,
            "source_path": "sec" if cik else None,
            "role": "researched",
        }
        if slug != counterparty["slug"]:
            self._slug_free(connection, slug)
        connection.execute(
            text(
                "UPDATE company SET slug = :slug, display_name = :display_name,"
                " country = :country, layer = :layer, source_path = :source_path, role = :role,"
                " updated_at = now() WHERE id = :id"
            ),
            {"id": company_id, **after},
        )
        record(
            connection,
            self._actor,
            "company.promoted",
            entity_type="company",
            entity_id=str(company_id),
            old_hash=content_hash(counterparty),
            new_hash=content_hash(after),
        )
        return company_id, slug

    def _not_in_universe(self, connection: Connection, slug: str, cik: str | None) -> None:
        configured = self._universe.companies
        if cik is not None:
            owner = connection.execute(
                text("SELECT slug FROM company WHERE cik = :cik"), {"cik": cik}
            ).scalar_one_or_none()
            owner = owner or next((s for s, c in configured.items() if c.cik == cik), None)
            if owner is not None:
                raise CandidateRefused(
                    409,
                    "already_in_universe",
                    f"CIK {cik} is already the universe company {owner!r}",
                )
        self._slug_free(connection, slug)

    def _slug_free(self, connection: Connection, slug: str) -> None:
        taken = connection.execute(
            text("SELECT 1 FROM company WHERE slug = :slug"), {"slug": slug}
        ).one_or_none()
        if taken is not None or slug in self._universe.companies:
            raise CandidateRefused(
                409, "slug_taken", f"the slug {slug!r} is taken: choose another (`slug`)"
            )
