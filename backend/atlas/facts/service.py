"""Recording and reading Facts (see `atlas.facts`)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Connection, Engine, text

from atlas.archive import Archive
from atlas.assertions import (
    Assertion,
    AssertionCreate,
    AssertionRefused,
    Assertions,
    EpistemicType,
    InvalidAssertion,
    get_assertion,
)
from atlas.audit import Actor, content_hash, record
from atlas.investigations.grounding import grounds, number_occurs

FACT_PREDICATE = "fact"

FactStep = Literal[
    "constraint",
    "demand_vs_supply",
    "relief",
    "control",
    "capture",
    "invalidation",
    "context",
]
FactStatus = Literal[
    "in_effect",
    "planned",
    "in_development",
    "hedged",
    "regulatory",
    "reported_by_third_party",
]


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


class Quantity(BaseModel):
    """A magnitude the quote states."""

    model_config = ConfigDict(extra="forbid")

    value: float = Field(description="the number as the quote gives it (it must occur there)")
    unit: str = Field(min_length=1, description='e.g. "USD", "%", "wafers per month"')
    metric: str = Field(min_length=1, description='what is measured, e.g. "net revenue"')

    _not_blank = field_validator("unit", "metric")(_not_blank)


class FactValue(BaseModel):
    """The `value_json` of a Fact's Assertion."""

    model_config = ConfigDict(extra="forbid")

    step: FactStep
    statement: str = Field(
        min_length=1, description="the fact in one sentence, in the quote's terms"
    )
    quantity: Quantity | None = None
    period: str | None = Field(
        default=None, description='as the quote gives it: "Q3 FY2026", "through 2028"'
    )
    status: FactStatus

    _statement = field_validator("statement")(_not_blank)

    @field_validator("period")
    @classmethod
    def _period(cls, value: str | None) -> str | None:
        return value if value is None else _not_blank(value)


class FactCreate(BaseModel):
    """A new Fact: the Assertion's span fields and the Fact's own."""

    model_config = ConfigDict(extra="forbid")

    subject_company_id: uuid.UUID
    source_version_id: uuid.UUID
    quote: str = Field(min_length=1, description="exactly the parsed text at the offsets")
    span_start: int = Field(ge=0)
    span_end: int = Field(ge=0)
    page_or_anchor: str | None = None
    event_start: datetime | None = None
    event_end: datetime | None = None
    epistemic_type: EpistemicType
    parser_version: str | None = None
    investigation_id: uuid.UUID | None = Field(
        default=None, description="the investigation it was found for, if any"
    )
    step: FactStep
    statement: str = Field(min_length=1)
    quantity: Quantity | None = None
    period: str | None = None
    status: FactStatus

    @model_validator(mode="after")
    def _valid(self) -> Self:
        if self.event_start and self.event_end and self.event_end < self.event_start:
            raise ValueError("event_end must not be before event_start")
        self.value()  # statement and period not blank
        return self

    def value(self) -> FactValue:
        return FactValue(
            step=self.step,
            statement=self.statement,
            quantity=self.quantity,
            period=self.period,
            status=self.status,
        )


class Fact(BaseModel):
    """A Fact; `id` is its Assertion's id."""

    id: uuid.UUID
    investigation_id: uuid.UUID | None
    step: FactStep
    status: FactStatus
    statement: str
    quantity: Quantity | None
    period: str | None
    created_at: datetime
    assertion: Assertion


class FactRecorded(BaseModel):
    fact: Fact
    audit_event_id: int


class FactNotFound(AssertionRefused):
    def __init__(self) -> None:
        super().__init__("not_found", "fact not found")


def check_quantity(quote: str, quantity: Quantity) -> None:
    """Raises `InvalidAssertion` (`quantity_not_in_quote`) unless the quantity's number occurs
    in the quote (the number rule of the grounding check)."""
    shown = format(abs(Decimal(repr(quantity.value))), "f")
    if not number_occurs(Decimal(repr(quantity.value)), grounds([quote])):
        raise InvalidAssertion(
            "quantity_not_in_quote", f"the quantity's number {shown} does not occur in the quote"
        )


_SELECT = """
    SELECT f.assertion_id, f.investigation_id, f.created_at, a.value_json
    FROM fact f JOIN assertion a ON a.id = f.assertion_id
"""
_FILTER = """
    WHERE (CAST(:company AS uuid) IS NULL OR a.subject_company_id = :company)
      AND (CAST(:step AS text) IS NULL OR f.step = :step)
      AND (CAST(:investigation AS uuid) IS NULL OR f.investigation_id = :investigation)
"""


def _build(connection: Connection, row: Any) -> Fact:
    assertion = get_assertion(connection, row.assertion_id)
    assert assertion is not None
    value = FactValue.model_validate(row.value_json)
    return Fact(
        id=row.assertion_id,
        investigation_id=row.investigation_id,
        step=value.step,
        status=value.status,
        statement=value.statement,
        quantity=value.quantity,
        period=value.period,
        created_at=row.created_at,
        assertion=assertion,
    )


def get_fact(connection: Connection, fact_id: uuid.UUID) -> Fact | None:
    row = connection.execute(
        text(f"{_SELECT} WHERE f.assertion_id = :id"),
        {"id": fact_id},
    ).one_or_none()
    return None if row is None else _build(connection, row)


def list_facts(
    connection: Connection,
    *,
    company_id: uuid.UUID | None = None,
    step: FactStep | None = None,
    investigation_id: uuid.UUID | None = None,
    limit: int,
    offset: int,
) -> tuple[list[Fact], int]:
    """Facts oldest first. A company's are those whose subject it is."""
    params: dict[str, Any] = {
        "company": company_id,
        "step": step,
        "investigation": investigation_id,
        "limit": limit,
        "offset": offset,
    }
    total = connection.execute(
        text(
            f"SELECT count(*) FROM fact f JOIN assertion a ON a.id = f.assertion_id {_FILTER}"  # noqa: S608 (constant fragment)
        ),
        params,
    ).scalar_one()
    rows = connection.execute(
        text(
            f"{_SELECT} {_FILTER} ORDER BY f.created_at, f.assertion_id LIMIT :limit OFFSET :offset"
        ),
        params,
    ).all()
    return [_build(connection, row) for row in rows], total


class Facts:
    """The write side: record a Fact, audited, in one transaction."""

    def __init__(self, engine: Engine, archive: Archive, actor: Actor) -> None:
        self._engine = engine
        self._assertions = Assertions(engine, archive, actor)
        self._actor = actor

    def create(self, request: FactCreate, *, extractor_version: str = "manual") -> FactRecorded:
        value = request.value()
        assertion_request = AssertionCreate(
            subject_company_id=request.subject_company_id,
            predicate=FACT_PREDICATE,
            value_json=value.model_dump(mode="json", exclude_none=True),
            source_version_id=request.source_version_id,
            quote=request.quote,
            span_start=request.span_start,
            span_end=request.span_end,
            page_or_anchor=request.page_or_anchor,
            event_start=request.event_start,
            event_end=request.event_end,
            epistemic_type=request.epistemic_type,
            parser_version=request.parser_version,
        )
        with self._engine.begin() as connection:
            if (
                request.investigation_id is not None
                and not connection.execute(
                    text("SELECT EXISTS (SELECT FROM investigation WHERE id = :id)"),
                    {"id": request.investigation_id},
                ).scalar_one()
            ):
                raise InvalidAssertion(
                    "unknown_investigation", f"investigation {request.investigation_id} not found"
                )
            # The Assertion's own checks (company, version, parse, exact span) come first; a
            # refusal anywhere rolls the whole transaction back.
            assertion = self._assertions.create_within(
                connection, assertion_request, extractor_version=extractor_version
            ).assertion
            if value.quantity is not None:
                check_quantity(request.quote, value.quantity)
            connection.execute(
                text(
                    "INSERT INTO fact (assertion_id, investigation_id, step, status)"
                    " VALUES (:id, :investigation, :step, :status)"
                ),
                {
                    "id": assertion.id,
                    "investigation": request.investigation_id,
                    "step": value.step,
                    "status": value.status,
                },
            )
            fact = get_fact(connection, assertion.id)
            assert fact is not None
            event = record(
                connection,
                self._actor,
                "fact.created",
                entity_type="fact",
                entity_id=str(fact.id),
                new_hash=content_hash(fact.model_dump(mode="json")),
            )
        return FactRecorded(fact=fact, audit_event_id=event.id)
