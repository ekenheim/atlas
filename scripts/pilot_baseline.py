"""The archive-search baseline for one pilot question, read from a running Atlas.

The pilot holds each investigation against what a plain search of the archive finds
(`.scratch/atlas-pilot-review/`, "The archive-search baseline"; the search itself is
`atlas.evaluation.baseline`). This script runs it over the API, with no model call:

1. **The documents.** Each seed company's filing documents (`GET /companies/{id}/sources`)
   whose latest Source Version is parsed, English and available in the `--months` (18) before
   `--as-of` (now): the window the investigation's EDGAR search uses. Each version's parsed
   text is read once (`GET /source-versions/{id}/content?kind=parsed`, the current parse where
   the API names one) and cached under `.scratch/live-runs/baseline-cache/`, since a parse
   never changes.
2. **Archive search.** The question's content words, BM25 over the passages, the `--top` (20)
   best with at most `--per-document` (3) from one document.
3. **Recall alone** (unless `--no-recall`). One `POST /memory/recall` with the question, scoped
   to the seed companies and the theme: what memory surfaces without a research role. Each
   archive hit is marked when it lies in a section recall resolved to. Recall makes no LLM call.
4. **Coverage** (with `--investigation`). Each archive hit is marked with the accepted Claims
   whose quote it contains. The reviewer then judges at most 10 on-question hits; the share of
   those the card covers is the baseline coverage of the pilot's verdict criteria.

Everything is a GET except the one recall. The report goes to `--out` (default
`.scratch/live-runs/<stamp>-baseline/`) as `results.json` and `summary.md`.

    uv run python scripts/pilot_baseline.py --company axt --company coherent --company lumentum \\
        --question "Is indium phosphide substrate supply a chokepoint ...?" \\
        --investigation <id>
"""

import argparse
import json
import re
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx2

from atlas.evaluation.baseline import Document, Hit, covering_quotes, query_terms, search

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / ".scratch" / "live-runs" / "baseline-cache"
PAGE = 200
PAUSE_SECONDS = 0.05  # between requests: the API is the owner's own, no need to hurry it
_FILED = re.compile(r"filed (\d{4}-\d{2}-\d{2})")


class Api:
    def __init__(self, base_url: str) -> None:
        self._client = httpx2.Client(base_url=base_url.rstrip("/") + "/api/v1", timeout=60.0)
        self.requests = 0

    def get(self, path: str, **params: str | int) -> Any:
        response = self._send("GET", path, params=params)
        return response.json()

    def text(self, path: str, **params: str | int) -> str:
        return self._send("GET", path, params=params).text

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self._send("POST", path, json=body).json()

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx2.Response:
        time.sleep(PAUSE_SECONDS)
        self.requests += 1
        response = self._client.request(method, path, **kwargs)
        response.raise_for_status()
        return response


def main() -> int:
    args = _arguments()
    as_of = _time(args.as_of) if args.as_of else datetime.now(UTC)
    since = as_of - timedelta(days=round(args.months * 30.44))
    api = Api(args.base_url)

    companies = {c["slug"]: c for c in _items(api.get("/companies"))}
    unknown = [slug for slug in args.company if slug not in companies]
    if unknown:
        print(f"unknown companies: {', '.join(unknown)}", file=sys.stderr)
        return 2
    seeds = [companies[slug] for slug in args.company]

    documents: list[Document] = []
    skipped: dict[str, int] = {}
    for company in seeds:
        found, why = _documents(api, company, since, as_of)
        documents.extend(found)
        for reason, count in why.items():
            skipped[reason] = skipped.get(reason, 0) + count
        print(f"{company['slug']}: {len(found)} documents in the window", file=sys.stderr)

    hits = search(args.question, documents, top=args.top, per_document=args.per_document)

    quotes: dict[str, str] = {}
    claims: dict[str, dict[str, Any]] = {}
    if args.investigation:
        investigation = api.get(f"/investigations/{args.investigation}")
        for entry in investigation["evidence"]:
            if not entry.get("excluded"):
                quotes[entry["claim_id"]] = entry["quote"]
                claims[entry["claim_id"]] = entry

    recall: dict[str, Any] | None = None
    sections: list[dict[str, Any]] = []
    if args.recall:
        recall = api.post(
            "/memory/recall",
            {
                "query": args.question,
                "scope": {"company_ids": [c["id"] for c in seeds], "theme_ids": [args.theme]},
            },
        )
        assert recall is not None
        sections = list(recall["evidence"])

    by_version = {document.source_version_id: document for document in documents}
    rows = [
        _row(rank, hit, by_version[hit.passage.source_version_id], quotes, sections)
        for rank, hit in enumerate(hits, start=1)
    ]
    covered = {claim_id for row in rows for claim_id in row["covered_by_claims"]}
    results: dict[str, Any] = {
        "base_url": args.base_url,
        "question": args.question,
        "terms": query_terms(args.question),
        "companies": [c["slug"] for c in seeds],
        "window": {"since": since.isoformat(), "as_of": as_of.isoformat()},
        "documents": len(documents),
        "documents_skipped": skipped,
        "requests": api.requests,
        "investigation": args.investigation,
        "hits": rows,
        "claims_in_no_hit": [
            {"claim_id": claim_id, "predicate": claim["predicate"], "quote": claim["quote"]}
            for claim_id, claim in claims.items()
            if claim_id not in covered
        ],
        "recall": None
        if recall is None
        else {
            "memories": len(recall["memories"]),
            "counts": recall["counts"],
            "sections": [
                {
                    "source_version_id": s["source_version_id"],
                    "section_anchor": s["section_anchor"],
                    "section_heading": s.get("section_heading"),
                }
                for s in sections
            ],
        },
    }

    out = Path(args.out) if args.out else _default_out()
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(_summary(results), encoding="utf-8")
    print(f"{len(rows)} hits from {len(documents)} documents; report in {out}", file=sys.stderr)
    return 0


def _documents(
    api: Api, company: dict[str, Any], since: datetime, as_of: datetime
) -> tuple[list[Document], dict[str, int]]:
    """The company's parsed English filing documents available in the window."""
    documents: list[Document] = []
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    offset = 0
    while True:
        page = api.get(f"/companies/{company['id']}/sources", limit=PAGE, offset=offset)
        for source in page["items"]:
            if source["source_type"] == "xbrl_companyfacts" or not source["latest_version_id"]:
                skip("not a text document")
                continue
            filed = _FILED.search(source.get("title") or "")
            if filed and not _near_window(filed.group(1), since, as_of):
                skip("outside the window")  # by the title's filing date: no request needed
                continue
            version = api.get(f"/source-versions/{source['latest_version_id']}")
            available_at = _time(version["available_at"])
            if not since <= available_at <= as_of:
                skip("outside the window")
            elif version["parse_status"] != "parsed":
                skip("not parsed")
            elif version.get("language") not in (None, "en"):
                skip("not English")
            else:
                parser = version.get("current_parser_version") or version["parser_version"]
                documents.append(
                    Document(
                        source_version_id=version["id"],
                        company=company["slug"],
                        title=source.get("title") or source["canonical_url"],
                        available_at=version["available_at"],
                        text=_parsed_text(api, version["id"], parser),
                    )
                )
        offset += PAGE
        if offset >= page["total"]:
            return documents, skipped


def _parsed_text(api: Api, version_id: str, parser_version: str) -> str:
    cached = CACHE / f"{version_id}.{parser_version}.txt"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    text = api.text(
        f"/source-versions/{version_id}/content", kind="parsed", parser_version=parser_version
    )
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(text, encoding="utf-8", newline="")
    return text


def _row(
    rank: int,
    hit: Hit,
    document: Document,
    quotes: dict[str, str],
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    passage = hit.passage
    recalled = [
        s["section_anchor"]
        for s in sections
        if s["source_version_id"] == passage.source_version_id
        and s["section_char_start"] < passage.char_end
        and passage.char_start < s["section_char_end"]
    ]
    return {
        "rank": rank,
        "score": hit.score,
        "terms": list(hit.terms),
        "company": document.company,
        "title": document.title,
        "available_at": document.available_at,
        **asdict(passage),
        "covered_by_claims": covering_quotes(passage.text, quotes),
        "in_recalled_sections": recalled,
    }


def _summary(results: dict[str, Any]) -> str:
    hits: list[dict[str, Any]] = results["hits"]
    lines = [
        "# Archive-search baseline",
        "",
        f"- **Question:** {results['question']}",
        f"- **Terms:** {', '.join(results['terms'])}",
        f"- **Companies:** {', '.join(results['companies'])}",
        f"- **Window:** {results['window']['since'][:10]} to {results['window']['as_of'][:10]}",
        f"- **Documents searched:** {results['documents']} "
        f"(skipped: {results['documents_skipped'] or 'none'})",
    ]
    if results["investigation"]:
        covered = sum(1 for hit in hits if hit["covered_by_claims"])
        lines.append(
            f"- **Investigation {results['investigation']}:** {covered} of {len(hits)} hits "
            f"contain an accepted Claim's quote; {len(results['claims_in_no_hit'])} accepted "
            "Claims are in no hit"
        )
    if results["recall"]:
        recalled = sum(1 for hit in hits if hit["in_recalled_sections"])
        lines.append(
            f"- **Recall alone:** {results['recall']['memories']} memories "
            f"({results['recall']['counts']}); {recalled} of {len(hits)} hits lie in a section "
            "recall resolved to"
        )
    lines += ["", "The reviewer marks each hit on-question or not (at most 10 on-question).", ""]
    for hit in hits:
        marks = [f"score {hit['score']}", f"terms: {', '.join(hit['terms'])}"]
        if hit["covered_by_claims"]:
            marks.append(f"covered by {len(hit['covered_by_claims'])} Claim(s)")
        if hit["in_recalled_sections"]:
            marks.append("in a recalled section")
        lines += [
            f"## {hit['rank']}. {hit['title']}",
            "",
            f"{hit['company']}, available {hit['available_at'][:10]}, version "
            f"`{hit['source_version_id']}` [{hit['char_start']}, {hit['char_end']}); "
            + "; ".join(marks),
            "",
            *(f"> {line}" for line in hit["text"].splitlines()),
            "",
        ]
    return "\n".join(lines)


def _near_window(filed: str, since: datetime, as_of: datetime) -> bool:
    """Whether a filing date could be in the window (a week's margin: the title's date is the
    filing date, the window is by `available_at`)."""
    day = datetime.fromisoformat(filed).replace(tzinfo=UTC)
    return since - timedelta(days=7) <= day <= as_of + timedelta(days=7)


def _items(answer: Any) -> list[dict[str, Any]]:
    listing = cast(dict[str, Any], answer)["items"] if isinstance(answer, dict) else answer
    return cast(list[dict[str, Any]], listing)


def _time(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _default_out() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return REPO / ".scratch" / "live-runs" / f"{stamp}-baseline"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--base-url", default="https://atlas.ekenhome.se")
    parser.add_argument("--question", required=True)
    parser.add_argument("--company", action="append", required=True, help="a seed company's slug")
    parser.add_argument("--theme", default="photonics")
    parser.add_argument("--as-of", help="ISO time; default now")
    parser.add_argument("--months", type=float, default=18.0)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--per-document", type=int, default=3)
    parser.add_argument("--investigation", help="mark hits its accepted Claims' quotes cover")
    parser.add_argument("--no-recall", dest="recall", action="store_false")
    parser.add_argument("--out")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
