"""Save raw theme-scoped recall answers for the pilot's questions and Scout queries (read-only).

The before-measure of the memory-quality effort, taken before ticket 02's probe script exists:
the raw answers are kept so that script's report can be computed from them later. Queries: the
five pilot questions, investigation 1's Scout queries on 0.3.0 and the breadth runs' Scout
queries on 0.2.5. Output: .scratch/live-runs/<stamp>-memory-probe-before/ (not in git).
"""

import json
import pathlib
import sys
import urllib.request

BASE = "https://atlas.ekenhome.se/api/v1"
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from pilot_runs import RUNS  # noqa: E402


def recall(query):
    body = {"query": query, "scope": {"theme_ids": ["photonics"]}}
    request = urllib.request.Request(
        BASE + "/memory/recall", data=json.dumps(body).encode(), headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.load(response)


def scout_queries(path):
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    card = data.get("research_card") or {}
    found = []
    for search in card.get("searched", []):
        found += [q.get("query") or q.get("text") for q in search.get("queries", [])]
    if not found:
        for pointer in data.get("pointers", []):
            text = pointer.get("query_text") or pointer.get("query")
            if text and text not in found:
                found.append(text)
    return [q for q in found if q]


def main():
    out = pathlib.Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    probes = [(f"q{n}", "question", question) for n, (question, _) in RUNS.items()]
    sources = {1: ".scratch/live-runs/pilot-0.3.0/inv-1/investigation.json"}
    sources.update({n: f".scratch/live-runs/breadth-0.2.5/inv-{n}.json" for n in (2, 3, 4, 5)})
    for number, path in sources.items():
        if pathlib.Path(path).exists():
            for index, query in enumerate(scout_queries(path), 1):
                if query != RUNS[number][0]:
                    probes.append((f"q{number}-s{index:02d}", "scout", query))
    summary = []
    for key, kind, query in probes:
        try:
            answer = recall(query)
        except Exception as error:
            print(f"{key}: failed: {error}", flush=True)
            summary.append({"key": key, "kind": kind, "query": query, "error": str(error)})
            continue
        (out / f"{key}.json").write_text(json.dumps(answer, ensure_ascii=False, indent=1), encoding="utf-8")
        memories = answer["memories"]
        sections, companies = set(), set()
        for memory in memories:
            for source in (memory.get("provenance") or {}).get("sources", []):
                sections.add((source.get("source_version_id"), source.get("section_anchor")))
                companies.add(source.get("company_id"))
        row = {
            "key": key, "kind": kind, "query": query, "memories": len(memories),
            "observations": sum(1 for m in memories if m["type"] == "observation"),
            "sections": len(sections), "companies": len(companies), "counts": answer.get("counts"),
        }
        summary.append(row)
        print(f"{key}: {row['memories']} memories, {row['observations']} observations, {row['sections']} sections, {row['companies']} companies", flush=True)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
