"""Checking a scenario's sources against the data as of its cutoff.

A `sourced` input stands only if its source does:

- **An XBRL observation** must be the as-of observation of the table's company for its period
  key (from the latest periodic filing available at `as_of`, never a value a later filing
  restated), may source only an input an XBRL fact can measure (a currency amount or a share
  count), must be in the table's currency (or `shares`), since currencies are never mixed
  without an FX basis, and must equal the input's value in every case.
- **An Assertion** must exist, be available at `as_of` (its Source Version's corrected
  availability, `source_version_availability`)
  and not be rejected or superseded.

`allowed_*` narrows what may be cited further (the Financial Analyst may cite only what it
was sent).
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, text

from atlas.financials.reads import FinancialObservation, observation_view
from atlas.financials.service import company_observations, get_observation
from atlas.financials.xbrl import Observation, select_as_of
from atlas.scenarios.model import (
    CASES,
    INPUT_NAMES,
    INPUT_SPECS,
    AssertionSource,
    AssumptionTable,
    InputName,
    SourcedInput,
    XbrlSource,
)


@dataclass(frozen=True)
class SourceProblem:
    input: InputName
    reason: str

    def __str__(self) -> str:
        return f"{self.input}: {self.reason}"


class ResolvedAssertion(BaseModel):
    """An Assertion span a scenario input cites."""

    model_config = ConfigDict(frozen=True)

    type: Literal["assertion"] = "assertion"
    assertion_id: uuid.UUID
    source_version_id: uuid.UUID
    quote: str
    span_start: int
    span_end: int
    verification_status: str
    available_at: datetime


class ResolvedObservation(BaseModel):
    """An XBRL observation a scenario input cites, with its full source."""

    model_config = ConfigDict(frozen=True)

    type: Literal["xbrl_observation"] = "xbrl_observation"
    observation: FinancialObservation


ResolvedSource = ResolvedAssertion | ResolvedObservation


def check_sources(
    connection: Connection,
    table: AssumptionTable,
    as_of: datetime,
    *,
    allowed_observations: Collection[uuid.UUID] | None = None,
    allowed_assertions: Collection[uuid.UUID] | None = None,
) -> list[SourceProblem]:
    """Every problem with the table's sources (none: every source stands)."""
    problems: list[SourceProblem] = []
    selected: dict[uuid.UUID, Observation] | None = None
    for name in INPUT_NAMES:
        each = table.get(name)
        if not isinstance(each, SourcedInput):
            continue
        source = each.source
        if isinstance(source, XbrlSource):
            if selected is None:
                chosen = select_as_of(company_observations(connection, table.company_id), as_of)
                selected = {observation.id: observation for observation in chosen.values()}
            reason = _xbrl_problem(connection, table, name, each, source, selected, as_of)
            if reason is None and (
                allowed_observations is not None
                and source.observation_id not in allowed_observations
            ):
                reason = "cites an XBRL observation it wasn't sent"
        else:
            reason = _assertion_problem(connection, source, as_of)
            if reason is None and (
                allowed_assertions is not None and source.assertion_id not in allowed_assertions
            ):
                reason = "cites an Assertion that isn't an accepted Claim's of the investigation"
        if reason is not None:
            problems.append(SourceProblem(name, reason))
    return problems


def _xbrl_problem(
    connection: Connection,
    table: AssumptionTable,
    name: InputName,
    each: SourcedInput,
    source: XbrlSource,
    selected: dict[uuid.UUID, Observation],
    as_of: datetime,
) -> str | None:
    spec = INPUT_SPECS[name]
    if not spec.xbrl:
        return f"an XBRL fact can't source {name} ({spec.meaning})"
    observation = selected.get(source.observation_id)
    if observation is None:
        return _not_selected(connection, table.company_id, source.observation_id, as_of)
    wanted = "shares" if spec.measure == "shares" else table.currency
    if observation.unit != wanted:
        return (
            f"XBRL observation {observation.id} is in {observation.unit}, not {wanted}:"
            " currencies are never mixed without an FX basis"
            if spec.measure == "money"
            else f"XBRL observation {observation.id} is in {observation.unit}, not shares"
        )
    if any(each.value(case) != observation.value for case in CASES):
        return (
            f"every case must equal XBRL observation {observation.id}'s value"
            f" {observation.value} ({observation.concept}, period ending"
            f" {observation.period_end.isoformat()})"
        )
    return None


def _not_selected(
    connection: Connection, company_id: uuid.UUID, observation_id: uuid.UUID, as_of: datetime
) -> str:
    owner = connection.execute(
        text("SELECT company_id FROM financial_observation WHERE id = :id"),
        {"id": observation_id},
    ).scalar_one_or_none()
    observation = get_observation(connection, observation_id)
    if owner is None or observation is None:
        return f"XBRL observation {observation_id} doesn't exist"
    if owner != company_id:
        return f"XBRL observation {observation_id} is another company's"
    if observation.available_at > as_of:
        return (
            f"XBRL observation {observation_id} wasn't available at {as_of.isoformat()}"
            f" (its filing is available from {observation.available_at.isoformat()})"
        )
    return (
        f"XBRL observation {observation_id} isn't the as-of value at {as_of.isoformat()}:"
        " a later periodic filing available by then reports its period"
    )


def _assertion_problem(
    connection: Connection, source: AssertionSource, as_of: datetime
) -> str | None:
    found = _assertion(connection, source.assertion_id)
    if found is None:
        return f"Assertion {source.assertion_id} doesn't exist"
    if found.available_at > as_of:
        return f"Assertion {source.assertion_id}'s source wasn't available at {as_of.isoformat()}"
    if found.verification_status in ("rejected", "superseded"):
        return f"Assertion {source.assertion_id} is {found.verification_status}"
    return None


def _assertion(connection: Connection, assertion_id: uuid.UUID) -> ResolvedAssertion | None:
    row = (
        connection.execute(
            text(
                "SELECT a.id AS assertion_id, a.source_version_id, a.quote, a.span_start,"
                " a.span_end, a.verification_status, av.available_at FROM assertion a"
                " JOIN source_version_availability av ON av.source_version_id = a.source_version_id"
                " WHERE a.id = :id"
            ),
            {"id": assertion_id},
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else ResolvedAssertion.model_validate(dict(row))


def resolve_sources(
    connection: Connection, table: AssumptionTable
) -> dict[InputName, ResolvedSource]:
    """What each sourced input cites, for display (whatever its state now)."""
    resolved: dict[InputName, ResolvedSource] = {}
    for name in INPUT_NAMES:
        each = table.get(name)
        if not isinstance(each, SourcedInput):
            continue
        if isinstance(each.source, XbrlSource):
            observation = get_observation(connection, each.source.observation_id)
            if observation is not None:
                resolved[name] = ResolvedObservation(observation=observation_view(observation))
        else:
            found = _assertion(connection, each.source.assertion_id)
            if found is not None:
                resolved[name] = found
    return resolved
