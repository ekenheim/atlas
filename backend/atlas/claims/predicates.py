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

**Layers.** Every Claim carries the supply-chain layer of what the link is about (ticket 12
tags Relationships with it): substrate → epi → chip/laser → DSP → module → system, plus
contract manufacturing, as slugs.

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
"""

import re
from collections.abc import Iterable
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


# Upstream to downstream; contract manufacturing is a service layer beside module/system.
LAYERS: tuple[LayerDefinition, ...] = (
    LayerDefinition("substrate", "bare wafers and substrates (InP, GaAs, SOI)"),
    LayerDefinition("epi", "epitaxial wafers grown on substrates"),
    LayerDefinition(
        "chip-laser", "laser and photonic chips: EML, DML, CW and VCSEL lasers, PICs, photodiodes"
    ),
    LayerDefinition("dsp", "DSPs, drivers, TIAs and other electrical ICs for optics"),
    LayerDefinition("module", "optical transceivers and modules"),
    LayerDefinition(
        "contract-manufacturing", "assembly, test and contract manufacturing of optics"
    ),
    LayerDefinition(
        "system", "systems built from modules: optical transport, switches, AI clusters"
    ),
)
LAYER_NAMES: frozenset[str] = frozenset(layer.name for layer in LAYERS)


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
        "the subject company owns all or part of the object company",
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
            r"\ballocat\w*",
            r"\bdemand (?:exceed|exceeds|exceeded|exceeding|outpac\w*|outstrip\w*|outgrew)\b",
            r"\b(?:exceed|exceeds|exceeded|exceeding) (?:our )?(?:supply|capacity)\b",
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


def directional_cue(predicate: str, quote: str) -> str | None:
    """The first words in `quote` expressing `predicate`, or None (e.g. co-mention only)."""
    rule = PREDICATES.get(predicate)
    if rule is None:
        return None
    found = [match for cue in rule.cues if (match := cue.search(quote)) is not None]
    return min(found, key=lambda match: match.start())[0] if found else None


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
# Words that name no particular input or product, alone or together.
_GENERIC_WORDS = frozenset(
    {
        "a", "all", "an", "and", "any", "certain", "critical", "equipment", "goods", "important",
        "input", "inputs", "item", "items", "its", "key", "many", "material", "materials", "most",
        "of", "or", "other", "our", "package", "packages", "packaging", "part", "parts", "product",
        "products", "raw", "several", "significant", "some", "source", "sources", "strategic",
        "supplies", "supply", "the", "their", "these", "those", "used", "various", "component",
        "components", "supplier", "suppliers", "vendor", "vendors", "amount", "in", "for", "such",
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
    can't be told, and this is the quote's first cue (`directional_cue`)."""
    rule = PREDICATES.get(predicate)
    if rule is None:
        return None
    spans = clauses(quote)
    named = _object_clauses(quote, object_text, spans)
    if not named:
        return directional_cue(predicate, quote)
    inside = [
        match
        for cue in rule.cues
        for match in cue.finditer(quote)
        if any(spans[i][0] <= match.start() and match.end() <= spans[i][1] for i in named)
    ]
    return min(inside, key=lambda match: match.start())[0] if inside else None


def names_object(quote: str, object_text: str) -> bool:
    """Whether `quote` contains `object_text` (case and spacing aside)."""
    words = object_text.split()
    pattern = r"\s+".join(re.escape(word) for word in words)
    return bool(words) and re.search(pattern, quote, re.IGNORECASE) is not None


def is_generic_object(object_text: str) -> bool:
    """Whether `object_text` names no particular input or product: only words such as
    "materials", "components", "equipment", "suppliers" ("certain materials, equipment and
    components")."""
    return {w.lower() for w in _WORD.findall(object_text)} <= _GENERIC_WORDS


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
    company whose document is quoted."""
    return mentions(quote, names) or (is_filer and _FIRST_PERSON.search(quote) is not None)
