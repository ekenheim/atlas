"""Locating a chunk in its section (memory-quality ticket 08; atlas.research.chunks): the rule
ticket 01 recorded on 0.10.2 (`docs/hindsight-feature-matrix.md`, question (b); recordings
`chunks/03-list-chunks` and `chunks/05-get-document`)."""

from typing import Any, cast

from atlas.research.chunks import locate
from tests.fakes.hindsight import load_recordings


def test_the_recorded_chunks_are_located_where_the_feature_matrix_found_them() -> None:
    recordings = load_recordings()
    document = cast(dict[str, Any], recordings["chunks/05-get-document"].response_body)
    listed = cast(dict[str, Any], recordings["chunks/03-list-chunks"].response_body)
    content: str = document["original_text"]
    chunks = [(c["chunk_id"], c["chunk_text"]) for c in listed["items"]]

    spans = locate(content, chunks)

    # The matrix: chunk 0 is content[0:603], chunk 1 content[605:813]; the break between them
    # and the final newline belong to no chunk.
    assert list(spans.values()) == [(0, 603), (605, 813)]


def test_a_chunk_is_searched_from_where_the_previous_one_ended() -> None:
    section = "Alpha beta.\n\nGamma.\n\nAlpha beta.\n\nDelta."
    spans = locate(section, [("c0", "Alpha beta."), ("c1", "Gamma."), ("c2", "Alpha beta.")])
    assert spans == {"c0": (0, 11), "c1": (13, 19), "c2": (21, 32)}


def test_a_chunk_that_is_not_a_slice_is_left_out_and_moves_nothing() -> None:
    section = "Alpha beta.\n\nGamma."
    spans = locate(section, [("c0", "Alpha beta."), ("c1", "Not here."), ("c2", "Gamma.")])
    assert spans == {"c0": (0, 11), "c2": (13, 19)}
