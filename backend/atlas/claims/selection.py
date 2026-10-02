"""Passage selection: which windows of its documents an extraction reads (memory-directed
reading ticket 05; docs/decisions.md, "Passage selection: pointers and search, alternately").

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
   the document's windows. The Memory text only finds the window: it is never sent on. A
   pointer with a `label` is recorded as `pointer:<label>` instead: the Skeptic's pointers
   carry their bear-checklist item (`pointer:customer_concentration`;
   atlas.investigations.skeptic), so its tags never read as a Scout query's number.
2. **`search`.** Every window that contains a term of the extraction's question or of the
   round's Scout queries (`Reading.queries`), scored by Okapi BM25 over all windows of the
   extraction's documents (the terms of the question and the queries together, each once).
3. **`entity:<company_id>`.** A window that names a known company other than the document's
   own, as before. Its score is its search score (0 when it matches no term).
3a. **`entity_pointer:<company_id>`** (memory-quality ticket 09; docs/decisions.md, "The entity
   hop"). For each **entity pointer** into the document (a fact carrying another company's
   entity, from this document; atlas.investigations.entity_hop), the window of the pointed
   section that shares most terms with the fact's text, chosen as a reading pointer's is.
   The tag names the company the hop was made for (the company the window is about), not the
   document's own. It is its own channel, not the recall pointers' and not the search's.
4. **`lead`.** Only for a document none of whose windows is chosen by the above: its windows
   in lead order (its results sections first: a 10-Q's or 10-K's MD&A, an 8-K's Items 2.02,
   7.01 and 8.01; then the rest in text order; the cover only when there is nothing else).

**Two channels, each with its own order.** Recall and the term search are independent ways
to a window: Memory finds retained facts however they are worded; the search covers every
archived document, retained or not, by its exact words. So neither is ranked above the other:

- the **pointer** candidates, by their best pointer's rank in its recall (then the lower
  query index, the earlier document, the earlier window);
- the **search and entity** candidates, by score (then the earlier document and window). A
  pointer window that also matches the search or names a company is in both lists, and is
  still one passage.
- the **entity pointer** candidates (ticket 09), by their best entity pointer's rank (then the
  company's place in the hop, the earlier document, the earlier window): a third list.

Lead windows follow both, by their position in their document's lead order (then the earlier
document).

**Dealing** `budget` passages (`deal`):

1. **The floor.** Each periodic report (the primary document of a 10-K, 10-Q, 20-F, 6-K or
   40-F), each results release (an 8-K listing Item 2.02: its primary document and its
   EX-99.1 and EX-99.2) and each results-call transcript (provider `tradingview`, document
   type "Call transcript"; not a conference's "Event transcript") that has a candidate gets
   its best one: a pointer window, else its best search or entity window, else a lead window
   (`keeps_a_passage`).
2. **Alternately, under the ceiling.** One pointer candidate, then one search or entity
   candidate, and so on, each list in its own order; a window already taken, or of a document
   that already has `ceiling` passages, is passed over (`ceiling`: a share of the budget, at
   least one passage). When one list runs out, the other goes on. So with more pointer
   windows than the budget, about half of it still goes to the search's best windows, and a
   document Memory doesn't hold yet (an unretained transcript) is read.
3. **The budget is not stranded.** If passages are left (every document is at its ceiling or
   out of such candidates), the candidates passed over are taken, alternately again.
3a. **The entity pointer channel** (ticket 09) takes its turn after each recall pointer's
   (pointer, entity pointer, search, and so on), but under the ceiling it takes at most
   `ceiling` passages in all, so it never takes more than one document may: the recall
   pointers keep at least as many turns as it has. Passed-over entity pointer windows are
   taken in step 3 like the others.
4. **Lead windows** last: under the ceiling, then the rest. So a document with nothing but
   lead windows, and no floor, is read only when no other document has a pointer, search or
   entity candidate unread.

The passages are returned in reading order: the pointer windows taken, the entity pointer
windows taken and the other search and entity windows taken, in turn, each in its order;
then the lead windows. So a run
whose token budget ends part-way has sent the best of both channels. Not taken pointer,
search and entity candidates are counted as dropped.
"""

import uuid
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from itertools import zip_longest

from atlas.claims.predicates import mentions
from atlas.research.search import bm25, overlap, query_terms, tokens
from atlas.retention.sections import Section, split_sections

PASSAGE_CHARS = 3000
# `selected_by` values: `pointer:<query_index>` (or `pointer:<label>`),
# `entity_pointer:<company_id>`, `search`, `entity:<company_id>`, `lead`.
POINTER = "pointer"
ENTITY_POINTER = "entity_pointer"
SEARCH = "search"
ENTITY = "entity"
LEAD = "lead"
SELECTIONS = (POINTER, ENTITY_POINTER, SEARCH, ENTITY, LEAD)
# A periodic report's primary document keeps one passage; so does a results release.
PERIODIC_FORMS = frozenset({"10-K", "10-Q", "20-F", "6-K", "40-F"})
RESULTS_ITEM = "2.02"  # an 8-K's "Results of Operations and Financial Condition"
RESULTS_EXHIBITS = frozenset({"EX-99.1", "EX-99.2"})
# A results call's transcript keeps one passage too: the TradingView source's documents
# (atlas.tradingview: `source_document.provider`) of this type (`document_type`, the catalog's
# category title, compared without case). A conference's "Event transcript" has no floor.
TRANSCRIPT_PROVIDER = "tradingview"
RESULTS_CALL_TYPES = frozenset({"call transcript"})
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
    query_index: int  # 0: the round's question; else the asking task's query's position
    memory_text: str  # finds the window; never quoted and never sent to a role
    # What `selected_by` calls the pointer's query instead of its index (None: the index, a
    # Scout's; the Skeptic's pointers are labelled with their bear-checklist item; an entity
    # pointer with the company the hop was made for).
    label: str | None = None
    # An entity pointer (memory-quality ticket 09): its own channel, tagged
    # `entity_pointer:<label>`.
    entity: bool = False


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
    which never tags a window; `provider` is its Source Document's (`tradingview` for a
    transcript)."""

    id: uuid.UUID
    text: str
    form_type: str | None = None
    document_type: str | None = None
    items: Sequence[str] = ()
    company_id: uuid.UUID | None = None
    provider: str | None = None

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
    # Its best entity pointer's (rank, query index): the entity pointer channel (ticket 09).
    entity_pointer: tuple[int, int] | None = None

    @property
    def searched(self) -> bool:
        """Whether the search or an entity tag chose it (a pointer may have too)."""
        return any(tag == SEARCH or tag.startswith(f"{ENTITY}:") for tag in self.selected_by)


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
    newest first): their candidates dealt within `budget`, pointer windows and search windows
    alternately, at most `ceiling` of one document while others have candidates (module
    docstring). `entities` are the known companies, (ID, names) each."""
    found = candidates(documents, entities=entities, question=question, reading=reading)
    floors = {
        index
        for index, document in enumerate(documents)
        if keeps_a_passage(
            document.form_type, document.document_type, document.items, provider=document.provider
        )
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
    form_type: str | None,
    document_type: str | None,
    items: Sequence[str] = (),
    *,
    provider: str | None = None,
) -> bool:
    """Whether a document has the floor of one passage: a periodic report's primary document,
    a results release (an 8-K listing Item 2.02: the 8-K itself, its EX-99.1 and EX-99.2), or
    a results call's transcript (the `tradingview` provider's "Call transcript")."""
    if provider == TRANSCRIPT_PROVIDER:
        return (document_type or "").strip().lower() in RESULTS_CALL_TYPES
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

    # The window each pointer chooses: (document, window) -> its pointers' (rank, query
    # index, tag); the recall pointers' and the entity pointers' apart.
    pointed: dict[tuple[int, int], list[tuple[int, int, str]]] = {}
    hopped: dict[tuple[int, int], list[tuple[int, int, str]]] = {}
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
        tag = pointer.label if pointer.label is not None else str(pointer.query_index)
        kind, into = (ENTITY_POINTER, hopped) if pointer.entity else (POINTER, pointed)
        into.setdefault((index, best), []).append(
            (pointer.rank, pointer.query_index, f"{kind}:{tag}")
        )

    found: list[Candidate] = []
    for index, document in enumerate(documents):
        others = [(each, names) for each, names in entities if each != document.company_id]
        chosen: list[Candidate] = []
        for at, (anchor, start, end) in enumerate(windows[index]):
            score = next(scores).score
            pointers = pointed.get((index, at), [])
            hops = hopped.get((index, at), [])
            window = document.text[start:end]
            selected_by = [
                # Each pointer's tag once, in query order.
                *dict.fromkeys(tag for _, _, tag in sorted(pointers, key=lambda p: p[1])),
                *dict.fromkeys(tag for _, _, tag in sorted(hops, key=lambda p: p[1])),
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
                        pointer=min((rank, query) for rank, query, _ in pointers)
                        if pointers
                        else None,
                        score=score,
                        entity_pointer=min((rank, query) for rank, query, _ in hops)
                        if hops
                        else None,
                    )
                )
        found.extend(chosen or _lead(index, document, sections[index]))
    return found


def deal(
    candidates: Sequence[Candidate], *, floors: Collection[int], budget: int, ceiling: int
) -> list[Candidate]:
    """At most `budget` of the candidates, in reading order (module docstring: dealing).
    `floors` are the documents (by position) that keep one passage when they have a
    candidate."""
    offered = list(candidates)
    # The two channels, each in its own order (a window both chose is in both), and the leads.
    pointers = sorted(
        (at for at, each in enumerate(offered) if each.pointer is not None),
        key=lambda at: _pointer_order(offered[at]),
    )
    hops = sorted(
        (at for at, each in enumerate(offered) if each.entity_pointer is not None),
        key=lambda at: _entity_pointer_order(offered[at]),
    )
    searches = sorted(
        (at for at, each in enumerate(offered) if each.lead is None and each.searched),
        key=lambda at: _search_order(offered[at]),
    )
    leads = sorted(
        (at for at, each in enumerate(offered) if each.lead is not None),
        key=lambda at: _lead_order(offered[at]),
    )
    chosen: set[int] = set()
    per_document: Counter[int] = Counter()
    hops_taken = 0

    def take(at: int) -> None:
        chosen.add(at)
        per_document[offered[at].document] += 1

    def free(at: int, limit: int | None) -> bool:
        """Not taken yet, and its document under `limit` passages (None: no limit)."""
        return at not in chosen and (limit is None or per_document[offered[at].document] < limit)

    # 1. The floor: a pointer window, else an entity pointer's, else the best search or entity
    # window, else a lead one.
    for at in (*pointers, *hops, *searches, *leads):
        if len(chosen) >= budget:
            break
        if offered[at].document in floors and per_document[offered[at].document] == 0:
            take(at)
    # 2 and 3. Pointer, entity pointer and search windows in turn: under the ceiling (where the
    # entity pointer channel takes at most `ceiling` in all), then what was passed over.
    channels = (pointers, hops, searches)
    for limit in (ceiling, None):
        turn = 0
        while len(chosen) < budget:
            for channel in (turn, (turn + 1) % 3, (turn + 2) % 3):
                if channel == 1 and limit is not None and hops_taken >= ceiling:
                    continue
                found = next((at for at in channels[channel] if free(at, limit)), None)
                if found is not None:
                    take(found)
                    hops_taken += channel == 1
                    turn = (channel + 1) % 3
                    break
            else:
                break  # no channel has a candidate left under this limit
    # 4. Lead windows last.
    for limit in (ceiling, None):
        for at in leads:
            if len(chosen) >= budget:
                break
            if free(at, limit):
                take(at)
    return _reading_order([offered[at] for at in chosen])


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


def _pointer_order(candidate: Candidate) -> tuple[int, int, int, int]:
    """Pointer windows: the best rank first, then the lower query index (the question's
    before a Scout query's), the earlier document, the earlier window."""
    rank, query = candidate.pointer or (0, 0)
    return (rank, query, candidate.document, candidate.start)


def _entity_pointer_order(candidate: Candidate) -> tuple[int, int, int, int]:
    """Entity pointer windows: the best rank first, then the company's place in the hop, the
    earlier document, the earlier window."""
    rank, query = candidate.entity_pointer or (0, 0)
    return (rank, query, candidate.document, candidate.start)


def _search_order(candidate: Candidate) -> tuple[float, int, int]:
    """Search and entity windows: the highest score first, then the earlier document, the
    earlier window."""
    return (-candidate.score, candidate.document, candidate.start)


def _lead_order(candidate: Candidate) -> tuple[int, int, int]:
    """Lead windows: by their place in their document's lead order, the documents in turn."""
    return (candidate.lead or 0, candidate.document, candidate.start)


def _reading_order(taken: Sequence[Candidate]) -> list[Candidate]:
    """The passages as sent: the pointer windows, the entity pointer windows and the other
    search and entity windows in turn, each in its own order, then the lead windows."""
    pointed = sorted((each for each in taken if each.pointer is not None), key=_pointer_order)
    hopped = sorted(
        (each for each in taken if each.pointer is None and each.entity_pointer is not None),
        key=_entity_pointer_order,
    )
    others = sorted(
        (
            each
            for each in taken
            if each.pointer is None and each.entity_pointer is None and each.lead is None
        ),
        key=_search_order,
    )
    leads = sorted((each for each in taken if each.lead is not None), key=_lead_order)
    mixed = [
        each for turn in zip_longest(pointed, hopped, others) for each in turn if each is not None
    ]
    return [*mixed, *leads]


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
