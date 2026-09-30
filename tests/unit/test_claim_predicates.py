"""The predicate whitelist (build plan §5.5), its direction, the layers, and the directional
language and party checks a Claim's quote must pass (`atlas.claims`)."""

import pytest

from atlas.claims import (
    LAYERS,
    PREDICATES,
    company_names,
    directional_cue,
    mentions,
    names_party,
    predicate_refusal,
)


def test_the_whitelist_is_build_plan_5_5_and_the_bottleneck_predicates() -> None:
    assert list(PREDICATES) == [
        "manufactures",
        "supplies",
        "buys_from",
        "uses_material",
        "owns",
        "competes_with",
        "substitutes_for",
        "expands_capacity_for",
        "depends_on",
        # company-level bottleneck predicates (pilot-fixes ticket 03)
        "capacity_constrained",
        "sole_sources",
        "vertically_integrates",
        "qualified_for",
    ]
    companies = [name for name, p in PREDICATES.items() if p.object_kind == "company"]
    assert companies == ["supplies", "buys_from", "owns", "competes_with", "depends_on"]
    assert [name for name, p in PREDICATES.items() if p.symmetric] == ["competes_with"]


def test_the_bottleneck_predicates_state_a_company_fact_about_a_product() -> None:
    for name in ["capacity_constrained", "sole_sources", "vertically_integrates", "qualified_for"]:
        predicate = PREDICATES[name]
        assert (predicate.object_kind, predicate.symmetric) == ("product", False), name
        assert predicate.reads.startswith(("the subject company", "customers have")), name
    assert "named or not" in PREDICATES["qualified_for"].reads
    assert "whether or not the supplier is named" in PREDICATES["sole_sources"].reads


def test_supplies_and_buys_from_read_in_opposite_directions() -> None:
    assert "the object is the subject's customer" in PREDICATES["supplies"].reads
    assert "the object is the subject's supplier" in PREDICATES["buys_from"].reads


@pytest.mark.parametrize(
    "proposed", ["works_with", "partners_with", "partners with", "Works-With", "collaborates_with"]
)
def test_undirected_relations_map_to_no_predicate(proposed: str) -> None:
    refusal = predicate_refusal(proposed)
    assert refusal is not None
    assert "maps to no predicate" in refusal


def test_only_whitelisted_names_are_predicates() -> None:
    assert predicate_refusal("supplies") is None
    assert predicate_refusal("Supplies") is not None  # names are exact
    assert "not a whitelisted predicate" in (predicate_refusal("customer_of") or "")


def test_the_layers_run_from_substrate_to_system_with_contract_manufacturing() -> None:
    assert [layer.name for layer in LAYERS] == [
        "substrate",
        "epi",
        "chip-laser",
        "dsp",
        "module",
        "contract-manufacturing",
        "system",
    ]


@pytest.mark.parametrize(
    ("predicate", "quote", "cue"),
    [
        ("supplies", "We supply 800G transceivers to NVIDIA.", "supply"),
        ("supplies", "NVIDIA accounted for 16.3% of our revenue as a customer.", "customer"),
        ("buys_from", "We purchase InP substrates from AXT.", "purchase"),
        ("buys_from", "AXT is a supplier of our substrates.", "supplier"),
        ("owns", "NVIDIA made a $2 billion investment in the Company", "investment"),
        ("competes_with", "Our competitors include Coherent.", "competitors"),
        ("depends_on", "We rely on a sole source for EML lasers.", "rely"),
        ("manufactures", "We manufacture indium phosphide lasers.", "manufacture"),
        ("expands_capacity_for", "We are expanding our 6-inch InP capacity.", "expanding"),
        ("substitutes_for", "Silicon photonics can replace EMLs in some links.", "replace"),
        ("uses_material", "Our lasers use indium phosphide.", "use"),
        ("capacity_constrained", "Demand for our EMLs exceeds our supply.", "exceeds our supply"),
        ("capacity_constrained", "We are capacity constrained in 200G EMLs.", "constrained"),
        ("capacity_constrained", "We allocate our InP laser output to customers.", "allocate"),
        (
            "sole_sources",
            "We purchase several key materials from sole-source or limited-source suppliers.",
            "sole-source",
        ),
        (
            "sole_sources",
            "There is a limited number of high-quality suppliers of many of the components.",
            "limited number of high-quality suppliers",
        ),
        (
            "vertically_integrates",
            "We manufacture our own indium phosphide substrates.",
            "our own",
        ),
        (
            "vertically_integrates",
            "Our platform includes the in-house design and manufacture of lasers.",
            "in-house",
        ),
        ("qualified_for", "Our 1.6T transceiver was qualified at a hyperscaler.", "qualified"),
        ("qualified_for", "We secured design wins for 800G modules.", "design wins"),
    ],
)
def test_directional_language_is_found(predicate: str, quote: str, cue: str) -> None:
    assert directional_cue(predicate, quote) == cue


@pytest.mark.parametrize(
    "quote",
    [
        "The Company\N{RIGHT SINGLE QUOTATION MARK}s peer group includes IPG Photonics Corp.,"
        " Wolfspeed Inc., Lumentum Holdings, Inc., Corning, Inc.",
        "Lumentum and Coherent both exhibited at OFC 2026.",
        "We work closely with partners such as Coherent.",
    ],
)
def test_co_mention_carries_no_directional_language_for_any_company_predicate(quote: str) -> None:
    for predicate in ["supplies", "buys_from", "owns", "competes_with", "depends_on"]:
        assert directional_cue(predicate, quote) is None, predicate


@pytest.mark.parametrize(
    "quote",
    [
        "We manufacture GaAs VCSELs and InP edge-emitting lasers.",
        "Customer demand for AI transceivers continues to grow.",
        "indium phosphide (InP);",
    ],
)
def test_a_plain_product_statement_is_no_bottleneck(quote: str) -> None:
    for predicate in ["capacity_constrained", "sole_sources", "vertically_integrates"]:
        assert directional_cue(predicate, quote) is None, predicate


def test_a_cue_counts_only_for_its_own_predicate() -> None:
    quote = "We purchase InP substrates from AXT."
    assert directional_cue("buys_from", quote) == "purchase"
    assert directional_cue("competes_with", quote) is None
    assert directional_cue("no_such_predicate", quote) is None


def test_company_names_drop_corporate_suffixes() -> None:
    assert company_names("Lumentum", "Lumentum Holdings Inc.") == [
        "Lumentum Holdings Inc.",
        "Lumentum Holdings",
        "Lumentum",
    ]
    assert company_names("NVIDIA", "NVIDIA Corporation") == ["NVIDIA Corporation", "NVIDIA"]
    assert company_names("Coherent", "Coherent Corp.") == ["Coherent Corp.", "Coherent"]


def test_names_match_case_sensitive_whole_words() -> None:
    names = company_names("Coherent", "Coherent Corp.")
    assert mentions("We compete with Coherent in datacom.", names)
    assert not mentions("tunable laser and coherent components", names)
    assert not mentions("Coherently designed modules", names)


def test_the_filer_may_be_named_in_the_first_person() -> None:
    names = company_names("Coherent", "Coherent Corp.")
    quote = "NVIDIA made a $2 billion investment in the Company"
    assert names_party(quote, names, is_filer=True)
    assert not names_party(quote, names, is_filer=False)
    assert names_party("we announced a supply agreement", names, is_filer=True)
