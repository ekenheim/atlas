"""The bear checks' answer (Chokepoint Watch tickets W4 and W8): one record per check.

Each check is its own typed record, told apart by `key` (a discriminated union): the value it
carries has the shape of its key and no other. A check that is `unknown` says why in
`unknown_reason`, one of a closed list, and every check has a `summary`, one plain sentence for
the owner's pages (no codes). `basis` stays the longer account in words, for the agent and the
audit.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import BaseModel, Field, model_validator

type CheckKey = Literal[
    "dilution",
    "shelf_or_atm",
    "gaap_gross_margin",
    "customer_concentration",
    "going_concern",
    "net_cash",
]
type CheckStatus = Literal["flag", "clear", "unknown"]
type UnknownReason = Literal[
    "form_not_collected",  # the filing the check reads is not one Atlas ingests, or holds none
    "no_xbrl",  # the XBRL figures the check needs are not there
    "not_comparable",  # there is no earlier period to compare with
    "no_statement",  # the report is read whole and says nothing the check can use
    "partial_parse",  # the report was only partly read, so silence proves nothing
    "stale_figure",  # the latest figure is more than fifteen months old
    "split_suspected",  # the share count moved by a split's ratio
    "several_share_classes",  # the counts of several share classes cannot be told apart
    "ambiguous_debt_tags",  # the debt tags do not add up to one debt
    "debt_not_tagged",  # no total debt, or not both current and noncurrent debt, is tagged
    "no_parsed_text",  # the filing has no parsed text
    "not_english",  # the filing is not in English
]

CHECK_KEYS: tuple[CheckKey, ...] = (
    "dilution",
    "shelf_or_atm",
    "gaap_gross_margin",
    "customer_concentration",
    "going_concern",
    "net_cash",
)

type Amount = int | float

# --- what an unknown says -------------------------------------------------------------------

_NOT_KNOWN: dict[UnknownReason, str] = {
    "form_not_collected": "the company's filings of this kind are not collected",
    "no_xbrl": "the company's financial data has no figure for it",
    "not_comparable": "there is no earlier period to compare with",
    "no_statement": "the report says nothing the check can use",
    "partial_parse": "the latest report could only be partly read, and the part read has nothing",
    "stale_figure": "the latest figure is more than 15 months old",
    "split_suspected": "the share count moved by a split's ratio, which is not new shares",
    "several_share_classes": "the company has several share classes and their counts cannot be"
    " told apart",
    "ambiguous_debt_tags": "the company's debt is tagged in a way that cannot be added up",
    "debt_not_tagged": "the company's debt is not tagged in its financial data",
    "no_parsed_text": "the latest report has no readable text",
    "not_english": "the latest report is not in English",
}
# Where the generic wording would mislead, the check's own.
_NOT_KNOWN_FOR: dict[tuple[CheckKey, UnknownReason], str] = {
    ("shelf_or_atm", "form_not_collected"): "the company's shelf filings are not collected",
    ("customer_concentration", "form_not_collected"): "the company's annual report is not"
    " collected",
    ("going_concern", "form_not_collected"): "the company's periodic reports are not collected",
    ("dilution", "no_xbrl"): "no share count is in the company's financial data",
    ("dilution", "not_comparable"): "there is no share count from a year earlier to compare with",
    ("dilution", "stale_figure"): "the latest share count is more than 15 months old",
    ("gaap_gross_margin", "no_xbrl"): "no quarterly revenue and gross profit are in the"
    " company's financial data",
    ("gaap_gross_margin", "not_comparable"): "there are not four comparable quarters, this year"
    " and a year earlier",
    ("gaap_gross_margin", "stale_figure"): "the latest quarter reported is more than 15 months old",
    ("customer_concentration", "no_statement"): "the annual report does not say that any"
    " customer is below 25% of revenue, or that none is above a threshold",
    ("customer_concentration", "partial_parse"): "the annual report could only be partly read,"
    " and the part read names no large customer",
    ("going_concern", "partial_parse"): "the latest report could only be partly read, and the"
    " part read has no going-concern doubt",
    ("net_cash", "no_xbrl"): "no cash balance is in the company's financial data",
    ("net_cash", "stale_figure"): "the latest balance sheet with cash is more than 15 months old",
}


def unknown_summary(key: CheckKey, reason: UnknownReason) -> str:
    """The owner's sentence for a check Atlas cannot answer: `Not known: ...`."""
    return f"Not known: {_NOT_KNOWN_FOR.get((key, reason), _NOT_KNOWN[reason])}."


# --- sources --------------------------------------------------------------------------------


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


# --- the values, one shape for each key -----------------------------------------------------


class DilutionValue(BaseModel):
    concept: str = Field(description="the share count compared, `taxonomy:concept`")
    shares: Amount
    shares_as_of: str = Field(description="the date of that count")
    shares_year_earlier: Amount
    year_earlier_as_of: str
    growth_pct: float = Field(description="the change over the year, in percent")


class ShelfFiling(BaseModel):
    form: str
    available_at: str = Field(description="when it became public, ISO 8601")
    source_version_id: uuid.UUID
    title: str


class ShelfOrAtmValue(BaseModel):
    filings: list[ShelfFiling] = Field(description="newest first")


class MarginQuarter(BaseModel):
    period_end: str
    revenue: Amount
    gross_profit: Amount
    margin_pct: float | None


class GrossMarginValue(BaseModel):
    unit: str
    ttm_margin_pct: float = Field(description="gross margin of the trailing four quarters")
    prior_ttm_margin_pct: float | None = Field(description="the four quarters a year before")
    change_points: float | None = Field(description="the first less the second, in points")
    quarters: list[MarginQuarter] = Field(description="the trailing four, oldest first")


class DocumentRef(BaseModel):
    """The filing a text check read."""

    source_version_id: uuid.UUID
    form: str


class CustomerMatch(BaseModel):
    percents: list[float]
    current_percent: float
    lower_bound: bool = Field(description="the sentence says `more than`, not the share itself")
    char_start: int
    char_end: int
    quote: str


class TopCustomersShare(BaseModel):
    """The share of the largest customers together, apart from any one customer's."""

    percents: list[float]
    current_percent: float
    char_start: int
    char_end: int
    quote: str


class CustomerConcentrationValue(BaseModel):
    document: DocumentRef
    current_percent: float | None = Field(description="the largest customer's current share")
    matches: list[CustomerMatch]
    top_customers_share: list[TopCustomersShare]
    no_customer_above: list[float] = Field(
        description="thresholds the report says no customer exceeded"
    )


class GoingConcernValue(BaseModel):
    document: DocumentRef
    sentences: int = Field(description="sentences naming substantial doubt")
    negated_sentences: int = Field(description="sentences saying there is none")
    hedged_only: bool = Field(description="every such sentence is conditional")


class NetCashValue(BaseModel):
    unit: str
    as_of_balance_sheet: str
    net_cash: Amount = Field(description="negative: net debt")
    cash: Amount
    short_term_investments: Amount | None
    debt: Amount
    debt_concepts: list[str]


# --- the checks -----------------------------------------------------------------------------


class _Check(BaseModel):
    KEY: ClassVar[CheckKey]

    status: CheckStatus = Field(
        description="`flag`: the check found what a bear looks for; `clear`: it looked and found"
        " none; `unknown`: Atlas does not hold what the check needs (never `clear`)"
    )
    unknown_reason: UnknownReason | None = Field(
        description="why the check is unknown; null for `flag` and `clear`"
    )
    summary: str = Field(
        description="one plain sentence for the owner, e.g. `Shares outstanding rose 14% in a"
        " year.` or `Not known: the company's shelf filings are not collected.`"
    )
    basis: str = Field(description="in words: what was compared or read, and the rule applied")
    sources: list[BearCheckSource]

    @model_validator(mode="after")
    def _a_reason_exactly_when_unknown(self) -> Self:
        if (self.status == "unknown") != (self.unknown_reason is not None):
            raise ValueError("unknown_reason is set when the status is unknown, and only then")
        return self

    @classmethod
    def not_known(
        cls,
        reason: UnknownReason,
        basis: str,
        *,
        value: Any = None,
        sources: list[BearCheckSource] | None = None,
    ) -> Self:
        """The check Atlas cannot answer, with its reason and the owner's sentence for it."""
        fields: dict[str, Any] = {
            "key": cls.KEY,
            "status": "unknown",
            "unknown_reason": reason,
            "summary": unknown_summary(cls.KEY, reason),
            "basis": basis,
            "value": value,
            "sources": sources or [],
        }
        return cls(**fields)


class DilutionCheck(_Check):
    KEY: ClassVar[CheckKey] = "dilution"
    key: Literal["dilution"]
    value: DilutionValue | None = Field(description="null when unknown")


class ShelfOrAtmCheck(_Check):
    KEY: ClassVar[CheckKey] = "shelf_or_atm"
    key: Literal["shelf_or_atm"]
    value: ShelfOrAtmValue | None = Field(description="null when unknown")


class GaapGrossMarginCheck(_Check):
    KEY: ClassVar[CheckKey] = "gaap_gross_margin"
    key: Literal["gaap_gross_margin"]
    value: GrossMarginValue | None = Field(description="null when unknown")


class CustomerConcentrationCheck(_Check):
    KEY: ClassVar[CheckKey] = "customer_concentration"
    key: Literal["customer_concentration"]
    value: CustomerConcentrationValue | None = Field(
        description="null when no report was read; kept when a partly read report is unknown"
    )


class GoingConcernCheck(_Check):
    KEY: ClassVar[CheckKey] = "going_concern"
    key: Literal["going_concern"]
    value: GoingConcernValue | None = Field(
        description="null when no report was read; kept when a partly read report is unknown"
    )


class NetCashCheck(_Check):
    KEY: ClassVar[CheckKey] = "net_cash"
    key: Literal["net_cash"]
    value: NetCashValue | None = Field(description="null when unknown")


BearCheck = Annotated[
    DilutionCheck
    | ShelfOrAtmCheck
    | GaapGrossMarginCheck
    | CustomerConcentrationCheck
    | GoingConcernCheck
    | NetCashCheck,
    Field(discriminator="key"),
]


class BearChecks(BaseModel):
    company_id: uuid.UUID
    as_of: datetime
    checks: list[BearCheck] = Field(description="the six checks, in the order of `CheckKey`")
    flagged: list[CheckKey] = Field(description="the keys of the checks that are `flag`")
    unknown: list[CheckKey] = Field(description="the keys of the checks that are `unknown`")
