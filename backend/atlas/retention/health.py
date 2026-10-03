"""Memory health: what the research bank holds and what it lost (memory-quality ticket 02;
`docs/runbooks.md`, "Memory health").

One read, two sources:

- **Atlas's own records** (`memory_document`, `hindsight_operation`): the bank's sections by
  retain state, for the bank and per company (the filer of the section's Source Document);
  `partial`, the completed sections whose extraction still reported errors after their one
  retry (`memory_document.extraction_errors` > 0, ticket 03: some chunk's extraction failed
  and Hindsight still completed it); the sections not in memory (`failed`, and `cancelled`:
  an operation the owner cancelled, which is not a failure) grouped by their state, their
  error class (`cancelled`, `permanent`, `transient`, `missing`) and their **normalized
  error** (IDs, UUIDs, hex and numbers of four or more digits replaced by placeholders,
  whitespace collapsed), each group with its count, its latest raw example, the first and
  last time a section of it was marked and its companies; and the pending sections by how
  long they have waited since their last submission. `stuck` counts the pending sections
  under an older retain profile that nothing is retaining (ticket 21: the backfill's
  `STUCK`), which `atlas memory backfill` takes.
- **Hindsight, read-only** (no LLM call): the observation scopes (`GET .../observations/scopes`)
  and, for each universe company, the entities whose name matches it (`GET .../entities`,
  paged). An entity matches a company when its normalized name (`atlas.identity.normalize`)
  equals the company's normalized display or legal name, starts with the display name's words,
  or equals one of its tickers. One company should be one entity; several is a split the graph
  cannot hop across.

A Hindsight read that fails (or Hindsight not configured) makes its part `unavailable` with the
reason; the rest of the read still answers.

`consolidation` (ticket 19) is Atlas's record of the bank's consolidations: the last requested
and the last completed run, their operations, and the sections retained since the last
completed one (`atlas.retention.consolidation`). `reconciliation` (ticket 22) is the bank's
last reconciliation of Atlas's records with Memory (`atlas.retention.reconciliation`).
"""

import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from atlas.companies import CompanyConfig, Universe
from atlas.hindsight import HINDSIGHT_NOT_CONFIGURED, HindsightError, HindsightGateway
from atlas.identity.normalize import normalize_name
from atlas.retention.backfill import STUCK, stuck_params
from atlas.retention.consolidation import ConsolidationRecord, consolidation_record
from atlas.retention.reads import RETAIN_STATES
from atlas.retention.reconciliation import ReconciliationSummary, last_reconciliation

PartStatus = Literal["ok", "unavailable"]
PendingAge = Literal["under_1h", "1h_to_24h", "1d_to_7d", "over_7d"]
_AGE_BOUNDS: tuple[tuple[PendingAge, float | None], ...] = (
    ("under_1h", 3600.0),
    ("1h_to_24h", 86400.0),
    ("1d_to_7d", 7 * 86400.0),
    ("over_7d", None),
)
# Listing pages: Hindsight's maximum for the scopes listing, and a bound on how much is read.
PAGE_SIZE = 1000
MAX_SCOPE_PAGES = 20
MAX_ENTITY_PAGES = 50
UNATTRIBUTED = "unattributed"  # sections whose Source Document has no company
_MAX_ERROR_CHARS = 300

_PLACEHOLDERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"srcv:\S+"), "<document>"),
    (
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
        "<uuid>",
    ),
    (re.compile(r"\b(?=[0-9a-fA-F]*[a-fA-F])(?=[0-9a-fA-F]*[0-9])[0-9a-fA-F]{12,}\b"), "<hex>"),
    (re.compile(r"\d{4,}(?:\.\d+)?"), "<n>"),
    (re.compile(r"\s+"), " "),
)


def normalize_error(error: str) -> str:
    """The error text a failed section is grouped by: identifiers and long numbers replaced by
    placeholders, whitespace collapsed, at most 300 characters."""
    normalized = error
    for pattern, placeholder in _PLACEHOLDERS:
        normalized = pattern.sub(placeholder, normalized)
    return normalized.strip()[:_MAX_ERROR_CHARS]


class SectionCounts(BaseModel):
    """Sections in the bank by retain state; `partial` is a subset of `completed`."""

    total: int = 0
    pending: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = Field(default=0, description="the operation was cancelled; not a failure")
    zero_fact: int = 0
    linked: int = 0
    partial: int = Field(
        default=0,
        description="completed sections whose extraction reported errors after their one retry",
    )
    fact_count: int = Field(default=0, description="memories counted across completed sections")
    at_profile: int = Field(
        default=0,
        description="completed and zero-fact sections retained under the current retain profile"
        " (memory-quality ticket 12)",
    )
    below_profile: int = Field(
        default=0,
        description="completed and zero-fact sections retained under an older profile: what a"
        " `atlas memory backfill` re-extracts (with the failed, cancelled and stuck ones)",
    )
    stuck: int = Field(
        default=0,
        description="pending sections under an older retain profile, not updated for"
        " ATLAS_BACKFILL_STUCK_AFTER_HOURS and with no retain, poll or reprocess job of their"
        " Source Version queued or running: what `atlas memory backfill` deletes and retains"
        " again (memory-quality ticket 21); a subset of `pending`",
    )


class CompanySections(BaseModel):
    company_id: uuid.UUID | None  # None: sections whose Source Document has no company
    slug: str | None
    display_name: str | None
    role: str | None  # researched or counterparty
    sections: SectionCounts


class FailedGroup(BaseModel):
    """Sections not in memory that share a state, an error class and a normalized error."""

    state: str = Field(description="failed or cancelled")
    error_class: str | None = Field(
        description="cancelled, permanent, transient or missing (null: recorded before classes)"
    )
    error: str = Field(description="the normalized error text")
    count: int
    example: str = Field(description="the latest failed section's error, as recorded")
    example_document_id: str | None
    first_at: datetime
    last_at: datetime
    companies: dict[str, int] = Field(description="sections by company slug (or unattributed)")


class PendingBucket(BaseModel):
    age: PendingAge
    count: int
    oldest_at: datetime | None


class ScopeCount(BaseModel):
    tags: list[str]
    count: int


class ObservationScopesHealth(BaseModel):
    status: PartStatus
    reason: str | None = None
    total: int | None = Field(default=None, description="the bank's distinct scopes")
    complete: bool = Field(default=True, description="false: more scopes than were read")
    scopes: list[ScopeCount] = Field(
        default_factory=list[ScopeCount],
        description="most populous first; with company_id, the scopes tagged with it",
    )


class EntityMatch(BaseModel):
    id: str
    canonical_name: str
    mention_count: int


class CompanyEntities(BaseModel):
    company_id: uuid.UUID | None  # None: in the universe config but never seeded
    slug: str
    display_name: str
    names: list[str] = Field(description="the names and tickers matched against")
    entities: list[EntityMatch]
    one_entity: bool


class EntitiesHealth(BaseModel):
    status: PartStatus
    reason: str | None = None
    total: int | None = Field(default=None, description="the bank's entities")
    scanned: int = 0
    complete: bool = Field(default=True, description="false: more entities than were read")
    companies: list[CompanyEntities] = Field(default_factory=list[CompanyEntities])


class MemoryHealth(BaseModel):
    bank_id: str
    company_id: uuid.UUID | None
    generated_at: datetime
    sections: SectionCounts
    companies: list[CompanySections]
    failed_groups: list[FailedGroup]
    pending_by_age: list[PendingBucket]
    observation_scopes: ObservationScopesHealth
    entities: EntitiesHealth
    consolidation: ConsolidationRecord = Field(
        description="the bank's last requested and last completed consolidation (ticket 19);"
        " for the whole bank, whatever company_id is"
    )
    reconciliation: ReconciliationSummary | None = Field(
        description="the bank's last reconciliation of Atlas's records with Memory (ticket 22):"
        " its status, differences by kind and when; for the whole bank, whatever company_id is"
    )


@dataclass
class _Group:
    first_at: datetime
    last_at: datetime
    count: int = 0
    example: str = ""
    example_document_id: str | None = None
    companies: dict[str, int] = field(default_factory=dict[str, int])


def memory_health(
    connection: Connection,
    bank_id: str,
    gateway: HindsightGateway | None,
    universe: Universe,
    company_id: uuid.UUID | None = None,
    *,
    stuck_after_hours: float,
) -> MemoryHealth | None:
    """The health read; None when `company_id` names no company. `stuck_after_hours`: how long
    a pending section under an older profile waits before it counts as stuck."""
    companies = {
        row["id"]: row
        for row in connection.execute(
            text("SELECT id, slug, display_name, role FROM company ORDER BY slug")
        ).mappings()
    }
    if company_id is not None and company_id not in companies:
        return None
    now: datetime = connection.execute(text("SELECT now()")).scalar_one()
    where, params = _filter(bank_id, company_id)
    total, per_company = _section_counts(connection, where, params, stuck_after_hours)
    if company_id is not None:
        per_company.setdefault(company_id, SectionCounts())
    listed = [
        CompanySections(
            company_id=key,
            slug=companies[key]["slug"] if key in companies else None,
            display_name=companies[key]["display_name"] if key in companies else None,
            role=companies[key]["role"] if key in companies else None,
            sections=counts,
        )
        for key, counts in per_company.items()
    ]
    if company_id is None:
        # Every universe company is listed, with nothing when nothing of it is in the bank.
        seen = {c.slug for c in listed}
        ids = {row["slug"]: key for key, row in companies.items()}
        listed.extend(
            CompanySections(
                company_id=ids.get(slug),
                slug=slug,
                display_name=config.display_name,
                role="researched",
                sections=SectionCounts(),
            )
            for slug, config in universe.companies.items()
            if slug not in seen
        )
    return MemoryHealth(
        bank_id=bank_id,
        company_id=company_id,
        generated_at=now,
        sections=total,
        companies=sorted(listed, key=lambda c: (c.slug is None, c.slug or "")),
        failed_groups=_failed_groups(connection, where, params),
        pending_by_age=_pending(connection, where, params, now),
        observation_scopes=_scopes(gateway, company_id),
        entities=_entities(gateway, universe, companies, company_id),
        consolidation=consolidation_record(connection, bank_id),
        reconciliation=last_reconciliation(connection, bank_id),
    )


def _filter(bank_id: str, company_id: uuid.UUID | None) -> tuple[str, dict[str, Any]]:
    where = "m.bank_id = :bank"
    params: dict[str, Any] = {"bank": bank_id}
    if company_id is not None:
        where += " AND d.company_id = :company"
        params["company"] = company_id
    return where, params


_FROM = (
    " FROM memory_document m"
    " JOIN source_version v ON v.id = m.source_version_id"
    " JOIN source_document d ON d.id = v.source_document_id"
    " LEFT JOIN company c ON c.id = d.company_id"
)
_PARTIAL = "m.retain_state = 'completed' AND m.extraction_errors > 0"


def _section_counts(
    connection: Connection, where: str, params: Mapping[str, Any], stuck_after_hours: float
) -> tuple[SectionCounts, dict[uuid.UUID | None, SectionCounts]]:
    rows = connection.execute(
        text(
            "SELECT d.company_id, m.retain_state, count(*) AS sections,"
            f" count(*) FILTER (WHERE {_PARTIAL}) AS partial,"
            " coalesce(sum(m.fact_count) FILTER (WHERE m.retain_state = 'completed'), 0)"
            " AS facts,"
            " count(*) FILTER (WHERE m.retain_state IN ('completed', 'zero_fact')"
            "   AND m.retain_profile = :profile) AS at_profile,"
            f" count(*) FILTER (WHERE {STUCK}) AS stuck"
            f"{_FROM} WHERE {where} GROUP BY 1, 2"
        ),
        {**params, **stuck_params(stuck_after_hours)},
    ).mappings()
    total = SectionCounts()
    per_company: dict[uuid.UUID | None, SectionCounts] = {}
    for row in rows:
        state: str = row["retain_state"]
        if state not in RETAIN_STATES:
            continue
        for counts in (total, per_company.setdefault(row["company_id"], SectionCounts())):
            setattr(counts, state, getattr(counts, state) + row["sections"])
            counts.total += row["sections"]
            counts.partial += row["partial"]
            counts.fact_count += int(row["facts"])
            counts.at_profile += row["at_profile"]
            counts.stuck += row["stuck"]
            if state in ("completed", "zero_fact"):
                counts.below_profile += row["sections"] - row["at_profile"]
    return total, per_company


def _failed_groups(
    connection: Connection, where: str, params: Mapping[str, Any]
) -> list[FailedGroup]:
    groups: dict[tuple[str, str | None, str], _Group] = {}
    for row in connection.execute(
        text(
            "SELECT m.retain_state, m.error_class, m.error, m.updated_at,"
            " m.hindsight_document_id, c.slug"
            f"{_FROM} WHERE {where} AND m.retain_state IN ('failed', 'cancelled')"
            " ORDER BY m.updated_at, m.hindsight_document_id"
        ),
        params,
    ).mappings():
        error: str = row["error"] or ""
        at: datetime = row["updated_at"]
        # Rows come oldest first: the first of a group is its first, the last its example.
        key = (row["retain_state"], row["error_class"], normalize_error(error))
        group = groups.setdefault(key, _Group(first_at=at, last_at=at))
        group.count += 1
        group.last_at = at
        group.example = error
        group.example_document_id = row["hindsight_document_id"]
        company = row["slug"] or UNATTRIBUTED
        group.companies[company] = group.companies.get(company, 0) + 1
    ordered = sorted(
        groups.items(), key=lambda item: (-item[1].count, item[0][0], item[0][1] or "", item[0][2])
    )
    return [
        FailedGroup(
            state=state,
            error_class=error_class,
            error=error,
            count=group.count,
            example=group.example,
            example_document_id=group.example_document_id,
            first_at=group.first_at,
            last_at=group.last_at,
            companies=dict(sorted(group.companies.items())),
        )
        for (state, error_class, error), group in ordered
    ]


def _pending(
    connection: Connection, where: str, params: Mapping[str, Any], now: datetime
) -> list[PendingBucket]:
    """Pending sections by how long since they were last submitted (their row's update)."""
    since: list[datetime] = list(
        connection.execute(
            text(f"SELECT m.updated_at{_FROM} WHERE {where} AND m.retain_state = 'pending'"),
            params,
        ).scalars()
    )
    buckets: list[PendingBucket] = []
    lower = float("-inf")
    for age, upper in _AGE_BOUNDS:
        inside = [
            at
            for at in since
            if (now - at).total_seconds() >= lower
            and (upper is None or (now - at).total_seconds() < upper)
        ]
        buckets.append(
            PendingBucket(age=age, count=len(inside), oldest_at=min(inside) if inside else None)
        )
        lower = upper if upper is not None else lower
    return buckets


def _unavailable(error: HindsightError | None) -> str:
    return HINDSIGHT_NOT_CONFIGURED if error is None else f"{type(error).__name__}: {error}"


def _paged[T](
    read: Callable[[int], tuple[list[T], int]], max_pages: int
) -> tuple[list[T], int, bool]:
    """Every item of a paged listing, at most `max_pages` pages: (items, total, complete)."""
    items: list[T] = []
    total = 0
    for _ in range(max_pages):
        page, total = read(len(items))
        items.extend(page)
        if not page or len(items) >= total:
            return items, total, True
    return items, total, len(items) >= total


def _scopes(
    gateway: HindsightGateway | None, company_id: uuid.UUID | None
) -> ObservationScopesHealth:
    if gateway is None:
        return ObservationScopesHealth(status="unavailable", reason=_unavailable(None))

    def read(offset: int) -> tuple[list[ScopeCount], int]:
        page = gateway.observation_scopes(limit=PAGE_SIZE, offset=offset)
        return [ScopeCount(tags=s.tags, count=s.count) for s in page.scopes], page.total

    try:
        scopes, total, complete = _paged(read, MAX_SCOPE_PAGES)
    except HindsightError as error:
        return ObservationScopesHealth(status="unavailable", reason=_unavailable(error))
    if company_id is not None:
        scopes = [s for s in scopes if f"company:{company_id}" in s.tags]
    return ObservationScopesHealth(status="ok", total=total, complete=complete, scopes=scopes)


def company_names(config: CompanyConfig) -> tuple[list[str], list[str]]:
    """The names an entity of the company may carry, and its tickers."""
    names = list(dict.fromkeys([config.display_name, config.legal_name]))
    tickers = [security.ticker for security in config.securities]
    if config.tradingview_symbol:
        tickers.append(config.tradingview_symbol.split(":", 1)[1])
    return names, list(dict.fromkeys(tickers))


def matches(entity_name: str, names: Sequence[str], tickers: Sequence[str]) -> bool:
    """Whether an entity's name is one of the company's names (see the module docstring)."""
    normalized = normalize_name(entity_name)
    if not normalized:
        return False
    if entity_name.strip().upper() in {ticker.upper() for ticker in tickers}:
        return True
    own = [normalize_name(name) for name in names]
    if normalized in own:
        return True
    display = own[0].split()
    return bool(display) and normalized.split()[: len(display)] == display


def _entities(
    gateway: HindsightGateway | None,
    universe: Universe,
    companies: Mapping[uuid.UUID, Any],
    company_id: uuid.UUID | None,
) -> EntitiesHealth:
    if gateway is None:
        return EntitiesHealth(status="unavailable", reason=_unavailable(None))

    def read(offset: int) -> tuple[list[EntityMatch], int]:
        page = gateway.entities(limit=PAGE_SIZE, offset=offset)
        listed = [
            EntityMatch(id=e.id, canonical_name=e.canonical_name, mention_count=e.mention_count)
            for e in page.items
        ]
        return listed, page.total

    try:
        entities, total, complete = _paged(read, MAX_ENTITY_PAGES)
    except HindsightError as error:
        return EntitiesHealth(status="unavailable", reason=_unavailable(error))
    ids = {row["slug"]: key for key, row in companies.items()}
    found: list[CompanyEntities] = []
    for slug, config in universe.companies.items():
        if company_id is not None and ids.get(slug) != company_id:
            continue
        names, tickers = company_names(config)
        matched = [e for e in entities if matches(e.canonical_name, names, tickers)]
        found.append(
            CompanyEntities(
                company_id=ids.get(slug),
                slug=slug,
                display_name=config.display_name,
                names=names + tickers,
                entities=matched,
                one_entity=len(matched) == 1,
            )
        )
    return EntitiesHealth(
        status="ok", total=total, scanned=len(entities), complete=complete, companies=found
    )
