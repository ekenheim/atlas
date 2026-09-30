"""The research roles follow the supply-chain bottleneck method (docs/decisions.md, "Research
roles follow the supply-chain bottleneck method"): a structural check that each role's current
prompt carries the method's key sections. It checks the committed text only; whether a model
follows it is measured by the evaluation set, not here."""

from typing import Any

import pytest

from atlas.roles import Role
from atlas.roles.editor import EDITOR, HYPOTHESIS_EDITOR
from atlas.roles.investigator import INVESTIGATOR
from atlas.roles.scout import SCOUT
from atlas.roles.skeptic import CHECKLIST_NAMES, SKEPTIC, SKEPTIC_PLAN

# Each role, the prompt version that introduced the method, and phrases its text must hold.
EXPECTED: list[tuple[Role[Any, Any], str, int, tuple[str, ...]]] = [
    (
        SCOUT,
        "scout",
        2,
        (
            "Hunt for bottlenecks, layer by layer",
            "demand:",
            "hardware:",
            "components:",
            "sub-components:",
            "feedstock and process equipment:",
            "who chokes it",
            "single or sole source",
            "lead times",
            "qualification",
            "InP",
            "GaAs",
            "indium",
            "gallium",
            "germanium",
            "MOCVD",
            "export controls",
            "Don't write generic company news queries",
        ),
    ),
    (
        INVESTIGATOR,
        "investigator",
        3,  # v3: a company's own bottleneck facts, the bottleneck predicates (pilot-fixes 03)
        (
            "Atlas hunts supply-chain bottlenecks",
            "who supplies whom",
            "second sourcing",
            "capacity, allocation and lead times",
            "qualification and design wins",
            "feedstock and equipment dependencies",
            "A company's own statements",
            "`capacity_constrained`",
            "`sole_sources`",
            "`vertically_integrates`",
            "`qualified_for`",
            "Growing demand alone is not a constraint",
            "A list item or a sentence fragment without the company",
            "exactly one name from `request.predicates`",
            "copied exactly, character for character",
        ),
    ),
    (
        SKEPTIC_PLAN,
        "skeptic-plan",
        2,
        (
            "bear case",
            "technology transitions",
            "VCSEL",
            "silicon photonics",
            "co-packaged",
            "new entrants",
            "inventory",
            "customer_concentration",
            "at-the-market",
            "standing falsifier",
        ),
    ),
    (
        SKEPTIC,
        "skeptic",
        2,
        (
            "bear case",
            "technology transitions",
            "VCSEL",
            "silicon photonics",
            "co-packaged",
            "new entrants",
            "inventory",
            "customer_concentration",
            "at-the-market",
            "standing falsifier",
            "copied exactly, character for character",
        ),
    ),
    (
        EDITOR,
        "editor",
        3,
        (
            "the bottleneck layer",
            "the chokepoint",
            "the mechanism",
            "capacity relief",
            "dilution or financing",
            "never cite a lead ID",
        ),
    ),
    (
        HYPOTHESIS_EDITOR,
        "editor-hypothesis",
        3,
        (
            "the bottleneck layer",
            "the chokepoint",
            "the mechanism",
            "<bottleneck layer>: <chokepoint> - <mechanism>",
            "Always include capacity relief",
            "dilution or financing",
        ),
    ),
]


@pytest.mark.parametrize(
    ("role", "name", "version", "phrases"), EXPECTED, ids=[e[1] for e in EXPECTED]
)
def test_each_research_role_prompt_carries_the_bottleneck_method(
    role: Role[Any, Any],
    name: str,
    version: int,
    phrases: tuple[str, ...],
) -> None:
    assert (role.prompt.name, role.prompt.version) == (name, version)
    text = " ".join(role.prompt.text.split())  # the prompt files wrap lines
    missing = [phrase for phrase in phrases if phrase not in text]
    assert missing == []


@pytest.mark.parametrize("role", [SKEPTIC, SKEPTIC_PLAN], ids=["skeptic", "skeptic-plan"])
def test_the_skeptic_prompts_read_every_bear_checklist_item(role: Role[Any, Any]) -> None:
    assert [n for n in CHECKLIST_NAMES if f"`{n}`" not in role.prompt.text] == []
