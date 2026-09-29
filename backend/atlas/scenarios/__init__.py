"""Scenarios (spec Phase 5 "Scenario", §8.2; ticket 19): deterministic low/base/high exposure
scenarios attached to a Hypothesis version.

`model` is the pure scenario function (the assumption table, the lines, the ±20% sensitivity,
canonical hashed outputs); `sources` checks an assumption table's sources against the as-of
data (XBRL observations, Assertions); `service` stores and reads scenarios; `analyst` turns
the Financial Analyst's proposal into assumption tables.
"""

from atlas.scenarios.model import (
    CASES,
    INPUT_NAMES,
    INPUT_SPECS,
    INPUTS,
    LINE_NAMES,
    MODEL_VERSION,
    AssertionSource,
    AssumptionTable,
    EstimatedInput,
    InputName,
    InputSpec,
    LineName,
    LineResult,
    MissingInput,
    ScenarioInput,
    ScenarioOutputs,
    SensitivityRow,
    SourcedInput,
    XbrlSource,
    canonical_json,
    compute,
    outputs_json,
    outputs_sha256,
)

__all__ = [
    "CASES",
    "INPUTS",
    "INPUT_NAMES",
    "INPUT_SPECS",
    "LINE_NAMES",
    "MODEL_VERSION",
    "AssertionSource",
    "AssumptionTable",
    "EstimatedInput",
    "InputName",
    "InputSpec",
    "LineName",
    "LineResult",
    "MissingInput",
    "ScenarioInput",
    "ScenarioOutputs",
    "SensitivityRow",
    "SourcedInput",
    "XbrlSource",
    "canonical_json",
    "compute",
    "outputs_json",
    "outputs_sha256",
]
