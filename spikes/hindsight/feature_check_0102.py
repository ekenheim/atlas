"""Hindsight 0.10.2 feature check for memory-quality ticket 01.

Two jobs against the local spike (`compose.yaml`, the cluster's 0.10.2 image):

1. Record every feature the memory-quality spec uses, one folder per feature under
   `recordings/` (they become contract fixtures for the recorded fake): explicit
   `observation_scopes` and the scopes listing, recall's options and `scores`, retain's
   `entities` with `resolve_entities: false`, an `entity_labels` group with `tag: true`, the
   memory listing by `entity_id`, `dry-run-extract`, reflect's `budget` and
   `exclude_mental_models`, a tagged mental model, chunks, and a document's `reprocess`.
2. Re-run `feature_check.py`'s checks on 0.10.2 into `rerun-0.10.2/` (not loaded by the fake;
   the 0.10.1 recordings stay the contract fixtures they are) so the verdicts can be compared.

LLM requests are capped (`CAP`, counted from every bank's own LLM request log before each
step that spends any); a step that would pass the cap is skipped and the skip is evidence.
Documents are synthetic (fictional companies). The banks are deleted at the end.

Usage: python spikes/hindsight/feature_check_0102.py
Writes spikes/hindsight/results/feature-check-0.10.2.json.
"""

import json
import os
import time
import traceback

import feature_check as fc

HERE = fc.HERE
NEW = HERE / "recordings"
RERUN = HERE / "rerun-0.10.2"
# 60 for the ticket; SPIKE_LLM_CAP lowers it by what an earlier, aborted run already spent.
CAP = int(os.environ.get("SPIKE_LLM_CAP", "60"))
TS = fc.TS
M = f"atlas-q01-{TS}"  # main bank: the re-run and most new features
L = f"atlas-q01-labels-{TS}"  # small chunks, entity labels, reprocess
fc.BANK, fc.BANK_IMPORT, fc.BANK_TEMPLATE = M, f"atlas-q01-import-{TS}", f"atlas-q01-template-{TS}"
BANKS = [M, L, fc.BANK_IMPORT, fc.BANK_TEMPLATE]
evidence: dict[str, object] = {}
skipped: list[dict[str, object]] = []


def new(feature, name, method, path, body=None, query=None):
    fc.REC = NEW
    st, resp, _ = fc.rec(feature, name, method, path, body, query)
    return st, resp


def wait_new(feature, bank, op_id, name):
    fc.REC = NEW
    return fc.wait_op(feature, bank, op_id, name)


def helper(method, path, body=None, query=None):
    """An unrecorded call (polls, counts, lists used only to compute evidence)."""
    st, resp, _ = fc.rec("_helper", "x", method, path, body, query)
    return st, resp


def llm_entries(bank):
    rows, offset = [], 0
    while True:
        st, resp = helper("GET", f"/v1/default/banks/{bank}/llm-requests", query={"limit": 500, "offset": offset})
        if st != 200 or not isinstance(resp, dict):
            return rows
        items = resp.get("items") or resp.get("requests") or []
        rows += items
        if len(items) < 500:
            return rows
        offset += 500


def llm_count():
    """Every LLM request in this run's banks, by bank and operation (from each bank's log)."""
    by_bank = {}
    for bank in BANKS:
        ops: dict[str, int] = {}
        for r in llm_entries(bank):
            key = f"{r.get('operation')}/{r.get('scope')}/{r.get('status')}"
            ops[key] = ops.get(key, 0) + 1
        by_bank[bank] = ops
    total = sum(sum(v.values()) for v in by_bank.values())
    return total, by_bank


def afford(n, what):
    total, _ = llm_count()
    if total + n > CAP:
        skipped.append({"step": what, "llm_requests_so_far": total, "would_need_up_to": n})
        print(f"   SKIP {what}: {total} + {n} > {CAP}", flush=True)
        return False
    return True


def delta(before):
    after, by_bank = llm_count()
    return after - before, by_bank


def items_of(resp):
    if isinstance(resp, dict):
        return resp.get("items") or resp.get("results") or resp.get("memories") or []
    return []


def memories_of(bank, **query):
    st, resp = helper("GET", f"/v1/default/banks/{bank}/memories/list", query={"limit": 500, **query})
    return items_of(resp)


def item(doc_id, text, ts, tags=None, context=None, **extra):
    out = fc.item(doc_id, text, ts, tags, **extra)
    if context is not None:
        out["context"] = context
    return out


def retain_new(feature, name, bank, items):
    st, resp = new(feature, name, "POST", f"/v1/default/banks/{bank}/memories", {"items": items, "async": True})
    op = wait_new(feature, bank, resp["operation_id"], name) if isinstance(resp, dict) and resp.get("operation_id") else None
    return st, resp, op


def consolidate_new(feature, bank, name="consolidate"):
    st, resp = new(feature, name, "POST", f"/v1/default/banks/{bank}/consolidate", {})
    op = wait_new(feature, bank, resp["operation_id"], name) if isinstance(resp, dict) and resp.get("operation_id") else None
    return st, op


def step(name, fn):
    print(f"== {name}", flush=True)
    try:
        evidence[name] = fn()
    except Exception as e:  # keep going; the failure is itself evidence
        evidence[name] = {"exception": repr(e), "traceback": traceback.format_exc()[-1500:]}
    print("   ", json.dumps(evidence[name], default=str)[:700], flush=True)


# --- documents (fictional) ---
SCOPE_ONE = ("Aurora Optics Inc. said its Tucson indium phosphide fab ran at full utilization in the "
             "second quarter of fiscal 2026 and that laser output cannot grow until a new MOCVD line "
             "qualifies in early 2027.")
SCOPE_TWO = ("Borealis Photonics Ltd. signed a three-year agreement to buy indium phosphide substrates "
             "from Cirrus Semiconductor, citing a shortage of six-inch substrates across the industry.")
# The short forms ("Aurora", "Halcyon") are the names the entities given with the item should
# take over; nothing in the text says "Aurora Optics Inc.".
ENTITIES = ("Aurora said that Halcyon accounted for 38% of fiscal 2026 revenue, and that Halcyon will "
            "take most of Aurora's 3.2T laser output in fiscal 2027.")
# A section-like text with paragraphs, a tab, double spaces, typographic quotes and dashes,
# cut into several chunks by the labels bank's small retain_chunk_size.
CHUNKED = (
    "Item 1A. Risk Factors\n\n"
    "Aurora Optics Inc. (“Aurora”) depends on a single supplier, Cirrus Semiconductor, for "
    "six-inch indium phosphide substrates.  Cirrus has told Aurora that its 2026 output is fully "
    "allocated — any new order ships in 2027 at the earliest.\n\n"
    "\tOur epitaxy capacity is concentrated in one MOCVD facility in Tucson, Arizona. A disruption "
    "there would halt production of our EML and CW lasers for several months.\n\n"
    "Halcyon Networks, our largest customer, accounted for 38% of fiscal 2026 revenue. Halcyon "
    "buys our 1.6T transceivers for its AI cluster switches; it may qualify a second source.\n\n"
    "We outsource module assembly to a contract manufacturer in Penang, Malaysia. The contract "
    "manufacturer’s yields on 1.6T modules were below plan in the fourth quarter, which "
    "reduced our shipments by about 12%.\n"
)
LABELLED = ("Borealis Photonics Ltd. said lead times for its EML lasers rose to 40 weeks, while its "
            "silicon photonics transceiver modules shipped on schedule to Halcyon Networks.")
DRY_RUN = ("Cirrus Semiconductor said its six-inch indium phosphide substrate output doubled in 2026 "
           "and that its epitaxial wafer line in Fremont is sold out through 2027.")

LAYER_LABELS = [{
    "key": "layer",
    "description": "The optical supply-chain layer(s) the fact concerns. Leave it out when none applies.",
    "type": "multi-values",
    "optional": True,
    "tag": True,
    "values": [
        {"value": "substrate", "description": "bare wafers and substrates (InP, GaAs, SOI)"},
        {"value": "epi", "description": "epitaxial wafers grown on substrates"},
        {"value": "chip-laser", "description": "laser and photonic chips: EML, DML, CW and VCSEL lasers, PICs"},
        {"value": "dsp", "description": "DSPs, drivers, TIAs and other electrical ICs for optics"},
        {"value": "module", "description": "optical transceivers and modules"},
        {"value": "contract-manufacturing", "description": "assembly, test and contract manufacturing of optics"},
        {"value": "system", "description": "systems built from modules: switches, optical transport, AI clusters"},
    ],
}]

RECALL_QUERY = "Aurora Optics laser capacity and supply constraints"


# --- setup and the re-run of the 0.10.1 checks -------------------------------------------------

def s_version():
    st, v = new("server_version", "version", "GET", "/version")
    fc.REC = RERUN
    fc.rec("monitoring", "health", "GET", "/health")
    fc.rec("monitoring", "version", "GET", "/version")
    return {"status": st, "version": v}


def s_rerun_config():
    fc.REC = RERUN
    out = fc.s_config()
    # Retains in the main bank don't consolidate by themselves, so each consolidation's LLM
    # requests can be attributed to the items it processed (the cluster consolidates after
    # every retain; an explicit consolidate processes the same unconsolidated facts).
    st, cfg, _ = fc.rec("bank_config", "disable-auto-consolidation", "PATCH", f"/v1/default/banks/{M}/config",
                        {"updates": {"enable_auto_consolidation": False}})
    out["auto_consolidation_off"] = {"status": st, "value": (cfg.get("config") or {}).get("enable_auto_consolidation")
                                     if isinstance(cfg, dict) else cfg}
    if out["auto_consolidation_off"]["value"] is not False:
        raise SystemExit(f"could not turn auto-consolidation off: {cfg}")
    return out


def s_labels_bank():
    fc.REC = RERUN
    st, resp, _ = fc.rec("_helper", "x", "PUT", f"/v1/default/banks/{L}", {
        "retain_mission": "Extract economically material facts about capacity, supply agreements, customer "
                          "dependencies and manufacturing constraints. Keep stated and inferred facts distinct.",
    })
    st2, cfg = helper("PATCH", f"/v1/default/banks/{L}/config",
                      {"updates": {"enable_auto_consolidation": False, "retain_chunk_size": 700}})
    conf = cfg.get("config", {}) if isinstance(cfg, dict) else {}
    if conf.get("enable_auto_consolidation") is not False or conf.get("retain_chunk_size") != 700:
        raise SystemExit(f"labels bank config not applied: {cfg}")
    return {"create": st, "config": st2, "retain_chunk_size": conf.get("retain_chunk_size")}


def rerun(fn, est, what):
    def run():
        if not afford(est, what):
            return {"skipped": "LLM cap"}
        fc.REC = RERUN
        before, _ = llm_count()
        out = fn()
        out["llm_requests"] = delta(before)[0]
        return out
    return run


def s_rerun_free():
    fc.REC = RERUN
    out = {"operations": fc.s_operations(), "tags": fc.s_tags(), "temporal": fc.s_temporal()}
    return out


def s_rerun_followup():
    """feature_followup.py's free probes: observation listing and the provenance hops."""
    fc.REC = RERUN
    out = {}
    st, obs, _ = fc.rec("observations", "list-via-memories", "GET", f"/v1/default/banks/{M}/memories/list",
                        query={"type": "observation", "limit": 100})
    rows = items_of(obs)
    out["observations_via_memories_list"] = {"status": st, "count": len(rows)}
    if rows:
        st2, full, _ = fc.rec("reflect", "resolve-observation", "GET", f"/v1/default/banks/{M}/memories/{rows[0]['id']}")
        hops = []
        for sid in (full.get("source_memory_ids") or [])[:2] if isinstance(full, dict) else []:
            st3, m, _ = fc.rec("reflect", "resolve-source-memory", "GET", f"/v1/default/banks/{M}/memories/{sid}")
            hops.append({"status": st3, "type": m.get("type"), "document_id": m.get("document_id"),
                         "chunk_id": m.get("chunk_id"), "metadata": m.get("metadata")})
        out["provenance_two_hop"] = {"observation_document_id": full.get("document_id") if isinstance(full, dict) else None,
                                     "observation_fields": sorted(full.keys()) if isinstance(full, dict) else full,
                                     "source_hops": hops}
    return out


# --- new: observation scopes and what consolidation costs (question c) -------------------------

def s_scopes():
    if not afford(10, "observation_scopes"):
        return {"skipped": "LLM cap"}
    out = {}
    b0, _ = llm_count()
    retain_new("observation_scopes", "retain-one-scope", M, [item(
        "doc-scope-one", SCOPE_ONE, "2026-07-30T00:00:00Z", ["company:aurora", "form:10-Q"],
        observation_scopes=[["company:aurora"]])])
    b1, by1 = llm_count()
    consolidate_new("observation_scopes", M, "consolidate-one-scope")
    b2, by2 = llm_count()
    retain_new("observation_scopes", "retain-two-scopes", M, [item(
        "doc-scope-two", SCOPE_TWO, "2026-08-12T00:00:00Z", ["company:borealis", "theme:photonics", "form:8-K"],
        observation_scopes=[["company:borealis"], ["theme:photonics"]])])
    b3, _ = llm_count()
    consolidate_new("observation_scopes", M, "consolidate-two-scopes")
    b4, by4 = llm_count()
    st, scopes = new("observation_scopes", "list-scopes", "GET", f"/v1/default/banks/{M}/observations/scopes")
    facts_one = memories_of(M, document_id="doc-scope-one")
    facts_two = memories_of(M, document_id="doc-scope-two")
    obs = memories_of(M, type="observation")
    out.update({
        "llm": {"retain_one_scope": b1 - b0, "consolidate_one_scope": b2 - b1,
                "retain_two_scopes": b3 - b2, "consolidate_two_scopes": b4 - b3,
                "by_operation_after": by4[M]},
        "facts_one_scope": len(facts_one), "facts_two_scopes": len(facts_two),
        "fact_fields": sorted(facts_one[0].keys()) if facts_one else None,
        "fact_tags": [f.get("tags") for f in facts_one + facts_two],
        "scopes_status": st, "scopes": scopes,
        "observations": [{"tags": o.get("tags"), "text": (o.get("text") or "")[:160],
                          "sources": len(o.get("source_memory_ids") or [])} for o in obs],
    })
    return out


# --- new: entities as written ------------------------------------------------------------------

def s_entities():
    if not afford(2, "entities"):
        return {"skipped": "LLM cap"}
    b0, _ = llm_count()
    retain_new("entities", "retain-entities-unresolved", M, [item(
        "doc-entities", ENTITIES, "2026-09-02T00:00:00Z", ["company:aurora", "form:8-K"],
        entities=[{"text": "Aurora Optics Inc.", "type": "ORG"}, {"text": "Halcyon Networks", "type": "ORG"}],
        resolve_entities=False)])
    retain_llm = delta(b0)[0]
    st, ents = new("entities", "list-entities", "GET", f"/v1/default/banks/{M}/entities", query={"limit": 200})
    st2, mems = new("entities", "document-memories", "GET", f"/v1/default/banks/{M}/memories/list",
                    query={"document_id": "doc-entities", "limit": 100})
    names = [(e.get("canonical_name"), e.get("mention_count"), e.get("id")) for e in items_of(ents)]
    return {"retain_llm_requests": retain_llm, "entities_status": st, "entities": names,
            "memories_status": st2,
            "memories": [{"text": m.get("text"), "entities": m.get("entities"), "chunk_id": m.get("chunk_id")}
                         for m in items_of(mems)]}


def s_entity_memories():
    st, ents = helper("GET", f"/v1/default/banks/{M}/entities", query={"limit": 200})
    rows = items_of(ents)
    target = next((e for e in rows if e.get("canonical_name") == "Aurora Optics Inc."), None) or \
        next((e for e in rows if "aurora" in (e.get("canonical_name") or "").lower()), None)
    if not target:
        return {"no_entity": [e.get("canonical_name") for e in rows]}
    base = {"entity_id": target["id"], "tags": "company:aurora", "tags_match": "any_strict", "limit": 100}
    st1, all_rows = new("entity_memories", "by-entity-and-tag", "GET", f"/v1/default/banks/{M}/memories/list", query=base)
    st2, dated = new("entity_memories", "by-entity-tag-and-date", "GET", f"/v1/default/banks/{M}/memories/list",
                     query={**base, "time_field": "mentioned_at", "start_date": "2026-01-01T00:00:00Z",
                            "end_date": "2027-01-01T00:00:00Z"})
    st3, _ = new("entity_memories", "entity-detail", "GET", f"/v1/default/banks/{M}/entities/{target['id']}")
    def brief(resp):
        return [{"text": (m.get("text") or "")[:120], "type": m.get("fact_type") or m.get("type"),
                 "mentioned_at": m.get("mentioned_at"), "document_id": m.get("document_id")} for m in items_of(resp)]
    return {"entity": target, "by_entity_and_tag": {"status": st1, "rows": brief(all_rows)},
            "with_date_filter": {"status": st2, "rows": brief(dated)},
            "entity_detail_status": st3}


# --- new: recall options and scores ------------------------------------------------------------

def s_recall_options():
    def recall(name, **body):
        st, resp = new("recall_options", name, "POST", f"/v1/default/banks/{M}/memories/recall",
                       {"query": RECALL_QUERY, **body})
        rows = items_of(resp)
        return {"status": st, "results": len(rows),
                "types": [r.get("type") for r in rows],
                "ids": [r.get("id") for r in rows],
                "scores": [r.get("scores") for r in rows[:3]],
                "result_fields": sorted(rows[0].keys()) if rows else None,
                "top_keys": sorted(resp.keys()) if isinstance(resp, dict) else resp,
                "source_facts": len(resp.get("source_facts") or {}) if isinstance(resp, dict) else None,
                "chunks": len(resp.get("chunks") or {}) if isinstance(resp, dict) else None,
                "source_fact_ids": [r.get("source_fact_ids") for r in rows if r.get("type") == "observation"][:3]}
    return {
        "max_tokens_8192": recall("max-tokens-8192", max_tokens=8192),
        "max_tokens_128": recall("max-tokens-128", max_tokens=128),
        "types_world": recall("types-world", types=["world"]),
        "prefer_observations": recall("prefer-observations", types=["world", "observation"], prefer_observations=True),
        "no_prefer_observations": recall("no-prefer-observations", types=["world", "observation"], prefer_observations=False),
        "source_facts": recall("include-source-facts", include={"source_facts": {}}),
        "chunks": recall("include-chunks", include={"chunks": {}}),
        "query_timestamp_2024": recall("query-timestamp-2024", query_timestamp="2024-04-01T00:00:00Z"),
        "query_timestamp_none": recall("query-timestamp-none"),
        "pointer_recall": recall("pointer-recall", budget="high", max_tokens=8192, prefer_observations=True,
                                 query_timestamp="2026-09-30T00:00:00Z",
                                 include={"source_facts": {}, "chunks": {}},
                                 tags=["company:aurora"], tags_match="any_strict"),
    }


# --- new: chunks (question b), reprocess (question a), entity labels, dry-run ------------------

def s_chunks():
    if not afford(4, "chunks"):
        return {"skipped": "LLM cap"}
    b0, _ = llm_count()
    retain_new("chunks", "retain-chunked", L, [item(
        "doc-chunked", CHUNKED, "2026-08-01T00:00:00Z", ["company:aurora", "form:10-K"],
        context="Aurora Optics Inc. 10-K for fiscal 2026, Item 1A. Risk Factors. The filer is speaking.")])
    retain_llm = delta(b0)[0]
    st, chunks = new("chunks", "list-chunks", "GET", f"/v1/default/banks/{L}/documents/doc-chunked/chunks")
    rows = items_of(chunks) or (chunks.get("chunks") if isinstance(chunks, dict) else []) or []
    first = rows[0] if rows else {}
    cid = first.get("chunk_id") or first.get("id")
    st2, one = new("chunks", "get-chunk", "GET", f"/v1/default/chunks/{cid}") if cid else (None, None)
    st3, doc = new("chunks", "get-document", "GET", f"/v1/default/banks/{L}/documents/doc-chunked")
    facts = memories_of(L, document_id="doc-chunked")
    st4, rc = new("chunks", "recall-include-chunks", "POST", f"/v1/default/banks/{L}/memories/recall",
                  {"query": "Aurora substrate supplier and epitaxy concentration", "include": {"chunks": {}},
                   "max_tokens": 8192})
    verbatim = []
    cursor = 0
    for c in rows:
        text = c.get("chunk_text") or c.get("text") or ""
        at = CHUNKED.find(text)
        verbatim.append({"chunk_index": c.get("chunk_index"), "chars": len(text), "verbatim": at >= 0,
                         "offset": at, "end": at + len(text) if at >= 0 else None,
                         "after_previous": at >= cursor if at >= 0 else None,
                         "stripped_verbatim": CHUNKED.find(text.strip()) >= 0})
        if at >= 0:
            cursor = at + len(text)
    recall_chunks = rc.get("chunks") if isinstance(rc, dict) else None
    recall_chunk_verbatim = {k: CHUNKED.find(v.get("text") or "") >= 0 for k, v in (recall_chunks or {}).items()} \
        if isinstance(recall_chunks, dict) else recall_chunks
    return {"retain_llm_requests": retain_llm, "chunks_status": st, "chunk_count": len(rows),
            "chunk_fields": sorted(first.keys()), "verbatim": verbatim,
            "content_chars": len(CHUNKED),
            "get_chunk_status": st2, "get_chunk_fields": sorted(one.keys()) if isinstance(one, dict) else one,
            "document_status": st3,
            "document_original_text_is_content": (doc.get("original_text") == CHUNKED) if isinstance(doc, dict) else None,
            "document_fields": sorted(doc.keys()) if isinstance(doc, dict) else doc,
            "facts": [{"chunk_id": f.get("chunk_id"), "text": (f.get("text") or "")[:100],
                       "tags": f.get("tags")} for f in facts],
            "recall_status": st4, "recall_chunks_verbatim": recall_chunk_verbatim}


def s_reprocess():
    """Question (a): does a stored document take new labels, context, entities or scopes?"""
    if not afford(9, "reprocess"):
        return {"skipped": "LLM cap"}
    out = {}
    before_facts = memories_of(L, document_id="doc-chunked")
    # Labels arrive in the bank config after the document was retained.
    st, cfg = new("entity_labels", "config-layer-labels", "PATCH", f"/v1/default/banks/{L}/config",
                  {"updates": {"entity_labels": LAYER_LABELS}})
    out["labels_config_status"] = st
    out["labels_config_applied"] = bool(isinstance(cfg, dict) and (cfg.get("config") or {}).get("entity_labels"))
    b0, _ = llm_count()
    st, resp = new("reprocess", "reprocess-document", "POST", f"/v1/default/banks/{L}/documents/doc-chunked/reprocess")
    op = wait_new("reprocess", L, resp["operation_id"], "reprocess-document") if isinstance(resp, dict) and resp.get("operation_id") else None
    out["reprocess"] = {"status": st, "response": resp, "final": (op or {}).get("status"), "llm_requests": delta(b0)[0]}
    st2, mems = new("reprocess", "memories-after-reprocess", "GET", f"/v1/default/banks/{L}/memories/list",
                    query={"document_id": "doc-chunked", "limit": 100})
    after = items_of(mems)
    out["before"] = [{"id": f.get("id"), "tags": f.get("tags"), "context": f.get("context")} for f in before_facts]
    out["after_reprocess"] = [{"id": f.get("id"), "tags": f.get("tags"), "context": f.get("context"),
                               "entities": f.get("entities")} for f in after]
    # Retained again under the same document ID, same content, with a new context, entities,
    # tags and explicit scopes.
    b1, _ = llm_count()
    retain_new("reprocess", "retain-again-same-id", L, [item(
        "doc-chunked", CHUNKED, "2026-08-01T00:00:00Z", ["company:aurora", "form:10-K", "theme:photonics"],
        context="Aurora Optics Inc. annual report (10-K), fiscal 2026, Item 1A. Risk Factors. The filer, "
                "Aurora Optics Inc., is speaking.",
        entities=[{"text": "Aurora Optics Inc.", "type": "ORG"}, {"text": "Cirrus Semiconductor", "type": "ORG"},
                  {"text": "Halcyon Networks", "type": "ORG"}],
        resolve_entities=False, observation_scopes=[["company:aurora"], ["theme:photonics"]])])
    out["retain_again_llm_requests"] = delta(b1)[0]
    st3, mems2 = new("reprocess", "memories-after-retain-again", "GET", f"/v1/default/banks/{L}/memories/list",
                     query={"document_id": "doc-chunked", "limit": 100})
    out["after_retain_again"] = [{"id": f.get("id"), "tags": f.get("tags"), "context": f.get("context"),
                                  "entities": f.get("entities")} for f in items_of(mems2)]
    b2, _ = llm_count()
    consolidate_new("reprocess", L, "consolidate")
    out["consolidate_llm_requests"] = delta(b2)[0]
    st4, scopes = new("reprocess", "list-scopes", "GET", f"/v1/default/banks/{L}/observations/scopes")
    out["scopes"] = scopes
    return out


def s_entity_labels():
    if not afford(2, "entity_labels"):
        return {"skipped": "LLM cap"}
    b0, _ = llm_count()
    retain_new("entity_labels", "retain-labelled", L, [item(
        "doc-labelled", LABELLED, "2026-09-10T00:00:00Z", ["company:borealis", "form:8-K"])])
    retain_llm = delta(b0)[0]
    st, mems = new("entity_labels", "document-memories", "GET", f"/v1/default/banks/{L}/memories/list",
                   query={"document_id": "doc-labelled", "limit": 100})
    facts = items_of(mems)
    label_tags = sorted({t for f in facts for t in (f.get("tags") or []) if t.startswith("layer:")})
    tag = label_tags[0] if label_tags else "layer:chip-laser"
    st2, rc = new("entity_labels", "recall-by-label-tag", "POST", f"/v1/default/banks/{L}/memories/recall",
                  {"query": "lead times and supply of lasers and modules", "tags": [tag], "tags_match": "any_strict"})
    st3, ents = new("entity_labels", "list-entities", "GET", f"/v1/default/banks/{L}/entities", query={"limit": 200})
    return {"retain_llm_requests": retain_llm, "facts": [{"text": f.get("text"), "tags": f.get("tags"),
                                                          "entities": f.get("entities")} for f in facts],
            "label_tags": label_tags, "recall_tag": tag, "recall_status": st2,
            "recall": [{"text": (r.get("text") or "")[:120], "tags": r.get("tags")} for r in items_of(rc)],
            "entities": [e.get("canonical_name") for e in items_of(ents)]}


def s_dry_run():
    if not afford(2, "dry_run_extract"):
        return {"skipped": "LLM cap"}
    b0, _ = llm_count()
    st, resp = new("dry_run_extract", "dry-run-extract", "POST", f"/v1/default/banks/{L}/memories/dry-run-extract",
                   {"content": DRY_RUN, "context": "Cirrus Semiconductor 8-K, September 2026. The filer is speaking.",
                    "timestamp": "2026-09-15T00:00:00Z"})
    stored = memories_of(L, q="Fremont")
    return {"status": st, "llm_requests": delta(b0)[0],
            "keys": sorted(resp.keys()) if isinstance(resp, dict) else resp,
            "facts": resp.get("facts") if isinstance(resp, dict) else None,
            "chunks": len(resp.get("chunks") or []) if isinstance(resp, dict) else None,
            "stored_after": len(stored)}


# --- new: a tagged mental model, reflect's budget and exclude_mental_models --------------------

def s_tagged_mental_model():
    if not afford(6, "tagged_mental_model"):
        return {"skipped": "LLM cap"}
    b0, _ = llm_count()
    st, resp = new("tagged_mental_model", "create", "POST", f"/v1/default/banks/{M}/mental-models", {
        "id": "aurora-status", "name": "Aurora status", "tags": ["company:aurora"],
        "source_query": "What constrains Aurora Optics' laser capacity, and who are its key suppliers and customers?",
        "max_tokens": 1024,
        "trigger": {"refresh_after_consolidation": False, "min_refresh_interval_seconds": 3600,
                    "budget": "low", "exclude_mental_models": True, "keep_trace": True},
    })
    op = wait_new("tagged_mental_model", M, resp["operation_id"], "create") if isinstance(resp, dict) and resp.get("operation_id") else None
    st2, mm = new("tagged_mental_model", "get", "GET", f"/v1/default/banks/{M}/mental-models/aurora-status")
    return {"create_status": st, "create_response": resp if st not in (200, 201) else None,
            "create_final": (op or {}).get("status"), "llm_requests": delta(b0)[0], "get_status": st2,
            "fields": sorted(mm.keys()) if isinstance(mm, dict) else mm,
            "tags": mm.get("tags") if isinstance(mm, dict) else None,
            "trigger": mm.get("trigger") if isinstance(mm, dict) else None,
            "content_chars": len(mm.get("content") or "") if isinstance(mm, dict) else None}


def s_reflect_options():
    out = {}
    for name, body, est in [
        ("budget-mid-tag-scoped", {"budget": "mid"}, 11),
        ("exclude-mental-models", {"budget": "low", "exclude_mental_models": True}, 6),
    ]:
        if not afford(est, f"reflect {name}"):
            out[name] = {"skipped": "LLM cap"}
            continue
        b0, _ = llm_count()
        st, resp = new("reflect_options", name, "POST", f"/v1/default/banks/{M}/reflect", {
            "query": "Is Aurora Optics capacity constrained? Cite evidence.",
            "tags": ["company:aurora"], "tags_match": "any_strict", "include": {"facts": {}}, **body})
        based = resp.get("based_on") or {} if isinstance(resp, dict) else {}
        out[name] = {"status": st, "llm_requests": delta(b0)[0],
                     "based_on_keys": sorted(based.keys()) if isinstance(based, dict) else based,
                     "mental_models_cited": based.get("mental_models") or based.get("mental-models")
                     if isinstance(based, dict) else None,
                     "memories_cited": len(based.get("memories") or []) if isinstance(based, dict) else None,
                     "cited_fields": sorted((based.get("memories") or [{}])[0].keys())
                     if isinstance(based, dict) and based.get("memories") else None,
                     "usage": resp.get("usage") if isinstance(resp, dict) else None,
                     "response": resp if st != 200 else None}
    return out


def s_rerun_mental_model():
    """The 0.10.1 row's manual refresh and history, on the tagged model (a second model's
    create and refresh would cost two more reflect runs)."""
    if not afford(6, "rerun mental-model refresh"):
        return {"skipped": "LLM cap"}
    fc.REC = RERUN
    b0, _ = llm_count()
    st, r, _ = fc.rec("mental_models", "refresh", "POST", f"/v1/default/banks/{M}/mental-models/aurora-status/refresh", {})
    op = fc.wait_op("mental_models", M, r["operation_id"], "refresh") if isinstance(r, dict) and r.get("operation_id") else None
    st2, mm, _ = fc.rec("mental_models", "get", "GET", f"/v1/default/banks/{M}/mental-models/aurora-status")
    st3, hist, _ = fc.rec("mental_models", "history", "GET", f"/v1/default/banks/{M}/mental-models/aurora-status/history")
    return {"refresh_status": st, "refresh_final": (op or {}).get("status"), "llm_requests": delta(b0)[0],
            "get_status": st2, "content_chars": len(mm.get("content") or "") if isinstance(mm, dict) else None,
            "history_status": st3,
            # the history is a bare list: the 2026-10-02 run expected a dict here and failed after
            # recording it, so its evidence was read from rerun-0.10.2/mental_models/
            "history_entries": len(hist) if isinstance(hist, list) else hist,
            "history_fields": sorted(hist[0].keys()) if isinstance(hist, list) and hist else None}


def s_rerun_reflect():
    """feature_check.s_reflect's three requests, each only if the cap allows."""
    out = {}
    path = f"/v1/default/banks/{M}/reflect"
    schema = {"type": "object", "properties": {
        "constrained": {"type": "boolean"}, "evidence": {"type": "array", "items": {"type": "string"}}},
        "required": ["constrained", "evidence"]}
    union = {"type": "object", "properties": {"n": {"type": ["number", "null"]}}, "required": ["n"]}
    for name, body in [
        ("provenance", {"query": "Is Aurora Optics capacity constrained? Cite evidence.", "include": {"facts": {}}}),
        ("structured-union-type", {"query": "How many wafers per year?", "response_schema": union}),
        ("structured", {"query": "Is Aurora Optics capacity constrained?", "response_schema": schema}),
    ]:
        if not afford(6, f"rerun reflect {name}"):
            out[name] = {"skipped": "LLM cap"}
            continue
        fc.REC = RERUN
        b0, _ = llm_count()
        st, resp, _ = fc.rec("reflect", name, "POST", path, body)
        based = resp.get("based_on") or {} if isinstance(resp, dict) else {}
        facts = (based.get("memories") or []) if isinstance(based, dict) else []
        out[name] = {"status": st, "llm_requests": delta(b0)[0],
                     "based_on_keys": sorted(based.keys()) if isinstance(based, dict) else based,
                     "cited": len(facts), "cited_fact_fields": sorted(facts[0].keys()) if facts else None,
                     "cited_types": sorted({f.get("type") for f in facts}),
                     "structured_output": resp.get("structured_output") if isinstance(resp, dict) else None,
                     "structured_output_error": resp.get("structured_output_error") if isinstance(resp, dict) else None,
                     "error": resp if st != 200 else None}
    return out


def s_llm_stats():
    out = {}
    for i, bank in enumerate(BANKS, 1):
        st, stats = new("llm_requests_0102", f"stats-{['main', 'labels', 'import', 'template'][i - 1]}", "GET",
                        f"/v1/default/banks/{bank}/llm-requests/stats", query={"period": "1d"})
        out[bank] = stats.get("buckets") if isinstance(stats, dict) else stats
    return out


def s_delete():
    fc.REC = RERUN
    out = {}
    for bank in BANKS:
        st, resp, _ = fc.rec("bank_delete", "delete-bank", "DELETE", f"/v1/default/banks/{bank}")
        out[bank] = {"status": st, "response": resp}
    st, resp, _ = fc.rec("bank_delete", "get-deleted-bank-config", "GET", f"/v1/default/banks/{M}/config")
    out["after"] = {"status": st}
    return out


if __name__ == "__main__":
    RERUN.mkdir(exist_ok=True)
    plan = [
        ("version", s_version),
        ("rerun.bank_config", s_rerun_config),
        ("labels_bank", s_labels_bank),
        ("rerun.retain_modes", rerun(fc.s_retain_modes, 6, "rerun retain modes")),
        ("rerun.upsert", rerun(fc.s_upsert, 6, "rerun upsert")),
        ("rerun.free", s_rerun_free),
        ("rerun.observations", rerun(fc.s_observations, 8, "rerun consolidation")),
        ("rerun.followup", s_rerun_followup),
        ("observation_scopes", s_scopes),
        ("entities", s_entities),
        ("entity_memories", s_entity_memories),
        ("recall_options", s_recall_options),
        ("chunks", s_chunks),
        ("reprocess", s_reprocess),
        ("entity_labels", s_entity_labels),
        ("dry_run_extract", s_dry_run),
        ("rerun.bank_templates", rerun(fc.s_templates, 0, "rerun bank templates")),
        ("rerun.export_import", rerun(fc.s_export_import, 2, "rerun export/import")),
        ("tagged_mental_model", s_tagged_mental_model),
        ("reflect_options", s_reflect_options),
        ("rerun.reflect", s_rerun_reflect),
        ("rerun.mental_models", s_rerun_mental_model),
        ("rerun.knowledge_pages", rerun(fc.s_knowledge_pages, 11, "rerun knowledge pages")),
    ]
    for name, fn in plan:
        step(name, fn)
        if name in ("rerun.bank_config", "labels_bank") and "exception" in json.dumps(evidence[name], default=str):
            break
    time.sleep(5)  # let any trailing background call land in the log
    total, by_bank = llm_count()
    evidence["llm_requests_total"] = total
    evidence["llm_requests_by_bank"] = by_bank
    evidence["skipped"] = skipped
    step("llm_requests_0102", s_llm_stats)
    step("delete", s_delete)
    out = HERE / "results" / "feature-check-0.10.2.json"
    out.write_text(json.dumps({"banks": BANKS, "cap": CAP, "evidence": evidence}, indent=2, default=str))
    print("->", out, "LLM requests:", total)
