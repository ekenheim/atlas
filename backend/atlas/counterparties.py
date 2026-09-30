"""Counterparty companies: a company outside the universe that an accepted quote names, kept
so the Relationship has its other end (pilot-fixes ticket 05; docs/decisions.md,
"Counterparty companies").

A counterparty is a `company` row with `role = 'counterparty'`: it has an identity (a CIK or
an LEI where a registry gave one), and nothing else. It is never ingested, never an
investigation seed and in no theme; it shows on the edge table, the theme map and the
Company dossier as the end of its edges. The owner promotes it to a researched company by
adding it to the theme config or by committing its Candidate.

- `resolve_named_company`: what a company name, as a quote wrote it, names. First a company
  Atlas already has (researched or counterparty: by name or alias, no network call). Else
  entity resolution by name (`resolve_mention`: SEC's ticker file and submissions, GLEIF),
  and **exactly one** real company must answer to the name: one SEC registrant whose name
  equals it after `normalize_name` (an unsponsored-ADR shell never counts), or, when SEC has
  none, one GLEIF record one of whose names (legal, other, transliterated) equals it. Names
  are equal only after normalisation, never by similarity. No match is `unresolved_company`
  and several are `ambiguous_company`; so is every unknown name when entity resolution isn't
  configured or a registry can't be reached. Nothing is written.
- `ensure_counterparty`: the company for a resolved name, created in the caller's
  transaction (audited, `company.counterparty_created`) unless a company with that CIK or
  LEI exists by now. Its ID follows the universe's rule (from the CIK, else the slug), so a
  config entry with the same CIK or slug later is the same company. A CIK-identified
  counterparty carries no LEI: a CIK↔LEI link is the owner's to confirm.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Connection, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.expression import bindparam

from atlas.audit import Actor, content_hash, record
from atlas.companies import company_id_from, default_slug
from atlas.identity import Entity, EntityResolver, IdentitySourceError, Mention, Resolution
from atlas.identity.normalize import US_STATES, normalize_name
from atlas.identity.service import find_in_universe, resolve_mention

UNRESOLVED = "unresolved_company"
AMBIGUOUS = "ambiguous_company"


@dataclass(frozen=True)
class NewCounterparty:
    """One real company outside Atlas that a name resolved to; not yet a row."""

    named_as: str  # the name as the quote wrote it: its display name
    legal_name: str  # the registry's name
    cik: str | None
    lei: str | None  # only when no CIK identified it
    country: str | None
    source: Literal["sec", "gleif"]
    source_url: str
    observed_at: datetime
    resolution: Resolution


@dataclass(frozen=True)
class NamedCompany:
    """What a company name resolved to: a company Atlas has (`company_id`), one real company
    it doesn't have yet (`new`), or neither (`refusal`: the reason code and the reason)."""

    company_id: uuid.UUID | None = None
    new: NewCounterparty | None = None
    refusal: tuple[str, str] | None = None


def resolve_named_company(
    connection: Connection,
    resolver: EntityResolver | None,
    name: str,
    *,
    ignored_ciks: frozenset[str] = frozenset(),
) -> NamedCompany:
    """Resolve `name` (see the module). Calls SEC and GLEIF unless Atlas has the company."""
    mention = Mention(name=name)
    if resolver is None:
        local = find_in_universe(connection, mention)
        if local is not None and local.company_id is not None:
            return NamedCompany(company_id=uuid.UUID(local.company_id))
        return _refused(
            UNRESOLVED,
            f"{name!r} is none of the companies Atlas has, and entity resolution is not"
            " configured (set ATLAS_SEC_USER_AGENT), so it can't be identified",
        )
    try:
        resolution = resolve_mention(connection, resolver, mention, ignored_ciks=ignored_ciks)
    except IdentitySourceError as error:
        return _refused(UNRESOLVED, f"entity resolution of {name!r} failed: {error}")
    if resolution.company_id is not None:
        return NamedCompany(company_id=uuid.UUID(resolution.company_id))
    wanted = normalize_name(name)
    source: Literal["sec", "gleif"] = "sec"
    matches = [e for e in resolution.candidates if e.cik and normalize_name(e.name) == wanted]
    if not matches:
        source = "gleif"
        matches = [e for e in resolution.candidates if e.lei and not e.cik and wanted in _names(e)]
    if not matches:
        return _refused(
            UNRESOLVED,
            f"no source identifies {name!r}: SEC's ticker file and GLEIF have no entity of"
            " exactly that name",
        )
    if len(matches) > 1:
        registry = "SEC registrants" if source == "sec" else "GLEIF records"
        listed = ", ".join(f"{e.name} ({e.cik or e.lei})" for e in matches[:5])
        return _refused(
            AMBIGUOUS,
            f"{len(matches)} {registry} answer to {name!r} ({listed}), so it names no single"
            " company",
        )
    [entity] = matches
    known = find_in_universe(connection, Mention(cik=entity.cik, lei=entity.lei))
    if known is not None and known.company_id is not None:
        return NamedCompany(company_id=uuid.UUID(known.company_id))
    kind, value = ("cik", entity.cik) if source == "sec" else ("lei", entity.lei)
    proposal = next(p for p in resolution.proposals if p.kind == kind and p.value == value)
    return NamedCompany(
        new=NewCounterparty(
            named_as=name,
            legal_name=entity.name or name,
            cik=entity.cik,
            lei=None if entity.cik else entity.lei,
            country=_country(entity),
            source=source,
            source_url=proposal.url,
            observed_at=proposal.observed_at,
            resolution=resolution,
        )
    )


def ensure_counterparty(connection: Connection, actor: Actor, new: NewCounterparty) -> uuid.UUID:
    """The company `new` identifies: the one with its CIK (else its LEI) if there is one by
    now, else a new counterparty, created and audited in the caller's transaction."""
    existing = connection.execute(
        text(
            "SELECT id FROM company WHERE CASE WHEN CAST(:cik AS text) IS NOT NULL"
            " THEN cik = :cik ELSE lei = :lei END ORDER BY created_at, id LIMIT 1"
        ),
        {"cik": new.cik, "lei": new.lei},
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    slug = _free_slug(connection, new)
    company_id = company_id_from(slug, new.cik)
    fields: dict[str, Any] = {
        "slug": slug,
        "legal_name": new.legal_name,
        "display_name": new.named_as,
        "cik": new.cik,
        "lei": new.lei,
        "country": new.country,
        "role": "counterparty",
    }
    origin: dict[str, Any] = {
        "named_as": new.named_as,
        "source": new.source,
        "source_url": new.source_url,
        "observed_at": new.observed_at.isoformat(),
    }
    connection.execute(
        text(
            "INSERT INTO company (id, slug, legal_name, display_name, cik, lei, country, role,"
            " counterparty_resolution) VALUES (:id, :slug, :legal_name, :display_name, :cik,"
            " :lei, :country, :role, :origin)"
        ).bindparams(bindparam("origin", type_=JSONB)),
        {
            "id": company_id,
            **fields,
            "origin": origin | {"resolution": new.resolution.model_dump(mode="json")},
        },
    )
    record(
        connection,
        actor,
        "company.counterparty_created",
        entity_type="company",
        entity_id=str(company_id),
        new_hash=content_hash(fields | origin),
    )
    return company_id


def _refused(code: str, reason: str) -> NamedCompany:
    return NamedCompany(refusal=(code, reason))


def _names(entity: Entity) -> set[str]:
    return {normalize_name(entity.name)} | {normalize_name(a.name) for a in entity.aliases}


def _country(entity: Entity) -> str | None:
    """The registry's country: GLEIF's jurisdiction, or US for a US state of incorporation
    (SEC gives a foreign registrant's country only as an EDGAR code, which isn't mapped)."""
    if entity.jurisdiction:
        country = entity.jurisdiction.split("-", 1)[0]
        return country if re.fullmatch(r"[A-Z]{2}", country) else None
    return "US" if entity.state_of_incorporation in US_STATES else None


def _free_slug(connection: Connection, new: NewCounterparty) -> str:
    """A slug no company has: from the name as quoted, else the legal name, else numbered."""

    def taken(slug: str) -> bool:
        found = connection.execute(text("SELECT 1 FROM company WHERE slug = :slug"), {"slug": slug})
        return found.one_or_none() is not None

    base = default_slug(new.named_as)
    for slug in (base, default_slug(new.legal_name)):
        if not taken(slug):
            return slug
    number = 2
    while taken(f"{base[:60]}-{number}"):
        number += 1
    return f"{base[:60]}-{number}"
