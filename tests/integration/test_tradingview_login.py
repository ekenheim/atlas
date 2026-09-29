"""`atlas tradingview login` and `atlas tradingview check` (ticket 31): Atlas gets its own
OAuth token through the MCP authorization flow, and one catalog call verifies access.

Seam: the `atlas` CLI as a subprocess, against the TradingView fake (its MCP server and
OAuth authorization server, `tests/fakes/tradingview.py`) served on localhost. The test
plays the owner's browser: it reads the printed authorization URL, approves it at the fake
and visits the loopback callback. Nothing live is called.
"""

import json
import os
import stat
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest

from tests.fakes.serve import Served, serve
from tests.fakes.tradingview import CLIENT_ID, FakeTradingView
from tests.harness import THEMES, UNREACHABLE_DATABASE_URL


@pytest.fixture
def tradingview() -> Iterator[tuple[FakeTradingView, Served]]:
    fake = FakeTradingView()
    with serve(fake.handle) as served:
        yield fake, served
        served.raise_errors()


def environment(tmp_path: Path, served: Served, **extra: str) -> dict[str, str]:
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "ATLAS_DATABASE_URL": UNREACHABLE_DATABASE_URL,
        "ATLAS_ACTOR": "local-researcher",
        "ATLAS_ARCHIVE_ROOT": str(tmp_path / "archive"),
        "ATLAS_THEMES_CONFIG": str(THEMES),
        "ATLAS_TRADINGVIEW_ENABLED": "true",
        "ATLAS_TRADINGVIEW_MCP_URL": f"{served.url}/mcp",
        "ATLAS_TRADINGVIEW_RATE_PER_S": "1",
        **extra,
    }


def login(tmp_path: Path, served: Served, fake: FakeTradingView, *args: str) -> tuple[str, str]:
    """Run the login, approve the printed URL like a browser; (stdout, stderr)."""
    process = subprocess.Popen(
        [sys.executable, "-m", "atlas", "tradingview", "login", "--timeout", "60", *args],
        cwd=tmp_path,
        env=environment(tmp_path, served),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stderr is not None
    seen: list[str] = []
    try:
        for line in process.stderr:
            seen.append(line)
            if line.startswith(f"{served.url}/auth/authorize?"):
                callback = fake.authorize(line.strip())
                assert httpx2.get(callback, timeout=10).status_code == 200
                break
        stdout, stderr = process.communicate(timeout=60)
    finally:
        process.kill()
    assert process.returncode == 0, "".join(seen) + stderr
    return stdout, "".join(seen) + stderr


def test_login_registers_a_client_runs_pkce_and_writes_the_token_file(
    tmp_path: Path, tradingview: tuple[FakeTradingView, Served]
) -> None:
    fake, served = tradingview

    stdout, stderr = login(tmp_path, served, fake)

    # Discovery: the 401 challenge, then the metadata it points at.
    assert [c.url.path for c in fake.calls[:3]] == [
        "/mcp",
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-authorization-server/auth",
    ]
    [registration] = fake.registrations
    redirect = registration["redirect_uris"][0]
    assert redirect.startswith("http://127.0.0.1:") and redirect.endswith("/callback")
    assert registration["token_endpoint_auth_method"] == "none"
    assert registration["grant_types"] == ["authorization_code", "refresh_token"]
    [exchange] = fake.token_requests
    assert exchange["grant_type"] == "authorization_code"
    assert exchange["client_id"] == CLIENT_ID
    assert exchange["resource"] == f"{served.url}/mcp"
    assert len(exchange["code_verifier"]) >= 43
    # The tokens went to the token file, readable by the owner only, and were never printed.
    token_file = tmp_path / ".atlas" / "tradingview-token.json"
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    stored = json.loads(token_file.read_text())
    assert (stored["access_token"], stored["refresh_token"]) == (
        "fake-access-token-2",
        "fake-refresh-token-2",
    )
    assert stored["token_endpoint"] == f"{served.url}/auth/token"
    assert stored["client_id"] == CLIENT_ID
    summary = json.loads(stdout)
    assert summary["token_file"] == ".atlas/tradingview-token.json"
    assert summary["refreshable"] is True
    for secret in ("fake-access-token-2", "fake-refresh-token-2", "fake-code-1"):
        assert secret not in stdout + stderr


def test_the_authorization_url_carries_pkce_state_and_the_resource(
    tmp_path: Path, tradingview: tuple[FakeTradingView, Served]
) -> None:
    fake, served = tradingview
    urls: list[str] = []
    original = fake.authorize

    def recording(url: str) -> str:
        urls.append(url)
        return original(url)

    fake.authorize = recording  # type: ignore[method-assign]

    login(tmp_path, served, fake)

    query = {k: v[0] for k, v in parse_qs(urlsplit(urls[0]).query).items()}
    assert query["client_id"] == CLIENT_ID
    assert query["code_challenge_method"] == "S256"
    assert query["resource"] == f"{served.url}/mcp"
    assert query["scope"] == "mcp"
    assert len(query["state"]) >= 32


def test_print_tokens_prints_them_for_secrets_and_writes_no_file(
    tmp_path: Path, tradingview: tuple[FakeTradingView, Served]
) -> None:
    fake, served = tradingview

    stdout, _ = login(tmp_path, served, fake, "--print-tokens")

    printed = json.loads(stdout)
    assert printed["ATLAS_TRADINGVIEW_ACCESS_TOKEN"] == "fake-access-token-2"
    assert printed["ATLAS_TRADINGVIEW_REFRESH_TOKEN"] == "fake-refresh-token-2"
    assert printed["ATLAS_TRADINGVIEW_TOKEN_URL"] == f"{served.url}/auth/token"
    assert printed["ATLAS_TRADINGVIEW_CLIENT_ID"] == CLIENT_ID
    assert not (tmp_path / ".atlas").exists()


def test_check_makes_one_catalog_call_and_prints_counts_only(
    tmp_path: Path, tradingview: tuple[FakeTradingView, Served]
) -> None:
    fake, served = tradingview
    login(tmp_path, served, fake)
    fake.calls.clear()

    checked = subprocess.run(
        [sys.executable, "-m", "atlas", "tradingview", "check", "--symbol", "NASDAQ:LITE"],
        cwd=tmp_path,
        env=environment(tmp_path, served),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout) == {
        "symbol": "NASDAQ:LITE",
        "documents": 3,
        "total": 3,
        "categories": {"Annual report": 1, "Earnings call": 2},
        "transcript_views": 2,
        "tool_calls": 1,
    }
    assert "SYNTHETIC" not in checked.stdout + checked.stderr  # no content
    assert [name for name, _ in fake.tool_calls] == ["mcp-tv-get-documents"]


def test_while_off_neither_command_calls_tradingview(
    tmp_path: Path, tradingview: tuple[FakeTradingView, Served]
) -> None:
    fake, served = tradingview
    env = environment(tmp_path, served, ATLAS_TRADINGVIEW_ENABLED="false")

    for command in (["login", "--timeout", "1"], ["check", "--symbol", "NASDAQ:LITE"]):
        result = subprocess.run(
            [sys.executable, "-m", "atlas", "tradingview", *command],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 1
        assert "ATLAS_TRADINGVIEW_ENABLED=false" in result.stderr

    assert fake.calls == []
