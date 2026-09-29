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
    LAYER_NAMES,
    LAYERS,
    PREDICATES,
    Layer,
    LayerDefinition,
    Predicate,
    company_names,
    directional_cue,
    mentions,
    names_party,
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
    "company_names",
    "directional_cue",
    "extract_claims_payload",
    "get_claim",
    "get_extraction",
    "list_claims",
    "mentions",
    "names_party",
    "predicate_refusal",
    "register_claim_handlers",
]
