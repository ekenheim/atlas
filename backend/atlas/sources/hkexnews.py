"""The HKEXnews source adapter: an HKEX-listed issuer's announcements and reports.

Discovery uses HKEXnews' title search (`/search/titleSearchServlet.do`), which answers with
JSON: `{"result": "<a JSON array, as a string>", "hasNextRow": bool, "rowRange": n, ...}`.
Each row names one document: `NEWS_ID`, `TITLE`, `LONG_TEXT` (its category), `STOCK_CODE`,
`STOCK_NAME`, `DATE_TIME` (`DD/MM/YYYY HH:MM`, Hong Kong time), `FILE_TYPE`, `FILE_INFO` and
`FILE_LINK` (a path under www1.hkexnews.hk). The search is by HKEXnews' internal `stockId`
(Innolight's is 1000311764), not the stock code. Shapes from the public descriptions cited
in docs/decisions.md ("HKEXnews"); the fixtures are hand-written from them, not recorded.

- `available_at` is `DATE_TIME`, HKEXnews' publication time (basis `publisher_timestamp`),
  converted from Asia/Hong_Kong to UTC. It has minute precision.
- Only PDF and HTML documents are candidates; other file types are skipped.
- The search asks for `rowRange` rows; while HKEXnews says more rows exist (`hasNextRow`)
  and no limit was asked for, it asks again for 100 more, up to `MAX_ROWS`. More than that
  fails the discovery rather than silently dropping announcements.
- The adapter doesn't declare a document's language: the English search also lists
  documents only published in Chinese, so the parse decides (`atlas.parsing`).

Every request goes through the client it is given; the ingest gives it a
`GatedHttpClient`, so HKEXnews' terms and robots.txt are checked before each one.
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from html import unescape
from typing import Any, cast
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo

from atlas.sources.adapter import (
    ExchangeAnnouncement,
    FetchedDocument,
    FetchError,
    SearchQuery,
    SourceCandidate,
)
from atlas.sources.gate import HttpGetter

PROVIDER_ID = "hkexnews"
PUBLISHER = "HKEXnews"
BASE_URL = "https://www1.hkexnews.hk"
SEARCH_URL = f"{BASE_URL}/search/titleSearchServlet.do"
TIMEZONE = "Asia/Hong_Kong"
HONG_KONG = ZoneInfo(TIMEZONE)
PAGE_ROWS = 100
MAX_ROWS = 500
DEFAULT_LOOKBACK = timedelta(days=730)
_DOCUMENT_TYPES = frozenset({"PDF", "HTM", "HTML"})
_TAG = re.compile(r"<[^>]+>")


def title_search_url(stock_id: str, from_date: date, to_date: date, rows: int) -> str:
    """HKEXnews' title search for one stock's announcements in English, newest first."""
    params = {
        "sortDir": "0",
        "sortByOptions": "DateTime",
        "category": "0",
        "market": "SEHK",
        "stockId": stock_id,
        "documentType": "-1",
        "fromDate": from_date.strftime("%Y%m%d"),
        "toDate": to_date.strftime("%Y%m%d"),
        "title": "",
        "searchType": "0",
        "t1code": "-2",
        "t2Gcode": "-2",
        "t2code": "-2",
        "rowRange": str(rows),
        "lang": "E",
    }
    return f"{SEARCH_URL}?{urlencode(params)}"


def published_at(value: str) -> datetime:
    """HKEXnews' `DATE_TIME` (`DD/MM/YYYY HH:MM`, Hong Kong time) in UTC."""
    local = datetime.strptime(value.strip(), "%d/%m/%Y %H:%M").replace(tzinfo=HONG_KONG)
    return local.astimezone(UTC)


def _text(value: Any) -> str:
    return " ".join(unescape(_TAG.sub(" ", str(value or ""))).split())


class HkexNewsAdapter:
    provider_id = PROVIDER_ID

    def __init__(
        self,
        client: HttpGetter,
        *,
        stock_id: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client = client
        self._stock_id = stock_id
        self._now = now

    async def discover(self, query: SearchQuery) -> list[SourceCandidate]:
        now = self._now()
        since = query.since or now - DEFAULT_LOOKBACK
        from_date = since.astimezone(HONG_KONG).date()
        to_date = now.astimezone(HONG_KONG).date()
        rows = query.limit or PAGE_ROWS
        while True:
            url = title_search_url(self._stock_id, from_date, to_date, rows)
            result = await self._client.get(url)
            listing = self._listing(url, result.content)
            if query.limit is not None or not listing["hasNextRow"]:
                break
            if rows >= MAX_ROWS:
                raise FetchError(
                    f"HKEXnews lists more than {MAX_ROWS} announcements since {from_date};"
                    " ingest a shorter period",
                    url=url,
                    status=result.status,
                    retryable=False,
                    attempts=result.attempts,
                )
            rows += PAGE_ROWS
        candidates: list[SourceCandidate] = []
        for row in listing["rows"]:
            candidate = self._candidate(row, now)
            if candidate is None or candidate.available_at <= since:
                continue
            candidates.append(candidate)
        return candidates[: query.limit] if query.limit is not None else candidates

    async def fetch(self, candidate: SourceCandidate) -> FetchedDocument:
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

    async def updates(self, since: datetime) -> list[SourceCandidate]:
        return await self.discover(SearchQuery(since=since))

    @staticmethod
    def _listing(url: str, body: bytes) -> dict[str, Any]:
        try:
            envelope: Any = json.loads(body)
            result: Any = envelope.get("result")
            # `result` is a JSON array serialized into a string (or null: no rows).
            parsed: Any = json.loads(result) if isinstance(result, str) else result
            if parsed is None:
                parsed = []
            if not isinstance(parsed, list):
                raise ValueError("result is not a list")
            rows: list[dict[str, Any]] = []
            for row in cast(list[Any], parsed):
                if not isinstance(row, dict):
                    raise ValueError("a result row is not an object")
                rows.append(cast(dict[str, Any], row))
        except (ValueError, AttributeError) as error:
            raise FetchError(
                f"HKEXnews title search answered something unexpected: {error}",
                url=url,
                status=None,
                retryable=False,
                attempts=(),
            ) from error
        return {"rows": rows, "hasNextRow": bool(envelope.get("hasNextRow"))}

    def _candidate(self, row: dict[str, Any], now: datetime) -> SourceCandidate | None:
        file_type = _text(row.get("FILE_TYPE")).upper()
        link = str(row.get("FILE_LINK") or "").strip()
        if file_type not in _DOCUMENT_TYPES or not link:
            return None
        local = _text(row.get("DATE_TIME"))
        public = published_at(local)
        category = _text(row.get("LONG_TEXT")) or None
        announcement = ExchangeAnnouncement(
            publisher=PUBLISHER,
            announcement_id=_text(row.get("NEWS_ID")),
            issuer_code=_text(row.get("STOCK_CODE")),
            issuer_name=_text(row.get("STOCK_NAME")),
            category=category,
            file_type=file_type,
            published_at=public,
            published_local=local,
            timezone=TIMEZONE,
        )
        return SourceCandidate(
            provider_id=PROVIDER_ID,
            kind="exchange_announcement",
            url=urljoin(BASE_URL, link),
            title=_text(row.get("TITLE")),
            document_type=category,
            discovered_at=now,
            available_at=public,
            available_at_basis="publisher_timestamp",
            announcement=announcement,
        )
