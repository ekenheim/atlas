"""`atlas` command: one image, run as `atlas api` or `atlas worker`."""

import argparse
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from atlas.logs import configure_logging
from atlas.settings import Settings

if TYPE_CHECKING:
    from atlas.companies import Universe
    from atlas.jobs import Enqueued

log = logging.getLogger("atlas")


def load_settings() -> Settings:
    try:
        return Settings()  # pyright: ignore[reportCallIssue]  # values come from env/.env
    except ValidationError as error:
        lines = ["atlas: invalid configuration (see .env.example):"]
        for issue in error.errors():
            if not issue["loc"]:  # a cross-field rule; its message names the settings
                lines.append(f"  - {issue['msg'].removeprefix('Value error, ')}")
                continue
            name = f"ATLAS_{str(issue['loc'][0]).upper()}"
            if issue["type"] == "missing":
                lines.append(f"  - {name} is required but not set")
            else:
                lines.append(f"  - {name}: {issue['msg']}")
        print("\n".join(lines), file=sys.stderr)
        raise SystemExit(2) from None


def run_evaluate(settings: Settings, cases: list[str] | None, *, live: bool) -> int:
    """Run the gold cases; print one line per case (stderr) and the run as JSON (stdout).

    0 when every case passed, 1 when one failed, 2 when the evaluation was refused.
    """
    import json
    import os

    from atlas.evaluation import LIVE_OPT_IN, CaseResult, EvaluationRefused, GoldError, open_gold
    from atlas.evaluation import evaluate as run_cases

    if live and os.environ.get(LIVE_OPT_IN) != "1":
        print(
            f"atlas: a live evaluation spends MiniMax and Codex quota (its cases' sources are"
            f" retained into throwaway Hindsight banks): set {LIVE_OPT_IN}=1 as well as"
            " --live (never in CI)",
            file=sys.stderr,
        )
        return 2

    def report(result: CaseResult) -> None:
        verdict = "pass" if result.passed else "FAIL"
        scores = ", ".join(f"{metric} {value:.2f}" for metric, value in result.scores.items())
        print(f"{result.case_id} {verdict} ({scores})", file=sys.stderr)
        if result.error:
            print(f"  {result.error.splitlines()[0]}", file=sys.stderr)

    try:
        gold = open_gold(settings.evaluation_gold_dir)
        outcome = run_cases(
            settings, gold, case_ids=cases, mode="live" if live else "fake", report=report
        )
    except (EvaluationRefused, GoldError) as error:
        print(f"atlas: {error}", file=sys.stderr)
        return 2
    summary = {
        "evaluation_run_id": str(outcome.run_id),
        "mode": "live" if live else "fake",
        "cases_total": len(outcome.results),
        "cases_passed": sum(result.passed for result in outcome.results),
        "cases": [
            {"case_id": r.case_id, "passed": r.passed, "scores": r.scores, "error": r.error}
            for r in outcome.results
        ],
    }
    print(json.dumps(summary, indent=2))
    return 0 if outcome.passed else 1


def run_api(settings: Settings) -> None:
    import uvicorn

    from atlas.api.app import create_app

    # log_config=None keeps uvicorn on the JSON root logger configured in main().
    uvicorn.run(create_app(settings), host="0.0.0.0", port=8000, log_config=None)  # noqa: S104


def run_worker(settings: Settings, once: bool) -> None:
    import signal
    import threading
    from datetime import timedelta

    from sqlalchemy.exc import OperationalError

    from atlas.db import create_engine
    from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry, builtin_schedules

    engine = create_engine(settings)
    worker = Worker(
        JobQueue(engine, pacing=Pacing.from_settings(settings)),
        builtin_registry(settings),
        lease=timedelta(seconds=settings.job_lease_seconds),
        schedules=builtin_schedules(settings, engine),
    )
    try:
        if once:
            try:
                attempts = worker.run_once()
            except OperationalError as error:
                log.error(f"worker pass failed: database unavailable ({type(error.orig).__name__})")
                raise SystemExit(1) from None
            log.info(f"worker pass done: {attempts} job attempt(s) run")
            return
        stop = threading.Event()

        def request_stop(signum: int, frame: object) -> None:
            log.info(f"worker stopping on signal {signum}; finishing the current job")
            stop.set()

        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, request_stop)
        worker.run_forever(stop, poll_seconds=settings.worker_poll_seconds)
    finally:
        engine.dispose()


def enqueue_job(
    settings: Settings,
    kind: str,
    key: str,
    payload_json: str,
    max_attempts: int,
    backfill: bool = False,
) -> None:

    from pydantic import JsonValue, TypeAdapter

    from atlas.audit import Actor
    from atlas.db import create_engine
    from atlas.jobs import JobQueue, builtin_registry

    kinds = builtin_registry(settings).kinds()
    if kind not in kinds:
        print(f"atlas: unknown job kind {kind!r} (known: {', '.join(kinds)})", file=sys.stderr)
        raise SystemExit(2)
    if max_attempts < 1:
        print("atlas: --max-attempts must be at least 1", file=sys.stderr)
        raise SystemExit(2)
    try:
        payload = TypeAdapter(dict[str, JsonValue]).validate_json(payload_json)
    except ValidationError:
        print("atlas: --payload must be a JSON object", file=sys.stderr)
        raise SystemExit(2) from None
    engine = create_engine(settings)
    try:
        enqueued = JobQueue(engine, actor=Actor.from_settings(settings)).enqueue(
            kind,
            key,
            payload,
            max_attempts=max_attempts,
            job_class="backfill" if backfill else "interactive",
        )
    finally:
        engine.dispose()
    _print_enqueued(enqueued)


def _print_enqueued(enqueued: "Enqueued") -> None:
    import json

    job = enqueued.job
    summary = {"id": str(job.id), "kind": job.kind, "idempotency_key": job.idempotency_key}
    print(
        json.dumps(
            {
                **summary,
                "job_class": job.job_class,
                "status": job.status,
                "created": enqueued.created,
                "payload": job.payload,
            },
            default=str,
        )
    )


def _universe(settings: Settings) -> "Universe":
    from atlas.companies import UniverseConfigError, load_universe

    try:
        return load_universe(settings.themes_config)
    except UniverseConfigError as error:
        print(f"atlas: {error}", file=sys.stderr)
        raise SystemExit(2) from None


def enqueue_ingest(
    settings: Settings,
    company: str,
    key: str | None,
    forms: str | None,
    limit: int | None,
    max_attempts: int,
    backfill: bool = False,
    since: str | None = None,
    all_history: bool = False,
    max_retains: int | None = None,
) -> None:
    from datetime import UTC, datetime, timedelta

    from atlas.audit import Actor
    from atlas.db import create_engine
    from atlas.jobs import JobQueue
    from atlas.ledger.exchange_ingest import exchange_refusal
    from atlas.ledger.ingest import INGEST_KIND, ingest_payload

    universe = _universe(settings)
    if company not in universe.companies:
        # A committed Candidate's company is in the universe's database extension.
        from atlas.companies import counterparty_refusal, extend_universe, is_counterparty

        engine = create_engine(settings)
        try:
            with engine.connect() as connection:
                universe = extend_universe(connection, universe)
                counterparty = is_counterparty(connection, company)
        finally:
            engine.dispose()
        if company not in universe.companies and counterparty:
            print(f"atlas: {counterparty_refusal(company)}", file=sys.stderr)
            raise SystemExit(2)
    if company not in universe.companies:
        known = ", ".join(sorted(universe.companies))
        print(
            f"atlas: company {company!r} is not configured in {settings.themes_config}"
            f" (known: {known})",
            file=sys.stderr,
        )
        raise SystemExit(2)
    source_path = universe.companies[company].source_path
    refusal = exchange_refusal(company, source_path)
    if refusal is not None:
        print(f"atlas: {refusal}", file=sys.stderr)
        raise SystemExit(2)
    if source_path != "sec" and forms:
        print(
            f"atlas: --forms applies to SEC filers only ({company!r} is {source_path!r})",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if (
        (limit is not None and limit < 1)
        or max_attempts < 1
        or (max_retains is not None and max_retains < 1)
    ):
        print(
            "atlas: --limit, --max-attempts and --max-retains must be at least 1", file=sys.stderr
        )
        raise SystemExit(2)
    if source_path != "sec" and max_retains is not None:
        print(
            f"atlas: --max-retains applies to SEC filers only ({company!r} is {source_path!r})",
            file=sys.stderr,
        )
        raise SystemExit(2)
    form_list = [form.strip() for form in forms.split(",") if form.strip()] if forms else None
    if since is not None and all_history:
        print("atlas: --since and --all-history exclude each other", file=sys.stderr)
        raise SystemExit(2)
    if since is not None:
        try:
            cutoff: datetime | None = datetime.fromisoformat(since)
        except ValueError:
            print(f"atlas: --since must be a date like 2025-01-31, not {since!r}", file=sys.stderr)
            raise SystemExit(2) from None
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
    elif all_history:
        cutoff = None
    else:
        cutoff = datetime.now(UTC) - timedelta(days=settings.ingest_lookback_days)
    # Without --key, each invocation is a new ingest run; reuse a key to make it idempotent.
    key = key or f"ingest:{company}:{datetime.now(UTC).isoformat(timespec='seconds')}"
    engine = create_engine(settings)
    try:
        enqueued = JobQueue(engine, actor=Actor.from_settings(settings)).enqueue(
            INGEST_KIND,
            key,
            ingest_payload(company, form_list, limit, cutoff, max_retains),
            max_attempts=max_attempts,
            job_class="backfill" if backfill else "interactive",
        )
    finally:
        engine.dispose()
    _print_enqueued(enqueued)


def run_retry_failed(
    settings: Settings, since: str | None, all_history: bool, backfill: bool
) -> None:
    import json
    from datetime import UTC, datetime, timedelta

    from atlas.audit import Actor
    from atlas.db import create_engine
    from atlas.retention import retry_failed

    if since is not None and all_history:
        print("atlas: --since and --all-history exclude each other", file=sys.stderr)
        raise SystemExit(2)
    cutoff: datetime | None
    if since is not None:
        try:
            cutoff = datetime.fromisoformat(since)
        except ValueError:
            print(f"atlas: --since must be a date like 2025-01-31, not {since!r}", file=sys.stderr)
            raise SystemExit(2) from None
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
    elif all_history:
        cutoff = None
    else:
        cutoff = datetime.now(UTC) - timedelta(days=settings.ingest_lookback_days)
    engine = create_engine(settings)
    try:
        summary = retry_failed(
            engine,
            Actor.from_settings(settings),
            since=cutoff,
            job_class="backfill" if backfill else "interactive",
            eight_k_items=settings.eight_k_items(),
            exhibits_only_items=settings.eight_k_exhibits_only_items(),
        )
    finally:
        engine.dispose()
    print(json.dumps(summary | {"since": cutoff.isoformat() if cutoff else None}))


def run_triage_retry(settings: Settings, source_version: str | None, failed: bool) -> None:
    import json
    import uuid

    from atlas.audit import Actor
    from atlas.db import create_engine
    from atlas.retention import TriageRetryRefused, retry_failed_triage

    if (source_version is None) == (not failed):
        print("atlas: give exactly one of --source-version and --failed", file=sys.stderr)
        raise SystemExit(2)
    version: uuid.UUID | None = None
    if source_version is not None:
        try:
            version = uuid.UUID(source_version)
        except ValueError:
            print(
                f"atlas: --source-version must be a UUID, not {source_version!r}", file=sys.stderr
            )
            raise SystemExit(2) from None
    engine = create_engine(settings)
    try:
        jobs = retry_failed_triage(engine, Actor.from_settings(settings), version)
    except TriageRetryRefused as refused:
        print(f"atlas: {refused}", file=sys.stderr)
        raise SystemExit(2) from None
    finally:
        engine.dispose()
    enqueued = [
        {"id": str(job.id), "source_version_id": job.payload["source_version_id"]} for job in jobs
    ]
    print(json.dumps({"enqueued": enqueued}))


def run_triage_audit(
    settings: Settings,
    sample: int,
    company: str | None,
    seed: int,
    *,
    backfill: bool,
    wait: bool,
    timeout: float,
    poll_seconds: float,
) -> int:
    """Create a triage audit and enqueue its job; print it as JSON (stdout). With `wait`,
    poll until it completes and print its summary instead (and a one-line reading on stderr).

    0 when created (or, waiting, completed), 1 when its job failed or the wait timed out, 2
    when the audit was refused.
    """
    import json
    import time

    from atlas.audit import Actor
    from atlas.db import create_engine
    from atlas.retention import AuditRefused, ReaderSettings, create_audit, get_audit

    engine = create_engine(settings)
    try:
        try:
            audit = create_audit(
                engine,
                Actor.from_settings(settings),
                sample=sample,
                company_slug=company,
                seed=seed,
                reader=ReaderSettings(
                    excerpt_chars=settings.triage_excerpt_chars,
                    windows_per_section=settings.triage_windows_per_section,
                    window_overlap_chars=settings.triage_window_overlap_chars,
                    judge_max_chars=settings.triage_judge_max_chars,
                ),
                job_class="backfill" if backfill else "interactive",
            )
        except AuditRefused as refused:
            print(f"atlas: {refused}", file=sys.stderr)
            return 2
        created = {
            "triage_audit_id": str(audit.id),
            "job_id": str(audit.job_id),
            "status": audit.status,
            "sample_size": audit.sample_size,
            "population": audit.population,
        }
        if not wait:
            print(json.dumps(created))
            return 0
        print(
            f"atlas: triage audit {audit.id}: {audit.sample_size} of {audit.population} skipped"
            " sections sampled; waiting for the worker to judge them",
            file=sys.stderr,
        )
        deadline = time.monotonic() + timeout
        while True:
            with engine.connect() as connection:
                found = get_audit(connection, audit.id)
            assert found is not None
            if found.status == "completed":
                break
            if found.job_status == "failed":
                print(f"atlas: the triage audit's job {audit.job_id} failed", file=sys.stderr)
                return 1
            if time.monotonic() >= deadline:
                print(
                    f"atlas: timed out after {timeout:g} s ({found.samples_judged} of"
                    f" {found.sample_size} judged); the audit continues: GET"
                    f" /api/v1/triage/audits/{audit.id}",
                    file=sys.stderr,
                )
                return 1
            time.sleep(poll_seconds)
    finally:
        engine.dispose()
    summary = found.summary
    if summary.miss_rate is not None:
        print(
            f"atlas: miss rate {summary.misses}/{summary.judged} = {summary.miss_rate:.1%}"
            f" (Wilson 95% {summary.wilson_low:.1%} to {summary.wilson_high:.1%})",
            file=sys.stderr,
        )
    print(
        json.dumps(created | {"status": found.status, "summary": summary.model_dump(mode="json")})
    )
    return 0


def run_correct_availability(settings: Settings) -> None:
    import dataclasses
    import json

    from atlas.audit import Actor
    from atlas.db import create_engine
    from atlas.ledger import correct_availability

    engine = create_engine(settings)
    try:
        summary = correct_availability(engine, Actor.from_settings(settings))
    finally:
        engine.dispose()
    print(json.dumps(dataclasses.asdict(summary)))


def run_sources_import(
    settings: Settings,
    company: str,
    file: Path,
    origin_url: str,
    published_at: str,
    title: str | None,
    publisher: str | None,
    media_type: str | None,
) -> None:
    import json
    from datetime import datetime

    from atlas.companies import UniverseConfigError
    from atlas.ledger.manual_import import ImportRefused, import_document

    try:
        when = datetime.fromisoformat(published_at)
    except ValueError:
        print(
            f"atlas: --published-at must be an ISO 8601 time with its offset, not {published_at!r}",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    try:
        imported = import_document(
            settings,
            company=company,
            file=file,
            origin_url=origin_url,
            published_at=when,
            title=title,
            publisher=publisher,
            media_type=media_type,
            published_local=published_at,
        )
    except (ImportRefused, UniverseConfigError) as error:
        print(f"atlas: {error}", file=sys.stderr)
        raise SystemExit(2) from None
    print(
        json.dumps(
            {
                "outcome": imported.outcome,
                "company_id": str(imported.company_id),
                "source_document_id": str(imported.source_document_id),
                "source_version_id": str(imported.source_version_id),
                "retain_jobs": imported.retain_jobs,
            }
        )
    )


def run_assign_families(settings: Settings) -> None:
    import dataclasses
    import json

    from atlas.archive import open_archive
    from atlas.audit import Actor
    from atlas.db import create_engine
    from atlas.ledger import assign_missing

    engine = create_engine(settings)
    try:
        summary = assign_missing(
            engine,
            open_archive(settings),
            Actor.from_settings(settings),
            max_hamming_distance=settings.evidence_family_max_hamming_distance,
        )
    finally:
        engine.dispose()
    print(json.dumps(dataclasses.asdict(summary)))


def enqueue_reparse(
    settings: Settings, company: str | None, parser_version: str, key: str | None
) -> None:
    """`atlas ledger reparse`: enqueue a `reparse` job for the Source Versions whose recorded
    parse is an earlier parser version's (one company's, or all)."""
    from datetime import UTC, datetime

    from sqlalchemy import text

    from atlas.audit import Actor
    from atlas.db import create_engine
    from atlas.jobs import JobQueue
    from atlas.ledger.parses import REPARSE_KIND, reparse_payload
    from atlas.parsing import PARSER_VERSION

    if parser_version != PARSER_VERSION:
        print(
            f"atlas: only the current parser ({PARSER_VERSION}) can re-parse, not"
            f" {parser_version!r}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    engine = create_engine(settings)
    try:
        company_id = None
        if company is not None:
            with engine.connect() as connection:
                company_id = connection.execute(
                    text("SELECT id FROM company WHERE slug = :slug"), {"slug": company}
                ).scalar_one_or_none()
            if company_id is None:
                print(f"atlas: no company {company!r} (seed the universe first)", file=sys.stderr)
                raise SystemExit(2)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        enqueued = JobQueue(engine, actor=Actor.from_settings(settings)).enqueue(
            REPARSE_KIND,
            key or f"reparse-{parser_version}-{company or 'all'}-{stamp}",
            reparse_payload(company_id=company_id, parser_version=parser_version),
        )
    finally:
        engine.dispose()
    _print_enqueued(enqueued)


def seed_companies(settings: Settings) -> None:
    import json

    from atlas.audit import Actor
    from atlas.companies import seed
    from atlas.db import create_engine

    universe = _universe(settings)
    engine = create_engine(settings)
    try:
        with engine.begin() as connection:
            seeded = seed(connection, Actor.from_settings(settings), universe)
    finally:
        engine.dispose()
    for each in seeded:
        print(
            json.dumps({"company": each.slug, "id": str(each.company_id), "changes": each.changes})
        )


def resolve_companies(settings: Settings, slugs: list[str] | None) -> int:
    import dataclasses
    import json

    from atlas.audit import Actor
    from atlas.companies import seed
    from atlas.db import create_engine
    from atlas.identity import EntityResolver, IdentitySourceError
    from atlas.identity.service import resolve_universe

    universe = _universe(settings)
    unknown = [slug for slug in slugs or [] if slug not in universe.companies]
    if unknown:
        print(f"atlas: not configured: {', '.join(unknown)}", file=sys.stderr)
        return 2
    if not settings.sec_user_agent:
        print("atlas: entity resolution calls SEC: set ATLAS_SEC_USER_AGENT", file=sys.stderr)
        return 2
    actor = Actor.from_settings(settings)
    engine = create_engine(settings)
    try:
        with engine.begin() as connection:
            seed(connection, actor, universe, slugs)
        with EntityResolver.from_settings(settings) as resolver:
            results = resolve_universe(engine, actor, resolver, universe, slugs)
    except IdentitySourceError as error:
        print(f"atlas: {error}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    for result in results:
        print(json.dumps(dataclasses.asdict(result), default=str))
    return 0


def run_tradingview_login(
    settings: Settings,
    print_tokens: bool,
    port: int | None,
    client_id: str | None,
    timeout: float,
) -> int:
    """`atlas tradingview login`: the OAuth flow; the tokens go to the token file (mode 0600)
    or, with --print-tokens, to stdout for use as secrets. Nothing else prints a token."""
    import json

    from atlas.tradingview import TradingViewAuthError, write_token_file
    from atlas.tradingview.login import login
    from atlas.tradingview.service import TradingViewDisabled, require_enabled

    def show(url: str) -> None:
        print(
            f"Open this URL in a browser and sign in to TradingView:\n{url}",
            file=sys.stderr,
            flush=True,
        )

    try:
        require_enabled(settings)
        tokens = login(settings, show=show, port=port, client_id=client_id, timeout=timeout)
    except (TradingViewDisabled, TradingViewAuthError) as error:
        print(f"atlas: {error}", file=sys.stderr)
        return 1
    summary = {
        "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None,
        "refreshable": tokens.refreshable(),
        "client_id": tokens.client_id,
        "token_endpoint": tokens.token_endpoint,
    }
    if print_tokens:
        print(
            json.dumps(
                summary
                | {
                    "ATLAS_TRADINGVIEW_ACCESS_TOKEN": tokens.access_token,
                    "ATLAS_TRADINGVIEW_REFRESH_TOKEN": tokens.refresh_token,
                    "ATLAS_TRADINGVIEW_TOKEN_URL": tokens.token_endpoint,
                    "ATLAS_TRADINGVIEW_CLIENT_ID": tokens.client_id,
                }
            )
        )
        return 0
    write_token_file(settings.tradingview_token_file, tokens)
    print(json.dumps(summary | {"token_file": str(settings.tradingview_token_file)}))
    return 0


def run_tradingview_check(settings: Settings, symbol: str) -> int:
    """`atlas tradingview check`: one catalog call; prints counts only, never content."""
    import json
    from collections import Counter
    from datetime import UTC, datetime, timedelta

    from atlas.tradingview import McpError, TradingViewAuthError, TradingViewClient
    from atlas.tradingview.service import TradingViewDisabled, mcp_session

    now = datetime.now(UTC)
    try:
        with mcp_session(settings) as mcp:
            client = TradingViewClient(mcp, max_calls=1, on_call=lambda tool, error: None)
            listed = client.documents(
                symbol,
                start=now - timedelta(days=settings.tradingview_lookback_days),
                end=now,
                limit=settings.tradingview_documents_limit,
            )
    except (TradingViewDisabled, TradingViewAuthError, McpError) as error:
        print(f"atlas: {error}", file=sys.stderr)
        return 1
    categories = Counter(
        (item.category.title if item.category else None) or "uncategorized" for item in listed.items
    )
    print(
        json.dumps(
            {
                "symbol": symbol,
                "documents": len(listed.items),
                "total": listed.total,
                "categories": dict(sorted(categories.items())),
                "transcript_views": sum(len(item.transcript_views()) for item in listed.items),
                "tool_calls": 1,
            }
        )
    )
    return 0


def run_audit_verify(settings: Settings) -> int:
    from atlas.audit import verify_chain
    from atlas.db import create_engine

    engine = create_engine(settings)
    try:
        with engine.connect() as connection:
            report = verify_chain(connection)
    finally:
        engine.dispose()
    if report.ok:
        print(f"audit chain ok: {report.events} events, head {report.head_hash or '-'}")
        return 0
    lines = [f"audit chain broken: {len(report.breaks)} problem(s) in {report.events} events"]
    lines += [f"  event {each.event_id}: {each.reason}" for each in report.breaks]
    print("\n".join(lines), file=sys.stderr)
    return 1


def run_apply_template(
    settings: Settings, template_path: Path | None, *, if_changed: bool = False
) -> int:
    import json

    from sqlalchemy.exc import OperationalError

    from atlas.audit import Actor
    from atlas.bank_template import BankTemplate, InvalidTemplate, apply_template, is_applied
    from atlas.db import create_engine
    from atlas.hindsight import HINDSIGHT_NOT_CONFIGURED, HindsightError, HindsightGateway

    try:
        template = BankTemplate.load(template_path or settings.hindsight_template_path)
    except InvalidTemplate as error:
        print(f"atlas: invalid bank template: {error}", file=sys.stderr)
        return 2
    gateway = HindsightGateway.from_settings(settings)
    if gateway is None:
        print(f"atlas: {HINDSIGHT_NOT_CONFIGURED}", file=sys.stderr)
        return 2
    engine = create_engine(settings)
    if if_changed:
        # A re-import can re-queue mental-model refreshes (LLM spend), so a deploy that runs this
        # on every start must not re-import a template the bank already has.
        with engine.connect() as connection:
            unchanged = is_applied(connection, gateway.bank_id, template)
        if unchanged:
            gateway.close()
            engine.dispose()
            print(
                f"template {template.template_version} already applied to {gateway.bank_id};"
                " nothing to do"
            )
            return 0
    try:
        applied = apply_template(engine, gateway, template, Actor.from_settings(settings))
    except HindsightError as error:
        print(f"atlas: template not applied: {error}", file=sys.stderr)
        return 1
    except OperationalError as error:
        # The import may have succeeded; re-applying the same template is safe.
        print(
            "atlas: template application not recorded: database unavailable"
            f" ({type(error.orig).__name__}); re-run once it is back",
            file=sys.stderr,
        )
        return 1
    finally:
        gateway.close()
        engine.dispose()
    summary = applied.model_dump(mode="json", include={"bank_id", "template_version"})
    summary |= {
        "manifest_sha256": applied.manifest_sha256,
        "dry_run": applied.dry_run.model_dump(mode="json", exclude={"bank_id"}),
        "applied": applied.applied.model_dump(mode="json", exclude={"bank_id"}),
        "audit_event_id": applied.audit_event_id,
    }
    print(json.dumps(summary))
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="atlas")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("api", help="serve the HTTP API and the static frontend")
    commands.add_parser("migrate", help="upgrade the database schema to the latest revision")
    audit = commands.add_parser("audit", help="inspect the audit trail")
    audit_commands = audit.add_subparsers(dest="audit_command", required=True)
    audit_commands.add_parser("verify", help="verify the hash chain; exit 1 if it is broken")
    worker = commands.add_parser("worker", help="run background jobs")
    worker.add_argument("--once", action="store_true", help="process available work, then exit")
    jobs = commands.add_parser("jobs", help="manage the job queue")
    jobs_commands = jobs.add_subparsers(dest="jobs_command", required=True)
    enqueue = jobs_commands.add_parser("enqueue", help="add a job (idempotent per kind and key)")
    enqueue.add_argument("kind", help="the job kind, e.g. noop")
    enqueue.add_argument("--key", required=True, help="idempotency key: same key, same job")
    enqueue.add_argument("--payload", default="{}", help="job payload as a JSON object")
    enqueue.add_argument("--max-attempts", type=int, default=3, help="retry bound (default 3)")
    enqueue.add_argument(
        "--backfill",
        action="store_true",
        help="backfill class: held by the backfill window, if set, and by the budgets'"
        " interactive reserve",
    )
    ingest = commands.add_parser(
        "ingest", help="enqueue an ingest job for a configured company (run by the worker)"
    )
    ingest.add_argument("--company", required=True, help="company slug from the theme config")
    ingest.add_argument("--key", help="idempotency key (default: a new run each time)")
    ingest.add_argument("--forms", help="comma-separated SEC forms (default 10-K,10-Q,8-K)")
    ingest.add_argument("--limit", type=int, help="at most this many recent filings")
    ingest.add_argument(
        "--since",
        help="only filings accepted after this date (default: ATLAS_INGEST_LOOKBACK_DAYS ago)",
    )
    ingest.add_argument(
        "--all-history",
        action="store_true",
        help="no lookback: every filing SEC lists (costly: each one is LLM-extracted)",
    )
    ingest.add_argument("--max-attempts", type=int, default=3, help="retry bound (default 3)")
    ingest.add_argument(
        "--backfill",
        action="store_true",
        help="a backfill: it and the retains it enqueues are backfill class (the backfill"
        " window, if set, and the budgets' interactive reserve); a company's first one records"
        " an ingest plan",
    )
    ingest.add_argument(
        "--max-retains",
        type=int,
        help="retain at most N of the company's not-yet-retained versions, newest first"
        " (a rerun retains the next N)",
    )
    retention = commands.add_parser("retention", help="memory retention maintenance")
    retention_commands = retention.add_subparsers(dest="retention_command", required=True)
    retry = retention_commands.add_parser(
        "retry-failed",
        help="resubmit the failed sections of Source Versions in the window (default lookback)",
    )
    retry.add_argument("--since", help="only versions available after this date")
    retry.add_argument("--all-history", action="store_true", help="every failed section")
    retry.add_argument("--backfill", action="store_true", help="backfill class (see ingest)")
    triage = commands.add_parser("triage", help="retention triage maintenance")
    triage_commands = triage.add_subparsers(dest="triage_command", required=True)
    triage_retry = triage_commands.add_parser(
        "retry", help="re-enqueue a triage job that failed after its attempts"
    )
    triage_retry.add_argument("--source-version", help="the Source Version (UUID) to retry")
    triage_retry.add_argument(
        "--failed", action="store_true", help="every version whose latest triage job failed"
    )
    triage_audit = triage_commands.add_parser(
        "audit",
        help="measure what triage skips that a full reading would retain: sample skipped"
        " sections (seeded, stratified by form and length) and enqueue their judging"
        " (GET /api/v1/triage/audits)",
    )
    triage_audit.add_argument(
        "--sample", type=int, default=40, help="how many skipped sections (default 40)"
    )
    triage_audit.add_argument("--company", help="only this company's sections (slug)")
    triage_audit.add_argument(
        "--seed", type=int, default=1, help="the sampling seed: same seed, same sample"
    )
    triage_audit.add_argument("--backfill", action="store_true", help="backfill class")
    triage_audit.add_argument(
        "--wait", action="store_true", help="wait for the worker to finish, then print the summary"
    )
    triage_audit.add_argument(
        "--timeout", type=float, default=6 * 3600, help="how long --wait waits (seconds)"
    )
    triage_audit.add_argument(
        "--poll-seconds", type=float, default=5.0, help="how often --wait looks (seconds)"
    )
    ledger = commands.add_parser("ledger", help="source ledger maintenance")
    ledger_commands = ledger.add_subparsers(dest="ledger_command", required=True)
    ledger_commands.add_parser(
        "correct-availability",
        help="record availability corrections for versions an earlier rule dated too early",
    )
    ledger_commands.add_parser(
        "assign-families",
        help="put parsed Source Versions recorded before Evidence Families into their family",
    )
    reparse = ledger_commands.add_parser(
        "reparse",
        help="enqueue a re-parse, with the current parser, of the Source Versions recorded"
        " under an earlier one (a separate parse record; the recorded parse is kept)",
    )
    reparse.add_argument("--company", help="only this company's Source Versions (slug)")
    reparse.add_argument(
        "--parser-version",
        default=None,
        help="the parser to re-parse with; must be the current one (the default)",
    )
    reparse.add_argument("--key", help="the job's idempotency key (default: a timestamped one)")
    sources = commands.add_parser("sources", help="source material fetched outside Atlas")
    sources_commands = sources.add_subparsers(dest="sources_command", required=True)
    source_import = sources_commands.add_parser(
        "import",
        help="record a document the owner fetched by hand (e.g. from HKEXnews) in the ledger",
    )
    source_import.add_argument("--company", required=True, help="company slug from the config")
    source_import.add_argument("--file", required=True, type=Path, help="the downloaded file")
    source_import.add_argument(
        "--origin-url", required=True, help="the URL the file was downloaded from"
    )
    source_import.add_argument(
        "--published-at",
        required=True,
        help="the publisher's timestamp, with its offset (e.g. 2026-08-21T22:30+08:00)",
    )
    source_import.add_argument("--title", help="the document's title (default: the file name)")
    source_import.add_argument("--publisher", help="default: the origin site's publisher")
    source_import.add_argument("--media-type", help="default: from the file extension")
    companies = commands.add_parser("companies", help="the configured company universe")
    companies_commands = companies.add_subparsers(dest="companies_command", required=True)
    companies_commands.add_parser("seed", help="create or update companies from the config")
    resolve = companies_commands.add_parser(
        "resolve",
        help="resolve companies to their CIK, LEI and listings (SEC, GLEIF, OpenFIGI);"
        " exact and corroborated identifiers commit, the rest wait for review",
    )
    resolve.add_argument(
        "--company", action="append", dest="slugs", help="only this company (repeatable)"
    )
    tradingview = commands.add_parser(
        "tradingview",
        help="the owner-override TradingView source (off by default; docs/runbooks.md)",
    )
    tradingview_commands = tradingview.add_subparsers(dest="tradingview_command", required=True)
    tv_login = tradingview_commands.add_parser(
        "login",
        help="get Atlas its own OAuth token (authorization code + PKCE; sign in in a browser)",
    )
    tv_login.add_argument(
        "--print-tokens",
        action="store_true",
        help="print the tokens (for secrets) instead of writing ATLAS_TRADINGVIEW_TOKEN_FILE",
    )
    tv_login.add_argument(
        "--port", type=int, help="the loopback redirect port (default ATLAS_TRADINGVIEW_LOGIN_PORT)"
    )
    tv_login.add_argument(
        "--client-id", help="a registered OAuth client, when the server has no registration"
    )
    tv_login.add_argument(
        "--timeout", type=float, default=300.0, help="seconds to wait for the sign-in (300)"
    )
    tv_check = tradingview_commands.add_parser(
        "check", help="one catalog call for a symbol; prints counts only"
    )
    tv_check.add_argument("--symbol", required=True, help="e.g. NASDAQ:LITE")
    hindsight = commands.add_parser("hindsight", help="configure the research bank")
    hindsight_commands = hindsight.add_subparsers(dest="hindsight_command", required=True)
    apply = hindsight_commands.add_parser(
        "apply-template", help="dry-run, then import the bank template, and record its version"
    )
    apply.add_argument(
        "--template", type=Path, help="template file (default: ATLAS_HINDSIGHT_TEMPLATE_PATH)"
    )
    apply.add_argument(
        "--if-changed",
        action="store_true",
        help="skip when this exact template is already the bank's latest application",
    )
    evaluate = commands.add_parser(
        "evaluate",
        help="run the gold evaluation cases and store the results (GET /api/v1/evaluations)",
    )
    evaluate.add_argument(
        "--case", action="append", dest="cases", help="only this case ID (repeatable)"
    )
    evaluate.add_argument(
        "--live",
        action="store_true",
        help="ask the real model (ATLAS_LITELLM_URL) instead of the scripted answers; needs"
        " ATLAS_LIVE_TESTS=1 too, spends MiniMax quota, never in CI",
    )
    args = parser.parse_args(argv)

    configure_logging()
    settings = load_settings()
    for provider, setting in settings.disabled_providers():
        log.info(f"{provider} disabled: missing {setting}")
    if args.command == "api":
        run_api(settings)
    elif args.command == "migrate":
        from atlas.db.migrate import upgrade

        upgrade(settings.database_url)
        log.info("database migrated to head")
    elif args.command == "audit":
        raise SystemExit(run_audit_verify(settings))
    elif args.command == "hindsight":
        raise SystemExit(run_apply_template(settings, args.template, if_changed=args.if_changed))
    elif args.command == "tradingview" and args.tradingview_command == "login":
        raise SystemExit(
            run_tradingview_login(
                settings, args.print_tokens, args.port, args.client_id, args.timeout
            )
        )
    elif args.command == "tradingview":
        raise SystemExit(run_tradingview_check(settings, args.symbol))
    elif args.command == "jobs":
        enqueue_job(settings, args.kind, args.key, args.payload, args.max_attempts, args.backfill)
    elif args.command == "ingest":
        enqueue_ingest(
            settings,
            args.company,
            args.key,
            args.forms,
            args.limit,
            args.max_attempts,
            args.backfill,
            since=args.since,
            all_history=args.all_history,
            max_retains=args.max_retains,
        )
    elif args.command == "ledger" and args.ledger_command == "assign-families":
        run_assign_families(settings)
    elif args.command == "ledger" and args.ledger_command == "reparse":
        from atlas.parsing import PARSER_VERSION

        enqueue_reparse(settings, args.company, args.parser_version or PARSER_VERSION, args.key)
    elif args.command == "ledger":
        run_correct_availability(settings)
    elif args.command == "triage" and args.triage_command == "audit":
        raise SystemExit(
            run_triage_audit(
                settings,
                args.sample,
                args.company,
                args.seed,
                backfill=args.backfill,
                wait=args.wait,
                timeout=args.timeout,
                poll_seconds=args.poll_seconds,
            )
        )
    elif args.command == "triage":
        run_triage_retry(settings, args.source_version, args.failed)
    elif args.command == "retention":
        run_retry_failed(settings, args.since, args.all_history, args.backfill)
    elif args.command == "companies" and args.companies_command == "resolve":
        raise SystemExit(resolve_companies(settings, args.slugs))
    elif args.command == "sources":
        run_sources_import(
            settings,
            args.company,
            args.file,
            args.origin_url,
            args.published_at,
            args.title,
            args.publisher,
            args.media_type,
        )
    elif args.command == "companies":
        seed_companies(settings)
    elif args.command == "evaluate":
        raise SystemExit(run_evaluate(settings, args.cases, live=args.live))
    else:
        run_worker(settings, once=args.once)
