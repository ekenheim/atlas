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
    select,
    selections,
)
from atlas.research.search import bm25, overlap, query_terms, tokens

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


def test_pointer_windows_come_first_by_rank_then_search_and_entity_by_score_then_leads() -> None:
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
        pointed(2, rank=1, query=3),  # rank 1, a later query's
        pointed(1, rank=4),
        searched(1, 9.0, start=20),
        searched(0, 2.5),
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
        pointed(1, rank=2, start=5),
        searched(0, 3.0, start=10),
        searched(0, 3.0, start=40),
    ]


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
