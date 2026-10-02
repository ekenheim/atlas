"""What a retained section says to Memory: its context, its entities and its display metadata
(memory-quality ticket 04; `docs/decisions.md`, "What a retained section says").

An extraction model reads the context before the section, so it is a few short, plain
sentences built by one function, `section_context`, from the Source Version and the section:

1. whose document it is and what kind (the form, an exhibit of a form, a call transcript, an
   exchange announcement, a document imported by hand), with the period it reports on when
   the source gives one (EDGAR's report date; a transcript's fiscal period);
2. the day it became public (the version's `available_at`, in UTC);
3. the section: its heading, the cover page, or the part of a chunked document;
4. who is speaking: the filer for a company's own filing or announcement; management and
   analysts for a call transcript, an analyst's question not being the company's statement;
   the publisher for a manual import.

No identifier a reader could not use (no UUID, accession or anchor) goes into it.

`section_entities` names the filer by its canonical name and every other company Atlas has
(universe companies and counterparties) whose names the section's text mentions, by the same
matcher passage selection uses for entity windows (`atlas.claims.predicates.mentions`), each
as written in the universe; the item sends them with `resolve_entities` false, so Hindsight
takes them as written.

`RETAIN_PROFILE` versions what a retain item says; each memory document records the profile
it was last submitted under, with the context and entities sent, so a backfill can find the
sections below the current one. `retain-v1` is every section retained before this module
(the context `<title>: <heading or anchor>`, no entities, no display metadata).
"""

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import Connection, text

from atlas.claims.predicates import company_names, mentions
from atlas.hindsight import RetainEntity

RETAIN_PROFILE = "retain-v2"
# The profile of every section retained before profiles were recorded.
FIRST_RETAIN_PROFILE = "retain-v1"

ENTITY_TYPE = "ORG"

# Forms whose report date is the end of the period they report on.
_PERIODIC_FORMS = frozenset({"10-K", "10-Q", "10-KT", "10-QT", "20-F", "40-F"})
_FORM_KINDS = {
    "10-K": "annual report",
    "10-KT": "transition report",
    "10-Q": "quarterly report",
    "10-QT": "transition report",
    "20-F": "annual report",
    "40-F": "annual report",
    "8-K": "current report",
    "6-K": "report",
    "DEF 14A": "proxy statement",
    "S-1": "registration statement",
    "F-1": "registration statement",
}
_CHUNK = re.compile(r"^chunk-0*(?P<number>\d+)$")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class SectionSource:
    """What the context, the entities and the display metadata are built from: the Source
    Version's document and company (a subset of `SourceVersionInfo`)."""

    source_type: str  # filing, transcript, exchange_announcement, manual_import, ...
    form_type: str | None
    document_type: str | None
    title: str
    publisher: str
    available_at: datetime
    company_id: uuid.UUID | None
    company_name: str | None  # the company's display name
    company_legal_name: str | None  # its canonical name, as written in the universe
    metadata: Mapping[str, Any]  # the version's adapter metadata


@dataclass(frozen=True)
class KnownCompany:
    """A company Atlas has (researched or counterparty): its canonical name and the names a
    text may use for it."""

    id: uuid.UUID
    canonical_name: str
    names: tuple[str, ...]


def known_companies(connection: Connection) -> list[KnownCompany]:
    """Every company Atlas has, by slug."""
    rows = connection.execute(
        text("SELECT id, display_name, legal_name FROM company ORDER BY slug")
    ).all()
    return [
        KnownCompany(row.id, row.legal_name, tuple(company_names(row.display_name, row.legal_name)))
        for row in rows
    ]


def section_context(source: SectionSource, *, heading: str | None, anchor: str) -> str:
    """The context sent with the section: short, plain sentences (see the module)."""
    sentences = [
        _kind(source),
        f"It was made public on {_day(source.available_at)}.",
        _section(heading, anchor),
        _speaker(source),
    ]
    return " ".join(sentence for sentence in sentences if sentence)


def section_entities(
    source: SectionSource, content: str, companies: Sequence[KnownCompany]
) -> list[RetainEntity]:
    """The filer's canonical name, then each other company the section's text names, in the
    order of `companies`; each once."""
    names: list[str] = []
    if source.company_legal_name:
        names.append(source.company_legal_name)
    names += [
        company.canonical_name
        for company in companies
        if company.id != source.company_id and mentions(content, company.names)
    ]
    return [RetainEntity(text=name, type=ENTITY_TYPE) for name in dict.fromkeys(names)]


def display_metadata(source: SectionSource) -> dict[str, str]:
    """The display keys added to the item's metadata, each only when known: `company_name`,
    `form` and `period` (EDGAR's report date, or a transcript's fiscal period)."""
    metadata: dict[str, str] = {}
    if source.company_name:
        metadata["company_name"] = source.company_name
    if source.form_type:
        metadata["form"] = source.form_type
    period = _report_date(source) or _fiscal_period(source)
    if period:
        metadata["period"] = period
    return metadata


# --- the sentences -----------------------------------------------------------------------------


def _kind(source: SectionSource) -> str:
    owner = f"{source.company_name}'s" if source.company_name else "the company's"
    if source.source_type == "transcript":
        transcript = _transcript(source)
        call = str(transcript.get("category") or "call").lower()
        event = transcript.get("event")
        named = f' "{_clean(str(event))}"' if event else ""
        period = _fiscal_period(source)
        for_period = f" for fiscal {period}" if period else ""
        return f"This is the transcript of {owner} {call}{named}{for_period}."
    if source.source_type == "manual_import":
        return (
            f'This is {owner} document "{_clean(source.title)}",'
            f" imported by hand from {source.publisher}."
        )
    if source.source_type == "exchange_announcement":
        return f'This is {owner} announcement "{_clean(source.title)}" on {source.publisher}.'
    form = source.form_type
    if form is None:
        return f'This is {owner} document "{_clean(source.title)}".'
    base = form.removesuffix("/A")
    kind = _FORM_KINDS.get(base, "filing")
    if form != base:
        kind = f"amended {kind}"
    report_date = _report_date(source)
    if report_date is None:
        period = ""
    elif base in _PERIODIC_FORMS:
        period = f" for the period ended {report_date}"
    else:
        period = f" dated {report_date}"
    document = f"{owner} {kind} on Form {form}{period}"
    exhibit = source.document_type
    if exhibit and exhibit != form and exhibit.upper().startswith("EX-"):
        return f"This is exhibit {exhibit[3:]} to {document}."
    return f"This is {document}."


def _section(heading: str | None, anchor: str) -> str:
    if heading:
        return f'This section is headed "{_clean(heading)}".'
    if anchor == "cover":
        return "This section is the cover page."
    chunk = _CHUNK.match(anchor)
    if chunk:
        return f"This is part {int(chunk['number'])} of the document."
    return ""


def _speaker(source: SectionSource) -> str:
    name = source.company_name
    if source.source_type == "manual_import":
        return f"{source.publisher} published it and is taken as the speaker."
    if name is None:
        return ""
    if source.source_type == "transcript":
        return (
            f"{name}'s management and analysts speak on the call;"
            f" an analyst's question is not a statement by {name}."
        )
    return f"{name} is speaking: this is its own document."


# --- helpers -----------------------------------------------------------------------------------


def _day(moment: datetime) -> str:
    return moment.astimezone(UTC).date().isoformat()


def _clean(value: str) -> str:
    return _SPACE.sub(" ", value).strip().replace('"', "'")


def _report_date(source: SectionSource) -> str | None:
    value = source.metadata.get("report_date")
    return str(value) if value else None


def _transcript(source: SectionSource) -> Mapping[str, Any]:
    value = source.metadata.get("tradingview")
    return cast(Mapping[str, Any], value) if isinstance(value, dict) else {}


def _fiscal_period(source: SectionSource) -> str | None:
    transcript = _transcript(source)
    parts = [
        str(transcript[key]) for key in ("fiscal_period", "fiscal_year") if transcript.get(key)
    ]
    return " ".join(parts) or None
