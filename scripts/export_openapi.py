"""Write the API's OpenAPI schema as JSON, the input to the frontend's typed client.

    uv run python scripts/export_openapi.py frontend/lib/api/openapi.json

The app is built with placeholder settings: building it opens no connection, and the
schema depends only on the routes. `scripts/gen_api_client.sh` runs this and then
`openapi-typescript`; CI runs it with `--check` to fail on a stale client.
"""

import json
import sys
import tempfile
from pathlib import Path

from atlas.api.app import create_app
from atlas.settings import Settings


def openapi_json() -> str:
    with tempfile.TemporaryDirectory() as archive_root:
        settings = Settings.model_validate(
            {
                "database_url": "postgresql+psycopg://schema-export@127.0.0.1/unused",
                "actor": "schema-export",
                "archive_root": Path(archive_root),
            }
        )
        schema = create_app(settings).openapi()
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: export_openapi.py OUTPUT.json")
    Path(sys.argv[1]).write_text(openapi_json(), encoding="utf-8")


if __name__ == "__main__":
    main()
