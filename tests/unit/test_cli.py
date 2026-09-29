import os
import subprocess
import sys
from pathlib import Path


def run_atlas(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    base = {"PATH": os.environ["PATH"], "HOME": str(cwd)}
    return subprocess.run(
        [sys.executable, "-m", "atlas", *args],
        cwd=cwd,
        env={**base, **env},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_missing_required_settings_fail_fast_with_actionable_names(tmp_path: Path) -> None:
    result = run_atlas(["api"], cwd=tmp_path, env={})

    assert result.returncode == 2
    for name in ("ATLAS_DATABASE_URL", "ATLAS_ACTOR", "ATLAS_ARCHIVE_ROOT"):
        assert name in result.stderr
    assert "Traceback" not in result.stderr


def valid_env(tmp_path: Path) -> dict[str, str]:
    archive = tmp_path / "archive"
    archive.mkdir(exist_ok=True)
    return {
        "ATLAS_DATABASE_URL": "postgresql+psycopg://atlas:atlas@127.0.0.1:1/atlas",
        "ATLAS_ACTOR": "local-researcher",
        "ATLAS_ARCHIVE_ROOT": str(archive),
    }


S3_SETTINGS = (
    "ATLAS_S3_ENDPOINT_URL",
    "ATLAS_S3_BUCKET",
    "ATLAS_S3_ACCESS_KEY_ID",
    "ATLAS_S3_SECRET_ACCESS_KEY",
)


def test_s3_archive_without_its_settings_fails_fast_naming_each_one(tmp_path: Path) -> None:
    env = {**valid_env(tmp_path), "ATLAS_ARCHIVE_BACKEND": "s3"}

    result = run_atlas(["api"], cwd=tmp_path, env=env)

    assert result.returncode == 2
    for name in S3_SETTINGS:
        assert name in result.stderr
    assert "ATLAS_?" not in result.stderr
    assert "Traceback" not in result.stderr


def test_s3_settings_error_names_only_what_is_missing_and_never_the_secret(tmp_path: Path) -> None:
    env = {
        **valid_env(tmp_path),
        "ATLAS_ARCHIVE_BACKEND": "s3",
        "ATLAS_S3_ENDPOINT_URL": "http://127.0.0.1:1",
        "ATLAS_S3_ACCESS_KEY_ID": "atlas",
        "ATLAS_S3_SECRET_ACCESS_KEY": "do-not-print-this-secret",
    }

    result = run_atlas(["api"], cwd=tmp_path, env=env)

    assert result.returncode == 2
    assert "ATLAS_S3_BUCKET" in result.stderr
    assert "ATLAS_S3_ENDPOINT_URL" not in result.stderr
    assert "do-not-print-this-secret" not in result.stderr


def test_unknown_archive_backend_is_rejected_with_its_setting_name(tmp_path: Path) -> None:
    env = {**valid_env(tmp_path), "ATLAS_ARCHIVE_BACKEND": "gcs"}

    result = run_atlas(["api"], cwd=tmp_path, env=env)

    assert result.returncode == 2
    assert "ATLAS_ARCHIVE_BACKEND" in result.stderr
    assert "filesystem" in result.stderr and "s3" in result.stderr


def test_worker_reports_each_disabled_provider_once_and_fails_cleanly_without_a_database(
    tmp_path: Path,
) -> None:
    result = run_atlas(["worker", "--once"], cwd=tmp_path, env=valid_env(tmp_path))

    assert result.returncode == 1
    assert "database unavailable" in result.stderr
    assert "Traceback" not in result.stderr
    for provider, setting in [
        ("hindsight", "ATLAS_HINDSIGHT_URL"),
        ("litellm", "ATLAS_LITELLM_URL"),
        ("sec", "ATLAS_SEC_LIVE"),
        ("searxng", "ATLAS_SEARXNG_URL"),
        ("tradingview", "ATLAS_TRADINGVIEW_ENABLED"),
    ]:
        assert result.stderr.count(f"{provider} disabled: missing {setting}") == 1


def test_a_blank_actor_is_refused_at_startup(tmp_path: Path) -> None:
    env = {**valid_env(tmp_path), "ATLAS_ACTOR": "  "}

    result = run_atlas(["worker", "--once"], cwd=tmp_path, env=env)

    assert result.returncode == 2
    assert "ATLAS_ACTOR" in result.stderr


def test_live_sec_without_a_user_agent_fails_fast_naming_the_setting(tmp_path: Path) -> None:
    env = {**valid_env(tmp_path), "ATLAS_SEC_LIVE": "true"}

    result = run_atlas(["worker", "--once"], cwd=tmp_path, env=env)

    assert result.returncode == 2
    assert "ATLAS_SEC_USER_AGENT" in result.stderr
    assert "Traceback" not in result.stderr
