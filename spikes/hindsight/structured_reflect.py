"""Probe reflect with a JSON Schema on an existing bank (ticket 04).

Usage: python3 spikes/hindsight/structured_reflect.py <bank_id> <label>
Appends the result to spikes/hindsight/results/<label>.json under "structured_reflect".
Hindsight returns HTTP 200 even when structured output fails, so the check
reads `structured_output_error` and validates the shape itself.
"""

import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

SCHEMA = {
    "type": "object",
    "properties": {
        "constraints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "constraint": {"type": "string"},
                    "evidence_quote": {"type": "string"},
                    "explicit_in_source": {"type": "boolean"},
                },
                "required": ["constraint", "evidence_quote", "explicit_in_source"],
            },
        },
        # Hindsight 0.10.1 returns 500 on union types ("type": [..., "null"]):
        # TypeError: unhashable type: 'list' in request validation.
        "q4_fy26_components_revenue_known": {"type": "boolean"},
        "q4_fy26_components_revenue_musd": {"type": "number"},
        "missing_information": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["constraints", "q4_fy26_components_revenue_known", "missing_information"],
}


def main(bank, label):
    body = {
        "query": "List Lumentum's documented supply or capacity constraints with a verbatim evidence "
                 "quote each, give Q4 FY2026 Components revenue in USD millions if known, "
                 "and list missing information.",
        "response_schema": SCHEMA,
        "include": {"facts": {}},
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:8888/v1/default/banks/{bank}/reflect",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            status, raw = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read().decode()
    out = {"status": status, "seconds": round(time.time() - t, 1)}
    try:
        d = json.loads(raw)
        so = d.get("structured_output")
        out.update(structured_output=so, structured_output_error=d.get("structured_output_error"),
                   shape_ok=isinstance(so, dict) and all(k in so for k in SCHEMA["required"]))
    except json.JSONDecodeError:
        out["raw"] = raw[:1500]
    path = pathlib.Path(__file__).parent / "results" / f"{label}.json"
    result = json.loads(path.read_text())
    result["structured_reflect"] = out
    path.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "structured_output"})[:800])
    print(json.dumps(out.get("structured_output"))[:1500])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
