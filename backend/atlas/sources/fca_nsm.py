"""The FCA National Storage Mechanism (NSM) source adapter: a UK issuer's regulated
announcements and reports (IQE's, first).

The NSM (<https://data.fca.org.uk/#/nsm/nationalstoragemechanism>) is the FCA's archive of
regulated information. Its terms allow use "for any lawful purpose" subject to its
Acceptable Use Policy (docs/decisions.md, "FCA National Storage Mechanism"). The site is a
single-page app over a search API:

- **Search:** `POST https://api.data.fca.org.uk/search?index=nsm-search` with a JSON query:
  `{from, size, sort: "submitted_date", sortorder: "desc", criteriaObj: {criteria: [
  {name: "company_lei", value: ["", <LEI>, "disclose_org", "related_org"]},
  {name: "latest_flag", value: "Y"}], dateCriteria: [{name: "publication_date" |
  "submitted_date", value: {from: null, to: <ISO time, no fraction>}}]}}`. That shape is
  the one the NSM's own search page sends; it is not documented, so the adapter sends it
  unchanged and narrows the answer itself.
- **Answer:** Elasticsearch-style: `hits.total.value` and `hits.hits[]._source` with
  `disclosure_id`, `seq_id`, `hist_seq`, `latest_flag`, `lei` and `company` (the
  disclosing organisation), `related_org` ([{lei, company}]), `headline`, `type` (the
  category, e.g. "Half-year Financial Report"), `type_code`, `category_group`, `source`
  (the PIP, e.g. "RNS", or "Direct upload"), `document_format`, `publication_date`,
  `submitted_date`, `document_date`, `last_updated_date` (ISO times in UTC, sometimes with
  nanoseconds) and `download_link` (a path under `https://data.fca.org.uk/artefacts/`).
- **Documents:** `GET https://data.fca.org.uk/artefacts/<download_link>`: an RNS
  announcement is HTML (`NSM/RNS/<seq_id>.html`), a directly uploaded report is often PDF.

Rules:
- The search matches the LEI as disclosing organisation **or** related issuer (e.g. a
  holder's Form 8.3 about the issuer). Only the disclosing organisation's own documents are
  candidates: a row whose `lei` isn't the issuer's is skipped.
- `available_at` is `publication_date` (when a PIP released it, or the submitter says it
  was published), else `submitted_date` (when the NSM received it): basis
  `publisher_timestamp`. With neither, it is the discovery time (`observed_discovery`).
- Only HTML and PDF documents are candidates (ESEF packages and other files are skipped).
- Rows come newest first by `submitted_date`, `PAGE_ROWS` at a time; paging stops at the
  first row submitted at or before `since`, or at the end. More than `MAX_ROWS` rows fails
  the discovery rather than silently dropping announcements.
- The adapter doesn't declare a document's language; the parse decides.

Every request goes through the client it is given; the ingest gives it a
`GatedHttpClient`, so the NSM's register entry and robots.txt are checked before each one,
and the ingest's client holds the register's (low) request rate.
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urljoin

from pydantic import JsonValue

from atlas.sources.adapter import (
    ExchangeAnnouncement,
    FetchedDocument,
    FetchError,
    SearchQuery,
    SourceCandidate,
)
from atlas.sources.gate import HttpClient

PROVIDER_ID = "fca_nsm"
PUBLISHER = "FCA National Storage Mechanism"
SEARCH_URL = "https://api.data.fca.org.uk/search?index=nsm-search"
ARTEFACTS_URL = "https://data.fca.org.uk/artefacts/"
PAGE_ROWS = 100
MAX_ROWS = 2000
DEFAULT_LOOKBACK = timedelta(days=730)
_DOCUMENT_TYPES = {"html": "HTML", "htm": "HTML", "pdf": "PDF"}
_TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})$")


def search_body(lei: str, to: datetime, start: int, size: int) -> JsonValue:
    """The NSM search for one LEI's latest documents submitted up to `to`, newest first."""
    until = to.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "from": start,
        "size": size,
        "sort": "submitted_date",
        "sortorder": "desc",
        "criteriaObj": {
            "criteria": [
                {"name": "company_lei", "value": ["", lei, "disclose_org", "related_org"]},
                {"name": "latest_flag", "value": "Y"},
            ],
            "dateCriteria": [
                {"name": "publication_date", "value": {"from": None, "to": until}},
                {"name": "submitted_date", "value": {"from": None, "to": until}},
            ],
        },
    }


def parse_timestamp(value: Any) -> datetime | None:
    """An NSM time (`2026-09-07T06:00:06Z`, possibly with up to nanoseconds) in UTC, or None
    when there is none."""
    match = _TIMESTAMP.match(str(value or "").strip())
    if match is None:
        return None
    whole, fraction, zone = match.groups()
    micros = (fraction or "")[:6].ljust(6, "0")
    offset = "+00:00" if zone == "Z" else zone
    return datetime.fromisoformat(f"{whole}.{micros}{offset}").astimezone(UTC)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


class FcaNsmAdapter:
    provider_id = PROVIDER_ID

    def __init__(
        self,
        client: HttpClient,
        *,
        lei: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client = client
        self._lei = lei.strip().upper()
        self._now = now

    async def discover(self, query: SearchQuery) -> list[SourceCandidate]:
        now = self._now()
        since = query.since or now - DEFAULT_LOOKBACK
        candidates: list[SourceCandidate] = []
        start = 0
        while True:
            if start >= MAX_ROWS:
                raise FetchError(
                    f"the NSM lists more than {MAX_ROWS} documents for {self._lei} since"
                    f" {since:%Y-%m-%d}; ingest a shorter period",
                    url=SEARCH_URL,
                    status=None,
                    retryable=False,
                    attempts=(),
                )
            result = await self._client.post_json(
                SEARCH_URL, search_body(self._lei, now, start, PAGE_ROWS)
            )
            rows, total = self._page(result.content)
            reached_since = False
            for row in rows:
                submitted = parse_timestamp(row.get("submitted_date"))
                if submitted is not None and submitted <= since:
                    reached_since = True
                    break
                candidate = self._candidate(row, now)
                if candidate is not None and candidate.available_at > since:
                    candidates.append(candidate)
            start += len(rows)
            enough = query.limit is not None and len(candidates) >= query.limit
            if reached_since or enough or len(rows) < PAGE_ROWS or start >= total:
                break
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
    def _page(body: bytes) -> tuple[list[dict[str, Any]], int]:
        try:
            envelope: Any = json.loads(body)
            hits: Any = envelope["hits"]
            total = int(hits["total"]["value"])
            rows: list[dict[str, Any]] = []
            for hit in cast(list[Any], hits["hits"]):
                source: Any = hit["_source"]
                if not isinstance(source, dict):
                    raise ValueError("a hit's _source is not an object")
                rows.append(cast(dict[str, Any], source))
        except (ValueError, KeyError, TypeError) as error:
            raise FetchError(
                f"the NSM search answered something unexpected: {error!r}",
                url=SEARCH_URL,
                status=None,
                retryable=False,
                attempts=(),
            ) from error
        return rows, total

    def _candidate(self, row: dict[str, Any], now: datetime) -> SourceCandidate | None:
        if _text(row.get("lei")).upper() != self._lei:
            return None  # another organisation's disclosure naming the issuer
        link = _text(row.get("download_link"))
        extension = link.rsplit(".", 1)[-1].lower() if "." in link else ""
        file_type = _DOCUMENT_TYPES.get(extension)
        if file_type is None:
            return None
        printed = _text(row.get("publication_date")) or _text(row.get("submitted_date"))
        published = parse_timestamp(printed)
        category = _text(row.get("type")) or None
        announcement = ExchangeAnnouncement(
            publisher=PUBLISHER,
            announcement_id=_text(row.get("seq_id")) or _text(row.get("disclosure_id")),
            issuer_code=self._lei,
            issuer_name=_text(row.get("company")),
            category=category,
            file_type=file_type,
            published_at=published,
            published_local=printed or None,
            timezone="UTC",
        )
        return SourceCandidate(
            provider_id=PROVIDER_ID,
            kind="exchange_announcement",
            url=urljoin(ARTEFACTS_URL, link.lstrip("/")),
            title=_text(row.get("headline")) or category or link,
            document_type=category,
            discovered_at=now,
            available_at=published or now,
            available_at_basis="publisher_timestamp" if published else "observed_discovery",
            announcement=announcement,
        )
