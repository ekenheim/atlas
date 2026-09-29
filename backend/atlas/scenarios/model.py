"""The scenario model (spec Phase 5 "Scenario"; §8.2): a pure, deterministic function of an
assumption table. No LLM, no database, no clock.

**Inputs.** An assumption table is one company's exposure through one product, in one
currency. Each input has a low, base and high value and is labelled:

- `sourced`: an XBRL observation (`xbrl_observation`) or an Assertion span (`assertion`);
- `estimated`: with its written basis;
- `missing`: no value (and never an invented one).

A value with neither a source nor a basis doesn't validate: no source-free figure passes.

**Lines** (§8.2, with the component's share of the downstream bill of materials, ticket 12's
"BOM share"):

    component_price           = downstream_unit_price x bom_share
    incremental_revenue       = addressable_units x company_share x component_price
    incremental_contribution  = incremental_revenue x operating_margin
    scenario_enterprise_value = incremental_contribution x ev_multiple
    net_debt                  = total_debt - cash
    illustrative_equity_value = scenario_enterprise_value - net_debt
    equity_value_per_share    = illustrative_equity_value / diluted_shares
    revenue_exposure          = incremental_revenue / reported_revenue

A line with a missing input (directly or through another line) is blocked: it has no value
and names the missing inputs.

**Cases and sensitivity.** Every line is computed for the low, base and high cases, and for
each present input of the base case moved by -20% and +20% alone (a fraction is kept within
its bounds and marked `capped`).

**Determinism.** Arithmetic is `Decimal` in a fixed context; each line is rounded half-even
to 6 decimal places; every number is written as a plain decimal string. The outputs are
canonical JSON (sorted keys, fixed separators, UTF-8), so identical inputs give
byte-identical outputs, and their SHA-256 is the outputs' hash.
"""

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from decimal import ROUND_HALF_EVEN, Context, Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MODEL_VERSION = "scenario-v1"

InputName = Literal[
    "addressable_units",
    "company_share",
    "downstream_unit_price",
    "bom_share",
    "operating_margin",
    "ev_multiple",
    "reported_revenue",
    "total_debt",
    "cash",
    "diluted_shares",
]
LineName = Literal[
    "component_price",
    "incremental_revenue",
    "incremental_contribution",
    "scenario_enterprise_value",
    "net_debt",
    "illustrative_equity_value",
    "equity_value_per_share",
    "revenue_exposure",
]
CaseName = Literal["low", "base", "high"]
CASES: tuple[CaseName, ...] = ("low", "base", "high")
# What an input measures: `money` is in the table's currency, `shares` a share count.
Measure = Literal["count", "fraction", "margin", "money", "multiple", "shares"]

_ZERO, _ONE = Decimal(0), Decimal(1)
_BOUNDS: dict[Measure, tuple[Decimal | None, Decimal | None]] = {
    "count": (_ZERO, None),
    "fraction": (_ZERO, _ONE),
    "margin": (-_ONE, _ONE),
    "money": (_ZERO, None),
    "multiple": (_ZERO, None),
    "shares": (_ZERO, None),
}


class InputSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: InputName
    measure: Measure
    meaning: str
    xbrl: bool  # whether an XBRL fact can source it (a currency amount or a share count)
    positive: bool = False  # a divisor: must be above zero


INPUTS: tuple[InputSpec, ...] = (
    InputSpec(
        name="addressable_units",
        measure="count",
        meaning="incremental addressable units of the downstream product per year",
        xbrl=False,
    ),
    InputSpec(
        name="company_share",
        measure="fraction",
        meaning="the company's feasible share of those units (0-1)",
        xbrl=False,
    ),
    InputSpec(
        name="downstream_unit_price",
        measure="money",
        meaning="the realized price of one downstream unit, in the table's currency",
        xbrl=False,
    ),
    InputSpec(
        name="bom_share",
        measure="fraction",
        meaning="the company's component's share of the downstream bill of materials (0-1)",
        xbrl=False,
    ),
    InputSpec(
        name="operating_margin",
        measure="margin",
        meaning="the incremental operating margin (-1 to 1)",
        xbrl=False,
    ),
    InputSpec(
        name="ev_multiple",
        measure="multiple",
        meaning="enterprise value per unit of annual incremental operating contribution",
        xbrl=False,
    ),
    InputSpec(
        name="reported_revenue",
        measure="money",
        meaning="the company's reported annual revenue, to size the exposure",
        xbrl=True,
        positive=True,
    ),
    InputSpec(
        name="total_debt",
        measure="money",
        meaning="the company's debt (with cash, net debt)",
        xbrl=True,
    ),
    InputSpec(
        name="cash",
        measure="money",
        meaning="the company's cash and cash equivalents",
        xbrl=True,
    ),
    InputSpec(
        name="diluted_shares",
        measure="shares",
        meaning="the company's diluted share count",
        xbrl=True,
        positive=True,
    ),
)
INPUT_SPECS: dict[InputName, InputSpec] = {spec.name: spec for spec in INPUTS}
INPUT_NAMES: tuple[InputName, ...] = tuple(spec.name for spec in INPUTS)

# --- the assumption table ---------------------------------------------------------------------


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class XbrlSource(_Model):
    type: Literal["xbrl_observation"]
    observation_id: uuid.UUID


class AssertionSource(_Model):
    type: Literal["assertion"]
    assertion_id: uuid.UUID


Source = Annotated[XbrlSource | AssertionSource, Field(discriminator="type")]
_Value = Annotated[Decimal, Field(allow_inf_nan=False)]


class _Valued(_Model):
    low: _Value
    base: _Value
    high: _Value

    @model_validator(mode="after")
    def _ordered(self) -> "_Valued":
        if not self.low <= self.base <= self.high:
            raise ValueError("low <= base <= high must hold")
        return self

    def value(self, case: CaseName) -> Decimal:
        return {"low": self.low, "base": self.base, "high": self.high}[case]


class SourcedInput(_Valued):
    kind: Literal["sourced"]
    source: Source


class EstimatedInput(_Valued):
    kind: Literal["estimated"]
    basis: Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]


class MissingInput(_Model):
    kind: Literal["missing"]
    reason: str | None = Field(default=None, max_length=2000)


ScenarioInput = Annotated[SourcedInput | EstimatedInput | MissingInput, Field(discriminator="kind")]


class AssumptionTable(_Model):
    """One company's exposure through one product, in one currency. An input left out is
    missing."""

    company_id: uuid.UUID
    product: Annotated[str, Field(min_length=1, max_length=500, pattern=r"\S")]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    inputs: dict[InputName, ScenarioInput] = Field(default_factory=dict[InputName, ScenarioInput])

    @model_validator(mode="after")
    def _in_bounds(self) -> "AssumptionTable":
        problems: list[str] = []
        for name, each in self.inputs.items():
            if isinstance(each, MissingInput):
                continue
            spec = INPUT_SPECS[name]
            low, high = _BOUNDS[spec.measure]
            for case in CASES:
                value = each.value(case)
                if (low is not None and value < low) or (high is not None and value > high):
                    problems.append(f"{name}.{case} must be within {_range(low, high)}")
                elif spec.positive and value <= 0:
                    problems.append(f"{name}.{case} must be above 0")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def get(self, name: InputName) -> SourcedInput | EstimatedInput | None:
        each = self.inputs.get(name)
        return None if each is None or isinstance(each, MissingInput) else each

    def canonical(self) -> dict[str, Any]:
        """The table as canonical JSON values: every input named, numbers as strings."""
        inputs: dict[str, Any] = {}
        for name in INPUT_NAMES:
            each = self.inputs.get(name, MissingInput(kind="missing"))
            if isinstance(each, MissingInput):
                inputs[name] = {"kind": "missing", "reason": each.reason}
                continue
            values = {case: number(each.value(case)) for case in CASES}
            if isinstance(each, SourcedInput):
                inputs[name] = {
                    "kind": "sourced",
                    "source": each.source.model_dump(mode="json"),
                    **values,
                }
            else:
                inputs[name] = {"kind": "estimated", "basis": each.basis, **values}
        return {
            "company_id": str(self.company_id),
            "product": self.product,
            "currency": self.currency,
            "inputs": inputs,
        }

    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.canonical())).hexdigest()


def _range(low: Decimal | None, high: Decimal | None) -> str:
    return f"[{'-inf' if low is None else low}, {'inf' if high is None else high}]"


# --- the outputs --------------------------------------------------------------------------------


class LineResult(_Model):
    value: str | None  # None: blocked
    missing: list[InputName]  # the missing inputs that block it


class SensitivityRow(_Model):
    input: InputName
    change: Literal["-20%", "+20%"]
    input_value: str
    capped: bool  # a fraction kept within its bounds
    lines: dict[LineName, str | None]


class ScenarioOutputs(_Model):
    model_version: str
    assumptions_sha256: str
    currency: str
    cases: dict[CaseName, dict[LineName, LineResult]]
    sensitivity: list[SensitivityRow]


_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
_PLACES = Decimal("0.000001")
_Values = Mapping[str, Decimal]
_LINES: tuple[tuple[LineName, tuple[str, ...], Callable[[_Values], Decimal]], ...] = (
    (
        "component_price",
        ("downstream_unit_price", "bom_share"),
        lambda v: _CONTEXT.multiply(v["downstream_unit_price"], v["bom_share"]),
    ),
    (
        "incremental_revenue",
        ("addressable_units", "company_share", "component_price"),
        lambda v: _CONTEXT.multiply(
            _CONTEXT.multiply(v["addressable_units"], v["company_share"]), v["component_price"]
        ),
    ),
    (
        "incremental_contribution",
        ("incremental_revenue", "operating_margin"),
        lambda v: _CONTEXT.multiply(v["incremental_revenue"], v["operating_margin"]),
    ),
    (
        "scenario_enterprise_value",
        ("incremental_contribution", "ev_multiple"),
        lambda v: _CONTEXT.multiply(v["incremental_contribution"], v["ev_multiple"]),
    ),
    ("net_debt", ("total_debt", "cash"), lambda v: _CONTEXT.subtract(v["total_debt"], v["cash"])),
    (
        "illustrative_equity_value",
        ("scenario_enterprise_value", "net_debt"),
        lambda v: _CONTEXT.subtract(v["scenario_enterprise_value"], v["net_debt"]),
    ),
    (
        "equity_value_per_share",
        ("illustrative_equity_value", "diluted_shares"),
        lambda v: _CONTEXT.divide(v["illustrative_equity_value"], v["diluted_shares"]),
    ),
    (
        "revenue_exposure",
        ("incremental_revenue", "reported_revenue"),
        lambda v: _CONTEXT.divide(v["incremental_revenue"], v["reported_revenue"]),
    ),
)
LINE_NAMES: tuple[LineName, ...] = tuple(name for name, _, _ in _LINES)


def number(value: Decimal) -> str:
    """A plain decimal string: no exponent, no trailing zeros, no negative zero."""
    if value.is_zero():
        return "0"
    text = format(value.normalize(_CONTEXT), "f")
    return text


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


_CHANGES: tuple[tuple[Literal["-20%", "+20%"], Decimal], ...] = (
    ("-20%", Decimal("0.8")),
    ("+20%", Decimal("1.2")),
)


def _lines(values: Mapping[InputName, Decimal]) -> dict[LineName, LineResult]:
    known: dict[str, Decimal] = {name: value for name, value in values.items()}
    blocked: dict[str, list[InputName]] = {
        name: [name] for name in INPUT_NAMES if name not in values
    }
    results: dict[LineName, LineResult] = {}
    for name, needs, compute in _LINES:
        found: set[InputName] = {each for need in needs for each in blocked.get(need, [])}
        missing: list[InputName] = sorted(found)
        if missing:
            blocked[name] = missing
            results[name] = LineResult(value=None, missing=missing)
            continue
        value = _CONTEXT.quantize(compute(known), _PLACES)
        known[name] = value
        results[name] = LineResult(value=number(value), missing=[])
    return results


def compute(table: AssumptionTable) -> ScenarioOutputs:
    """Every line for the low, base and high cases, and the base case's single-input ±20%
    sensitivity (see the module)."""
    present: dict[InputName, SourcedInput | EstimatedInput] = {}
    for name in INPUT_NAMES:
        each = table.get(name)
        if each is not None:
            present[name] = each
    cases: dict[CaseName, dict[LineName, LineResult]] = {
        case: _lines({name: each.value(case) for name, each in present.items()}) for case in CASES
    }
    base: dict[InputName, Decimal] = {name: each.base for name, each in present.items()}
    sensitivity: list[SensitivityRow] = []
    for name in present:
        for change, factor in _CHANGES:
            moved = _CONTEXT.multiply(base[name], factor)
            low, high = _BOUNDS[INPUT_SPECS[name].measure]
            capped = False
            if INPUT_SPECS[name].measure in ("fraction", "margin"):
                if high is not None and moved > high:
                    moved, capped = high, True
                if low is not None and moved < low:
                    moved, capped = low, True
            lines = _lines({**base, name: moved})
            sensitivity.append(
                SensitivityRow(
                    input=name,
                    change=change,
                    input_value=number(moved),
                    capped=capped,
                    lines={line: result.value for line, result in lines.items()},
                )
            )
    return ScenarioOutputs(
        model_version=MODEL_VERSION,
        assumptions_sha256=table.sha256(),
        currency=table.currency,
        cases=cases,
        sensitivity=sensitivity,
    )


def outputs_json(outputs: ScenarioOutputs) -> bytes:
    """The outputs' canonical JSON: the bytes that are hashed and stored."""
    return canonical_json(outputs.model_dump(mode="json"))


def outputs_sha256(outputs: ScenarioOutputs) -> str:
    return hashlib.sha256(outputs_json(outputs)).hexdigest()
