import os
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas.api.app import create_app
from atlas.settings import Settings
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import API_KEY as LITELLM_KEY
from tests.fakes.litellm import FakeLiteLLM
from tests.fakes.serve import serve
from tests.integration.conftest import (
    S3_ACCESS_KEY_ID,
    S3_ENDPOINT_URL,
    S3_SECRET_ACCESS_KEY,
    s3_settings,
    unique_bucket_name,
)

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


def test_ready_with_the_s3_archive_when_its_bucket_exists(tmp_path: Path, s3_bucket: str) -> None:
    client = TestClient(create_app(make_settings(tmp_path, **s3_settings(s3_bucket))))

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["archive"] == "ok"
    for leak in (s3_bucket, S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY):
        assert leak not in response.text


def test_s3_readiness_does_not_depend_on_the_archive_root(tmp_path: Path, s3_bucket: str) -> None:
    settings = make_settings(
        tmp_path, archive_root=tmp_path / "does-not-exist", **s3_settings(s3_bucket)
    )
    client = TestClient(create_app(settings))

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["archive"] == "ok"


def test_not_ready_when_the_s3_bucket_is_missing(tmp_path: Path) -> None:
    missing = unique_bucket_name("missing")
    client = TestClient(create_app(make_settings(tmp_path, **s3_settings(missing))))

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["archive"] == "down"
    assert missing not in response.text


def test_not_ready_when_the_s3_endpoint_is_unreachable(tmp_path: Path, s3_bucket: str) -> None:
    unreachable = {**s3_settings(s3_bucket), "s3_endpoint_url": "http://127.0.0.1:1"}
    client = TestClient(create_app(make_settings(tmp_path, **unreachable)))

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["archive"] == "down"


# --- Hindsight and LiteLLM: checked when configured ---------------------------------------------


@pytest.fixture
def hindsight_url() -> Iterator[str]:
    """The recorded Hindsight fake on localhost (its `/health` is a real 0.10.1 recording)."""
    fake = RecordedHindsight()
    with serve(fake.transport.handle_request) as served:
        yield served.url
    served.raise_errors()
    assert set(fake.served) <= {"monitoring/01-health"}


@contextmanager
def litellm(fake: FakeLiteLLM) -> Generator[str]:
    with serve(fake.handle) as served:
        yield served.url
    served.raise_errors()


def ready_with(tmp_path: Path, **overrides: object) -> tuple[int, dict[str, str]]:
    response = TestClient(create_app(make_settings(tmp_path, **overrides))).get("/health/ready")
    return response.status_code, response.json()["checks"]


def test_ready_when_hindsight_and_litellm_are_up(tmp_path: Path, hindsight_url: str) -> None:
    fake = FakeLiteLLM()
    with litellm(fake) as litellm_url:
        status, checks = ready_with(
            tmp_path,
            hindsight_url=hindsight_url,
            litellm_url=litellm_url,
            litellm_api_key=LITELLM_KEY,
        )

    assert status == 200
    assert checks == {"database": "ok", "archive": "ok", "hindsight": "ok", "litellm": "ok"}
    assert [(c.method, c.url.path) for c in fake.calls] == [("GET", "/model/info")]


def test_not_ready_when_hindsight_is_unreachable(tmp_path: Path) -> None:
    status, checks = ready_with(tmp_path, hindsight_url="http://127.0.0.1:1")

    assert status == 503
    assert checks["hindsight"] == "down"
    assert checks["litellm"] == "not_configured"


def test_not_ready_when_litellm_is_unreachable(tmp_path: Path, hindsight_url: str) -> None:
    status, checks = ready_with(
        tmp_path,
        hindsight_url=hindsight_url,
        litellm_url="http://127.0.0.1:1",
        litellm_api_key=LITELLM_KEY,
    )

    assert status == 503
    assert (checks["hindsight"], checks["litellm"]) == ("ok", "down")


def test_not_ready_when_litellm_rejects_the_key(tmp_path: Path) -> None:
    with litellm(FakeLiteLLM()) as litellm_url:
        status, checks = ready_with(tmp_path, litellm_url=litellm_url, litellm_api_key="sk-other")

    assert status == 503
    assert checks["litellm"] == "down"


def test_not_ready_when_an_alias_atlas_uses_has_no_route(tmp_path: Path) -> None:
    with litellm(FakeLiteLLM().without("atlas-reflect")) as litellm_url:
        status, checks = ready_with(tmp_path, litellm_url=litellm_url, litellm_api_key=LITELLM_KEY)

    assert status == 503
    assert checks["litellm"] == "down"


def test_litellm_without_its_key_is_not_configured(tmp_path: Path) -> None:
    status, checks = ready_with(tmp_path, litellm_url="http://127.0.0.1:1")

    assert status == 200
    assert checks["litellm"] == "not_configured"
