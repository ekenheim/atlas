"""The bear checks' answer (Chokepoint Watch ticket W4): one record per check."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

type CheckKey = Literal[
    "dilution",
    "shelf_or_atm",
    "gaap_gross_margin",
    "customer_concentration",
    "going_concern",
    "net_cash",
]
type CheckStatus = Literal["flag", "clear", "unknown"]

CHECK_KEYS: tuple[CheckKey, ...] = (
    "dilution",
    "shelf_or_atm",
    "gaap_gross_margin",
    "customer_concentration",
    "going_concern",
    "net_cash",
)


class BearCheckSource(BaseModel):
    """What a check rests on: XBRL observations (`observation_id`, read at
    `GET /financial-observations/{id}`), or a Source Version with the span of the sentence it
    quotes (`GET /source-versions/{id}/content?kind=parsed&parser_version=` at the offsets, in
    code points) or, for a filing the ledger holds, the Source Version alone."""

    kind: Literal["financial_observation", "source_version"]
    observation_id: uuid.UUID | None = None
    concept: str | None = None  # the observation's `taxonomy:concept`
    period_end: str | None = None
    value: str | None = None
    source_version_id: uuid.UUID | None = None
    form_type: str | None = None
    available_at: datetime | None = None
    parser_version: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote: str | None = None


class BearCheck(BaseModel):
    key: CheckKey
    status: CheckStatus = Field(
        description="`flag`: the check found what a bear looks for; `clear`: it looked and found"
        " none; `unknown`: Atlas does not hold what the check needs (never `clear`)"
    )
    value: dict[str, Any] | None = Field(
        description="the numbers or matches behind the status; null when unknown"
    )
    basis: str = Field(description="in words: what was compared or read, and the rule applied")
    sources: list[BearCheckSource]


class BearChecks(BaseModel):
    company_id: uuid.UUID
    as_of: datetime
    checks: list[BearCheck]
