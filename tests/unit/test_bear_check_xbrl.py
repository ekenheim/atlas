"""The XBRL bear checks' edges (Chokepoint Watch ticket W4, review): dilution across splits and
share classes, and net cash from distinct debt concepts. Hand-built observations in, the check
out; the recorded filings are in `tests/integration/test_bear_checks.py`."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from atlas.bear_checks.models import DilutionCheck, NetCashCheck
from atlas.bear_checks.xbrl import dilution, net_cash
from atlas.financials import Observation, select_as_of

AS_OF = datetime(2026, 9, 29, tzinfo=UTC)
FILED = datetime(2026, 8, 17, tzinfo=UTC)


def obs(
    concept: str,
    end: str,
    value: int | str,
    *,
    taxonomy: str = "us-gaap",
    unit: str = "USD",
    start: str | None = None,
    accession: str = "0001-26-000001",
    filed: datetime = FILED,
) -> Observation:
    return Observation(
        id=uuid.uuid4(),
        cik="0000000001",
        source_version_id=uuid.uuid4(),
        taxonomy=taxonomy,
        concept=concept,
        unit=unit,
        period_start=date.fromisoformat(start) if start else None,
        period_end=date.fromisoformat(end),
        value=Decimal(value),
        accession=accession,
        form="10-K",
        filed=filed.date(),
        fiscal_year=None,
        fiscal_period=None,
        frame=None,
        available_at=filed,
        available_at_basis="sec_acceptance",
        accepted_at=filed,
        previous_observation_id=None,
        linkage="first",
        suspect_reasons=(),
    )


def dilution_of(*observations: Observation) -> DilutionCheck:
    return dilution(select_as_of(observations, AS_OF), observations, AS_OF)


def cover(end: str, value: int, accession: str = "0001-26-000001") -> Observation:
    return obs(
        "EntityCommonStockSharesOutstanding",
        end,
        value,
        taxonomy="dei",
        unit="shares",
        accession=accession,
    )


def weighted(start: str, end: str, value: int, accession: str = "0001-26-000001") -> Observation:
    return obs(
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        end,
        value,
        unit="shares",
        start=start,
        accession=accession,
    )


# --- dilution ---------------------------------------------------------------------------------


def test_ordinary_growth_is_flagged_above_ten_percent_and_clear_below():
    flagged = dilution_of(cover("2026-08-14", 111_000_000), cover("2025-08-12", 100_000_000))
    clear = dilution_of(cover("2026-08-14", 109_000_000), cover("2025-08-12", 100_000_000))

    assert (flagged.status, clear.status) == ("flag", "clear")
    assert flagged.value is not None and flagged.value.growth_pct == 11.0


def test_a_forward_split_is_unknown_not_a_hundred_percent_dilution():
    answer = dilution_of(cover("2026-08-14", 200_000_000), cover("2025-08-12", 100_000_000))

    assert (answer.status, answer.value) == ("unknown", None)
    assert "split" in answer.basis
    assert answer.unknown_reason == "split_suspected"
    assert answer.summary == (
        "Not known: the share count moved by a split's ratio, which is not new shares."
    )


def test_a_reverse_split_is_unknown_not_a_collapse():
    answer = dilution_of(cover("2026-08-14", 10_000_000), cover("2025-08-12", 100_000_000))

    assert answer.status == "unknown"
    assert "split" in answer.basis


def test_a_ratio_within_two_percent_of_a_whole_number_is_a_split_and_further_is_not():
    near = dilution_of(cover("2026-08-14", 296_000_000), cover("2025-08-12", 100_000_000))
    far = dilution_of(cover("2026-08-14", 190_000_000), cover("2025-08-12", 100_000_000))

    assert near.status == "unknown"  # 2.96, within 2% of 3
    assert far.status == "flag"  # 1.9 is not within 2% of 2


def test_a_split_uses_the_split_adjusted_weighted_diluted_shares_when_the_filing_has_them():
    # The later filing restates the earlier year's weighted shares for the split.
    answer = dilution_of(
        cover("2026-08-14", 200_000_000),
        cover("2025-08-12", 100_000_000),
        weighted("2025-06-29", "2026-06-27", 190_000_000),
        weighted("2024-06-30", "2025-06-28", 170_000_000),
    )

    assert answer.status == "flag"  # 190 / 170 = +11.8%
    assert answer.value is not None
    assert answer.value.growth_pct == 11.76
    assert "WeightedAverageNumberOfDilutedSharesOutstanding" in answer.basis
    assert "split" in answer.basis


def test_several_share_classes_on_the_cover_are_unknown():
    # Two values for one cover date in one filing: Class A and Class B.
    answer = dilution_of(
        cover("2026-08-14", 150_000_000),
        cover("2026-08-14", 20_000_000),
        cover("2025-08-12", 100_000_000),
    )

    assert answer.status == "unknown"
    assert "share classes" in answer.basis
    assert answer.unknown_reason == "several_share_classes"


# --- net cash ---------------------------------------------------------------------------------

END = "2026-06-27"


def net_cash_of(*observations: Observation) -> NetCashCheck:
    return net_cash(select_as_of(observations, AS_OF), AS_OF)


def test_the_filers_total_is_the_debt_and_is_named():
    answer = net_cash_of(
        obs("CashAndCashEquivalentsAtCarryingValue", END, 2000),
        obs("DebtLongtermAndShorttermCombinedAmount", END, 1600),
        obs("LongTermDebtCurrent", END, 1500),
        obs("LongTermDebtNoncurrent", END, 100),
    )

    assert answer.status == "clear"
    assert answer.value is not None and answer.value.debt == 1600
    assert "DebtLongtermAndShorttermCombinedAmount" in answer.basis


def test_a_total_that_is_not_its_parts_is_unknown():
    answer = net_cash_of(
        obs("CashAndCashEquivalentsAtCarryingValue", END, 2000),
        obs("DebtLongtermAndShorttermCombinedAmount", END, 1000),
        obs("LongTermDebtCurrent", END, 1500),
        obs("LongTermDebtNoncurrent", END, 100),
    )

    assert answer.status == "unknown"
    assert "total" in answer.basis
    assert answer.unknown_reason == "ambiguous_debt_tags"


def test_current_and_noncurrent_debt_are_summed_and_a_duplicate_concept_counts_once():
    answer = net_cash_of(
        obs("CashAndCashEquivalentsAtCarryingValue", END, 500),
        obs("LongTermDebtCurrent", END, 300),
        obs("ShortTermBorrowings", END, 300),  # the same borrowing, tagged twice
        obs("LongTermDebtNoncurrent", END, 400),
    )

    assert answer.status == "flag"
    assert answer.summary == "Debt exceeds cash by 200 (USD)."
    assert answer.value is not None and answer.value.debt == 700
    assert answer.value.net_cash == -200
    assert "LongTermDebtCurrent" in answer.basis and "LongTermDebtNoncurrent" in answer.basis


def test_distinct_current_borrowings_are_all_counted():
    answer = net_cash_of(
        obs("CashAndCashEquivalentsAtCarryingValue", END, 1000),
        obs("LongTermDebtCurrent", END, 100),
        obs("ShortTermBorrowings", END, 50),
        obs("LongTermDebtNoncurrent", END, 400),
    )

    assert answer.value is not None and answer.value.debt == 550
    assert "ShortTermBorrowings" in answer.basis


def test_two_different_noncurrent_debt_concepts_cannot_be_told_apart_so_unknown():
    answer = net_cash_of(
        obs("CashAndCashEquivalentsAtCarryingValue", END, 1000),
        obs("LongTermDebtCurrent", END, 100),
        obs("LongTermDebtNoncurrent", END, 400),
        obs("ConvertibleDebtNoncurrent", END, 250),  # part of the 400, or besides it?
    )

    assert answer.status == "unknown"
    assert answer.unknown_reason == "ambiguous_debt_tags"
    assert answer.summary == (
        "Not known: the company's debt is tagged in a way that cannot be added up."
    )


def test_a_line_of_credit_that_matches_no_other_concept_is_unknown():
    answer = net_cash_of(
        obs("CashAndCashEquivalentsAtCarryingValue", END, 1000),
        obs("LongTermDebtCurrent", END, 100),
        obs("LongTermDebtNoncurrent", END, 400),
        obs("LineOfCredit", END, 75),
    )

    assert answer.status == "unknown"
    assert "LineOfCredit" in answer.basis


def test_only_one_side_of_the_debt_is_unknown():
    answer = net_cash_of(
        obs("CashAndCashEquivalentsAtCarryingValue", END, 1000),
        obs("LongTermDebtNoncurrent", END, 400),
    )

    assert answer.status == "unknown"
    assert answer.unknown_reason == "debt_not_tagged"


def test_short_term_investments_are_added_to_cash():
    answer = net_cash_of(
        obs("CashAndCashEquivalentsAtCarryingValue", END, 100),
        obs("ShortTermInvestments", END, 400),
        obs("DebtLongtermAndShorttermCombinedAmount", END, 300),
    )

    assert answer.status == "clear"
    assert answer.value is not None and answer.value.net_cash == 200
