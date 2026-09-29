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


def test_backfill_runs_at_any_time_by_default_under_five_hour_budgets(tmp_path: Path) -> None:
    settings = Settings.model_validate(_base(tmp_path))

    assert (settings.backfill_window, settings.backfill_timezone) == ("", "UTC")
    assert (settings.queue_pause_base_seconds, settings.queue_pause_max_seconds) == (60, 3600)
    assert settings.budget_window_hours == 5
    assert (settings.codex_budget_operations, settings.minimax_budget_tokens) == (40, 400_000)
    assert settings.budget_interactive_reserve == 0.3


def test_the_backfill_window_accepts_several_ranges(tmp_path: Path) -> None:
    window = "01:00-07:00, 13:00-15:00,22:30-23:00"

    settings = Settings.model_validate(_base(tmp_path) | {"backfill_window": window})

    assert settings.backfill_window == window


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"backfill_window": "1-7"}, "HH:MM-HH:MM"),
        ({"backfill_window": "25:00-07:00"}, "not a time of day"),
        ({"backfill_window": "03:00-03:00"}, "is empty"),
        ({"backfill_window": "01:00-07:00,13:00"}, "HH:MM-HH:MM"),
        ({"backfill_window": "01:00-07:00,,13:00-15:00"}, "HH:MM-HH:MM"),
        ({"budget_window_hours": 0}, "greater than 0"),
        ({"codex_budget_operations": 0}, "greater than or equal to 1"),
        ({"minimax_budget_tokens": 0}, "greater than or equal to 1"),
        ({"budget_interactive_reserve": 1}, "less than 1"),
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


def test_mental_models_refresh_daily_at_six_thirty_utc_by_default(tmp_path: Path) -> None:
    assert Settings.model_validate(_base(tmp_path)).mental_model_refresh_at == "06:30"
    off = Settings.model_validate(_base(tmp_path) | {"mental_model_refresh_at": ""})
    assert off.mental_model_refresh_at == ""


@pytest.mark.parametrize("value", ["6:30", "24:00", "06:60", "06:30-07:00"])
def test_an_invalid_mental_model_refresh_time_is_rejected_at_startup(
    tmp_path: Path, value: str
) -> None:
    with pytest.raises(ValidationError, match="mental_model_refresh_at"):
        Settings.model_validate(_base(tmp_path) | {"mental_model_refresh_at": value})


def test_the_exchange_user_agent_is_generic_and_never_carries_personal_data(
    tmp_path: Path,
) -> None:
    # Owner decision 2026-09-29: non-SEC sources get no email (SEC's contact rule is SEC's).
    base = {
        "database_url": "postgresql+psycopg://x@db/atlas",
        "actor": "a",
        "archive_root": tmp_path,
    }
    settings = Settings.model_validate(base)
    assert settings.exchange_user_agent == "AtlasResearch"
    with pytest.raises(ValidationError, match="personal data"):
        Settings.model_validate({**base, "exchange_user_agent": "Atlas me@example.com"})
