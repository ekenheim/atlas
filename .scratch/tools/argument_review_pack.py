"""Cut a saved argument-plan run into the reviewers' files (the lead's tool).

    python .scratch/tools/argument_review_pack.py <n> <folder under .scratch/live-runs>

Writes `<folder>/inv-<n>/review/` (not in git: quotes include licensed transcript text):
- `facts-<k>.json`: the run's Facts in chunks of 36, each with its company, step, status,
  statement, quantity and period, the quote, the source title, and 700 characters of the
  archived parse either side (read once per Source Version through the API);
- `facts-compact.json`: every Fact in one line each (for coverage judgments);
- `card.json`: the argument card's steps, each with its status, its kept statements (with the
  quotes of the Facts each cites), its counterevidence, what remains unchecked, and the
  statements dropped by the checks;
- `run.json`: stop, usage, tasks with their artifacts, role calls without their bodies;
- `baseline.json`: the archive-search baseline's hits;
- `index.json`: the chunks.
"""

import collections
import json
import pathlib
import sys
import urllib.request

BASE = "https://atlas.ekenhome.se/api/v1"
CONTEXT = 700
CHUNK = 36


def get_text(path: str) -> str:
    with urllib.request.urlopen(BASE + path, timeout=120) as response:
        return response.read().decode("utf-8")


def main() -> None:
    number, folder = int(sys.argv[1]), sys.argv[2]
    target = pathlib.Path(".scratch/live-runs") / folder / f"inv-{number}"
    out = target / "review"
    out.mkdir(exist_ok=True)

    def load(name: str):
        return json.loads((target / name).read_text(encoding="utf-8"))

    def save(name: str, value) -> None:
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")

    investigation = load("investigation.json")
    card = investigation.get("research_card") or {}
    facts = load("facts.json")
    facts = facts.get("items", facts) if isinstance(facts, dict) else facts

    # Company names and source titles from the card's steps (each Fact appears there).
    company: dict[str, str] = {}
    title: dict[str, str] = {}
    for step in card.get("steps") or []:
        for each in [*(step.get("facts") or []), *(step.get("counterevidence") or [])]:
            fid = each.get("fact_id")
            if fid:
                company[fid] = each.get("company_name") or company.get(fid, "")
                title[fid] = each.get("source_title") or title.get(fid, "")

    # A Fact the card doesn't cite (or a run with no card) takes its company from its subject.
    names = {each["id"]: each["display_name"] for each in json.loads(get_text("/companies?limit=500")).get("items", [])}
    for fact in facts:
        if not company.get(fact["id"]):
            company[fact["id"]] = names.get(fact["assertion"].get("subject_company_id") or "", "")

    texts: dict[tuple[str, str], str] = {}

    def context(fact: dict) -> tuple[str, str]:
        held = fact["assertion"]
        key = (held["source_version_id"], held.get("parser_version") or "")
        if key not in texts:
            query = f"?kind=parsed&parser_version={key[1]}" if key[1] else "?kind=parsed"
            try:
                texts[key] = get_text(f"/source-versions/{key[0]}/content{query}")
            except Exception as error:  # noqa: BLE001 - a missing parse leaves the context empty
                print(f"  no parse for {key[0]}: {error}")
                texts[key] = ""
        text = texts[key]
        start, end = held["span_start"], held["span_end"]
        return text[max(0, start - CONTEXT) : start], text[end : end + CONTEXT]

    rows = []
    for fact in facts:
        before, after = context(fact)
        rows.append(
            {
                "fact_id": fact["id"],
                "company": company.get(fact["id"], ""),
                "step": fact["step"],
                "status": fact["status"],
                "statement": fact["statement"],
                "quantity": fact.get("quantity"),
                "period": fact.get("period"),
                "challenges": (fact["assertion"].get("value_json") or {}).get("challenges") or [],
                "quote": fact["assertion"]["quote"],
                "source_title": title.get(fact["id"], ""),
                "context_before": before,
                "context_after": after,
            }
        )
    index = []
    for position, start in enumerate(range(0, len(rows), CHUNK), start=1):
        chunk = rows[start : start + CHUNK]
        save(f"facts-{position}.json", chunk)
        index.append({"chunk": position, "facts": len(chunk)})
    save(
        "facts-compact.json",
        [
            {k: r[k] for k in ("fact_id", "company", "step", "status", "statement", "quantity", "period")}
            | {"quote": r["quote"][:400]}
            for r in rows
        ],
    )

    quotes = {r["fact_id"]: r for r in rows}

    def cited(items: list) -> list:
        return [
            {
                "fact_id": each.get("fact_id"),
                "company": each.get("company_name"),
                "status": each.get("status"),
                "quote": (quotes.get(each.get("fact_id")) or {}).get("quote"),
                "source_title": each.get("source_title"),
            }
            for each in items or []
        ]

    save(
        "card.json",
        {
            "question": investigation["question"],
            "steps": [
                {
                    "step": s["step"],
                    "asks": s.get("asks"),
                    "status": s.get("status"),
                    "statements": [
                        {
                            "statement": k.get("statement"),
                            "facts": cited(k.get("facts")),
                            "counterevidence": cited(k.get("counterevidence")),
                        }
                        for k in (s.get("statements") or [])
                    ],
                    "counterevidence_count": len(s.get("counterevidence") or []),
                    "facts_count": len(s.get("facts") or []),
                    "unchecked": s.get("unchecked"),
                }
                for s in card.get("steps") or []
            ],
            "unsupported_findings": card.get("unsupported_findings"),
            "open_questions": card.get("open_questions"),
            "grounding_limit": card.get("grounding_limit"),
        },
    )
    calls = load("role-calls.json")
    calls = calls.get("role_calls", calls)
    save(
        "run.json",
        {
            "id": investigation["id"],
            "question": investigation["question"],
            "status": investigation["status"],
            "stop_reason": investigation["stop_reason"],
            "stop_detail": investigation.get("stop_detail"),
            "created_at": investigation["created_at"],
            "stopped_at": investigation.get("stopped_at"),
            "usage": investigation["usage"],
            "tasks": [
                {k: t.get(k) for k in ("key", "role", "status", "detail", "artifacts")}
                for t in investigation["tasks"]
            ],
            "leads": investigation.get("leads"),
            "role_calls": collections.Counter(f"{c['role']}:{c['status']}" for c in calls),
            "facts_by_step": collections.Counter(r["step"] for r in rows),
            "facts_with_quantity": sum(1 for r in rows if r["quantity"]),
        },
    )
    baseline = target / "baseline" / "results.json"
    if baseline.exists():
        save("baseline.json", json.loads(baseline.read_text(encoding="utf-8")))
    save("index.json", {"chunks": index, "facts": len(rows)})
    print(json.dumps(index))


if __name__ == "__main__":
    main()
