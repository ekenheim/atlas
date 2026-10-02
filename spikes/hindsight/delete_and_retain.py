"""Delete-then-retain on the local Hindsight 0.10.2 (memory-quality ticket 12).

One synthetic document (fictional companies): retained, consolidated, its document deleted
(`DELETE /documents/{id}`), retained again under the same ID with a new context, new tags and given
entities. Records each request and response under `recordings/delete_and_retain/`, and the facts,
the observations and the document before and after. LLM requests are capped (CAP, 8), counted from
the bank's own request log before each step that spends any. The bank is deleted at the end.

Usage: python spikes/hindsight/delete_and_retain.py
"""

import json
import time

import feature_check as fc

CAP = 8
BANK = f"atlas-q12-{fc.TS}"
FEATURE = "delete_and_retain"
DOC = "doc-delete-retain"
TEXT = (
    "Aurora Optics Inc. said its Tucson indium phosphide fab ran at full utilization in fiscal 2026. "
    "Halcyon Networks accounted for 38% of Aurora's revenue and will take most of its 3.2T laser "
    "output in fiscal 2027, which Aurora called its binding capacity constraint."
)
OLD_CTX = "Synthetic document (fictional companies). Old context."
NEW_CTX = (
    "Aurora Optics Inc. annual report (10-K), fiscal 2026, Item 1. Business. The filer, Aurora Optics "
    "Inc., is speaking."
)
out: dict = {}


def llm_total():
    rows, offset = [], 0
    while True:
        st, resp, _ = fc.rec(
            "_h",
            "x",
            "GET",
            f"/v1/default/banks/{BANK}/llm-requests",
            query={"limit": 500, "offset": offset},
        )
        if st != 200 or not isinstance(resp, dict):
            return len(rows), rows
        items = resp.get("items") or resp.get("requests") or []
        rows += items
        if len(items) < 500:
            return len(rows), rows
        offset += 500


def r(name, method, path, body=None, query=None):
    st, resp, _ = fc.rec(FEATURE, name, method, f"/v1/default/banks/{BANK}{path}", body, query)
    return st, resp


def wait(op_resp, name):
    if isinstance(op_resp, dict) and op_resp.get("operation_id"):
        return fc.wait_op(FEATURE, BANK, op_resp["operation_id"], name)
    return None


def state(label):
    _, mem = r(f"{label}-memories", "GET", "/memories/list", query={"limit": 200})
    # `GET .../observations` is 405 (recorded as evidence); the observations are the memory
    # list's `fact_type: observation` rows, in `facts`.
    _, obs = r(f"{label}-observations", "GET", "/observations", query={"limit": 200})
    st, doc = r(f"{label}-document", "GET", f"/documents/{DOC}")
    _, ents = r(f"{label}-entities", "GET", "/entities", query={"limit": 200})
    items = (mem or {}).get("items", []) if isinstance(mem, dict) else []
    oitems = (
        (obs or {}).get("items") or (obs or {}).get("observations") or []
        if isinstance(obs, dict)
        else []
    )
    return {
        "document_status": st,
        "facts": [
            {
                "id": f.get("id"),
                "type": f.get("fact_type"),
                "context": f.get("context"),
                "tags": f.get("tags"),
                "entities": f.get("entities"),
                "text": (f.get("text") or "")[:90],
            }
            for f in items
        ],
        "observations": [
            {
                "id": o.get("id"),
                "text": (o.get("text") or "")[:90],
                "proof_count": o.get("proof_count"),
                "source_memory_ids": o.get("source_memory_ids"),
                "tags": o.get("tags"),
            }
            for o in oitems
        ],
        "entity_names": [
            e.get("canonical_name") or e.get("name")
            for e in ((ents or {}).get("items", []) if isinstance(ents, dict) else [])
        ],
    }


def item(ctx, **extra):
    return {
        "content": TEXT,
        "document_id": DOC,
        "timestamp": "2026-08-01T00:00:00Z",
        "context": ctx,
        "metadata": {"fixture": "delete-and-retain"},
        **extra,
    }


try:
    fc.rec("_h", "x", "PUT", f"/v1/default/banks/{BANK}", {"name": BANK})
    n0 = llm_total()[0]
    _, resp = r(
        "retain-first",
        "POST",
        "/memories",
        {"items": [item(OLD_CTX, tags=["company:aurora"])], "async": True},
    )
    wait(resp, "retain-first")
    n1 = llm_total()[0]
    out["llm_after_retain_1"] = n1 - n0
    st, resp = r("consolidate-first", "POST", "/consolidate", {})
    wait(resp, "consolidate-first")
    n2 = llm_total()[0]
    out["llm_after_consolidate_1"] = n2 - n1
    out["before"] = state("before")
    if n2 > CAP - 3:
        out["stopped"] = (
            f"{n2} requests spent; the second retain and consolidation need up to 3 more"
        )
    else:
        st, resp = r("delete-document", "DELETE", f"/documents/{DOC}")
        out["delete"] = {"status": st, "response": resp}
        time.sleep(2)
        out["after_delete"] = state("after-delete")
        n3 = llm_total()[0]
        _, resp = r(
            "retain-second",
            "POST",
            "/memories",
            {
                "items": [
                    item(
                        NEW_CTX,
                        tags=["company:aurora", "form:10-K"],
                        entities=[
                            {"text": "Aurora Optics Inc.", "type": "ORG"},
                            {"text": "Halcyon Networks", "type": "ORG"},
                        ],
                        resolve_entities=False,
                    )
                ],
                "async": True,
            },
        )
        wait(resp, "retain-second")
        n4 = llm_total()[0]
        out["llm_after_retain_2"] = n4 - n3
        out["after_retain"] = state("after-retain")
        if n4 + 2 <= CAP:
            st, resp = r("consolidate-second", "POST", "/consolidate", {})
            wait(resp, "consolidate-second")
            out["llm_after_consolidate_2"] = llm_total()[0] - n4
            out["after_consolidate"] = state("after-consolidate")
        else:
            out["consolidate_second"] = "skipped: cap"
    total, rows = llm_total()
    out["llm_total"] = total
    (fc.REC / FEATURE).mkdir(parents=True, exist_ok=True)
    (fc.HERE / "results" / "delete-and-retain-llm-requests.json").write_text(
        json.dumps(
            [
                {
                    "operation": x.get("operation"),
                    "scope": x.get("scope"),
                    "status": x.get("status"),
                }
                for x in rows
            ],
            indent=2,
        )
    )
finally:
    fc.rec("_h", "x", "DELETE", f"/v1/default/banks/{BANK}")
    (fc.HERE / "results").mkdir(exist_ok=True)
    (fc.HERE / "results" / "delete-and-retain.json").write_text(
        json.dumps(out, indent=2, default=str)
    )
    print(json.dumps(out, indent=2, default=str)[:7000])
