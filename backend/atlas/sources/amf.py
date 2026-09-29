"""The AMF info-financière source adapter: a French issuer's regulated information (Soitec's,
first), from the open API of the AMF's regulated-information database.

info-financiere.gouv.fr is run by the DILA for the Autorité des marchés financiers; its data
is under the Licence Ouverte / Open Licence 2.0 (Etalab), and its API allows 10,000 calls
per IP per day (<https://www.data.gouv.fr/dataservices/api-info-financiere>; docs/decisions.md,
"AMF info-financière for Soitec"). Atlas is a client of that documented API only; it never
crawls the site's HTML pages, RSS or Atom feeds.

- **Search:** `GET https://www.info-financiere.gouv.fr/api/explore/v2.0/catalog/datasets/
  flux-amf-new-prod/records` (an Opendatasoft Explore API v2.0) with
  `where=identificationsociete_iso_cd_lei="<LEI>"`,
  `order_by=informationdeposee_inf_dat_emt desc`, `limit` (≤ 100) and `offset`.
- **Answer:** `{total_count, links, records: [{links, record: {id, timestamp, size,
  fields}}]}`. The fields used: `uin_idt_uin` (the filing's ID), `uin_dat_amf` (sent to the
  AMF) and `informationdeposee_inf_dat_emt` (transmitted), ISO times with an offset (UTC);
  `identificationsociete_iso_cd_lei`, `identificationsociete_iso_nom_soc`;
  `informationdeposee_inf_tit_inf` (the title), `informationdeposee_inf_lng_inf` (the
  language, in French: "Anglais", "Français"), `type_d_information`,
  `sous_type_d_information`, `type_of_information`, `subtype_of_information` (the string
  "NULL" when there is none) and `url_de_recuperation` (the file, on Opendatasoft's file
  host `fr.ftp.opendatasoft.com/datadila/INFOFI/`).

Rules:
- `available_at` is the later of `uin_dat_amf` and `informationdeposee_inf_dat_emt` (they
  normally agree): the AMF publication time, basis `publisher_timestamp`. With neither, it is
  the discovery time (`observed_discovery`).
- The language is the feed's: "Anglais" is `en` and "Français" is `fr` (so a French-only
  document is archived with `language=fr` and never retained); any other value leaves it to
  the parse.
- Only PDF and HTML files are candidates (an ESEF package is skipped); a row for another
  LEI is skipped.
- Rows come newest first, `PAGE_ROWS` at a time; paging stops at the first row transmitted at
  or before `since`, or at the end. More than `MAX_ROWS` rows (so more than 10 API calls)
  fails the discovery rather than silently dropping filings.
- Each announcement credits its source as the licence asks (`ExchangeAnnouncement.attribution`:
  the AMF, the dataset, the record and its last update, and the licence).

Every request goes through the client it is given; the ingest gives it a
`GatedHttpClient`, so the register entry (whose `api_client` covers exactly these API and
file URLs) and robots.txt are checked before each one, at the register's request rate.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode, urlsplit

from atlas.sources.adapter import (
    ExchangeAnnouncement,
    FetchedDocument,
    FetchError,
    SearchQuery,
    SourceCandidate,
)
from atlas.sources.gate import HttpClient

PROVIDER_ID = "amf_info_financiere"
PUBLISHER = "AMF info-financière"
DATASET = "flux-amf-new-prod"
API_URL = "https://www.info-financiere.gouv.fr/api/explore/v2.0"
RECORDS_URL = f"{API_URL}/catalog/datasets/{DATASET}/records"
LICENCE = "Licence Ouverte / Open Licence 2.0 (Etalab)"
LICENCE_URL = "https://www.etalab.gouv.fr/licence-ouverte-open-licence/"
PAGE_ROWS = 100  # the Explore API's maximum `limit`
MAX_ROWS = 1000  # at most 10 API calls per discovery
DEFAULT_LOOKBACK = timedelta(days=730)
_DOCUMENT_TYPES = {"pdf": "PDF", "html": "HTML", "htm": "HTML"}
_LANGUAGES = {"anglais": "en", "français": "fr", "francais": "fr"}


def records_url(lei: str, offset: int, limit: int) -> str:
    """The search for one LEI's filings, newest first."""
    query = {
        "where": f'identificationsociete_iso_cd_lei="{lei}"',
        "order_by": "informationdeposee_inf_dat_emt desc",
        "limit": str(limit),
        "offset": str(offset),
    }
    return f"{RECORDS_URL}?{urlencode(query)}"


def parse_timestamp(value: Any) -> datetime | None:
    """An API time (`2026-09-02T16:07:58+00:00`) in UTC, or None when there is none."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _text(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return "" if text == "NULL" else text


class AmfInfoFinanciereAdapter:
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
        offset = 0
        while True:
            if offset >= MAX_ROWS:
                raise FetchError(
                    f"info-financière lists more than {MAX_ROWS} filings for {self._lei} since"
                    f" {since:%Y-%m-%d}; ingest a shorter period",
                    url=RECORDS_URL,
                    status=None,
                    retryable=False,
                    attempts=(),
                )
            url = records_url(self._lei, offset, PAGE_ROWS)
            result = await self._client.get(url)
            rows, total = self._page(result.content, url)
            reached_since = False
            for record_id, updated, fields in rows:
                transmitted = parse_timestamp(fields.get("informationdeposee_inf_dat_emt"))
                if transmitted is not None and transmitted <= since:
                    reached_since = True
                    break
                candidate = self._candidate(record_id, updated, fields, now)
                if candidate is not None and candidate.available_at > since:
                    candidates.append(candidate)
            offset += len(rows)
            enough = query.limit is not None and len(candidates) >= query.limit
            if reached_since or enough or len(rows) < PAGE_ROWS or offset >= total:
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
    def _page(body: bytes, url: str) -> tuple[list[tuple[str, str, dict[str, Any]]], int]:
        try:
            envelope: Any = json.loads(body)
            total = int(envelope["total_count"])
            rows: list[tuple[str, str, dict[str, Any]]] = []
            for item in cast(list[Any], envelope["records"]):
                record: Any = item["record"]
                fields: Any = record["fields"]
                if not isinstance(fields, dict):
                    raise ValueError("a record's fields are not an object")
                rows.append(
                    (
                        str(record["id"]),
                        _text(record.get("timestamp")),
                        cast(dict[str, Any], fields),
                    )
                )
        except (ValueError, KeyError, TypeError) as error:
            raise FetchError(
                f"the info-financière API answered something unexpected: {error!r}",
                url=url,
                status=None,
                retryable=False,
                attempts=(),
            ) from error
        return rows, total

    def _candidate(
        self, record_id: str, updated: str, fields: dict[str, Any], now: datetime
    ) -> SourceCandidate | None:
        if _text(fields.get("identificationsociete_iso_cd_lei")).upper() != self._lei:
            return None
        link = _text(fields.get("url_de_recuperation"))
        path = urlsplit(link).path
        extension = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        file_type = _DOCUMENT_TYPES.get(extension)
        if not link.startswith("https://") or file_type is None:
            return None
        published: datetime | None = None
        printed: str | None = None
        for key in ("uin_dat_amf", "informationdeposee_inf_dat_emt"):
            time = parse_timestamp(fields.get(key))
            if time is not None and (published is None or time > published):
                published, printed = time, _text(fields.get(key))
        category = _text(fields.get("type_d_information")) or None
        subtype = _text(fields.get("subtype_of_information")) or _text(
            fields.get("sous_type_d_information")
        )
        language = _LANGUAGES.get(_text(fields.get("informationdeposee_inf_lng_inf")).lower())
        announcement = ExchangeAnnouncement(
            publisher=PUBLISHER,
            announcement_id=_text(fields.get("uin_idt_uin")) or record_id,
            issuer_code=self._lei,
            issuer_name=_text(fields.get("identificationsociete_iso_nom_soc")),
            category=category,
            file_type=file_type,
            published_at=published,
            published_local=printed,
            timezone="UTC",
            attribution=(
                f"Source: Autorité des marchés financiers (AMF), info-financiere.gouv.fr"
                f" (DILA), dataset {DATASET}, record {record_id}"
                + (f", updated {updated}" if updated else "")
                + f". {LICENCE}, {LICENCE_URL}"
            ),
        )
        return SourceCandidate(
            provider_id=PROVIDER_ID,
            kind="exchange_announcement",
            url=link,
            title=_text(fields.get("informationdeposee_inf_tit_inf")) or subtype or link,
            document_type=subtype or category,
            discovered_at=now,
            available_at=published or now,
            available_at_basis="publisher_timestamp" if published else "observed_discovery",
            announcement=announcement,
            language=language,
        )
