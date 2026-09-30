"""The SearXNG client: one search is `GET /search?q=...&format=json&engines=...&language=...`.

SearXNG's search API (https://docs.searxng.org/dev/search_api.html) answers `format=json`
with the query, its `results` (each with `url`, `title`, `content`, `engine`, `engines`,
`publishedDate`, ...) and `unresponsive_engines`: `[engine, reason]` pairs for the engines
that timed out, were suspended or failed. Engines are always named explicitly (the owner's
instance's default set is partly broken), and so is the language (`ATLAS_SEARXNG_LANGUAGE`,
default `en`): without it SearXNG answers in the instance's locale. An instance without the
JSON format enabled answers 403.

Every failure (an HTTP error, a failed connection, a body that isn't SearXNG's JSON) raises
`SearchFailed`, an ordinary error: SearXNG isn't a queue dependency, so its outages never
pause the Hindsight and LiteLLM job kinds.
"""

from datetime import date, datetime
from typing import Self

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from atlas.settings import Settings

_ERROR_TEXT_LIMIT = 300


class SearchFailed(Exception):
    """A SearXNG search failed; the message says how."""


class UnresponsiveEngine(BaseModel):
    model_config = ConfigDict(frozen=True)

    engine: str
    reason: str


class SearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    position: int  # 1-based, in SearXNG's order
    url: str
    title: str
    snippet: str  # SearXNG's `content`
    engines: list[str]
    published_date: date | None


class SearchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    results: list[SearchResult]
    unresponsive_engines: list[UnresponsiveEngine]


class _Result(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    title: str = ""
    content: str | None = ""
    engine: str | None = None
    engines: list[str] = []
    published_date: str | None = Field(default=None, alias="publishedDate")


class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[_Result] = []
    unresponsive_engines: list[tuple[str, str]] = []  # [engine, reason] pairs


def _published(value: str | None) -> date | None:
    """The day of SearXNG's `publishedDate` (ISO 8601, with or without a time), else None."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


class SearXNGClient:
    def __init__(
        self,
        base_url: str,
        engines: list[str],
        *,
        timeout: float,
        language: str = "en",
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        if not engines:
            raise ValueError("name at least one SearXNG engine")
        if not language:
            raise ValueError("name the SearXNG search language")
        self.engines = list(engines)
        self.language = language
        self._client = httpx2.Client(
            base_url=base_url.rstrip("/"),
            headers={"Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_settings(
        cls, settings: Settings, *, transport: httpx2.BaseTransport | None = None
    ) -> "SearXNGClient | None":
        """The client for the configured SearXNG, or None when ATLAS_SEARXNG_URL isn't set."""
        if not settings.searxng_url:
            return None
        return cls(
            settings.searxng_url,
            settings.searxng_engine_list(),
            timeout=settings.searxng_timeout_seconds,
            language=settings.searxng_language,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def search(self, query: str) -> SearchResponse:
        params = {
            "q": query,
            "format": "json",
            "engines": ",".join(self.engines),
            "language": self.language,
        }
        try:
            response = self._client.get("/search", params=params)
        except httpx2.TransportError as error:
            raise SearchFailed(f"SearXNG search: {type(error).__name__}: {error}") from None
        if not response.is_success:
            raise SearchFailed(
                f"SearXNG search: HTTP {response.status_code}: {response.text[:_ERROR_TEXT_LIMIT]}"
            )
        try:
            body = _Response.model_validate_json(response.content)
        except ValidationError as error:
            raise SearchFailed(f"SearXNG search: unexpected response: {error}") from None
        return SearchResponse(
            query=query,
            results=[
                SearchResult(
                    position=position,
                    url=result.url,
                    title=result.title,
                    snippet=result.content or "",
                    engines=result.engines or ([result.engine] if result.engine else []),
                    published_date=_published(result.published_date),
                )
                for position, result in enumerate(body.results, start=1)
            ],
            unresponsive_engines=[
                UnresponsiveEngine(engine=engine, reason=reason)
                for engine, reason in body.unresponsive_engines
            ],
        )
