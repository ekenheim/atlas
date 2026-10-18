"""The mechanical bear checks of a company as of a time (Chokepoint Watch ticket W4).

Six deterministic checks, no model call, over what Atlas already holds: the as-of XBRL
observations (`atlas.bear_checks.xbrl`) and the archived parses of the company's filings whose
effective availability is at or before the cutoff (`atlas.bear_checks.patterns`). A check
returns `flag`, `clear` or `unknown`, its value, the rule applied in words and its sources
(observations, or a Source Version with the span of the sentence quoted). Not having the data
is `unknown`, never `clear`. Prices and consensus are not read. Rules in `docs/decisions.md`,
"The mechanical bear checks".
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, text

from atlas.archive import Archive
from atlas.bear_checks import xbrl
from atlas.bear_checks.models import BearCheck, BearChecks, BearCheckSource
from atlas.bear_checks.patterns import customer_concentration, going_concern, no_large_customer
from atlas.financials import load_metric_catalog, metric_values, select_as_of
from atlas.financials.service import company_observations
from atlas.ledger.reads import current_parse

SHELF_FORMS = ("S-3", "S-3ASR", "F-3", "S-1", "424B5")
SHELF_WINDOW_DAYS = 365
CONCENTRATION_FORMS = ("10-K", "20-F")
GOING_CONCERN_FORMS = ("10-K", "10-Q", "20-F", "40-F")
CONCENTRATION_FLAG_PERCENT = 25
MAX_MATCHES = 10  # sentences listed in a value
_WITH_TEXT = ("parsed", "incomplete")

_PRIMARY = """
    SELECT DISTINCT ON (d.id)
           v.id AS version_id, d.title, d.form_type, a.available_at
    FROM source_document d
    JOIN source_version v ON v.source_document_id = d.id
    JOIN source_version_availability a ON a.source_version_id = v.id
    WHERE d.company_id = :company AND d.source_type <> 'xbrl_companyfacts'
      AND a.available_at <= :as_of AND {condition}
    ORDER BY d.id, a.available_at DESC, v.version_number DESC
"""
_SHELF = _PRIMARY.format(
    condition="regexp_replace(upper(d.form_type), '/A$', '') = ANY(:forms)"
    " AND a.available_at > :since"
)
_REPORTS = _PRIMARY.format(
    condition="upper(d.form_type) = ANY(:forms) AND upper(d.document_type) = upper(d.form_type)"
)


class UnknownCompany(ValueError):
    """A company id that is not in the universe."""


@dataclass(frozen=True)
class _Report:
    version_id: uuid.UUID
    title: str
    form_type: str
    available_at: datetime


def bear_checks(
    engine: Engine, archive: Archive, metrics_config: Path, company_id: uuid.UUID, as_of: datetime
) -> BearChecks:
    """The six checks for the company at `as_of` (module docstring). Raises `UnknownCompany`."""
    as_of = as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC)
    catalog = load_metric_catalog(metrics_config)
    with engine.connect() as connection:
        if (
            connection.execute(
                text("SELECT 1 FROM company WHERE id = :id"), {"id": company_id}
            ).one_or_none()
            is None
        ):
            raise UnknownCompany(f"unknown company: {company_id}")
        observations = company_observations(connection, company_id)
        selected = select_as_of(observations, as_of)
        values = metric_values(selected, catalog, xbrl.METRICS)
        checks = [
            xbrl.dilution(selected, observations, as_of),
            _shelf_or_atm(connection, company_id, as_of),
            xbrl.gaap_gross_margin(values, as_of),
            _customer_concentration(connection, archive, company_id, as_of),
            _going_concern(connection, archive, company_id, as_of),
            xbrl.net_cash(selected, as_of),
        ]
    return BearChecks(company_id=company_id, as_of=as_of, checks=checks)


def _shelf_or_atm(connection: Connection, company_id: uuid.UUID, as_of: datetime) -> BearCheck:
    """Any shelf or ATM prospectus in the ledger in the twelve months before the cutoff. Atlas
    ingests 10-K, 10-Q and 8-K only, so an empty ledger proves nothing: unknown, never clear."""
    rows = (
        connection.execute(
            text(_SHELF),
            {
                "company": company_id,
                "as_of": as_of,
                "since": as_of - timedelta(days=SHELF_WINDOW_DAYS),
                "forms": list(SHELF_FORMS),
            },
        )
        .mappings()
        .all()
    )
    if not rows:
        return BearCheck(
            key="shelf_or_atm",
            status="unknown",
            value=None,
            basis=(
                "form not ingested: Atlas ingests 10-K, 10-Q and 8-K, and holds no S-3, S-3ASR,"
                f" F-3, S-1 or 424B5 of this company in the {SHELF_WINDOW_DAYS} days before the"
                " as-of time, which is not evidence that there was none"
            ),
            sources=[],
        )
    rows = sorted(rows, key=lambda row: row["available_at"], reverse=True)
    forms = sorted({row["form_type"] for row in rows})
    filings = [
        {
            "form": row["form_type"],
            "available_at": row["available_at"].astimezone(UTC).isoformat(),
            "source_version_id": str(row["version_id"]),
            "title": row["title"],
        }
        for row in rows
    ]
    return BearCheck(
        key="shelf_or_atm",
        status="flag",
        value={"filings": filings},
        basis=(
            f"{len(rows)} shelf or offering filing(s) ({', '.join(forms)})"
            f" in the ledger, public in the {SHELF_WINDOW_DAYS} days before the as-of time"
        ),
        sources=[
            BearCheckSource(
                kind="source_version",
                source_version_id=row["version_id"],
                form_type=row["form_type"],
                available_at=row["available_at"],
            )
            for row in rows
        ],
    )


def _latest_report(
    connection: Connection, company_id: uuid.UUID, as_of: datetime, forms: tuple[str, ...]
) -> _Report | None:
    rows = (
        connection.execute(
            text(_REPORTS), {"company": company_id, "as_of": as_of, "forms": list(forms)}
        )
        .mappings()
        .all()
    )
    if not rows:
        return None
    latest = max(rows, key=lambda row: (row["available_at"], str(row["version_id"])))
    return _Report(
        latest["version_id"], latest["title"] or "", latest["form_type"], latest["available_at"]
    )


@dataclass(frozen=True)
class _Text:
    body: str
    parser_version: str
    complete: bool  # a parse that read the whole document (`parsed`, not `incomplete`)


def _parsed_text(connection: Connection, archive: Archive, report: _Report) -> _Text | str:
    """The report's current parse, or why there is none."""
    parse = current_parse(connection, report.version_id)
    if parse is None or parse.parse_status not in _WITH_TEXT or parse.parsed_object_uri is None:
        return "has no parsed text"
    if parse.language not in (None, "en"):
        return "is not in English"
    return _Text(
        archive.get(parse.parsed_object_uri).decode("utf-8"),
        parse.parser_version,
        parse.parse_status == "parsed",
    )


def _source(
    report: _Report, parser_version: str, start: int, end: int, quote: str
) -> BearCheckSource:
    return BearCheckSource(
        kind="source_version",
        source_version_id=report.version_id,
        form_type=report.form_type,
        available_at=report.available_at,
        parser_version=parser_version,
        char_start=start,
        char_end=end,
        quote=quote,
    )


def _describe(report: _Report) -> str:
    return f"{report.form_type} public {report.available_at.astimezone(UTC).date()}"


def _document(report: _Report) -> dict[str, Any]:
    return {"source_version_id": str(report.version_id), "form": report.form_type}


def _customer_concentration(
    connection: Connection, archive: Archive, company_id: uuid.UUID, as_of: datetime
) -> BearCheck:
    """Flag when a customer's current-period share of revenue is 25% or more (a sentence or a
    table row of the latest 10-K or 20-F). Clear only on positive evidence: a customer's share
    below 25% stated as a value ("more than 10%" is a lower bound, not a value), or the
    statement that no customer exceeded a threshold of 25% or less, in a whole parse. A text
    that says nothing of the kind is unknown."""
    unknown = BearCheck(
        key="customer_concentration", status="unknown", value=None, basis="", sources=[]
    )
    report = _latest_report(connection, company_id, as_of, CONCENTRATION_FORMS)
    if report is None:
        unknown.basis = "no 10-K or 20-F of this company is in the ledger as of the as-of time"
        return unknown
    parsed = _parsed_text(connection, archive, report)
    if isinstance(parsed, str):
        unknown.basis = f"the latest annual report ({_describe(report)}) {parsed}"
        return unknown
    matches = customer_concentration(parsed.body)
    customers = [each for each in matches if each.kind == "customer"]
    groups = [each for each in matches if each.kind == "top_customers"]
    flagged = [each for each in customers if each.current >= CONCENTRATION_FLAG_PERCENT]
    stated = [each for each in customers if not each.floor]
    none_large = [
        each
        for each in no_large_customer(parsed.body)
        if each.threshold <= CONCENTRATION_FLAG_PERCENT
    ]
    value: dict[str, Any] = {
        "document": _document(report),
        "current_percent": float(max((each.current for each in customers), default=0)) or None,
        "matches": [
            {
                "percents": [float(p) for p in each.percents],
                "current_percent": float(each.current),
                "lower_bound": each.floor,
                "char_start": each.char_start,
                "char_end": each.char_end,
                "quote": each.sentence,
            }
            for each in (flagged or customers)[:MAX_MATCHES]
        ],
        "top_customers_share": [
            {
                "percents": [float(p) for p in each.percents],
                "current_percent": float(each.current),
                "char_start": each.char_start,
                "char_end": each.char_end,
                "quote": each.sentence,
            }
            for each in groups[:MAX_MATCHES]
        ],
        "no_customer_above": [float(each.threshold) for each in none_large],
    }
    limit = CONCENTRATION_FLAG_PERCENT
    if flagged:
        return BearCheck(
            key="customer_concentration",
            status="flag",
            value=value,
            basis=(
                f"{len(flagged)} sentence(s) or table row(s) of the latest annual report"
                f" ({_describe(report)}) give a customer's current-period share of revenue as"
                f" {limit}% or more; flag at {limit}%"
            ),
            sources=[
                _source(
                    report, parsed.parser_version, each.char_start, each.char_end, each.sentence
                )
                for each in flagged[:MAX_MATCHES]
            ],
        )
    if not parsed.complete:
        unknown.basis = (
            f"the latest annual report ({_describe(report)}) was only partly parsed: no flag in"
            " the part read is not evidence that there is none"
        )
        unknown.value = value
        return unknown
    evidence = [*stated, *none_large]
    if evidence:
        return BearCheck(
            key="customer_concentration",
            status="clear",
            value=value,
            basis=(
                f"the latest annual report ({_describe(report)}) states "
                + (
                    f"a customer's share below {limit}% in {len(stated)} place(s)"
                    if stated
                    else f"that no customer exceeded {none_large[0].threshold}% of revenue"
                )
                + ("; and that no customer exceeded a threshold" if stated and none_large else "")
            ),
            sources=[
                _source(
                    report, parsed.parser_version, each.char_start, each.char_end, each.sentence
                )
                for each in evidence[:MAX_MATCHES]
            ],
        )
    unknown.value = value
    unknown.basis = (
        f"the latest annual report ({_describe(report)}) states no customer's share of revenue"
        f" below {limit}% and not that no customer exceeded a threshold ("
        f"{len(customers)} customer sentence(s) or row(s) give only a lower bound or nothing"
        " below the line); only that wording is read"
    )
    return unknown


def _going_concern(
    connection: Connection, archive: Archive, company_id: uuid.UUID, as_of: datetime
) -> BearCheck:
    """Flag when the latest periodic report names substantial doubt about continuing as a going
    concern (a sentence that actually denies it does not count). Clear only from a whole parse
    of a 10-K, 10-Q, 20-F or 40-F; a partial parse that flags nothing is unknown."""
    unknown = BearCheck(key="going_concern", status="unknown", value=None, basis="", sources=[])
    report = _latest_report(connection, company_id, as_of, GOING_CONCERN_FORMS)
    if report is None:
        unknown.basis = (
            "no 10-K, 10-Q, 20-F or 40-F of this company is in the ledger as of the as-of time"
        )
        return unknown
    parsed = _parsed_text(connection, archive, report)
    if isinstance(parsed, str):
        unknown.basis = f"the latest periodic report ({_describe(report)}) {parsed}"
        return unknown
    matches = going_concern(parsed.body)
    stated = [each for each in matches if not each.negated]
    value: dict[str, Any] = {
        "document": _document(report),
        "sentences": len(stated),
        "negated_sentences": len(matches) - len(stated),
        "hedged_only": bool(stated) and all(each.hedged for each in stated),
    }
    sources = [
        _source(report, parsed.parser_version, each.char_start, each.char_end, each.sentence)
        for each in (stated or matches)[:MAX_MATCHES]
    ]
    if stated:
        return BearCheck(
            key="going_concern",
            status="flag",
            value=value,
            basis=(
                f"the latest periodic report ({_describe(report)}) names substantial doubt about"
                f" the ability to continue as a going concern in {len(stated)} sentence(s)"
                + (" (all conditional: 'could', 'may', 'if')" if value["hedged_only"] else "")
            ),
            sources=sources,
        )
    if not parsed.complete:
        unknown.value = value
        unknown.sources = sources
        unknown.basis = (
            f"the latest periodic report ({_describe(report)}) was only partly parsed: no"
            " going-concern language in the part read is not evidence that there is none"
        )
        return unknown
    return BearCheck(
        key="going_concern",
        status="clear",
        value=value,
        basis=(
            f"the whole latest periodic report ({_describe(report)}) was read and has no"
            " sentence naming substantial doubt about the ability to continue as a going concern"
            + (f" ({len(matches)} sentence(s) say there is none)" if matches else "")
        ),
        sources=sources,
    )
