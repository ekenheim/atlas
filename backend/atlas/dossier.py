"""The Company dossier's read (product spec §10.1 B): one company's identity and listings,
the identity mappings awaiting the owner, its themes, its Source Documents, its Relationships
out (as subject) and in (as object), its as-of financials, and the exchange requests the
fetch gate blocked.

Every part is the same read its own route serves (`/companies/{id}`, `/identity-mappings`,
`/companies/{id}/sources`, `/relationships?company_id=`, `/companies/{id}/financials`,
`/companies/{id}/fetch-gate-decisions?status=blocked`), gathered in one connection so the
page sees one consistent state.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import Connection

from atlas.companies import Company, Universe, company_id_for, get_company
from atlas.financials import FinancialFigures, MetricCatalog, financial_figures
from atlas.identity.service import IdentityMapping, list_mappings
from atlas.ledger import FetchGateDecision, SourceDocument, list_decisions, list_source_documents
from atlas.relationships import Relationship, list_relationships

# The most rows of each list one dossier returns; each total says whether there are more.
DOSSIER_LIMIT = 500


class ThemeRef(BaseModel):
    id: str
    title: str


class CompanyDossier(BaseModel):
    company: Company
    themes: list[ThemeRef] = Field(description="the themes the company belongs to")
    pending_identity_reviews: list[IdentityMapping] = Field(
        description="identity mappings awaiting the owner, oldest first"
    )
    sources: list[SourceDocument] = Field(description="Source Documents, first seen first")
    source_total: int
    relationships_out: list[Relationship] = Field(description="edges with the company as subject")
    relationships_in: list[Relationship] = Field(description="edges with the company as object")
    financials: FinancialFigures = Field(description="canonical metrics as of `as_of`")
    fetch_gate_blocks: list[FetchGateDecision] = Field(
        description="exchange requests the fetch gate blocked, newest first"
    )
    fetch_gate_block_total: int


def company_dossier(
    connection: Connection,
    company_id: uuid.UUID,
    *,
    universe: Universe,
    catalog: MetricCatalog,
    as_of: datetime,
) -> CompanyDossier | None:
    """The dossier, or None when there is no such company."""
    company = get_company(connection, company_id)
    if company is None:
        return None
    themes = [
        ThemeRef(id=theme_id, title=theme.title)
        for theme_id, theme in sorted(universe.themes.items())
        if any(
            company_id_for(slug, universe.companies[slug]) == company_id for slug in theme.companies
        )
    ]
    pending = list_mappings(
        connection,
        review_state="pending",
        company_id=company_id,
        kind=None,
        limit=DOSSIER_LIMIT,
        offset=0,
    )[0]
    sources, source_total = list_source_documents(
        connection, company_id, limit=DOSSIER_LIMIT, offset=0
    )
    edges = list_relationships(
        connection, company_id=company_id, sort="layer", limit=DOSSIER_LIMIT, offset=0
    )[0]
    blocks, block_total = list_decisions(
        connection, company_id, status="blocked", limit=DOSSIER_LIMIT, offset=0
    )
    return CompanyDossier(
        company=company,
        themes=themes,
        pending_identity_reviews=pending,
        sources=sources,
        source_total=source_total,
        relationships_out=[e for e in edges if e.subject_company_id == company_id],
        relationships_in=[e for e in edges if e.object_company_id == company_id],
        financials=financial_figures(connection, company_id, catalog, as_of),
        fetch_gate_blocks=blocks,
        fetch_gate_block_total=block_total,
    )
