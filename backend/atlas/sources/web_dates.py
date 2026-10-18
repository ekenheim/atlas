"""What a web page says about itself: its publication date and its title (W3).

`page_date(html)` reads the publication date a page's HTML claims, in this order, the first that
parses winning:

1. `<meta property="article:published_time" content="...">` (Open Graph; `name=` is read too);
2. JSON-LD (`<script type="application/ld+json">`): the first `datePublished` of a node whose
   `@type` is `Article`, `NewsArticle` or `PressRelease`, in the document's order, through
   objects, lists and `@graph`. An `Organization`, `WebPage` or `Event` date is not the page's.

A bare `<time datetime>` is never read: a page is full of dates (an event, a footer, a price) and
none says when the page became public. A PDF carries none.

The date is a claim of the page, not of the server, and **Atlas believes it only a little**: the
caller (`atlas.ledger.web_fetch`) uses it for `available_at` only when it is no later than the
fetch and no more than seven days before it; any other page is available when Atlas fetched it,
and the date it claimed is kept as written.

**A date is made an instant without ever being earlier than it was** (availability is never
overstated; `docs/decisions.md`, "Pages: available when Atlas had them"):
- with a UTC offset (`2026-08-21T14:30:00+02:00`, `...Z`, RFC 2822 `GMT`): as written;
- without an offset: read in the latest zone on Earth, UTC-12:00, so it is never before the real
  instant (`2026-08-21T14:30:00` is 2026-08-22T02:30Z);
- a date alone (`2026-08-21`): the end of that day in UTC-12:00 (2026-08-22T11:59:59Z).

`page_title(html)` is `og:title`, else `<title>`, whitespace collapsed.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Literal, cast

LATEST_ZONE = timezone(timedelta(hours=-12))
ARTICLE_TYPES = frozenset({"Article", "NewsArticle", "PressRelease"})
_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}|\d{8}")
_SPACE = re.compile(r"\s+")
_MAX_JSON_LD = 200_000  # one script's text; a larger one is not read

type DateSource = Literal["article_published_time", "json_ld"]


@dataclass(frozen=True)
class PageDate:
    moment: datetime  # aware
    source: DateSource
    written: str  # the value as the page wrote it


def parse_moment(value: str) -> datetime | None:
    """`value` as an aware instant by the rules in the module docstring, or None."""
    value = value.strip()
    if not value:
        return None
    try:
        if _DATE_ONLY.fullmatch(value):
            day = datetime.fromisoformat(value).date()
            return datetime.combine(day, time(23, 59, 59), tzinfo=LATEST_ZONE).astimezone(UTC)
        moment = datetime.fromisoformat(value)
    except ValueError:
        try:
            moment = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=LATEST_ZONE)
    return moment.astimezone(UTC)


class _Scan(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: list[str] = []
        self.og_title: str | None = None
        self.title = ""
        self._in_title = False
        self._ld: list[str] | None = None
        self.json_ld: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {key.lower(): (value or "") for key, value in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").strip().lower()
            if key == "article:published_time" and a.get("content"):
                self.meta.append(a["content"])
            elif key == "og:title" and a.get("content") and self.og_title is None:
                self.og_title = a["content"]
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and a.get("type", "").strip().lower() == "application/ld+json":
            self._ld = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._ld is not None:
            self.json_ld.append("".join(self._ld))
            self._ld = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._ld is not None:
            self._ld.append(data)


def _scan(html: bytes | str) -> _Scan:
    text = html if isinstance(html, str) else html.decode("utf-8", errors="replace")
    scan = _Scan()
    scan.feed(text)
    scan.close()
    return scan


def _is_article(node: dict[str, Any]) -> bool:
    kinds = node.get("@type")
    names = [kinds] if isinstance(kinds, str) else cast(list[Any], kinds or [])
    return any(isinstance(name, str) and name in ARTICLE_TYPES for name in names)


def _dates_published(node: Any) -> list[str]:
    """Every `datePublished` string of an Article-type node in a JSON-LD value, in order."""
    found: list[str] = []
    if isinstance(node, dict):
        fields = cast(dict[str, Any], node)
        written = fields.get("datePublished")
        if _is_article(fields) and isinstance(written, str):
            found.append(written)
        for key, value in fields.items():
            if key != "datePublished":
                found.extend(_dates_published(value))
    elif isinstance(node, list):
        for item in cast(list[Any], node):
            found.extend(_dates_published(item))
    return found


def page_date(html: bytes | str) -> PageDate | None:
    """The publication date the page's HTML claims (see the module), or None."""
    scan = _scan(html)
    for written in scan.meta:
        moment = parse_moment(written)
        if moment is not None:
            return PageDate(moment, "article_published_time", written)
    for script in scan.json_ld:
        if len(script) > _MAX_JSON_LD:
            continue
        try:
            document = json.loads(script)
        except ValueError:
            continue
        for written in _dates_published(document):
            moment = parse_moment(written)
            if moment is not None:
                return PageDate(moment, "json_ld", written)
    return None


def page_title(html: bytes | str) -> str | None:
    """The page's title: `og:title`, else `<title>`; None when it has neither."""
    scan = _scan(html)
    title = _SPACE.sub(" ", scan.og_title or scan.title).strip()
    return title or None
