"""Research queries over Memory, with every citation resolved to Evidence (spec Part B).

`service` runs scoped recall and the `reflect` job, `provenance` resolves memories and quotes
back to Source Version sections, `quotes` holds the quote normalization rule, and `reads`
serves stored research answers to the API.
"""

from atlas.research.handlers import register_research_handlers
from atlas.research.provenance import (
    Citation,
    CitationSource,
    CitationState,
    Evidence,
    ProvenanceResolver,
    QuoteSpan,
)
from atlas.research.quotes import QUOTE_RULE
from atlas.research.reads import ResearchAnswer, research_answer
from atlas.research.service import (
    REFLECT_KIND,
    AppliedScope,
    RecallRequest,
    RecallResponse,
    ReflectRequest,
    Research,
    ResearchRefused,
    ResearchScope,
)

__all__ = [
    "QUOTE_RULE",
    "REFLECT_KIND",
    "AppliedScope",
    "Citation",
    "CitationSource",
    "CitationState",
    "Evidence",
    "ProvenanceResolver",
    "QuoteSpan",
    "RecallRequest",
    "RecallResponse",
    "ReflectRequest",
    "Research",
    "ResearchAnswer",
    "ResearchRefused",
    "ResearchScope",
    "register_research_handlers",
    "research_answer",
]
