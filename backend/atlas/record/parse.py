"""Parsing an artifact page into its ledger (atlas-record ticket 01). Pure.

The ledger is JSON in a `<pre>` near the foot of the page. It is found by parsing, never by an
`id`: two of the eight fixtures have no `id="ledger"`, and one has no code fences. Every
`<pre>` is taken in order, its tags stripped, its entities unescaped, a leading code fence
(three backticks and `json`) and a trailing one removed; the first block that is a JSON object
with `chokepoints` (a theme ledger) or `board` (the council's) is the ledger.

A page with no such block, or whose block does not fit its ledger's model, is a `Parsed` with
an `error` and no ledger. It never raises.
"""

import html
import json
import re
from dataclasses import dataclass
from typing import Any, cast

from pydantic import ValidationError

from atlas.record.ledger import CouncilLedger, Ledger, ThemeLedger

_PRE = re.compile(r"<pre\b[^>]*>(.*?)</pre\s*>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]*>")
_OPENING_FENCE = re.compile(r"^```[A-Za-z]*[ \t]*\r?\n?")
_CLOSING_FENCE = re.compile(r"\r?\n?[ \t]*```$")


@dataclass(frozen=True)
class Parsed:
    ledger: Ledger | None
    error: str | None  # set exactly when there is no ledger
    raw: dict[str, Any] | None = None  # the JSON object as the page wrote it (what is stored)


def pre_blocks(page: bytes) -> list[str]:
    """Each `<pre>`'s text: tags stripped, entities unescaped, the code fences removed."""
    text = page.decode("utf-8", errors="replace")
    blocks: list[str] = []
    for match in _PRE.finditer(text):
        block = html.unescape(_TAG.sub("", match.group(1))).strip()
        block = _OPENING_FENCE.sub("", block, count=1)
        block = _CLOSING_FENCE.sub("", block, count=1)
        blocks.append(block.strip())
    return blocks


def parse_page(page: bytes) -> Parsed:
    blocks = pre_blocks(page)
    if not blocks:
        return Parsed(None, "no_ledger: the page has no <pre> block")
    for block in blocks:
        try:
            loaded: object = json.loads(block)
        except ValueError:
            continue
        if not isinstance(loaded, dict):
            continue
        raw = cast("dict[str, Any]", loaded)
        try:
            if "chokepoints" in raw:
                return Parsed(ThemeLedger.model_validate(raw), None, raw)
            if "board" in raw:
                return Parsed(CouncilLedger.model_validate(raw), None, raw)
        except ValidationError as error:
            return Parsed(None, f"invalid_ledger: {_summary(error)}")
    return Parsed(
        None,
        f"no_ledger: none of the page's {len(blocks)} <pre> blocks is a JSON object with"
        " `chokepoints` or `board`",
    )


def _summary(error: ValidationError) -> str:
    problems = [
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors()[:5]
    ]
    more = len(error.errors()) - len(problems)
    return "; ".join(problems) + (f" (and {more} more)" if more > 0 else "")
