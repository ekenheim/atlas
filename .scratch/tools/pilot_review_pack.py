"""Cut a saved pilot run into small files the reviewers can read whole (the lead's tool).

    python .scratch/tools/pilot_review_pack.py <n> <folder under .scratch/live-runs>

Writes `<folder>/inv-<n>/review/`:
- `claims-<k>.json`: the accepted Claims in chunks by Investigator, each with its quote, its
  700 characters of context either side, the document's title and who selected its passage;
- `claims-compact.json`: every accepted Claim in one line each (for coverage judgments);
- `card.json`: the research card's findings with the Claims each cites, the open questions,
  the unsupported findings, what was not read;
- `run.json`: the stop, usage, tasks with their artifacts, pointed companies, the pointers by
  company and query, the leads kept, the counterevidence, the role calls without their bodies;
- `baseline.json`: the baseline's hits as the script wrote them.
"""

import collections
import json
import pathlib
import sys

CHUNK = 36


def main():
    number, folder = int(sys.argv[1]), sys.argv[2]
    target = pathlib.Path(".scratch/live-runs") / folder / f"inv-{number}"
    out = target / "review"
    out.mkdir(exist_ok=True)

    def load(name):
        return json.loads((target / name).read_text(encoding="utf-8"))

    def save(name, value):
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")

    investigation = load("investigation.json")
    context = load("claims-context.json")
    by_task = collections.defaultdict(list)
    for claim in context:
        by_task[claim["task_key"]].append(claim)
    keep = (
        "claim_id", "subject_name", "predicate", "object_name", "object_text", "product", "layer",
        "epistemic_type", "quote", "source_title", "available_at", "passage_selected_by",
        "context_before", "context_after", "source_version_id", "span_start", "span_end",
    )
    chunks, current = [], []
    for task in sorted(by_task, key=lambda key: -len(by_task[key])):
        claims = by_task[task]
        parts = max(1, -(-len(claims) // CHUNK))
        size = -(-len(claims) // parts)
        pieces = [claims[i : i + size] for i in range(0, len(claims), size)]
        for piece in pieces:
            if len(piece) < CHUNK // 2 and current and len(current) + len(piece) <= CHUNK:
                current += piece
                continue
            if current:
                chunks.append(current)
            current = list(piece)
    if current:
        chunks.append(current)
    index = []
    for position, chunk in enumerate(chunks, start=1):
        save(f"claims-{position}.json", [{key: claim.get(key) for key in keep} for claim in chunk])
        index.append({"chunk": position, "claims": len(chunk), "companies": sorted({c["subject_name"] for c in chunk})})
    save(
        "claims-compact.json",
        [
            {
                "claim_id": c["claim_id"], "subject": c["subject_name"], "predicate": c["predicate"],
                "object": c.get("object_name") or c.get("object_text"), "layer": c.get("layer"),
                "quote": c["quote"], "source_title": c["source_title"],
            }
            for c in context
        ],
    )

    card = investigation.get("research_card") or {}
    quotes = {c["claim_id"]: c for c in context}
    save(
        "card.json",
        {
            "question": investigation["question"],
            "editor_verdict": card.get("editor_verdict"),
            "editor_failure": card.get("editor_failure"),
            "findings": [
                {
                    "number": position,
                    "statement": finding["claim_text"],
                    "limitations": finding.get("limitations"),
                    "open_questions": finding.get("open_questions"),
                    "needs_review": finding.get("needs_review"),
                    "grounded": finding.get("grounded"),  # pilot fix 21
                    "counterevidence_ids": finding.get("counterevidence_ids"),
                    "claims": [
                        {
                            "claim_id": claim_id,
                            "subject": quotes[claim_id]["subject_name"],
                            "predicate": quotes[claim_id]["predicate"],
                            "object": quotes[claim_id].get("object_name") or quotes[claim_id].get("object_text"),
                            "quote": quotes[claim_id]["quote"],
                            "source_title": quotes[claim_id]["source_title"],
                        }
                        for claim_id in finding["claim_ids"]
                        if claim_id in quotes
                    ],
                    "claims_not_in_evidence": [c for c in finding["claim_ids"] if c not in quotes],
                }
                for position, finding in enumerate(card.get("findings", []), start=1)
            ],
            "open_questions": card.get("open_questions"),
            "unsupported_findings": card.get("unsupported_findings"),
            "not_read": card.get("not_read"),
            # Which companies the Skeptic checked (pilot fix 25, the disclosure part).
            "skeptic_coverage": card.get("skeptic_coverage"),
            "grounding_limit": card.get("grounding_limit"),
            "claims_cited_by_some_finding": len({c for f in card.get("findings", []) for c in f["claim_ids"]}),
            "accepted_claims": len(context),
        },
    )

    pointers = investigation.get("pointers", [])
    by_company = collections.Counter(p.get("company_name") or p.get("company_id") for p in pointers)
    by_kind = collections.Counter(p.get("query_kind") or p.get("kind") for p in pointers)
    calls = load("role-calls.json")["role_calls"]
    save(
        "run.json",
        {
            "id": investigation["id"], "question": investigation["question"],
            "status": investigation["status"], "stop_reason": investigation["stop_reason"],
            "stop_detail": investigation.get("stop_detail"),
            "created_at": investigation["created_at"], "stopped_at": investigation["stopped_at"],
            "budgets": investigation["budgets"], "usage": investigation["usage"],
            "tasks": [
                {k: t.get(k) for k in ("key", "role", "status", "detail", "artifacts", "created_at", "updated_at")}
                for t in investigation["tasks"]
            ],
            "pointed_companies": investigation.get("pointed_companies"),
            "pointers": {"total": len(pointers), "by_company": by_company, "by_query_kind": by_kind,
                         "example": pointers[:2]},
            "leads": investigation.get("leads"),
            "searched": card.get("searched"),
            "read": card.get("read"),
            "counterevidence": investigation.get("counterevidence"),
            "bear_context": card.get("bear_context"),
            "contradictions": card.get("contradictions"),
            "role_calls": [
                {
                    "id": c["id"], "role": c["role"], "prompt_version": c["prompt_version"],
                    "status": c["status"], "error": c["error"], "started_at": c["started_at"],
                    "finished_at": c["finished_at"],
                    "attempts": [
                        {k: a.get(k) for k in ("attempt", "tokens_in", "tokens_out", "validation_errors")}
                        for a in c.get("attempts", [])
                    ],
                }
                for c in calls
            ],
            "passage_selected_by": collections.Counter(
                (s.split(":")[0] if isinstance(s, str) else str(s))
                for c in context
                for s in (c.get("passage_selected_by") or ["none"])
            ),
        },
    )
    baseline = target / "baseline" / "results.json"
    if baseline.exists():
        save("baseline.json", json.loads(baseline.read_text(encoding="utf-8")))
    save("index.json", {"chunks": index, "accepted_claims": len(context)})
    print(json.dumps(index))
    for path in sorted(out.iterdir()):
        print(f"{path.stat().st_size:9d} {path.name}")


if __name__ == "__main__":
    main()
