"""Beliefs on the theme map and the company dossier (beliefs ticket 03).

A theme's Beliefs are its active ones, each with the companies its citations' Facts speak for
(`cited_companies`: the subject companies of the cited Facts). A company's Beliefs are those
that name it (`companies`) or cite a Fact it is the subject of, each with the company's
**Exposure**, derived from the two:

- `holder`: the Belief names the company and a load-bearing, positive citation is a Fact the
  company itself states (it holds the position the Belief asserts);
- `dependent`: the Belief names the company, but no load-bearing positive citation is its own
  (it depends on the bottleneck; others' words carry the evidence);
- `supplier`: the Belief does not name the company, but a cited Fact is the company's (it is
  the source of evidence for another company's Belief).
"""

import uuid
from typing import Literal

from pydantic import Field
from sqlalchemy import Connection, text

from atlas.beliefs.service import BeliefSummary, CompanyRef, list_beliefs

type Exposure = Literal["holder", "supplier", "dependent"]

# The most Beliefs one theme or company read returns (the pilot's scale).
_MAX_BELIEFS = 500


class ThemeBelief(BeliefSummary):
    cited_companies: list[CompanyRef] = Field(
        description="the companies whose Facts the Belief cites, by name"
    )


class CompanyBelief(ThemeBelief):
    exposure: Exposure = Field(
        description="holder: the Belief names the company and its own load-bearing Fact backs it;"
        " dependent: it names the company but others' Facts carry it; supplier: it names"
        " another company and cites this one's Fact"
    )


def _cited(
    connection: Connection, belief_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, list[CompanyRef]], dict[uuid.UUID, set[uuid.UUID]]]:
    """The companies each Belief's citations speak for, and those whose own Fact is a
    load-bearing positive citation of it."""
    cited: dict[uuid.UUID, list[CompanyRef]] = {each: [] for each in belief_ids}
    backing: dict[uuid.UUID, set[uuid.UUID]] = {each: set() for each in belief_ids}
    rows = connection.execute(
        text(
            "SELECT c.belief_id, co.id, co.slug, co.display_name,"
            " bool_or(c.weight = 'load_bearing' AND c.valence > 0) AS backs"
            " FROM belief_citation c JOIN assertion a ON a.id = c.ref_id"
            " JOIN company co ON co.id = a.subject_company_id"
            " WHERE c.belief_id = ANY(:ids)"
            " GROUP BY c.belief_id, co.id, co.slug, co.display_name ORDER BY co.display_name"
        ),
        {"ids": belief_ids},
    )
    for row in rows:
        cited[row.belief_id].append(
            CompanyRef(id=row.id, slug=row.slug, display_name=row.display_name)
        )
        if row.backs:
            backing[row.belief_id].add(row.id)
    return cited, backing


def theme_beliefs(connection: Connection, theme_id: str) -> list[ThemeBelief]:
    """The theme's active Beliefs, oldest first."""
    found = list_beliefs(connection, theme=theme_id, status="active", limit=_MAX_BELIEFS, offset=0)[
        0
    ]
    cited, _ = _cited(connection, [each.id for each in found])
    return [ThemeBelief(**each.model_dump(), cited_companies=cited[each.id]) for each in found]


def company_beliefs(connection: Connection, company_id: uuid.UUID) -> list[CompanyBelief]:
    """The active Beliefs naming the company or citing a Fact it states, with its Exposure."""
    ids = list(
        connection.execute(
            text(
                "SELECT b.id FROM belief b WHERE b.status = 'active' AND ("
                " EXISTS (SELECT FROM belief_company bc"
                "   WHERE bc.belief_id = b.id AND bc.company_id = :company)"
                " OR EXISTS (SELECT FROM belief_citation c JOIN assertion a ON a.id = c.ref_id"
                "   WHERE c.belief_id = b.id AND a.subject_company_id = :company))"
            ),
            {"company": company_id},
        ).scalars()
    )
    if not ids:
        return []
    found = list_beliefs(connection, ids=ids, status="active", limit=_MAX_BELIEFS, offset=0)[0]
    cited, backing = _cited(connection, ids)
    result: list[CompanyBelief] = []
    for each in found:
        named = any(company.id == company_id for company in each.companies)
        exposure: Exposure
        if not named:
            exposure = "supplier"
        elif company_id in backing[each.id]:
            exposure = "holder"
        else:
            exposure = "dependent"
        result.append(
            CompanyBelief(**each.model_dump(), cited_companies=cited[each.id], exposure=exposure)
        )
    return result
