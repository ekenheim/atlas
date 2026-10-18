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
from atlas.financials.xbrl import is_monetary_amount, period_type

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


SPLIT_TOLERANCE = Decimal("0.02")
# Ratios of share counts a year apart that are splits (and reverse splits), not issuance.
SPLIT_RATIOS = tuple(
    Decimal(n) / Decimal(d)
    for n, d in (
        (2, 1), (3, 1), (4, 1), (5, 1), (10, 1), (3, 2),
        (1, 2), (1, 3), (1, 4), (1, 5), (1, 10), (2, 3),
    )
)  # fmt: skip
WEIGHTED_SERIES = (
    ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding"),
    ("ifrs-full", "AdjustedWeightedAverageShares"),
)


def _split_like(ratio: Decimal) -> bool:
    return any(abs(ratio - each) <= each * SPLIT_TOLERANCE for each in SPLIT_RATIOS)


def _several_classes(observations: Iterable[Observation], one: Observation) -> bool:
    """Whether the same filing gives another value for the same cover fact and date: the
    filer's share classes (companyfacts drops the class, so they collide on one key)."""
    return any(
        each.key == one.key and each.accession == one.accession and each.value != one.value
        for each in observations
    )


def _weighted_pair(
    selected: Mapping[PeriodKey, Observation], as_of: datetime
) -> tuple[str, Observation, Observation] | None:
    """The latest weighted diluted share count (a year or a quarter) and the same period a year
    earlier, as the latest filing reports them: restated for any split in between."""
    for taxonomy, concept in WEIGHTED_SERIES:
        series = [
            each
            for key, each in selected.items()
            if (key.taxonomy, key.concept, key.unit) == (taxonomy, concept, "shares")
            and each.value > 0
            and each.period_start is not None
            and period_type(each.period_start, each.period_end) in ("quarter", "year")
        ]
        for latest in sorted(series, key=lambda each: each.period_end, reverse=True):
            if _stale(latest.period_end, as_of):
                break
            kind = period_type(latest.period_start, latest.period_end)
            earlier = [
                each
                for each in series
                if period_type(each.period_start, each.period_end) == kind
                and 350 <= (latest.period_end - each.period_end).days <= 380
            ]
            if earlier:
                return f"{taxonomy}:{concept}", latest, earlier[0]
    return None


def dilution(
    selected: Mapping[PeriodKey, Observation],
    observations: Iterable[Observation],
    as_of: datetime,
) -> BearCheck:
    """Shares outstanding now against a year earlier; flag above 10% growth. A count that moves
    by a split's ratio is not issuance: the check then uses the weighted diluted shares as the
    latest filing reports them (restated for the split) or is unknown. A filer with several
    share classes is unknown (companyfacts does not say which class a count is)."""
    everything = list(observations)
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
        if _several_classes(everything, latest) or _several_classes(everything, before):
            return _unknown_dilution(
                f"{name} gives several values for one date in one filing: the filer reports"
                " several share classes, and the classes compared cannot be told apart"
            )
        ratio = latest.value / before.value
        if _split_like(ratio):
            return _split_dilution(selected, as_of, name, ratio, latest, before)
        return _dilution_check(name, latest, before, f"{name}: ")
    detail = "; ".join(reasons) if reasons else "no share-count observation (dei or balance sheet)"
    return _unknown_dilution(f"shares outstanding cannot be compared with a year earlier: {detail}")


def _unknown_dilution(basis: str) -> BearCheck:
    return BearCheck(key="dilution", status="unknown", value=None, basis=basis, sources=[])


def _dilution_check(
    name: str, latest: Observation, before: Observation, lead: str, note: str = ""
) -> BearCheck:
    growth = latest.value / before.value - 1
    return BearCheck(
        key="dilution",
        status="flag" if growth > DILUTION_FLAG else "clear",
        value={
            "concept": name,
            "shares": _number(latest.value),
            "shares_as_of": latest.period_end.isoformat(),
            "shares_year_earlier": _number(before.value),
            "year_earlier_as_of": before.period_end.isoformat(),
            "growth_pct": _percent(growth * 100),
        },
        basis=(
            f"{lead}{_number(latest.value):,} at {latest.period_end} against"
            f" {_number(before.value):,} at {before.period_end}, {_percent(growth * 100):+}%;"
            f" flag above +10%{note}"
        ),
        sources=_sources((latest, before)),
    )


def _split_dilution(
    selected: Mapping[PeriodKey, Observation],
    as_of: datetime,
    name: str,
    ratio: Decimal,
    latest: Observation,
    before: Observation,
) -> BearCheck:
    said = f"{name} changed by a factor of {_percent(ratio)}, which looks like a split"
    pair = _weighted_pair(selected, as_of)
    if pair is None:
        return _unknown_dilution(
            f"{said}, and there is no split-adjusted weighted diluted share count to use instead"
        )
    weighted, now, then = pair
    if _split_like(now.value / then.value):
        return _unknown_dilution(
            f"{said}, and the weighted diluted shares ({weighted}) move by a split's ratio too"
        )
    return _dilution_check(
        weighted,
        now,
        then,
        f"split-adjusted weighted diluted shares ({weighted}): ",
        f" ({said}; the weighted counts are the latest filing's, restated for it)",
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


CASH_CONCEPTS = (
    ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
    ("ifrs-full", "CashAndCashEquivalents"),
)
# Debt concepts by what they are, per taxonomy. A total includes the current part; a side is
# the current or the noncurrent debt; `other` concepts (a line of credit, notes) may be a part
# of a side or besides it, which a filing's tags do not say.
DEBT: dict[str, dict[str, tuple[str, ...]]] = {
    "us-gaap": {
        "totals": ("DebtLongtermAndShorttermCombinedAmount", "LongTermDebt"),
        "current_total": ("DebtCurrent",),
        "current": (
            "LongTermDebtCurrent",
            "ShortTermBorrowings",
            "ConvertibleNotesPayableCurrent",
            "ConvertibleDebtCurrent",
            "NotesPayableCurrent",
        ),
        "noncurrent": (
            "LongTermDebtNoncurrent",
            "ConvertibleDebtNoncurrent",
            "ConvertibleNotesPayableNoncurrent",
            "NotesPayableNoncurrent",
        ),
        "other": (
            "LineOfCredit",
            "LongTermLineOfCredit",
            "ConvertibleNotesPayable",
            "NotesPayable",
            "SecuredDebt",
            "UnsecuredDebt",
            "LongTermDebtAndCapitalLeaseObligations",
        ),
    },
    "ifrs-full": {
        "totals": ("Borrowings",),
        "current_total": ("CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",),
        "current": (),
        "noncurrent": ("LongtermBorrowings", "NoncurrentPortionOfNoncurrentBorrowings"),
        "other": (),
    },
}
DEBT_TOLERANCE = Decimal("0.01")


class _Debt:
    def __init__(self, amount: Decimal, text: str, used: list[Observation]) -> None:
        self.amount = amount
        self.text = text
        self.used = used


def _distinct(found: Sequence[Observation]) -> list[tuple[Decimal, list[Observation]]]:
    """The observations grouped by value, in order: one concept tagged twice is one debt."""
    groups: list[tuple[Decimal, list[Observation]]] = []
    for each in found:
        for value, same in groups:
            if value == each.value:
                same.append(each)
                break
        else:
            groups.append((each.value, [each]))
    return groups


def _names(observations: Sequence[Observation]) -> str:
    return " = ".join(each.concept for each in observations)


def _debt(
    selected: Mapping[PeriodKey, Observation], taxonomy: str, unit: str, end: date
) -> _Debt | str:
    """The company's debt at a balance sheet date from the distinct debt concepts tagged, or why
    that cannot be told."""
    families = DEBT.get(taxonomy)
    if families is None:
        return f"debt concepts of {taxonomy} are not read"

    def tagged(family: str) -> list[Observation]:
        return [
            each
            for concept in families[family]
            if (each := selected.get(PeriodKey(taxonomy, concept, unit, None, end))) is not None
        ]

    totals = _distinct(tagged("totals"))
    if len(totals) > 1:
        return "the debt totals tagged disagree: " + "; ".join(_names(o) for _, o in totals)
    current_total = _distinct(tagged("current_total"))
    current_parts = _distinct(tagged("current"))
    noncurrent = _distinct(tagged("noncurrent"))
    if len(noncurrent) > 1:
        return (
            "noncurrent debt is tagged as "
            + " and ".join(_names(o) for _, o in noncurrent)
            + " with different amounts: whether one is part of the other is not tagged"
        )
    current: tuple[Decimal, list[Observation]] | None = None
    if current_total:
        current = current_total[0]
        if any(value > current[0] for value, _ in current_parts):
            return "a current debt concept exceeds the current debt total tagged"
    elif current_parts:
        current = (
            sum((value for value, _ in current_parts), Decimal(0)),
            [o for _, group in current_parts for o in group],
        )
    current_text = (
        " + ".join(_names(group) for _, group in (current_total or current_parts))
        if current is not None
        else ""
    )
    parts_amount: Decimal | None = None
    if current is not None and noncurrent:
        parts_amount = current[0] + noncurrent[0][0]
    total_amount = totals[0][0] if totals else None
    used: list[Observation] = []
    if total_amount is not None:
        if parts_amount is not None and abs(parts_amount - total_amount) > max(
            abs(total_amount) * DEBT_TOLERANCE, Decimal(1)
        ):
            return (
                f"the total debt tagged ({_names(totals[0][1])}) is not the sum of its current"
                " and noncurrent parts"
            )
        amount = total_amount
        text = _names(totals[0][1])
        used = list(totals[0][1])
        if parts_amount is not None and current is not None:
            text += (
                f" (the current {_names(current[1])} and noncurrent {_names(noncurrent[0][1])}"
                " add up to it)"
            )
    elif parts_amount is not None and current is not None:
        amount = parts_amount
        text = f"{current_text} (current) + {_names(noncurrent[0][1])} (noncurrent)"
        used = [*current[1], *noncurrent[0][1]]
    else:
        return "no total debt, or both current and noncurrent debt, is tagged"
    known = {amount, *(each.value for each in used)}
    if current is not None:
        known.add(current[0])
    if noncurrent:
        known.add(noncurrent[0][0])
    for other in tagged("other"):
        if other.value != 0 and other.value not in known:
            return (
                f"{other.concept} ({_number(other.value):,}) is tagged beside the debt above:"
                " whether it is part of it is not tagged"
            )
    return _Debt(amount, text, used)


def net_cash(selected: Mapping[PeriodKey, Observation], as_of: datetime) -> BearCheck:
    """Cash and short-term investments less debt at the latest balance sheet date that has cash;
    flag net debt. Debt is the distinct debt concepts tagged, each named in the basis: the
    filer's total, or its current and noncurrent debt (a duplicate tag counts once). When the
    tags do not say what is a total and what a part, or debt is not tagged (not zero), the check
    is unknown."""
    unknown = BearCheck(key="net_cash", status="unknown", value=None, basis="", sources=[])
    cash_sets = [
        (taxonomy, each)
        for taxonomy, concept in CASH_CONCEPTS
        for key, each in selected.items()
        if (key.taxonomy, key.concept) == (taxonomy, concept)
        and key.start is None
        and is_monetary_amount(key.unit)
    ]
    if not cash_sets:
        unknown.basis = "no cash and cash equivalents in XBRL"
        return unknown
    taxonomy, cash = max(cash_sets, key=lambda pair: pair[1].period_end)
    unit, end = cash.unit, cash.period_end
    if _stale(end, as_of):
        unknown.basis = f"the latest balance sheet with cash is at {end}"
        return unknown
    debt = _debt(selected, taxonomy, unit, end)
    if isinstance(debt, str):
        unknown.basis = f"balance sheet at {end}: {debt}"
        return unknown
    investments = next(
        (
            each
            for tax, concept in SHORT_TERM_INVESTMENT_CONCEPTS
            for key, each in selected.items()
            if (key.taxonomy, key.concept, key.unit, key.start, key.end)
            == (tax, concept, unit, None, end)
        ),
        None,
    )
    net = cash.value + (investments.value if investments else Decimal(0)) - debt.amount
    return BearCheck(
        key="net_cash",
        status="flag" if net < 0 else "clear",
        value={
            "unit": unit,
            "as_of_balance_sheet": end.isoformat(),
            "net_cash": _number(net),
            "cash": _number(cash.value),
            "short_term_investments": _number(investments.value) if investments else None,
            "debt": _number(debt.amount),
            "debt_concepts": [each.concept for each in debt.used],
        },
        basis=(
            f"balance sheet at {end}: cash {_number(cash.value):,}"
            + (f" + short-term investments {_number(investments.value):,}" if investments else "")
            + f" - debt {_number(debt.amount):,} [{debt.text}] = {_number(net):,} ({unit});"
            + (" flag: net debt" if net < 0 else " no flag: net cash")
            + ("" if investments else "; no short-term investments tagged, counted as none")
        ),
        sources=_sources([cash, *([investments] if investments else []), *debt.used]),
    )
