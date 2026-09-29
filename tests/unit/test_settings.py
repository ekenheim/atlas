from pathlib import Path

import pytest
from pydantic import ValidationError

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


def test_archive_backend_defaults_to_the_filesystem(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {"database_url": "postgresql+psycopg://x@db/atlas", "actor": "a", "archive_root": tmp_path}
    )

    assert settings.archive_backend == "filesystem"


def test_s3_secret_is_never_rendered_by_the_settings(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {
            "database_url": "postgresql+psycopg://x@db/atlas",
            "actor": "a",
            "archive_root": tmp_path,
            "archive_backend": "s3",
            "s3_endpoint_url": "http://s3.internal:9000",
            "s3_bucket": "atlas-archive",
            "s3_access_key_id": "atlas",
            "s3_secret_access_key": "do-not-print-this-secret\r",
        }
    )

    assert "do-not-print-this-secret" not in repr(settings)
    assert "do-not-print-this-secret" not in str(settings.model_dump())
    assert settings.s3_secret_access_key is not None
    assert settings.s3_secret_access_key.get_secret_value() == "do-not-print-this-secret"


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


def required_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.setenv("ATLAS_DATABASE_URL", "postgresql+psycopg://atlas:atlas@db/atlas")
    monkeypatch.setenv("ATLAS_ACTOR", "local-researcher")
    monkeypatch.setenv("ATLAS_ARCHIVE_ROOT", "/data/archive")


def test_live_sec_is_off_by_default_and_reported_as_a_disabled_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    required_env(monkeypatch, tmp_path)

    settings = Settings()  # pyright: ignore[reportCallIssue]

    assert settings.sec_live is False
    assert ("sec", "ATLAS_SEC_LIVE") in settings.disabled_providers()


def test_live_sec_requires_a_user_agent_with_a_contact_email(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    required_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ATLAS_SEC_LIVE", "true")

    with pytest.raises(ValidationError, match="sec_user_agent"):
        Settings()  # pyright: ignore[reportCallIssue]

    monkeypatch.setenv("ATLAS_SEC_USER_AGENT", "Atlas Research")
    with pytest.raises(ValidationError, match="contact email"):
        Settings()  # pyright: ignore[reportCallIssue]

    monkeypatch.setenv("ATLAS_SEC_USER_AGENT", "Atlas Research ops@example.com\r")
    settings = Settings()  # pyright: ignore[reportCallIssue]
    assert settings.sec_user_agent == "Atlas Research ops@example.com"
    assert "sec" not in {provider for provider, _ in settings.disabled_providers()}


def _base(tmp_path: Path) -> dict[str, object]:
    return {
        "database_url": "postgresql+psycopg://x@db/atlas",
        "actor": "a",
        "archive_root": tmp_path,
    }


def test_the_backfill_window_defaults_to_one_to_seven_utc(tmp_path: Path) -> None:
    settings = Settings.model_validate(_base(tmp_path))

    assert (settings.backfill_window, settings.backfill_timezone) == ("01:00-07:00", "UTC")
    assert (settings.queue_pause_base_seconds, settings.queue_pause_max_seconds) == (60, 3600)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"backfill_window": "1-7"}, "HH:MM-HH:MM"),
        ({"backfill_window": "25:00-07:00"}, "not a time of day"),
        ({"backfill_window": "03:00-03:00"}, "is empty"),
        ({"backfill_timezone": "Mars/Olympus"}, "unknown timezone"),
        ({"queue_pause_max_seconds": 7200}, "less than or equal to 3600"),
        ({"queue_pause_base_seconds": 600, "queue_pause_max_seconds": 300}, "must not exceed"),
    ],
)
def test_invalid_pacing_settings_are_rejected_at_startup(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings.model_validate(_base(tmp_path) | overrides)


def test_an_empty_backfill_window_is_accepted(tmp_path: Path) -> None:
    settings = Settings.model_validate(_base(tmp_path) | {"backfill_window": ""})

    assert settings.backfill_window == ""
