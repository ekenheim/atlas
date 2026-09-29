"""The scenario math (ticket 19; spec Phase 5 "Scenario", §8.2): a pure deterministic function
of an assumption table.

Expected values are worked by hand from the §8.2 formulas (units x share x price, with the
price the downstream unit price x the BOM share; x margin; x multiple; - net debt;
/ diluted shares), never recomputed the way the code does.
"""

import hashlib
import json
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from atlas.scenarios import (
    AssumptionTable,
    compute,
    outputs_json,
    outputs_sha256,
)

COMPANY = uuid.UUID("7f1c0e0a-5b8e-4c43-9a4f-1d2b3c4d5e6f")
OBSERVATION = uuid.UUID("0b6f7a8e-2f2c-4c1d-8e8f-9a0b1c2d3e4f")
ASSERTION = uuid.UUID("5d4c3b2a-1f0e-4d9c-8b7a-6f5e4d3c2b1a")


def estimated(low: str, base: str, high: str, basis: str = "an analyst's estimate") -> Any:
    return {"kind": "estimated", "basis": basis, "low": low, "base": base, "high": high}


def xbrl(value: str) -> Any:
    return {
        "kind": "sourced",
        "source": {"type": "xbrl_observation", "observation_id": str(OBSERVATION)},
        "low": value,
        "base": value,
        "high": value,
    }


def inputs(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "addressable_units": estimated("8000000", "10000000", "12000000"),
        "company_share": {
            "kind": "sourced",
            "source": {"type": "assertion", "assertion_id": str(ASSERTION)},
            "low": "0.2",
            "base": "0.25",
            "high": "0.3",
        },
        "downstream_unit_price": estimated("900", "1000", "1100"),
        "bom_share": estimated("0.15", "0.2", "0.25"),
        "operating_margin": estimated("0.25", "0.3", "0.35"),
        "ev_multiple": estimated("15", "20", "25"),
        "reported_revenue": xbrl("5000000000"),
        "total_debt": xbrl("3000000000"),
        "cash": xbrl("1000000000"),
        "diluted_shares": xbrl("150000000"),
    }
    values.update(changes)
    return {name: value for name, value in values.items() if value is not None}


def table(**changes: Any) -> AssumptionTable:
    return AssumptionTable.model_validate(
        {
            "company_id": str(COMPANY),
            "product": "EML lasers for 800G transceivers",
            "currency": "USD",
            "inputs": inputs(**changes),
        }
    )


def case(outputs: Any, name: str) -> dict[str, str | None]:
    return {line: result.value for line, result in outputs.cases[name].items()}


def test_low_base_and_high_follow_the_8_2_transmission_with_bom_share() -> None:
    outputs = compute(table())

    assert case(outputs, "base") == {
        "component_price": "200",  # 1000 x 0.2
        "incremental_revenue": "500000000",  # 10M x 0.25 x 200
        "incremental_contribution": "150000000",  # x 0.3
        "scenario_enterprise_value": "3000000000",  # x 20
        "net_debt": "2000000000",  # 3bn - 1bn
        "illustrative_equity_value": "1000000000",  # 3bn - 2bn
        "equity_value_per_share": "6.666667",  # 1bn / 150M, half-even to 6 places
        "revenue_exposure": "0.1",  # 500M / 5bn
    }
    assert case(outputs, "low") == {
        "component_price": "135",
        "incremental_revenue": "216000000",
        "incremental_contribution": "54000000",
        "scenario_enterprise_value": "810000000",
        "net_debt": "2000000000",
        "illustrative_equity_value": "-1190000000",
        "equity_value_per_share": "-7.933333",
        "revenue_exposure": "0.0432",
    }
    assert case(outputs, "high") == {
        "component_price": "275",
        "incremental_revenue": "990000000",
        "incremental_contribution": "346500000",
        "scenario_enterprise_value": "8662500000",
        "net_debt": "2000000000",
        "illustrative_equity_value": "6662500000",
        "equity_value_per_share": "44.416667",
        "revenue_exposure": "0.198",
    }
    assert outputs.currency == "USD"
    assert outputs.model_version == "scenario-v1"


def test_a_missing_input_blocks_its_lines_and_every_line_built_on_them() -> None:
    outputs = compute(table(ev_multiple={"kind": "missing", "reason": "no multiple yet"}))

    base = outputs.cases["base"]
    for line in ("scenario_enterprise_value", "illustrative_equity_value"):
        assert (base[line].value, base[line].missing) == (None, ["ev_multiple"])
    assert base["equity_value_per_share"].value is None
    assert base["incremental_contribution"].value == "150000000"
    assert base["net_debt"].value == "2000000000"
    assert base["revenue_exposure"].value == "0.1"


def test_an_input_left_out_is_missing_and_blocked_lines_name_every_missing_input() -> None:
    outputs = compute(table(cash=None, ev_multiple=None))

    for name in ("low", "base", "high"):
        result = outputs.cases[name]["equity_value_per_share"]
        assert (result.value, result.missing) == (None, ["cash", "ev_multiple"])
        assert outputs.cases[name]["net_debt"].missing == ["cash"]
    # No sensitivity row for an input that isn't there.
    assert {row.input for row in outputs.sensitivity} == {
        "addressable_units",
        "company_share",
        "downstream_unit_price",
        "bom_share",
        "operating_margin",
        "reported_revenue",
        "total_debt",
        "diluted_shares",
    }


def test_sensitivity_moves_one_base_input_by_20_percent_at_a_time() -> None:
    outputs = compute(table())

    rows = {(row.input, row.change): row for row in outputs.sensitivity}
    assert len(rows) == 20  # 10 inputs x (-20%, +20%)
    up = rows[("ev_multiple", "+20%")]
    assert (up.input_value, up.capped) == ("24", False)
    assert up.lines["scenario_enterprise_value"] == "3600000000"  # 150M x 24
    assert up.lines["equity_value_per_share"] == "10.666667"  # (3.6bn - 2bn) / 150M
    assert up.lines["incremental_revenue"] == "500000000"  # untouched
    down = rows[("bom_share", "-20%")]
    assert down.input_value == "0.16"
    assert down.lines["component_price"] == "160"
    assert down.lines["incremental_revenue"] == "400000000"  # 10M x 0.25 x 160
    cash = rows[("cash", "+20%")]
    assert cash.lines["net_debt"] == "1800000000"  # 3bn - 1.2bn


def test_a_fraction_moved_past_its_bound_is_capped_and_marked() -> None:
    outputs = compute(table(company_share=estimated("0.8", "0.9", "0.95")))

    up = next(
        row for row in outputs.sensitivity if (row.input, row.change) == ("company_share", "+20%")
    )
    assert (up.input_value, up.capped) == ("1", True)
    assert up.lines["incremental_revenue"] == "2000000000"  # 10M x 1 x 200


def test_identical_inputs_give_byte_identical_outputs_and_the_same_hash() -> None:
    first = outputs_json(compute(table()))
    # The same table written differently: numbers vs strings, other key order, trailing zeros.
    again = AssumptionTable.model_validate(
        {
            "inputs": {
                name: value | {"low": _loose(value, "low"), "base": _loose(value, "base")}
                if value["kind"] != "missing"
                else value
                for name, value in reversed(inputs().items())
            },
            "currency": "USD",
            "product": "EML lasers for 800G transceivers",
            "company_id": str(COMPANY),
        }
    )
    second = outputs_json(compute(again))

    assert first == second
    assert outputs_sha256(compute(again)) == hashlib.sha256(first).hexdigest()
    # Canonical JSON: sorted keys, no whitespace, numbers as strings.
    assert (
        first
        == json.dumps(
            json.loads(first), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    )
    assert '"equity_value_per_share":{"missing":[],"value":"6.666667"}' in first.decode()


def _loose(value: dict[str, Any], key: str) -> Any:
    """The same number, written as a JSON number or with trailing zeros."""
    text = str(value[key])
    return int(text) if text.isdigit() else f"{text}000"


def test_a_different_input_changes_the_outputs_hash() -> None:
    assert outputs_sha256(compute(table())) != outputs_sha256(
        compute(table(ev_multiple=estimated("15", "21", "25")))
    )
    assert table().sha256() != table(ev_multiple=estimated("15", "21", "25")).sha256()


@pytest.mark.parametrize(
    "value",
    [
        # A figure with no source and no basis.
        {"kind": "estimated", "low": "1", "base": "2", "high": "3"},
        {"kind": "estimated", "basis": "  ", "low": "1", "base": "2", "high": "3"},
        {"kind": "sourced", "low": "1", "base": "2", "high": "3"},
        {"low": "1", "base": "2", "high": "3"},
        # A source that isn't one.
        {
            "kind": "sourced",
            "source": {"type": "web_page", "url": "https://example.test"},
            "low": "1",
            "base": "2",
            "high": "3",
        },
        # A missing input with a value.
        {"kind": "missing", "reason": None, "base": "2"},
        # An estimate without all three cases, or out of order.
        {"kind": "estimated", "basis": "a guess", "base": "2"},
        {"kind": "estimated", "basis": "a guess", "low": "3", "base": "2", "high": "4"},
        {"kind": "estimated", "basis": "a guess", "low": "NaN", "base": "2", "high": "4"},
    ],
)
def test_no_source_free_figure_passes_validation(value: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        table(addressable_units=value)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("company_share", estimated("0.5", "0.9", "1.1")),
        ("bom_share", estimated("-0.1", "0.2", "0.3")),
        ("operating_margin", estimated("-1.5", "0.2", "0.3")),
        ("diluted_shares", estimated("0", "1", "2")),
        ("addressable_units", estimated("-1", "1", "2")),
    ],
)
def test_values_outside_an_input_s_bounds_are_refused(name: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        table(**{name: value})


def test_the_currency_is_a_three_letter_code() -> None:
    with pytest.raises(ValidationError):
        AssumptionTable.model_validate(
            {"company_id": str(COMPANY), "product": "lasers", "currency": "usd", "inputs": {}}
        )


def test_an_empty_table_computes_to_every_line_blocked() -> None:
    outputs = compute(
        AssumptionTable.model_validate(
            {"company_id": str(COMPANY), "product": "lasers", "currency": "EUR"}
        )
    )

    assert all(result.value is None for result in outputs.cases["base"].values())
    assert outputs.cases["base"]["component_price"].missing == [
        "bom_share",
        "downstream_unit_price",
    ]
    assert outputs.sensitivity == []
