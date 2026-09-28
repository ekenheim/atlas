from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import create_app
from atlas.settings import Settings


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://atlas:atlas@127.0.0.1:1/atlas",
        "actor": "local-researcher",
        "archive_root": tmp_path / "archive",
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_liveness_reports_ok_without_touching_dependencies(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path)))

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
