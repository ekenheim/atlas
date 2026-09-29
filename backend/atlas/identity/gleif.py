"""The GLEIF API (https://api.gleif.org/api/v1; JSON:API, CC0 data; 60 requests/min per user).

Lookups: one record by LEI, ISIN → issuer LEI (an ADR's ISIN maps to the underlying
issuer), exact legal name, and full text (which returns a parent with its subsidiaries,
so its hits are only ever candidates). `fuzzycompletions` is deliberately absent: it came
back empty for Lumentum while the full-text filter found it (identity research §2).

A LAPSED registration still identifies the entity (the renewal is overdue); RETIRED,
MERGED or a successor entity are reported so the resolver can send them to review.
"""

import time
from dataclasses import dataclass

import httpx2
from pydantic import BaseModel, ConfigDict, ValidationError

from atlas.identity.http import IdentitySourceError, JsonHttp, Sleep
from atlas.sources.sec_http import TokenBucket

GLEIF_URL = "https://api.gleif.org/api/v1"
# The one limiter for all GLEIF traffic in this process (60 requests per minute).
GLEIF_RATE_LIMITER = TokenBucket(rate_per_s=60 / 60)
_PAGE_SIZE = "10"


@dataclass(frozen=True)
class LeiRecord:
    lei: str
    legal_name: str
    other_names: tuple[str, ...]  # other and transliterated names
    jurisdiction: str | None  # e.g. US-DE, TW
    entity_status: str | None  # ACTIVE, INACTIVE
    registration_status: str | None  # ISSUED, LAPSED, RETIRED, MERGED, ...
    successor_leis: tuple[str, ...]
    url: str

    @property
    def names(self) -> tuple[str, ...]:
        return (self.legal_name, *self.other_names)


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Name(_Body):
    name: str | None = None


class _Successor(_Body):
    lei: str | None = None


class _Entity(_Body):
    legalName: _Name = _Name()
    otherNames: list[_Name] = []
    transliteratedOtherNames: list[_Name] = []
    jurisdiction: str | None = None
    status: str | None = None
    successorEntities: list[_Successor] = []


class _Registration(_Body):
    status: str | None = None


class _Attributes(_Body):
    lei: str | None = None
    entity: _Entity = _Entity()
    registration: _Registration = _Registration()


class _Item(_Body):
    id: str
    attributes: _Attributes


class _One(_Body):
    data: _Item


class _Many(_Body):
    data: list[_Item]


def _record(item: _Item, url: str) -> LeiRecord:
    entity = item.attributes.entity
    names = [n.name for n in entity.otherNames + entity.transliteratedOtherNames if n.name]
    return LeiRecord(
        lei=item.attributes.lei or item.id,
        legal_name=entity.legalName.name or "",
        other_names=tuple(names),
        jurisdiction=entity.jurisdiction,
        entity_status=entity.status,
        registration_status=item.attributes.registration.status,
        successor_leis=tuple(s.lei for s in entity.successorEntities if s.lei),
        url=url,
    )


def _parse[T: BaseModel](model: type[T], content: bytes, url: str) -> T:
    try:
        return model.model_validate_json(content)
    except ValidationError as error:
        raise IdentitySourceError("GLEIF", f"{url}: unexpected response: {error}") from None


class GleifClient:
    def __init__(
        self,
        base_url: str = GLEIF_URL,
        *,
        transport: httpx2.BaseTransport | None = None,
        limiter: TokenBucket = GLEIF_RATE_LIMITER,
        sleep: Sleep = time.sleep,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._http = JsonHttp(
            "GLEIF",
            limiter=limiter,
            headers={"Accept": "application/vnd.api+json"},
            transport=transport,
            sleep=sleep,
        )

    def close(self) -> None:
        self._http.close()

    def record(self, lei: str) -> LeiRecord | None:
        url = f"{self._base}/lei-records/{lei}"
        content = self._http.request("GET", url, missing_ok=True)
        return None if content is None else _record(_parse(_One, content, url).data, url)

    def _filter(self, name: str, value: str) -> list[LeiRecord]:
        url = f"{self._base}/lei-records"
        params = {f"filter[{name}]": value, "page[size]": _PAGE_SIZE}
        content = self._http.request("GET", url, params=params) or b"{}"
        items = _parse(_Many, content, url).data
        return [_record(item, f"{self._base}/lei-records/{item.id}") for item in items]

    def by_isin(self, isin: str) -> list[LeiRecord]:
        return self._filter("isin", isin)

    def by_legal_name(self, name: str) -> list[LeiRecord]:
        return self._filter("entity.legalName", name)

    def fulltext(self, query: str) -> list[LeiRecord]:
        return self._filter("fulltext", query)
