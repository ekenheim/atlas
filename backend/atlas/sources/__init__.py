"""Source adapters: discover and fetch source material (spec Part A, Source adapters)."""

from atlas.sources.adapter import (
    AvailabilityBasis,
    CandidateKind,
    FetchAttempt,
    FetchedDocument,
    FetchError,
    HttpValidators,
    SearchQuery,
    SecFiling,
    SourceAdapter,
    SourceCandidate,
)
from atlas.sources.edgar import EdgarAdapter, keep_8k_document, live_edgar_adapter
from atlas.sources.edgar_fixtures import FixtureReplay, fixture_edgar_adapter
from atlas.sources.sec_http import SEC_RATE_LIMITER, HttpResult, SecHttpClient, TokenBucket

__all__ = [
    "SEC_RATE_LIMITER",
    "AvailabilityBasis",
    "CandidateKind",
    "EdgarAdapter",
    "FetchAttempt",
    "FetchError",
    "FetchedDocument",
    "FixtureReplay",
    "HttpResult",
    "HttpValidators",
    "SearchQuery",
    "SecFiling",
    "SecHttpClient",
    "SourceAdapter",
    "SourceCandidate",
    "TokenBucket",
    "fixture_edgar_adapter",
    "keep_8k_document",
    "live_edgar_adapter",
]
