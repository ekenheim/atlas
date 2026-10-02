"""Old against new bank-template missions, by `dry-run-extract` (memory-quality ticket 05).

Three recorded sections from `tests/fixtures/` (a 10-K Item, an 8-K exhibit, a transcript
part), each parsed and sectioned by Atlas's own code, are extracted twice on the local spike
Hindsight (`compose.yaml`): once with the old template's `retain_mission` and no entity labels
(template 1.1.0, read from git), once with the new template's `retain_mission` and its `layer`
label group (the working tree's `configs/hindsight/bank-template.json`). `dry-run-extract`
takes both as per-call overrides and stores nothing, so one throwaway bank serves both.

Per section and template: the facts, their entities, the `layer:` labels among them, the
chunks and the token usage. The observations mission can't be compared this way: it acts at
consolidation, which `dry-run-extract` doesn't run.

LLM requests are capped (`CAP`, default 12): one per chunk, and each excerpt is cut to fit one
chunk (`retain_chunk_size` is sent as `CHUNK`), so the run needs 6. Before each call the
requests already spent (the `chunks` of the answers so far) plus the chunks the call needs
must fit the cap, or the call is skipped and the skip recorded. The bank's own LLM request
log is read at the end as a cross-check. The bank is deleted at the end.

Usage (from the repo root, the spike running on 127.0.0.1:8888):
    uv run python spikes/hindsight/mission_compare_05.py --show    # the excerpts; no request
    uv run python spikes/hindsight/mission_compare_05.py           # the live comparison
Writes spikes/hindsight/results/mission-compare-05.json and prints a Markdown summary.
"""

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(HERE))

import feature_check as fc  # noqa: E402  (the spike's HTTP helper; stdlib only)

from atlas.parsing import (  # noqa: E402
    TRADINGVIEW_TRANSCRIPT_MEDIA_TYPE,
    ParsedText,
    parse,
)
from atlas.retention.sections import split_sections  # noqa: E402

CAP = int(os.environ.get("SPIKE_LLM_CAP", "12"))
CHUNK = 3000  # retain_chunk_size sent with every call; every excerpt fits in one chunk
MAX_EXCERPT = 2800
OLD_REF = "5827cc0"  # template 1.1.0 (the commit memory-quality ticket 05 was built on)
TEMPLATE = "configs/hindsight/bank-template.json"
BANK = f"atlas-q05-missions-{fc.TS}"
EDGAR = REPO / "tests" / "fixtures" / "edgar" / "lumentum" / "www.sec.gov" / "Archives" / "edgar"
EDGAR = EDGAR / "data" / "1633978"
SECTIONS: list[dict[str, Any]] = [
    {
        "name": "10-K Item",
        "file": EDGAR / "000162828026057358" / "lite-20260627.htm",
        "media_type": "text/html",
        "form": "10-K",
        "primary": True,
        "anchor": "part-i-item-1a",
        # a risk factor that names suppliers, beside generic risk language
        "start_at": "We depend on a limited number of suppliers for raw materials",
        "context": "Lumentum Holdings Inc. annual report (10-K) for fiscal 2026: Item 1A. Risk Factors",
        "timestamp": "2026-08-18T00:00:00Z",
    },
    {
        "name": "8-K exhibit",
        "file": EDGAR / "000162828026055726" / "lite_ex991xq4fy26.htm",
        "media_type": "text/html",
        "form": "EX-99.1",
        "primary": False,
        "anchor": None,  # the chunk holding `start_at`
        # the company description, then the forward-looking-statements disclaimer
        "start_at": "About Lumentum",
        "context": "Lumentum Holdings Inc. 8-K exhibit 99.1, press release on fourth-quarter fiscal 2026 results",
        "timestamp": "2026-08-11T20:24:11Z",
    },
    {
        "name": "transcript part",
        "file": REPO / "tests" / "fixtures" / "tradingview" / "view-syn-view-1001-t.json",
        "media_type": TRADINGVIEW_TRANSCRIPT_MEDIA_TYPE,
        "form": None,
        "primary": False,
        "anchor": "chunk-001",
        "start_at": None,
        "context": "Earnings call transcript (synthetic Atlas test fixture): the company's executives and analysts",
        "timestamp": "2026-08-11T21:00:00Z",
    },
]


def excerpt(spec: dict[str, Any]) -> dict[str, Any]:
    parsed = parse(Path(spec["file"]).read_bytes(), spec["media_type"])
    if not isinstance(parsed, ParsedText):
        raise SystemExit(f"{spec['file']}: not parsed ({parsed!r})")
    text = parsed.text
    sections = split_sections(text, form=spec["form"], primary=spec["primary"])
    if spec["anchor"] is not None:
        found = [s for s in sections if s.anchor == spec["anchor"]]
    else:
        at = text.find(spec["start_at"])
        found = [s for s in sections if s.start <= at < s.end]
    if len(found) != 1:
        anchors = [(s.anchor, s.end - s.start) for s in sections]
        raise SystemExit(f"{spec['name']}: no section {spec['anchor'] or spec['start_at']!r} in {anchors}")
    [section] = found
    body = text[section.start : section.end]
    start = body.find(spec["start_at"]) if spec["start_at"] else 0
    window = body[max(start, 0) :]
    if len(window) > MAX_EXCERPT:
        cut = window.rfind("\n", 0, MAX_EXCERPT)
        window = window[: cut if cut > MAX_EXCERPT // 2 else MAX_EXCERPT]
    return {
        "name": spec["name"],
        "file": str(Path(spec["file"]).relative_to(REPO)),
        "anchor": section.anchor,
        "section_chars": section.end - section.start,
        "excerpt_offset": section.start + max(start, 0),
        "excerpt_chars": len(window),
        "content": window,
        "context": spec["context"],
        "timestamp": spec["timestamp"],
    }


def template_bank(ref: str | None) -> dict[str, Any]:
    if ref is None:
        raw = (REPO / TEMPLATE).read_text(encoding="utf-8")
    else:
        raw = subprocess.run(
            ["git", "show", f"{ref}:{TEMPLATE}"], cwd=REPO, check=True, capture_output=True, text=True
        ).stdout
    template = json.loads(raw)
    return {"version": template["template_version"], **template["manifest"]["bank"]}


def overrides(bank: dict[str, Any]) -> dict[str, Any]:
    """The prompt-affecting fields `dry-run-extract` takes per call (the rest is the bank's)."""
    return {
        "retain_mission": bank["retain_mission"],
        "entity_labels": bank.get("entity_labels"),
        "retain_chunk_size": CHUNK,
    }


def summary(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {"error": response}
    facts = response.get("facts") or []
    return {
        "facts": [
            {
                "text": f.get("text"),
                "fact_type": f.get("fact_type"),
                "entities": f.get("entities"),
                "layer_labels": [e for e in f.get("entities") or [] if str(e).startswith("layer:")],
            }
            for f in facts
        ],
        "fact_count": len(facts),
        "chunks": len(response.get("chunks") or []),
        "usage": response.get("usage"),
    }


def run(excerpts: list[dict[str, Any]]) -> dict[str, Any]:
    old, new = template_bank(OLD_REF), template_bank(None)
    status, created, _ = fc.rec("_helper", "x", "PUT", f"/v1/default/banks/{BANK}", {})
    if status not in (200, 201):
        raise SystemExit(f"could not create {BANK}: {status} {created}")
    spent, skipped, results = 0, [], []
    try:
        for item in excerpts:
            needed = math.ceil(len(item["content"]) / CHUNK)
            row: dict[str, Any] = {k: v for k, v in item.items() if k != "content"}
            for label, bank in (("old", old), ("new", new)):
                if spent + needed > CAP:
                    skipped.append({"section": item["name"], "template": label, "spent": spent})
                    row[label] = {"skipped": "LLM cap"}
                    continue
                body = {
                    "content": item["content"],
                    "context": item["context"],
                    "timestamp": item["timestamp"],
                    **overrides(bank),
                }
                status, response, _ = fc.rec(
                    "_helper", "x", "POST", f"/v1/default/banks/{BANK}/memories/dry-run-extract", body
                )
                row[label] = {"status": status, "template_version": bank["version"], **summary(response)}
                spent += row[label].get("chunks") or needed
                print(f"   {item['name']} / {label}: {row[label].get('fact_count')} facts", flush=True)
            results.append(row)
        time.sleep(3)
        _, log, _ = fc.rec("_helper", "x", "GET", f"/v1/default/banks/{BANK}/llm-requests", query={"limit": 500})
        logged = len((log.get("items") or log.get("requests") or [])) if isinstance(log, dict) else None
    finally:
        deleted, _, _ = fc.rec("_helper", "x", "DELETE", f"/v1/default/banks/{BANK}")
    return {
        "bank": BANK,
        "cap": CAP,
        "llm_requests_counted": spent,
        "llm_requests_logged": logged,
        "skipped": skipped,
        "bank_deleted_status": deleted,
        "old_template": old["version"],
        "new_template": new["version"],
        "sections": results,
    }


def markdown(out: dict[str, Any]) -> str:
    lines = [
        f"Templates {out['old_template']} (old) and {out['new_template']} (new); "
        f"{out['llm_requests_counted']} LLM requests counted, {out['llm_requests_logged']} logged.",
        "",
        "| Section | Old facts | New facts | New facts with a layer label | Layer labels |",
        "|---|---|---|---|---|",
    ]
    for row in out["sections"]:
        old, new = row.get("old", {}), row.get("new", {})
        new_facts = new.get("facts") or []
        labelled = sum(1 for f in new_facts if f["layer_labels"])
        labels = sorted({label for f in new_facts for label in f["layer_labels"]})
        lines.append(
            f"| {row['name']} (`{row['anchor']}`) | {old.get('fact_count', old.get('skipped'))} | "
            f"{new.get('fact_count', new.get('skipped'))} | {labelled} | {', '.join(labels) or '-'} |"
        )
    for row in out["sections"]:
        lines += ["", f"### {row['name']}"]
        for label in ("old", "new"):
            lines.append(f"- {label}:")
            for fact in row.get(label, {}).get("facts") or []:
                tags = f" [{', '.join(fact['layer_labels'])}]" if fact["layer_labels"] else ""
                lines.append(f"  - {fact['text']}{tags}")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--show", action="store_true", help="print the excerpts; send nothing")
    args = parser.parse_args()
    excerpts = [excerpt(spec) for spec in SECTIONS]
    if args.show:
        for item in excerpts:
            meta = {k: v for k, v in item.items() if k != "content"}
            print(json.dumps(meta), "\n", item["content"], "\n", "-" * 80)
        raise SystemExit(0)
    out = run(excerpts)
    path = HERE / "results" / "mission-compare-05.json"
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(markdown(out))
    print("->", path)
