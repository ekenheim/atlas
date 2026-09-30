"""The triage audit's statistics (ticket 33): the Wilson interval and the length bands.

Expected intervals are the published Wilson score values (Wilson 1927; e.g. Newcombe 1998,
Table I), not recomputed the way the code does.
"""

import pytest

from atlas.retention.audit import length_band, wilson_interval


def test_the_wilson_interval_matches_published_values() -> None:
    low, high = wilson_interval(1, 10)
    assert (round(low, 4), round(high, 4)) == (0.0179, 0.4042)
    low, high = wilson_interval(0, 40)
    assert low == 0.0
    assert round(high, 4) == 0.0876  # z^2 / (n + z^2): informative at 0 of n
    low, high = wilson_interval(81, 263)  # Newcombe's example
    assert (round(low, 4), round(high, 4)) == (0.2553, 0.3662)


def test_the_wilson_interval_stays_in_the_unit_interval() -> None:
    assert wilson_interval(10, 10)[1] == 1.0
    assert wilson_interval(0, 0) == (0.0, 1.0)
    with pytest.raises(ValueError):
        wilson_interval(3, 2)


def test_length_bands() -> None:
    assert [length_band(n) for n in (1, 1999, 2000, 9999, 10_000, 49_999, 50_000, 143_495)] == [
        "under-2k",
        "under-2k",
        "2k-10k",
        "2k-10k",
        "10k-50k",
        "10k-50k",
        "50k-plus",
        "50k-plus",
    ]
