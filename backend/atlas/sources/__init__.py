"""Source adapters: discover and fetch source material (spec Part A, Source adapters)."""

from atlas.sources.adapter import (
    AvailabilityBasis,
    CandidateKind,
    ExchangeAnnouncement,
    FetchAttempt,
    FetchedDocument,
    FetchError,
    HttpValidators,
    ManualImport,
    SearchQuery,
    SecFiling,
    SourceAdapter,
    SourceCandidate,
    TradingViewTranscript,
)
from atlas.sources.edgar import (
    EdgarAdapter,
    filing_availability,
    keep_8k_document,
    live_edgar_adapter,
)
from atlas.sources.edgar_calendar import (
    EDGAR_CALENDAR_RANGE,
    EdgarCalendarRangeError,
    edgar_dissemination_time,
    is_edgar_business_day,
)
from atlas.sources.edgar_fixtures import FixtureReplay, fixture_edgar_adapter
from atlas.sources.sec_http import SEC_RATE_LIMITER, HttpResult, SecHttpClient, TokenBucket

__all__ = [
    "EDGAR_CALENDAR_RANGE",
    "SEC_RATE_LIMITER",
    "AvailabilityBasis",
    "CandidateKind",
    "EdgarAdapter",
    "EdgarCalendarRangeError",
    "ExchangeAnnouncement",
    "FetchAttempt",
    "FetchError",
    "FetchedDocument",
    "FixtureReplay",
    "HttpResult",
    "HttpValidators",
    "ManualImport",
    "SearchQuery",
    "SecFiling",
    "SecHttpClient",
    "SourceAdapter",
    "SourceCandidate",
    "TokenBucket",
    "TradingViewTranscript",
    "edgar_dissemination_time",
    "filing_availability",
    "fixture_edgar_adapter",
    "is_edgar_business_day",
    "keep_8k_document",
    "live_edgar_adapter",
]
