from pathlib import Path

import pytest

from atlas.settings import Settings


def test_crlf_env_file_values_are_loaded_without_trailing_whitespace(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_bytes(
        b"ATLAS_DATABASE_URL=postgresql+psycopg://atlas:atlas@127.0.0.1:55432/atlas\r\n"
        b"ATLAS_ACTOR=local-researcher \r\n"
        b"ATLAS_ARCHIVE_ROOT=/data/archive\r\n"
        b"ATLAS_LITELLM_URL=https://litellm.example\r\n"
    )

    settings = Settings(_env_file=env_file)  # pyright: ignore[reportCallIssue]

    assert settings.database_url == "postgresql+psycopg://atlas:atlas@127.0.0.1:55432/atlas"
    assert settings.actor == "local-researcher"
    assert settings.archive_root == Path("/data/archive")
    assert settings.litellm_url == "https://litellm.example"


def test_environment_values_with_carriage_returns_are_stripped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.setenv("ATLAS_DATABASE_URL", "postgresql+psycopg://atlas:atlas@db/atlas\r")
    monkeypatch.setenv("ATLAS_ACTOR", "local-researcher\r")
    monkeypatch.setenv("ATLAS_ARCHIVE_ROOT", "/data/archive\r")

    settings = Settings()  # pyright: ignore[reportCallIssue]

    assert settings.database_url == "postgresql+psycopg://atlas:atlas@db/atlas"
    assert settings.actor == "local-researcher"
    assert settings.archive_root == Path("/data/archive")
