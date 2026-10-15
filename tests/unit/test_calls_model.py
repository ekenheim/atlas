"""The arithmetic of the prospective record (atlas-beliefs ticket 19): due dates, the close of a
day, a company's move and a checkpoint. Literal values, worked out by hand."""

from datetime import UTC, date, datetime

from atlas.calls.model import (
    Close,
    Move,
    add_months,
    close_on_or_before,
    due_on,
    move,
    outcome,
    step_direction,
)


def test_months_are_calendar_months_and_a_day_the_month_lacks_becomes_its_last() -> None:
    assert add_months(date(2026, 10, 16), 1) == date(2026, 11, 16)
    assert add_months(date(2026, 10, 16), 3) == date(2027, 1, 16)
    assert add_months(date(2026, 10, 16), 6) == date(2027, 4, 16)
    assert add_months(date(2026, 8, 31), 1) == date(2026, 9, 30)
    assert add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert add_months(date(2027, 11, 30), 3) == date(2028, 2, 29)  # a leap year


def test_a_call_falls_due_from_its_utc_date() -> None:
    late_evening_in_new_york = datetime.fromisoformat(
        "2026-10-16T23:30:00-04:00"
    )  # 03:30Z, the 17th
    assert due_on(late_evening_in_new_york, 1) == date(2026, 11, 17)
    assert due_on(datetime(2026, 10, 16, 0, 0, tzinfo=UTC), 6) == date(2027, 4, 16)


def test_the_close_of_a_day_is_its_own_or_the_last_before_it_within_a_week() -> None:
    closes = [Close(date(2026, 10, 12), 100.0), Close(date(2026, 10, 14), 104.0)]
    assert close_on_or_before(closes, date(2026, 10, 14)) == Close(date(2026, 10, 14), 104.0)
    assert close_on_or_before(closes, date(2026, 10, 17)) == Close(date(2026, 10, 14), 104.0)
    assert close_on_or_before(closes, date(2026, 10, 21)) == Close(date(2026, 10, 14), 104.0)
    assert close_on_or_before(closes, date(2026, 10, 22)) is None  # eight days stale
    assert close_on_or_before(closes, date(2026, 10, 11)) is None  # nothing yet


def test_a_move_runs_from_the_call_date_to_the_due_day() -> None:
    closes = [Close(date(2026, 10, 15), 80.0), Close(date(2026, 11, 13), 100.0)]
    one = move("lumentum", "NASDAQ:LITE", closes, date(2026, 10, 16), date(2026, 11, 16))
    assert one == Move(
        "lumentum", "NASDAQ:LITE", date(2026, 10, 15), 80.0, date(2026, 11, 13), 100.0
    )
    assert one is not None and one.change == 0.25
    assert move("x", "A:B", [], date(2026, 10, 16), date(2026, 11, 16)) is None
    assert (
        move("x", "A:B", [Close(date(2026, 10, 15), 0.0)], date(2026, 10, 16), date(2026, 10, 16))
        is None
    )


def test_a_checkpoint_is_the_calls_equal_weighted_change_against_the_benchmarks() -> None:
    day = date(2026, 10, 16)
    a = Move("a", "X:A", day, 100.0, day, 110.0)  # +10%
    b = Move("b", "X:B", day, 50.0, day, 50.0)  # 0%
    c = Move("c", "X:C", day, 10.0, day, 9.0)  # -10%
    result = outcome([a, c], [a, b, c])
    assert result is not None
    assert (result.change, result.benchmark_change, result.relative_change) == (0.0, 0.0, 0.0)

    result = outcome([a], [a, b, c])
    assert result is not None
    assert (result.change, result.benchmark_change, result.relative_change) == (0.1, 0.0, 0.1)

    third = Move("d", "X:D", day, 3.0, day, 3.0)
    result = outcome([a, b], [a, b, third])  # calls +5%, peers +3.333333%
    assert result is not None
    assert (result.change, result.benchmark_change, result.relative_change) == (
        0.05,
        0.033333,
        0.016667,
    )


def test_a_checkpoint_without_peers_has_no_relative_change_and_without_companies_none() -> None:
    day = date(2026, 10, 16)
    a = Move("a", "X:A", day, 100.0, day, 90.0)
    result = outcome([a], [])
    assert result is not None
    assert (result.change, result.benchmark_change, result.relative_change) == (-0.1, None, None)
    assert outcome([], [a]) is None


def test_a_steps_direction() -> None:
    assert step_direction("constraint") == "tightening"
    assert step_direction("demand_vs_supply") == "tightening"
    assert step_direction("relief") == "easing"
    assert step_direction("invalidation") == "easing"
    assert step_direction("control") is None
    assert step_direction("capture") is None
