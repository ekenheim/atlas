"""Entity resolution against the universe: look up, store, review.

- `resolve_mention(connection, resolver, mention)`: the universe first (a company by CIK or
  LEI, a listing by ISIN or by ticker on its venue valid at `as_of`, a legal, display or
  alias name valid at `as_of`); only an unknown company goes to the external sources. The
  result's `company_id` says which universe company it is (None: an unseeded company). This
  is what Candidates from leads call.
- `resolve_universe`: resolve each configured company and store every proposal as an
  `identity_mapping` row: exact and corroborated ones are committed (applied to `company` /
  `security`) at once, the rest wait as `pending`. A CIK↔LEI link always waits for the owner.
  Stored mappings are never re-proposed: a rerun only adds what is new.
- `IdentityMappings`: the owner confirms (applying it) or rejects (with a reason) a pending
  mapping. Every change is audited in the same transaction.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.expression import bindparam

from atlas.audit import Actor, content_hash, record
from atlas.companies import Universe
from atlas.identity.normalize import canonical_ticker, normalize_name, operating_mic
from atlas.identity.resolver import (
    Alias,
    Entity,
    EntityResolver,
    Fact,
    Mention,
    Proposal,
    Resolution,
)

_NAMESPACE = uuid.UUID("3a0f4f0e-5b1d-4d53-9c61-2f7e8d1b6a90")

type ReviewState = Literal["committed", "pending", "confirmed", "rejected"]


# --- the universe first ---


def _local_resolution(
    mention: Mention, company: dict[str, Any], matched_by: str, *, exact: bool
) -> Resolution:
    reasons = [] if exact else [f"matched the universe by {matched_by} only"]
    return Resolution(
        mention=mention,
        tier="exact" if exact else "candidate",
        entity=Entity(name=company["legal_name"], cik=company["cik"], lei=company["lei"]),
        candidates=[],
        proposals=[],
        review_reasons=reasons,
        notes=[],
        evidence=[],
        dropped=[],
        company_id=str(company["id"]),
        matched_by=matched_by,
    )


def find_in_universe(connection: Connection, mention: Mention) -> Resolution | None:
    """The universe company `mention` names, without any network call; None if unknown."""
    as_of = mention.as_of or datetime.now(UTC).date()
    companies = {
        row["id"]: dict(row)
        for row in connection.execute(
            text("SELECT id, slug, legal_name, display_name, cik, lei FROM company")
        ).mappings()
    }

    def one(ids: set[uuid.UUID], matched_by: str, *, exact: bool) -> Resolution | None:
        if len(ids) == 1:
            return _local_resolution(mention, companies[ids.pop()], matched_by, exact=exact)
        return None

    if mention.cik and mention.cik.strip().isdigit():
        cik = mention.cik.strip().zfill(10)
        found = one({i for i, c in companies.items() if c["cik"] == cik}, "cik", exact=True)
        if found:
            return found
    if mention.lei:
        lei = mention.lei.strip().upper()
        found = one({i for i, c in companies.items() if c["lei"] == lei}, "lei", exact=True)
        if found:
            return found
    listings = connection.execute(
        text(
            "SELECT company_id, ticker, exchange_mic, isin FROM security"
            " WHERE daterange(valid_from, valid_to, '[)') @> CAST(:as_of AS date)"
        ),
        {"as_of": as_of},
    ).mappings()
    rows = [dict(r) for r in listings]
    if mention.isin:
        isin = mention.isin.strip().upper()
        found = one({r["company_id"] for r in rows if r["isin"] == isin}, "isin", exact=True)
        if found:
            return found
    if mention.ticker:
        ticker = canonical_ticker(mention.ticker)
        on_ticker = [r for r in rows if r["ticker"] == ticker]
        if mention.mic:
            mic = operating_mic(mention.mic.strip().upper())
            found = one(
                {r["company_id"] for r in on_ticker if r["exchange_mic"] == mic},
                "ticker and venue",
                exact=True,
            )
            if found:
                return found
        else:
            found = one({r["company_id"] for r in on_ticker}, "ticker", exact=False)
            if found:
                return found
    if mention.name:
        wanted = normalize_name(mention.name)
        by_name = {
            i
            for i, c in companies.items()
            if wanted in (normalize_name(c["legal_name"]), normalize_name(c["display_name"]))
        }
        found = one(by_name, "name", exact=False)
        if found:
            return found
        aliases = connection.execute(
            text(
                "SELECT company_id, kind FROM company_alias WHERE normalized_name = :name"
                " AND (valid_from IS NULL OR valid_from <= :as_of)"
                " AND (valid_to IS NULL OR :as_of < valid_to)"
            ),
            {"name": wanted, "as_of": as_of},
        ).mappings()
        hits = [dict(a) for a in aliases]
        kind = "former name" if any(a["kind"] == "former" for a in hits) else "alias"
        found = one({a["company_id"] for a in hits}, kind, exact=False)
        if found:
            return found
    return None


def resolve_mention(
    connection: Connection,
    resolver: EntityResolver,
    mention: Mention,
    *,
    ignored_ciks: frozenset[str] = frozenset(),
) -> Resolution:
    """Resolve a company mention (e.g. from a lead): the universe first, else the external
    sources. `company_id` is set when the company is in the universe."""
    local = find_in_universe(connection, mention)
    if local is not None:
        return local
    resolution = resolver.resolve(mention, ignored_ciks=ignored_ciks)
    entity = resolution.entity
    if entity is not None and resolution.tier != "conflict":
        known = find_in_universe(
            connection, Mention(cik=entity.cik, lei=entity.lei, as_of=mention.as_of)
        )
        if known is not None and known.company_id is not None:
            return resolution.model_copy(
                update={"company_id": known.company_id, "matched_by": known.matched_by}
            )
    return resolution


# --- storing a company's resolution ---


class IdentityConflict(Exception):
    """Applying a mapping would contradict what the company or another company holds."""


def _mapping_id(company_id: uuid.UUID, kind: str, value: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"identity_mapping:{company_id}:{kind}:{value}")


def _alias_id(company_id: uuid.UUID, alias: Alias) -> uuid.UUID:
    key = f"{company_id}:{alias.source}:{alias.kind}:{alias.name}:{alias.valid_from}"
    return uuid.uuid5(_NAMESPACE, f"company_alias:{key}")


@dataclass
class Stored:
    committed: int = 0
    pending: int = 0
    unchanged: int = 0
    aliases: int = 0
    held: list[str] = field(default_factory=list[str])  # auto-commits held for review


def _insert_aliases(
    connection: Connection,
    actor: Actor,
    company_id: uuid.UUID,
    aliases: list[Alias],
    url: str,
    observed_at: datetime,
) -> int:
    created = 0
    for alias in aliases:
        alias_id = _alias_id(company_id, alias)
        row = connection.execute(
            text(
                "INSERT INTO company_alias (id, company_id, name, normalized_name, kind,"
                " valid_from, valid_to, source, source_url, observed_at)"
                " VALUES (:id, :company, :name, :normalized, :kind, :valid_from, :valid_to,"
                " :source, :url, :observed_at) ON CONFLICT DO NOTHING RETURNING id"
            ),
            {
                "id": alias_id,
                "company": company_id,
                "name": alias.name,
                "normalized": normalize_name(alias.name),
                "kind": alias.kind,
                "valid_from": alias.valid_from,
                "valid_to": alias.valid_to,
                "source": alias.source,
                "url": url,
                "observed_at": observed_at,
            },
        ).one_or_none()
        if row is not None:
            created += 1
            record(
                connection,
                actor,
                "company_alias.created",
                entity_type="company_alias",
                entity_id=str(alias_id),
                new_hash=content_hash(alias.model_dump()),
            )
    return created


def _security_id(company_id: uuid.UUID, ticker: str, mic: str, valid_from: date) -> uuid.UUID:
    # The same key atlas.companies uses for config securities.
    namespace = uuid.UUID("8f5d2c1e-7b43-4c1a-9e0d-6a3b2f1c4d57")
    return uuid.uuid5(namespace, f"security:{company_id}:{mic}:{ticker}:{valid_from}")


_SECURITY_COLUMNS = (
    "company_id, ticker, exchange_mic, segment_mic, isin, figi, share_class_figi,"
    " instrument_type, currency, valid_from, valid_to, review_state"
)


def _apply_listing(
    connection: Connection,
    actor: Actor,
    company_id: uuid.UUID,
    details: dict[str, Any],
    observed_on: date,
    *,
    by_owner: bool,
) -> uuid.UUID:
    ticker, mic = details["ticker"], details["exchange_mic"]
    current = (
        connection.execute(
            text(
                f"SELECT id, {_SECURITY_COLUMNS} FROM security"  # noqa: S608 (constant columns)
                " WHERE exchange_mic = :mic AND ticker = :ticker"
                " AND daterange(valid_from, valid_to, '[)') @> CAST(:on AS date) FOR UPDATE"
            ),
            {"mic": mic, "ticker": ticker, "on": observed_on},
        )
        .mappings()
        .one_or_none()
    )
    review_state = "reviewed" if by_owner else "unreviewed"
    if current is not None:
        if current["company_id"] != company_id:
            raise IdentityConflict(f"{ticker} on {mic} is another company's listing")
        before = dict(current)
        security_id: uuid.UUID = before.pop("id")
        after = before | {
            "segment_mic": details.get("segment_mic") or before["segment_mic"],
            "figi": details.get("figi") or before["figi"],
            "share_class_figi": details.get("share_class_figi") or before["share_class_figi"],
        }
        if by_owner:
            after["review_state"] = "reviewed"
        if after != before:
            connection.execute(
                text(
                    "UPDATE security SET segment_mic = :segment_mic, figi = :figi,"
                    " share_class_figi = :share_class_figi, review_state = :review_state"
                    " WHERE id = :id"
                ),
                {"id": security_id, **after},
            )
            record(
                connection,
                actor,
                "security.updated",
                entity_type="security",
                entity_id=str(security_id),
                old_hash=content_hash(before),
                new_hash=content_hash(after),
            )
        return security_id
    currency = details.get("currency")
    if not currency:
        raise IdentityConflict(f"no currency is known for {mic}: set the listing by hand")
    # No source gives a listing's start date: it is listed from when Atlas observed it.
    fields = {
        "company_id": company_id,
        "ticker": ticker,
        "exchange_mic": mic,
        "segment_mic": details.get("segment_mic"),
        "isin": None,
        "figi": details.get("figi"),
        "share_class_figi": details.get("share_class_figi"),
        "instrument_type": details.get("instrument_type") or "unknown",
        "currency": currency,
        "valid_from": observed_on,
        "valid_to": None,
        "review_state": review_state,
    }
    security_id = _security_id(company_id, ticker, mic, observed_on)
    connection.execute(
        text(
            f"INSERT INTO security (id, {_SECURITY_COLUMNS}) VALUES (:id, :company_id, :ticker,"  # noqa: S608
            " :exchange_mic, :segment_mic, :isin, :figi, :share_class_figi, :instrument_type,"
            " :currency, :valid_from, :valid_to, :review_state)"
        ),
        {"id": security_id, **fields},
    )
    record(
        connection,
        actor,
        "security.created",
        entity_type="security",
        entity_id=str(security_id),
        new_hash=content_hash(fields),
    )
    return security_id


def _apply_company_identifier(
    connection: Connection, actor: Actor, company_id: uuid.UUID, kind: str, value: str
) -> None:
    column = "cik" if kind == "cik" else "lei"
    row = connection.execute(
        text(f"SELECT {column} FROM company WHERE id = :id FOR UPDATE"),  # noqa: S608
        {"id": company_id},
    ).one()
    current: str | None = row[0]
    if current == value:
        return
    if current is not None:
        raise IdentityConflict(f"the company already has {column.upper()} {current}")
    other = connection.execute(
        text(f"SELECT slug FROM company WHERE {column} = :value AND id <> :id"),  # noqa: S608
        {"value": value, "id": company_id},
    ).one_or_none()
    if other is not None:
        raise IdentityConflict(f"{column.upper()} {value} belongs to {other[0]}")
    connection.execute(
        text(f"UPDATE company SET {column} = :value, updated_at = now() WHERE id = :id"),  # noqa: S608
        {"value": value, "id": company_id},
    )
    record(
        connection,
        actor,
        "company.updated",
        entity_type="company",
        entity_id=str(company_id),
        old_hash=content_hash({column: None}),
        new_hash=content_hash({column: value}),
    )


def _apply(
    connection: Connection,
    actor: Actor,
    mapping: dict[str, Any],
    *,
    by_owner: bool,
) -> uuid.UUID | None:
    """Make `company`/`security` reflect the mapping; the security it touched, if any."""
    company_id: uuid.UUID = mapping["company_id"]
    kind, value, details = mapping["kind"], mapping["value"], mapping["details"]
    observed: datetime = mapping["observed_at"]
    if kind == "listing":
        return _apply_listing(
            connection, actor, company_id, details, observed.date(), by_owner=by_owner
        )
    _apply_company_identifier(connection, actor, company_id, kind, value)
    if kind == "lei":
        names = [Alias(name=details["legal_name"], kind="legal", source="gleif")] + [
            Alias(name=name, kind="other", source="gleif")
            for name in details.get("other_names", [])
        ]
        _insert_aliases(connection, actor, company_id, names, mapping["source_url"], observed)
    return None


def store_resolution(
    connection: Connection, actor: Actor, company_id: uuid.UUID, resolution: Resolution
) -> Stored:
    """Store a company's proposals (in the caller's transaction): new ones are committed and
    applied when exact or corroborated and not the owner's, else left pending."""
    stored = Stored()
    evidence = [fact.model_dump(mode="json") for fact in resolution.evidence]
    for proposal in resolution.proposals:
        mapping_id = _mapping_id(company_id, proposal.kind, proposal.value)
        exists = connection.execute(
            text("SELECT review_state FROM identity_mapping WHERE id = :id"), {"id": mapping_id}
        ).one_or_none()
        if exists is not None:
            stored.unchanged += 1
            continue
        state: ReviewState = "committed" if proposal.auto_commit else "pending"
        reasons = list(proposal.reasons)
        mapping = _mapping_row(mapping_id, company_id, proposal, state, reasons, evidence)
        security_id: uuid.UUID | None = None
        if state == "committed":
            try:
                with connection.begin_nested():
                    security_id = _apply(connection, actor, mapping, by_owner=False)
            except IdentityConflict as conflict:
                state = "pending"
                reasons.append(str(conflict))
                stored.held.append(f"{proposal.kind} {proposal.value}: {conflict}")
                mapping = _mapping_row(mapping_id, company_id, proposal, state, reasons, evidence)
        _insert_mapping(connection, mapping | {"security_id": security_id})
        record(
            connection,
            actor,
            f"identity_mapping.{'committed' if state == 'committed' else 'proposed'}",
            entity_type="identity_mapping",
            entity_id=str(mapping_id),
            new_hash=content_hash(_hashable(mapping)),
        )
        if state == "committed":
            stored.committed += 1
        else:
            stored.pending += 1
    # SEC's names (current and former, with dates) once the company's CIK is settled.
    cik_settled = connection.execute(
        text(
            "SELECT value, source_url, observed_at FROM identity_mapping WHERE company_id = :id"
            " AND kind = 'cik' AND review_state IN ('committed', 'confirmed')"
        ),
        {"id": company_id},
    ).one_or_none()
    entity = resolution.entity
    if cik_settled is not None and entity is not None and entity.cik == cik_settled[0]:
        sec_aliases = [a for a in entity.aliases if a.source == "sec"]
        stored.aliases += _insert_aliases(
            connection, actor, company_id, sec_aliases, cik_settled[1], cik_settled[2]
        )
    return stored


def _mapping_row(
    mapping_id: uuid.UUID,
    company_id: uuid.UUID,
    proposal: Proposal,
    state: ReviewState,
    reasons: list[str],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": mapping_id,
        "company_id": company_id,
        "kind": proposal.kind,
        "value": proposal.value,
        "tier": proposal.tier,
        "review_state": state,
        "owner_confirmation": proposal.owner_confirmation,
        "source": proposal.source,
        "source_url": proposal.url,
        "observed_at": proposal.observed_at,
        "reasons": reasons,
        "details": proposal.details,
        "evidence": evidence,
    }


def _hashable(mapping: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in mapping.items() if k not in ("evidence",)}


def _insert_mapping(connection: Connection, mapping: dict[str, Any]) -> None:
    connection.execute(
        text(
            "INSERT INTO identity_mapping (id, company_id, security_id, kind, value, tier,"
            " review_state, owner_confirmation, source, source_url, observed_at, reasons,"
            " details, evidence) VALUES (:id, :company_id, :security_id, :kind, :value, :tier,"
            " :review_state, :owner_confirmation, :source, :source_url, :observed_at,"
            " :reasons, :details, :evidence)"
        ).bindparams(bindparam("details", type_=JSONB), bindparam("evidence", type_=JSONB)),
        mapping,
    )


@dataclass(frozen=True)
class CompanyResolved:
    slug: str
    company_id: uuid.UUID
    tier: str
    committed: int
    pending: int
    unchanged: int
    aliases: int
    review_reasons: list[str]
    notes: list[str]


def resolve_universe(
    engine: Engine,
    actor: Actor,
    resolver: EntityResolver,
    universe: Universe,
    slugs: list[str] | None = None,
) -> list[CompanyResolved]:
    """Resolve each seeded company of the universe (default: all) and store its proposals,
    one transaction per company (the network calls happen outside it)."""
    results: list[CompanyResolved] = []
    for slug in slugs if slugs is not None else list(universe.companies):
        config = universe.companies[slug]
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT id, cik FROM company WHERE slug = :slug"), {"slug": slug}
            ).one_or_none()
        if row is None:
            raise LookupError(f"company {slug!r} isn't seeded: run `atlas companies seed`")
        company_id: uuid.UUID = row[0]
        mention = Mention(cik=row[1], name=config.legal_name, country=config.country)
        ignored = frozenset(i.cik for i in config.ignored_ciks)
        resolution = resolver.resolve(mention, ignored_ciks=ignored)
        with engine.begin() as connection:
            stored = store_resolution(connection, actor, company_id, resolution)
        results.append(
            CompanyResolved(
                slug=slug,
                company_id=company_id,
                tier=resolution.tier,
                committed=stored.committed,
                pending=stored.pending,
                unchanged=stored.unchanged,
                aliases=stored.aliases,
                review_reasons=resolution.review_reasons + stored.held,
                notes=resolution.notes + resolution.dropped,
            )
        )
    return results


# --- the owner's review ---


class IdentityMapping(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    company_slug: str
    security_id: uuid.UUID | None
    kind: Literal["cik", "lei", "listing"]
    value: str = Field(description="the CIK, the LEI, or TICKER@MIC for a listing")
    tier: Literal["exact", "corroborated", "candidate"]
    review_state: ReviewState
    owner_confirmation: bool = Field(description="only the owner commits it (CIK↔LEI links)")
    source: Literal["sec", "gleif", "openfigi"]
    source_url: str
    observed_at: datetime
    reasons: list[str]
    details: dict[str, Any]
    evidence: list[Fact]
    reviewed_by: str | None
    reviewed_at: datetime | None
    review_note: str | None
    created_at: datetime


class MappingConfirm(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class MappingReject(BaseModel):
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class MappingReviewed(BaseModel):
    mapping: IdentityMapping
    audit_event_id: int


class MappingRefused(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


_MAPPING_COLUMNS = (
    "m.id, m.company_id, c.slug AS company_slug, m.security_id, m.kind, m.value, m.tier,"
    " m.review_state, m.owner_confirmation, m.source, m.source_url, m.observed_at, m.reasons,"
    " m.details, m.evidence, m.reviewed_by, m.reviewed_at, m.review_note, m.created_at"
)


def list_mappings(
    connection: Connection,
    *,
    review_state: ReviewState | None,
    company_id: uuid.UUID | None,
    kind: str | None,
    limit: int,
    offset: int,
) -> tuple[list[IdentityMapping], int]:
    where = (
        " WHERE (CAST(:state AS text) IS NULL OR m.review_state = :state)"
        " AND (CAST(:company AS uuid) IS NULL OR m.company_id = :company)"
        " AND (CAST(:kind AS text) IS NULL OR m.kind = :kind)"
    )
    params = {"state": review_state, "company": company_id, "kind": kind}
    total = connection.execute(
        text(f"SELECT count(*) FROM identity_mapping m{where}"),  # noqa: S608
        params,
    ).scalar_one()
    rows = connection.execute(
        text(
            f"SELECT {_MAPPING_COLUMNS} FROM identity_mapping m JOIN company c"  # noqa: S608
            f" ON c.id = m.company_id{where} ORDER BY m.created_at, c.slug, m.kind, m.value"
            " LIMIT :limit OFFSET :offset"
        ),
        params | {"limit": limit, "offset": offset},
    ).mappings()
    return [IdentityMapping.model_validate(dict(r)) for r in rows], total


def get_mapping(connection: Connection, mapping_id: uuid.UUID) -> IdentityMapping | None:
    row = (
        connection.execute(
            text(
                f"SELECT {_MAPPING_COLUMNS} FROM identity_mapping m"  # noqa: S608
                " JOIN company c ON c.id = m.company_id WHERE m.id = :id"
            ),
            {"id": mapping_id},
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else IdentityMapping.model_validate(dict(row))


class IdentityMappings:
    def __init__(self, engine: Engine, actor: Actor) -> None:
        self._engine = engine
        self._actor = actor

    def _pending(self, connection: Connection, mapping_id: uuid.UUID) -> dict[str, Any]:
        row = (
            connection.execute(
                text("SELECT * FROM identity_mapping WHERE id = :id FOR UPDATE"),
                {"id": mapping_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise MappingRefused(404, "not_found", "identity mapping not found")
        if row["review_state"] != "pending":
            raise MappingRefused(
                409,
                "invalid_transition",
                f"the mapping is {row['review_state']}; only a pending mapping can be reviewed",
            )
        return dict(row)

    def _review(
        self,
        connection: Connection,
        mapping: dict[str, Any],
        state: Literal["confirmed", "rejected"],
        note: str | None,
        security_id: uuid.UUID | None = None,
    ) -> int:
        before = {"review_state": mapping["review_state"], "security_id": mapping["security_id"]}
        after = {"review_state": state, "security_id": security_id or mapping["security_id"]}
        connection.execute(
            text(
                "UPDATE identity_mapping SET review_state = :state, reviewed_by = :actor,"
                " reviewed_at = now(), review_note = :note,"
                " security_id = coalesce(:security, security_id) WHERE id = :id"
            ),
            {
                "state": state,
                "actor": self._actor.name,
                "note": note,
                "security": security_id,
                "id": mapping["id"],
            },
        )
        return record(
            connection,
            self._actor,
            f"identity_mapping.{state}",
            entity_type="identity_mapping",
            entity_id=str(mapping["id"]),
            old_hash=content_hash(before),
            new_hash=content_hash(after | {"note": note}),
        ).id

    def confirm(self, mapping_id: uuid.UUID, request: MappingConfirm) -> MappingReviewed:
        with self._engine.begin() as connection:
            mapping = self._pending(connection, mapping_id)
            try:
                with connection.begin_nested():
                    security_id = _apply(connection, self._actor, mapping, by_owner=True)
            except IdentityConflict as conflict:
                raise MappingRefused(409, "identity_conflict", str(conflict)) from None
            event_id = self._review(connection, mapping, "confirmed", request.note, security_id)
            if mapping["kind"] in ("cik", "lei"):
                # A company has one CIK and one LEI: the other pending ones are answered.
                others = connection.execute(
                    text(
                        "SELECT * FROM identity_mapping WHERE company_id = :company"
                        " AND kind = :kind AND review_state = 'pending' AND id <> :id FOR UPDATE"
                    ),
                    {"company": mapping["company_id"], "kind": mapping["kind"], "id": mapping_id},
                ).mappings()
                for other in [dict(o) for o in others]:
                    note = f"{mapping['kind'].upper()} {mapping['value']} was confirmed instead"
                    self._review(connection, other, "rejected", note)
            found = get_mapping(connection, mapping_id)
        assert found is not None
        return MappingReviewed(mapping=found, audit_event_id=event_id)

    def reject(self, mapping_id: uuid.UUID, request: MappingReject) -> MappingReviewed:
        with self._engine.begin() as connection:
            mapping = self._pending(connection, mapping_id)
            event_id = self._review(connection, mapping, "rejected", request.reason.strip())
            found = get_mapping(connection, mapping_id)
        assert found is not None
        return MappingReviewed(mapping=found, audit_event_id=event_id)
