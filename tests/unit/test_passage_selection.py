"""Passage selection (memory-directed reading ticket 05): which windows are candidates, in
what order they are best, and how the budget is dealt (floor, ceiling, ties, a window chosen
twice). The texts are hand-written; the allocation sentence is Lumentum's (pilot
investigation 1), the rest filler."""

import uuid

import pytest

from atlas.claims.selection import (
    Candidate,
    Document,
    Pointer,
    Reading,
    candidates,
    ceiling,
    deal,
    keeps_a_passage,
    placements,
    select,
    selections,
)
from atlas.research.search import bm25, overlap, query_terms, tokens
from atlas.retention.sections import split_sections

ALLOCATION = (
    "This demand is outpacing our current supply which has required us to make decisions on"
    " supply allocation."
)
MEMORY = "Demand for Lumentum laser chips outpaces its supply, forcing allocation decisions"
FILLER = "The quarterly dividend policy and the lease of the headquarters were unchanged."
NVIDIA = uuid.UUID(int=1)
LUMENTUM = uuid.UUID(int=2)
ENTITIES = [(NVIDIA, ["NVIDIA", "NVIDIA Corporation"]), (LUMENTUM, ["Lumentum"])]


def paragraph(sentence: str, filler: str = FILLER, chars: int = 2900) -> str:
    """One line of about `chars` characters that starts with `sentence`: a window of its own."""
    line = sentence
    while len(line) + len(filler) + 1 < chars:
        line += " " + filler
    return line + "\n"


def note(*paragraphs: str, company_id: uuid.UUID | None = None) -> Document:
    """A document with no Item headings (chunk sections), a window per paragraph."""
    return Document(id=uuid.uuid4(), text="".join(paragraphs), company_id=company_id)


def texts(document: Document, found: list[Candidate]) -> list[str]:
    return [document.text[each.start : each.end] for each in found]


# --- candidates -----------------------------------------------------------------------------------


def test_a_pointer_chooses_the_window_of_its_section_that_best_matches_the_memory() -> None:
    document = note(
        paragraph("We make optical components."),
        paragraph("Customers order lasers from us."),
        paragraph(ALLOCATION),
        paragraph("We lease our facilities."),
    )
    pointer = Pointer(document.id, "chunk-001", rank=3, query_index=2, memory_text=MEMORY)

    [found] = candidates([document], reading=Reading(pointers=[pointer]))

    assert document.text[found.start : found.end].startswith(ALLOCATION)
    assert found.selected_by == ("pointer:2",)
    assert found.pointer == (3, 2)


def test_a_pointer_whose_memory_matches_no_window_chooses_its_section_s_first_window() -> None:
    document = note(paragraph("We make optical components."), paragraph(ALLOCATION))
    pointer = Pointer(document.id, "chunk-001", 1, 0, "Gallium export permits were delayed")

    [found] = candidates([document], reading=Reading(pointers=[pointer]))

    assert found.start == 0


def test_a_pointer_into_a_section_the_parse_lacks_chooses_among_the_whole_document() -> None:
    document = note(paragraph("We make optical components."), paragraph(ALLOCATION))
    pointer = Pointer(document.id, "part-i-item-1", 1, 0, MEMORY)

    [found] = candidates([document], reading=Reading(pointers=[pointer]))

    assert document.text[found.start : found.end].startswith(ALLOCATION)


def test_a_pointer_into_another_document_chooses_nothing() -> None:
    document = note(paragraph(ALLOCATION))
    pointer = Pointer(uuid.uuid4(), "chunk-001", 1, 0, MEMORY)

    found = candidates([document], reading=Reading(pointers=[pointer]))

    assert [each.selected_by for each in found] == [("lead",)]


def test_search_ranks_the_windows_by_the_question_s_and_the_queries_terms() -> None:
    document = note(
        paragraph("We lease our facilities."),
        paragraph("Indium phosphide substrates are supplied by a few vendors."),
        paragraph("Export permits for gallium and germanium were delayed.", chars=1400),
    )

    found = candidates(
        [document],
        question="Who supplies indium phosphide substrate?",
        reading=Reading(queries=["gallium germanium export permits"]),
    )

    # The window with none of the terms is no candidate; singular matches plural.
    assert [each.selected_by for each in found] == [("search",), ("search",)]
    assert [text.split(".")[0] for text in texts(document, found)] == [
        "Indium phosphide substrates are supplied by a few vendors",
        "Export permits for gallium and germanium were delayed",
    ]
    assert all(each.score > 0 and each.pointer is None for each in found)
    # Best first is by score, across the question's and the queries' terms.
    best = deal(found, floors=(), budget=1, ceiling=1)
    assert texts(document, best)[0].startswith("Export permits")


def test_a_window_naming_another_known_company_is_an_entity_candidate() -> None:
    document = note(
        paragraph("Lumentum makes lasers."),
        paragraph("We sell lasers to NVIDIA."),
        company_id=LUMENTUM,
    )

    found = candidates([document], entities=ENTITIES)

    # The document's own company never tags a window; with no question there is no search.
    assert [(each.selected_by, each.score) for each in found] == [((f"entity:{NVIDIA}",), 0.0)]
    assert texts(document, found)[0].startswith("We sell lasers to NVIDIA.")


def test_a_window_chosen_by_several_selections_is_one_candidate_recording_them_all() -> None:
    document = note(
        paragraph("We lease our facilities."),
        paragraph(ALLOCATION + " NVIDIA is a customer."),
        company_id=LUMENTUM,
    )
    pointers = [
        Pointer(document.id, "chunk-001", rank=7, query_index=3, memory_text=MEMORY),
        Pointer(document.id, "chunk-001", rank=2, query_index=0, memory_text=MEMORY),
        Pointer(document.id, "chunk-001", rank=9, query_index=3, memory_text=MEMORY),
    ]

    found = candidates(
        [document],
        entities=ENTITIES,
        question="supply allocation",
        reading=Reading(pointers=pointers),
    )

    assert len(found) == 1
    assert found[0].selected_by == ("pointer:0", "pointer:3", "search", f"entity:{NVIDIA}")
    assert found[0].pointer == (2, 0)  # its best pointer
    chosen = select(
        [document],
        entities=ENTITIES,
        question="supply allocation",
        reading=Reading(pointers=pointers),
        budget=5,
        ceiling=5,
    )
    assert len(chosen.passages) == 1
    assert chosen.passages[0].selected_by == list(found[0].selected_by)
    assert chosen.dropped == 0


def test_a_labelled_pointer_is_recorded_by_its_label_not_its_query_number() -> None:
    # The Skeptic's pointers carry their bear-checklist item (memory-directed reading ticket
    # 07), so its passages' tags never read as a Scout query's number. Order is by rank, then
    # the query's number, as for any pointer; pointers sharing a label are one tag.
    document = note(paragraph("We lease our facilities."), paragraph(ALLOCATION))
    pointers = [
        Pointer(document.id, "chunk-001", 4, 9, MEMORY, label="customer_concentration"),
        Pointer(document.id, "chunk-001", 1, 2, MEMORY, label="inventory_cycle"),
        Pointer(document.id, "chunk-001", 6, 8, MEMORY, label="inventory_cycle"),
    ]

    [found] = candidates([document], reading=Reading(pointers=pointers))

    assert document.text[found.start : found.end].startswith(ALLOCATION)
    assert found.selected_by == ("pointer:inventory_cycle", "pointer:customer_concentration")
    assert found.pointer == (1, 2)
    assert selections(found.selected_by) == ["pointer"]


def chunk_placed(document: Document, chunk_start: int, *, label: str | None = None) -> Pointer:
    """A pointer into the document's first section placed by its fact's chunk, which starts at
    `chunk_start`; its Memory text matches the allocation window best (memory-quality 08)."""
    [section, *_] = split_sections(document.text, form=None, primary=False)
    return Pointer(
        document.id,
        section.anchor,
        1,
        2,
        MEMORY,
        label=label,
        section_char_start=section.start,
        section_char_end=section.end,
        chunk_char_start=chunk_start,
    )


def test_a_pointer_placed_by_its_chunk_reads_the_window_the_chunk_starts_in() -> None:
    first = paragraph("We make optical components.")
    document = note(first, paragraph(ALLOCATION), paragraph("We lease our facilities."))
    pointers = [
        chunk_placed(document, len(first) - 40),  # starts at the end of the first window
        chunk_placed(document, len(first) - 40, label="inventory_cycle"),
    ]

    [found] = candidates([document], reading=Reading(pointers=pointers))

    assert (found.start, found.end) == (0, len(first))
    assert found.selected_by == ("pointer:2:chunk", "pointer:inventory_cycle:chunk")
    assert selections(found.selected_by) == ["pointer"]
    assert placements(found.selected_by) == ["chunk"]


def test_a_chunk_placed_pointer_into_a_section_the_parse_has_elsewhere_is_placed_by_match() -> None:
    # The parse read is not the one the chunk was located in: its section lies elsewhere.
    first = paragraph("We make optical components.")
    document = note(first, paragraph(ALLOCATION))
    pointer = chunk_placed(document, 10)
    moved = Pointer(
        pointer.source_version_id,
        pointer.section_anchor,
        pointer.rank,
        pointer.query_index,
        pointer.memory_text,
        section_char_start=5,
        section_char_end=pointer.section_char_end,
        chunk_char_start=10,
    )

    [found] = candidates([document], reading=Reading(pointers=[moved]))

    assert document.text[found.start : found.end].startswith(ALLOCATION)
    assert found.selected_by == ("pointer:2",)
    assert placements(found.selected_by) == ["match"]


def test_how_a_passage_s_pointers_were_placed() -> None:
    assert placements(["pointer:0:chunk", "pointer:3", "search"]) == ["chunk", "match"]
    assert placements(["pointer:customer_concentration:chunk"]) == ["chunk"]
    assert placements(["search", f"entity:{NVIDIA}", "lead"]) == []


def test_lead_windows_are_offered_only_by_a_document_with_no_other_candidate() -> None:
    matching = note(paragraph("We lease our facilities."), paragraph("We make lasers."))
    silent = note(paragraph("Officer changes."), paragraph("Exhibits."))

    found = candidates([matching, silent], question="lasers")

    assert [(each.document, each.selected_by, each.lead) for each in found] == [
        (0, ("search",), None),
        (1, ("lead",), 0),
        (1, ("lead",), 1),
    ]


def test_an_8_k_s_lead_windows_start_with_its_results_item() -> None:
    eight_k = Document(
        id=uuid.uuid4(),
        text=(
            "FORM 8-K cover page\n"
            "Item 2.02. Results of Operations and Financial Condition.\nThe press release.\n"
            "Item 9.01. Financial Statements and Exhibits.\nExhibit 99.1\n"
        ),
        form_type="8-K",
        document_type="8-K",
        items=("2.02", "9.01"),
    )

    found = candidates([eight_k])

    assert [each.section_anchor for each in found] == ["item-2-02", "item-9-01"]  # no cover
    assert [each.lead for each in found] == [0, 1]


# --- best first, and the dealing ------------------------------------------------------------------


def pointed(document: int, rank: int, query: int = 0, start: int = 0) -> Candidate:
    return Candidate(document, "s", start, start + 10, (f"pointer:{query}",), pointer=(rank, query))


def searched(document: int, score: float, start: int = 0) -> Candidate:
    return Candidate(document, "s", start, start + 10, ("search",), score=score)


def lead(document: int, position: int) -> Candidate:
    return Candidate(document, "s", position * 10, position * 10 + 10, ("lead",), lead=position)


def both(document: int, rank: int, score: float, start: int = 0) -> Candidate:
    """A window a pointer chose that the search matches too."""
    return Candidate(
        document, "s", start, start + 10, ("pointer:0", "search"), pointer=(rank, 0), score=score
    )


def test_pointer_windows_by_rank_and_search_windows_by_score_alternate_then_leads() -> None:
    offered = [
        lead(3, 0),
        searched(0, 2.5),
        Candidate(0, "s", 50, 60, ("entity:x",), score=0.0),
        pointed(1, rank=4),
        searched(1, 9.0, start=20),
        pointed(2, rank=1, query=3),
        pointed(0, rank=1, query=0, start=30),
    ]

    dealt = deal(offered, floors=(), budget=10, ceiling=10)

    assert dealt == [
        pointed(0, rank=1, query=0, start=30),  # rank 1, the question's
        searched(1, 9.0, start=20),  # the best search window
        pointed(2, rank=1, query=3),  # rank 1, a later query's
        searched(0, 2.5),
        pointed(1, rank=4),
        Candidate(0, "s", 50, 60, ("entity:x",), score=0.0),  # an entity window matching no term
        lead(3, 0),
    ]


def test_ties_go_to_the_earlier_document_then_the_earlier_window() -> None:
    offered = [
        searched(1, 3.0, start=0),
        searched(0, 3.0, start=40),
        searched(0, 3.0, start=10),
        pointed(1, rank=2, start=5),
        pointed(0, rank=2, start=70),
    ]

    dealt = deal(offered, floors=(), budget=4, ceiling=4)

    assert dealt == [
        pointed(0, rank=2, start=70),
        searched(0, 3.0, start=10),
        pointed(1, rank=2, start=5),
        searched(0, 3.0, start=40),
    ]


def test_pointer_windows_do_not_crowd_out_the_search_windows_of_a_document_memory_lacks() -> None:
    # A retained 10-K with more pointer windows than the whole budget, and a transcript not
    # yet retained: no memory, so no pointer; only the search reaches it.
    retained = [pointed(0, rank=n + 1, start=n * 10) for n in range(12)]
    transcript = [searched(1, 9.0 - n, start=n * 10) for n in range(6)]

    dealt = deal([*retained, *transcript], floors=(), budget=8, ceiling=8)

    # Half the budget each, taken in turn: the best four of either channel.
    assert [each.document for each in dealt] == [0, 1, 0, 1, 0, 1, 0, 1]
    assert [each for each in dealt if each.document == 0] == retained[:4]
    assert [each for each in dealt if each.document == 1] == transcript[:4]


def test_when_one_channel_runs_out_the_other_takes_the_rest() -> None:
    retained = [pointed(0, rank=n + 1, start=n * 10) for n in range(12)]
    transcript = [searched(1, 9.0 - n, start=n * 10) for n in range(2)]

    few_search_windows = deal([*retained, *transcript], floors=(), budget=8, ceiling=8)
    few_pointers = deal([*retained[:1], *transcript], floors=(), budget=8, ceiling=8)

    assert [each.document for each in few_search_windows] == [0, 1, 0, 1, 0, 0, 0, 0]
    assert few_pointers == [retained[0], *transcript]


def test_a_window_both_channels_chose_is_taken_once() -> None:
    offered = [
        both(0, rank=1, score=9.0),  # the best pointer window is the best search window too
        pointed(0, rank=2, start=10),
        pointed(0, rank=3, start=20),
        searched(1, 5.0),
        searched(1, 4.0, start=10),
    ]

    dealt = deal(offered, floors=(), budget=4, ceiling=4)

    assert dealt == [
        both(0, rank=1, score=9.0),
        searched(1, 5.0),  # the search's turn passes over the window already taken
        pointed(0, rank=2, start=10),
        searched(1, 4.0, start=10),
    ]


def test_the_ceiling_counts_a_document_s_pointer_and_search_windows_together() -> None:
    ten_k = [
        *(pointed(0, rank=n + 1, start=n * 10) for n in range(5)),
        *(searched(0, 20.0 - n, start=100 + n * 10) for n in range(5)),
    ]
    release = [searched(1, 5.0 - n, start=n * 10) for n in range(3)]

    under_the_ceiling = deal([*ten_k, *release], floors=(), budget=4, ceiling=2)
    with_budget_left = deal([*ten_k, *release], floors=(), budget=6, ceiling=2)

    # One pointer window and one search window of the 10-K, then it is at its ceiling.
    assert under_the_ceiling == [ten_k[0], ten_k[5], release[0], release[1]]
    # What is left goes on, in turn again: the next pointer window, the next search window.
    assert [each.document for each in with_budget_left].count(0) == 4
    assert {ten_k[1], ten_k[6]} <= set(with_budget_left)
    assert release[2] not in with_budget_left


def test_the_ceiling_stops_one_document_taking_more_than_its_share() -> None:
    long_filing = [searched(0, 20.0 - n, start=n * 10) for n in range(10)]
    others = [searched(d, 5.0 - n, start=n * 10) for d in (1, 2) for n in range(4)]

    dealt = deal([*long_filing, *others], floors=(), budget=9, ceiling=3)

    by_document = [sum(1 for each in dealt if each.document == d) for d in (0, 1, 2)]
    assert by_document == [3, 3, 3]
    # Each document's own best windows, the whole best first.
    assert dealt[:3] == long_filing[:3]


def test_a_share_the_other_documents_cannot_use_passes_on() -> None:
    long_filing = [searched(0, 20.0 - n, start=n * 10) for n in range(10)]
    short = [searched(1, 5.0)]

    dealt = deal([*long_filing, *short], floors=(), budget=6, ceiling=2)

    assert [each.document for each in dealt] == [0, 0, 0, 0, 0, 1]
    assert dealt[:5] == long_filing[:5]


def test_a_periodic_report_or_results_release_with_a_candidate_keeps_one_passage() -> None:
    ten_k = [searched(0, 20.0 - n, start=n * 10) for n in range(6)]
    notes = [searched(1, 10.0 - n, start=n * 10) for n in range(6)]
    ten_q = [searched(2, 0.4)]  # a weak match
    release = [lead(3, 0), lead(3, 1)]  # nothing matched: its lead windows
    silent_report: list[Candidate] = []  # a floor document with no window at all

    dealt = deal([*ten_k, *notes, *ten_q, *release], floors={0, 2, 3, 4}, budget=6, ceiling=2)

    assert silent_report == []
    assert [sum(1 for each in dealt if each.document == d) for d in range(4)] == [2, 2, 1, 1]
    assert ten_q[0] in dealt
    assert release[0] in dealt  # its first lead window


def test_a_budget_smaller_than_the_floors_goes_to_the_best_floor_candidates() -> None:
    offered = [searched(0, 1.0), pointed(1, rank=5), searched(2, 4.0), searched(2, 9.0, start=10)]

    dealt = deal(offered, floors={0, 1, 2}, budget=2, ceiling=1)

    assert dealt == [pointed(1, rank=5), searched(2, 9.0, start=10)]


def test_a_document_with_only_lead_windows_and_no_floor_waits_for_every_other_candidate() -> None:
    ten_k = [searched(0, 20.0 - n, start=n * 10) for n in range(6)]
    administrative = [lead(1, 0), lead(1, 1)]  # an 8-K with Items 5.02 and 9.01

    while_others_have_candidates = deal([*ten_k, *administrative], floors={0}, budget=5, ceiling=2)
    with_budget_to_spare = deal([*ten_k, *administrative], floors={0}, budget=8, ceiling=2)

    assert [each.document for each in while_others_have_candidates] == [0] * 5
    assert [each.document for each in with_budget_to_spare] == [0] * 6 + [1, 1]


def test_lead_only_documents_share_what_is_left_one_window_each_in_turn() -> None:
    first = [lead(0, position) for position in range(3)]
    second = [lead(1, position) for position in range(3)]

    dealt = deal([*first, *second], floors=(), budget=4, ceiling=2)

    assert [(each.document, each.lead) for each in dealt] == [(0, 0), (1, 0), (0, 1), (1, 1)]


def test_select_counts_the_candidates_not_taken_as_dropped_but_not_lead_windows() -> None:
    document = note(*(paragraph(f"Laser product {n}.") for n in range(5)))
    silent = note(paragraph("Officer changes."))

    chosen = select([document, silent], question="laser", budget=2, ceiling=1)

    assert [p.source_version_id for p in chosen.passages] == [document.id, document.id]
    assert chosen.dropped == 3


@pytest.mark.parametrize(
    ("form_type", "document_type", "items", "kept"),
    [
        ("10-K", "10-K", (), True),
        ("10-Q", "10-Q", (), True),
        ("10-K/A", "10-K/A", (), True),
        ("20-F", "20-F", (), True),
        ("6-K", "6-K", (), True),
        ("40-F", "40-F", (), True),
        ("10-K", "EX-21.1", (), False),  # an exhibit of the report is not the report
        ("8-K", "8-K", ("2.02", "9.01"), True),
        ("8-K", "EX-99.1", ("2.02", "9.01"), True),
        ("8-K", "EX-99.2", ("2.02", "9.01"), True),
        ("8-K", "EX-10.1", ("2.02", "9.01"), False),
        ("8-K", "8-K", ("5.02", "9.01"), False),  # officer changes and an exhibit list
        ("8-K", "EX-99.1", ("7.01", "9.01"), False),
        (None, None, (), False),  # a manual import, an exchange announcement
    ],
)
def test_which_documents_keep_a_passage(
    form_type: str | None, document_type: str | None, items: tuple[str, ...], kept: bool
) -> None:
    assert keeps_a_passage(form_type, document_type, items) is kept


@pytest.mark.parametrize(
    ("provider", "document_type", "kept"),
    [
        ("tradingview", "Call transcript", True),  # a results call
        ("tradingview", "call transcript", True),
        ("tradingview", "Event transcript", False),  # a conference
        ("tradingview", None, False),
        ("manual_import", "Call transcript", False),  # only the provider's own typing counts
        (None, "Call transcript", False),
    ],
)
def test_a_results_call_transcript_keeps_a_passage(
    provider: str | None, document_type: str | None, kept: bool
) -> None:
    assert keeps_a_passage(None, document_type, (), provider=provider) is kept


def test_a_call_transcript_with_a_candidate_is_read_and_a_conference_transcript_waits() -> None:
    filing = note(*(paragraph(f"Laser capacity for lasers, part {n}.") for n in range(4)))
    call = Document(
        id=uuid.uuid4(),
        text=paragraph("Our capacity is completely sold out."),
        document_type="Call transcript",
        provider="tradingview",
    )
    conference = Document(
        id=uuid.uuid4(),
        text=paragraph("Capacity came up at the conference."),
        document_type="Event transcript",
        provider="tradingview",
    )

    chosen = select([filing, call, conference], question="laser capacity", budget=2, ceiling=2)

    # The call keeps its one passage beside the filing's better-matching windows; the
    # conference transcript, with as weak a match, gets none.
    assert [p.source_version_id for p in chosen.passages] == [filing.id, call.id]
    assert chosen.dropped == 4


def test_the_ceiling_is_a_share_of_the_budget_and_at_least_one_passage() -> None:
    assert ceiling(24, 1 / 3) == 8
    assert ceiling(24, 0.3333) == 8  # a third as an environment variable would write it
    assert ceiling(72, 0.3333) == 24
    assert ceiling(48, 1 / 3) == 16
    assert ceiling(5, 1 / 3) == 1
    assert ceiling(2, 1 / 3) == 1
    assert ceiling(6, 0.5) == 3
    assert ceiling(24, 1.0) == 24


def test_the_kinds_of_selection_of_a_passage() -> None:
    assert selections(["pointer:0", "pointer:3", "search", f"entity:{NVIDIA}"]) == [
        "pointer",
        "search",
        "entity",
    ]
    assert selections(["lead"]) == ["lead"]
    assert selections([f"entity:{NVIDIA}", "recall"]) == ["entity", "recall"]  # before ticket 05


# --- the shared search code -----------------------------------------------------------------------


def test_overlap_counts_the_terms_a_text_contains_each_once() -> None:
    window = tokens(ALLOCATION)

    assert query_terms(MEMORY) == [
        "demand",
        "lumentum",
        "laser",
        "chip",
        "outpace",
        "supply",
        "forcing",
        "allocation",
        "decision",
    ]
    # "outpaces" is not "outpacing": the stemmer only drops a plural's ending.
    assert overlap(query_terms(MEMORY), window) == 4  # demand, supply, allocation, decision
    assert overlap(["supply", "supply"], window) == 1
    assert overlap([], window) == 0


def test_bm25_scores_each_text_of_the_set_and_names_the_terms_it_contains() -> None:
    scored = bm25(
        ["laser", "germanium"],
        [tokens("We make lasers."), tokens("We lease offices."), tokens("Germanium lasers.")],
    )

    assert [each.terms for each in scored] == [("laser",), (), ("laser", "germanium")]
    assert scored[1].score == 0.0
    assert scored[2].score > scored[0].score > 0
    assert bm25([], [tokens("We make lasers.")])[0].score == 0.0
    assert bm25(["laser"], []) == []
