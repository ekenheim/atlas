from importlib.metadata import version
from pathlib import Path

from fastapi.testclient import TestClient

import atlas
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
    assert f'atlas_build_info{{version="{version("atlas-research")}"}} 1.0' in response.text


def test_build_info_reports_the_release_version_the_image_was_stamped_with(tmp_path: Path) -> None:
    client = TestClient(create_app(make_settings(tmp_path / "archive", version="1.4.2")))

    response = client.get("/metrics")

    assert 'atlas_build_info{version="1.4.2"} 1.0' in response.text


def test_the_package_version_is_the_installed_distribution_version() -> None:
    assert atlas.__version__ == version("atlas-research")


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
