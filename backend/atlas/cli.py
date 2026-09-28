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
            field = str(issue["loc"][0]) if issue["loc"] else "?"
            name = f"ATLAS_{field.upper()}"
            if issue["type"] == "missing":
                lines.append(f"  - {name} is required but not set")
            else:
                lines.append(f"  - {name}: {issue['msg']}")
        print("\n".join(lines), file=sys.stderr)
        raise SystemExit(2) from None


def run_api(settings: Settings) -> None:
    import uvicorn

    from atlas.api.app import create_app

    uvicorn.run(create_app(settings), host="0.0.0.0", port=8000)  # noqa: S104 - container port


def run_worker(settings: Settings, once: bool) -> None:
    # The job queue arrives with ticket 04; until then there is never any work.
    log.info("worker idle: no work available")
    if not once:
        raise SystemExit("atlas worker: continuous mode needs the job queue (ticket 04)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="atlas")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("api", help="serve the HTTP API and the static frontend")
    commands.add_parser("migrate", help="upgrade the database schema to the latest revision")
    worker = commands.add_parser("worker", help="run background jobs")
    worker.add_argument("--once", action="store_true", help="process available work, then exit")
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
    else:
        run_worker(settings, once=args.once)
