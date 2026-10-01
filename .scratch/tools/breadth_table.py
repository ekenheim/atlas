"""Automatic measures of the breadth runs (pilot-review ticket 16). Run from the repo root."""

import collections
import json
import pathlib
import urllib.request
from datetime import datetime, timedelta

BASE = "https://atlas.ekenhome.se/api/v1"
OUT = pathlib.Path(".scratch/live-runs/breadth-0.2.5")


def load(name):
    path = OUT / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def items(answer):
    return answer["items"] if isinstance(answer, dict) and "items" in answer else answer


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=90) as response:
        return json.load(response)


def when(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


relationships = items(get("/relationships?sort=created_at&order=desc&limit=200"))
rows = {}
for number in (2, 3, 4, 5):
    inv = load(f"inv-{number}.json")
    if inv is None:
        continue
    claims = items(load(f"inv-{number}-claims.json") or [])
    calls = (load(f"inv-{number}-role-calls.json") or {}).get("role_calls", [])
    tasks = {t["key"]: t for t in inv["tasks"]}
    start, stop = when(inv["created_at"]), when(inv["stopped_at"]) if inv.get("stopped_at") else None
    accepted = [c for c in claims if c["outcome"] == "accepted"]
    rejected = collections.Counter(c["reason_code"] for c in claims if c["outcome"] != "accepted")
    read = (inv.get("research_card") or {}).get("read", [])
    investigators = [r for r in read if str(r.get("task_key", "")).startswith("investigator")]
    documents = [d for r in investigators for d in r["documents"]]
    admin = {"item-5-02", "item-3-02", "item-9-01", "item-5-07", "item-5-03", "cover"}
    admin_only = [d for d in documents if d["sections"] and set(d["sections"]) <= admin]
    skeptic = tasks.get("skeptic", {}).get("artifacts") or {}
    plan = next((c for c in calls if c["role"] == "skeptic" and c.get("prompt_name") == "skeptic-plan"), None)
    plan_output = (plan or {}).get("output") or {}
    analyst = tasks.get("financial_analyst", {}).get("artifacts") or {}
    sourced = [
        sum(1 for v in proposal["inputs"].values() if v["kind"] == "sourced")
        for proposal in analyst.get("scenario_proposals", [])
    ]
    edges = [
        r
        for r in relationships
        if stop and start <= when(r["created_at"]) <= stop + timedelta(seconds=180)
    ]
    states = collections.Counter(r["review_state"] for r in edges)
    layers = collections.Counter(r["layer"] for r in edges)
    scout = tasks.get("scout", {}).get("artifacts") or {}
    counter = inv.get("counterevidence", [])
    rows[number] = {
        "id": inv["id"],
        "stop": f"{inv['status']} / {inv.get('stop_reason')}",
        "stop_detail": inv.get("stop_detail"),
        "tokens_in": inv["usage"]["tokens_in"],
        "tokens_out": inv["usage"]["tokens_out"],
        "minutes": round((stop - start).total_seconds() / 60, 1) if stop else None,
        "role_calls": len(calls),
        "claims_proposed": len(claims),
        "claims_accepted": len(accepted),
        "accepted_predicates": dict(collections.Counter(c["predicate"] for c in accepted)),
        "accepted_layers": dict(collections.Counter(c["layer"] for c in accepted)),
        "rejections": dict(rejected),
        "investigators": {
            r["task_key"]: {
                "documents": len(r["documents"]),
                "passages": sum(d["passages"] for d in r["documents"]),
                "max_passages_one_document": max((d["passages"] for d in r["documents"]), default=0),
                "accepted": r.get("claims_accepted"),
            }
            for r in investigators
        },
        "documents_admin_items_only": len(admin_only),
        "skeptic": {
            "plan_queries": len(plan_output.get("queries", [])),
            "plan_documents": len(plan_output.get("documents", [])),
            "documents": skeptic.get("documents"),
            "passages": skeptic.get("passages"),
            "fallback": skeptic.get("documents_fallback"),
            "accepted": skeptic.get("counterevidence_accepted"),
            "independent": skeptic.get("counterevidence_independent"),
            "items_naming_no_claim": sum(1 for c in counter if not c.get("contradicts_claim_ids")),
            "by_checklist_item": dict(collections.Counter(c["checklist_item"] for c in counter)),
        },
        "analyst_sourced_inputs_per_company": sourced,
        "findings": len((inv.get("research_card") or {}).get("findings", [])),
        "open_questions": len((inv.get("research_card") or {}).get("open_questions", [])),
        "editor_stop_detail": (tasks.get("editor", {}).get("artifacts") or {}).get("stop_detail"),
        "edges_created": len(edges),
        "edges_by_state": dict(states),
        "edges_by_layer": dict(layers),
        "leads_found_taken": [scout.get("leads_found"), scout.get("leads_taken")],
        "lead_titles": [(lead.get("title") or "")[:70] for lead in inv.get("leads", [])][:10],
    }

(OUT / "table.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
for number, row in rows.items():
    print(f"\n===== investigation {number}: {row['id']}")
    for key, value in row.items():
        if key not in ("id", "lead_titles"):
            print(f"  {key}: {value}")
    for title in row["lead_titles"]:
        print("     lead:", title)
