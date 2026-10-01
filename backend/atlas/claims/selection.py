"""Passage selection: which windows of its documents an extraction reads (memory-directed
reading ticket 05; docs/decisions.md, "Passage selection: pointers and search, best first").

Each document's parsed text is split into sections by the retention sectioner (so a section
here is a memory document's section there) and each section into **windows** of at most
`PASSAGE_CHARS` characters, cut at line breaks. A window becomes a **candidate** when a
selection chooses it; a window several selections choose is one candidate (and one passage)
recording all of them in `selected_by`:

1. **`pointer:<query_index>`.** For each reading pointer into the document (Memory used as an
   index: atlas.investigations.pointers), the window of the pointed section that shares most
   terms with the pointer's Memory text (`atlas.research.search.overlap`; the earliest window
   on a tie, also when none shares a term). The section is found by its anchor, in the parse
   the extraction reads; a pointer whose anchor that parse doesn't have chooses among all of
   the document's windows. The Memory text only finds the window: it is never sent on.
2. **`search`.** Every window that contains a term of the extraction's question or of the
   round's Scout queries (`Reading.queries`), scored by Okapi BM25 over all windows of the
   extraction's documents (the terms of the question and the queries together, each once).
3. **`entity:<company_id>`.** A window that names a known company other than the document's
   own, as before. Its score is its search score (0 when it matches no term).
4. **`lead`.** Only for a document none of whose windows is chosen by the above: its windows
   in lead order (its results sections first: a 10-Q's or 10-K's MD&A, an 8-K's Items 2.02,
   7.01 and 8.01; then the rest in text order; the cover only when there is nothing else).

**Best first** is one order over all the documents' candidates: pointer windows by their best
pointer's rank in its recall (then the lower query index, the earlier document, the earlier
window); then search and entity windows by score (then the earlier document and window); then
lead windows by their position in their document's lead order (then the earlier document).

**Dealing** `budget` passages (`deal`):

1. **The floor.** Each periodic report (the primary document of a 10-K, 10-Q, 20-F, 6-K or
   40-F) and each results release (an 8-K listing Item 2.02: its primary document and its
   EX-99.1 and EX-99.2) that has a candidate gets its best one (`keeps_a_passage`).
2. **Under the ceiling.** The pointer, search and entity candidates, best first; a document
   that already has `ceiling` passages is passed over (`ceiling`: a share of the budget, at
   least one passage).
3. **The budget is not stranded.** If passages are left (every document is at its ceiling or
   out of such candidates), the candidates passed over are taken, best first.
4. **Lead windows** last, the same way: under the ceiling, then the rest. So a document with
   nothing but lead windows, and no floor, is read only when no other document has a pointer,
   search or entity candidate unread.

The passages are returned best first (the order above), so a run whose token budget ends
part-way has sent the best ones. Not taken pointer, search and entity candidates are counted
as dropped.
"""

import uuid
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field

from atlas.claims.predicates import mentions
from atlas.research.search import bm25, overlap, query_terms, tokens
from atlas.retention.sections import Section, split_sections

PASSAGE_CHARS = 3000
# `selected_by` values: `pointer:<query_index>`, `search`, `entity:<company_id>`, `lead`.
POINTER = "pointer"
SEARCH = "search"
ENTITY = "entity"
LEAD = "lead"
SELECTIONS = (POINTER, SEARCH, ENTITY, LEAD)
# A periodic report's primary document keeps one passage; so does a results release.
PERIODIC_FORMS = frozenset({"10-K", "10-Q", "20-F", "6-K", "40-F"})
RESULTS_ITEM = "2.02"  # an 8-K's "Results of Operations and Financial Condition"
RESULTS_EXHIBITS = frozenset({"EX-99.1", "EX-99.2"})
# The sections read first among a document's lead windows, by form: the results sections.
_LEAD_FIRST: dict[str, tuple[str, ...]] = {
    "10-Q": ("part-i-item-2",),  # Management's Discussion and Analysis
    "10-K": ("part-ii-item-7",),  # Management's Discussion and Analysis
    "8-K": ("item-2-02", "item-7-01", "item-8-01"),  # results; Regulation FD; other events
}


@dataclass(frozen=True)
class Pointer:
    """A reading pointer as selection uses it: where Memory pointed, and how well."""

    source_version_id: uuid.UUID
    section_anchor: str
    rank: int  # the memory's rank in its recall's results (1 is best)
    query_index: int  # 0: the round's question; else the Scout query's position
    memory_text: str  # finds the window; never quoted and never sent to a role


@dataclass(frozen=True)
class Reading:
    """What directs an extraction's reading besides its own question: the reading pointers
    into its documents and the Scout's queries of the round. Empty outside an investigation."""

    pointers: Sequence[Pointer] = ()
    queries: Sequence[str] = ()


@dataclass(frozen=True)
class Document:
    """A Source Version as selection reads it: its parsed text and what kind of document it
    is. `items` are its filing's 8-K Items ("2.02", "9.01"); `company_id` is its own company,
    which never tags a window."""

    id: uuid.UUID
    text: str
    form_type: str | None = None
    document_type: str | None = None
    items: Sequence[str] = ()
    company_id: uuid.UUID | None = None

    @property
    def primary(self) -> bool:
        return self.document_type is not None and self.document_type == self.form_type


@dataclass(frozen=True)
class Candidate:
    """A window a selection chose. `document` is its document's position in the extraction's
    order; `pointer` its best pointer's (rank, query index); `lead` its position among its
    document's lead windows (a lead window has neither pointer nor score)."""

    document: int
    section_anchor: str
    start: int
    end: int
    selected_by: tuple[str, ...]
    pointer: tuple[int, int] | None = None
    score: float = 0.0
    lead: int | None = None


@dataclass(frozen=True)
class Selected:
    """A passage to send: a window of a Source Version's parsed text and why it was chosen."""

    source_version_id: uuid.UUID
    section_anchor: str
    char_start: int
    char_end: int
    selected_by: list[str]


@dataclass(frozen=True)
class Selection:
    passages: list[Selected] = field(default_factory=list[Selected])
    dropped: int = 0  # pointer, search and entity candidates not taken


def select(
    documents: Sequence[Document],
    *,
    entities: Sequence[tuple[uuid.UUID, Sequence[str]]] = (),
    question: str | None = None,
    reading: Reading | None = None,
    budget: int,
    ceiling: int,
) -> Selection:
    """The passages to read of `documents` (in the extraction's order; an investigation's are
    newest first): their candidates dealt best first within `budget`, at most `ceiling` of one
    document while others have candidates (module docstring). `entities` are the known
    companies, (ID, names) each."""
    found = candidates(documents, entities=entities, question=question, reading=reading)
    floors = {
        index
        for index, document in enumerate(documents)
        if keeps_a_passage(document.form_type, document.document_type, document.items)
    }
    dealt = deal(found, floors=floors, budget=budget, ceiling=ceiling)
    offered = sum(1 for each in found if each.lead is None)
    taken = sum(1 for each in dealt if each.lead is None)
    return Selection(
        passages=[
            Selected(
                source_version_id=documents[each.document].id,
                section_anchor=each.section_anchor,
                char_start=each.start,
                char_end=each.end,
                selected_by=list(each.selected_by),
            )
            for each in dealt
        ],
        dropped=offered - taken,
    )


def ceiling(budget: int, share: float) -> int:
    """The most passages one document may take of `budget` while others have candidates:
    `share` of it, rounded down, at least one. A hundredth of a passage is forgiven, so a
    share written 0.3333 is a third (8 of 24, not 7)."""
    return max(1, int(budget * share + 0.01))


def keeps_a_passage(
    form_type: str | None, document_type: str | None, items: Sequence[str] = ()
) -> bool:
    """Whether a document has the floor of one passage: a periodic report's primary document,
    or a results release (an 8-K listing Item 2.02: the 8-K itself, its EX-99.1 and EX-99.2)."""
    form = (form_type or "").upper().removesuffix("/A")
    kind = (document_type or "").upper()
    primary = bool(kind) and kind.removesuffix("/A") == form
    if form in PERIODIC_FORMS:
        return primary
    if form == "8-K" and RESULTS_ITEM in items:
        return primary or kind in RESULTS_EXHIBITS
    return False


def candidates(
    documents: Sequence[Document],
    *,
    entities: Sequence[tuple[uuid.UUID, Sequence[str]]] = (),
    question: str | None = None,
    reading: Reading | None = None,
) -> list[Candidate]:
    """Every candidate window of the documents, each once with all its selections (module
    docstring), in document then text order (a lead-only document's in lead order)."""
    reading = reading or Reading()
    terms = query_terms("\n".join([question or "", *reading.queries]))
    # Every window with text, per document, and its words (for the search and the pointers).
    sections: list[list[Section]] = []
    windows: list[list[tuple[str, int, int]]] = []
    for document in documents:
        split = split_sections(document.text, form=document.form_type, primary=document.primary)
        sections.append(split)
        windows.append(
            [
                (section.anchor, start, end)
                for section in split
                for start, end in cut_windows(document.text, section.start, section.end)
                if document.text[start:end].strip()
            ]
        )
    tokenized = [
        [tokens(document.text[start:end]) for _, start, end in each]
        for document, each in zip(documents, windows, strict=True)
    ]
    words = [[frozenset(window) for window in each] for each in tokenized]
    scores = iter(bm25(terms, [window for each in tokenized for window in each]))
    positions = {document.id: index for index, document in enumerate(documents)}

    # The window each pointer chooses: (document, window) -> its pointers' (rank, query index).
    pointed: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for pointer in reading.pointers:
        index = positions.get(pointer.source_version_id)
        if index is None or not windows[index]:
            continue
        within = [
            at
            for at, (anchor, _, _) in enumerate(windows[index])
            if anchor == pointer.section_anchor
        ] or list(range(len(windows[index])))
        best = _best_window(query_terms(pointer.memory_text), words[index], within)
        pointed.setdefault((index, best), []).append((pointer.rank, pointer.query_index))

    found: list[Candidate] = []
    for index, document in enumerate(documents):
        others = [(each, names) for each, names in entities if each != document.company_id]
        chosen: list[Candidate] = []
        for at, (anchor, start, end) in enumerate(windows[index]):
            score = next(scores).score
            pointers = pointed.get((index, at), [])
            window = document.text[start:end]
            selected_by = [
                *(f"{POINTER}:{query}" for query in sorted({query for _, query in pointers})),
                *([SEARCH] if score > 0 else []),
                *(f"{ENTITY}:{each}" for each, names in others if mentions(window, names)),
            ]
            if selected_by:
                chosen.append(
                    Candidate(
                        document=index,
                        section_anchor=anchor,
                        start=start,
                        end=end,
                        selected_by=tuple(selected_by),
                        pointer=min(pointers) if pointers else None,
                        score=score,
                    )
                )
        found.extend(chosen or _lead(index, document, sections[index]))
    return found


def deal(
    candidates: Sequence[Candidate], *, floors: Collection[int], budget: int, ceiling: int
) -> list[Candidate]:
    """At most `budget` of the candidates, best first (module docstring: dealing). `floors`
    are the documents (by position) that keep one passage when they have a candidate."""
    ordered = sorted(candidates, key=_order)
    chosen: set[int] = set()
    per_document: Counter[int] = Counter()

    def take(index: int) -> None:
        chosen.add(index)
        per_document[ordered[index].document] += 1

    for index, each in enumerate(ordered):
        if len(chosen) >= budget:
            break
        if each.document in floors and per_document[each.document] == 0:
            take(index)
    for leads in (False, True):
        for limit in (ceiling, None):
            for index, each in enumerate(ordered):
                if len(chosen) >= budget:
                    break
                if index in chosen or (each.lead is not None) != leads:
                    continue
                if limit is not None and per_document[each.document] >= limit:
                    continue
                take(index)
    return [ordered[index] for index in sorted(chosen)]


def selections(selected_by: Sequence[str]) -> list[str]:
    """The kinds of selection in a passage's `selected_by`, each once, in `SELECTIONS` order
    (then any other, such as the `recall` of extractions made before ticket 05)."""
    kinds = dict.fromkeys(tag.split(":", 1)[0] for tag in selected_by)
    return [kind for kind in SELECTIONS if kind in kinds] + [
        kind for kind in kinds if kind not in SELECTIONS
    ]


def cut_windows(parsed: str, start: int, end: int) -> list[tuple[int, int]]:
    """[start, end) cut into windows of at most PASSAGE_CHARS, each ending at a line break
    when it has one past its first half."""
    windows: list[tuple[int, int]] = []
    position = start
    while position < end:
        limit = min(position + PASSAGE_CHARS, end)
        if limit < end:
            cut = parsed.rfind("\n", position + PASSAGE_CHARS // 2, limit)
            if cut >= 0:
                limit = cut + 1
        windows.append((position, limit))
        position = limit
    return windows


def _best_window(
    memory: Sequence[str], words: Sequence[frozenset[str]], within: Sequence[int]
) -> int:
    """Of the windows `within` (positions in `words`), the one sharing most of the Memory
    text's terms; the earliest on a tie."""
    return max(within, key=lambda at: (overlap(memory, words[at]), -at))


def _order(candidate: Candidate) -> tuple[int, float, int, int, int]:
    """Best first: pointer windows by rank, then search and entity windows by score, then
    lead windows by their place in their document's lead order."""
    if candidate.pointer is not None:
        rank, query = candidate.pointer
        return (0, rank, query, candidate.document, candidate.start)
    if candidate.lead is None:
        return (1, -candidate.score, 0, candidate.document, candidate.start)
    return (2, candidate.lead, 0, candidate.document, candidate.start)


def _lead(index: int, document: Document, sections: Sequence[Section]) -> list[Candidate]:
    """A document's lead windows, for one with no pointer, search or entity window (a press
    release naming no other known company and none of the question's terms, say): its results
    sections first, then the rest in text order; the cover only when there is nothing else."""
    first = _LEAD_FIRST.get((document.form_type or "").upper().removesuffix("/A"), ())
    ordered = sorted(
        (section for section in sections if section.anchor != "cover"),
        key=lambda section: section.anchor not in first,  # stable: text order otherwise
    ) or list(sections)
    spans = [
        (section.anchor, start, end)
        for section in ordered
        for start, end in cut_windows(document.text, section.start, section.end)
        if document.text[start:end].strip()
    ]
    return [
        Candidate(
            document=index,
            section_anchor=anchor,
            start=start,
            end=end,
            selected_by=(LEAD,),
            lead=position,
        )
        for position, (anchor, start, end) in enumerate(spans)
    ]
