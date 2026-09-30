"""Triage windows (ticket 33): overlapping windows, so a sentence at a boundary is read whole.

`window_spans(length, size, overlap, cap)` is the pure part of the triage reader (and of the
full-section judge's chunks); expected offsets are written out by hand.
"""

import pytest

from atlas.retention.triage import WindowSpan, window_spans


def spans(length: int, size: int, overlap: int, cap: int | None = None) -> list[tuple[int, int]]:
    return [(span.start, span.end) for span in window_spans(length, size, overlap, cap)]


def test_a_text_that_fits_one_window_is_one_window() -> None:
    assert window_spans(1500, 1500, 200) == [WindowSpan(1, 1, 0, 1500)]
    assert window_spans(10, 1500, 200) == [WindowSpan(1, 1, 0, 10)]


def test_one_character_past_the_window_makes_a_second_window_that_overlaps() -> None:
    # The second window starts 200 characters before the first one ends.
    assert spans(1501, 1500, 200) == [(0, 1500), (1300, 1501)]


def test_consecutive_windows_overlap_by_exactly_the_overlap() -> None:
    # Stride 1300: windows start at 0, 1300, 2600, 3900; the last one ends at the text's end.
    assert spans(4000, 1500, 200) == [(0, 1500), (1300, 2800), (2600, 4000)]
    assert spans(4100, 1500, 200) == [(0, 1500), (1300, 2800), (2600, 4100)]
    assert spans(4101, 1500, 200) == [(0, 1500), (1300, 2800), (2600, 4100), (3900, 4101)]


def test_a_sentence_across_a_boundary_is_read_whole_in_the_next_window() -> None:
    text = "x" * 1480 + "Capacity doubles at the Thailand fab in 2027." + "y" * 1000
    sentence = text.index("Capacity"), text.index("2027.") + len("2027.")
    assert sentence[0] < 1500 < sentence[1]  # it straddles the first window's end
    whole = [
        (span.start, span.end)
        for span in window_spans(len(text), 1500, 200)
        if span.start <= sentence[0] and sentence[1] <= span.end
    ]
    assert whole == [(1300, 2525)]  # the second (and last) window


def test_without_overlap_the_windows_tile_the_text() -> None:
    assert spans(3001, 1500, 0) == [(0, 1500), (1500, 3000), (3000, 3001)]


def test_a_capped_reader_keeps_the_first_and_last_windows_and_spreads_the_rest() -> None:
    # 10 windows (stride 1300: the last starts at 11700), 3 read: parts 1, 5 (1 + round(4.5),
    # rounded half to even) and 10.
    chosen = window_spans(13000, 1500, 200, cap=3)
    assert [span.part for span in chosen] == [1, 5, 10]
    assert {span.parts for span in chosen} == {10}
    assert [(span.start, span.end) for span in chosen] == [
        (0, 1500),
        (5200, 6700),
        (11700, 13000),
    ]
    assert [span.part for span in window_spans(13000, 1500, 200, cap=1)] == [1]
    assert len(window_spans(13000, 1500, 200, cap=50)) == 10


def test_the_overlap_must_be_less_than_the_window() -> None:
    with pytest.raises(ValueError, match="overlap"):
        window_spans(5000, 1500, 1500)
