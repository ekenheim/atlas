import os
from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import create_app
from atlas.settings import Settings

DATABASE_URL = os.environ.get(
    "ATLAS_TEST_DATABASE_URL", "postgresql+psycopg://atlas:atlas@127.0.0.1:55432/atlas"
)


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    archive = tmp_path / "archive"
    archive.mkdir(exist_ok=True)
    values: dict[str, object] = {
        "database_url": DATABASE_URL,
        "actor": "local-researcher",
        "archive_root": archive,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_ready_when_database_and_archive_are_available(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "database": "ok",
            "archive": "ok",
            "hindsight": "not_configured",
            "litellm": "not_configured",
        },
    }


def test_not_ready_when_database_is_unreachable(tmp_path: Path) -> None:
    unreachable = "postgresql+psycopg://atlas:atlas@127.0.0.1:1/atlas?connect_timeout=2"
    client = TestClient(create_app(make_settings(tmp_path, database_url=unreachable)))

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"]["database"] == "down"


def test_not_ready_when_archive_root_is_missing(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, archive_root=tmp_path / "does-not-exist")
    client = TestClient(create_app(settings))

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"] == {
        "database": "ok",
        "archive": "down",
        "hindsight": "not_configured",
        "litellm": "not_configured",
    }
