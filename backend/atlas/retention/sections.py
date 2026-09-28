"""Split a Source Version's parsed text into sections, each retained as one memory document.

`split_sections(text, form=..., primary=...)` is deterministic: the same text and
`SECTIONER_VERSION` always give the same anchors and offsets. Offsets are character indices
into the parsed text (`text[start:end]`), and the sections tile it: together they cover every
character exactly once, in order.

Rules of `sec-items-v1`:
- An SEC filing's primary document (10-K, 10-Q, 8-K and their amendments) is split on its
  Item headings: a line that starts `Item <n>` (`1`, `1A`, `10`, `2.02`, ...) followed by
  `.`, `:`, a dash or the end of the line, at most 200 characters long. `PART <roman>`
  lines qualify the items after them, so a 10-Q's Part I Item 1 and Part II Item 1 differ.
- The table of contents repeats the headings, so the body starts at the *last* occurrence
  of the first heading's (part, item); earlier headings are contents. From there, a
  (part, item) seen again folds into the section before it.
- An item's section starts at its `PART` line when that line directly precedes it, and runs
  to the next section. The text before the first section is the `cover` section.
- Anchors: `part-ii-item-1a`, `item-2-02` (8-Ks have no parts), `cover`.
- Anything else (exhibits such as press releases, a primary document without Item headings,
  other providers' text) is cut into bounded chunks `chunk-001`, `chunk-002`, ... of at most
  `MAX_CHUNK_CHARS` characters, each ending at a line break when the chunk has one.
"""

import re
from dataclasses import dataclass

SECTIONER_VERSION = "sec-items-v1"
MAX_CHUNK_CHARS = 12_000
SEC_ITEM_FORMS = frozenset({"10-K", "10-Q", "8-K"})

_MAX_HEADING_CHARS = 200
_ITEM = re.compile(
    r"ITEM\s+(?P<item>\d{1,2}(?:\.\d{2})?[A-C]?)(?:\.|:|\s*[-\N{EN DASH}\N{EM DASH}]|\s*$)",
    re.IGNORECASE,
)
_PART = re.compile(r"PART\s+(?P<part>IV|I{1,3})\b", re.IGNORECASE)


@dataclass(frozen=True)
class Section:
    anchor: str
    heading: str | None  # the Item heading line; None for the cover and for chunks
    start: int
    end: int


@dataclass(frozen=True)
class _Heading:
    key: tuple[str | None, str]  # (part, item)
    line: str
    start: int  # where the section starts: the item line, or its PART line just before


def split_sections(text: str, *, form: str | None, primary: bool) -> list[Section]:
    """The sections of a parsed text; empty only when the text is empty."""
    if not text:
        return []
    if primary and form is not None and form.upper().removesuffix("/A") in SEC_ITEM_FORMS:
        sections = _item_sections(text)
        if sections:
            return sections
    return _chunks(text)


def _item_sections(text: str) -> list[Section]:
    headings = _body_headings(_headings(text))
    if not headings:
        return []
    sections: list[Section] = []
    if headings[0].start > 0:
        sections.append(Section("cover", None, 0, headings[0].start))
    for index, heading in enumerate(headings):
        end = headings[index + 1].start if index + 1 < len(headings) else len(text)
        sections.append(Section(_anchor(heading.key), heading.line, heading.start, end))
    return sections


def _headings(text: str) -> list[_Heading]:
    headings: list[_Heading] = []
    part: str | None = None
    part_start: int | None = None  # the PART line directly before the current line, if any
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        start, offset = offset, offset + len(line)
        if not stripped:
            continue
        if len(stripped) <= _MAX_HEADING_CHARS and (match := _PART.match(stripped)):
            part, part_start = match["part"].upper(), start
            continue
        if len(stripped) <= _MAX_HEADING_CHARS and (match := _ITEM.match(stripped)):
            key = (part, match["item"].upper())
            headings.append(
                _Heading(key, stripped, part_start if part_start is not None else start)
            )
        part_start = None
    return headings


def _body_headings(headings: list[_Heading]) -> list[_Heading]:
    """Drop the table of contents, then keep the first occurrence of each (part, item)."""
    if not headings:
        return []
    first = headings[0].key
    body_start = max(index for index, heading in enumerate(headings) if heading.key == first)
    seen: set[tuple[str | None, str]] = set()
    body: list[_Heading] = []
    for heading in headings[body_start:]:
        if heading.key not in seen:
            seen.add(heading.key)
            body.append(heading)
    return body


def _anchor(key: tuple[str | None, str]) -> str:
    part, item = key
    anchor = f"item-{item.lower().replace('.', '-')}"
    return f"part-{part.lower()}-{anchor}" if part else anchor


def _chunks(text: str) -> list[Section]:
    chunks: list[Section] = []
    start = 0
    while start < len(text):
        end = min(start + MAX_CHUNK_CHARS, len(text))
        if end < len(text):
            newline = text.rfind("\n", start, end)
            if newline > start:
                end = newline + 1
        chunks.append(Section(f"chunk-{len(chunks) + 1:03d}", None, start, end))
        start = end
    return chunks
