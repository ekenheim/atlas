"""The bear checks that read XBRL (Chokepoint Watch ticket W4): dilution, GAAP gross margin and
net cash, as pure functions over the as-of observations and canonical metric values of
`atlas.financials`. No database, no model: what the filings tagged, as of a cutoff.

A check without the data it needs is `unknown` and says what was missing; it is never `clear`.
A series whose latest value is more than `STALE_DAYS` before the cutoff is no evidence of the
company's position at the cutoff, so it is unknown too.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from atlas.bear_checks.models import BearCheck, BearCheckSource
from atlas.financials import MetricValue, Observation, PeriodKey
from atlas.financials.xbrl import period_type

STALE_DAYS = 456  # fifteen months
DILUTION_FLAG = Decimal("0.10")  # growth above 10% in a year
MARGIN_FALL_FLAG = Decimal(5)  # a fall of more than five points year on year

# Share counts, best first: the cover page's count is the most recent; the balance sheet's the
# fallback. Each is read in its own unit ("shares").
SHARE_SERIES = (
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesOutstanding"),
    ("ifrs-full", "NumberOfSharesOutstanding"),
)
# Short-term investments are no canonical metric; these are the tags read, first found wins.
SHORT_TERM_INVESTMENT_CONCEPTS = (
    ("us-gaap", "ShortTermInvestments"),
    ("us-gaap", "MarketableSecuritiesCurrent"),
    ("us-gaap", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"),
)
METRICS = (
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "cash",
    "total_debt",
    "debt_current",
    "debt_noncurrent",
)


def observation_source(observation: Observation) -> BearCheckSource:
    return BearCheckSource(
        kind="financial_observation",
        observation_id=observation.id,
        concept=f"{observation.taxonomy}:{observation.concept}",
        period_end=observation.period_end.isoformat(),
        value=str(observation.value),
        available_at=observation.available_at,
    )


def _sources(observations: Iterable[Observation]) -> list[BearCheckSource]:
    seen: dict[object, Observation] = {}
    for each in observations:
        seen.setdefault(each.id, each)
    return [observation_source(each) for each in seen.values()]


def _stale(end: date, as_of: datetime) -> bool:
    return (as_of.date() - end).days > STALE_DAYS


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _percent(value: Decimal) -> float:
    return round(float(value), 2)


def dilution(selected: Mapping[PeriodKey, Observation], as_of: datetime) -> BearCheck:
    """Shares outstanding now against a year earlier; flag above 10% growth."""
    reasons: list[str] = []
    for taxonomy, concept in SHARE_SERIES:
        series = sorted(
            (
                each
                for key, each in selected.items()
                if (key.taxonomy, key.concept, key.unit) == (taxonomy, concept, "shares")
                and each.value > 0
            ),
            key=lambda each: each.period_end,
        )
        name = f"{taxonomy}:{concept}"
        if not series:
            continue
        latest = series[-1]
        if _stale(latest.period_end, as_of):
            reasons.append(f"{name}'s latest count is from {latest.period_end}")
            continue
        target = latest.period_end - timedelta(days=365)
        earlier = [
            each
            for each in series
            if abs((each.period_end - target).days) <= 60 and each is not latest
        ]
        if not earlier:
            reasons.append(f"{name} has no count within 60 days of {target}")
            continue
        before = min(earlier, key=lambda each: abs((each.period_end - target).days))
        growth = latest.value / before.value - 1
        flagged = growth > DILUTION_FLAG
        return BearCheck(
            key="dilution",
            status="flag" if flagged else "clear",
            value={
                "concept": name,
                "shares": _number(latest.value),
                "shares_as_of": latest.period_end.isoformat(),
                "shares_year_earlier": _number(before.value),
                "year_earlier_as_of": before.period_end.isoformat(),
                "growth_pct": _percent(growth * 100),
            },
            basis=(
                f"{name}: {_number(latest.value):,} at {latest.period_end} against"
                f" {_number(before.value):,} at {before.period_end}, {_percent(growth * 100):+}%;"
                " flag above +10%"
            ),
            sources=_sources((latest, before)),
        )
    detail = "; ".join(reasons) if reasons else "no share-count observation (dei or balance sheet)"
    return BearCheck(
        key="dilution",
        status="unknown",
        value=None,
        basis=f"shares outstanding cannot be compared with a year earlier: {detail}",
        sources=[],
    )


def _chain(available: Mapping[date, Any], last: date, count: int = 4) -> list[date] | None:
    """`count` consecutive fiscal quarter ends ending at `last` (each 80 to 100 days apart)."""
    ends = [last]
    for _ in range(count - 1):
        candidates = [e for e in available if 80 <= (ends[-1] - e).days <= 100]
        if not candidates:
            return None
        ends.append(min(candidates, key=lambda e: abs((ends[-1] - e).days - 91)))
    return ends


class _Quarter:
    def __init__(
        self, end: date, revenue: Decimal, gross_profit: Decimal, sources: list[Observation]
    ):
        self.end = end
        self.revenue = revenue
        self.gross_profit = gross_profit
        self.sources = sources


def _quarters(values: Sequence[MetricValue], unit: str) -> dict[date, _Quarter]:
    by_end: dict[date, dict[str, MetricValue]] = {}
    for value in values:
        if (
            value.unit == unit
            and value.metric in ("revenue", "cost_of_revenue", "gross_profit")
            and period_type(value.period_start, value.period_end) == "quarter"
        ):
            by_end.setdefault(value.period_end, {})[value.metric] = value
    quarters: dict[date, _Quarter] = {}
    for end, found in by_end.items():
        revenue = found.get("revenue")
        if revenue is None:
            continue
        if "gross_profit" in found:
            profit = found["gross_profit"]
            quarters[end] = _Quarter(
                end, revenue.value, profit.value, [*revenue.sources, *profit.sources]
            )
        elif "cost_of_revenue" in found:
            cost = found["cost_of_revenue"]
            quarters[end] = _Quarter(
                end, revenue.value, revenue.value - cost.value, [*revenue.sources, *cost.sources]
            )
    return quarters


def _margin(quarters: Sequence[_Quarter]) -> Decimal | None:
    revenue = sum((each.revenue for each in quarters), Decimal(0))
    if revenue <= 0:
        return None
    return sum((each.gross_profit for each in quarters), Decimal(0)) / revenue * 100


def gaap_gross_margin(values: Sequence[MetricValue], as_of: datetime) -> BearCheck:
    """Gross profit over revenue for the trailing four quarters, against the four a year
    before; flag below zero or a fall of more than five points. Gross profit is the filer's
    `GrossProfit`, else revenue less cost of revenue."""
    units = sorted({each.unit for each in values})
    best: tuple[date, str, dict[date, _Quarter]] | None = None
    for unit in units:
        quarters = _quarters(values, unit)
        if quarters and (best is None or max(quarters) > best[0]):
            best = (max(quarters), unit, quarters)
    unknown = BearCheck(
        key="gaap_gross_margin",
        status="unknown",
        value=None,
        basis="",
        sources=[],
    )
    if best is None:
        unknown.basis = "no quarterly revenue and gross profit (or cost of revenue) in XBRL"
        return unknown
    latest, unit, quarters = best
    if _stale(latest, as_of):
        unknown.basis = f"the latest quarter with revenue and gross profit ended {latest}"
        return unknown
    ends = _chain(quarters, latest)
    if ends is None:
        unknown.basis = (
            f"fewer than four consecutive quarters of revenue and gross profit ending {latest}"
        )
        return unknown
    current = [quarters[each] for each in reversed(ends)]
    margin = _margin(current)
    if margin is None:
        unknown.basis = "revenue of the trailing four quarters is not positive"
        return unknown

    prior: list[_Quarter] | None = None
    prior_margin: Decimal | None = None
    year_before = [e for e in quarters if 350 <= (latest - e).days <= 380]
    if year_before:
        prior_ends = _chain(quarters, min(year_before, key=lambda e: abs((latest - e).days - 364)))
        if prior_ends is not None:
            prior = [quarters[each] for each in reversed(prior_ends)]
            prior_margin = _margin(prior)
    change = margin - prior_margin if prior_margin is not None else None

    value: dict[str, Any] = {
        "unit": unit,
        "ttm_margin_pct": _percent(margin),
        "prior_ttm_margin_pct": _percent(prior_margin) if prior_margin is not None else None,
        "change_points": _percent(change) if change is not None else None,
        "quarters": [
            {
                "period_end": each.end.isoformat(),
                "revenue": _number(each.revenue),
                "gross_profit": _number(each.gross_profit),
                "margin_pct": _percent(each.gross_profit / each.revenue * 100)
                if each.revenue > 0
                else None,
            }
            for each in current
        ],
    }
    used = [source for each in current + (prior or []) for source in each.sources]
    if margin < 0:
        status, rule = "flag", "flag: the trailing margin is below zero"
    elif change is not None and change < -MARGIN_FALL_FLAG:
        status, rule = "flag", "flag: a fall of more than 5 points year on year"
    elif change is not None:
        status, rule = "clear", "no flag: not below zero, no fall of more than 5 points"
    else:
        status, rule = "unknown", "no four consecutive quarters a year earlier to compare with"
    basis = (
        f"trailing four quarters to {latest}: gross margin {_percent(margin)}%"
        + (f" against {_percent(prior_margin)}% a year earlier" if prior_margin is not None else "")
        + f" ({unit}); {rule}"
    )
    return BearCheck(
        key="gaap_gross_margin", status=status, value=value, basis=basis, sources=_sources(used)
    )


def net_cash(
    selected: Mapping[PeriodKey, Observation], values: Sequence[MetricValue], as_of: datetime
) -> BearCheck:
    """Cash and short-term investments less debt at the latest balance sheet date that has cash
    and debt; flag net debt. Debt is the filer's total, else its current and noncurrent parts
    (a filer tagging only one of them is unknown: debt it did not tag is not zero)."""
    instants: dict[tuple[str, str], dict[date, MetricValue]] = {}
    for value in values:
        if value.metric in ("cash", "total_debt", "debt_current", "debt_noncurrent") and (
            value.period_start is None
        ):
            instants.setdefault((value.metric, value.unit), {})[value.period_end] = value
    cash_units = sorted(
        (unit for metric, unit in instants if metric == "cash"),
        key=lambda unit: -max(instants[("cash", unit)]).toordinal(),
    )
    unknown = BearCheck(key="net_cash", status="unknown", value=None, basis="", sources=[])
    if not cash_units:
        unknown.basis = "no cash and cash equivalents in XBRL"
        return unknown
    unit = cash_units[0]
    end = max(instants[("cash", unit)])
    if _stale(end, as_of):
        unknown.basis = f"the latest balance sheet with cash is at {end}"
        return unknown
    cash = instants[("cash", unit)][end]
    debt_parts: list[MetricValue]
    total = instants.get(("total_debt", unit), {}).get(end)
    current = instants.get(("debt_current", unit), {}).get(end)
    noncurrent = instants.get(("debt_noncurrent", unit), {}).get(end)
    if total is not None:
        debt_parts = [total]
    elif current is not None and noncurrent is not None:
        debt_parts = [current, noncurrent]
    else:
        unknown.basis = f"no total debt, or current and noncurrent debt, tagged at {end}"
        return unknown
    investments = next(
        (
            each
            for taxonomy, concept in SHORT_TERM_INVESTMENT_CONCEPTS
            for key, each in selected.items()
            if (key.taxonomy, key.concept, key.unit, key.start, key.end)
            == (taxonomy, concept, unit, None, end)
        ),
        None,
    )
    debt = sum((each.value for each in debt_parts), Decimal(0))
    net = cash.value + (investments.value if investments else Decimal(0)) - debt
    used = [
        *cash.sources,
        *([investments] if investments else []),
        *[s for p in debt_parts for s in p.sources],
    ]
    return BearCheck(
        key="net_cash",
        status="flag" if net < 0 else "clear",
        value={
            "unit": unit,
            "as_of_balance_sheet": end.isoformat(),
            "net_cash": _number(net),
            "cash": _number(cash.value),
            "short_term_investments": _number(investments.value) if investments else None,
            "debt": _number(debt),
        },
        basis=(
            f"balance sheet at {end}: cash {_number(cash.value):,}"
            + (f" + short-term investments {_number(investments.value):,}" if investments else "")
            + f" - debt {_number(debt):,} = {_number(net):,} ({unit});"
            + (" flag: net debt" if net < 0 else " no flag: net cash")
            + ("" if investments else "; no short-term investments tagged, counted as none")
        ),
        sources=_sources(used),
    )
