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

**Entity pointers** (memory-quality ticket 09; atlas.investigations.entity_hop) join the same
ranking with their own weight: an entity pointer at rank r among the hop's pointers for one
company weighs `entity_weight / r` (`ATLAS_ENTITY_HOP_POINTER_WEIGHT`, default 0.5: half of a
recall pointer's best weight), and names the company whose document it is. `pointers` and
`best_rank` stay the recall pointers' (`best_rank` None for a company only the hop reached);
`entity_pointers` counts the others; `score` is the sum of both.

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
"""

import uuid
from collections.abc import Collection, Hashable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal

from pydantic import JsonValue
from sqlalchemy import Connection, text

# What became of a company the round's pointers name.
Outcome = Literal["seed", "added", "no_room", "premise_disproven"]
# The Scout task's artifacts that record a round's ranking (see `artifacts`).
POINTED_COMPANIES = "pointed_companies"
COMPANY_BUDGET = "company_budget"
# An added Investigator task's artifact: the pointers it was added for.
ADDED_FOR_POINTERS = "added_for_pointers"
# A reading pointer the entity hop made (`reading_pointer.query_kind`).
ENTITY_POINTER_KIND = "entity"
# What an entity pointer weighs against a recall pointer's best (1), unless the setting says.
DEFAULT_ENTITY_WEIGHT = 0.5
_SCORE_PLACES = 4


@dataclass(frozen=True)
class PointerWeight:
    """How strongly a round's reading pointers name a company."""

    pointers: int  # how many of the Scout's recall pointers name it
    score: float  # the sum of their weights, to four places (the order uses the exact sum)
    best_rank: int | None  # the best (lowest) rank among its recall pointers; None: none
    entity_pointers: int = 0  # how many of the round's entity pointers name it

    def as_json(self) -> dict[str, JsonValue]:
        return {
            "pointers": self.pointers,
            "entity_pointers": self.entity_pointers,
            "score": self.score,
            "best_rank": self.best_rank,
        }


@dataclass(frozen=True)
class RankedCompany:
    company_id: uuid.UUID
    slug: str
    name: str
    weight: PointerWeight


def rank_companies(
    ranks: Mapping[str, Sequence[int]],
    entity_ranks: Mapping[str, Sequence[int]] | None = None,
    *,
    entity_weight: float = DEFAULT_ENTITY_WEIGHT,
) -> list[tuple[str, PointerWeight]]:
    """Companies (by slug, each with the ranks of the recall pointers that name it, and of the
    entity pointers in `entity_ranks`) by weight, best first; a company with no pointer is
    left out. A recall pointer weighs 1 / rank, an entity pointer `entity_weight` / rank."""
    hops = entity_ranks or {}
    weight = Fraction(str(entity_weight))
    weighed: list[tuple[str, Fraction, int | None, int, int]] = []
    for slug in dict.fromkeys([*ranks, *hops]):
        recalled, hopped = ranks.get(slug, ()), hops.get(slug, ())
        if not recalled and not hopped:
            continue
        score = sum((Fraction(1, rank) for rank in recalled), Fraction(0)) + sum(
            (weight / rank for rank in hopped), Fraction(0)
        )
        best = min(recalled) if recalled else None
        weighed.append((slug, score, best, len(recalled), len(hopped)))
    # Ties: the better best recall rank (a company only the hop reached after any), then slug.
    weighed.sort(key=lambda item: (-item[1], item[2] is None, item[2] or 0, item[0]))
    return [
        (slug, PointerWeight(count, round(float(score), _SCORE_PLACES), best, entities))
        for slug, score, best, count, entities in weighed
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
    connection: Connection,
    investigation_id: uuid.UUID,
    round_: int,
    *,
    entity_weight: float = DEFAULT_ENTITY_WEIGHT,
) -> list[RankedCompany]:
    """The researched companies the round's Scout pointers name (its recall pointers and its
    entity pointers), by weight, best first."""
    rows = connection.execute(
        text(
            "SELECT c.id, c.slug, c.display_name, p.rank, p.query_kind FROM reading_pointer p"
            " JOIN investigation_task t ON t.id = p.task_id AND t.role = 'scout'"
            # A counterparty is never researched: no Investigator, whatever points to it.
            " JOIN company c ON c.id = p.company_id AND c.role = 'researched'"
            " WHERE p.investigation_id = :id AND p.round = :round"
        ),
        {"id": investigation_id, "round": round_},
    ).all()
    ranks: dict[str, list[int]] = {}
    entity_ranks: dict[str, list[int]] = {}
    companies: dict[str, tuple[uuid.UUID, str]] = {}
    for row in rows:
        chosen = entity_ranks if row.query_kind == ENTITY_POINTER_KIND else ranks
        chosen.setdefault(row.slug, []).append(row.rank)
        companies[row.slug] = (row.id, row.display_name)
    return [
        RankedCompany(companies[slug][0], slug, companies[slug][1], weight)
        for slug, weight in rank_companies(ranks, entity_ranks, entity_weight=entity_weight)
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
