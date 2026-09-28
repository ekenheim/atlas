"""Run the frontend's Playwright smoke test against a live, freshly seeded Atlas.

    uv run python scripts/e2e.py

Needs the Compose Postgres (`docker compose up -d --wait postgres-app`) and the built
static export (`npm --prefix frontend run build`). In order, it:

1. installs Playwright's chromium (`--with-deps` when `CI` is set) and checks that it
   launches. If it can't, the test is skipped with a message locally, and fails in CI.
2. creates an empty database (`atlas_e2e_<hex>`) next to the test databases
   (`ATLAS_TEST_DATABASE_URL`) and, through the `atlas` CLI, migrates it, enqueues the
   Lumentum ingest and runs one worker pass against the recorded EDGAR fixtures
   (`tests/fixtures/edgar`), archiving into a temporary directory.
3. starts the API with uvicorn on a free localhost port, serving `frontend/out` on the
   same origin (`ATLAS_FRONTEND_DIR`), and runs `playwright test` against it.
4. stops the API and drops the database.
"""

# The commands run here are fixed (npm, node and the atlas CLI), never user input.
# ruff: noqa: S603, S607

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from atlas.api.app import create_app
from atlas.settings import Settings

REPO = Path(__file__).resolve().parents[1]
FRONTEND = REPO / "frontend"
STATIC_EXPORT = FRONTEND / "out"
THEMES = REPO / "configs" / "themes" / "ai-infrastructure.yaml"
EDGAR_FIXTURES = REPO / "tests" / "fixtures" / "edgar"
ADMIN_DATABASE_URL = os.environ.get(
    "ATLAS_TEST_DATABASE_URL", "postgresql+psycopg://atlas:atlas@127.0.0.1:55432/atlas"
)
# Host ports the Compose services and the dev API own; never bind them here.
RESERVED_PORTS = {55432, 59000, 58000, 58080}
IN_CI = bool(os.environ.get("CI"))


def main() -> int:
    if not (STATIC_EXPORT / "index.html").is_file():
        print(f"e2e: {STATIC_EXPORT} has no build; run `npm --prefix frontend run build`")
        return 1
    unavailable = browser_unavailable()
    if unavailable:
        if IN_CI:
            print(f"e2e: FAILED: the Playwright chromium browser is unavailable: {unavailable}")
            return 1
        print(
            "e2e: SKIPPED: the Playwright chromium browser is unavailable "
            f"({unavailable}). Install it with "
            "`npm --prefix frontend exec playwright install --with-deps chromium` and re-run; "
            "on a distro Playwright doesn't support, PLAYWRIGHT_HOST_PLATFORM_OVERRIDE="
            "ubuntu22.04-x64 may work."
        )
        return 0

    with tempfile.TemporaryDirectory(prefix="atlas-e2e-") as tmp, fresh_database() as url:
        workdir = Path(tmp)  # the CLI runs here, so no developer .env is picked up
        archive = workdir / "archive"
        archive.mkdir()
        seed(url, archive, workdir)
        settings = Settings.model_validate(
            {
                "database_url": url,
                "actor": "e2e-smoke",
                "archive_root": archive,
                "themes_config": THEMES,
                "frontend_dir": STATIC_EXPORT,
            }
        )
        with running_api(settings) as base_url:
            print(f"e2e: API and static export at {base_url}", flush=True)
            env = {**os.environ, "ATLAS_E2E_BASE_URL": base_url}
            return subprocess.run(npx("playwright", "test"), cwd=FRONTEND, env=env).returncode


def npx(*args: str) -> list[str]:
    return ["npm", "exec", "--no", "--", *args]


def browser_unavailable() -> str | None:
    """Why chromium can't be installed or launched, or None when it launches."""
    install = npx("playwright", "install", *(["--with-deps"] if IN_CI else []), "chromium")
    installed = subprocess.run(install, cwd=FRONTEND, capture_output=True, text=True)
    if installed.returncode != 0:
        return f"`playwright install` failed: {last_line(installed.stderr or installed.stdout)}"
    probe = "require('@playwright/test').chromium.launch().then((b) => b.close())"
    launched = subprocess.run(["node", "-e", probe], cwd=FRONTEND, capture_output=True, text=True)
    if launched.returncode != 0:
        return f"chromium does not launch: {last_line(launched.stderr)}"
    return None


def last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else "no output"


@contextmanager
def fresh_database() -> Generator[str]:
    name = f"atlas_e2e_{uuid.uuid4().hex[:12]}"
    admin = create_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(ADMIN_DATABASE_URL).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def seed(database_url: str, archive: Path, workdir: Path) -> None:
    """Migrate, then ingest Lumentum from the recorded EDGAR fixtures via the CLI."""
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(workdir),
        "ATLAS_DATABASE_URL": database_url,
        "ATLAS_ACTOR": "e2e-smoke",
        "ATLAS_ARCHIVE_ROOT": str(archive),
        "ATLAS_THEMES_CONFIG": str(THEMES),
        "ATLAS_SEC_FIXTURES_DIR": str(EDGAR_FIXTURES),
    }
    for args in (
        ["migrate"],
        ["ingest", "--company", "lumentum", "--key", "e2e-smoke"],
        ["worker", "--once"],
    ):
        done = subprocess.run(
            [sys.executable, "-m", "atlas", *args],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if done.returncode != 0:
            raise SystemExit(f"e2e: `atlas {' '.join(args)}` failed:\n{done.stderr}")


def free_port() -> int:
    while True:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port: int = probe.getsockname()[1]
        if port not in RESERVED_PORTS:
            return port


@contextmanager
def running_api(settings: Settings) -> Generator[str]:
    port = free_port()
    config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise SystemExit(f"e2e: the API did not start on port {port}")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    if shutil.which("npm") is None:
        raise SystemExit("e2e: npm is not on PATH")
    sys.exit(main())
