"""Extraction bake-off for ticket 04: retain the Lumentum fixture into a fresh
bank on the running local Hindsight, then score and record what came back.

Usage: python3 spikes/hindsight/bakeoff.py <label>
Writes spikes/hindsight/results/<label>.json. Stdlib only, paced: one document
retained at a time; Hindsight itself is capped at 2 concurrent LLM calls.
"""

import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8888/v1/default/banks"
HERE = pathlib.Path(__file__).parent
FIX = HERE / "fixtures" / "lumentum"


def call(method, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r), time.time() - t
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:2000], time.time() - t


def wait_operation(bank, op_id, limit=1800):
    start = time.time()
    while time.time() - start < limit:
        st, op, _ = call("GET", f"/{bank}/operations/{op_id}")
        status = op.get("status") if isinstance(op, dict) else None
        if status in ("completed", "failed", "cancelled", "error"):
            return op, time.time() - start
        time.sleep(3)
    return {"status": "timeout"}, time.time() - start


def matches(fact_texts, groups):
    for text in fact_texts:
        low = text.lower()
        if all(any(k in low for k in group) for group in groups):
            return text
    return None


def main(label):
    bank = f"atlas-bakeoff-{label}-{int(time.time())}"
    manifest = json.loads((FIX / "manifest.json").read_text())
    expected = json.loads((FIX / "expected-facts.json").read_text())
    result = {"label": label, "bank": bank, "documents": []}

    for doc in manifest["documents"]:
        content = (FIX / doc["file"]).read_text()
        item = {
            "content": content,
            "document_id": f"srcv:{doc['sha256']}",
            "timestamp": doc["acceptance_datetime"],
            "context": f"Lumentum Holdings Inc. SEC {doc['form']}, {doc['section']}",
            "metadata": {"accession": doc["accession"], "url": doc["url"],
                         "available_at": doc["acceptance_datetime"], "form": doc["form"]},
            "tags": ["company:lumentum", "theme:photonics", "source:sec", "doctype:filing"],
        }
        st, resp, dt = call("POST", f"/{bank}/memories", {"items": [item], "async": True})
        entry = {"file": doc["file"], "submit_status": st, "submit_s": round(dt, 2)}
        op_id = resp.get("operation_id") if isinstance(resp, dict) else None
        if op_id:
            op, wait = wait_operation(bank, op_id)
            entry.update(operation_id=op_id, status=op.get("status"), wait_s=round(wait, 1),
                         error=op.get("error_message") or op.get("error"))
        else:
            entry["response"] = resp
        result["documents"].append(entry)
        print(json.dumps(entry)[:400], flush=True)

    st, mem, _ = call("GET", f"/{bank}/memories/list?limit=500")
    items = mem.get("items", []) if isinstance(mem, dict) else []
    texts = [m.get("text") or m.get("content") or "" for m in items]
    result["memories"] = {"status": st, "count": len(items),
                          "by_type": {}, "sample": texts[:60]}
    for m in items:
        t = m.get("fact_type") or m.get("type") or "?"
        result["memories"]["by_type"][t] = result["memories"]["by_type"].get(t, 0) + 1

    hits = []
    for e in expected:
        doc_texts = texts  # facts aren't always attributable per doc in the list view
        hit = matches(doc_texts, e["match_all_of"])
        hits.append({"id": e["id"], "statement": e["statement"], "found": hit is not None, "matched": hit})
    result["expected"] = {"found": sum(h["found"] for h in hits), "total": len(hits), "detail": hits}

    st, stats, _ = call("GET", f"/{bank}/llm-requests/stats")
    result["llm_request_stats"] = stats if st == 200 else {"status": st, "body": stats}
    st, reqs, _ = call("GET", f"/{bank}/llm-requests?limit=200")
    result["llm_requests_raw_status"] = st
    if st == 200:
        rows = reqs.get("items", reqs) if isinstance(reqs, dict) else reqs
        result["llm_requests"] = [
            {k: r.get(k) for k in ("operation", "scope", "model", "status", "error", "latency_ms",
                                   "duration_ms", "input_tokens", "output_tokens", "created_at")
             if k in r}
            for r in (rows if isinstance(rows, list) else [])
        ]

    question = ("What supply constraints or capacity issues does Lumentum describe, "
                "and what evidence supports them? Say what is missing.")
    st, refl, dt = call("POST", f"/{bank}/reflect",
                        {"query": question, "include": {"facts": {}}}, timeout=900)
    if st == 200:
        text = refl.get("text") or refl.get("answer") or ""
        facts = (refl.get("based_on") or {}).get("memories") or refl.get("facts") or []
        result["reflect"] = {"status": st, "seconds": round(dt, 1), "answer": text[:4000],
                             "cited_facts": len(facts) if isinstance(facts, list) else facts,
                             "keys": sorted(refl.keys())}
    else:
        result["reflect"] = {"status": st, "seconds": round(dt, 1), "body": refl}

    out = HERE / "results" / f"{label}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    print(f"\n{label}: memories={result['memories']['count']} "
          f"expected={result['expected']['found']}/{result['expected']['total']} "
          f"reflect={result['reflect']['status']} -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
