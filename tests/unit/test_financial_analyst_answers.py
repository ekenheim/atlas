"""The Financial Analyst's answer, read in the forms MiniMax writes it (bottleneck-argument
ticket 07).

Seam: the role's response model, which the caller validates every answer with. The two
inputs below are the shapes recorded on pilot question 2 (0.5.3, 2026-10-07), whose answers
were quarantined for them; their IDs and wording are made up.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from atlas.roles.financial_analyst import FINANCIAL_ANALYST, ScenarioProposal

SOURCED = {
    "name": "reported_revenue",
    "kind": "sourced",
    "observation_id": "obs-1",
    "basis": None,
    "low": "100",
    "base": "100",
    "high": "100",
}


def proposal(*inputs: dict[str, Any]) -> ScenarioProposal:
    return ScenarioProposal.model_validate(
        {
            "scenarios": [
                {
                    "company_id": "c-1",
                    "product": "indium phosphide substrates",
                    "currency": "USD",
                    "inputs": list(inputs),
                }
            ]
        }
    )


def test_a_kind_naming_an_assertion_with_its_id_is_sourced() -> None:
    # The first recorded shape: `kind: "assertion"`, the Assertion's ID given, an optional
    # field left out.
    [scenario] = proposal(
        SOURCED,
        {
            "name": "company_share",
            "kind": "assertion",
            "assertion_id": "a-1",
            "basis": "the company's stated share",
            "low": "0.40",
            "base": "0.40",
            "high": "0.50",
        },
    ).scenarios
    share = scenario.inputs[1]
    assert (share.kind, share.assertion_id, share.observation_id) == ("sourced", "a-1", None)


def test_a_kind_naming_the_id_field_is_read_the_same() -> None:
    # The second recorded shape: `kind: "assertion_id"`.
    [scenario] = proposal(
        {"name": "company_share", "kind": "assertion_id", "assertion_id": "a-2", "base": "0.4"}
    ).scenarios
    [share] = scenario.inputs
    assert (share.kind, share.assertion_id, share.low, share.high) == ("sourced", "a-2", None, None)


def test_a_kind_naming_a_source_it_does_not_give_is_missing() -> None:
    [scenario] = proposal(
        {"name": "reported_revenue", "kind": "observation", "base": "100"}
    ).scenarios
    assert scenario.inputs[0].kind == "missing"


def test_an_unknown_kind_is_still_invalid() -> None:
    with pytest.raises(ValidationError):
        proposal({**SOURCED, "kind": "guess"})


def test_the_cap_leaves_room_for_a_full_table() -> None:
    # 4,096 cut question 2's first answer off mid-table.
    assert FINANCIAL_ANALYST.max_output_tokens == 6144
