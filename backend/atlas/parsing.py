"""The parser: deterministic HTML/text normalization, fully separate from any LLM work.

`parse(raw, media_type)` turns archived bytes into plain text. The same bytes and the same
`PARSER_VERSION` always give the same text, and so the same content hash: the output
depends on nothing but the input (no locale, clock, hash seed or network). Any change to
the output for some input is a new parser version.

Rules of `html-text-v1`:
- Decoding: the charset declared in the document (XML declaration or `<meta>`), else
  UTF-8, else Windows-1252, taking the first that decodes strictly. If none does, the
  declared charset (or UTF-8) with replacement characters, and the parse is incomplete.
- Dropped with their content: `head`, `script`, `style`, `noscript`, `template`, the
  inline-XBRL `ix:header`, and every element whose `style` says `display:none`. Comments,
  processing instructions and declarations are dropped. Source text is data: nothing in
  it is interpreted beyond this.
- Block elements (paragraphs, divs, headings, list items, table rows, `br`, ...) end a
  line; table cells are separated by a tab. Inside `pre`, source line breaks are kept.
- Character references are decoded; the text is NFC-normalized; no-break and other
  Unicode spaces become spaces; zero-width characters are removed.
- Per line, runs of whitespace collapse to one space (or one tab, if the run held a cell
  break), and the line is trimmed. Empty lines are dropped. Lines end with "\\n".
- `text/plain`: decoded the same way, then the same line rules.

Other media types (JSON, XBRL instance data, ...) are not parsed: `parse` returns None.
"""

import codecs
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser

PARSER_VERSION = "html-text-v1"

HTML_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})
TEXT_MEDIA_TYPES = frozenset({"text/plain"})

_SKIPPED = frozenset({"head", "script", "style", "noscript", "template", "ix:header"})
_VOID = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_BLOCK = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "body",
        "br",
        "caption",
        "center",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "html",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "tfoot",
        "thead",
        "tr",
        "ul",
    }
)
_CELL = frozenset({"td", "th"})

_LINE, _CELL_BREAK = "\n", "\t"
_DECLARED_CHARSET = re.compile(
    rb"""<\?xml[^>]*\bencoding\s*=\s*["']([A-Za-z0-9._-]+)["']"""
    rb"""|<meta[^>]*\bcharset\s*=\s*["']?([A-Za-z0-9._-]+)""",
    re.IGNORECASE,
)
_SPACES = re.compile(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]")
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
_HORIZONTAL_RUN = re.compile(r"[ \t\f\v]+")
_DISPLAY_NONE = re.compile(r"display\s*:\s*none", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedText:
    text: str
    parser_version: str
    complete: bool  # False when bytes could not be decoded and were replaced

    def encoded(self) -> bytes:
        """The parse as archived: UTF-8."""
        return self.text.encode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.encoded()).hexdigest()


def is_parseable(media_type: str) -> bool:
    return media_type.lower() in HTML_MEDIA_TYPES | TEXT_MEDIA_TYPES


def parse(raw: bytes, media_type: str) -> ParsedText | None:
    """The normalized text of `raw`, or None if this media type is not parsed."""
    kind = media_type.lower()
    if kind not in HTML_MEDIA_TYPES | TEXT_MEDIA_TYPES:
        return None
    decoded, complete = _decode(raw)
    if kind in HTML_MEDIA_TYPES:
        extractor = _TextExtractor()
        extractor.feed(decoded)
        extractor.close()
        text = extractor.text()
    else:
        text = decoded.replace("\r\n", "\n").replace("\r", "\n")
    return ParsedText(_normalize(text), PARSER_VERSION, complete)


def _decode(raw: bytes) -> tuple[str, bool]:
    declared = _declared_charset(raw[:4096])
    candidates = [c for c in (declared, "utf-8", "cp1252") if c is not None]
    for charset in dict.fromkeys(candidates):
        try:
            return raw.decode(charset), True
        except UnicodeDecodeError:
            continue
    return raw.decode(declared or "utf-8", errors="replace"), False


def _declared_charset(head: bytes) -> str | None:
    match = _DECLARED_CHARSET.search(head)
    if match is None:
        return None
    name = (match.group(1) or match.group(2)).decode("ascii").lower()
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _ZERO_WIDTH.sub("", _SPACES.sub(" ", text))
    lines: list[str] = []
    for line in text.split("\n"):
        line = _HORIZONTAL_RUN.sub(lambda run: "\t" if "\t" in run[0] else " ", line)
        line = line.strip(" \t")
        if line:
            lines.append(line)
    return "".join(f"{line}\n" for line in lines)


@dataclass
class _Element:
    tag: str
    hidden: bool
    pre: bool


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[_Element] = []
        self._out: list[str] = []

    def text(self) -> str:
        return "".join(self._out)

    def _hidden(self) -> bool:
        return bool(self._stack) and self._stack[-1].hidden

    def _pre(self) -> bool:
        return bool(self._stack) and self._stack[-1].pre

    def _break(self, tag: str) -> None:
        if self._hidden():
            return
        if tag in _BLOCK:
            self._out.append(_LINE)
        elif tag in _CELL:
            self._out.append(_CELL_BREAK)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._break(tag)
        if tag in _VOID:
            return
        style = next((value or "" for name, value in attrs if name == "style"), "")
        hidden = self._hidden() or tag in _SKIPPED or bool(_DISPLAY_NONE.search(style))
        self._stack.append(_Element(tag, hidden, self._pre() or tag == "pre"))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # `<br/>`, `<div/>`: an element with no content.
        self._break(tag)

    def handle_endtag(self, tag: str) -> None:
        # Close the nearest open element of this name (and anything left open inside it);
        # a stray end tag with no open element is ignored.
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                self._break(tag)
                return

    def handle_data(self, data: str) -> None:
        if self._hidden():
            return
        if not self._pre():
            data = data.replace("\r", " ").replace("\n", " ")
        else:
            data = data.replace("\r\n", "\n").replace("\r", "\n")
        self._out.append(data)
