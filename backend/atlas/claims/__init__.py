"""Claims: the Investigator's span-backed proposals, checked and turned into Assertions.

`predicates` holds the §5.5 whitelist with its direction rules, the layer taxonomy and the
directional-language and party checks; `extraction` runs the `extract_claims` job (passages,
Investigator calls, checks, outcomes); `reads` lists Claims and extractions.
"""

from atlas.claims.extraction import (
    EXTRACT_CLAIMS_KIND,
    EXTRACTOR_VERSION,
    INVESTIGATOR_ACTOR,
    ClaimExtractor,
    ExtractClaimsPayload,
    extract_claims_payload,
)
from atlas.claims.handlers import register_claim_handlers
from atlas.claims.predicates import (
    BOTTLENECK_PREDICATES,
    CLAUSE_BOUNDARY,
    LAYER_NAMES,
    LAYERS,
    PREDICATES,
    Layer,
    LayerDefinition,
    Predicate,
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
from atlas.claims.reads import (
    Claim,
    ClaimExtraction,
    ClaimOutcome,
    Passage,
    get_claim,
    get_extraction,
    list_claims,
)

__all__ = [
    "BOTTLENECK_PREDICATES",
    "CLAUSE_BOUNDARY",
    "EXTRACTOR_VERSION",
    "EXTRACT_CLAIMS_KIND",
    "INVESTIGATOR_ACTOR",
    "LAYERS",
    "LAYER_NAMES",
    "PREDICATES",
    "Claim",
    "ClaimExtraction",
    "ClaimExtractor",
    "ClaimOutcome",
    "ExtractClaimsPayload",
    "Layer",
    "LayerDefinition",
    "Passage",
    "Predicate",
    "clauses",
    "company_names",
    "directional_cue",
    "extract_claims_payload",
    "get_claim",
    "get_extraction",
    "is_generic_object",
    "list_claims",
    "mentions",
    "names_object",
    "names_party",
    "object_clause_cue",
    "predicate_refusal",
    "register_claim_handlers",
]
