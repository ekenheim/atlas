"""Hindsight 0.10.1 feature check for ticket 06.

Exercises each feature the spec relies on (§6.1) against the local spike and
records every request/response pair under spikes/hindsight/recordings/<feature>/.
Those recordings become the contract fixtures for Atlas's fake Hindsight in CI.
Documents are synthetic (fictional companies) so they are safe to commit.

Usage: python3 spikes/hindsight/feature_check.py
Writes spikes/hindsight/results/feature-check.json (evidence + auto-checks).
"""

import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = "http://127.0.0.1:8888"
HERE = pathlib.Path(__file__).parent
REC = HERE / "recordings"
TS = int(time.time())
BANK = f"atlas-fm-{TS}"
BANK_IMPORT = f"atlas-fm-import-{TS}"
BANK_TEMPLATE = f"atlas-fm-template-{TS}"
counters: dict[str, int] = {}
evidence: dict[str, dict] = {}


def clip(v, n=20000):
    if isinstance(v, str):
        return v if len(v) <= n else v[:n] + f"…[{len(v) - n} chars clipped]"
    if isinstance(v, list):
        return [clip(x, n) for x in v]
    if isinstance(v, dict):
        return {k: clip(x, n) for k, x in v.items()}
    return v


def rec(feature, name, method, path, body=None, query=None, raw=None, headers=None, timeout=900):
    url = ROOT + path + ("?" + urllib.parse.urlencode(query, doseq=True) if query else "")
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hdrs = headers or ({"Content-Type": "application/json"} if body is not None else {})
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, payload, ctype = r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        status, payload, ctype = e.code, e.read(), e.headers.get("Content-Type", "")
    secs = round(time.time() - t, 2)
    if "json" in ctype:
        try:
            resp = json.loads(payload)
        except json.JSONDecodeError:
            resp = payload.decode(errors="replace")
    elif ctype.startswith("text"):
        resp = payload.decode(errors="replace")
    else:
        resp = {"_binary_bytes": len(payload), "_content_type": ctype}
    if feature.startswith("_"):  # polls and helper lists aren't recorded
        return status, resp, payload
    counters[feature] = counters.get(feature, 0) + 1
    out = REC / feature / f"{counters[feature]:02d}-{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "request": {"method": method, "path": path, "query": query,
                    "body": clip(body) if raw is None else "<multipart upload>"},
        "response": {"status": status, "seconds": secs, "body": clip(resp)},
    }, indent=2, default=str))
    return status, resp, payload


def wait_op(feature, bank, op_id, name="operation", limit=1800):
    start, last = time.time(), None
    while time.time() - start < limit:
        st, op, _ = rec("_polls", "poll", "GET", f"/v1/default/banks/{bank}/operations/{op_id}")
        last = op if isinstance(op, dict) else {"raw": op}
        if last.get("status") in ("completed", "failed", "cancelled", "error"):
            break
        time.sleep(3)
    counters[feature] = counters.get(feature, 0) + 1
    out = REC / feature / f"{counters[feature]:02d}-{name}-final.json"
    out.write_text(json.dumps({"request": {"method": "GET", "path": f"/v1/default/banks/{bank}/operations/{op_id}"},
                               "response": {"status": 200, "body": clip(last)}}, indent=2, default=str))
    return last


def item(doc_id, text, ts, tags=None, **extra):
    return {"content": text, "document_id": doc_id, "timestamp": ts,
            "context": "Synthetic Atlas feature-check document (fictional companies).",
            "metadata": {"source_version_id": str(uuid.uuid4()), "fixture": "feature-check"},
            **({"tags": tags} if tags is not None else {}), **extra}


def retain(feature, name, bank, items, is_async=True):
    st, resp, _ = rec(feature, name, "POST", f"/v1/default/banks/{bank}/memories",
                      {"items": items, "async": is_async})
    if is_async and isinstance(resp, dict) and resp.get("operation_id"):
        return st, resp, wait_op(feature, bank, resp["operation_id"], name)
    return st, resp, None


def memories(bank, **query):
    st, resp, _ = rec("_lists", "list", "GET", f"/v1/default/banks/{bank}/memories/list",
                      query={"limit": 500, **query})
    return resp.get("items", []) if isinstance(resp, dict) else []


def texts(rows):
    return [r.get("text") or r.get("content") or "" for r in rows]


def section(name, fn):
    print(f"== {name}", flush=True)
    try:
        evidence[name] = fn()
    except Exception as e:  # keep going; the failure is itself evidence
        evidence[name] = {"exception": repr(e)}
    print("   ", json.dumps(evidence[name], default=str)[:600], flush=True)


# --- documents (fictional) ---
AURORA_V1 = ("Aurora Optics Inc. operates an indium phosphide wafer fab in Tucson, Arizona with capacity "
             "of 40,000 wafers per year. Aurora Optics supplies 1.6T transceiver lasers to Halcyon Networks.")
AURORA_V2 = ("Aurora Optics Inc. announced it will close its Tucson, Arizona fab by December 2026 and move "
             "laser production to a contract manufacturer in Penang, Malaysia.")
BETA = "Borealis Photonics Ltd. reported that lead times for its silicon photonics modules rose to 52 weeks."
UNTAGGED = "Cirrus Semiconductor said its gallium arsenide substrate output doubled in 2025."
OLD = "In March 2024 Aurora Optics said demand for 800G optical modules was weak and inventories were high."
NEW = "In August 2026 Aurora Optics said demand for 800G optical modules exceeded supply for the third quarter."


def s_config():
    st, resp, _ = rec("bank_config", "create-bank", "PUT", f"/v1/default/banks/{BANK}", {
        "retain_mission": "Extract economically material facts about capacity, supply agreements, customer "
                          "dependencies and manufacturing constraints. Keep stated and inferred facts distinct.",
        "reflect_mission": "Form source-grounded syntheses; distinguish facts from claims; seek disconfirmation.",
        "disposition_skepticism": 5, "disposition_literalism": 5,
    })
    st2, cfg, _ = rec("bank_config", "get-config", "GET", f"/v1/default/banks/{BANK}/config")
    return {"create_status": st, "config_status": st2,
            "config_keys": sorted(cfg.keys())[:40] if isinstance(cfg, dict) else cfg}


def s_retain_modes():
    st, resp, _ = retain("retain", "sync", BANK, [item("doc-sync", BETA, "2026-08-01T00:00:00Z", ["company:borealis"])], False)
    sync_ok = st == 200
    st2, r2, op2 = retain("retain", "async", BANK, [item("doc-untagged", UNTAGGED, "2026-08-02T00:00:00Z")])
    st3, r3, op3 = retain("retain", "batch", BANK, [
        item("doc-old", OLD, "2024-03-15T00:00:00Z", ["company:aurora"]),
        item("doc-new", NEW, "2026-08-20T00:00:00Z", ["company:aurora"]),
    ])
    return {"sync_status": st, "sync_response_keys": sorted(resp.keys()) if isinstance(resp, dict) else resp,
            "sync_ok": sync_ok, "async_submit": st2, "async_final": (op2 or {}).get("status"),
            "batch_submit": st3, "batch_final": (op3 or {}).get("status"),
            "batch_ops_returned": r3.get("operation_ids") or r3.get("operation_id") if isinstance(r3, dict) else r3,
            "memories_total": len(memories(BANK))}


def s_upsert():
    retain("upsert", "v1", BANK, [item("doc-upsert", AURORA_V1, "2026-01-10T00:00:00Z", ["company:aurora"])])
    v1 = texts(memories(BANK, document_id="doc-upsert"))
    retain("upsert", "v2-same-document-id", BANK, [item("doc-upsert", AURORA_V2, "2026-09-01T00:00:00Z", ["company:aurora"])])
    v2 = texts(memories(BANK, document_id="doc-upsert"))
    mention = lambda ts, k: sum(k in t.lower() for t in ts)
    # Atlas's scheme: each version under its own id keeps both.
    retain("upsert", "v1-own-id", BANK, [item("srcv:aurora-v1", AURORA_V1, "2026-01-10T00:00:00Z", ["company:aurora"])])
    retain("upsert", "v2-own-id", BANK, [item("srcv:aurora-v2", AURORA_V2, "2026-09-01T00:00:00Z", ["company:aurora"])])
    own1 = texts(memories(BANK, document_id="srcv:aurora-v1"))
    own2 = texts(memories(BANK, document_id="srcv:aurora-v2"))
    st, doc, _ = rec("upsert", "get-document", "GET", "/v1/default/banks/%s/documents/doc-upsert" % BANK)
    return {"v1_facts": len(v1), "v1_mentions_40000": mention(v1, "40,000") + mention(v1, "40000"),
            "after_v2_facts": len(v2), "after_v2_mentions_40000": mention(v2, "40,000") + mention(v2, "40000"),
            "after_v2_mentions_penang": mention(v2, "penang"),
            "own_ids_v1_facts": len(own1), "own_ids_v2_facts": len(own2),
            "document_status": st}


def s_operations():
    st, ops, _ = rec("operations", "list", "GET", f"/v1/default/banks/{BANK}/operations", query={"limit": 50})
    rows = ops.get("items") or ops.get("operations") or [] if isinstance(ops, dict) else []
    statuses = {}
    for o in rows:
        statuses[o.get("status")] = statuses.get(o.get("status"), 0) + 1
    one = rows[0] if rows else {}
    return {"list_status": st, "count": len(rows), "statuses": statuses, "fields": sorted(one.keys())}


def recall(name, feature, **body):
    st, resp, _ = rec(feature, name, "POST", f"/v1/default/banks/{BANK}/memories/recall",
                      {"query": "optical module demand and supply constraints", "budget": "mid", **body})
    rows = resp.get("results") or resp.get("memories") or [] if isinstance(resp, dict) else []
    return st, rows


def which(rows):
    keys = {"aurora": "aurora", "borealis": "borealis", "cirrus": "cirrus"}
    found = {k: 0 for k in keys}
    for r in rows:
        t = (r.get("text") or "").lower()
        for k in keys:
            found[k] += k in t
    return found


def s_tags():
    out = {}
    for mode in ("any", "any_strict", "all_strict", "exact"):
        st, rows = recall(f"tags-{mode}", "tags", tags=["company:aurora"], tags_match=mode)
        out[mode] = {"status": st, "results": len(rows), "by_company": which(rows)}
    st, rows = recall("no-tags", "tags")
    out["no_filter"] = {"status": st, "results": len(rows), "by_company": which(rows)}
    return out


def s_temporal():
    st, rows = recall("window-2024", "temporal", query_timestamp="2024-04-01T00:00:00Z",
                      temporal_window={"start": "2024-01-01T00:00:00Z", "end": "2024-12-31T23:59:59Z"})
    joined = [(r.get("text") or "").lower() for r in rows]
    future = [t for t in joined if "2026" in t or "exceeded supply" in t or "penang" in t]
    return {"status": st, "results": len(rows), "future_dated_results": len(future),
            "first_results": [t[:120] for t in joined[:5]],
            "hard_filter": len(future) == 0}


def s_reflect():
    st, resp, _ = rec("reflect", "provenance", "POST", f"/v1/default/banks/{BANK}/reflect",
                      {"query": "Is Aurora Optics capacity constrained? Cite evidence.", "include": {"facts": {}}})
    based = resp.get("based_on") or {} if isinstance(resp, dict) else {}
    facts = based.get("memories") or based.get("facts") or []
    first = facts[0] if facts else {}
    prov = None
    if first.get("id"):
        st2, mem, _ = rec("reflect", "resolve-memory", "GET", f"/v1/default/banks/{BANK}/memories/{first['id']}")
        prov = {"status": st2, "fields": sorted(mem.keys()) if isinstance(mem, dict) else mem,
                "document_id": mem.get("document_id") if isinstance(mem, dict) else None}
    schema = {"type": "object", "properties": {
        "constrained": {"type": "boolean"}, "evidence": {"type": "array", "items": {"type": "string"}}},
        "required": ["constrained", "evidence"]}
    st3, sresp, _ = rec("reflect", "structured", "POST", f"/v1/default/banks/{BANK}/reflect",
                        {"query": "Is Aurora Optics capacity constrained?", "response_schema": schema})
    union = {"type": "object", "properties": {"n": {"type": ["number", "null"]}}, "required": ["n"]}
    st4, uresp, _ = rec("reflect", "structured-union-type", "POST", f"/v1/default/banks/{BANK}/reflect",
                        {"query": "How many wafers per year?", "response_schema": union})
    return {"status": st, "based_on_keys": sorted(based.keys()), "cited": len(facts),
            "cited_fact_fields": sorted(first.keys()), "resolved_memory": prov,
            "structured_status": st3,
            "structured_output": sresp.get("structured_output") if isinstance(sresp, dict) else None,
            "structured_output_error": sresp.get("structured_output_error") if isinstance(sresp, dict) else None,
            "union_type_status": st4}


def s_observations():
    st, resp, _ = rec("observations", "consolidate", "POST", f"/v1/default/banks/{BANK}/consolidate", {})
    op = wait_op("observations", BANK, resp["operation_id"], "consolidate") if isinstance(resp, dict) and resp.get("operation_id") else None
    st2, obs, _ = rec("observations", "list", "GET", f"/v1/default/banks/{BANK}/observations", query={"limit": 100})
    rows = obs.get("items") or obs.get("observations") or [] if isinstance(obs, dict) else []
    return {"consolidate_status": st, "consolidate_final": (op or {}).get("status"),
            "observations": len(rows), "sample": [(o.get("text") or "")[:150] for o in rows[:3]]}


def s_mental_models():
    st, resp, _ = rec("mental_models", "create", "POST", f"/v1/default/banks/{BANK}/mental-models", {
        "id": "theme-status", "name": "Theme status",
        "source_query": "What are the documented developments in optical module supply and demand, "
                        "with supporting and opposing evidence?",
        "trigger": {"refresh_after_consolidation": False, "min_refresh_interval_seconds": 3600},
    })
    op = wait_op("mental_models", BANK, resp["operation_id"], "create") if isinstance(resp, dict) and resp.get("operation_id") else None
    st2, mm, _ = rec("mental_models", "get", "GET", f"/v1/default/banks/{BANK}/mental-models/theme-status")
    st3, r3, _ = rec("mental_models", "refresh", "POST", f"/v1/default/banks/{BANK}/mental-models/theme-status/refresh", {})
    op3 = wait_op("mental_models", BANK, r3["operation_id"], "refresh") if isinstance(r3, dict) and r3.get("operation_id") else None
    st4, hist, _ = rec("mental_models", "history", "GET", f"/v1/default/banks/{BANK}/mental-models/theme-status/history")
    content = (mm.get("content") or mm.get("text") or "") if isinstance(mm, dict) else ""
    return {"create_status": st, "create_final": (op or {}).get("status"), "get_status": st2,
            "content_chars": len(content), "fields": sorted(mm.keys()) if isinstance(mm, dict) else mm,
            "refresh_status": st3, "refresh_final": (op3 or {}).get("status"),
            "refresh_response": r3 if st3 != 200 else None, "history_status": st4,
            "history_entries": len(hist.get("items", hist)) if isinstance(hist, (dict, list)) else hist}


def s_knowledge_pages():
    st, resp, _ = rec("knowledge_pages", "create", "POST", f"/v1/default/banks/{BANK}/knowledge-base/pages", {
        "name": "Aurora Optics overview",
        "source_query": "Summarize what is documented about Aurora Optics' capacity and customers.",
    })
    op = wait_op("knowledge_pages", BANK, resp["operation_id"], "create") if isinstance(resp, dict) and resp.get("operation_id") else None
    st2, pages, _ = rec("knowledge_pages", "list", "GET", f"/v1/default/banks/{BANK}/knowledge-base/pages")
    return {"create_status": st, "create_response_keys": sorted(resp.keys()) if isinstance(resp, dict) else resp,
            "create_final": (op or {}).get("status"), "list_status": st2,
            "pages": len(pages.get("items", pages)) if isinstance(pages, (dict, list)) else pages}


def s_templates():
    st, schema, _ = rec("bank_templates", "schema", "GET", "/v1/bank-template-schema")
    st2, manifest, _ = rec("bank_templates", "export", "GET", f"/v1/default/banks/{BANK}/export")
    st3, dry, _ = rec("bank_templates", "import-dry-run", "POST", f"/v1/default/banks/{BANK_TEMPLATE}/import",
                      manifest if isinstance(manifest, dict) else {}, query={"dry_run": "true"})
    st4, real, _ = rec("bank_templates", "import", "POST", f"/v1/default/banks/{BANK_TEMPLATE}/import",
                       manifest if isinstance(manifest, dict) else {})
    st5, cfg, _ = rec("bank_templates", "imported-config", "GET", f"/v1/default/banks/{BANK_TEMPLATE}/config")
    cfg_text = json.dumps(cfg)
    return {"schema_status": st, "export_status": st2,
            "manifest_keys": sorted(manifest.keys()) if isinstance(manifest, dict) else manifest,
            "dry_run_status": st3, "dry_run": dry, "import_status": st4, "import": real,
            "imported_config_has_retain_mission": "Extract economically material" in cfg_text}


def s_export_import():
    st, resp, _ = rec("export_import", "export", "POST", f"/v1/default/banks/{BANK}/document-transfer/export",
                      query={"document_id": ["srcv:aurora-v1", "srcv:aurora-v2"]})
    op = wait_op("export_import", BANK, resp["operation_id"], "export") if isinstance(resp, dict) and resp.get("operation_id") else {}
    meta = op.get("result_metadata") or {}
    key = meta.get("storage_key")
    if not key:
        return {"export_status": st, "export_final": op.get("status"), "result_metadata": meta}
    st2, _, blob = rec("export_import", "download", "GET", f"/v1/default/files/download/{key}")
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"export.zip\"\r\n"
            f"Content-Type: application/zip\r\n\r\n").encode() + blob + f"\r\n--{boundary}--\r\n".encode()
    st3, r3, _ = rec("export_import", "import", "POST", f"/v1/default/banks/{BANK_IMPORT}/document-transfer",
                     raw=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    op3 = wait_op("export_import", BANK_IMPORT, r3["operation_id"], "import") if isinstance(r3, dict) and r3.get("operation_id") else {}
    imported = texts(memories(BANK_IMPORT))
    st4, stats, _ = rec("export_import", "import-llm-requests", "GET", f"/v1/default/banks/{BANK_IMPORT}/llm-requests/stats")
    return {"export_status": st, "export_final": op.get("status"), "bytes": len(blob), "download_status": st2,
            "import_status": st3, "import_final": op3.get("status"), "import_error": op3.get("error_message"),
            "imported_memories": len(imported), "import_llm_requests": stats.get("buckets") if isinstance(stats, dict) else stats}


def s_llm_log():
    st, stats, _ = rec("llm_requests", "stats", "GET", f"/v1/default/banks/{BANK}/llm-requests/stats")
    return {"status": st, "buckets": stats.get("buckets") if isinstance(stats, dict) else stats}


if __name__ == "__main__":
    for name, fn in [("bank_config", s_config), ("retain_modes", s_retain_modes), ("upsert", s_upsert),
                     ("operations", s_operations), ("tags", s_tags), ("temporal", s_temporal),
                     ("reflect", s_reflect), ("observations", s_observations),
                     ("mental_models", s_mental_models), ("knowledge_pages", s_knowledge_pages),
                     ("bank_templates", s_templates), ("export_import", s_export_import),
                     ("llm_requests", s_llm_log)]:
        section(name, fn)
    out = HERE / "results" / "feature-check.json"
    out.write_text(json.dumps({"bank": BANK, "evidence": evidence}, indent=2, default=str))
    print("->", out)
