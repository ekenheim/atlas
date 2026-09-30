"""The parser: deterministic HTML/text/PDF normalization, fully separate from any LLM work.

`parse(raw, media_type)` turns archived bytes into plain text, with its language and, for
a PDF, one anchor per page. The same bytes and the same `PARSER_VERSION` always give the
same result, and so the same content hash: the output depends on nothing but the input
(no locale, clock, hash seed or network) and the pinned PDF library (`pypdf`, pinned
exactly in pyproject.toml; upgrading it is a new parser version). Any change to the
output for some input is a new parser version.

`text-v2` is `html-text-v1` (its HTML and text rules are unchanged, so an HTML or text
parse has the same text and content hash as under v1) plus PDF text and the language.
`text-v3` is `text-v2` plus the page-artifact rules for HTML below. Its text and PDF rules
are unchanged, and so is the parse of an HTML document without page breaks (the same text
and content hash as under v2).

Rules for HTML and text (from `html-text-v1`):
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

Page artifacts in HTML, new in `text-v3` (pilot fix 04). A filing rendered from a paginated
document repeats a footer and a header around every page break, and they land inside
sentences ("... design and manufacture\n9\nTable of Contents\nof transceivers ..."), so a
true quote is no span of the parse. Text is removed only where the markup shows it is an
artifact; a false removal would corrupt the text Evidence quotes.
- A page break is a block element whose `style` sets `page-break-before` or
  `page-break-after` to `always` (or `break-before`/`break-after` to `page`), outside hidden
  content: before the element or after it, as the property says (`<hr
  style="page-break-after:always"/>` in the recorded filings). The page breaks cut the
  document into pages. A document without one is not paginated: none of these rules apply.
- Back-link: a page's first line is removed when the whole line is the text of one
  same-document link (`<a href="#...">`) reading "Table of Contents" (in any case). A
  contents heading that is not a link, such a link further down the page, a link to another
  document, and a link that shares its line with other text all stay.
- Page number: a page's last line is removed when it is 1 to 3 ASCII digits and counts up
  with the pages: the nearest other page before it, or after it, that ends in such a number
  differs from it by exactly the number of page breaks between them. A lone number and one
  out of sequence (a contents page's last page reference, a table value) stay.
- Split paragraph: with those removed, the last line before a page break and the first line
  after it become one line, joined by one space, when the first does not end a sentence (it
  does not end in `.`, `!`, `?`, `:` or `;`, closing quotes and brackets aside), the second
  starts with a lowercase letter and is not a list marker (`a.`, `ii)`), and neither is a
  table row (no tab).
- Left in the text, deliberately: a running title (a company name or statement title
  repeated at the top of pages, which is also how a statement is headed), page numbers in
  any other form ("F-12", "Page 3", "- 3 -", roman numerals), back-links with other wording,
  a split paragraph whose second part starts with a capital or a digit (a capital also
  starts a heading), and everything in plain text and PDF.

Rules for PDF (`application/pdf`), new in `text-v2`:
- Each page's text is pypdf's `extract_text()` (plain mode), with C0 control characters
  other than tab and line feed removed, then the same normalization and line rules as
  HTML. The document's text is its pages' texts in page order.
- A `PageAnchor` per page: its 1-based number, its label (the PDF's `/PageLabels`, e.g.
  `iv`, else the number), and `[start, end)` in characters (code points) of the text. A
  page with no text has `start == end`.
- A PDF none of whose pages yields any text (an image-only or scanned PDF: Atlas does no
  OCR) is `Unsupported`, with the reason. Bytes pypdf can't read (not a PDF, encrypted
  with a password) raise, and the ledger records the parse as failed.

The language (a lowercase ISO 639 primary subtag, or `und` when undetermined), in order:
the language the document declares (`<html lang>`, a PDF catalog's `/Lang`), else a
deterministic guess from the text: Han, kana and Hangul characters give `zh`, `ja` or
`ko`; otherwise counts of short function words decide between `en`, `fr`, `de`, `es`,
`it` and `nl`, and too few of them, or a near tie, give `und`. (An adapter's declared
language, such as EDGAR's English, overrides this in the ledger.)

TradingView transcripts (`application/x-tradingview-transcript+json`, parser version
`tradingview-transcript-v1`; ticket 31): the raw bytes are a `get_document_view` answer as
TradingView's MCP server returned it, a JSON object whose `astDescription` is a tree of nodes
(`{"type": ..., "children": [...]}`, where a child is a node or a string). The text is the
tree flattened in document order: each child of the root is one line (its strings
concatenated, whatever the inline node types, e.g. a bold speaker label followed by
`": text"`, so a line reads `Speaker: text`); a `br` node inside a line breaks it. Then the
same normalization and line rules as HTML, and the language is detected from the text. A
tree with no text is `Unsupported`; bytes that aren't such a JSON object raise, and the
ledger records the parse as failed.

Other media types (JSON, XBRL instance data, ...) are not parsed: `parse` returns None.
"""

import bisect
import codecs
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from itertools import pairwise
from typing import cast

from pypdf import PdfReader

PARSER_VERSION = "text-v3"
# The HTML/text/PDF parser's versions, oldest first: a Source Version recorded under an
# earlier one can be re-parsed with `PARSER_VERSION` (`atlas ledger reparse`).
PARSER_LINEAGE = ("html-text-v1", "text-v2", PARSER_VERSION)
UNDETERMINED = "und"

HTML_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})
TEXT_MEDIA_TYPES = frozenset({"text/plain"})
PDF_MEDIA_TYPES = frozenset({"application/pdf", "application/x-pdf"})
TRADINGVIEW_TRANSCRIPT_MEDIA_TYPE = "application/x-tradingview-transcript+json"
TRADINGVIEW_TRANSCRIPT_PARSER_VERSION = "tradingview-transcript-v1"
_PARSEABLE = (
    HTML_MEDIA_TYPES
    | TEXT_MEDIA_TYPES
    | PDF_MEDIA_TYPES
    | frozenset({TRADINGVIEW_TRANSCRIPT_MEDIA_TYPE})
)

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
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")
_LANGUAGE_TAG = re.compile(r"\s*([A-Za-z]{2,3})(?:[-_][A-Za-z0-9]{1,8})*\s*")
_PAGE_BREAK = re.compile(
    r"(?:^|;)\s*(?:page-)?break-(before|after)\s*:\s*(?:always|page)\b", re.IGNORECASE
)
_BACK_LINK = "table of contents"
_PAGE_NUMBER = re.compile(r"[0-9]{1,3}")
_SENTENCE_END = re.compile(r"[.!?:;][\"'\u201d\u2019)\]]*$")
_LIST_MARKER = re.compile(r"[a-z]{1,4}[.)](?:\s|$)")


@dataclass(frozen=True)
class PageAnchor:
    """Where one PDF page's text lies in the parse: `text[start:end]`, in code points."""

    page: int  # 1-based, in document order
    label: str  # the page's label (PDF /PageLabels), e.g. "iv"; else its number
    start: int
    end: int


@dataclass(frozen=True)
class Unsupported:
    """Bytes of a parsed media type that yield no text Atlas can use (it does no OCR)."""

    parser_version: str
    reason: str


@dataclass(frozen=True)
class ParsedText:
    text: str
    parser_version: str
    complete: bool  # False when bytes could not be decoded and were replaced
    language: str = UNDETERMINED  # ISO 639 primary subtag, or "und"
    pages: tuple[PageAnchor, ...] = ()  # one per PDF page; none for HTML and text

    def encoded(self) -> bytes:
        """The parse as archived: UTF-8."""
        return self.text.encode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.encoded()).hexdigest()


def is_parseable(media_type: str) -> bool:
    return media_type.lower() in _PARSEABLE


def parse(raw: bytes, media_type: str) -> ParsedText | Unsupported | None:
    """The normalized text of `raw`, `Unsupported` if it has no usable text, or None if
    this media type is not parsed."""
    kind = media_type.lower()
    if kind not in _PARSEABLE:
        return None
    if kind in PDF_MEDIA_TYPES:
        return _parse_pdf(raw)
    if kind == TRADINGVIEW_TRANSCRIPT_MEDIA_TYPE:
        return _parse_tradingview_transcript(raw)
    decoded, complete = _decode(raw)
    declared: str | None = None
    if kind in HTML_MEDIA_TYPES:
        extractor = _TextExtractor()
        extractor.feed(decoded)
        extractor.close()
        text = _without_page_artifacts(extractor.pages())
        declared = extractor.language
    else:
        text = _normalize(_lines(decoded))
    return ParsedText(text, PARSER_VERSION, complete, _language(declared, text))


def _lines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _parse_pdf(raw: bytes) -> ParsedText | Unsupported:
    reader = PdfReader(io.BytesIO(raw))
    labels = reader.page_labels
    texts = [_normalize(_CONTROL.sub("", _lines(page.extract_text()))) for page in reader.pages]
    if not any(texts):
        return Unsupported(
            PARSER_VERSION,
            f"no extractable text on any of its {len(texts)} pages (an image-only or scanned PDF)",
        )
    anchors: list[PageAnchor] = []
    start = 0
    for index, page_text in enumerate(texts):
        end = start + len(page_text)
        label = labels[index] if index < len(labels) and labels[index] else str(index + 1)
        anchors.append(PageAnchor(page=index + 1, label=label, start=start, end=end))
        start = end
    text = "".join(texts)
    declared: object = reader.root_object.get("/Lang")
    language = _language(declared if isinstance(declared, str) else None, text)
    return ParsedText(text, PARSER_VERSION, True, language, tuple(anchors))


class TranscriptFormatError(ValueError):
    """Bytes that aren't a TradingView document view with an `astDescription` tree."""


def _parse_tradingview_transcript(raw: bytes) -> ParsedText | Unsupported:
    view: object = json.loads(raw.decode("utf-8"))
    tree = _field(view, "astDescription")
    children = _field(tree, "children")
    if not isinstance(children, list):
        raise TranscriptFormatError("no astDescription tree with children in the document view")
    lines = [_inline_text(child) for child in cast(list[object], children)]
    text = _normalize(_CONTROL.sub("", _lines("\n".join(lines))))
    if not text:
        return Unsupported(TRADINGVIEW_TRANSCRIPT_PARSER_VERSION, "the transcript has no text")
    return ParsedText(text, TRADINGVIEW_TRANSCRIPT_PARSER_VERSION, True, _language(None, text))


def _field(node: object, name: str) -> object:
    """`node[name]` if `node` is a JSON object, else None."""
    return cast(dict[str, object], node).get(name) if isinstance(node, dict) else None


def _inline_text(node: object) -> str:
    """A node's strings in document order; a `br` node is a line break."""
    if isinstance(node, str):
        return node
    if _field(node, "type") == "br":
        return "\n"
    children = _field(node, "children")
    if not isinstance(children, list):
        return ""
    return "".join(_inline_text(child) for child in cast(list[object], children))


def _language(declared: str | None, text: str) -> str:
    """The declared language's primary subtag if it is a well-formed tag, else a guess."""
    if declared is not None:
        match = _LANGUAGE_TAG.fullmatch(declared)
        if match is not None:
            return match.group(1).lower()
    return detect_language(text)


# Short function words, each in exactly one list: frequent in running text of their
# language and rare in the others'. Chosen for the pilot's filing languages.
_FUNCTION_WORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        "the and of to is that for with was are this which have from by be its our were"
        " has will than their it we".split()
    ),
    "fr": frozenset(
        "le la les des du et est une pour dans qui sur pas avec nous sont au aux ce ces"
        " été leur nos notre".split()
    ),
    "de": frozenset(
        "der die das und ist nicht mit von den dem zu auf für ein eine wir sich auch im"
        " einen wird wurde".split()
    ),
    "es": frozenset(
        "el los las y del por para con una se su al como más sus fue este esta".split()
    ),
    "it": frozenset("di che gli della non sono nel alla dei è nella delle anche per".split()),
    "nl": frozenset("het een van niet op te voor zijn dat wij ook door naar werd".split()),
}
_WORD = re.compile(r"[^\W\d_]+")
_MIN_FUNCTION_WORDS = 4


def detect_language(text: str) -> str:
    """A deterministic guess at `text`'s language (see the module docstring), or "und"."""
    han = kana = hangul = letters = 0
    for character in text:
        if not character.isalpha():
            continue
        letters += 1
        code = ord(character)
        if 0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF:
            kana += 1
        elif 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF:
            hangul += 1
        elif 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
            han += 1
    east_asian = han + kana + hangul
    if letters and east_asian * 2 >= letters:
        if hangul * 2 >= east_asian:
            return "ko"
        return "ja" if kana * 10 >= east_asian else "zh"
    counts: Counter[str] = Counter()
    for word in _WORD.findall(text.lower()):
        for language, words in _FUNCTION_WORDS.items():
            if word in words:
                counts[language] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if not ranked or ranked[0][1] < _MIN_FUNCTION_WORDS:
        return UNDETERMINED
    if len(ranked) > 1 and ranked[1][1] * 3 >= ranked[0][1] * 2:
        return UNDETERMINED  # a near tie: the runner-up has two thirds of the winner's count
    return ranked[0][0]


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
    return _text(_normalized_lines(text))


def _normalized_lines(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text)
    text = _ZERO_WIDTH.sub("", _SPACES.sub(" ", text))
    lines: list[str] = []
    for line in text.split("\n"):
        line = _HORIZONTAL_RUN.sub(lambda run: "\t" if "\t" in run[0] else " ", line)
        line = line.strip(" \t")
        if line:
            lines.append(line)
    return lines


def _text(lines: list[str]) -> str:
    return "".join(f"{line}\n" for line in lines)


@dataclass(frozen=True)
class _Page:
    """One page of an HTML document: what lies between two page breaks."""

    text: str  # as extracted, not yet normalized
    opening_link: str | None  # the text of the same-document link the page opens with, if any


def _without_page_artifacts(pages: list[_Page]) -> str:
    """The document's normalized text without its page artifacts (the module docstring has
    the rules). One page is a document without page breaks: its text, untouched."""
    if len(pages) == 1:
        return _normalize(pages[0].text)
    paged = [_normalized_lines(page.text) for page in pages]
    for page, lines in zip(pages, paged, strict=True):
        if _opens_with_back_link(page, lines):
            del lines[0]
    for index in _pages_ending_in_their_number(paged):
        del paged[index][-1]
    text: list[str] = []
    for lines in paged:
        if text and lines and _continues(text[-1], lines[0]):
            text[-1] = f"{text[-1]} {lines[0]}"
            lines = lines[1:]
        text.extend(lines)
    return _text(text)


def _opens_with_back_link(page: _Page, lines: list[str]) -> bool:
    """Whether the page's first line is, whole, a same-document "Table of Contents" link."""
    if page.opening_link is None or not lines:
        return False
    return _normalized_lines(page.opening_link) == [lines[0]] and lines[0].casefold() == _BACK_LINK


def _pages_ending_in_their_number(paged: list[list[str]]) -> list[int]:
    """The pages whose last line is a page number that counts up with the pages."""
    numbers = {
        index: int(lines[-1])
        for index, lines in enumerate(paged)
        if lines and _PAGE_NUMBER.fullmatch(lines[-1])
    }
    numbered = sorted(numbers)

    def counts_up(earlier: int, later: int) -> bool:
        return numbers[later] - numbers[earlier] == later - earlier

    return [
        index
        for position, index in enumerate(numbered)
        if (position > 0 and counts_up(numbered[position - 1], index))
        or (position + 1 < len(numbered) and counts_up(index, numbered[position + 1]))
    ]


def _continues(before: str, after: str) -> bool:
    """Whether `after`, the first line after a page break, continues the sentence `before`,
    the last line before it, leaves open."""
    if "\t" in before or "\t" in after:
        return False
    if _SENTENCE_END.search(before):
        return False
    return after[0].islower() and not _LIST_MARKER.match(after)


def _attribute(attrs: list[tuple[str, str | None]], name: str) -> str:
    """The attribute's value, or "" when the element has none."""
    return next((value or "" for attribute, value in attrs if attribute == name), "")


@dataclass
class _Element:
    tag: str
    hidden: bool
    pre: bool
    page_break_after: bool = False
    link_start: int | None = None  # for a same-document link: where its text starts in the output


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[_Element] = []
        self._out: list[str] = []
        self._page_breaks: list[int] = []  # indexes into `_out`, each just after a line break
        self._links: list[tuple[int, int]] = []  # same-document links' texts, as `_out[a:b]`
        self.language: str | None = None  # the <html> element's `lang`, if any

    def pages(self) -> list[_Page]:
        """The extracted text, cut at the page breaks (one page if there are none)."""
        links = sorted(self._links)
        pages: list[_Page] = []
        for start, end in pairwise([0, *self._page_breaks, len(self._out)]):
            opening_link = None
            first = bisect.bisect_left(links, (start, 0))
            if first < len(links) and links[first][0] < end:
                link_start, link_end = links[first]
                if not _normalized_lines("".join(self._out[start:link_start])):
                    opening_link = "".join(self._out[link_start : min(link_end, end)])
            pages.append(_Page("".join(self._out[start:end]), opening_link))
        return pages

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

    def _page_break_edges(self, tag: str, style: str) -> set[str]:
        """Where an element with this `style` breaks the page: `before` it, `after` it, both
        or neither. Only a visible block element does, so a page break always falls between
        two lines."""
        if tag not in _BLOCK or self._hidden() or _DISPLAY_NONE.search(style):
            return set()
        return {edge[1].lower() for edge in _PAGE_BREAK.finditer(style)}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._break(tag)
        if tag == "html" and self.language is None:
            self.language = next((value for name, value in attrs if name == "lang" and value), None)
        style = _attribute(attrs, "style")
        edges = self._page_break_edges(tag, style)
        if "before" in edges or (edges and tag in _VOID):
            self._page_breaks.append(len(self._out))
        if tag in _VOID:
            return
        hidden = self._hidden() or tag in _SKIPPED or bool(_DISPLAY_NONE.search(style))
        same_document_link = tag == "a" and _attribute(attrs, "href").startswith("#")
        link_start = len(self._out) if same_document_link and not hidden else None
        self._stack.append(
            _Element(tag, hidden, self._pre() or tag == "pre", "after" in edges, link_start)
        )

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # `<br/>`, `<div/>`: an element with no content.
        self._break(tag)
        if self._page_break_edges(tag, _attribute(attrs, "style")):
            self._page_breaks.append(len(self._out))

    def handle_endtag(self, tag: str) -> None:
        # Close the nearest open element of this name (and anything left open inside it);
        # a stray end tag with no open element is ignored.
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index].tag == tag:
                closed = self._stack[index:]
                del self._stack[index:]
                for element in closed:
                    if element.link_start is not None:
                        self._links.append((element.link_start, len(self._out)))
                self._break(tag)
                if closed[0].page_break_after:
                    self._page_breaks.append(len(self._out))
                return

    def handle_data(self, data: str) -> None:
        if self._hidden():
            return
        if not self._pre():
            data = data.replace("\r", " ").replace("\n", " ")
        else:
            data = data.replace("\r\n", "\n").replace("\r", "\n")
        self._out.append(data)
