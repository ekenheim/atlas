"""The research bank template's bank configuration (memory-quality ticket 05).

The template file is checked against the bank-template schema Hindsight 0.10.2 served
(`spikes/hindsight/rerun-0.10.2/bank_templates/01-schema.json`), and its `layer` label group
against the Claim layer taxonomy (`atlas.claims.LAYERS`), so the two vocabularies can't drift.
"""

import json
from pathlib import Path
from typing import Any, cast

from jsonschema.validators import validator_for

from atlas.bank_template import BankTemplate
from atlas.claims import LAYERS

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "configs" / "hindsight" / "bank-template.json"
SCHEMA_0102 = REPO / "spikes" / "hindsight" / "rerun-0.10.2" / "bank_templates" / "01-schema.json"


def recorded_schema() -> dict[str, Any]:
    recording = json.loads(SCHEMA_0102.read_text(encoding="utf-8"))
    return cast(dict[str, Any], recording["response"]["body"])


def bank() -> dict[str, Any]:
    return cast(dict[str, Any], BankTemplate.load(TEMPLATE).manifest["bank"])


def layer_group() -> dict[str, Any]:
    groups = cast(list[dict[str, Any]], bank()["entity_labels"])
    [group] = [g for g in groups if g["key"] == "layer"]
    return group


def test_the_manifest_validates_against_the_recorded_0_10_2_schema() -> None:
    schema = recorded_schema()
    manifest = BankTemplate.load(TEMPLATE).manifest
    validator = validator_for(schema)(schema)

    errors = [f"{list(e.absolute_path)}: {e.message}" for e in validator.iter_errors(manifest)]

    assert errors == []
    # The schema allows unknown fields, so a misspelt one would pass; every field the
    # template sets must be one the schema names.
    defs = cast(dict[str, Any], schema["$defs"])
    assert set(bank()) <= set(defs["BankTemplateConfig"]["properties"])
    for group in cast(list[dict[str, Any]], bank()["entity_labels"]):
        assert set(group) <= set(defs["LabelGroup"]["properties"])
        for value in cast(list[dict[str, Any]], group["values"]):
            assert set(value) <= set(defs["LabelValue"]["properties"])


def test_the_layer_label_values_are_the_claim_layer_taxonomy() -> None:
    group = layer_group()

    assert [v["value"] for v in group["values"]] == [layer.name for layer in LAYERS]
    assert [v["description"] for v in group["values"]] == [layer.covers for layer in LAYERS]


def test_the_layer_group_is_optional_allows_several_values_and_writes_tags() -> None:
    group = layer_group()

    assert (group["type"], group["optional"], group["tag"]) == ("multi-values", True, True)
    assert group["description"]


def test_the_missions_say_what_to_ignore_and_stand_alone() -> None:
    config = bank()
    retain = cast(str, config["retain_mission"])
    observations = cast(str, config["observations_mission"])

    # The retain mission has an ignore list and asks for attribution (finding 5).
    for phrase in (
        "Ignore",
        "safe-harbor",
        "certifications",
        "exhibit lists",
        "signature blocks",
        "names no product, counterparty",
        "who made it",
    ):
        assert phrase in retain, phrase
    # The observations mission replaces Hindsight's built-in rules, so it restates the ones
    # Atlas needs (durable, specific, changes dated, contradictions kept) and adds its own.
    for phrase in (
        "durable, specific",
        "with both dates or periods",
        "unit",
        "who supplies or depends on whom",
        "keep both sides",
        "not corroboration",
    ):
        assert phrase in observations, phrase
