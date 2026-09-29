"""The read side: as-of financial figures and observations, each with its full source.

Every figure carries the observations it came from, and every observation its accession,
form, taxonomy, concept, period, unit, currency, FX basis and `available_at` (spec story 44).
"""

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Connection

from atlas.financials.metrics import MetricCatalog, MetricValue, metric_values
from atlas.financials.service import (
    company_observations,
    get_observation,
    key_history,
)
from atlas.financials.xbrl import (
    Observation,
    PeriodType,
    period_days,
    period_type,
    select_as_of,
)


class FxBasis(BaseModel):
    """How a value was converted from its reporting currency. Atlas has no FX source yet, so
    every value is as filed and this is always null."""

    rate_source: str
    rate_date: date
    from_currency: str


class FinancialObservation(BaseModel):
    """One XBRL fact of one filing, as of its filing's availability."""

    id: uuid.UUID
    cik: str
    source_version_id: uuid.UUID  # the archived companyfacts it was read from
    accession: str
    form: str
    filed: date
    fiscal_year: int | None  # the filing's, not the fact's (informational)
    fiscal_period: str | None  # the filing's, not the fact's (informational)
    frame: str | None  # SEC's "latest filing" marker, computed now: never used for as-of
    taxonomy: str
    concept: str
    unit: str
    currency: str | None
    fx_basis: FxBasis | None  # null: in the reporting currency, as filed
    period_start: date | None
    period_end: date
    period_type: PeriodType
    period_days: int | None
    value: Decimal
    available_at: datetime
    available_at_basis: str
    accepted_at: datetime | None
    previous_observation_id: uuid.UUID | None
    linkage: str  # first, restates or reaffirms (its predecessor)
    suspect_reasons: list[str]


class FinancialFigure(BaseModel):
    """A canonical metric's value for one period and unit, as of the cutoff."""

    metric: str
    label: str
    unit: str
    currency: str | None
    fx_basis: FxBasis | None
    period_start: date | None
    period_end: date
    period_type: PeriodType
    period_days: int | None
    value: Decimal
    derived: bool  # e.g. Q4 = FY - 9M; `sources` holds both
    concept: str | None
    available_at: datetime
    flags: list[str]
    sources: list[FinancialObservation]


class FinancialFigures(BaseModel):
    company_id: uuid.UUID
    as_of: datetime
    metrics_version: int
    figures: list[FinancialFigure]


class FinancialObservationHistory(BaseModel):
    observation: FinancialObservation
    history: list[FinancialObservation]  # every observation of its period key, in filing order


def observation_view(observation: Observation) -> FinancialObservation:
    return FinancialObservation(
        id=observation.id,
        cik=observation.cik,
        source_version_id=observation.source_version_id,
        accession=observation.accession,
        form=observation.form,
        filed=observation.filed,
        fiscal_year=observation.fiscal_year,
        fiscal_period=observation.fiscal_period,
        frame=observation.frame,
        taxonomy=observation.taxonomy,
        concept=observation.concept,
        unit=observation.unit,
        currency=observation.currency,
        fx_basis=None,
        period_start=observation.period_start,
        period_end=observation.period_end,
        period_type=period_type(observation.period_start, observation.period_end),
        period_days=period_days(observation.period_start, observation.period_end),
        value=observation.value,
        available_at=observation.available_at,
        available_at_basis=observation.available_at_basis,
        accepted_at=observation.accepted_at,
        previous_observation_id=observation.previous_observation_id,
        linkage=observation.linkage,
        suspect_reasons=list(observation.suspect_reasons),
    )


def _figure(value: MetricValue, catalog: MetricCatalog) -> FinancialFigure:
    return FinancialFigure(
        metric=value.metric,
        label=catalog.metrics[value.metric].label,
        unit=value.unit,
        currency=value.currency,
        fx_basis=None,
        period_start=value.period_start,
        period_end=value.period_end,
        period_type=period_type(value.period_start, value.period_end),
        period_days=period_days(value.period_start, value.period_end),
        value=value.value,
        derived=value.derived,
        concept=value.concept,
        available_at=value.available_at,
        flags=list(value.flags),
        sources=[observation_view(source) for source in value.sources],
    )


def financial_figures(
    connection: Connection,
    company_id: uuid.UUID,
    catalog: MetricCatalog,
    as_of: datetime,
    metrics: Sequence[str] | None = None,
) -> FinancialFigures:
    selected = select_as_of(company_observations(connection, company_id), as_of)
    values = metric_values(selected, catalog, metrics)
    return FinancialFigures(
        company_id=company_id,
        as_of=as_of,
        metrics_version=catalog.version,
        figures=[_figure(value, catalog) for value in values],
    )


def selected_observations(
    connection: Connection,
    company_id: uuid.UUID,
    as_of: datetime,
    **filters: Any,
) -> list[FinancialObservation]:
    """The as-of observation of every period key, optionally only these taxonomy, concept or
    unit; ordered by taxonomy, concept, unit and period."""
    selected = select_as_of(company_observations(connection, company_id), as_of)
    wanted = {name: value for name, value in filters.items() if value is not None}
    keys = sorted(
        (key for key in selected if all(getattr(key, name) == v for name, v in wanted.items())),
        key=lambda k: (k.taxonomy, k.concept, k.unit, k.end, k.start or date.min),
    )
    return [observation_view(selected[key]) for key in keys]


def observation_history(
    connection: Connection, observation_id: uuid.UUID
) -> FinancialObservationHistory | None:
    observation = get_observation(connection, observation_id)
    if observation is None:
        return None
    return FinancialObservationHistory(
        observation=observation_view(observation),
        history=[observation_view(o) for o in key_history(connection, observation)],
    )
