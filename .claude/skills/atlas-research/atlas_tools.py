"""Atlas's research tools for a session (the `atlas-research` skill). Standard library only.

    python atlas_tools.py companies
    python atlas_tools.py search --company <slug> --q "<terms>" --as-of <ISO> [--top 8] [--per-document 2]
    python atlas_tools.py read --version <id> --start <n> --end <m> --as-of <ISO>
    python atlas_tools.py locate --version <id> --quote "<verbatim text>"
    python atlas_tools.py record --version <id> --quote "<verbatim>" --step <step> --status <status>
        --statement "<one sentence>" --as-of <ISO> [--part <key>] [--period "<as the quote gives it>"]
        [--quantity <value> <unit> <metric>] [--epistemic direct_source_statement|third_party_report]
        [--company <slug>] [--dry-run]
    python atlas_tools.py recall --q "<question>" --as-of <ISO> [--theme photonics] [--companies slug,slug]
        [--max-tokens 4096]
    python atlas_tools.py fact <id>
    python atlas_tools.py judge --statement "<one statement>" --question "<verbatim>" --facts id,id
        [--counter id,id] [--votes 1] [--run <run id>]
    python atlas_tools.py relate --fact <id> --counter <id> --question "<verbatim>" [--run <run id>]

`judge` has Atlas's finding judge compare a statement with the quotes of the Facts it cites and
prints `supported` or `misstated` with the clause bases and the words that go beyond the quotes;
`relate` has the counter-judge say what a counterevidence Fact does to a Fact (`contradicts`,
`limits`, `dates`, `qualifies`, `supports`, `unrelated`). A quota or outage answer (HTTP 503) is
retried a few times with a pause.

Every command prints JSON. `read` and `record` refuse a Source Version available after `--as-of`.
`locate` and `record` find the quote in the archived parse (code-point offsets), folding
typographic quotes, dashes and spaces if the exact text does not occur; a quote occurring more
than once, or not at all, is refused. `record` posts the Fact through `POST /api/v1/facts`, so
Atlas's own checks apply (verbatim span, status wording, period against the document's date);
a refusal is printed with its reason.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("ATLAS_BASE_URL", "https://atlas.ekenhome.se").rstrip("/") + "/api/v1"
FOLD = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        " ": " ",
        " ": " ",
        " ": " ",
    }
)
_versions: dict[str, dict] = {}
_texts: dict[tuple[str, str], str] = {}
_companies: list[dict] | None = None


def get(path: str, raw: bool = False):
    request = urllib.request.Request(BASE + path, headers={"Accept": "application/json, text/plain"})
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read().decode("utf-8")
    return body if raw else json.loads(body)


def post(path: str, body: dict):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        try:
            return error.code, json.loads(text)
        except ValueError:
            return error.code, {"error": text[:1000]}


def post_retrying(path: str, body: dict, tries: int = 4):
    """`post`, again after a pause on a 503 (a quota or outage at the judge: transient)."""
    for attempt in range(tries):
        status, answer = post(path, body)
        if status != 503 or attempt == tries - 1:
            return status, answer
        time.sleep(10 * (attempt + 1))
    return status, answer


def out(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=1))


def companies() -> list[dict]:
    global _companies
    if _companies is None:
        _companies = get("/companies?role=researched&limit=100")["items"]
    return _companies


def company_id(slug: str) -> str:
    for each in companies():
        if each["slug"] == slug:
            return each["id"]
    raise SystemExit(f"unknown company slug: {slug}")


def version(version_id: str) -> dict:
    if version_id not in _versions:
        _versions[version_id] = get(f"/source-versions/{version_id}")
    return _versions[version_id]


def check_as_of(version_id: str, as_of: str | None) -> dict:
    held = version(version_id)
    available = held.get("effective_available_at") or held.get("available_at") or ""
    if as_of and available > as_of:
        raise SystemExit(
            json.dumps(
                {
                    "refused": "available_after_as_of",
                    "available_at": available,
                    "as_of": as_of,
                    "version": version_id,
                }
            )
        )
    return held


def parsed_text(version_id: str, parser_version: str | None) -> tuple[str, str]:
    held = version(version_id)
    parser = parser_version or held.get("current_parser_version") or held.get("parser_version") or ""
    key = (version_id, parser)
    if key not in _texts:
        query = f"?kind=parsed&parser_version={urllib.parse.quote(parser)}" if parser else "?kind=parsed"
        _texts[key] = get(f"/source-versions/{version_id}/content{query}", raw=True)
    return _texts[key], parser


def locate(version_id: str, quote: str, parser_version: str | None = None) -> dict:
    text, parser = parsed_text(version_id, parser_version)
    quote = quote.strip()
    offset_source = "exact"
    count = text.count(quote)
    start = text.find(quote)
    if count == 0:
        folded_text, folded_quote = text.translate(FOLD), quote.translate(FOLD)
        count = folded_text.count(folded_quote)
        start = folded_text.find(folded_quote)
        offset_source = "folded"
    if count != 1:
        return {
            "located": False,
            "reason": "quote_not_found" if count == 0 else "quote_ambiguous",
            "occurrences": count,
            "version": version_id,
        }
    end = start + len(quote)
    return {
        "located": True,
        "version": version_id,
        "parser_version": parser,
        "span_start": start,
        "span_end": end,
        "offset_source": offset_source,
        "archived_quote": text[start:end],
    }


def cmd_companies(_: argparse.Namespace) -> None:
    out(
        [
            {k: each.get(k) for k in ("slug", "id", "display_name", "layer", "country")}
            for each in companies()
        ]
    )


def cmd_search(args: argparse.Namespace) -> None:
    query = urllib.parse.urlencode(
        {
            "q": args.q,
            "company_id": company_id(args.company),
            "as_of": args.as_of,
            "top": args.top,
            "per_document": args.per_document,
        }
    )
    answer = get(f"/archive-search?{query}")
    out(
        {
            "query": answer.get("query"),
            "terms": answer.get("terms"),
            "as_of": answer.get("as_of"),
            "documents_searched": answer.get("documents_searched"),
            "hits": [
                {
                    k: h.get(k)
                    for k in (
                        "source_version_id",
                        "company",
                        "title",
                        "document_type",
                        "form_type",
                        "available_at",
                        "parser_version",
                        "char_start",
                        "char_end",
                        "score",
                        "text",
                    )
                }
                for h in answer.get("hits", [])
            ],
        }
    )


def cmd_read(args: argparse.Namespace) -> None:
    held = check_as_of(args.version, args.as_of)
    text, parser = parsed_text(args.version, args.parser_version)
    start, end = max(0, args.start), min(len(text), args.end)
    out(
        {
            "version": args.version,
            "title": (held.get("source_document") or held.get("document") or {}).get("title"),
            "available_at": held.get("effective_available_at") or held.get("available_at"),
            "parser_version": parser,
            "length": len(text),
            "start": start,
            "end": end,
            "text": text[start:end],
        }
    )


def cmd_locate(args: argparse.Namespace) -> None:
    out(locate(args.version, args.quote, args.parser_version))


def cmd_record(args: argparse.Namespace) -> None:
    held = check_as_of(args.version, args.as_of)
    placed = locate(args.version, args.quote, args.parser_version)
    if not placed["located"]:
        out({"recorded": False, **placed})
        return
    document = held.get("source_document") or held.get("document") or {}
    subject = company_id(args.company) if args.company else document.get("company_id")
    body = {
        "subject_company_id": subject,
        "source_version_id": args.version,
        "quote": placed["archived_quote"],
        "span_start": placed["span_start"],
        "span_end": placed["span_end"],
        "epistemic_type": args.epistemic,
        "parser_version": placed["parser_version"] or None,
        "step": args.step,
        "statement": args.statement,
        "status": args.status,
        "period": args.period,
        "part": args.part,
        "quantity": (
            {"value": float(args.quantity[0]), "unit": args.quantity[1], "metric": args.quantity[2]}
            if args.quantity
            else None
        ),
    }
    if args.dry_run:
        out({"recorded": False, "dry_run": True, "body": body})
        return
    status, answer = post("/facts", body)
    if status == 201:
        out(
            {
                "recorded": True,
                "fact_id": answer.get("id") or (answer.get("fact") or {}).get("id"),
                "answer": answer,
            }
        )
    else:
        out({"recorded": False, "http": status, "answer": answer, "body": body})


def cmd_recall(args: argparse.Namespace) -> None:
    """Memory as a tool: the theme's memories for a question, each with the archived sections
    it resolves to. Hindsight's `query_timestamp` is not a hard filter, so a memory is kept
    only if one of its resolved sections was available by `--as-of`; the rest are dropped and
    counted (`dropped_future`). Read a kept memory's section with `read` before relying on it."""
    scope: dict = {"theme_ids": [args.theme]} if args.theme else {}
    if args.companies:
        scope["company_ids"] = [company_id(s.strip()) for s in args.companies.split(",") if s.strip()]
    body = {
        "query": args.q,
        "scope": scope,
        "max_tokens": args.max_tokens,
        "query_timestamp": args.as_of,
        "include_source_facts": True,
    }
    status, answer = post("/memory/recall", body)
    if status != 200:
        out({"http": status, "answer": answer})
        return
    by_memory: dict[str, list[dict]] = {}
    for section in answer.get("evidence") or []:
        for memory_id in section.get("memory_ids") or []:
            by_memory.setdefault(memory_id, []).append(
                {
                    k: section.get(k)
                    for k in (
                        "source_version_id",
                        "company_id",
                        "form_type",
                        "section_anchor",
                        "section_char_start",
                        "section_char_end",
                        "available_at",
                    )
                }
            )
    kept, dropped = [], 0
    for m in answer.get("memories") or []:
        sections = by_memory.get(m.get("memory_id"), [])
        before = [x for x in sections if (x.get("available_at") or "9999") <= args.as_of]
        if not before:
            dropped += 1
            continue
        kept.append(
            {
                "memory_id": m.get("memory_id"),
                "type": m.get("type"),
                "text": m.get("text"),
                "occurred": [m.get("occurred_start"), m.get("occurred_end")],
                "sections": before,
            }
        )
    out(
        {
            "query": args.q,
            "as_of": args.as_of,
            "counts": answer.get("counts"),
            "memories": kept,
            "dropped_future": dropped,
            "note": "a memory is derived, never evidence: read its section and record a Fact from the archived text",
        }
    )


def cmd_fact(args: argparse.Namespace) -> None:
    out(get(f"/facts/{args.id}"))


def cmd_judge(args: argparse.Namespace) -> None:
    body = {
        "question": args.question,
        "statement": args.statement,
        "fact_ids": [x for x in args.facts.split(",") if x],
        "counter_fact_ids": [x for x in (args.counter or "").split(",") if x],
        "votes": args.votes,
        "run_id": args.run,
    }
    status, answer = post_retrying("/statements/judge", body)
    if status != 200:
        out({"http": status, "answer": answer})
        return
    out(
        {
            "verdict": answer["verdict"],
            "reason": answer["reason"],
            "beyond": answer["beyond"],
            "kinds": answer["kinds"],
            "unverified": answer["unverified"],
            "clauses": answer["clauses"],
            "refs": answer["refs"],
            "counter_relations": answer["counter_relations"],
            "run_id": answer["run_id"],
        }
    )


def cmd_relate(args: argparse.Namespace) -> None:
    body = {
        "question": args.question,
        "fact_id": args.fact,
        "counter_fact_id": args.counter,
        "run_id": args.run,
    }
    status, answer = post_retrying("/statements/relate", body)
    out(answer if status == 200 else {"http": status, "answer": answer})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("companies").set_defaults(run=cmd_companies)
    p = sub.add_parser("search")
    p.add_argument("--company", required=True)
    p.add_argument("--q", required=True)
    p.add_argument("--as-of", required=True)
    p.add_argument("--top", type=int, default=8)
    p.add_argument("--per-document", type=int, default=2)
    p.set_defaults(run=cmd_search)
    p = sub.add_parser("read")
    p.add_argument("--version", required=True)
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--end", type=int, required=True)
    p.add_argument("--as-of", required=True)
    p.add_argument("--parser-version", default=None)
    p.set_defaults(run=cmd_read)
    p = sub.add_parser("locate")
    p.add_argument("--version", required=True)
    p.add_argument("--quote", required=True)
    p.add_argument("--parser-version", default=None)
    p.set_defaults(run=cmd_locate)
    p = sub.add_parser("record")
    p.add_argument("--version", required=True)
    p.add_argument("--quote", required=True)
    p.add_argument("--step", required=True, choices=["constraint", "demand_vs_supply", "relief", "control", "capture", "invalidation", "context"])
    p.add_argument("--status", required=True, choices=["in_effect", "planned", "in_development", "hedged", "regulatory", "reported_by_third_party"])
    p.add_argument("--statement", required=True)
    p.add_argument("--as-of", required=True)
    p.add_argument("--part", default=None)
    p.add_argument("--period", default=None)
    p.add_argument("--quantity", nargs=3, metavar=("VALUE", "UNIT", "METRIC"), default=None)
    p.add_argument("--epistemic", default="direct_source_statement", choices=["direct_source_statement", "third_party_report"])
    p.add_argument("--company", default=None)
    p.add_argument("--parser-version", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(run=cmd_record)
    p = sub.add_parser("recall")
    p.add_argument("--q", required=True)
    p.add_argument("--as-of", required=True)
    p.add_argument("--theme", default="photonics")
    p.add_argument("--companies", default=None)
    p.add_argument("--max-tokens", type=int, default=4096)
    p.set_defaults(run=cmd_recall)
    p = sub.add_parser("fact")
    p.add_argument("id")
    p.set_defaults(run=cmd_fact)
    p = sub.add_parser("judge")
    p.add_argument("--statement", required=True)
    p.add_argument("--question", required=True)
    p.add_argument("--facts", required=True, help="comma-separated Fact ids the statement cites")
    p.add_argument("--counter", default=None, help="comma-separated counterevidence Fact ids")
    p.add_argument("--votes", type=int, default=1)
    p.add_argument("--run", default=None)
    p.set_defaults(run=cmd_judge)
    p = sub.add_parser("relate")
    p.add_argument("--fact", required=True)
    p.add_argument("--counter", required=True)
    p.add_argument("--question", required=True)
    p.add_argument("--run", default=None)
    p.set_defaults(run=cmd_relate)
    args = parser.parse_args()
    try:
        args.run(args)
    except urllib.error.HTTPError as error:
        out({"http": error.code, "error": error.read().decode("utf-8", errors="replace")[:1000]})
        sys.exit(1)


if __name__ == "__main__":
    main()
