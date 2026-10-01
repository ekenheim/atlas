"""The predicate whitelist (build plan §5.5), its direction, the layers, and the directional
language and party checks a Claim's quote must pass (`atlas.claims`)."""

import pytest

from atlas.claims import (
    FOLD_TABLE,
    LAYER_TERMS,
    LAYERS,
    PREDICATES,
    SHARED_LAYER_TERMS,
    clauses,
    company_names,
    direction_refusal,
    directional_cue,
    fold,
    is_generic_object,
    layer_term,
    mentions,
    names_object,
    names_party,
    object_clause_cue,
    predicate_refusal,
    stray_companies,
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
        # Memory-directed reading ticket 02: the pilot's constraint statements.
        (
            "capacity_constrained",
            "This demand is outpacing our current supply",
            "demand is outpacing",
        ),
        (
            "capacity_constrained",
            "to address our increased customer demand and industry-wide shortage",
            "shortage",
        ),
        (
            "capacity_constrained",
            "which has required us to make decisions on supply allocation",
            "supply allocation",
        ),
        ("capacity_constrained", "Our 200G EMLs are sold out through 2027.", "sold out"),
        ("capacity_constrained", "Lead times for our InP lasers have extended.", "Lead times"),
        ("capacity_constrained", "We were unable to meet demand for EML chips.", "unable to meet"),
        ("capacity_constrained", "Customers for our EMLs remain on allocation.", "on allocation"),
        (
            "capacity_constrained",
            "the allocation of our limited EML supply among customers",
            "allocation of our limited EML supply",
        ),
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


# --- constraint cues, ownership direction, the fold, the unnamed filer --------------------------
# (memory-directed reading ticket 02; the sentences are pilot investigation 1's on 0.2.5)

# Coherent's FY2026 10-K: an expansion, accepted as `capacity_constrained` through "allocation".
EXPANSION = (
    "we remain disciplined in our capital allocation, prioritizing investments to expand"
    " manufacturing capacity so we can efficiently fulfill the ongoing acceleration in customer"
    " demand."
)


@pytest.mark.parametrize(
    "quote",
    [
        EXPANSION,
        "prioritizing investments to expand manufacturing capacity",
        "we remain disciplined in our capital allocation",
        "We allocate capital to expand capacity for our datacom lasers.",
        "The purchase price allocation for the acquisition is preliminary.",
        "Customer demand for AI transceivers continues to grow.",
    ],
)
def test_an_expansion_or_an_allocation_of_capital_is_no_constraint(quote: str) -> None:
    assert directional_cue("capacity_constrained", quote) is None


def test_capacity_words_alone_name_no_product() -> None:
    # Why fix 09's rule let "manufacturing capacity" through: its generic words were the
    # materials-and-components vocabulary only.
    for object_text in ["manufacturing capacity", "production capacity", "our facilities"]:
        assert is_generic_object(object_text), object_text
    assert not is_generic_object("6-inch InP manufacturing capacity")
    assert not is_generic_object("indium phosphide capacity")
    # And a quote that names only the capacity words doesn't name the product.
    assert not names_object("constrained manufacturing capacity", "EML manufacturing capacity")
    assert names_object("constrained EML manufacturing capacity", "EML manufacturing capacity")


COHERENT = company_names("Coherent", "Coherent Corp.")
LUMENTUM = company_names("Lumentum", "Lumentum Holdings Inc.")
NVIDIA = company_names("NVIDIA", "NVIDIA Corporation")
# Hand-shaped from Coherent's 10-Q filed 2026-05-06 and Lumentum's 8-K filed 2026-03-02.
ISSUED_AND_SOLD = "the Company issued and sold 7,788,161 shares of Common Stock to NVIDIA"
ISSUANCE_AND_SALE = (
    "Lumentum Holdings Inc. completed the issuance and sale of 2,876,415 shares of the"
    " Company\N{RIGHT SINGLE QUOTATION MARK}s Series A Convertible Preferred Stock to NVIDIA"
    " Corporation"
)


@pytest.mark.parametrize(
    ("quote", "issuer", "filer"),
    [
        (ISSUED_AND_SOLD, COHERENT, True),
        (ISSUANCE_AND_SALE, LUMENTUM, False),
        ("NVIDIA purchased 7,788,161 shares of our Common Stock", COHERENT, True),
        ("7,788,161 shares of Common Stock were purchased by NVIDIA Corporation", COHERENT, True),
    ],
)
def test_owns_runs_from_the_holder_of_the_shares_to_their_issuer(
    quote: str, issuer: list[str], filer: bool
) -> None:
    assert directional_cue("owns", quote) is not None
    held = direction_refusal("owns", quote, NVIDIA, issuer, filer="object" if filer else None)
    assert held is None
    reversed_ = direction_refusal("owns", quote, issuer, NVIDIA, filer="subject" if filer else None)
    assert reversed_ is not None
    assert "NVIDIA" in reversed_
    assert "holder" in reversed_


def test_a_filer_that_buys_shares_is_their_holder() -> None:
    quote = "We purchased 1,000,000 shares of AXT common stock"
    axt = company_names("AXT", "AXT Inc.")
    assert direction_refusal("owns", quote, COHERENT, axt, filer="subject") is None
    assert direction_refusal("owns", quote, axt, COHERENT, filer="object") is not None


def test_a_sentence_of_no_issuance_or_purchase_says_nothing_of_the_direction() -> None:
    quote = "NVIDIA made a $2 billion investment in the Company"
    assert direction_refusal("owns", quote, NVIDIA, COHERENT, filer="object") is None
    assert direction_refusal("owns", quote, COHERENT, NVIDIA, filer="subject") is None
    assert direction_refusal("competes_with", ISSUED_AND_SOLD, COHERENT, NVIDIA) is None


# Coherent's 8-K filed 2026-03-02 (the same sentence in Lumentum's, "advanced laser components").
NVIDIA_COMMITMENT = (
    "The non-exclusive agreement includes an NVIDIA multi-billion-dollar purchase commitment and"
    " future access and capacity rights for advanced laser and optical networking products."
)


def test_the_company_that_makes_a_purchase_commitment_is_the_buyer() -> None:
    assert directional_cue("supplies", NVIDIA_COMMITMENT) == "purchase commitment"
    assert direction_refusal("supplies", NVIDIA_COMMITMENT, COHERENT, NVIDIA) is None
    reversed_ = direction_refusal("buys_from", NVIDIA_COMMITMENT, COHERENT, NVIDIA)
    assert reversed_ is not None
    assert "buyer" in reversed_
    assert direction_refusal("supplies", NVIDIA_COMMITMENT, NVIDIA, COHERENT) is not None
    assert direction_refusal("buys_from", NVIDIA_COMMITMENT, NVIDIA, COHERENT) is None
    # "with" names no buyer (the recorded 10-K's wording): the Reviewer judges the direction.
    with_ = "The agreement includes a multi-billion-dollar purchase commitment with NVIDIA"
    assert direction_refusal("buys_from", with_, COHERENT, NVIDIA) is None


NBH = "\N{NON-BREAKING HYPHEN}"


def characters(*code_points: int) -> str:
    return "".join(chr(code_point) for code_point in code_points)


def test_the_fold_maps_one_character_to_one_character() -> None:
    # The table of the ticket: hyphens U+2010 to U+2015 and U+2212; curly quotation marks;
    # no-break and narrow spaces.
    hyphens = characters(0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212)
    assert fold(hyphens) == "-" * 7
    assert fold(characters(0x2018, 0x2019, 0x201A, 0x201B)) == "'" * 4
    assert fold(characters(0x201C, 0x201D, 0x201E, 0x201F)) == '"' * 4
    assert fold(characters(0x00A0, 0x2007, 0x2009, 0x200A, 0x202F)) == " " * 5
    assert len(FOLD_TABLE) == 20
    slide = f"6{NBH}inch platform producing EMLs, with higher yields than 3{NBH}inch lines"
    assert fold(slide) == "6-inch platform producing EMLs, with higher yields than 3-inch lines"
    assert len(fold(slide)) == len(slide)
    # Nothing else changes: case, ASCII, accents, other punctuation.
    plain = "We don't 'fold' Case - or caf" + characters(0xE9, 0x2026, 0x2022, 0xB5) + "."
    assert fold(plain) == plain


def test_cues_and_objects_are_read_through_the_fold_and_returned_as_written() -> None:
    quote = f"Our platform includes the in{NBH}house design and manufacture of 6{NBH}inch lasers."
    assert directional_cue("vertically_integrates", quote) == f"in{NBH}house"
    assert object_clause_cue("vertically_integrates", quote, "6-inch lasers") == f"in{NBH}house"
    assert names_object(quote, "6-inch lasers")
    assert names_party(
        "the Company\N{RIGHT SINGLE QUOTATION MARK}s lasers", COHERENT, is_filer=True
    )
    assert names_party("the Company's lasers", COHERENT, is_filer=True)


def test_companies_named_besides_the_parties_are_strays() -> None:
    known = [COHERENT, LUMENTUM, NVIDIA]
    assert stray_companies(NVIDIA_COMMITMENT, [NVIDIA], known) == []
    two = "NVIDIA also entered into a purchase commitment with Lumentum for laser components."
    assert stray_companies(two, [NVIDIA], known) == ["Lumentum"]
    assert stray_companies(two, [NVIDIA, LUMENTUM], known) == []
    # A company Atlas doesn't know, written with its legal form, is one too.
    unknown = "Broadcom Inc. supplies VCSEL arrays to NVIDIA Corporation."
    assert stray_companies(unknown, [NVIDIA], known) == ["Broadcom Inc."]
    assert stray_companies("NVIDIA Corporation buys VCSEL arrays.", [["NVIDIA"]], known) == []
    assert stray_companies(f"6{NBH}inch platform producing EMLs", [], known) == []


# --- the layer rule (memory-directed reading ticket 08) ------------------------------------------

# Recorded Coherent FY2026 10-K.
SHERMAN = (
    "We are investing in manufacturing capacity for the Datacenter and Communications markets,"
    " including expanding our indium phosphide capacity in Sherman, Texas, to address our"
    " increased customer demand and industry-wide shortage."
)
ISSUANCE = (
    "On March 2, 2026, the Company issued and sold 7,788,161 shares of Common Stock to NVIDIA"
    " for an aggregate purchase price of $2.0 billion."
)


def test_every_layer_has_terms_and_no_term_belongs_to_two_layers() -> None:
    assert list(LAYER_TERMS) == [layer.name for layer in LAYERS]
    assert all(LAYER_TERMS.values())
    seen: dict[str, str] = {}
    for layer, terms in LAYER_TERMS.items():
        for term in terms:
            assert seen.setdefault(term.lower(), layer) == layer, term
    assert not {term.lower() for term in SHARED_LAYER_TERMS} & set(seen)


@pytest.mark.parametrize(
    ("layer", "quote", "object_text", "term"),
    [
        # The object text names the layer: "InP substrates" keeps `substrate`.
        (
            "substrate",
            "We purchase InP substrates from a limited number of suppliers.",
            "InP substrates",
            "substrates",
        ),
        ("epi", "IQE supplies epitaxial wafers to us.", None, "epitaxial"),
        ("epi", "We added MOCVD reactors in Taiwan.", "MOCVD reactors", "MOCVD"),
        (
            "chip-laser",
            "Demand for our 200G EML lasers exceeded our supply.",
            "200G EML lasers",
            "EML",
        ),
        ("chip-laser", "a new record for datacom laser chip orders", None, "laser"),
        ("dsp", "We buy DSPs from Marvell.", None, "DSPs"),
        ("module", "We supply 800G transceivers to NVIDIA.", None, "transceivers"),
        (
            "contract-manufacturing",
            "For many products, a particular contract manufacturer may be the sole source of the"
            " finished good products.",
            None,
            "contract manufacturer",
        ),
        ("system", "Ciena ships optical transport systems to carriers.", None, "optical transport"),
        # A company object: the whole quote is read.
        (
            "chip-laser",
            "entered into a strategic multi-year supply agreement with NVIDIA for advanced lasers"
            " and optical networking products",
            None,
            "lasers",
        ),
        # A product object the quote names with a term of the layer in its clause.
        (
            "chip-laser",
            "6-inch platform producing EMLs, CW lasers, and photodiodes",
            "6-inch platform",
            "EMLs",
        ),
    ],
)
def test_a_layer_is_supported_by_a_term_of_it_in_the_object_text_or_the_quote(
    layer: str, quote: str, object_text: str | None, term: str
) -> None:
    assert layer_term(layer, quote, object_text) == term


@pytest.mark.parametrize(
    ("layer", "quote", "object_text"),
    [
        # The pilot's wrong layers: InP capacity is no substrate fact, an issuer no chip.
        ("substrate", SHERMAN, "indium phosphide capacity in Sherman, Texas"),
        ("epi", SHERMAN, "indium phosphide capacity"),
        ("chip-laser", SHERMAN, "indium phosphide capacity"),
        ("chip-laser", ISSUANCE, None),
        ("system", "NVIDIA made a $2 billion investment in the Company", None),
        (
            "substrate",
            "We purchase germanium for our infrared optics from a single supplier.",
            "germanium",
        ),
        (
            "substrate",
            "We continue to expand our global 6-inch InP manufacturing capacity.",
            "6-inch InP manufacturing capacity",
        ),
        # Another layer's term is no support.
        ("epi", "We purchase InP substrates from a limited number of suppliers.", "InP substrates"),
        ("module", "We manufacture GaAs VCSELs.", "GaAs VCSELs"),
        # Not a layer at all.
        ("optics", "We manufacture GaAs VCSELs.", "GaAs VCSELs"),
    ],
)
def test_a_layer_the_quote_and_object_do_not_name_is_unsupported(
    layer: str, quote: str, object_text: str | None
) -> None:
    assert layer_term(layer, quote, object_text) is None


@pytest.mark.parametrize("shared", SHARED_LAYER_TERMS)
def test_a_term_shared_by_several_layers_supports_none_of_them(shared: str) -> None:
    quote = f"We are expanding our {shared} capacity."
    for layer in LAYERS:
        assert layer_term(layer.name, quote, f"{shared} capacity") is None, layer.name


def test_a_term_in_another_clause_than_a_product_object_is_no_support() -> None:
    # "VCSEL" is in the clause about the GaAs facilities, not in the InP capacity's.
    assert layer_term("chip-laser", VCSEL, "6-inch InP manufacturing capacity") is None
    assert layer_term("chip-laser", VCSEL, "6-inch GaAs VCSEL manufacturing facilities") == "VCSEL"
    # A quote that doesn't name the object is read whole.
    assert layer_term("chip-laser", VCSEL, "wafer fabs") == "VCSEL"


def test_a_longer_term_of_another_layer_wins_over_the_term_inside_it() -> None:
    # A laser driver is an electrical IC: "laser" inside it is no chip-laser term.
    quote = "We purchase laser drivers from a single supplier."
    assert layer_term("dsp", quote, "laser drivers") == "laser drivers"
    assert layer_term("chip-laser", quote, "laser drivers") is None


def test_layer_terms_are_whole_words_read_through_the_fold_and_acronyms_keep_their_case() -> None:
    assert layer_term("substrate", "our substrateless design", None) is None
    assert layer_term("chip-laser", "a pic of our fab; systems and teams", None) is None
    assert layer_term("dsp", "we tia up with partners", None) is None
    assert layer_term("chip-laser", "our PICs and photodiodes", None) == "PICs"
    assert layer_term("epi", f"our epi{NBH}wafer foundry", None) == "epi"
    quote = f"third{NBH}party contract{NBH}manufacturers build our modules"
    assert layer_term("contract-manufacturing", quote, None) == f"contract{NBH}manufacturers"
