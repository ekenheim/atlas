"""Retrieval options, step 1 (live): the candidate pools from the real pipeline.

Retains the recorded EDGAR fixtures (and the synthetic transcript) through Atlas's real retain
path into a throwaway bank on the LOCAL spike Hindsight (localhost:8888; `run.sh`), exactly as
the conformance driver does (`tests/live/conformance.py`), then recalls every probe question and
its four queries with budget=high, max_tokens=8192, trace=true, and saves everything the offline
step needs: the raw recall answers (with traces), every memory in the bank, the document-to-section
map and the resolved known answers. The bank is deleted at the end.

    ATLAS_SPIKE_ENV_FILE=... bash spikes/hindsight/run.sh MiniMax-M3 '{"thinking":{"type":"disabled"}}'
    PYTHONPATH=. uv run python spikes/hindsight/retrieval_options_collect.py --out DIR

Hard cap: ATLAS_RO_LLM_CAP (default 120) LLM requests read from the bank's request log; the
retain/LLM-operation proxies of the conformance driver enforce their own caps as well.
"""

import argparse
import json
import os
import sys
import tempfile
import uuid
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import boto3
import httpx2
from botocore.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from atlas.companies import load_universe
from atlas.conformance import BehaviourBank, load_known_answers
from atlas.conformance.known_answers import resolve_answers
from atlas.db.migrate import upgrade
from atlas.research.probes import load_probes
from tests.fakes.serve import serve
from tests.fakes.tradingview import FakeTradingView
from tests.live.conformance import (
    Aborted,
    KNOWN_ANSWERS,
    PROBES,
    THEMES,
    Caps,
    conformance_settings,
    new_bank_id,
    run_behaviours,
)
from tests.live.stack import DEFAULT_ADMIN_DATABASE_URL

HINDSIGHT = "http://127.0.0.1:8888"

if not hasattr(os, "fchmod"):  # Windows: Atlas's token-file writer calls it; the file is a fake's
    os.fchmod = lambda fd, mode: None  # type: ignore[attr-defined]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cap = int(os.environ.get("ATLAS_RO_LLM_CAP", "120"))

    admin_url = os.environ.get("ATLAS_TEST_DATABASE_URL") or DEFAULT_ADMIN_DATABASE_URL
    name = f"atlas_retopt_{uuid.uuid4().hex[:10]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    db_url = make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    summary: dict[str, Any] = {}
    bucket = f"atlas-retopt-{uuid.uuid4().hex[:10]}"
    s3 = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:59000",
        aws_access_key_id="atlas-dev",
        aws_secret_access_key="atlas-dev-secret",
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 1}),
    )
    s3.create_bucket(Bucket=bucket)
    try:
        upgrade(db_url)
        with ExitStack() as stack:
            tv = stack.enter_context(serve(FakeTradingView().handle))
            caps = Caps.around(HINDSIGHT)
            stack.callback(caps.close)
            llm_served = stack.enter_context(serve(caps.llm.handle))
            caps.chain(llm_served.url)
            retains_served = stack.enter_context(serve(caps.retains.handle))
            settings = conformance_settings(
                database_url=db_url,
                workdir=Path(tempfile.mkdtemp(prefix="retopt-")),
                hindsight_url=retains_served.url,
                hindsight_api_key=None,
                bank_id=new_bank_id(),
                tradingview_url=tv.url,
                fast=False,
            )
            # Windows: the filesystem archive's read-only temp file cannot be unlinked; use the
            # shared Silo (a throwaway bucket, deleted at the end).
            settings = settings.model_copy(
                update={
                    "archive_backend": "s3",
                    "s3_endpoint_url": "http://127.0.0.1:59000",
                    "s3_bucket": bucket,
                    "s3_access_key_id": "atlas-dev",
                    "s3_secret_access_key": SecretStr("atlas-dev-secret"),
                }
            )
            universe = load_universe(THEMES)
            probes = load_probes(PROBES, universe)
            answers = load_known_answers(KNOWN_ANSWERS, universe, probes)
            bank_id = settings.hindsight_bank_id

            def during(bank: BehaviourBank) -> None:
                # the LLM request budget so far (extraction + consolidation)
                stats = bank.gateway.llm_request_stats(period="1d").model_dump(mode="json")
                (out / "llm-stats-after-retain.json").write_text(json.dumps(stats, indent=1))
                resolved, errors = resolve_answers(bank.api, answers.answers)
                (out / "answers.json").write_text(
                    json.dumps(
                        {
                            "resolved": [r.model_dump(mode="json") for r in resolved],
                            "errors": [e.model_dump(mode="json") for e in errors],
                        },
                        indent=1,
                    )
                )
                engine = create_engine(db_url)
                with engine.connect() as c:
                    rows = c.execute(
                        text(
                            "SELECT m.hindsight_document_id AS doc, m.section_anchor AS anchor,"
                            " m.source_version_id AS version, v.source_document_id AS sdoc,"
                            " m.retain_state AS state, m.fact_count AS facts"
                            " FROM memory_document m JOIN source_version v"
                            " ON v.id = m.source_version_id WHERE m.bank_id = :b"
                        ),
                        {"b": bank_id},
                    ).all()
                (out / "documents.json").write_text(
                    json.dumps([{k: str(v) for k, v in r._mapping.items()} for r in rows], indent=1)
                )
                engine.dispose()
                base = f"{HINDSIGHT}/v1/default/banks/{bank_id}"
                with httpx2.Client(timeout=600.0) as http:
                    memories: list[dict[str, Any]] = []
                    while True:
                        page = http.get(
                            f"{base}/memories/list",
                            params={"limit": 100, "offset": len(memories)},
                        ).json()
                        memories.extend(page["items"])
                        if not page["items"] or len(memories) >= page["total"]:
                            break
                    (out / "memories.json").write_text(json.dumps(memories, indent=1))
                    recalls: list[dict[str, Any]] = []
                    for probe in probes.probes:
                        for query in (probe.question, *probe.queries):
                            body = {
                                "query": query,
                                "budget": "high",
                                "max_tokens": 8192,
                                "trace": True,
                            }
                            reply = http.post(f"{base}/memories/recall", json=body)
                            # Start the spike with ATLAS_RERANKER_PROVIDER=rrf: the litellm/TEI
                            # reranker answers 413 for a pool over 256 (the first run's 25 500s).
                            if not reply.is_success:
                                (out / "recall-error.txt").write_text(reply.text, encoding="utf-8")
                                raise Aborted(f"recall failed: HTTP {reply.status_code}")
                            recalls.append(
                                {
                                    "probe": probe.id,
                                    "query": query,
                                    "is_question": query == probe.question,
                                    "status": reply.status_code,
                                    "answer": reply.json() if reply.is_success else reply.text,
                                }
                            )
                    (out / "recalls.json").write_text(json.dumps(recalls))
                final = bank.gateway.llm_request_stats(period="1d").model_dump(mode="json")
                (out / "llm-stats-final.json").write_text(json.dumps(final, indent=1))
                summary["memories"] = len(memories)
                summary["recalls"] = len(recalls)

            report = _Report()
            run_behaviours(
                report,
                settings,
                caps,
                settle_seconds=3600.0,
                poll_seconds=5.0,
                checks=[],
                during=during,
                read_llm_stats=False,
            )
            summary["aborted"] = report.aborted
            summary["bank_deleted"] = report.bank_deleted
            summary["proxy_retain_operations"] = caps.retains.total
            summary["proxy_llm_operations"] = caps.llm.total
            summary["proxy_refused"] = caps.refused()
    finally:
        try:
            for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
                for e in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]:
                    s3.delete_object(Bucket=bucket, Key=e["Key"], VersionId=e["VersionId"])
            s3.delete_bucket(Bucket=bucket)
        except Exception as error:  # reported, not fatal
            print("bucket cleanup failed:", error)
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
    summary["llm_cap"] = cap
    (out / "collect-summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    return 0


class _Report:
    """The few attributes `run_behaviours` writes."""

    def __init__(self) -> None:
        self.bank_id = ""
        self.behaviours: list[Any] = []
        self.aborted: str | None = None
        self.bank_deleted: bool | None = None
        self.stack: dict[str, Any] = {}
        self.usage: Any = None


if __name__ == "__main__":
    sys.exit(main())
