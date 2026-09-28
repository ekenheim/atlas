"""Follow-up probes for ticket 06: provenance hops, observation/page listing routes."""
import json, sys
import feature_check as fc

bank = sys.argv[1]
out = {}
st, obs, _ = fc.rec("observations", "list-via-memories", "GET", f"/v1/default/banks/{bank}/memories/list",
                    query={"type": "observation", "limit": 100})
rows = obs.get("items", []) if isinstance(obs, dict) else []
out["observations_via_memories_list"] = {"status": st, "count": len(rows)}
if rows:
    o = rows[0]
    st2, full, _ = fc.rec("reflect", "resolve-observation", "GET", f"/v1/default/banks/{bank}/memories/{o['id']}")
    src = (full.get("source_memory_ids") or []) if isinstance(full, dict) else []
    hops = []
    for sid in src[:3]:
        st3, m, _ = fc.rec("reflect", "resolve-source-memory", "GET", f"/v1/default/banks/{bank}/memories/{sid}")
        hops.append({"status": st3, "type": m.get("type"), "document_id": m.get("document_id"),
                     "chunk_id": m.get("chunk_id"), "metadata": m.get("metadata")})
    out["provenance_two_hop"] = {"observation_document_id": full.get("document_id"), "source_hops": hops}
st, tree, _ = fc.rec("knowledge_pages", "tree", "GET", f"/v1/default/banks/{bank}/knowledge-base/tree")
out["knowledge_tree"] = {"status": st, "body": str(tree)[:400]}
pages = []
def walk(n):
    if isinstance(n, dict):
        if str(n.get("id", "")).startswith("kp-") or n.get("type") == "page": pages.append(n.get("id"))
        for v in n.values(): walk(v)
    elif isinstance(n, list):
        for v in n: walk(v)
walk(tree)
if pages:
    st, page, _ = fc.rec("knowledge_pages", "get-page", "GET", f"/v1/default/banks/{bank}/knowledge-base/pages/{pages[0]}")
    out["knowledge_page"] = {"status": st, "keys": sorted(page.keys()) if isinstance(page, dict) else page,
                             "content_chars": len((page.get("content") or "")) if isinstance(page, dict) else 0}
st, hist, _ = fc.rec("mental_models", "history-check", "GET", f"/v1/default/banks/{bank}/mental-models/theme-status/history")
out["mental_model_history_entries"] = len(hist) if isinstance(hist, list) else hist
print(json.dumps(out, indent=2, default=str)[:3000])
res = fc.HERE / "results" / "feature-check.json"
d = json.loads(res.read_text()); d["followup"] = out; res.write_text(json.dumps(d, indent=2, default=str))
