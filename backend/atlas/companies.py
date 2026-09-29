"""The company universe: companies and themes from versioned config, seeded into the database.

`load_universe` reads a theme config (`configs/themes/*.yaml`); `seed` makes the `company`
and `security` rows match it, idempotently, auditing only real changes. Company IDs are
deterministic (from the CIK, else the slug), so every database seeded from the same config
agrees on them. Securities are effective-dated and never deleted: a listing that ends gets
a `valid_to` in config.
"""

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import Connection, text

from atlas.audit import Actor, content_hash, record

_SLUG = r"^[a-z0-9][a-z0-9-]*$"
# Fixed namespace for company and security IDs; changing it would re-key every company.
_NAMESPACE = uuid.UUID("8f5d2c1e-7b43-4c1a-9e0d-6a3b2f1c4d57")


class UniverseConfigError(ValueError):
    """The theme config is missing or invalid; the message says where."""


class _Config(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SecurityConfig(_Config):
    ticker: str = Field(min_length=1)
    exchange_mic: str = Field(pattern=r"^[A-Z0-9]{4}$")
    instrument_type: str = Field(min_length=1)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    valid_from: date
    valid_to: date | None = None
    isin: str | None = None
    figi: str | None = None


# A company's primary layer in the photonics supply chain (spec Phases 3-6a, "Theme config").
type Layer = Literal[
    "substrate", "epi", "chip-laser", "dsp", "module", "contract-manufacturing", "system"
]
# Where a company's primary disclosures come from: SEC EDGAR, or its exchange's feed.
type SourcePath = Literal["sec", "exchange:hkex", "exchange:fca-nsm", "exchange:euronext"]

_CIK = r"^[0-9]{10}$"


class IgnoredCik(_Config):
    """A CIK that SEC files map to the company but that must never be used as its filer, e.g.
    an unsponsored-ADR shell holding only depositary F-6EF registrations."""

    cik: str = Field(pattern=_CIK)
    reason: str = Field(min_length=1)


class ExchangeListingConfig(_Config):
    """How an exchange-disclosed company is found in its exchange's feed."""

    issuer_code: str = Field(min_length=1)  # the exchange's code, e.g. HKEX stock code "03308"
    # The feed's own ID for the issuer, if it has one (HKEXnews `stockId`; the NSM: its LEI)
    feed_id: str | None = None


class CompanyConfig(_Config):
    legal_name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    cik: str | None = Field(default=None, pattern=_CIK)
    lei: str | None = None
    country: str = Field(pattern=r"^[A-Z]{2}$")
    website: str | None = None
    layer: Layer | None = None
    source_path: SourcePath
    # The SEC forms to ingest (amendments included); None means the adapter's default
    # (10-K, 10-Q, 8-K). A foreign private issuer files 20-F/6-K instead.
    sec_forms: tuple[str, ...] | None = Field(default=None, min_length=1)
    ignored_ciks: tuple[IgnoredCik, ...] = ()
    # For an `exchange:*` company: its identifiers in the exchange's disclosure feed.
    exchange: ExchangeListingConfig | None = None
    securities: tuple[SecurityConfig, ...] = ()

    @model_validator(mode="after")
    def _source_path(self) -> Self:
        if self.source_path == "sec" and self.cik is None:
            raise ValueError("source_path 'sec' needs a cik")
        if self.source_path == "sec" and self.exchange is not None:
            raise ValueError("source_path 'sec' takes no exchange listing")
        if self.source_path != "sec":
            if self.cik is not None:
                raise ValueError(
                    f"source_path {self.source_path!r} is not an SEC filer: remove the cik"
                    " (list an SEC-mapped CIK under ignored_ciks instead)"
                )
            if self.sec_forms is not None:
                raise ValueError(f"source_path {self.source_path!r} takes no sec_forms")
        return self


class ThemeConfig(_Config):
    title: str = Field(min_length=1)
    description: str = ""
    companies: tuple[str, ...]


class Universe(_Config):
    version: int = Field(ge=1)
    name: str = Field(pattern=_SLUG)
    companies: dict[str, CompanyConfig]
    themes: dict[str, ThemeConfig] = {}

    @field_validator("companies", "themes")
    @classmethod
    def _slugs(cls, value: dict[str, Any]) -> dict[str, Any]:
        bad = [slug for slug in value if not re.fullmatch(_SLUG, slug)]
        if bad:
            raise ValueError(f"not a slug (lowercase letters, digits, '-'): {', '.join(bad)}")
        return value

    @model_validator(mode="after")
    def _references(self) -> Self:
        for slug, theme in self.themes.items():
            unknown = [c for c in theme.companies if c not in self.companies]
            if unknown:
                raise ValueError(f"theme {slug!r} names unknown companies: {', '.join(unknown)}")
        ciks = [c.cik for c in self.companies.values() if c.cik]
        if len(ciks) != len(set(ciks)):
            raise ValueError("two companies share a CIK")
        ignored = {i.cik: slug for slug, c in self.companies.items() for i in c.ignored_ciks}
        for slug, company in self.companies.items():
            if company.cik in ignored:
                raise ValueError(
                    f"company {slug!r} uses CIK {company.cik}, which {ignored[company.cik]!r}"
                    " lists as ignored"
                )
        return self


def load_universe(path: Path) -> Universe:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise UniverseConfigError(f"cannot read theme config {path}: {error.strerror}") from None
    except yaml.YAMLError as error:
        raise UniverseConfigError(f"theme config {path} is not valid YAML: {error}") from None
    try:
        return Universe.model_validate(document)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc']) or '<root>'}: {issue['msg']}"
            for issue in error.errors()
        )
        raise UniverseConfigError(f"theme config {path} is invalid: {problems}") from None


def company_id_for(slug: str, config: CompanyConfig) -> uuid.UUID:
    return company_id_from(slug, config.cik)


def company_id_from(slug: str, cik: str | None) -> uuid.UUID:
    """A company's ID: from its CIK, else its slug (config and committed Candidates alike)."""
    key = f"cik:{cik}" if cik else f"slug:{slug}"
    return uuid.uuid5(_NAMESPACE, f"company:{key}")


def extend_universe(connection: Connection, universe: Universe) -> Universe:
    """The universe with its database extension: each company a committed Candidate added
    (`universe_company`), in its theme. Config wins where both name a slug. A company with no
    source path (no automated source yet) is left out, as no config entry could hold it."""
    rows = connection.execute(
        text(
            "SELECT u.theme, c.slug, c.legal_name, c.display_name, c.cik, c.lei, c.country,"
            " c.website, c.layer, c.source_path, c.sec_forms FROM universe_company u"
            " JOIN company c ON c.id = u.company_id WHERE c.source_path IS NOT NULL"
            " ORDER BY c.slug, u.theme"
        )
    ).mappings()
    companies = dict(universe.companies)
    members: dict[str, list[str]] = {}
    for row in rows:
        slug: str = row["slug"]
        if slug in universe.companies:
            continue
        fields = {k: v for k, v in row.items() if k not in ("theme", "slug") and v is not None}
        companies[slug] = CompanyConfig.model_validate(fields)
        members.setdefault(row["theme"], []).append(slug)
    if not members:
        return universe
    themes = dict(universe.themes)
    for theme, slugs in members.items():
        config = themes.get(theme) or ThemeConfig(title=theme, companies=())
        added = tuple(s for s in slugs if s not in config.companies)
        themes[theme] = config.model_copy(update={"companies": config.companies + added})
    return universe.model_copy(update={"companies": companies, "themes": themes})


def _security_id(company_id: uuid.UUID, security: SecurityConfig) -> uuid.UUID:
    key = f"{company_id}:{security.exchange_mic}:{security.ticker}:{security.valid_from}"
    return uuid.uuid5(_NAMESPACE, f"security:{key}")


@dataclass(frozen=True)
class Seeded:
    slug: str
    company_id: uuid.UUID
    changes: int  # audited creations and updates (company and securities)


_COMPANY_FIELDS = (
    "slug",
    "legal_name",
    "display_name",
    "cik",
    "lei",
    "country",
    "website",
    "layer",
    "source_path",
    "sec_forms",
)
_SECURITY_FIELDS = (
    "company_id",
    "ticker",
    "exchange_mic",
    "instrument_type",
    "currency",
    "valid_from",
    "valid_to",
    "isin",
    "figi",
)


def seed(
    connection: Connection, actor: Actor, universe: Universe, slugs: Iterable[str] | None = None
) -> list[Seeded]:
    """Make the rows for `slugs` (default: every company) match the config, in the caller's
    transaction. Unchanged rows are left alone and produce no audit event."""
    wanted = list(universe.companies) if slugs is None else list(slugs)
    return [_seed_company(connection, actor, slug, universe.companies[slug]) for slug in wanted]


# Identifiers entity resolution may set (atlas.identity): config sets them only when it
# names them, so a re-seed never erases a confirmed LEI or a resolved FIGI.
_RESOLVED_FIELDS = frozenset({"cik", "lei", "isin", "figi"})


def _config_fields(fields: tuple[str, ...], desired: dict[str, Any]) -> tuple[str, ...]:
    return tuple(f for f in fields if not (f in _RESOLVED_FIELDS and desired.get(f) is None))


def _seed_company(connection: Connection, actor: Actor, slug: str, config: CompanyConfig) -> Seeded:
    company_id = company_id_for(slug, config)
    desired: dict[str, Any] = {"slug": slug} | config.model_dump(include=set(_COMPANY_FIELDS))
    desired["sec_forms"] = list(config.sec_forms) if config.sec_forms is not None else None
    changes = _upsert(
        connection,
        actor,
        "company",
        company_id,
        desired,
        _COMPANY_FIELDS,
        _config_fields(_COMPANY_FIELDS, desired),
    )
    for security in config.securities:
        fields = {"company_id": company_id} | security.model_dump()
        security_id = _security_id(company_id, security)
        changes += _upsert(
            connection,
            actor,
            "security",
            security_id,
            fields,
            _SECURITY_FIELDS,
            _config_fields(_SECURITY_FIELDS, fields),
        )
    return Seeded(slug, company_id, changes)


def _upsert(
    connection: Connection,
    actor: Actor,
    table: str,
    entity_id: uuid.UUID,
    desired: dict[str, Any],
    fields: tuple[str, ...],
    managed: tuple[str, ...],
) -> int:
    """Insert the row with every field, or bring the `managed` fields up to date."""
    columns = ", ".join(fields)
    values = ", ".join(f":{field}" for field in fields)
    created = connection.execute(
        text(
            f"INSERT INTO {table} (id, {columns}) VALUES (:id, {values}) "  # noqa: S608 (constant names)
            "ON CONFLICT DO NOTHING RETURNING id"
        ),
        {"id": entity_id, **desired},
    ).one_or_none()
    if created is not None:
        record(
            connection,
            actor,
            f"{table}.created",
            entity_type=table,
            entity_id=str(entity_id),
            new_hash=content_hash(desired),
        )
        return 1
    managed_columns = ", ".join(managed)
    current = (
        connection.execute(
            text(f"SELECT {managed_columns} FROM {table} WHERE id = :id FOR UPDATE"),  # noqa: S608
            {"id": entity_id},
        )
        .mappings()
        .one_or_none()
    )
    if current is None:
        # The conflict was on another unique key (e.g. the slug under a different CIK).
        raise UniverseConfigError(f"{table} {desired.get('slug', entity_id)} conflicts with a row")
    old_hash = content_hash(dict(current))
    new_hash = content_hash({field: desired[field] for field in managed})
    if old_hash == new_hash:
        return 0
    assignments = ", ".join(f"{field} = :{field}" for field in managed)
    touch = ", updated_at = now()" if table == "company" else ""
    connection.execute(
        text(f"UPDATE {table} SET {assignments}{touch} WHERE id = :id"),  # noqa: S608
        {"id": entity_id, **desired},
    )
    record(
        connection,
        actor,
        f"{table}.updated",
        entity_type=table,
        entity_id=str(entity_id),
        old_hash=old_hash,
        new_hash=new_hash,
    )
    return 1


# --- reads ---


class Security(BaseModel):
    id: uuid.UUID
    ticker: str
    exchange_mic: str = Field(description="ISO 10383 operating MIC")
    segment_mic: str | None = Field(description="the segment MIC OpenFIGI matched, e.g. XNGS")
    instrument_type: str
    currency: str
    isin: str | None
    figi: str | None = Field(description="composite (country-level) FIGI")
    share_class_figi: str | None
    underlying_security_id: uuid.UUID | None = Field(description="an ADR's underlying line")
    adr_ratio: float | None
    review_state: str
    valid_from: date
    valid_to: date | None


class CompanyAlias(BaseModel):
    name: str
    kind: Literal["legal", "former", "other"]
    valid_from: date | None
    valid_to: date | None
    source: str
    source_url: str
    observed_at: datetime


class Company(BaseModel):
    id: uuid.UUID
    slug: str
    legal_name: str
    display_name: str
    cik: str | None
    lei: str | None
    country: str
    website: str | None
    layer: Layer | None
    source_path: SourcePath | None
    sec_forms: list[str] | None
    parent_company_id: uuid.UUID | None
    review_state: str
    securities: list[Security]
    aliases: list[CompanyAlias]
    created_at: datetime
    updated_at: datetime


_COMPANY_COLUMNS = (
    "id, slug, legal_name, display_name, cik, lei, country, website, layer, source_path,"
    " sec_forms, parent_company_id,"
    " review_state, created_at, updated_at"
)


def list_companies(connection: Connection, *, limit: int, offset: int) -> tuple[list[Company], int]:
    total = connection.execute(text("SELECT count(*) FROM company")).scalar_one()
    rows = connection.execute(
        text(
            f"SELECT {_COMPANY_COLUMNS} FROM company ORDER BY slug LIMIT :limit OFFSET :offset"  # noqa: S608
        ),
        {"limit": limit, "offset": offset},
    ).mappings()
    return [_company(connection, row) for row in rows.all()], total


def get_company(connection: Connection, company_id: uuid.UUID) -> Company | None:
    row = (
        connection.execute(
            text(f"SELECT {_COMPANY_COLUMNS} FROM company WHERE id = :id"),  # noqa: S608
            {"id": company_id},
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else _company(connection, row)


def _company(connection: Connection, row: Any) -> Company:
    securities = connection.execute(
        text(
            "SELECT id, ticker, exchange_mic, segment_mic, instrument_type, currency, isin, figi,"
            " share_class_figi, underlying_security_id, adr_ratio, review_state,"
            " valid_from, valid_to FROM security WHERE company_id = :id"
            " ORDER BY valid_from, exchange_mic, ticker"
        ),
        {"id": row["id"]},
    ).mappings()
    aliases = connection.execute(
        text(
            "SELECT name, kind, valid_from, valid_to, source, source_url, observed_at"
            " FROM company_alias WHERE company_id = :id"
            " ORDER BY kind, valid_from NULLS FIRST, name, source"
        ),
        {"id": row["id"]},
    ).mappings()
    return Company.model_validate(
        {
            **row,
            "securities": [Security.model_validate(dict(s)) for s in securities],
            "aliases": [CompanyAlias.model_validate(dict(a)) for a in aliases],
        }
    )
