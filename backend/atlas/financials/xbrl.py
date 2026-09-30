"""XBRL companyfacts as as-of observations: parsing, availability, linkage and selection.

Pure functions (no database); `atlas.financials.service` stores and reads what they produce.
The rules are those of docs/research/xbrl-normalization.md (branch research/xbrl-normalization)
§3-§4 and docs/decisions.md, "XBRL normalization":

- An observation is one fact of one filing: (taxonomy, concept, unit, start, end, accession).
  Its period key drops the accession. `fy`, `fp` and `frame` describe the *filing* (and
  `frame` is SEC's "latest filing" marker, computed now): they are stored for information
  and never used to find a period or to select a value.
- `available_at` is the filing's availability (`filing_availability`: EDGAR dissemination),
  never the companyfacts fetch time. An accession the submissions index doesn't list, or
  one outside the EDGAR holiday table, falls back to 23:59:59 ET on its `filed` date (basis
  `sec_filing_date_eod`): EDGAR's filing date is the day the filing was disseminated, so
  that is never earlier than the truth.
- As of a cutoff, a period key's value is the eligible observation (periodic-report form,
  `available_at <= as_of`) of the latest filing: greatest (available_at, accepted_at,
  accession). Amendments win because they are later.
- Over a key's history in that order, a different value *restates* its predecessor and an
  equal one *reaffirms* it. A restatement is suspect (still selected, shown for review) on
  a sign change, a change of more than 50%, or a period ending more than two years before
  the filing's report date: the shapes of tagging errors such as Lumentum's EPS of 3.29.
"""

import json
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Literal, NamedTuple

from pydantic import BaseModel

from atlas.sources.adapter import SecFiling
from atlas.sources.edgar import filing_availability, normalize_cik
from atlas.sources.edgar_calendar import EASTERN, EdgarCalendarRangeError

ObservationBasis = Literal[
    "sec_acceptance", "sec_dissemination", "sec_filing_date_eod", "observed_revision"
]
Linkage = Literal["first", "restates", "reaffirms"]
SuspectReason = Literal["sign_change", "large_change", "old_period"]
PeriodType = Literal["instant", "quarter", "half_year", "nine_months", "year", "other"]

# Periodic reports: an 8-K's or 6-K's XBRL (a few filers tag releases) is never as-of data.
PERIODIC_FORMS = frozenset({"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"})
LARGE_CHANGE = Decimal("0.5")
OLD_PERIOD_YEARS = 2
# Duration lengths in days (end - start + 1). 52/53-week filers have 91- or 98-day quarters
# and 364- or 371-day years; calendar filers 90-92 and 365-366.
_PERIOD_DAYS: tuple[tuple[PeriodType, int, int], ...] = (
    ("quarter", 84, 98),
    ("half_year", 175, 189),
    ("nine_months", 266, 280),
    ("year", 357, 371),
)


class PeriodKey(NamedTuple):
    taxonomy: str
    concept: str
    unit: str
    start: date | None
    end: date


@dataclass(frozen=True)
class CompanyFact:
    """One fact as companyfacts lists it."""

    taxonomy: str
    concept: str
    unit: str
    start: date | None
    end: date
    value: Decimal
    accession: str
    form: str
    filed: date
    fiscal_year: int | None
    fiscal_period: str | None
    frame: str | None

    @property
    def key(self) -> PeriodKey:
        return PeriodKey(self.taxonomy, self.concept, self.unit, self.start, self.end)


@dataclass(frozen=True)
class CompanyFacts:
    cik: str
    entity_name: str
    facts: list[CompanyFact]


@dataclass(frozen=True)
class Observation:
    """A stored fact of one filing, with its availability and its place in the key's history."""

    id: uuid.UUID
    cik: str
    source_version_id: uuid.UUID
    taxonomy: str
    concept: str
    unit: str
    period_start: date | None
    period_end: date
    value: Decimal
    accession: str
    form: str
    filed: date
    fiscal_year: int | None
    fiscal_period: str | None
    frame: str | None
    available_at: datetime
    available_at_basis: ObservationBasis
    accepted_at: datetime | None
    previous_observation_id: uuid.UUID | None
    linkage: Linkage
    suspect_reasons: tuple[SuspectReason, ...]

    @property
    def key(self) -> PeriodKey:
        return PeriodKey(self.taxonomy, self.concept, self.unit, self.period_start, self.period_end)

    @property
    def currency(self) -> str | None:
        return unit_currency(self.unit)

    @property
    def order(self) -> tuple[datetime, datetime, str, str]:
        """Filing order: latest filing last. The value only breaks an (unseen) exact tie."""
        return (
            self.available_at,
            self.accepted_at or self.available_at,
            self.accession,
            str(self.value),
        )


class _Fact(BaseModel):
    start: date | None = None
    end: date
    val: Decimal
    accn: str
    fy: int | None = None
    fp: str | None = None
    form: str
    filed: date
    frame: str | None = None


class _Concept(BaseModel):
    units: dict[str, list[_Fact]]


class _CompanyFacts(BaseModel):
    cik: int | str
    entityName: str
    facts: dict[str, dict[str, _Concept]] = {}


def parse_companyfacts(content: bytes) -> CompanyFacts:
    """Every fact of a companyfacts JSON document. Numbers are read as exact decimals."""
    document = _CompanyFacts.model_validate(
        json.loads(content, parse_float=Decimal, parse_int=Decimal)
    )
    facts = [
        CompanyFact(
            taxonomy=taxonomy,
            concept=concept,
            unit=unit,
            start=fact.start,
            end=fact.end,
            value=fact.val,
            accession=fact.accn,
            form=fact.form,
            filed=fact.filed,
            fiscal_year=fact.fy,
            fiscal_period=fact.fp,
            frame=fact.frame,
        )
        for taxonomy, concepts in document.facts.items()
        for concept, data in concepts.items()
        for unit, unit_facts in data.units.items()
        for fact in unit_facts
    ]
    return CompanyFacts(
        cik=normalize_cik(str(int(document.cik))), entity_name=document.entityName, facts=facts
    )


def unit_currency(unit: str) -> str | None:
    """The ISO currency of a monetary unit ('USD', and 'USD/shares' per share), else None."""
    numerator = unit.split("/", 1)[0]
    return (
        numerator if len(numerator) == 3 and numerator.isalpha() and numerator.isupper() else None
    )


def is_monetary_amount(unit: str) -> bool:
    """A plain currency amount ('EUR'), which adds up over periods; not a per-share value."""
    return "/" not in unit and unit_currency(unit) is not None


def period_type(start: date | None, end: date) -> PeriodType:
    if start is None:
        return "instant"
    days = (end - start).days + 1
    for name, low, high in _PERIOD_DAYS:
        if low <= days <= high:
            return name
    return "other"


def period_days(start: date | None, end: date) -> int | None:
    return None if start is None else (end - start).days + 1


def filed_end_of_day(filed: date) -> datetime:
    """23:59:59 ET on the filing date, in UTC: the conservative fallback availability."""
    return datetime.combine(filed, time(23, 59, 59), tzinfo=EASTERN).astimezone(UTC)


def fact_availability(
    accession: str, filed: date, filings: Mapping[str, SecFiling]
) -> tuple[datetime, ObservationBasis, datetime | None]:
    """(available_at, basis, accepted_at) of a fact of `accession`, from its filing."""
    filing = filings.get(accession)
    if filing is not None:
        try:
            available_at, basis = filing_availability(filing)
        except EdgarCalendarRangeError:
            return filed_end_of_day(filed), "sec_filing_date_eod", filing.acceptance_datetime
        if basis == "sec_acceptance" or basis == "sec_dissemination":
            return available_at, basis, filing.acceptance_datetime
    return filed_end_of_day(filed), "sec_filing_date_eod", None


def normalize(
    companyfacts: CompanyFacts,
    filings: Iterable[SecFiling],
    *,
    source_version_id: uuid.UUID,
    snapshot_available_at: datetime,
    existing: Sequence[Observation] = (),
) -> list[Observation]:
    """The new observations in a companyfacts snapshot, linked into the `existing` history.

    A fact already stored (same key, accession and value) is skipped. A fact whose accession
    already has a *different* value for its key was revised inside companyfacts: it is new,
    available from when Atlas saw it (`snapshot_available_at`, basis `observed_revision`).
    Linkage and suspect flags of new observations are computed against the key's whole
    history; stored observations are never changed.

    The result is in filing order (`Observation.order`), so each new observation's
    predecessor is either stored already or earlier in the list: inserting it in this order
    satisfies the restatement link's foreign key. companyfacts' own order can't be used: it
    lists some keys' facts newest filing first (Coherent's, 2026-09-30).
    """
    by_accession = {filing.accession_number: filing for filing in filings}
    report_dates = _report_dates(companyfacts.facts, by_accession)
    stored: dict[tuple[PeriodKey, str], set[Decimal]] = defaultdict(set)
    history: dict[PeriodKey, list[Observation]] = defaultdict(list)
    for observation in existing:
        stored[(observation.key, observation.accession)].add(observation.value)
        history[observation.key].append(observation)

    new: list[Observation] = []
    for fact in companyfacts.facts:
        values = stored[(fact.key, fact.accession)]
        if fact.value in values:
            continue
        available_at, basis, accepted_at = fact_availability(
            fact.accession, fact.filed, by_accession
        )
        if values:
            available_at, basis = max(available_at, snapshot_available_at), "observed_revision"
        values.add(fact.value)
        observation = Observation(
            id=uuid.uuid4(),
            cik=companyfacts.cik,
            source_version_id=source_version_id,
            taxonomy=fact.taxonomy,
            concept=fact.concept,
            unit=fact.unit,
            period_start=fact.start,
            period_end=fact.end,
            value=fact.value,
            accession=fact.accession,
            form=fact.form,
            filed=fact.filed,
            fiscal_year=fact.fiscal_year,
            fiscal_period=fact.fiscal_period,
            frame=fact.frame,
            available_at=available_at,
            available_at_basis=basis,
            accepted_at=accepted_at,
            previous_observation_id=None,
            linkage="first",
            suspect_reasons=(),
        )
        new.append(observation)
        history[fact.key].append(observation)

    new_ids = {observation.id for observation in new}
    linked: dict[uuid.UUID, Observation] = {}
    for observations in history.values():
        if not new_ids.intersection(o.id for o in observations):
            continue
        ordered = sorted(observations, key=lambda o: o.order)
        for previous, current in zip([None, *ordered], ordered, strict=False):
            if current.id in new_ids:
                linked[current.id] = _link(current, previous, report_dates)
    return sorted((linked[observation.id] for observation in new), key=lambda o: o.order)


def _link(
    current: Observation, previous: Observation | None, report_dates: Mapping[str, date]
) -> Observation:
    if previous is None:
        return current
    if current.value == previous.value:
        return replace(current, previous_observation_id=previous.id, linkage="reaffirms")
    reasons: list[SuspectReason] = []
    old, new = previous.value, current.value
    if old != 0 and new != 0 and (old > 0) != (new > 0):
        reasons.append("sign_change")
    if old == 0 or abs(new - old) / abs(old) > LARGE_CHANGE:
        reasons.append("large_change")
    report_date = report_dates.get(current.accession)
    if report_date is not None and current.period_end < _years_before(
        report_date, OLD_PERIOD_YEARS
    ):
        reasons.append("old_period")
    return replace(
        current,
        previous_observation_id=previous.id,
        linkage="restates",
        suspect_reasons=tuple(reasons),
    )


def _years_before(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February
        return day.replace(year=day.year - years, day=28)


def _report_dates(
    facts: Sequence[CompanyFact], filings: Mapping[str, SecFiling]
) -> dict[str, date]:
    """Each accession's report period: the submissions index's `reportDate`, else the latest
    period end among its financial (non-`dei`) facts, which is the period it reports."""
    latest: dict[str, date] = {}
    for fact in facts:
        if fact.taxonomy != "dei" and fact.end > latest.get(fact.accession, date.min):
            latest[fact.accession] = fact.end
    for accession, filing in filings.items():
        if filing.report_date is not None:
            latest[accession] = filing.report_date
    return latest


def select_as_of(
    observations: Iterable[Observation], as_of: datetime
) -> dict[PeriodKey, Observation]:
    """Per period key, the value of the latest periodic-report filing available at `as_of`."""
    selected: dict[PeriodKey, Observation] = {}
    for observation in observations:
        if observation.form not in PERIODIC_FORMS or observation.available_at > as_of:
            continue
        current = selected.get(observation.key)
        if current is None or observation.order > current.order:
            selected[observation.key] = observation
    return selected
