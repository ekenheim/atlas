"""`atlas` command: one image, run as `atlas api` or `atlas worker`."""

import argparse
import logging
import sys

from pydantic import ValidationError

from atlas.logs import configure_logging
from atlas.settings import Settings

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

    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError

    from atlas.jobs import JobQueue, Worker, builtin_registry

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    worker = Worker(
        JobQueue(engine),
        builtin_registry(),
        lease=timedelta(seconds=settings.job_lease_seconds),
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
    settings: Settings, kind: str, key: str, payload_json: str, max_attempts: int
) -> None:
    import json

    from pydantic import JsonValue, TypeAdapter
    from sqlalchemy import create_engine

    from atlas.jobs import JobQueue, builtin_registry

    kinds = builtin_registry().kinds()
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
    engine = create_engine(settings.database_url)
    try:
        enqueued = JobQueue(engine).enqueue(kind, key, payload, max_attempts=max_attempts)
    finally:
        engine.dispose()
    job = enqueued.job
    summary = {"id": str(job.id), "kind": job.kind, "idempotency_key": job.idempotency_key}
    print(json.dumps({**summary, "status": job.status, "created": enqueued.created}))


def run_audit_verify(settings: Settings) -> int:
    from sqlalchemy import create_engine

    from atlas.audit import verify_chain

    engine = create_engine(settings.database_url)
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
    elif args.command == "jobs":
        enqueue_job(settings, args.kind, args.key, args.payload, args.max_attempts)
    else:
        run_worker(settings, once=args.once)
