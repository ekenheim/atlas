"""The entity hop: from a company to every document of the theme that names it (memory-quality
ticket 09; docs/decisions.md, "The entity hop").

A recall finds what ranks for a query; it does not promise every document that names a
company. Memory does keep that index: every retain item names its filer and each universe
company its section mentions as entities, given as written (`resolve_entities` false; ticket
04), and the memory list filtered by an entity is exhaustive (study finding 4; recording
`entity_memories/01-by-entity-and-tag`). So once the Scout has recorded its reading pointers
(atlas.investigations.pointers), its task makes the hop, with no LLM call and no budget:

1. **The companies hopped**: the round's seeds first, then the researched companies the
   round's recall pointers name, by their weight (atlas.investigations.companies); at most
   `ATLAS_ENTITY_HOP_MAX_COMPANIES` (default 6).
2. **The company's entity**: the entity whose canonical name is exactly the company's
   canonical name (its `legal_name`, the name ticket 04 sends), found in the bank's entity
   listing (`GET .../entities`, paged). Never by parsing a memory's `entities` string, which
   the memory list joins with commas (a name with a comma would split). A company with no
   such entity (nothing retained names it, or only under the extractor's short forms) is
   recorded `no_entity`.
3. **Its facts**: every memory carrying the entity, strictly scoped to the theme's tag
   (`entity_memories`), each resolved to its Source Version section the way a recall's
   memory is (atlas.research.provenance). A section of the company's **own** document makes
   no entity pointer (its recall covers it), and neither does one available after the
   investigation's as-of time (the listing's own date filter is only partly verified, so
   Atlas applies the bound from each fact's Source Version), one the round's recall pointers
   already point at, or a memory that does not resolve.
4. **The entity pointers**: the remaining sections, newest Source Version first (one pointer
   per section, from its first fact), at most `ATLAS_ENTITY_HOP_MAX_FACTS` (default 20) per
   company; each a `reading_pointer` of `query_kind` `entity`, naming the company whose
   document it is (`company_id`) and the company the hop was made for (`query_company_id`),
   the entity (`entity_id`, `query` its canonical name), `query_index` the company's place
   in the hop and `rank` the pointer's place among the company's.

Entity pointers join the ranking of pointed companies (each weighs
`ATLAS_ENTITY_HOP_POINTER_WEIGHT` / its rank; the weight used is recorded in the Scout's
artifacts) and passage selection as their own channel (atlas.claims.selection). **Co-mention
is a reason to read, nothing more**: an entity pointer makes no edge and no Evidence, and its
memory's text, like any pointer's, is never quoted and never sent to a role.

**Failures.** A listing that fails for a reason of its own (an HTTP error that is neither a
quota nor an outage) is an `entity_listing_failed` event and the hop goes on without it (the
entity listing: no company is hopped); a quota or outage is re-raised before anything is
stored, so the task pauses and hops again when it lifts. The hop is recorded once per task,
in one transaction with its events, its counts in the task's artifacts and one audit event
(`investigation.entity_pointers_recorded`, by `atlas-scout`); a later attempt asks nothing.
"""

import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import JsonValue
from sqlalchemy import Engine, RowMapping, text

from atlas.audit import content_hash, record
from atlas.hindsight import HindsightError, HindsightGateway, Memory, TagScope
from atlas.investigations.companies import rank_companies
from atlas.investigations.pointers import ENTITY_QUERY, SCOUT_ACTOR, SCOUT_QUERY
from atlas.investigations.service import event, lock
from atlas.jobs.pacing import classify_failure
from atlas.research.provenance import Citation, CitationSource

# The Scout task's artifacts that record the hop (see `record_entity_pointers`).
ENTITY_HOP = "entity_hop"
ENTITY_POINTERS = "entity_pointers"
ENTITY_LISTINGS_FAILED = "entity_listings_failed"
ENTITY_POINTER_WEIGHT = "entity_pointer_weight"
# What became of a company the hop was made for.
type HopOutcome = Literal["listed", "no_entity", "listing_failed", "entities_unavailable"]
# The entity listing is read this many entities a page, at most this many pages.
_PAGE = 1000
_MAX_PAGES = 50
_ERROR_LIMIT = 500

# A memory's provenance: resolves it to its sections (atlas.research.provenance).
Resolve = Callable[[Memory], Citation]


@dataclass(frozen=True)
class HopLimits:
    max_companies: int
    max_facts: int
    pointer_weight: float


@dataclass
class _Hop:
    """One company's hop, as the Scout's artifacts and the investigation read give it."""

    company_id: uuid.UUID
    slug: str
    company_name: str
    entity_name: str
    entity_id: str | None = None
    outcome: HopOutcome = "listed"
    facts_listed: int = 0
    pointers: int = 0
    own_documents: int = 0
    after_as_of: int = 0
    already_pointed: int = 0
    unresolved: int = 0
    beyond_limit: int = 0
    error: str | None = None
    rows: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def as_json(self) -> dict[str, JsonValue]:
        return {
            "company_id": str(self.company_id),
            "slug": self.slug,
            "company_name": self.company_name,
            "entity_name": self.entity_name,
            "entity_id": self.entity_id,
            "outcome": self.outcome,
            "facts_listed": self.facts_listed,
            "pointers": self.pointers,
            "own_documents": self.own_documents,
            "after_as_of": self.after_as_of,
            "already_pointed": self.already_pointed,
            "unresolved": self.unresolved,
            "beyond_limit": self.beyond_limit,
        }


def record_entity_pointers(
    engine: Engine,
    gateway: HindsightGateway,
    resolve: Resolve,
    investigation: RowMapping,
    task: RowMapping,
    limits: HopLimits,
) -> dict[str, JsonValue]:
    """Make the round's entity hop and store its entity pointers (see the module); returns the
    Scout task's hop artifacts. A task whose hop is recorded asks nothing."""
    recorded = _recorded(task["artifacts"])
    if recorded is not None:
        return recorded
    as_of: datetime = investigation["as_of"]
    scope = TagScope([f"theme:{investigation['theme']}"], "any_strict")
    hops = _companies(engine, investigation, task, limits.max_companies)
    failures: list[tuple[_Hop | None, str]] = []
    entities: dict[str, list[str]] | None = None
    if hops:
        try:
            entities = _entities(gateway)
        except HindsightError as error:
            if classify_failure(error) is not None:
                raise  # a quota or an outage: the task pauses and hops again
            failures.append((None, _error(error)))
    pointed = _recall_sections(engine, task["id"])
    for index, hop in enumerate(hops, start=1):
        if entities is None:
            hop.outcome = "entities_unavailable"
            continue
        ids = entities.get(hop.entity_name, [])
        if not ids:
            hop.outcome = "no_entity"
            continue
        hop.entity_id = ids[0]
        try:
            listed = _listed(gateway, ids, scope)
        except HindsightError as error:
            if classify_failure(error) is not None:
                raise
            hop.outcome, hop.error = "listing_failed", _error(error)
            failures.append((hop, hop.error))
            continue
        hop.facts_listed = len(listed)
        _pointers(hop, index, listed, resolve, as_of, pointed, limits.max_facts)
        for rank, row in enumerate(hop.rows, start=1):
            row |= {
                "id": uuid.uuid4(),
                "investigation_id": investigation["id"],
                "round": task["round"],
                "task_id": task["id"],
                "rank": rank,
            }
    rows = [row for hop in hops for row in hop.rows]
    with engine.begin() as connection:
        lock(connection, investigation["id"])
        recorded = _recorded(
            connection.execute(
                text("SELECT artifacts FROM investigation_task WHERE id = :id"), {"id": task["id"]}
            ).scalar_one()
        )
        if recorded is not None:
            return recorded  # by an earlier attempt
        if rows:
            connection.execute(text(_INSERT), rows)
        artifacts: dict[str, JsonValue] = {
            ENTITY_HOP: list[JsonValue](hop.as_json() for hop in hops),
            ENTITY_POINTERS: len(rows),
            ENTITY_LISTINGS_FAILED: len(failures),
            ENTITY_POINTER_WEIGHT: limits.pointer_weight,
        }
        for failed, error in failures:
            event(
                connection,
                investigation["id"],
                "entity_listing_failed",
                round=task["round"],
                task_key=task["key"],
                listing="entity_memories" if failed is not None else "entities",
                company_id=str(failed.company_id) if failed is not None else None,
                entity_id=failed.entity_id if failed is not None else None,
                error=error,
            )
        event(
            connection,
            investigation["id"],
            "entity_pointers_recorded",
            round=task["round"],
            task_key=task["key"],
            **artifacts,
        )
        connection.execute(
            text(
                "UPDATE investigation_task SET artifacts = artifacts || CAST(:new AS jsonb)"
                " WHERE id = :id"
            ),
            {"id": task["id"], "new": json.dumps(artifacts)},
        )
        if rows:
            record(
                connection,
                SCOUT_ACTOR,
                "investigation.entity_pointers_recorded",
                entity_type="investigation_task",
                entity_id=str(task["id"]),
                new_hash=content_hash({"pointers": rows}),
            )
    return artifacts


_COLUMNS = (
    "id, investigation_id, round, task_id, query_index, query, rank, memory_id, memory_type,"
    " memory_text, source_version_id, section_anchor, section_heading, section_char_start,"
    " section_char_end, company_id, available_at, citation_state, query_kind, query_company_id,"
    " entity_names, entity_id"
)
_INSERT = (
    f"INSERT INTO reading_pointer ({_COLUMNS}) VALUES ("  # noqa: S608 (constant SQL)
    + ", ".join(f":{column.strip()}" for column in _COLUMNS.split(","))
    + ")"
)


def _companies(
    engine: Engine, investigation: RowMapping, task: RowMapping, max_companies: int
) -> list[_Hop]:
    """The companies the round hops from: its seeds, then the researched companies its recall
    pointers name by weight; at most `max_companies`."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT c.slug, p.rank FROM reading_pointer p"
                " JOIN company c ON c.id = p.company_id AND c.role = 'researched'"
                " WHERE p.task_id = :task AND p.query_kind = :kind"
            ),
            {"task": task["id"], "kind": SCOUT_QUERY},
        ).all()
        ranks: dict[str, list[int]] = {}
        for row in rows:
            ranks.setdefault(row.slug, []).append(row.rank)
        seeds = list(investigation["seed_company_ids"] or [])
        companies = {
            row.id: row
            for row in connection.execute(
                text(
                    "SELECT id, slug, display_name, legal_name FROM company"
                    " WHERE id = ANY(:ids) OR slug = ANY(:slugs)"
                ),
                {"ids": seeds, "slugs": list(ranks)},
            )
        }
    by_slug = {row.slug: row for row in companies.values()}
    order = [
        *(companies[seed] for seed in seeds if seed in companies),
        *(by_slug[slug] for slug, _ in rank_companies(ranks) if slug in by_slug),
    ]
    hops: list[_Hop] = []
    for company in dict.fromkeys(order):
        if len(hops) >= max_companies:
            break
        hops.append(_Hop(company.id, company.slug, company.display_name, company.legal_name))
    return hops


def _entities(gateway: HindsightGateway) -> dict[str, list[str]]:
    """The bank's entities by exact canonical name (most mentioned first)."""
    found: dict[str, list[str]] = {}
    read = 0
    for _ in range(_MAX_PAGES):
        page = gateway.entities(limit=_PAGE, offset=read)
        for entity in page.items:
            found.setdefault(entity.canonical_name, []).append(entity.id)
        read += len(page.items)
        if not page.items or read >= page.total:
            break
    return found


def _listed(gateway: HindsightGateway, entity_ids: Sequence[str], scope: TagScope) -> list[Memory]:
    """Every memory carrying one of the entities (one name's), each once, in listing order."""
    memories: dict[str, Memory] = {}
    for entity_id in entity_ids:
        for memory in gateway.entity_memories(entity_id, scope=scope):
            memories.setdefault(memory.id, memory)
    return list(memories.values())


def _recall_sections(engine: Engine, task_id: uuid.UUID) -> set[tuple[uuid.UUID, str]]:
    """The sections the task's recall pointers already point at."""
    with engine.connect() as connection:
        return {
            (row.source_version_id, row.section_anchor)
            for row in connection.execute(
                text(
                    "SELECT DISTINCT source_version_id, section_anchor FROM reading_pointer"
                    " WHERE task_id = :task AND query_kind = :kind"
                ),
                {"task": task_id, "kind": SCOUT_QUERY},
            )
        }


def _pointers(
    hop: _Hop,
    index: int,
    listed: Sequence[Memory],
    resolve: Resolve,
    as_of: datetime,
    pointed: set[tuple[uuid.UUID, str]],
    max_facts: int,
) -> None:
    """The hop's entity pointer rows (without their IDs and ranks), newest first, and its
    counts (see the module)."""
    candidates: dict[tuple[uuid.UUID, str], tuple[Memory, CitationSource]] = {}
    for memory in listed:
        citation = resolve(memory)
        if citation.state != "resolved":
            hop.unresolved += 1
            continue
        for source in citation.sources:
            section = (source.source_version_id, source.section_anchor)
            if source.company_id == hop.company_id:
                hop.own_documents += 1
            elif source.available_at > as_of:
                hop.after_as_of += 1
            elif section in pointed:
                hop.already_pointed += 1
            else:
                candidates.setdefault(section, (memory, source))
    newest = sorted(
        candidates.values(),
        key=lambda found: (
            -found[1].available_at.timestamp(),
            str(found[1].source_version_id),
            found[1].section_char_start,
            found[1].section_anchor,
        ),
    )
    hop.beyond_limit = max(len(newest) - max_facts, 0)
    for memory, source in newest[:max_facts]:
        hop.rows.append(
            {
                "query_index": index,
                "query": hop.entity_name,
                "memory_id": memory.id,
                "memory_type": memory.type,
                "memory_text": memory.text,
                "source_version_id": source.source_version_id,
                "section_anchor": source.section_anchor,
                "section_heading": source.section_heading,
                "section_char_start": source.section_char_start,
                "section_char_end": source.section_char_end,
                "company_id": source.company_id,
                "available_at": source.available_at,
                "citation_state": "resolved",
                "query_kind": ENTITY_QUERY,
                "query_company_id": hop.company_id,
                # The entity the fact was listed by: its name as Atlas sent it, never parsed
                # from the memory list's comma-joined string.
                "entity_names": [hop.entity_name],
                "entity_id": hop.entity_id,
            }
        )
    hop.pointers = len(hop.rows)


def _recorded(artifacts: dict[str, Any]) -> dict[str, JsonValue] | None:
    """The task's hop artifacts, once recorded."""
    if ENTITY_POINTERS not in artifacts:
        return None
    keys = (ENTITY_HOP, ENTITY_POINTERS, ENTITY_LISTINGS_FAILED, ENTITY_POINTER_WEIGHT)
    return {key: artifacts[key] for key in keys if key in artifacts}


def _error(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"[:_ERROR_LIMIT]
