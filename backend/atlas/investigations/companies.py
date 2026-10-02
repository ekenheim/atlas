"""Which companies a round of an investigation reads: its seeds, and the companies its reading
pointers name (memory-directed reading ticket 06; docs/decisions.md, "Multi-hop
Investigators").

Seeds are where the reading starts, not where it ends. Once a round's Scout has recorded its
reading pointers (atlas.investigations.pointers), the companies they name are **ranked by
weight**: a company's weight is the sum, over the Scout's pointers that name it, of
`1 / rank`, the pointer's rank being its memory's place in its recall's results (1 is best).
So a pointer at the top of a recall weighs 1, one at rank 10 a tenth, and a company that
several queries point to adds its pointers up. Ties go to the company with the better best
rank, then by slug.

Every seed has its Investigator already (the plan as created). The other ranked companies
get one **in rank order while the company budget has room**: `max_companies` Investigators a
round, the seeds counted (`ATLAS_INVESTIGATION_MAX_COMPANIES`, default 6; a request may
lower it). A seed is never dropped: a budget below the number of seeds only adds nobody. A
company whose premise was already disproven gets none and takes no room. Only **researched**
companies are ranked: a counterparty has no archive to read (and no pointer can name it), a
pointer with no company names nobody.

What each ranked company came to (`seed`, `added`, `no_room`, `premise_disproven`) is
recorded once per round, in the Scout task's artifacts and a `companies_ranked` event
(atlas.investigations.service), and shown on the investigation read; the research card lists
the ones not read.

Each Investigator then reads its company's **document floor** first (pilot fix 24): the
latest periodic report and the latest results release, when it has them; then the documents
its pointers name, then its latest ones (`document_floor`, `documents_in_order`).
"""

import uuid
from collections.abc import Collection, Hashable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from typing import Any, Literal

from pydantic import JsonValue
from sqlalchemy import Connection, text

from atlas.claims.selection import is_periodic_report, is_results_release

# What became of a company the round's pointers name.
Outcome = Literal["seed", "added", "no_room", "premise_disproven"]
# The Scout task's artifacts that record a round's ranking (see `artifacts`).
POINTED_COMPANIES = "pointed_companies"
COMPANY_BUDGET = "company_budget"
# An added Investigator task's artifact: the pointers it was added for.
ADDED_FOR_POINTERS = "added_for_pointers"
_SCORE_PLACES = 4


@dataclass(frozen=True)
class PointerWeight:
    """How strongly a round's reading pointers name a company."""

    pointers: int  # how many of the Scout's pointers name it
    score: float  # the sum of 1 / rank over them, to four places (the order uses the exact sum)
    best_rank: int  # the best (lowest) rank among them

    def as_json(self) -> dict[str, JsonValue]:
        return {"pointers": self.pointers, "score": self.score, "best_rank": self.best_rank}


@dataclass(frozen=True)
class RankedCompany:
    company_id: uuid.UUID
    slug: str
    name: str
    weight: PointerWeight


def rank_companies(ranks: Mapping[str, Sequence[int]]) -> list[tuple[str, PointerWeight]]:
    """Companies (by slug, each with the ranks of the pointers that name it) by weight, best
    first; a company with no pointer is left out."""
    weighed = [
        (slug, sum((Fraction(1, rank) for rank in each), Fraction(0)), min(each), len(each))
        for slug, each in ranks.items()
        if each
    ]
    weighed.sort(key=lambda item: (-item[1], item[2], item[0]))
    return [
        (slug, PointerWeight(count, round(float(score), _SCORE_PLACES), best))
        for slug, score, best, count in weighed
    ]


def allot[K: Hashable](
    ranked: Sequence[K], *, reading: Collection[K], disproven: Collection[K], max_companies: int
) -> dict[K, Outcome]:
    """What becomes of each ranked company (best first): one of the `reading` companies (the
    seeds, which have their Investigator whatever the budget) is a `seed`; another gets an
    Investigator (`added`) while fewer than `max_companies` companies are read, unless its
    premise is `disproven`; the rest have `no_room`."""
    room = max_companies - len(reading)
    outcomes: dict[K, Outcome] = {}
    for company in ranked:
        if company in reading:
            outcomes[company] = "seed"
        elif company in disproven:
            outcomes[company] = "premise_disproven"
        elif room > 0:
            outcomes[company] = "added"
            room -= 1
        else:
            outcomes[company] = "no_room"
    return outcomes


def pointed_companies(
    connection: Connection, investigation_id: uuid.UUID, round_: int
) -> list[RankedCompany]:
    """The researched companies the round's Scout pointers name, by weight, best first."""
    rows = connection.execute(
        text(
            "SELECT c.id, c.slug, c.display_name, p.rank FROM reading_pointer p"
            " JOIN investigation_task t ON t.id = p.task_id AND t.role = 'scout'"
            # A counterparty is never researched: no Investigator, whatever points to it.
            " JOIN company c ON c.id = p.company_id AND c.role = 'researched'"
            " WHERE p.investigation_id = :id AND p.round = :round"
        ),
        {"id": investigation_id, "round": round_},
    ).all()
    ranks: dict[str, list[int]] = {}
    companies: dict[str, tuple[uuid.UUID, str]] = {}
    for row in rows:
        ranks.setdefault(row.slug, []).append(row.rank)
        companies[row.slug] = (row.id, row.display_name)
    return [
        RankedCompany(companies[slug][0], slug, companies[slug][1], weight)
        for slug, weight in rank_companies(ranks)
    ]


def entry(company: RankedCompany, outcome: Outcome, task_key: str | None) -> dict[str, JsonValue]:
    """A ranked company as the Scout task's artifacts, the `companies_ranked` event and the
    investigation read carry it."""
    return {
        "company_id": str(company.company_id),
        "company_name": company.name,
        "slug": company.slug,
        **company.weight.as_json(),
        "outcome": outcome,
        "task_key": task_key,
    }


def not_read_reason(recorded: Mapping[str, Any], company_budget: int) -> str | None:
    """Why a ranked company (its recorded `entry`) got no Investigator, in words; None when
    it has one."""
    if recorded["outcome"] == "no_room":
        return f"the company budget ({company_budget} Investigators a round) had no room"
    if recorded["outcome"] == "premise_disproven":
        return "its premise was disproven"
    return None


# --- Which of a company's documents its Investigator reads (pilot fix 24) ----------------------


@dataclass(frozen=True)
class FloorCandidate:
    """One of a company's Source Documents, by the version of it an Investigator would read,
    as the document floor sees it."""

    version_id: uuid.UUID
    available_at: datetime
    form_type: str | None
    document_type: str | None
    items: tuple[str, ...] = ()  # its filing's 8-K Items


# Among one results 8-K's documents, the press release is read first (then its second
# exhibit, then the 8-K's own document).
_RELEASE_PREFERENCE = {"EX-99.1": 2, "EX-99.2": 1}


def document_floor(documents: Sequence[FloorCandidate]) -> list[uuid.UUID]:
    """An Investigator's document floor: its company's latest periodic report, then its
    latest results release (each when it has one), by the passage floor's notion of both
    (atlas.claims.selection: `is_periodic_report`, `is_results_release`). Memory points at
    what it holds most of (transcripts), so without the floor a company's filings can go
    unread."""
    periodic = [d for d in documents if is_periodic_report(d.form_type, d.document_type)]
    releases = [d for d in documents if is_results_release(d.form_type, d.document_type, d.items)]
    floor: list[uuid.UUID] = []
    if periodic:
        floor.append(max(periodic, key=lambda d: (d.available_at, str(d.version_id))).version_id)
    if releases:
        latest = max(
            releases,
            key=lambda d: (
                d.available_at,
                _RELEASE_PREFERENCE.get((d.document_type or "").upper(), 0),
                str(d.version_id),
            ),
        )
        floor.append(latest.version_id)
    return floor


def documents_in_order[K: Hashable](
    floor: Sequence[K], pointed: Sequence[K], latest: Sequence[K], room: int
) -> list[K]:
    """The documents an Investigator reads, at most `room`: the floor, then the pointed ones
    (best pointer first), then its latest ones (newest first), each once. When the room is
    smaller than the floor plus one pointed document, the floor's first (the periodic
    report) and the best-pointed document come first."""
    if pointed and room < len(floor) + 1:
        order = [*floor[:1], *pointed[:1], *floor[1:], *pointed[1:], *latest]
    else:
        order = [*floor, *pointed, *latest]
    return list(dict.fromkeys(order))[: max(room, 0)]
