"""The Theme explorer's reads (product spec §10.1 A): each theme's companies by supply-chain
layer, the Relationships between them and the Candidates proposed for it.

A theme is the universe config's (`configs/themes/*.yaml`) extended with the committed
Candidates (`atlas.companies.extend_universe`). A company is listed whether or not it has
been seeded; `gaps` names what it still lacks (`not_seeded`, `no_sources`), and a layer with
no company is itself a coverage gap. The Bottlenecks mental model (Hindsight) is added by the
API, so these reads never call Hindsight.

**Relationships between them:** every edge whose subject is a theme company and whose object
is a theme company or a product, material or technology (no company). An edge to a
researched company outside the theme is on the companies' dossiers, not on the map. An edge
may have no layer (its Evidence names none): it is among the map's edges, sorted before the
layered ones, and the Theme explorer lists it under its companies instead of under a layer.
A theme company's **company-level** edge (no object at all: its own `capacity_constrained`
statement, `Relationship.company_level`) is such an edge, listed under that company.

**Counterparties:** a counterparty company (`atlas.counterparties`) is in no theme, but the
edges between it and a theme company are on the map, and `counterparties` lists the ones at
the end of those edges. They are never among the theme's companies, so they count in neither
the layers nor the coverage gaps.
"""

import time
import uuid
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from atlas.beliefs.exposure import ThemeBelief, theme_beliefs
from atlas.candidates import Candidate, list_candidates
from atlas.claims.predicates import LAYERS
from atlas.companies import CompanyLayer, SourcePath, Universe, company_id_for
from atlas.relationships import Relationship, list_relationships

# The most edges or Candidates one read returns per company or theme (the pilot's scale).
_MAX_ROWS = 500

type CoverageGap = Literal["not_seeded", "no_sources"]


class ThemeCompany(BaseModel):
    id: uuid.UUID
    slug: str
    display_name: str
    legal_name: str
    country: str
    layer: CompanyLayer | None
    source_path: SourcePath
    seeded: bool = Field(description="the company row exists (open its dossier)")
    source_count: int = Field(description="its Source Documents")
    relationship_count: int = Field(description="edges naming it as subject or object")
    pending_identity_reviews: int = Field(description="identity mappings awaiting the owner")
    gaps: list[CoverageGap]


class ThemeCounterparty(BaseModel):
    """A counterparty company at the other end of a theme company's edge."""

    id: uuid.UUID
    slug: str
    display_name: str
    legal_name: str
    country: str | None
    cik: str | None
    lei: str | None
    relationship_count: int = Field(description="the map's edges naming it")


class ThemeLayer(BaseModel):
    layer: CompanyLayer
    covers: str = Field(description="what the layer holds")
    companies: list[ThemeCompany]


class ThemeSummary(BaseModel):
    id: str
    title: str
    description: str
    universe_version: int = Field(description="the theme config's version")
    company_count: int
    companies_without_sources: int
    empty_layers: list[CompanyLayer] = Field(description="layers with no company in the theme")
    relationship_count: int
    open_candidate_count: int = Field(description="Candidates still `lead`, awaiting a decision")


class ThemeMap(BaseModel):
    theme: ThemeSummary
    beliefs: list[ThemeBelief] = Field(
        description="what Atlas believes about the theme: its active Beliefs, oldest first (the"
        " page groups them by step and judgement)"
    )
    layers: list[ThemeLayer] = Field(description="upstream to downstream, empty ones included")
    unlayered: list[ThemeCompany] = Field(description="companies with no layer set")
    relationships: list[Relationship] = Field(
        description="edges between the theme's companies (or to a product, or between one of"
        " them and a counterparty): those with no layer first (they belong under their"
        " companies, not under a layer), then by layer"
    )
    counterparties: list[ThemeCounterparty] = Field(
        description="the counterparty companies those edges name, by name"
    )
    candidates: list[Candidate] = Field(description="the theme's Candidates, newest first")


# The sections of the theme map, named after the answer's own keys. `theme` (the summary)
# counts the edges and the Candidates, so asking for it computes both; `counterparties` are the
# ends of the edges, so asking for them computes the edges.
MAP_SECTIONS = (
    "theme",
    "beliefs",
    "layers",
    "unlayered",
    "relationships",
    "counterparties",
    "candidates",
)
# `companies` stands for the two sections that list the theme's companies.
MAP_SECTION_ALIASES = {"companies": ("layers", "unlayered")}


def list_themes(connection: Connection, universe: Universe) -> list[ThemeSummary]:
    return [
        _build(connection, universe, theme_id, frozenset({"theme"}))["theme"]
        for theme_id in sorted(universe.themes)
    ]


def theme_sections(
    connection: Connection,
    universe: Universe,
    theme_id: str,
    sections: frozenset[str],
    timings: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """Only the named sections of the map (`MAP_SECTIONS`), each computed only if named (or
    needed by one that is), or None when the universe has no such theme. `timings` receives
    the seconds each computed section took (the edges' time is `relationships`')."""
    if theme_id not in universe.themes:
        return None
    return _build(connection, universe, theme_id, sections, timings)


def _build(
    connection: Connection,
    universe: Universe,
    theme_id: str,
    sections: frozenset[str],
    timings: dict[str, float] | None = None,
) -> dict[str, Any]:
    """The named sections, in the map's order. A section nobody named is not computed."""
    clock = timings if timings is not None else {}

    def timed(name: str) -> Callable[[], None]:
        started = time.perf_counter()

        def stop() -> None:
            clock[name] = clock.get(name, 0.0) + time.perf_counter() - started

        return stop

    theme = universe.themes[theme_id]
    ids = {slug: company_id_for(slug, universe.companies[slug]) for slug in theme.companies}
    built: dict[str, Any] = {}

    companies: list[ThemeCompany] = []
    if sections & {"theme", "layers", "unlayered"}:
        stop = timed("companies")
        counts = _company_counts(connection, list(ids.values()))
        companies = [
            _theme_company(universe, slug, ids[slug], counts.get(ids[slug]))
            for slug in theme.companies
        ]
        stop()

    relationships: list[Relationship] = []
    counterparties: list[ThemeCounterparty] = []
    if sections & {"theme", "relationships", "counterparties"}:
        stop = timed("relationships")
        relationships, counterparties = _edges(connection, set(ids.values()))
        stop()

    candidates: list[Candidate] = []
    if sections & {"theme", "candidates"}:
        stop = timed("candidates")
        candidates = list_candidates(
            connection, state=None, theme=theme_id, limit=_MAX_ROWS, offset=0
        )[0]
        stop()

    # The theme's own layers when its config lists them (a second theme has a supply chain of
    # its own), else the photonics taxonomy's.
    theme_layers: list[tuple[CompanyLayer, str]] = [
        (layer.name, layer.covers)
        for layer in (theme.layers if theme.layers is not None else LAYERS)
    ]
    known = {name for name, _ in theme_layers}
    layers = [
        ThemeLayer(
            layer=name,
            covers=covers,
            companies=[c for c in companies if c.layer == name],
        )
        for name, covers in theme_layers
    ]
    if "theme" in sections:
        built["theme"] = ThemeSummary(
            id=theme_id,
            title=theme.title,
            description=theme.description,
            universe_version=universe.version,
            company_count=len(companies),
            companies_without_sources=sum(1 for c in companies if c.source_count == 0),
            empty_layers=[layer.layer for layer in layers if not layer.companies],
            relationship_count=len(relationships),
            open_candidate_count=sum(1 for c in candidates if c.state == "lead"),
        )
    if "beliefs" in sections:
        stop = timed("beliefs")
        built["beliefs"] = theme_beliefs(connection, theme_id)
        stop()
    if "layers" in sections:
        built["layers"] = layers
    if "unlayered" in sections:
        # A company whose layer the theme does not list (a committed Candidate's) is never
        # lost from the map: it is listed where the companies with no layer are.
        built["unlayered"] = [c for c in companies if c.layer is None or c.layer not in known]
    if "relationships" in sections:
        built["relationships"] = relationships
    if "counterparties" in sections:
        built["counterparties"] = counterparties
    if "candidates" in sections:
        built["candidates"] = candidates
    return built


def _edges(
    connection: Connection, members: set[uuid.UUID]
) -> tuple[list[Relationship], list[ThemeCounterparty]]:
    """The edges on the map and the counterparties at their ends."""
    outside = {
        company_id: counterparty
        for company_id, counterparty in _counterparties(connection).items()
        if company_id not in members
    }
    ends = members | set(outside)
    edges: dict[uuid.UUID, Relationship] = {}
    for company_id in members:
        for edge in list_relationships(
            connection, company_id=company_id, sort="layer", limit=_MAX_ROWS, offset=0
        )[0]:
            # One end is the theme company asked for; the other a theme company, a
            # counterparty, (as the object) a product, or nothing (a company-level edge).
            inside = edge.object_company_id is None or edge.object_company_id in ends
            if edge.subject_company_id in ends and inside:
                edges[edge.id] = edge
    # Edges with no layer first (as the edge table sorts them), then upstream to downstream.
    rank = {layer.name: position for position, layer in enumerate(LAYERS, start=1)}
    relationships = sorted(
        edges.values(),
        key=lambda e: (rank[e.layer] if e.layer else 0, e.subject_name, e.predicate, e.created_at),
    )
    named: dict[uuid.UUID, int] = {}
    for edge in relationships:
        for end in {edge.subject_company_id, edge.object_company_id}:
            if end is not None and end in outside:
                named[end] = named.get(end, 0) + 1
    counterparties = sorted(
        (
            outside[company_id].model_copy(update={"relationship_count": count})
            for company_id, count in named.items()
        ),
        key=lambda c: (c.display_name, c.slug),
    )
    return relationships, counterparties


def _counterparties(connection: Connection) -> dict[uuid.UUID, ThemeCounterparty]:
    rows = connection.execute(
        text(
            "SELECT id, slug, display_name, legal_name, country, cik, lei,"
            " 0 AS relationship_count FROM company WHERE role = 'counterparty'"
        )
    ).mappings()
    return {row["id"]: ThemeCounterparty.model_validate(dict(row)) for row in rows}


def _theme_company(
    universe: Universe, slug: str, company_id: uuid.UUID, counts: tuple[int, int, int] | None
) -> ThemeCompany:
    config = universe.companies[slug]
    seeded = counts is not None
    sources, relationships, pending = counts or (0, 0, 0)
    gaps: list[CoverageGap] = []
    if not seeded:
        gaps.append("not_seeded")
    if sources == 0:
        gaps.append("no_sources")
    return ThemeCompany(
        id=company_id,
        slug=slug,
        display_name=config.display_name,
        legal_name=config.legal_name,
        country=config.country,
        layer=config.layer,
        source_path=config.source_path,
        seeded=seeded,
        source_count=sources,
        relationship_count=relationships,
        pending_identity_reviews=pending,
        gaps=gaps,
    )


def _company_counts(
    connection: Connection, company_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int, int]]:
    """(Source Documents, Relationships, pending identity mappings) of each seeded company."""
    rows = connection.execute(
        text(
            "SELECT c.id,"
            " (SELECT count(*) FROM source_document d WHERE d.company_id = c.id) AS sources,"
            " (SELECT count(*) FROM relationship r"
            "   WHERE r.subject_company_id = c.id OR r.object_company_id = c.id) AS edges,"
            " (SELECT count(*) FROM identity_mapping m"
            "   WHERE m.company_id = c.id AND m.review_state = 'pending') AS pending"
            " FROM company c WHERE c.id = ANY(:ids)"
        ),
        {"ids": company_ids},
    )
    return {row.id: (row.sources, row.edges, row.pending) for row in rows}
