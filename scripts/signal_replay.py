"""Replay the archive-signal scan as of a past time, read from a running Atlas (ticket 18).

The nightly `scan_signals` job scores the sentences of archived documents for the cues of a
bottleneck (`atlas.discovery.signals`, `configs/discovery/signals.yaml`) and stores the hits as
leads. This script asks the question the early-signal case studies pose: **what would the scan
have ranked highest by a given date?** It runs the same scorer over the documents public by
`--as-of`, over the API, with no model call and no write:

1. **The documents.** For each company (`--companies`, default every researched company) the
   latest Source Version of each document public by `--as-of` (`GET /archive-documents`, the
   documents the archive search reads; from `--since` on, if given), its current parse read once
   (`GET /source-versions/{id}/content?kind=parsed`) and cached under
   `.scratch/live-runs/signal-replay-cache/` (a parse never changes).
2. **The scorer.** The job's own: `SignalScorer.scan` over each text, with the document's form,
   source type and the company's names, oldest document first, a sentence a company's earlier
   document already holds as a hit being a repeat and dropped, as the job drops it.
3. **The ranking.** All hits of all companies by score (ties: the later document first), then
   at most `ranking.max_per_document` (config; `--max-per-document` overrides) of one document
   among the first results and the rest after them (`cap_per_document`), as
   `GET /leads?origin=archive_signal` ranks them. The `--top` (20) are printed with rank,
   company, document title and date, score, the cue families, the speaker of a call and the
   first 200 characters of the sentence.
4. **A sentence you expect** (`--expect TEXT`, repeatable): the best rank of a hit whose sentence
   contains the text (case-insensitive, whitespace folded), and whether it is in the top
   `--within` (5). Nothing about the vocabulary is fitted to it: this only looks it up. The exit
   status is 1 when an expected sentence is not within the top.

Everything is a GET. The report goes to `--out` (default
`.scratch/live-runs/<stamp>-signal-replay/`) as `results.json` and `summary.md`.

    uv run python scripts/signal_replay.py --as-of 2025-08-31T00:00:00Z --top 20 \\
        --expect "just two players"
"""

import argparse
import json
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2

from atlas.claims.predicates import company_names
from atlas.discovery.signal_scan import sentence_sha256
from atlas.discovery.signals import SignalHit, SignalScorer, cap_per_document, load_signals_config

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / ".scratch" / "live-runs" / "signal-replay-cache"
DEFAULT_CONFIG = REPO / "configs" / "discovery" / "signals.yaml"
PAUSE_SECONDS = 0.05  # between requests: the API is the owner's own, no need to hurry it
DOCUMENT_PAGE = 500
_SPACES = re.compile(r"\s+")


class Api:
    def __init__(self, base_url: str) -> None:
        self._client = httpx2.Client(base_url=base_url.rstrip("/") + "/api/v1", timeout=120.0)
        self.requests = 0

    def get(self, path: str, **params: Any) -> Any:
        return self._send(path, params).json()

    def text(self, path: str, **params: Any) -> str:
        return self._send(path, params).text

    def _send(self, path: str, params: dict[str, Any]) -> httpx2.Response:
        time.sleep(PAUSE_SECONDS)
        self.requests += 1
        response = self._client.get(path, params={k: v for k, v in params.items() if v is not None})
        response.raise_for_status()
        return response


@dataclass(frozen=True)
class Ranked:
    hit: SignalHit
    company: str
    title: str
    source_version_id: str
    available_at: datetime


def main() -> int:
    args = _arguments()
    as_of = _time(args.as_of)
    since = _time(args.since) if args.since else None
    api = Api(args.base_url)
    config = load_signals_config(Path(args.config))
    scorer = SignalScorer(config)
    cap = args.max_per_document or config.ranking.max_per_document

    universe = {c["slug"]: c for c in _items(api.get("/companies", role="researched", limit=500))}
    wanted = [slug.strip() for slug in args.companies.split(",") if slug.strip()] or list(universe)
    unknown = [slug for slug in wanted if slug not in universe]
    if unknown:
        print(f"unknown companies: {', '.join(unknown)}", file=sys.stderr)
        return 2
    companies = [universe[slug] for slug in wanted]

    documents: list[dict[str, Any]] = []
    for company in companies:
        found = _documents(api, company, as_of, since)
        documents.extend(found)
        print(f"{company['slug']}: {len(found)} documents", file=sys.stderr)
    documents.sort(key=lambda each: (each["available_at"], each["source_version_id"]))

    seen: set[tuple[str, str]] = set()  # (company, sentence): the job's "repeat" rule
    ranked: list[Ranked] = []
    scanned = repeats = 0
    for document in documents:
        text = _parsed(api, document)
        company = universe[document["company"]]
        primary = document["document_type"] is not None and (
            document["document_type"] == document["form_type"]
        )
        hits = scorer.scan(
            text,
            form_type=document["form_type"],
            primary=primary,
            source_type=document["source_type"],
            company_names=company_names(company["display_name"], company["legal_name"]),
        )
        scanned += 1
        stored: list[Ranked] = []
        for hit in hits:
            key = (document["company"], sentence_sha256(hit.quote))
            if key in seen:
                repeats += 1
                continue
            stored.append(
                Ranked(
                    hit,
                    document["company"],
                    document["title"],
                    document["source_version_id"],
                    document["available_at"],
                )
            )
        seen.update((document["company"], sentence_sha256(each.hit.quote)) for each in stored)
        ranked.extend(stored)
    ranked.sort(key=lambda each: (-each.hit.score, -each.available_at.timestamp()))
    ranked = cap_per_document(ranked, lambda each: each.source_version_id, cap)

    rows = [_row(rank, each) for rank, each in enumerate(ranked, start=1)]
    expected = [_expect(text, rows, args.within) for text in args.expect]
    results: dict[str, Any] = {
        "base_url": args.base_url,
        "as_of": as_of.isoformat(),
        "since": since.isoformat() if since else None,
        "companies": wanted,
        "config": str(args.config),
        "documents": len(documents),
        "repeats": repeats,
        "hits": len(rows),
        "max_per_document": cap,
        "requests": api.requests,
        "top": rows[: args.top],
        "expect": expected,
    }
    out = Path(args.out) if args.out else _default_out()
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(_summary(results, args.within), encoding="utf-8")
    print(_summary(results, args.within))
    print(f"{len(rows)} hits from {scanned} documents; report in {out}", file=sys.stderr)
    return 1 if any(not each["within"] for each in expected) else 0


def _documents(
    api: Api, company: dict[str, Any], as_of: datetime, since: datetime | None
) -> list[dict[str, Any]]:
    """The company's documents public by `as_of` (the archive search's: the latest version of
    each, parsed, English), with the fields the scorer needs."""
    answer = api.get(
        "/archive-documents",
        company_id=company["id"],
        as_of=as_of.isoformat(),
        since=since.isoformat() if since else None,
        limit=DOCUMENT_PAGE,
    )
    if answer["total"] > DOCUMENT_PAGE:
        print(
            f"warning: {company['slug']} has {answer['total']} documents; the newest"
            f" {DOCUMENT_PAGE} are read (narrow with --since)",
            file=sys.stderr,
        )
    return [
        {
            "company": company["slug"],
            "source_version_id": each["source_version_id"],
            "title": each["title"],
            "form_type": each["form_type"],
            "document_type": each["document_type"],
            "source_type": each["source_type"],
            "parser_version": each["parser_version"],
            "available_at": _time(each["available_at"]),
        }
        for each in answer["documents"]
    ]


def _parsed(api: Api, document: dict[str, Any]) -> str:
    """The document's parsed text, from the cache when a parse was read before."""
    path = CACHE / f"{document['source_version_id']}-{document['parser_version']}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    text = api.text(
        f"/source-versions/{document['source_version_id']}/content",
        kind="parsed",
        parser_version=document["parser_version"],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def _row(rank: int, each: Ranked) -> dict[str, Any]:
    hit = each.hit
    return {
        "rank": rank,
        "company": each.company,
        "title": each.title,
        "available_at": each.available_at.isoformat(),
        "source_version_id": each.source_version_id,
        "section_anchor": hit.section_anchor,
        "char_start": hit.start,
        "char_end": hit.end,
        "score": hit.score,
        "families": list(hit.families),
        "factors": dict(hit.factors),
        "speaker": hit.speaker,
        "speaker_kind": hit.speaker_kind,
        "sentence": hit.quote,
    }


def _expect(text: str, rows: Sequence[dict[str, Any]], within: int) -> dict[str, Any]:
    needle = _SPACES.sub(" ", text.strip().lower())
    for row in rows:
        if needle in _SPACES.sub(" ", row["sentence"].lower()):
            return {
                "text": text,
                "rank": row["rank"],
                "within": row["rank"] <= within,
                "company": row["company"],
                "available_at": row["available_at"],
                "score": row["score"],
                "sentence": row["sentence"],
            }
    return {"text": text, "rank": None, "within": False}


def _summary(results: dict[str, Any], within: int) -> str:
    lines = [
        f"# Archive signals as of {results['as_of']}",
        "",
        f"{results['hits']} hits from {results['documents']} documents of"
        f" {len(results['companies'])} companies ({results['repeats']} repeats dropped).",
        "",
        "| # | Company | Document | Public | Score | Families | Sentence |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in results["top"]:
        speaker = f" [{row['speaker_kind']}]" if row["speaker_kind"] else ""
        sentence = row["sentence"].replace("|", "\\|")
        shown = sentence if len(sentence) <= 200 else sentence[:197] + "..."
        lines.append(
            f"| {row['rank']} | {row['company']} | {row['title']} | {row['available_at'][:10]} |"
            f" {row['score']} | {', '.join(row['families'])} | {shown}{speaker} |"
        )
    for each in results["expect"]:
        lines.append("")
        if each["rank"] is None:
            lines.append(f"Expected {each['text']!r}: no hit contains it.")
        else:
            verdict = (
                f"within the top {within}" if each["within"] else f"NOT within the top {within}"
            )
            lines.append(
                f"Expected {each['text']!r}: rank {each['rank']} ({verdict}), {each['company']},"
                f" {each['available_at'][:10]}, score {each['score']}."
            )
    return "\n".join(lines) + "\n"


def _items(page: Any) -> list[dict[str, Any]]:
    return list(page["items"])


def _time(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _default_out() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return REPO / ".scratch" / "live-runs" / f"{stamp}-signal-replay"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument(
        "--as-of", required=True, help="ISO time with an offset, e.g. 2025-08-31T00:00:00Z"
    )
    parser.add_argument("--since", help="only documents public from this time on (ISO)")
    parser.add_argument("--companies", default="", help="comma-separated slugs (default: all)")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        help="a phrase of a sentence you expect among the top hits (repeatable)",
    )
    parser.add_argument(
        "--max-per-document",
        type=int,
        help="hits of one document among the first results (default: the config's ranking)",
    )
    parser.add_argument("--within", type=int, default=5, help="the rank --expect must reach")
    parser.add_argument("--base-url", default="https://atlas.ekenhome.se", help="a running Atlas")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="the signals config")
    parser.add_argument("--out", help="the report folder (default: under .scratch/live-runs/)")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
