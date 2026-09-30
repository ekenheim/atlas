"""The predicate whitelist (build plan §5.5), its direction, the layers, and the directional
language and party checks a Claim's quote must pass (`atlas.claims`)."""

import pytest

from atlas.claims import (
    LAYERS,
    PREDICATES,
    clauses,
    company_names,
    directional_cue,
    is_generic_object,
    mentions,
    names_object,
    names_party,
    object_clause_cue,
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


# --- cue proximity and named objects (pilot-fixes ticket 09) -------------------------------------

# From the recorded Coherent FY2026 10-K: "expand" is in the InP clause only.
VCSEL = (
    "We continue to expand our global 6-inch InP manufacturing capacity in the United States and"
    " Europe to support increasing customer demand, while also operating multiple 6-inch GaAs"
    " VCSEL manufacturing facilities."
)


def test_the_vcsel_sentence_has_two_clauses() -> None:
    [first, second] = clauses(VCSEL)
    assert VCSEL[first[0] : first[1]].endswith("customer demand")
    assert VCSEL[second[0] : second[1]].startswith("operating multiple")


@pytest.mark.parametrize(
    "object_text", ["6-inch GaAs VCSEL manufacturing facilities", "GaAs VCSELs", "VCSEL"]
)
def test_a_cue_in_the_neighbouring_clause_is_no_cue_for_the_object(object_text: str) -> None:
    assert directional_cue("expands_capacity_for", VCSEL) == "expand"  # the old, quote-wide check
    assert object_clause_cue("expands_capacity_for", VCSEL, object_text) is None


@pytest.mark.parametrize(
    ("predicate", "quote", "object_text", "cue"),
    [
        ("expands_capacity_for", VCSEL, "6-inch InP manufacturing capacity", "expand"),
        (
            "expands_capacity_for",
            "we continue to expand our 6-inch InP capacity",
            "6-inch InP capacity",
            "expand",
        ),
        # Recorded Coherent 10-K: commas inside the clause ("Sherman, Texas,") are no boundary.
        (
            "expands_capacity_for",
            "We are investing in manufacturing capacity for the Datacenter and Communications"
            " markets, including expanding our indium phosphide capacity in Sherman, Texas, to"
            " address our increased customer demand and industry-wide shortage.",
            "indium phosphide capacity",
            "capacity",
        ),
        (
            "sole_sources",
            "However, in the Industrial segment, we currently purchase several key components and"
            " materials used in the manufacture of our products, including exotic materials,"
            " crystals, and optics, from sole-source or limited-source suppliers.",
            "exotic materials, crystals, and optics",
            "sole-source",
        ),
        (
            "vertically_integrates",
            "Our vertically integrated technology platform includes the in-house design and"
            " manufacture of transceivers and many of their critical components, including lasers,"
            " detectors, ICs, passive optics, thermal solutions, and PICs.",
            "lasers",
            "vertically integrated",
        ),
        (
            "sole_sources",
            "Our manufacturing processes and those of our contract manufacturers rely on many"
            " materials, including precious and rare earth metals, indium phosphide"
            " (\N{LEFT DOUBLE QUOTATION MARK}InP\N{RIGHT DOUBLE QUOTATION MARK}) and certain"
            " lasers and laser components that may be difficult to source, may only be available"
            " from a single or limited number of suppliers.",
            "indium phosphide",
            "limited number of suppliers",
        ),
        # Recorded Lumentum FY2026 10-K.
        (
            "capacity_constrained",
            "Due to increased demand across a range of industries, our business and"
            " customers\N{RIGHT SINGLE QUOTATION MARK} businesses are experiencing and could, in"
            " the future, experience supply constraints due to both constrained manufacturing"
            " capacity, as well as component parts shortages.",
            "manufacturing capacity",
            "constraints",
        ),
        (
            "manufactures",
            "We use a combination of our own wafer fabrication facilities, or wafer fabs, assembly"
            " and test facilities, as well as third-party contract manufacturers to produce our"
            " products.",
            "wafer fabs",
            "fabrication",
        ),
    ],
)
def test_a_cue_in_the_object_s_clause_counts_whatever_commas_the_clause_holds(
    predicate: str, quote: str, object_text: str, cue: str
) -> None:
    assert object_clause_cue(predicate, quote, object_text) == cue


@pytest.mark.parametrize(
    ("predicate", "quote", "object_text"),
    [
        (
            "expands_capacity_for",
            "We expand our InP laser capacity; we also purchase GaAs substrates.",
            "GaAs substrates",
        ),
        (
            "expands_capacity_for",
            "We are adding capacity for EMLs, whereas our VCSEL output is flat.",
            "VCSEL output",
        ),
        (
            "vertically_integrates",
            "We manufacture our own InP substrates, but we buy GaAs wafers.",
            "GaAs wafers",
        ),
        (
            "expands_capacity_for",
            "We expanded 6-inch InP capacity in Sherman, and also sell GaAs wafers.",
            "GaAs wafers",
        ),
    ],
)
def test_each_clause_boundary_separates_a_cue_from_the_object(
    predicate: str, quote: str, object_text: str
) -> None:
    assert directional_cue(predicate, quote) is not None
    assert object_clause_cue(predicate, quote, object_text) is None


def test_a_quote_that_doesn_t_name_the_object_falls_back_to_its_first_cue() -> None:
    quote = (
        "Changes in demand and customer requirements for our products may reduce manufacturing"
        " yields, which could negatively impact our profitability."
    )
    assert object_clause_cue("manufactures", quote, "optical and photonic products") == (
        "manufacturing"
    )


@pytest.mark.parametrize(
    "object_text",
    [
        "certain materials, equipment and components",
        "raw materials, packages and components",
        "several key components and materials",
        "materials and components",
    ],
)
def test_generic_materials_and_components_name_no_input(object_text: str) -> None:
    assert is_generic_object(object_text)


@pytest.mark.parametrize(
    "object_text", ["InP substrates", "exotic materials, crystals, and optics", "germanium", "EMLs"]
)
def test_a_named_input_is_not_generic(object_text: str) -> None:
    assert not is_generic_object(object_text)


def test_an_object_is_named_when_the_quote_contains_it_case_and_spacing_aside() -> None:
    quote = "We purchase InP  substrates from a limited number of suppliers."
    assert names_object(quote, "InP substrates")
    assert names_object(quote, "inp substrates")
    assert not names_object(quote, "indium phosphide substrates")
    assert not names_object(quote, "")


def test_an_object_paraphrased_from_most_of_the_quote_s_words_is_named() -> None:
    # Pilot investigation 1's re-run: Lumentum's allocation statement, as the model named it.
    quote = (
        "since then, we have seen increasing demand from AI and cloud customers as they"
        " continue to expand their data centers, driven in part by the continued advances in"
        " cloud and AI infrastructure. This demand is outpacing our current supply which has"
        " required us to make decisions on supply allocation."
    )
    assert names_object(quote, "products for AI and cloud customers' data center expansion")
    assert not names_object(quote, "EML laser chips")
    assert not names_object(
        "This demand is outpacing our current supply which has required us to make decisions"
        " on supply allocation.",
        "optical components for AI and cloud data centers",
    )
