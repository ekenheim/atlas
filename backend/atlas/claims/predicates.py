"""The predicate whitelist (build plan §5.5), its direction rules and the photonics layers.

**Predicates.** Only these thirteen may name a Claim's relation: build plan §5.5's nine and
four **company-level bottleneck predicates** (pilot-fixes ticket 03, owner-authorized; see
`docs/decisions.md`). Each has an explicit direction: the subject does something *to* the
object, and nothing is ever inferred the other way. `supplies` and `buys_from` are two
predicates, never derived from each other; "works with", "partners with" and "collaborates
with" name no direction and map to no predicate at all. An object is either a company
(`supplies`, `buys_from`, `owns`, `competes_with`, `depends_on`) or a product, material or
technology named in text (`manufactures`, `uses_material`, `substitutes_for`,
`expands_capacity_for`, and the bottleneck predicates `capacity_constrained`,
`sole_sources`, `vertically_integrates`, `qualified_for`). `competes_with` is the one
symmetric predicate; it is still stored in the direction proposed.

**Company-level bottleneck predicates** state a fact a company discloses about itself and a
product, with no counterparty named: that it can't meet demand for the product
(`capacity_constrained`), that it gets an input from one or a few suppliers, named or not
(`sole_sources`; `depends_on` when the supplier is a named company), that it makes an input
for its own products (`vertically_integrates`), or that customers have qualified it as a
supplier of a product (`qualified_for`; `supplies` when the customer is a named company).
They form edges from the company to a product node like `manufactures` does.

**Layers.** A Claim may carry the supply-chain layer of what the link is about (ticket 12
tags Relationships with it): substrate → epi → chip/laser → DSP → module → system, plus
contract manufacturing, as slugs. The layer is optional and kept only when the quote or the
object text names it (`layer_term`, memory-directed reading ticket 08): each layer has its
terms (`LAYER_TERMS`), and a word several layers share ("InP", "indium phosphide", "wafer":
`SHARED_LAYER_TERMS`) supports none of them.

**Directional language.** A Claim's quote must use language that expresses its predicate
(`directional_cue`): a small, conservative pattern list per predicate. Two companies named
in one sentence ("the peer group includes ...") is co-mention, not a relation, and matches
no pattern. This is a necessary condition only: whether the direction is right is for the
reviewer (ticket 12), which extends this list with the reviewer model's classification.

**Cue proximity** (pilot-fixes ticket 09). For a product object, the cue must be in a clause
of the quote that names the object (`object_clause_cue`): clauses are cut only at a short
list of boundaries (`CLAUSE_BOUNDARY`: "; ", ", while", ", whereas", ", but", ", although",
", and also", " while also"), never at a bare comma. "We continue to expand our 6-inch InP
manufacturing capacity ..., while also operating multiple 6-inch GaAs VCSEL manufacturing
facilities" expands capacity for InP, not for the VCSEL facilities. A quote that doesn't name
the object can't be judged this way and falls back to its first cue.

**Named, specific objects** (pilot-fixes ticket 09). A bottleneck predicate's object must be
named in its quote (`names_object`) and be a particular input or product, not generic words
("certain materials, equipment and components": `is_generic_object`).

**Parties.** A quote must name both parties (`names_party`): a company by one of its names
(case-sensitive, whole words, so "coherent optics" never names Coherent), or, for the
company whose document it is, a first-person reference ("we", "our", "the Company").

**The filer as the unnamed party** (memory-directed reading ticket 02). An impersonal sentence
or slide bullet of the filer's own document may leave the filer unnamed ("The non-exclusive
agreement includes an NVIDIA multi-billion-dollar purchase commitment ..."). The extraction
accepts the filer as the unnamed party only when the quote names the other party (or the
object product), carries the predicate's cue, and names no other company that could be the
unnamed one (`stray_companies`): a sentence naming two other companies still proves nothing
about the filer.

**The typographic fold** (`fold`). Quotes are located, and cues, names and objects are
matched, through a one-character-to-one-character fold of typographic hyphens, quotation
marks and spaces to their ASCII forms (`FOLD_TABLE`), so offsets hold; what is stored and
returned is always the text as written.

**Direction from the wording** (`direction_refusal`). Two shapes of sentence fix who is who,
whatever the cue: shares issued or sold *to* a company, or purchased *by* it, make that
company the holder (`owns` runs from the holder to the issuer); and "an X purchase
commitment" makes X the buyer (`supplies` runs to X, `buys_from` from X).
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from atlas.companies import Layer

ObjectKind = Literal["company", "product"]

# One layer vocabulary: the universe's (`atlas.companies`), which the config and the
# company table's check constraint use.


@dataclass(frozen=True)
class LayerDefinition:
    name: Layer
    covers: str
    # The words that name the layer and nothing else (`layer_term`): lower case for a word or
    # phrase (matched whatever its case), upper case for an acronym (matched as written); the
    # last word may be plural, and words may be joined by a space or a hyphen.
    terms: tuple[str, ...]


# Upstream to downstream; contract manufacturing is a service layer beside module/system.
LAYERS: tuple[LayerDefinition, ...] = (
    LayerDefinition(
        "substrate",
        "bare wafers and substrates (InP, GaAs, SOI)",
        ("substrate", "bare wafer", "boule", "ingot"),
    ),
    LayerDefinition(
        "epi",
        "epitaxial wafers grown on substrates",
        ("epitaxy", "epitaxial", "epi", "epiwafer", "MOCVD", "MBE"),
    ),
    LayerDefinition(
        "chip-laser",
        "laser and photonic chips: EML, DML, CW and VCSEL lasers, PICs, photodiodes",
        (
            "laser",
            "EML",
            "DML",
            "VCSEL",
            "DFB",
            "photodiode",
            "photodetector",
            "PIC",
            "photonic integrated circuit",
            "photonic chip",
            "optical chip",
        ),
    ),
    LayerDefinition(
        "dsp",
        "DSPs, drivers, TIAs and other electrical ICs for optics",
        (
            "DSP",
            "digital signal processor",
            "TIA",
            "transimpedance amplifier",
            "laser driver",
            "driver IC",
            "retimer",
            "serdes",
        ),
    ),
    LayerDefinition(
        "module",
        "optical transceivers and modules",
        ("transceiver", "optical module", "module", "pluggable", "transponder", "AOC"),
    ),
    LayerDefinition(
        "contract-manufacturing",
        "assembly, test and contract manufacturing of optics",
        (
            "contract manufacturer",
            "contract manufacturing",
            "electronics manufacturing services",
            "EMS",
            "outsourced manufacturing",
            "outsourced assembly",
            "OSAT",
        ),
    ),
    LayerDefinition(
        "system",
        "systems built from modules: optical transport, switches, AI clusters",
        (
            "optical transport",
            "transport system",
            "line system",
            "network switch",
            "ethernet switch",
            "data center switch",
            "switching system",
            "router",
            "server",
            "AI cluster",
            "networking equipment",
        ),
    ),
)
LAYER_NAMES: frozenset[str] = frozenset(layer.name for layer in LAYERS)
# Each layer's terms (the table in `docs/decisions.md`, "A layer only when the quote supports
# one"). No term is in two layers.
LAYER_TERMS: dict[str, tuple[str, ...]] = {layer.name: layer.terms for layer in LAYERS}
# Words several layers share, so they name none of them: the materials (an InP substrate, an
# InP epiwafer and an InP laser are three layers; indium, gallium and germanium are feedstock,
# which the taxonomy has no layer for), and "wafer", "chip" and "optics" on their own.
SHARED_LAYER_TERMS: tuple[str, ...] = (
    "InP",
    "indium phosphide",
    "GaAs",
    "gallium arsenide",
    "SOI",
    "silicon photonics",
    "indium",
    "gallium",
    "germanium",
    "wafer",
    "chip",
    "optics",
)


def _cues(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


@dataclass(frozen=True)
class Predicate:
    name: str
    object_kind: ObjectKind
    symmetric: bool
    reads: str  # what "<subject> <predicate> <object>" means, direction included
    cues: tuple[re.Pattern[str], ...]


_PREDICATES: tuple[Predicate, ...] = (
    Predicate(
        "manufactures",
        "product",
        False,
        "the subject company makes the object product",
        _cues(
            r"\bmanufactur\w*",
            r"\bproduc(?:e|es|ed|ing|tion)\b",
            r"\bfabricat\w*",
            r"\b(?:make|makes|made|making)\b",
            r"\b(?:build|builds|built|building)\b",
        ),
    ),
    Predicate(
        "supplies",
        "company",
        False,
        "the subject company sells or ships to the object company"
        " (the object is the subject's customer)",
        _cues(
            r"\bsuppl(?:y|ies|ied|ying|ier|iers)\b",
            r"\b(?:sell|sells|sold|selling|sales to)\b",
            r"\b(?:ship|ships|shipped|shipping|shipments)\b",
            r"\bcustomers?\b",
            r"\bpurchase (?:commitment|agreement|order)s?\b",
        ),
    ),
    Predicate(
        "buys_from",
        "company",
        False,
        "the subject company purchases from the object company"
        " (the object is the subject's supplier)",
        _cues(
            r"\bpurchas\w*",
            r"\b(?:buy|buys|bought|buying)\b",
            r"\bsourc(?:e|es|ed|ing)\b",
            r"\bprocur\w*",
            r"\bsuppl(?:ier|iers|ied by)\b",
            r"\bvendors?\b",
        ),
    ),
    Predicate(
        "uses_material",
        "product",
        False,
        "the subject company uses the object material or input in its products",
        _cues(
            r"\b(?:use|uses|used|using)\b",
            r"\butiliz\w*",
            r"\bmaterials?\b",
            r"\bbased on\b",
            r"\bmade (?:of|from|with)\b",
        ),
    ),
    Predicate(
        "owns",
        "company",
        False,
        "the subject company owns all or part of the object company: the subject is the holder"
        " of the shares and the object their issuer (a company that issues or sells its shares"
        " to an investor is the object, the investor the subject)",
        _cues(
            r"\bown(?:s|ed|ership)?\b",
            r"\bacqui(?:re|res|red|ring|sition)\b",
            r"\bsubsidiar(?:y|ies)\b",
            r"\bstake\b",
            r"\bequity\b",
            r"\binvest(?:s|ed|ment|ments)?\b",
            r"\bshares\b",
        ),
    ),
    Predicate(
        "competes_with",
        "company",
        True,
        "the subject company competes with the object company (symmetric)",
        _cues(r"\bcompet\w*", r"\brivals?\b"),
    ),
    Predicate(
        "substitutes_for",
        "product",
        False,
        "the subject company's product substitutes for the object product or technology",
        _cues(
            r"\bsubstitut\w*",
            r"\breplac\w*",
            r"\balternatives? to\b",
            r"\binstead of\b",
            r"\bdisplac\w*",
        ),
    ),
    Predicate(
        "expands_capacity_for",
        "product",
        False,
        "the subject company adds production capacity for the object product",
        _cues(
            r"\bexpan(?:d|ds|ded|ding|sion)\b",
            r"\bcapacity\b",
            r"\bramp(?:s|ed|ing)?\b",
            r"\bnew (?:fab|facility|line|plant)\b",
        ),
    ),
    Predicate(
        "depends_on",
        "company",
        False,
        "the subject company relies on the object company (e.g. a sole or major supplier)",
        _cues(
            r"\bdepend\w*",
            r"\brel(?:y|ies|ied|iance|ying)\b",
            r"\b(?:sole|single)[- ]sourc\w*",
            r"\bconcentrat\w*",
        ),
    ),
    # --- company-level bottleneck predicates (pilot-fixes ticket 03) ---
    Predicate(
        "capacity_constrained",
        "product",
        False,
        "the subject company cannot fully meet demand for the object product: its capacity,"
        " supply or allocation of it is constrained (demand exceeds its supply, it allocates"
        " or backlogs it, it is short of it)",
        _cues(
            r"\bconstrain\w*",
            r"\bshortages?\b",
            # Allocation of supply, never of capital: "capital allocation", "allocate capital
            # to ..." and "purchase price allocation" are no cue (ticket 02).
            r"\b(?:supply|capacity|product|customer) allocations?\b",
            r"\ballocations? of (?:(?!capital\b)[\w-]+ ){0,3}"
            r"(?:supply|capacity|output|production|products?)\b",
            r"\ballocat(?:e|es|ed|ing)\b"
            r"(?= (?:(?!(?:capital|resources|funds|costs?|to|for|in)\b)[\w-]+ ){0,4}"
            r"(?:supply|capacity|output|production|products?|shipments|inventory)\b)",
            r"\bon allocation\b",
            # Demand exceeding or outpacing supply ("This demand is outpacing our current
            # supply").
            r"\bdemand (?:(?:is|was|has|have|had|continues to|continued to) )?(?:\w+ly )?"
            r"(?:exceed(?:s|ed|ing)?|outpac(?:e|es|ed|ing)|outstrip(?:s|ped|ping)?"
            r"|outgrew|outgrow(?:s|n|ing)?)\b",
            r"\b(?:exceed(?:s|ed|ing)?|outpac(?:e|es|ed|ing)|outstrip(?:s|ped|ping)?)"
            r" (?:(?:our|its|the|current|available|existing|industry) ){0,3}"
            r"(?:supply|capacity)\b",
            r"\b(?:unable|not able) to (?:fully )?(?:meet|satisfy|fulfill)\b",
            r"\bbacklogs?\b",
            r"\blead[- ]times?\b",
            r"\b(?:tight|limited) (?:supply|capacity)\b",
            r"\bsold out\b",
        ),
    ),
    Predicate(
        "sole_sources",
        "product",
        False,
        "the subject company obtains the object input from a single supplier or a limited"
        " number of suppliers (sole, single or limited source), whether or not the supplier is"
        " named",
        _cues(
            r"\b(?:sole|single|limited)[- ]sourc\w*",
            r"\b(?:sole|single|one|only) (?:supplier|vendor|source|manufacturer)s?\b",
            r"\blimited number of (?:\w+[- ]?){0,3}(?:suppliers|vendors|sources|manufacturers)\b",
            r"\b(?:few|small number of) (?:\w+[- ]?){0,3}(?:suppliers|vendors|sources)\b",
        ),
    ),
    Predicate(
        "vertically_integrates",
        "product",
        False,
        "the subject company makes the object input itself for its own products (in-house,"
        " captive or vertically integrated supply) rather than buying it",
        _cues(
            r"\bvertical(?:ly)?[- ]integrat\w*",
            r"\bin[- ]house\b",
            r"\bour own\b",
            r"\bcaptive\b",
            r"\binternal(?:ly)? (?:produc|manufactur|sourc|suppl|develop|grow|fabricat)\w*",
            r"\bself[- ]suppl\w*",
        ),
    ),
    Predicate(
        "qualified_for",
        "product",
        False,
        "customers have qualified the subject company, or chosen it in a design win, as a"
        " supplier of the object product (the customers named or not)",
        _cues(
            r"\bqualif(?:y|ies|ied|ying|ication|ications)\b",
            r"\bdesign[- ]wins?\b",
            r"\b(?:selected|chosen|awarded) (?:as|by|for)\b",
        ),
    ),
)

# The four company-level bottleneck predicates (pilot-fixes ticket 03): a company's own
# statement about itself and a product; they need no named counterparty.
BOTTLENECK_PREDICATES = frozenset(
    {"capacity_constrained", "sole_sources", "vertically_integrates", "qualified_for"}
)

PREDICATES: dict[str, Predicate] = {predicate.name: predicate for predicate in _PREDICATES}

# Relations people and models commonly propose that name no direction: they map to nothing.
UNDIRECTED_RELATIONS = frozenset(
    {"works_with", "partners_with", "collaborates_with", "partner", "partnership", "related_to"}
)


def predicate_refusal(name: str) -> str | None:
    """Why `name` can't be a Claim's predicate, or None if it is whitelisted."""
    if name in PREDICATES:
        return None
    normalized = re.sub(r"[\s-]+", "_", name.strip().lower())
    listed = ", ".join(PREDICATES)
    if normalized in UNDIRECTED_RELATIONS or "partner" in normalized or "work" in normalized:
        return (
            f"{name!r} names no direction and maps to no predicate"
            f" (never to supplies or buys_from); the whitelist is {listed}"
        )
    return f"{name!r} is not a whitelisted predicate; the whitelist is {listed}"


# --- the typographic fold (memory-directed reading ticket 02) ---------------------------------

# One character to one character, so an offset in the folded text is the same offset in the
# text as written: typographic hyphens and dashes to "-", curly quotation marks to straight
# ones, no-break and narrow spaces to a space. Nothing else is folded (not case, not accents,
# not runs of whitespace).
FOLD_TABLE: dict[str, str] = {
    **dict.fromkeys(
        (
            "\N{HYPHEN}",  # U+2010
            "\N{NON-BREAKING HYPHEN}",  # U+2011
            "\N{FIGURE DASH}",  # U+2012
            "\N{EN DASH}",  # U+2013
            "\N{EM DASH}",  # U+2014
            "\N{HORIZONTAL BAR}",  # U+2015
            "\N{MINUS SIGN}",  # U+2212
        ),
        "-",
    ),
    **dict.fromkeys(
        (
            "\N{LEFT SINGLE QUOTATION MARK}",  # U+2018
            "\N{RIGHT SINGLE QUOTATION MARK}",  # U+2019
            "\N{SINGLE LOW-9 QUOTATION MARK}",  # U+201A
            "\N{SINGLE HIGH-REVERSED-9 QUOTATION MARK}",  # U+201B
        ),
        "'",
    ),
    **dict.fromkeys(
        (
            "\N{LEFT DOUBLE QUOTATION MARK}",  # U+201C
            "\N{RIGHT DOUBLE QUOTATION MARK}",  # U+201D
            "\N{DOUBLE LOW-9 QUOTATION MARK}",  # U+201E
            "\N{DOUBLE HIGH-REVERSED-9 QUOTATION MARK}",  # U+201F
        ),
        '"',
    ),
    **dict.fromkeys(
        (
            "\N{NO-BREAK SPACE}",  # U+00A0
            "\N{FIGURE SPACE}",  # U+2007
            "\N{THIN SPACE}",  # U+2009
            "\N{HAIR SPACE}",  # U+200A
            "\N{NARROW NO-BREAK SPACE}",  # U+202F
        ),
        " ",
    ),
}
_FOLD = str.maketrans(FOLD_TABLE)


def fold(text: str) -> str:
    """`text` with its typographic hyphens, quotation marks and spaces as ASCII (`FOLD_TABLE`):
    the same length, every other character unchanged."""
    return text.translate(_FOLD)


def directional_cue(predicate: str, quote: str) -> str | None:
    """The first words in `quote` expressing `predicate`, or None (e.g. co-mention only). Read
    through the fold; returned as the quote writes them."""
    rule = PREDICATES.get(predicate)
    if rule is None:
        return None
    folded = fold(quote)
    found = [match for cue in rule.cues if (match := cue.search(folded)) is not None]
    if not found:
        return None
    first = min(found, key=lambda match: match.start())
    return quote[first.start() : first.end()]


# --- cue proximity (pilot-fixes ticket 09) ----------------------------------------------

# Where one clause of a sentence ends and another, with its own verb, begins. Deliberately
# short: a comma alone is never a boundary (lists, places and appositives use commas inside one
# clause: "in Sherman, Texas, to address ..."), nor is a plain ", and".
CLAUSE_BOUNDARY = re.compile(
    r"(?:\s*;"
    r"|,\s+(?:while|whilst|whereas|but|although|though)(?:\s+also)?\b"
    r"|,\s+and also\b"
    r"|\s+(?:whereas|while also)\b)\s*",
    re.IGNORECASE,
)
_WORD = re.compile(r"[A-Za-z0-9][\w.-]*[A-Za-z0-9]|[A-Za-z0-9]")
# Words that name no particular input or product, alone or together. The last row (ticket 02)
# is the capacity vocabulary: "manufacturing capacity" names no product, so it is no object of
# a bottleneck predicate, and a quote naming only those words doesn't name "EML manufacturing
# capacity".
_GENERIC_WORDS = frozenset(
    {
        "a", "all", "an", "and", "any", "certain", "critical", "equipment", "goods", "important",
        "input", "inputs", "item", "items", "its", "key", "many", "material", "materials", "most",
        "of", "or", "other", "our", "package", "packages", "packaging", "part", "parts", "product",
        "products", "raw", "several", "significant", "some", "source", "sources", "strategic",
        "supplies", "supply", "the", "their", "these", "those", "used", "various", "component",
        "components", "supplier", "suppliers", "vendor", "vendors", "amount", "in", "for", "such",
        "capacity", "capacities", "manufacturing", "production", "output", "facility", "facilities",
    }
)  # fmt: skip


def clauses(quote: str) -> list[tuple[int, int]]:
    """`quote` cut at its clause boundaries (`CLAUSE_BOUNDARY`), as [start, end) spans."""
    spans: list[tuple[int, int]] = []
    start = 0
    for boundary in CLAUSE_BOUNDARY.finditer(quote):
        spans.append((start, boundary.start()))
        start = boundary.end()
    spans.append((start, len(quote)))
    return spans


def _object_clauses(quote: str, object_text: str, spans: list[tuple[int, int]]) -> set[int]:
    """The clauses of `quote` that name `object_text`: those holding an occurrence of the
    whole text (case and spacing aside), else those holding the most of its words. Empty when
    the quote names none of it."""

    def clause_of(position: int) -> int:
        return next(i for i, (_, end) in enumerate(spans) if position <= end)

    words = object_text.split()
    if not words:
        return set()
    whole = re.compile(r"\s+".join(re.escape(word) for word in words), re.IGNORECASE)
    found: set[int] = set()
    for match in whole.finditer(quote):
        found.update(range(clause_of(match.start()), clause_of(match.end()) + 1))
    if found:
        return found
    counts = [0] * len(spans)
    for word in {w.lower() for w in _WORD.findall(object_text)} - _GENERIC_WORDS:
        stem = word[:-1] if len(word) > 3 and word.endswith("s") else word
        pattern = re.compile(rf"(?<!\w){re.escape(stem)}\w*", re.IGNORECASE)
        for index in {clause_of(m.start()) for m in pattern.finditer(quote)}:
            counts[index] += 1
    best = max(counts)
    return {index for index, count in enumerate(counts) if count == best} if best else set()


def object_clause_cue(predicate: str, quote: str, object_text: str) -> str | None:
    """The first words expressing `predicate` in a clause of `quote` that names `object_text`,
    or None when every cue is in another clause ("We continue to expand our 6-inch InP
    capacity ..., while also operating multiple 6-inch GaAs VCSEL manufacturing facilities"
    has no cue for the VCSEL facilities). When the quote doesn't name the object, the clause
    can't be told, and this is the quote's first cue (`directional_cue`). Read through the
    fold; returned as the quote writes it."""
    rule = PREDICATES.get(predicate)
    if rule is None:
        return None
    folded = fold(quote)
    spans = clauses(folded)
    named = _object_clauses(folded, fold(object_text), spans)
    if not named:
        return directional_cue(predicate, quote)
    inside = [
        match
        for cue in rule.cues
        for match in cue.finditer(folded)
        if any(spans[i][0] <= match.start() and match.end() <= spans[i][1] for i in named)
    ]
    if not inside:
        return None
    first = min(inside, key=lambda match: match.start())
    return quote[first.start() : first.end()]


def names_object(quote: str, object_text: str) -> bool:
    """Whether `quote` names `object_text`: contains it whole (case and spacing aside), or at
    least half of its particular words (not `_GENERIC_WORDS`; a word counts when the quote has
    a word starting with it, less a plural "s"). The model's `object_text` paraphrases
    ("products for AI and cloud customers' data center expansion" for a quote about "demand
    from AI and cloud customers as they continue to expand their data centers"), so a verbatim
    match alone would reject the statement the pilot needed most; a quote that names none or
    few of the object's words ("InP substrates" for "indium phosphide substrates") still fails.
    Both are read through the fold."""
    quote, object_text = fold(quote), fold(object_text)
    words = object_text.split()
    if not words:
        return False
    pattern = r"\s+".join(re.escape(word) for word in words)
    if re.search(pattern, quote, re.IGNORECASE) is not None:
        return True
    particular = {w.lower() for w in _WORD.findall(object_text)} - _GENERIC_WORDS
    if not particular:
        return False
    found = 0
    for word in particular:
        stem = word[:-1] if len(word) > 3 and word.endswith("s") else word
        if re.search(rf"(?<!\w){re.escape(stem)}", quote, re.IGNORECASE):
            found += 1
    return 2 * found >= len(particular)


def is_generic_object(object_text: str) -> bool:
    """Whether `object_text` names no particular input or product: only words such as
    "materials", "components", "equipment", "suppliers" ("certain materials, equipment and
    components"), or the capacity vocabulary ("manufacturing capacity")."""
    return {w.lower() for w in _WORD.findall(fold(object_text))} <= _GENERIC_WORDS


# --- the layer rule (memory-directed reading ticket 08) ----------------------------------------


def _term_pattern(term: str) -> re.Pattern[str]:
    """A layer term as a pattern: whole words, the words joined by spaces or a hyphen, the
    last one optionally plural; an acronym (written in upper case) only as written."""
    words = r"[\s-]+".join(re.escape(word) for word in term.split())
    acronym = any(word.isupper() for word in term.split())
    return re.compile(rf"(?<!\w){words}(?:s|es)?(?!\w)", 0 if acronym else re.IGNORECASE)


_LAYER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (layer.name, _term_pattern(term)) for layer in LAYERS for term in layer.terms
)


def _layer_terms_in(folded: str) -> list[tuple[int, int, str]]:
    """Where `folded` names a layer: (start, end, layer) of each term, in text order. A term
    inside a longer term of another layer is not one ("laser" in "laser driver")."""
    found = sorted(
        (match.start(), match.end(), layer)
        for layer, pattern in _LAYER_PATTERNS
        for match in pattern.finditer(folded)
    )
    return [
        (start, end, layer)
        for start, end, layer in found
        if not any(
            other != layer and s <= start and end <= e and e - s > end - start
            for s, e, other in found
        )
    ]


def layer_term(layer: str, quote: str, object_text: str | None = None) -> str | None:
    """The words that support `layer` for a Claim, as written, or None when nothing does: a
    term of that layer (`LAYER_TERMS`) in the object text, else in the quote. For a product
    object (`object_text`) the quote is read only in the clauses that name the object (as the
    cue is: `object_clause_cue`), or whole when it names none of it; for a company object the
    whole quote is read. A word several layers share (`SHARED_LAYER_TERMS`: "InP", "indium
    phosphide", "wafer") is no term of any, so "indium phosphide capacity" supports no layer
    and "InP substrates" supports `substrate`. Read through the fold."""
    if layer not in LAYER_NAMES:
        return None
    named = (object_text or "").strip()
    if named:
        for start, end, name in _layer_terms_in(fold(named)):
            if name == layer:
                return named[start:end]
    folded = fold(quote)
    spans = clauses(folded)
    inside = _object_clauses(folded, fold(named), spans) if named else set[int]()
    scope = [spans[index] for index in sorted(inside)] or [(0, len(folded))]
    for start, end, name in _layer_terms_in(folded):
        if name == layer and any(low <= start and end <= high for low, high in scope):
            return quote[start:end]
    return None


_CORPORATE_SUFFIX = re.compile(
    r",?\s+(?:Inc\.?|Incorporated|Corp\.?|Corporation|Co\.?|Company|Ltd\.?|Limited|plc|PLC"
    r"|N\.V\.|S\.A\.|SA|AG|SE|Holdings?|Group)$"
)
_FIRST_PERSON = re.compile(
    r"\b(?:we|our|ours|the company(?:['\N{RIGHT SINGLE QUOTATION MARK}]s)?)\b", re.IGNORECASE
)


def company_names(display_name: str, legal_name: str) -> list[str]:
    """The names a text may use for a company: display and legal names, and the legal name
    without its corporate suffixes ("Lumentum Holdings Inc." → "Lumentum Holdings",
    "Lumentum"). Longest first; never shorter than three characters."""
    names = {display_name.strip(), legal_name.strip()}
    stem = legal_name.strip()
    while (shorter := _CORPORATE_SUFFIX.sub("", stem)) != stem:
        stem = shorter
        names.add(stem)
    return sorted((name for name in names if len(name) >= 3), key=lambda n: (-len(n), n))


def mentions(text: str, names: Iterable[str]) -> bool:
    """Whether `text` names the company by one of `names` (case-sensitive, whole words)."""
    return any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) for name in names)


def names_party(quote: str, names: Iterable[str], *, is_filer: bool) -> bool:
    """Whether `quote` identifies the party: by name, or in the first person if it is the
    company whose document is quoted. Read through the fold."""
    folded = fold(quote)
    return mentions(folded, [fold(name) for name in names]) or (
        is_filer and _FIRST_PERSON.search(folded) is not None
    )


# --- the filer as the unnamed party (memory-directed reading ticket 02) -----------------------

# A company written with its legal form ("Broadcom Inc.", "Sumitomo Electric Industries, Ltd."):
# up to four capitalized words, then the form. Only forms that are nothing else in a sentence
# ("Company", "Group", "Holdings", "Limited" and "SE" are left out).
_LEGAL_FORM_NAME = re.compile(
    r"(?<![\w.])(?:[A-Z][\w&'-]*\s+){0,3}[A-Z][\w&'-]*,?\s+"
    r"(?:Inc\.?|Incorporated|Corp\.?|Corporation|Co\.|Ltd\.?|LLC|plc|PLC|N\.V\.|S\.A\.|AG|GmbH"
    r"|K\.K\.)(?!\w)"
)


def stray_companies(
    quote: str, parties: Sequence[Sequence[str]], companies: Iterable[Sequence[str]]
) -> list[str]:
    """The companies `quote` names besides its parties, as it writes them: each of `companies`
    (the names lists of the companies Atlas has) that is none of `parties` and is mentioned,
    and every name written with a corporate legal form that is not a party's ("Broadcom Inc.").
    A quote that leaves the filer unnamed and names such a company could be about that
    company instead: co-mention, which proves nothing about the filer."""
    folded = fold(quote)
    party_names = {fold(name) for names in parties for name in names}
    strays: list[str] = []
    for names in companies:
        candidates = [fold(name) for name in names]
        if party_names.intersection(candidates):
            continue
        written = next((name for name in candidates if mentions(folded, [name])), None)
        if written is not None:
            strays.append(written)
    for match in _LEGAL_FORM_NAME.finditer(folded):
        written = match[0]
        known = mentions(written, party_names) or any(
            written in stray or stray in written for stray in strays
        )
        if not known:
            strays.append(written)
    return strays


# --- direction from the wording (memory-directed reading ticket 02) ---------------------------

_SHARES = r"(?i:shares|stock|securities|warrants)"
_BOUGHT = r"(?i:purchased|acquired|bought|subscribed for)"
_COMMITMENT = r"(?i:purchase (?:commitment|order)s?)"


def _party(names: Sequence[str], first_person: str | None) -> str:
    """A pattern for a party: one of its names (as written, case-sensitive), or, for the
    filer, the first-person words `first_person`."""
    written = [re.escape(fold(name)) for name in names]
    if first_person is not None:
        written.append(f"(?i:{first_person})")
    return f"(?<!\\w)(?:{'|'.join(written)})(?!\\w)"


def _holds_shares(folded: str, names: Sequence[str], *, is_filer: bool) -> bool:
    """Whether the quote makes the party the holder of shares: they were issued or sold *to*
    it, or it purchased them (or they were purchased *by* it)."""
    party = _party(names, "we|us|the company" if is_filer else None)
    patterns = (
        rf"\b(?i:issu(?:e|es|ed|ing|ance)|sold|sale|sell|sells|selling)\b.{{0,300}}?\b{_SHARES}\b"
        rf".{{0,300}}?\bto\s+(?:the\s+)?{party}",
        rf"{party}.{{0,60}}?\b{_BOUGHT}\b.{{0,200}}?\b{_SHARES}\b",
        rf"\b{_SHARES}\b.{{0,200}}?\b{_BOUGHT} by\s+(?:the\s+)?{party}",
    )
    return any(re.search(pattern, folded, re.DOTALL) for pattern in patterns)


def _commits_to_purchase(folded: str, names: Sequence[str], *, is_filer: bool) -> bool:
    """Whether the quote gives a purchase commitment or order as the party's ("an NVIDIA
    multi-billion-dollar purchase commitment", "purchase orders by NVIDIA"): it is the buyer.
    "A purchase commitment with X" names no buyer."""
    party = _party(names, "our|the company's" if is_filer else None)
    patterns = (
        rf"{party}(?:'s)?\s+(?:[\w$.,-]+\s+){{0,4}}?{_COMMITMENT}\b",
        rf"\b{_COMMITMENT} (?i:by|of)\s+(?:the\s+)?{party}",
    )
    return any(re.search(pattern, folded, re.DOTALL) for pattern in patterns)


def direction_refusal(
    predicate: str,
    quote: str,
    subject: Sequence[str],
    counterpart: Sequence[str],
    *,
    filer: Literal["subject", "object"] | None = None,
) -> str | None:
    """Why the wording of `quote` gives `predicate` the other way round between the subject
    and the object company (`counterpart`), each by its names (`filer`: the one whose document
    it is, which the first person also names); None when the wording doesn't say.

    - `owns`: in a sentence of issuance or purchase ("issued and sold ... shares ... to X",
      "X purchased ... shares", "shares ... purchased by X") X is the holder, so X is the
      subject. The issuer as subject is refused.
    - `supplies`, `buys_from`: "an X purchase commitment" (or "purchase orders by X") makes X
      the buyer: the object of `supplies`, the subject of `buys_from`.

    Only a sentence that makes exactly one of the two the holder (or buyer) is judged."""
    folded = fold(quote)
    name, other = subject[0], counterpart[0]
    if predicate == "owns":
        subject_holds = _holds_shares(folded, subject, is_filer=filer == "subject")
        object_holds = _holds_shares(folded, counterpart, is_filer=filer == "object")
        if object_holds and not subject_holds:
            return (
                f"the quote says the shares were issued or sold to, or purchased by, {other}:"
                f" {other} is the holder and {name} the issuer, and `owns` runs from the holder"
                f" to the issuer ({other} owns {name}, not {name} owns {other})"
            )
    elif predicate in ("supplies", "buys_from"):
        subject_buys = _commits_to_purchase(folded, subject, is_filer=filer == "subject")
        object_buys = _commits_to_purchase(folded, counterpart, is_filer=filer == "object")
        if predicate == "buys_from" and object_buys and not subject_buys:
            return (
                f"the quote gives the purchase commitment as {other}'s: {other} is the buyer,"
                f" so the relation runs the other way ({name} supplies {other}, not {name}"
                f" buys_from {other})"
            )
        if predicate == "supplies" and subject_buys and not object_buys:
            return (
                f"the quote gives the purchase commitment as {name}'s: {name} is the buyer,"
                f" so the relation runs the other way ({name} buys_from {other}, not {name}"
                f" supplies {other})"
            )
    return None
