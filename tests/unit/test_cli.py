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


def test_worker_once_exits_cleanly_and_reports_each_disabled_provider_once(tmp_path: Path) -> None:
    result = run_atlas(["worker", "--once"], cwd=tmp_path, env=valid_env(tmp_path))

    assert result.returncode == 0, result.stderr
    for provider, setting in [
        ("hindsight", "ATLAS_HINDSIGHT_URL"),
        ("litellm", "ATLAS_LITELLM_URL"),
    ]:
        assert result.stderr.count(f"{provider} disabled: missing {setting}") == 1
