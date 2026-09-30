"""The Theme explorer's reads (product spec §10.1 A): each theme's companies by supply-chain
layer, the Relationships between them and the Candidates proposed for it.

A theme is the universe config's (`configs/themes/*.yaml`) extended with the committed
Candidates (`atlas.companies.extend_universe`). A company is listed whether or not it has
been seeded; `gaps` names what it still lacks (`not_seeded`, `no_sources`), and a layer with
no company is itself a coverage gap. The Bottlenecks mental model (Hindsight) is added by the
API, so these reads never call Hindsight.

**Relationships between them:** every edge whose subject is a theme company and whose object
is a theme company or a product, material or technology (no company). An edge to a
researched company outside the theme is on the companies' dossiers, not on the map.

**Counterparties:** a counterparty company (`atlas.counterparties`) is in no theme, but the
edges between it and a theme company are on the map, and `counterparties` lists the ones at
the end of those edges. They are never among the theme's companies, so they count in neither
the layers nor the coverage gaps.
"""

import uuid
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from atlas.candidates import Candidate, list_candidates
from atlas.claims.predicates import LAYERS
from atlas.companies import Layer, SourcePath, Universe, company_id_for
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
    layer: Layer | None
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
    layer: Layer
    covers: str = Field(description="what the layer holds")
    companies: list[ThemeCompany]


class ThemeSummary(BaseModel):
    id: str
    title: str
    description: str
    universe_version: int = Field(description="the theme config's version")
    company_count: int
    companies_without_sources: int
    empty_layers: list[Layer] = Field(description="layers with no company in the theme")
    relationship_count: int
    open_candidate_count: int = Field(description="Candidates still `lead`, awaiting a decision")


class ThemeMap(BaseModel):
    theme: ThemeSummary
    layers: list[ThemeLayer] = Field(description="upstream to downstream, empty ones included")
    unlayered: list[ThemeCompany] = Field(description="companies with no layer set")
    relationships: list[Relationship] = Field(
        description="edges between the theme's companies (or to a product, or between one of"
        " them and a counterparty), by layer"
    )
    counterparties: list[ThemeCounterparty] = Field(
        description="the counterparty companies those edges name, by name"
    )
    candidates: list[Candidate] = Field(description="the theme's Candidates, newest first")


def list_themes(connection: Connection, universe: Universe) -> list[ThemeSummary]:
    return [_build(connection, universe, theme_id).theme for theme_id in sorted(universe.themes)]


def theme_map(connection: Connection, universe: Universe, theme_id: str) -> ThemeMap | None:
    """The theme's map, or None when the universe has no such theme."""
    return _build(connection, universe, theme_id) if theme_id in universe.themes else None


def _build(connection: Connection, universe: Universe, theme_id: str) -> ThemeMap:
    theme = universe.themes[theme_id]
    ids = {slug: company_id_for(slug, universe.companies[slug]) for slug in theme.companies}
    counts = _company_counts(connection, list(ids.values()))
    companies = [
        _theme_company(universe, slug, ids[slug], counts.get(ids[slug])) for slug in theme.companies
    ]

    members = set(ids.values())
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
            # counterparty, or (as the object) a product.
            inside = edge.object_company_id is None or edge.object_company_id in ends
            if edge.subject_company_id in ends and inside:
                edges[edge.id] = edge
    rank = {layer.name: position for position, layer in enumerate(LAYERS)}
    relationships = sorted(
        edges.values(), key=lambda e: (rank[e.layer], e.subject_name, e.predicate, e.created_at)
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
    candidates = list_candidates(connection, state=None, theme=theme_id, limit=_MAX_ROWS, offset=0)[
        0
    ]

    layers = [
        ThemeLayer(
            layer=layer.name,
            covers=layer.covers,
            companies=[c for c in companies if c.layer == layer.name],
        )
        for layer in LAYERS
    ]
    summary = ThemeSummary(
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
    return ThemeMap(
        theme=summary,
        layers=layers,
        unlayered=[c for c in companies if c.layer is None],
        relationships=relationships,
        counterparties=counterparties,
        candidates=candidates,
    )


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
