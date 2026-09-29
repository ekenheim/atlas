"""The Financial Analyst's part of an investigation (the `financial_analyst` task): what it is
sent, and which of its proposed inputs stand.

**Sent.** Each seed company that an accepted Claim names, with its as-of XBRL figures: per
metric (revenue, operating income, cash, debt, share counts), the latest reported (never
derived) value, an annual one for a flow metric where there is one, each as its observation
ID. The accepted Claims, each by its Assertion ID, with their quotes as quoted, low-trust
retrieved data.

**Kept.** Each proposed scenario becomes an assumption table (atlas.scenarios.model). An
input stands only if it validates on its own (a value has a source or a basis; three
ordered values within the input's bounds) and its source stands at the investigation's
as-of time, citing only what the Analyst was sent (atlas.scenarios.sources). Anything else
is rejected with its reason and the input becomes missing: never a number without a source.
A scenario for a company it wasn't sent is dropped.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import JsonValue, ValidationError
from sqlalchemy import Connection, RowMapping, text

from atlas.financials.metrics import MetricCatalog, MetricValue, metric_values
from atlas.financials.service import company_observations
from atlas.financials.xbrl import period_days, select_as_of
from atlas.roles.contract import QuotedText
from atlas.roles.financial_analyst import (
    AnalystClaim,
    AnalystCompany,
    AnalystFigure,
    AnalystInput,
    FinancialAnalystRequest,
    ProposedInput,
    ProposedScenario,
    ScenarioProposal,
)
from atlas.scenarios.model import (
    INPUTS,
    AssumptionTable,
    InputName,
    MissingInput,
    number,
)
from atlas.scenarios.sources import check_sources

# The metrics the Analyst is sent, in this order.
ANALYST_METRICS = (
    "revenue",
    "operating_income",
    "cash",
    "total_debt",
    "debt_current",
    "debt_noncurrent",
    "diluted_shares",
    "shares_outstanding",
)
_ANNUAL_DAYS = 350


@dataclass
class AnalystContext:
    request: FinancialAnalystRequest
    retrieved: list[QuotedText]
    observations: dict[uuid.UUID, set[uuid.UUID]]  # company -> the observation IDs sent
    assertions: set[uuid.UUID] = field(default_factory=set[uuid.UUID])


def analyst_companies(
    connection: Connection, seed_company_ids: Sequence[uuid.UUID], claims: Sequence[RowMapping]
) -> list[tuple[uuid.UUID, str]]:
    """The seed companies an accepted Claim names, in seed order, with their names."""
    named = {
        each
        for claim in claims
        for each in (claim["subject_company_id"], claim["object_company_id"])
        if each is not None
    }
    wanted = [seed for seed in seed_company_ids if seed in named]
    names = dict(
        connection.execute(
            text("SELECT id, display_name FROM company WHERE id = ANY(:ids)"), {"ids": wanted}
        ).all()
    )
    return [(each, str(names[each])) for each in wanted if each in names]


def analyst_context(
    connection: Connection,
    *,
    theme_id: str,
    question: str,
    as_of: datetime,
    companies: Sequence[tuple[uuid.UUID, str]],
    claims: Sequence[RowMapping],
    catalog: MetricCatalog,
) -> AnalystContext:
    sent: dict[uuid.UUID, set[uuid.UUID]] = {}
    entries: list[AnalystCompany] = []
    for company_id, name in companies:
        selected = select_as_of(company_observations(connection, company_id), as_of)
        values = metric_values(
            selected, catalog, [m for m in ANALYST_METRICS if m in catalog.metrics]
        )
        figures = [_figure(value, catalog) for value in _latest(values)]
        sent[company_id] = {uuid.UUID(figure.observation_id) for figure in figures}
        entries.append(AnalystCompany(company_id=str(company_id), name=name, figures=figures))
    assertions: dict[uuid.UUID, RowMapping] = {}
    for claim in claims:
        assertions.setdefault(claim["assertion_id"], claim)
    request = FinancialAnalystRequest(
        theme_id=theme_id,
        research_question=question,
        as_of=as_of.isoformat(),
        inputs=[
            AnalystInput(
                name=spec.name, measure=spec.measure, meaning=spec.meaning, xbrl_allowed=spec.xbrl
            )
            for spec in INPUTS
        ],
        companies=entries,
        claims=[
            AnalystClaim(
                assertion_id=str(assertion_id),
                subject=claim["subject_name"],
                predicate=claim["predicate"],
                object=claim["object_name"] or claim["object_text"] or "",
                product=claim["product"],
                layer=claim["layer"],
            )
            for assertion_id, claim in assertions.items()
        ],
    )
    retrieved = [
        QuotedText(
            id=str(assertion_id),
            source=f"{claim['source_version_id']}#{claim['span_start']}-{claim['span_end']}",
            text=claim["quote"],
        )
        for assertion_id, claim in assertions.items()
    ]
    return AnalystContext(request, retrieved, sent, set(assertions))


def _latest(values: Sequence[MetricValue]) -> list[MetricValue]:
    """Per metric, the latest reported value: an annual one for a flow metric if any."""
    chosen: dict[str, MetricValue] = {}
    for value in values:
        if value.derived:
            continue
        current = chosen.get(value.metric)
        if current is None or _rank(value) > _rank(current):
            chosen[value.metric] = value
    return [chosen[metric] for metric in ANALYST_METRICS if metric in chosen]


def _rank(value: MetricValue) -> tuple[bool, Any, int, str]:
    days = period_days(value.period_start, value.period_end)
    annual = days is None or days >= _ANNUAL_DAYS
    return (annual, value.period_end, days or 0, value.unit)


def _figure(value: MetricValue, catalog: MetricCatalog) -> AnalystFigure:
    return AnalystFigure(
        observation_id=str(value.sources[0].id),
        metric=value.metric,
        label=catalog.metrics[value.metric].label,
        concept=value.concept,
        period_start=value.period_start.isoformat() if value.period_start else None,
        period_end=value.period_end.isoformat(),
        unit=value.unit,
        value=number(value.value),
    )


@dataclass
class KeptProposals:
    tables: list[AssumptionTable]
    rejected: list[dict[str, JsonValue]]  # {company_id, input, reason}


def keep_proposals(
    connection: Connection, context: AnalystContext, proposal: ScenarioProposal, as_of: datetime
) -> KeptProposals:
    """The proposal's assumption tables with only the inputs that stand (see the module)."""
    kept = KeptProposals([], [])
    done: set[uuid.UUID] = set()
    for scenario in proposal.scenarios:
        company_id = _uuid(scenario.company_id)
        if company_id is None or company_id not in context.observations:
            kept.rejected.append(
                _rejected(scenario.company_id, None, "a company the Analyst wasn't sent")
            )
            continue
        if company_id in done:
            kept.rejected.append(
                _rejected(scenario.company_id, None, "a second scenario for the company")
            )
            continue
        table = _table(company_id, scenario, kept)
        if table is None:
            continue
        problems = check_sources(
            connection,
            table,
            as_of,
            allowed_observations=context.observations[company_id],
            allowed_assertions=context.assertions,
        )
        if problems:
            inputs = dict(table.inputs)
            for problem in problems:
                kept.rejected.append(_rejected(str(company_id), problem.input, problem.reason))
                inputs[problem.input] = MissingInput(
                    kind="missing", reason=f"rejected: {problem.reason}"
                )
            table = table.model_copy(update={"inputs": inputs})
        done.add(company_id)
        kept.tables.append(table)
    return kept


def _table(
    company_id: uuid.UUID, scenario: ProposedScenario, kept: KeptProposals
) -> AssumptionTable | None:
    base: dict[str, Any] = {
        "company_id": str(company_id),
        "product": scenario.product,
        "currency": scenario.currency,
    }
    try:
        AssumptionTable.model_validate(base)
    except ValidationError as error:
        kept.rejected.append(_rejected(str(company_id), None, _errors(error)))
        return None
    inputs: dict[InputName, Any] = {}
    for proposed in scenario.inputs:
        if proposed.name in inputs:
            kept.rejected.append(_rejected(str(company_id), proposed.name, "proposed twice"))
            continue
        raw, reason = _raw_input(proposed)
        if raw is not None:
            try:
                AssumptionTable.model_validate(base | {"inputs": {proposed.name: raw}})
            except ValidationError as error:
                raw, reason = None, _errors(error)
        if raw is None:
            reason = reason or "invalid"
            kept.rejected.append(_rejected(str(company_id), proposed.name, reason))
            raw = {"kind": "missing", "reason": f"rejected: {reason}"}
        inputs[proposed.name] = raw
    return AssumptionTable.model_validate(base | {"inputs": inputs})


def _raw_input(proposed: ProposedInput) -> tuple[dict[str, Any] | None, str | None]:
    values = {"low": proposed.low, "base": proposed.base, "high": proposed.high}
    if proposed.kind == "missing":
        if any(each is not None for each in values.values()):
            return None, "a missing input has values"
        return {"kind": "missing", "reason": proposed.basis}, None
    if proposed.kind == "estimated":
        return {"kind": "estimated", "basis": proposed.basis, **values}, None
    cited = [each for each in (proposed.observation_id, proposed.assertion_id) if each is not None]
    if len(cited) != 1:
        return None, "a sourced input cites exactly one observation_id or assertion_id"
    if _uuid(cited[0]) is None:
        return None, f"cites {cited[0]!r}, which isn't an ID it was sent"
    source = (
        {"type": "xbrl_observation", "observation_id": proposed.observation_id}
        if proposed.observation_id is not None
        else {"type": "assertion", "assertion_id": proposed.assertion_id}
    )
    return {"kind": "sourced", "source": source, **values}, None


def _errors(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in each['loc'][1:]) or 'value'}: {each['msg']}"
        if each["loc"]
        else each["msg"]
        for each in error.errors(include_url=False)
    )


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _rejected(company_id: str, name: InputName | None, reason: str) -> dict[str, JsonValue]:
    return {"company_id": company_id, "input": name, "reason": reason[:500]}
