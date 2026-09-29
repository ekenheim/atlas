"""The SEC EDGAR source adapter (build plan §4.2, item 1).

Discovery reads each filer's submissions index (data.sec.gov) and lists, per target filing
(10-K, 10-Q, 8-K and their amendments by default), its primary document and, for 8-Ks, its
press-release exhibits (EX-99.*, found in the filing's index headers). Each filer's XBRL
companyfacts is listed too and fetched raw, never interpreted here.

`available_at` for filing documents is EDGAR's `acceptanceDateTime` (basis
`sec_acceptance`). The submissions index gives it in UTC: its trailing "Z" is genuine, as
the filing headers' Eastern-time ACCEPTANCE-DATETIME confirms. companyfacts has no
acceptance time, so it falls back to the observed discovery time.

The submissions index's `filings.files` (older pages) is not followed: `filings.recent`
holds the latest 1,000 filings, years more than the pilot's backfill window.
"""

import re
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from html import unescape

from pydantic import BaseModel, ConfigDict, Field

from atlas.sources.adapter import (
    FetchedDocument,
    HttpValidators,
    SearchQuery,
    SecFiling,
    SourceCandidate,
)
from atlas.sources.sec_http import SecHttpClient

PROVIDER_ID = "sec_edgar"
DEFAULT_FORMS = ("10-K", "10-Q", "8-K")
DEFAULT_EXHIBIT_PREFIXES = ("EX-99",)

_DOCUMENT_ENTRY = re.compile(
    r"<DOCUMENT>\s*<TYPE>(?P<type>[^\s<]+)\s*<SEQUENCE>\d+\s*<FILENAME>(?P<filename>[^\s<]+)"
)


def normalize_cik(cik: str) -> str:
    """'1633978', '0001633978' or 'CIK0001633978' -> '0001633978'."""
    digits = cik.strip().upper().removeprefix("CIK")
    if not digits.isdigit() or len(digits) > 10:
        raise ValueError(f"not a SEC CIK: {cik!r}")
    return digits.zfill(10)


def parse_acceptance_datetime(value: str) -> datetime:
    """EDGAR's acceptanceDateTime, e.g. '2026-08-11T20:24:11.000Z', as an aware UTC datetime."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"acceptanceDateTime without a time zone: {value!r}")
    return parsed.astimezone(UTC)


class _RecentFilings(BaseModel):
    """The column-oriented `filings.recent` block of a submissions index."""

    model_config = ConfigDict(populate_by_name=True)

    accession_number: list[str] = Field(alias="accessionNumber")
    filing_date: list[str] = Field(alias="filingDate")
    report_date: list[str] = Field(alias="reportDate")
    acceptance_datetime: list[str] = Field(alias="acceptanceDateTime")
    form: list[str]
    items: list[str]
    primary_document: list[str] = Field(alias="primaryDocument")


class _Filings(BaseModel):
    recent: _RecentFilings


class _Submissions(BaseModel):
    cik: str
    name: str
    filings: _Filings


def parse_submissions(content: bytes) -> list[SecFiling]:
    """Every filing in a submissions index's `filings.recent`, newest first as EDGAR lists them."""
    index = _Submissions.model_validate_json(content)
    recent = index.filings.recent
    cik = normalize_cik(index.cik)
    return [
        SecFiling(
            cik=cik,
            company_name=index.name,
            accession_number=recent.accession_number[i],
            form=recent.form[i],
            filing_date=date.fromisoformat(recent.filing_date[i]),
            report_date=date.fromisoformat(recent.report_date[i])
            if recent.report_date[i]
            else None,
            acceptance_datetime=parse_acceptance_datetime(recent.acceptance_datetime[i]),
            primary_document=recent.primary_document[i],
            items=tuple(item for item in recent.items[i].split(",") if item),
        )
        for i in range(len(recent.accession_number))
    ]


def parse_index_headers(content: bytes) -> list[tuple[str, str]]:
    """(document type, file name) for each document in a filing's `-index-headers.html`."""
    text = unescape(content.decode("utf-8", errors="replace"))
    return [(m["type"], m["filename"]) for m in _DOCUMENT_ENTRY.finditer(text)]


class EdgarAdapter:
    """SEC EDGAR, for the filers (CIKs) it is configured with."""

    provider_id: str = PROVIDER_ID

    def __init__(
        self,
        client: SecHttpClient,
        *,
        ciks: Sequence[str],
        forms: Sequence[str] = DEFAULT_FORMS,
        exhibit_prefixes: Sequence[str] = DEFAULT_EXHIBIT_PREFIXES,
        eight_k_items: Sequence[str] | None = None,
        exhibits_only_items: Sequence[str] = (),
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        data_base_url: str = "https://data.sec.gov",
        archives_base_url: str = "https://www.sec.gov",
    ) -> None:
        self._client = client
        self._ciks = [normalize_cik(cik) for cik in ciks]
        self._forms = tuple(forms)
        self._exhibit_prefixes = tuple(exhibit_prefixes)
        # 8-K selection: None keeps every 8-K; otherwise only 8-Ks listing one of these items.
        self._eight_k_items = frozenset(eight_k_items) if eight_k_items is not None else None
        # An 8-K whose items all fall in this set is a press release: its exhibits carry the
        # substance and its cover document is skipped (when it has exhibits to keep).
        self._exhibits_only_items = frozenset(exhibits_only_items)
        self._now = now
        self._data = data_base_url.rstrip("/")
        self._archives = archives_base_url.rstrip("/")
        # Last submissions index per URL, so a re-check can be conditional.
        self._indexes: dict[str, tuple[HttpValidators, bytes]] = {}

    async def filings(self, cik: str) -> list[SecFiling]:
        """The filer's recent filings from its submissions index (re-checked conditionally)."""
        url = f"{self._data}/submissions/CIK{normalize_cik(cik)}.json"
        cached = self._indexes.get(url)
        result = await self._client.get(url, cached[0] if cached else None)
        if result.not_modified and cached:
            content = cached[1]
        else:
            content = result.content
        self._indexes[url] = (result.validators, content)
        return parse_submissions(content)

    async def discover(self, query: SearchQuery) -> list[SourceCandidate]:
        ciks = [normalize_cik(query.cik)] if query.cik else self._ciks
        candidates: list[SourceCandidate] = []
        for cik in ciks:
            candidates += await self._discover(cik, query, companyfacts_always=True)
        return candidates

    async def updates(self, since: datetime) -> list[SourceCandidate]:
        """Filings accepted after `since`, plus companyfacts for each filer that has any."""
        query = SearchQuery(since=since)
        candidates: list[SourceCandidate] = []
        for cik in self._ciks:
            candidates += await self._discover(cik, query, companyfacts_always=False)
        return candidates

    async def fetch(self, candidate: SourceCandidate) -> FetchedDocument:
        if candidate.provider_id != self.provider_id:
            raise ValueError(f"not an EDGAR candidate: {candidate.provider_id}")
        result = await self._client.get(candidate.url, candidate.validators)
        return FetchedDocument(
            candidate=candidate,
            url=result.url,
            fetched_at=self._now(),
            not_modified=result.not_modified,
            content=result.content,
            media_type=result.media_type,
            validators=result.validators,
            attempts=result.attempts,
        )

    async def _discover(
        self, cik: str, query: SearchQuery, *, companyfacts_always: bool
    ) -> list[SourceCandidate]:
        forms = query.forms or self._forms
        discovered_at = self._now()
        selected = [
            filing
            for filing in await self.filings(cik)
            if (filing.form in forms or filing.form.removesuffix("/A") in forms)
            and (query.since is None or filing.acceptance_datetime > query.since)
            and self._selected_8k(filing)
        ]
        selected.sort(key=lambda filing: filing.acceptance_datetime, reverse=True)
        if query.limit is not None:
            selected = selected[: query.limit]

        candidates: list[SourceCandidate] = []
        for filing in selected:
            body = self._document(filing, filing.form, filing.primary_document, discovered_at)
            if _is_8k(filing) and self._exhibit_prefixes:
                exhibits = await self._exhibits(filing, discovered_at)
                press_release = (
                    bool(filing.items) and set(filing.items) <= self._exhibits_only_items
                )
                if not (press_release and exhibits):
                    candidates.append(body)
                candidates += exhibits
            else:
                candidates.append(body)
        if selected or companyfacts_always:
            candidates.append(self._companyfacts(cik, discovered_at))
        return candidates

    def _selected_8k(self, filing: SecFiling) -> bool:
        if not _is_8k(filing):
            return True
        return keep_8k_document(
            filing.items,
            is_cover=False,
            has_exhibits=False,
            eight_k_items=tuple(self._eight_k_items) if self._eight_k_items is not None else None,
            exhibits_only_items=(),
        )

    def _folder(self, filing: SecFiling) -> str:
        accession = filing.accession_number.replace("-", "")
        return f"{self._archives}/Archives/edgar/data/{int(filing.cik)}/{accession}"

    async def _exhibits(self, filing: SecFiling, discovered_at: datetime) -> list[SourceCandidate]:
        url = f"{self._folder(filing)}/{filing.accession_number}-index-headers.html"
        result = await self._client.get(url)
        return [
            self._document(filing, document_type, filename, discovered_at)
            for document_type, filename in parse_index_headers(result.content)
            if document_type.startswith(self._exhibit_prefixes)
        ]

    def _document(
        self, filing: SecFiling, document_type: str, filename: str, discovered_at: datetime
    ) -> SourceCandidate:
        title = f"{filing.company_name} {filing.form} filed {filing.filing_date.isoformat()}"
        if document_type != filing.form:
            title += f", {document_type}"
        return SourceCandidate(
            provider_id=self.provider_id,
            kind="sec_filing_document",
            url=f"{self._folder(filing)}/{filename}",
            title=title,
            document_type=document_type,
            discovered_at=discovered_at,
            available_at=filing.acceptance_datetime,
            available_at_basis="sec_acceptance",
            filing=filing,
        )

    def _companyfacts(self, cik: str, discovered_at: datetime) -> SourceCandidate:
        return SourceCandidate(
            provider_id=self.provider_id,
            kind="sec_companyfacts",
            url=f"{self._data}/api/xbrl/companyfacts/CIK{cik}.json",
            title=f"XBRL companyfacts for CIK {cik}",
            discovered_at=discovered_at,
            available_at=discovered_at,
            available_at_basis="observed_discovery",
        )


def _is_8k(filing: SecFiling) -> bool:
    return filing.form.removesuffix("/A") == "8-K"


def keep_8k_document(
    items: Sequence[str],
    *,
    is_cover: bool,
    has_exhibits: bool,
    eight_k_items: Sequence[str] | None,
    exhibits_only_items: Sequence[str],
) -> bool:
    """Whether a document of an 8-K is worth ingesting and retaining (docs/decisions.md).

    An 8-K is kept only if it lists one of `eight_k_items` (None keeps every 8-K). A kept
    8-K whose items all fall in `exhibits_only_items` is a press release: its cover document
    is dropped when it has exhibits, which carry the substance.
    """
    if eight_k_items is not None and not set(eight_k_items).intersection(items):
        return False
    press_release = bool(items) and set(items) <= set(exhibits_only_items)
    return not (is_cover and press_release and has_exhibits)


def live_edgar_adapter(user_agent: str, *, ciks: Sequence[str]) -> EdgarAdapter:
    """The adapter against real SEC endpoints, under the process-wide SEC rate limiter."""
    return EdgarAdapter(SecHttpClient(user_agent), ciks=ciks)
