from pathlib import Path

from fastapi.testclient import TestClient

from atlas.api.app import create_app
from tests.harness import make_settings


def test_liveness_reports_ok_without_touching_dependencies(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path / "archive")))

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_are_exposed_in_prometheus_text_format(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path / "archive")))

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'atlas_build_info{version="0.1.0"} 1.0' in response.text


def test_static_frontend_is_served_alongside_the_api(tmp_path: Path) -> None:
    dist = tmp_path / "frontend"
    dist.mkdir()
    (dist / "index.html").write_text('<html><body><div id="atlas-root"></div></body></html>')
    client = TestClient(create_app(make_settings(tmp_path / "archive", frontend_dir=dist)))

    page = client.get("/")
    api = client.get("/health/live")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert 'id="atlas-root"' in page.text
    assert api.json() == {"status": "ok"}
