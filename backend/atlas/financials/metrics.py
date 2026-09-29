"""Canonical metrics (revenue, capex, ...) over as-of selected XBRL observations.

A metric is an ordered concept family per taxonomy (`configs/financials/metrics.yaml`).
For each (unit, period) the value comes from the latest filing that tagged any concept of
the family; inside that filing the first listed concept wins, and another listed concept
with a different value flags `concept_mismatch`.

A flow metric's missing quarter is derived from two year-to-date values with the same
start (Q2 = H1 - Q1, Q3 = 9M - H1, Q4 = FY - 9M) when the difference spans a quarter,
which holds 52/53-week calendars (a 98-day quarter, a 371-day year). A derived value keeps
both sources, is available when the later one is, and is only ever computed within one
currency unit: values in different currencies are never combined without a stated FX basis,
which Atlas doesn't have (every value is as filed; `fx_basis` is None).
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from atlas.financials.xbrl import (
    Observation,
    PeriodKey,
    is_monetary_amount,
    period_type,
    unit_currency,
)

MetricFlag = Literal["derived", "concept_mismatch", "sign_change", "large_change", "old_period"]


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    flow: bool
    concepts: dict[str, list[str]] = Field(min_length=1)  # taxonomy -> concepts, by precedence


class MetricCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    metrics: dict[str, MetricDefinition]


def load_metric_catalog(path: Path) -> MetricCatalog:
    return MetricCatalog.model_validate(yaml.safe_load(path.read_text()))


class CurrencyMismatch(ValueError):
    """Two values in different units were about to be combined."""


@dataclass(frozen=True)
class MetricValue:
    metric: str
    unit: str
    period_start: date | None
    period_end: date
    value: Decimal
    derived: bool
    concept: str | None  # the reported concept, or the sources' shared concept if derived
    available_at: datetime
    sources: tuple[Observation, ...]  # derived: (the longer period, the shorter one)
    flags: tuple[MetricFlag, ...]

    @property
    def currency(self) -> str | None:
        return unit_currency(self.unit)


def metric_values(
    selected: Mapping[PeriodKey, Observation],
    catalog: MetricCatalog,
    metrics: Iterable[str] | None = None,
) -> list[MetricValue]:
    """Every metric's value per (unit, period) from as-of `selected` observations, reported
    ones first then derived quarters; ordered by metric, unit and period."""
    names = list(catalog.metrics) if metrics is None else list(metrics)
    values: list[MetricValue] = []
    for name in names:
        definition = catalog.metrics[name]
        reported = _reported(name, definition, selected)
        values += reported
        if definition.flow:
            values += _derived_quarters(name, reported)
    values.sort(key=lambda v: (v.metric, v.unit, v.period_end, v.period_start or date.min))
    return values


def _reported(
    name: str, definition: MetricDefinition, selected: Mapping[PeriodKey, Observation]
) -> list[MetricValue]:
    rank = {
        (taxonomy, concept): position
        for taxonomy, concepts in definition.concepts.items()
        for position, concept in enumerate(concepts)
    }
    groups: dict[tuple[str, date | None, date], list[Observation]] = defaultdict(list)
    for key, observation in selected.items():
        if (key.taxonomy, key.concept) in rank:
            groups[(key.unit, key.start, key.end)].append(observation)

    values: list[MetricValue] = []
    for (unit, start, end), candidates in groups.items():
        latest = max(o.order[:3] for o in candidates)
        filing = [o for o in candidates if o.order[:3] == latest]
        winner = min(filing, key=lambda o: rank[(o.taxonomy, o.concept)])
        flags: list[MetricFlag] = list(winner.suspect_reasons)
        if any(o.value != winner.value for o in filing):
            flags.append("concept_mismatch")
        values.append(
            MetricValue(
                metric=name,
                unit=unit,
                period_start=start,
                period_end=end,
                value=winner.value,
                derived=False,
                concept=winner.concept,
                available_at=winner.available_at,
                sources=(winner,),
                flags=tuple(flags),
            )
        )
    return values


def derive_difference(name: str, longer: MetricValue, shorter: MetricValue) -> MetricValue:
    """`longer - shorter` over the part of `longer`'s period after `shorter`'s end."""
    if longer.unit != shorter.unit:
        raise CurrencyMismatch(
            f"{name}: {longer.unit} and {shorter.unit} can't be combined without an FX basis"
        )
    sources = (*longer.sources, *shorter.sources)
    concepts = {source.concept for source in sources}
    flags: list[MetricFlag] = ["derived"]
    for flag in (*longer.flags, *shorter.flags):
        if flag not in flags:
            flags.append(flag)
    return MetricValue(
        metric=name,
        unit=longer.unit,
        period_start=shorter.period_end + timedelta(days=1),
        period_end=longer.period_end,
        value=longer.value - shorter.value,
        derived=True,
        concept=concepts.pop() if len(concepts) == 1 else None,
        available_at=max(longer.available_at, shorter.available_at),
        sources=sources,
        flags=tuple(flags),
    )


def _derived_quarters(name: str, reported: list[MetricValue]) -> list[MetricValue]:
    have = {(v.unit, v.period_start, v.period_end) for v in reported}
    chains: dict[tuple[str, date], list[MetricValue]] = defaultdict(list)
    for value in reported:
        if value.period_start is not None and is_monetary_amount(value.unit):
            chains[(value.unit, value.period_start)].append(value)
    derived: list[MetricValue] = []
    for chain in chains.values():
        chain.sort(key=lambda v: v.period_end)
        for shorter, longer in pairwise(chain):
            start = shorter.period_end + timedelta(days=1)
            if period_type(start, longer.period_end) != "quarter":
                continue
            if (longer.unit, start, longer.period_end) in have:
                continue
            derived.append(derive_difference(name, longer, shorter))
    return derived
