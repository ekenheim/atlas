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
from typing import Any, Self

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


class CompanyConfig(_Config):
    legal_name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    cik: str | None = Field(default=None, pattern=r"^[0-9]{10}$")
    lei: str | None = None
    country: str = Field(pattern=r"^[A-Z]{2}$")
    website: str | None = None
    securities: tuple[SecurityConfig, ...] = ()


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
    key = f"cik:{config.cik}" if config.cik else f"slug:{slug}"
    return uuid.uuid5(_NAMESPACE, f"company:{key}")


def _security_id(company_id: uuid.UUID, security: SecurityConfig) -> uuid.UUID:
    key = f"{company_id}:{security.exchange_mic}:{security.ticker}:{security.valid_from}"
    return uuid.uuid5(_NAMESPACE, f"security:{key}")


@dataclass(frozen=True)
class Seeded:
    slug: str
    company_id: uuid.UUID
    changes: int  # audited creations and updates (company and securities)


_COMPANY_FIELDS = ("slug", "legal_name", "display_name", "cik", "lei", "country", "website")
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


def _seed_company(connection: Connection, actor: Actor, slug: str, config: CompanyConfig) -> Seeded:
    company_id = company_id_for(slug, config)
    desired: dict[str, Any] = {"slug": slug} | config.model_dump(include=set(_COMPANY_FIELDS))
    changes = _upsert(connection, actor, "company", company_id, desired, _COMPANY_FIELDS)
    for security in config.securities:
        fields = {"company_id": company_id} | security.model_dump()
        security_id = _security_id(company_id, security)
        changes += _upsert(connection, actor, "security", security_id, fields, _SECURITY_FIELDS)
    return Seeded(slug, company_id, changes)


def _upsert(
    connection: Connection,
    actor: Actor,
    table: str,
    entity_id: uuid.UUID,
    desired: dict[str, Any],
    fields: tuple[str, ...],
) -> int:
    columns = ", ".join(fields)
    values = ", ".join(f":{field}" for field in fields)
    created = connection.execute(
        text(
            f"INSERT INTO {table} (id, {columns}) VALUES (:id, {values}) "  # noqa: S608 (constant names)
            "ON CONFLICT DO NOTHING RETURNING id"
        ),
        {"id": entity_id, **desired},
    ).one_or_none()
    new_hash = content_hash(desired)
    if created is not None:
        record(
            connection,
            actor,
            f"{table}.created",
            entity_type=table,
            entity_id=str(entity_id),
            new_hash=new_hash,
        )
        return 1
    current = (
        connection.execute(
            text(f"SELECT {columns} FROM {table} WHERE id = :id FOR UPDATE"),  # noqa: S608
            {"id": entity_id},
        )
        .mappings()
        .one_or_none()
    )
    if current is None:
        # The conflict was on another unique key (e.g. the slug under a different CIK).
        raise UniverseConfigError(f"{table} {desired.get('slug', entity_id)} conflicts with a row")
    old_hash = content_hash(dict(current))
    if old_hash == new_hash:
        return 0
    assignments = ", ".join(f"{field} = :{field}" for field in fields)
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
    exchange_mic: str
    instrument_type: str
    currency: str
    isin: str | None
    figi: str | None
    valid_from: date
    valid_to: date | None


class Company(BaseModel):
    id: uuid.UUID
    slug: str
    legal_name: str
    display_name: str
    cik: str | None
    lei: str | None
    country: str
    website: str | None
    parent_company_id: uuid.UUID | None
    review_state: str
    securities: list[Security]
    created_at: datetime
    updated_at: datetime


_COMPANY_COLUMNS = (
    "id, slug, legal_name, display_name, cik, lei, country, website, parent_company_id,"
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
            "SELECT id, ticker, exchange_mic, instrument_type, currency, isin, figi,"
            " valid_from, valid_to FROM security WHERE company_id = :id"
            " ORDER BY valid_from, exchange_mic, ticker"
        ),
        {"id": row["id"]},
    ).mappings()
    return Company.model_validate(
        {**row, "securities": [Security.model_validate(dict(s)) for s in securities]}
    )
