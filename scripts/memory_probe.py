"""The memory probe set against a running Atlas: what the reading index returns.

Runs each probe of `--probes` (`configs/memory/probes.yaml`: the five pilot questions and
their Scout-style queries, each with its theme scope) through `POST /api/v1/memory/recall`,
which makes no LLM call, and reports per recall, per probe and in total: memories returned,
resolved citations, distinct sections and companies, the share of observations, the memories
whose text another returned memory repeats, and the companies ranked by pointer weight
(`atlas.research.probes`). Company IDs are named through `GET /api/v1/companies`.

The report goes to `--out` (default `.scratch/live-runs/<stamp>-memory-probe/`) as
`results.json` (every answer's measures, and the raw answers) and `summary.md`. Run it before
and after a change to Memory; the summary goes into the implementation log.

    uv run python scripts/memory_probe.py --base-url https://atlas.ekenhome.se
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2

from atlas.companies import load_universe
from atlas.research.probes import ProbeConfigError, ProbeRecall, load_probes, report, summary

REPO = Path(__file__).resolve().parents[1]
PAUSE_SECONDS = 0.2  # between recalls: the API and Hindsight are shared
PAGE = 500


def main() -> int:
    args = _arguments()
    try:
        probes = load_probes(Path(args.probes), load_universe(Path(args.themes)))
    except ProbeConfigError as error:
        print(f"invalid probe file: {error}", file=sys.stderr)
        return 2
    client = httpx2.Client(base_url=args.base_url.rstrip("/") + "/api/v1", timeout=120.0)
    names = _company_names(client)
    answers: list[tuple[ProbeRecall, dict[str, Any] | str]] = []
    for recall in probes.recalls():
        time.sleep(PAUSE_SECONDS)
        body = {"query": recall.text, "scope": {"theme_ids": recall.theme_ids}}
        response = client.post("/memory/recall", json=body)
        if response.is_success:
            answers.append((recall, response.json()))
        else:
            answers.append((recall, f"HTTP {response.status_code}: {response.text[:300]}"))
        print(f"{recall.probe_id} {recall.kind} {recall.index}: HTTP {response.status_code}")
    probe_report = report(answers, names)
    out = Path(args.out) if args.out else _default_out()
    out.mkdir(parents=True, exist_ok=True)
    results = {
        "base_url": args.base_url,
        "probes": str(args.probes),
        "probe_set_version": probes.version,
        "run_at": datetime.now(UTC).isoformat(),
        "report": probe_report.model_dump(mode="json"),
        "answers": [
            {"recall": recall.model_dump(mode="json"), "answer": answer}
            for recall, answer in answers
        ],
    }
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    header = (
        f"# Memory probe, {results['run_at']}\n\n"
        f"Against {args.base_url}, probe set version {probes.version}.\n\n"
    )
    (out / "summary.md").write_text(header + summary(probe_report), encoding="utf-8")
    print(f"report: {out}")
    return 1 if any(row.error for row in probe_report.results) else 0


def _company_names(client: httpx2.Client) -> dict[str, str]:
    names: dict[str, str] = {}
    offset = 0
    while True:
        response = client.get("/companies", params={"limit": PAGE, "offset": offset})
        response.raise_for_status()
        page = response.json()
        names.update({item["id"]: item["slug"] for item in page["items"]})
        offset += len(page["items"])
        if not page["items"] or offset >= page["total"]:
            return names


def _default_out() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return REPO / ".scratch" / "live-runs" / f"{stamp}-memory-probe"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--base-url", default="https://atlas.ekenhome.se")
    parser.add_argument("--probes", default=str(REPO / "configs" / "memory" / "probes.yaml"))
    parser.add_argument(
        "--themes", default=str(REPO / "configs" / "themes" / "ai-infrastructure.yaml")
    )
    parser.add_argument("--out")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
