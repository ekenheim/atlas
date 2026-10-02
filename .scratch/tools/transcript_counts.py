"""Count the TradingView transcripts per company: in the catalog, in the ledger, parsed, and in
Memory (pilot-review ticket 17). Read-only against production; prints a Markdown table."""

import collections
import json
import urllib.request

BASE = "https://atlas.ekenhome.se/api/v1"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=90) as response:
        return json.load(response)


def items(answer):
    return answer["items"] if isinstance(answer, dict) and "items" in answer else answer


def pages(path):
    found, offset = [], 0
    while True:
        page = items(get(f"{path}{'&' if '?' in path else '?'}limit=100&offset={offset}"))
        found += page
        if len(page) < 100:
            return found
        offset += 100


def main():
    companies = [c for c in items(get("/companies")) if c.get("role") != "counterparty"]
    print("| Company | Catalog transcripts | In the ledger | Parsed | Sections completed | cancelled or failed | pending | zero-fact | Facts |")
    print("|---|---|---|---|---|---|---|---|---|")
    totals = collections.Counter()
    for company in sorted(companies, key=lambda c: c["display_name"]):
        catalog = pages(f"/tradingview/catalog?company_id={company['id']}")
        in_catalog = sum(1 for row in catalog if "transcript" in (row.get("category") or "").lower())
        documents = [d for d in pages(f"/companies/{company['id']}/sources") if d.get("provider") == "tradingview"]
        parsed, states, facts = 0, collections.Counter(), 0
        for document in documents:
            versions = items(get(f"/sources/{document['id']}/versions?limit=1"))
            if not versions:
                continue
            version = versions[0]
            if version.get("parse_status") == "parsed":
                parsed += 1
            memory = get(f"/source-versions/{version['id']}/memory")
            for section in memory["documents"]:
                states[section["retain_state"]] += 1
                facts += section.get("fact_count") or 0
        row = (in_catalog, len(documents), parsed, states["completed"], states["failed"] + states.get("cancelled", 0), states["pending"], states["zero_fact"], facts)
        for index, value in enumerate(row):
            totals[index] += value
        print(f"| {company['display_name']} | " + " | ".join(str(v) for v in row) + " |", flush=True)
    print("| **All** | " + " | ".join(str(totals[i]) for i in range(8)) + " |")


if __name__ == "__main__":
    main()
