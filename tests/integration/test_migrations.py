import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text


def test_migrate_upgrades_an_empty_database_to_head(
    empty_database_url: str, tmp_path: Path
) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "ATLAS_DATABASE_URL": empty_database_url,
        "ATLAS_ACTOR": "local-researcher",
        "ATLAS_ARCHIVE_ROOT": str(archive),
    }

    result = subprocess.run(
        [sys.executable, "-m", "atlas", "migrate"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    engine = create_engine(empty_database_url)
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    engine.dispose()
    assert revision == "0005"
