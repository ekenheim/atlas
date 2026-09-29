"""The common source-adapter protocol (build plan §4.2) and the models it exchanges.

An adapter discovers `SourceCandidate`s and fetches each into a `FetchedDocument`: the raw
bytes plus how and when they were obtained. Adapters never create Source Versions; the
ingestion service (the source ledger) does that from what they return.
"""

from datetime import date, datetime
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

# How `available_at` was determined (spec Part A, Source ledger). `sec_dissemination`: an
# EDGAR filing accepted outside the dissemination window, public at the next opening.
AvailabilityBasis = Literal[
    "sec_acceptance", "sec_dissemination", "publisher_timestamp", "observed_discovery"
]
CandidateKind = Literal[
    "sec_filing_document", "sec_companyfacts", "exchange_announcement", "manual_import"
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class HttpValidators(_Frozen):
    """Cache validators from a response, echoed back verbatim on the next conditional request."""

    etag: str | None = None
    last_modified: str | None = None


class FetchAttempt(_Frozen):
    """One HTTP attempt: its outcome and, if another attempt followed, the wait before it."""

    attempt: int
    status: int | None = None  # None when no response arrived (timeout, network error)
    error: str | None = None
    retry_after_s: float | None = None  # what the server asked for via Retry-After
    delay_s: float | None = None  # the wait actually taken before the next attempt


class FetchError(Exception):
    """A fetch that did not produce a document. `retryable` tells a job whether trying again
    later can help (throttling, server errors, timeouts) or not (other 4xx)."""

    def __init__(
        self,
        message: str,
        *,
        url: str,
        status: int | None,
        retryable: bool,
        attempts: tuple[FetchAttempt, ...],
    ) -> None:
        super().__init__(message)
        self.url = url
        self.status = status
        self.retryable = retryable
        self.attempts = attempts


class SecFiling(_Frozen):
    """One EDGAR filing, as listed in the filer's submissions index."""

    cik: str  # ten digits, zero-padded
    company_name: str
    accession_number: str  # with dashes, e.g. 0001628280-26-055726
    form: str
    filing_date: date
    report_date: date | None
    acceptance_datetime: AwareDatetime  # EDGAR's acceptanceDateTime, in UTC
    primary_document: str
    items: tuple[str, ...] = ()


class ExchangeAnnouncement(_Frozen):
    """One document an exchange's disclosure feed lists (HKEXnews, LSE RNS, Euronext), with
    what the feed says about it. It describes the Source Document the ledger records."""

    publisher: str  # the feed, e.g. "HKEXnews"; the Source Document's publisher
    announcement_id: str  # the feed's own identifier, e.g. HKEXnews NEWS_ID
    issuer_code: str  # the exchange's code for the issuer, e.g. "03308"
    issuer_name: str  # as the feed names it
    category: str | None = None  # the feed's classification, e.g. "[Interim/Half-Year Report]"
    file_type: str | None = None  # as the feed says, e.g. "PDF"
    published_at: AwareDatetime  # the feed's publication timestamp, in UTC
    published_local: str  # the timestamp exactly as the feed printed it
    timezone: str  # the IANA zone the feed's timestamp is in, e.g. "Asia/Hong_Kong"


class ManualImport(_Frozen):
    """A document the owner fetched by hand and imported (`atlas sources import`), with
    where it came from; it describes the Source Document the ledger records."""

    publisher: str  # who published it, e.g. "HKEXnews"
    file_name: str  # the imported file's name
    imported_by: str  # the actor who imported it
    published_local: str  # the publication time exactly as the owner gave it


class SearchQuery(_Frozen):
    """What to discover. Each adapter uses the fields that apply to it."""

    text: str | None = None
    cik: str | None = None  # SEC filer; None means every filer the adapter is configured for
    forms: tuple[str, ...] | None = None  # None means the adapter's default forms
    since: AwareDatetime | None = None  # only material that became available after this
    limit: int | None = None  # at most this many of the most recent items


class SourceCandidate(_Frozen):
    """A piece of source material that can be fetched, identified by its canonical URL."""

    provider_id: str
    kind: CandidateKind
    url: str
    title: str
    document_type: str | None = None  # e.g. "10-K", "EX-99.1"
    discovered_at: AwareDatetime
    available_at: AwareDatetime
    available_at_basis: AvailabilityBasis
    filing: SecFiling | None = None
    announcement: ExchangeAnnouncement | None = None
    manual: ManualImport | None = None
    validators: HttpValidators | None = None  # from the last fetch; makes the next conditional
    # The document's language as the source declares it (ISO 639 primary subtag, e.g. "en",
    # "zh"), if it does; otherwise the ledger records the language the parse finds.
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")


class FetchedDocument(_Frozen):
    """The outcome of fetching a candidate: raw bytes exactly as served, or `not_modified`."""

    candidate: SourceCandidate
    url: str  # the final URL, after redirects
    fetched_at: AwareDatetime
    not_modified: bool
    content: bytes  # empty when not_modified
    media_type: str | None
    validators: HttpValidators
    attempts: tuple[FetchAttempt, ...]


class SourceAdapter(Protocol):
    provider_id: str

    async def discover(self, query: SearchQuery) -> list[SourceCandidate]: ...

    async def fetch(self, candidate: SourceCandidate) -> FetchedDocument: ...

    async def updates(self, since: datetime) -> list[SourceCandidate]: ...
