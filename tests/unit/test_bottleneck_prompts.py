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
        3,  # v3: a filing phrase per query for EDGAR full-text search (pilot fix 12)
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
            "EDGAR full-text search",
            "`filing_phrase`",
            "`InP substrates`",
        ),
    ),
    (
        INVESTIGATOR,
        "investigator",
        # v3: a company's own bottleneck facts, the bottleneck predicates (pilot-fixes 03);
        # v4: a company object outside the known companies, by name (pilot-fixes 05);
        # v5: the layer from the quote's named object, no generic Claims, one clause (09)
        5,
        (
            "the layer of the object the quote names",
            "never from `request.question`",
            "generic sentences are not Claims",
            "need the input or product named in the quote",
            "some of our suppliers are our sole sources for certain materials, equipment and"
            " components",
            "We purchase InP substrates from a limited number of suppliers",
            "**One clause.**",
            "while also operating multiple 6-inch GaAs VCSEL manufacturing facilities",
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
            "`object_name` is that company's name exactly as the quote writes it",
            "never a description",
        ),
    ),
    (
        SKEPTIC_PLAN,
        "skeptic-plan",
        # v3: it must choose archived documents from the catalog (pilot fix 06), and a filing
        # phrase per query (pilot fix 12)
        3,
        (
            "Search results are leads: Atlas never reads them",
            "Only archived documents are Evidence",
            "You must choose documents from the `catalog`",
            "at least one document of each seed company",
            "risk factors",
            "8-K",
            "older filings",
            "An empty `documents` list reads nothing",
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
            "EDGAR full-text search",
            "`filing_phrase`",
        ),
    ),
    (
        SKEPTIC,
        "skeptic",
        # v3: each item is a contradiction of a named Claim or bear context, never both
        # (memory-directed reading, ticket 03)
        3,
        (
            "one of two kinds, never both",
            "`contradiction`",
            "`bear_context`",
            "`denies`",
            "`limits`",
            "`dates`",
            "names that Claim's subject company or its object",
            "When in doubt, it is `bear_context`",
            "A row of a table",
            "`figure_name`",
            "`figure_period`",
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
        # v4: what was searched and read, and a card with no accepted Claim (pilot fix 01);
        # v5: contradictions and bear context, separately (memory-directed reading, ticket 03)
        5,
        (
            "in two separate lists",
            "`contradictions`",
            "`bear_context`",
            "it contradicts no finding",
            "what the contradictions and the bear context suggest checking",
            "Bear context alone never makes the verdict `needs_review`",
            "the bottleneck layer",
            "the chokepoint",
            "the mechanism",
            "capacity relief",
            "dilution or financing",
            "never cite a lead ID",
            "When the request has no Claims, write the card anyway",
            "`findings` is `[]`",
            "`verdict` is `needs_review`",
            "what the next round should look for",
            "Reason from `read`",
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
