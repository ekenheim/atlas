"""Integration tests run against the Compose services; network is limited to localhost."""

import pytest

LOCAL_HOSTS = ["127.0.0.1", "localhost", "::1"]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration/" in item.nodeid:
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.enable_socket)
            item.add_marker(pytest.mark.allow_hosts(LOCAL_HOSTS))
