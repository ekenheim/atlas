"""Live tests call real external services. They are excluded by default (`-m 'not live'`)
and never run in CI; run them explicitly, e.g. `uv run pytest -m live tests/live`."""

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/live/" in item.nodeid:
            item.add_marker(pytest.mark.live)
            item.add_marker(pytest.mark.enable_socket)
