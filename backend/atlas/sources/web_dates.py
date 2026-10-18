"""What a web page says about itself: its publication date and its title (W3).

`page_date(html)` reads the publication date a page's HTML carries, in this order, the first
that parses winning:

1. `<meta property="article:published_time" content="...">` (Open Graph; `name=` is read too);
2. JSON-LD (`<script type="application/ld+json">`): the first `datePublished`, in the document's
   order, through objects, lists and `@graph`;
3. `<time datetime="...">`: the first one marked `itemprop="datePublished"` or `pubdate`, else
   the first that parses.

A PDF carries none. The date is a claim of the page, not of the server: the caller never lets it
be later than the moment the page was fetched.

**A date is made an instant without ever being earlier than it was** (availability is never
overstated; `docs/decisions.md`, "Pages: available when their own date says"):
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
_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}|\d{8}")
_SPACE = re.compile(r"\s+")
_MAX_JSON_LD = 200_000  # one script's text; a larger one is not read

type DateSource = Literal["article_published_time", "json_ld", "time_element"]


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
        self.times: list[tuple[bool, str]] = []  # (marked as the publication date, datetime)

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
        elif tag == "time" and a.get("datetime"):
            marked = a.get("itemprop", "").strip().lower() == "datepublished" or "pubdate" in a
            self.times.append((marked, a["datetime"]))

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


def _dates_published(node: Any) -> list[str]:
    """Every `datePublished` string in a JSON-LD value, in document order."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in cast(dict[str, Any], node).items():
            if key == "datePublished" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_dates_published(value))
    elif isinstance(node, list):
        for item in cast(list[Any], node):
            found.extend(_dates_published(item))
    return found


def page_date(html: bytes | str) -> PageDate | None:
    """The publication date the page's HTML carries (see the module), or None."""
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
    for _, written in sorted(scan.times, key=lambda each: not each[0]):  # marked first, stable
        moment = parse_moment(written)
        if moment is not None:
            return PageDate(moment, "time_element", written)
    return None


def page_title(html: bytes | str) -> str | None:
    """The page's title: `og:title`, else `<title>`; None when it has neither."""
    scan = _scan(html)
    title = _SPACE.sub(" ", scan.og_title or scan.title).strip()
    return title or None
