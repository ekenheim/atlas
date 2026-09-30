"""The EDGAR full-text search client: discovery's primary-source channel (pilot fix 12).

One search is `GET <sec_efts_url>/search-index?q=...&forms=...&dateRange=custom&startdt=
&enddt=`, keyless, through the SEC HTTP client (atlas.sources.sec_http: the SEC User-Agent
with its contact email, the process-wide 10 requests/s limit, retries with backoff). `q` is
each phrase in double quotes, so EDGAR matches it exactly (`"InP substrates"`); `forms` the
comma-separated form types (10-K, 10-Q, 8-K, 20-F, 6-K, 40-F by default); the date range
is on the filing date.

The answer (EDGAR full-text search FAQ, https://www.sec.gov/edgar/search/efts-faq.html; the
recorded fixture `tests/fixtures/edgar-fts/`) is an Elasticsearch result: `hits.total.value`
and `hits.hits[]`, one per matching document, each with `_id` (`<accession>:<file name>`)
and `_source`: `ciks` and `display_names` (the filers, e.g. `AXT INC  (AXTI)  (CIK
0001051627)`), `form`, `file_type` (the document's type: the form itself, or an exhibit such
as `EX-99.1`), `file_date`, `period_ending` and `adsh` (the accession number). No text
snippet comes back. Only those fields are read. A hit becomes a `FilingHit` whose URL is the
document's in the EDGAR archive, as the EDGAR adapter builds it
(`https://www.sec.gov/Archives/edgar/data/<CIK>/<accession without dashes>/<file name>`), so
a filing Atlas has ingested has the same canonical URL.

Every failure (an HTTP error after the client's retries, a body that isn't the expected
JSON) raises `FilingSearchFailed`, an ordinary error: like SearXNG, EDGAR full-text search
never pauses the queue.
"""

import asyncio
import re
from collections.abc import Sequence
from datetime import date
from typing import Self
from urllib.parse import urlencode

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from atlas.settings import Settings
from atlas.sources.adapter import FetchError
from atlas.sources.sec_http import SEC_RATE_LIMITER, SecHttpClient, TokenBucket

FORMS = ("10-K", "10-Q", "8-K", "20-F", "6-K", "40-F")
_ERROR_TEXT_LIMIT = 300
_QUOTED = re.compile(r'"([^"]+)"')
_SPACE = re.compile(r"\s+")
_DISPLAY_NAME = re.compile(
    r"^(?P<name>.*?)\s*(?:\((?P<tickers>[^()]*)\)\s*)?\(CIK (?P<cik>\d{1,10})\)\s*$"
)
_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")


class FilingSearchFailed(Exception):
    """An EDGAR full-text search failed; the message says how."""


class FilingHit(BaseModel):
    """One document an EDGAR full-text search returned."""

    model_config = ConfigDict(frozen=True)

    position: int  # 1-based, in EDGAR's order
    cik: str  # the (first) filer's, 10 digits
    filer: str  # its name as EDGAR displays it, without ticker and CIK
    ticker: str | None  # the first ticker EDGAR displays for it
    form: str  # the filing's form type
    file_type: str | None  # the document's type (the form itself, or an exhibit)
    file_date: date
    period_ending: date | None
    accession: str  # 0001437749-26-008612
    document: str  # the document's file name in the filing
    url: str  # the document in the EDGAR archive

    @property
    def title(self) -> str:
        """`<filer> <form> filed <date>`, with the document type when it isn't the form."""
        title = f"{self.filer} {self.form} filed {self.file_date.isoformat()}"
        if self.file_type and self.file_type != self.form:
            title += f", {self.file_type}"
        return title


class FilingSearch(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str  # the `q` sent
    total: int  # the documents EDGAR matched (it pages them; only the first are kept)
    hits: list[FilingHit]


class _Source(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ciks: list[str]
    display_names: list[str] = []
    form: str
    file_type: str | None = None
    file_date: date
    period_ending: date | None = None
    adsh: str


class _Hit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(alias="_id")
    source: _Source = Field(alias="_source")


class _Total(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: int


class _Hits(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total: _Total
    hits: list[_Hit]


class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hits: _Hits


def filing_phrases(filing_phrase: str | None) -> list[str]:
    """The exact phrases a filing phrase asks for: its double-quoted parts when it has any,
    else the whole of it; blanks dropped, spaces collapsed."""
    if filing_phrase is None:
        return []
    quoted = _QUOTED.findall(filing_phrase)
    parts = quoted if quoted else [filing_phrase.replace('"', " ")]
    phrases = [_SPACE.sub(" ", part).strip() for part in parts]
    return list(dict.fromkeys(phrase for phrase in phrases if phrase))


def filing_query(phrases: Sequence[str]) -> str:
    """EDGAR's `q` for the phrases: each in double quotes (an exact-phrase match)."""
    if not phrases:
        raise ValueError("an EDGAR full-text search needs at least one phrase")
    return " ".join(f'"{phrase}"' for phrase in phrases)


def _filer(display_name: str, cik: str) -> tuple[str, str | None]:
    """(name, first ticker) from EDGAR's display name `NAME  (TICKER, ...)  (CIK ##########)`."""
    match = _DISPLAY_NAME.match(display_name.strip())
    if match is None or match["cik"].zfill(10) != cik:
        return _SPACE.sub(" ", display_name).strip() or f"CIK {cik}", None
    name = _SPACE.sub(" ", match["name"]).strip() or f"CIK {cik}"
    tickers = [t.strip() for t in (match["tickers"] or "").split(",") if t.strip()]
    return name, tickers[0] if tickers else None


def parse_filing_search(
    query: str, content: bytes, *, max_hits: int, archives_url: str = "https://www.sec.gov"
) -> FilingSearch:
    """The first `max_hits` documents of an EDGAR full-text search answer (see the module).
    A hit without a filer CIK, an accession number or a document name is skipped."""
    try:
        body = _Response.model_validate_json(content)
    except ValidationError as error:
        raise FilingSearchFailed(f"EDGAR full-text search: unexpected response: {error}") from None
    hits: list[FilingHit] = []
    for hit in body.hits.hits:
        source = hit.source
        accession, _, document = hit.id.partition(":")
        if not source.ciks or not document or not _ACCESSION.match(source.adsh):
            continue
        if accession != source.adsh:
            continue
        cik = source.ciks[0].strip().zfill(10)
        if not cik.isdigit() or len(cik) != 10:
            continue
        filer, ticker = _filer(source.display_names[0] if source.display_names else "", cik)
        folder = f"{archives_url.rstrip('/')}/Archives/edgar/data/{int(cik)}"
        hits.append(
            FilingHit(
                position=len(hits) + 1,
                cik=cik,
                filer=filer,
                ticker=ticker,
                form=source.form,
                file_type=source.file_type,
                file_date=source.file_date,
                period_ending=source.period_ending,
                accession=source.adsh,
                document=document,
                url=f"{folder}/{source.adsh.replace('-', '')}/{document}",
            )
        )
        if len(hits) == max_hits:
            break
    return FilingSearch(query=query, total=body.hits.total.value, hits=hits)


class EdgarFullTextSearch:
    """EDGAR full-text search under SEC's fair-access rules (see the module)."""

    def __init__(
        self,
        user_agent: str,
        *,
        base_url: str = "https://efts.sec.gov/LATEST",
        archives_url: str = "https://www.sec.gov",
        forms: Sequence[str] = FORMS,
        max_hits: int = 10,
        transport: httpx2.AsyncBaseTransport | None = None,
        limiter: TokenBucket = SEC_RATE_LIMITER,
        max_attempts: int = 3,
        backoff_base_s: float = 1.0,
        max_retry_after_s: float = 30.0,
    ) -> None:
        if not forms:
            raise ValueError("name at least one form type")
        if max_hits < 1:
            raise ValueError("keep at least one hit")
        self.user_agent = user_agent
        self.forms = tuple(forms)
        self.max_hits = max_hits
        self._base = base_url.rstrip("/")
        self._archives = archives_url
        self._transport = transport
        self._limiter = limiter
        self._max_attempts = max_attempts
        self._backoff_base_s = backoff_base_s
        self._max_retry_after_s = max_retry_after_s

    @classmethod
    def from_settings(
        cls, settings: Settings, *, transport: httpx2.AsyncBaseTransport | None = None
    ) -> Self | None:
        """The client for the configured SEC User-Agent, or None when the channel is off."""
        if not settings.edgar_fts_enabled() or not settings.sec_user_agent:
            return None
        return cls(
            settings.sec_user_agent,
            base_url=settings.sec_efts_url,
            max_hits=settings.discovery_edgar_max_hits,
            transport=transport,
        )

    def url(self, phrases: Sequence[str], *, start: date, end: date) -> str:
        """The search's URL (see the module)."""
        params = {
            "q": filing_query(phrases),
            "forms": ",".join(self.forms),
            "dateRange": "custom",
            "startdt": start.isoformat(),
            "enddt": end.isoformat(),
        }
        return f"{self._base}/search-index?{urlencode(params)}"

    def search(self, phrases: Sequence[str], *, start: date, end: date) -> FilingSearch:
        """Search the phrases in the filings dated `start` to `end` (inclusive)."""
        if start > end:
            raise ValueError("the date range starts after it ends")
        url = self.url(phrases, start=start, end=end)
        content = asyncio.run(self._get(url))
        return parse_filing_search(
            filing_query(phrases), content, max_hits=self.max_hits, archives_url=self._archives
        )

    async def _get(self, url: str) -> bytes:
        client = SecHttpClient(
            self.user_agent,
            transport=self._transport,
            limiter=self._limiter,
            max_attempts=self._max_attempts,
            backoff_base_s=self._backoff_base_s,
            max_retry_after_s=self._max_retry_after_s,
        )
        async with client:
            try:
                result = await client.get(url)
            except FetchError as error:
                raise FilingSearchFailed(
                    f"EDGAR full-text search: {str(error)[:_ERROR_TEXT_LIMIT]}"
                ) from None
        return result.content
