"""Record Atlas's research bank template and the monitoring routes against the local spike.

Build ticket 12. Uses the same recording format as feature_check.py, and makes no LLM calls:
a template with missions, dispositions and directives but no mental models queues no work,
and /health and /version are read-only. The template is imported into a fresh, timestamped
bank, never into Atlas's research bank.

    uv run python spikes/hindsight/record_bank_template.py

Re-run it whenever configs/hindsight/bank-template.json changes, then update the recording
names in tests/unit/test_hindsight_contract.py and the bank ID the tests use.
"""

import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = "http://127.0.0.1:8888"
HERE = pathlib.Path(__file__).parent
REC = HERE / "recordings"
TEMPLATE = HERE.parents[1] / "configs" / "hindsight" / "bank-template.json"
BANK = f"atlas-template-{int(time.time())}"


def rec(feature: str, name: str, method: str, path: str, body=None, query=None):
    url = ROOT + path + ("?" + urllib.parse.urlencode(query) if query else "")
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    request = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            status, payload = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, payload = error.code, error.read()
    seconds = round(time.time() - started, 2)
    parsed = json.loads(payload)
    if not feature.startswith("_"):  # helper reads aren't recorded
        out = REC / feature / f"{name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "request": {"method": method, "path": path, "query": query, "body": body},
            "response": {"status": status, "seconds": seconds, "body": parsed},
        }
        out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"{status} {method} {path} {query or ''}")
    return status, parsed


def main() -> None:
    manifest = json.loads(TEMPLATE.read_text(encoding="utf-8"))["manifest"]
    bank_path = f"/v1/default/banks/{BANK}"
    rec("monitoring", "01-health", "GET", "/health")
    rec("monitoring", "02-version", "GET", "/version")
    rec(
        "research_template",
        "01-import-dry-run",
        "POST",
        f"{bank_path}/import",
        manifest,
        {"dry_run": "true"},
    )
    rec("research_template", "02-import", "POST", f"{bank_path}/import", manifest)
    rec("research_template", "03-imported-config", "GET", f"{bank_path}/config")
    # Evidence only (not recorded): the directives landed, and no LLM call was made.
    print(json.dumps(rec("_", "directives", "GET", f"{bank_path}/directives")[1], indent=1))
    print(json.dumps(rec("_", "stats", "GET", f"{bank_path}/llm-requests/stats")[1], indent=1))
    print(f"bank: {BANK}")


if __name__ == "__main__":
    main()
