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
        from atlas.companies import extend_universe

        engine = create_engine(settings)
        try:
            with engine.connect() as connection:
                universe = extend_universe(connection, universe)
        finally:
            engine.dispose()
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
    elif args.command == "ledger":
        run_correct_availability(settings)
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
    else:
        run_worker(settings, once=args.once)
