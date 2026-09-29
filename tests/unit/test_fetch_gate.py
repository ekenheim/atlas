"""The fetch gate (Phase 3-6a ticket 04): the site register, the terms decision and
robots.txt (RFC 9309), decided before any request, at the transport boundary.

Seam: `GatedHttpClient.get` over a `SecHttpClient` whose transport serves the fixture
robots files in `tests/fixtures/robots/` and records every request. Expected verdicts come
from RFC 9309 and the fixture files, not from the matcher.
"""

import asyncio
import hashlib
import math
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
import pytest

from atlas.sources import FetchError, SecHttpClient, TokenBucket
from atlas.sources.gate import (
    FetchBlocked,
    FetchGate,
    GateDecision,
    GatedHttpClient,
    SiteRegister,
    SiteRegisterError,
    load_site_register,
)

REPO = Path(__file__).parents[2]
ROBOTS = REPO / "tests" / "fixtures" / "robots"
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
UA = "AtlasResearch tests@example.invalid"

type Route = tuple[int, bytes]
REQUESTED = "requested"


class Site:
    """A fake web: URL -> (status, body); every request is recorded."""

    def __init__(self, routes: dict[str, Route]) -> None:
        self.routes = routes
        self.requests: list[str] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(str(request.url))
        status, body = self.routes.get(str(request.url), (404, b"not found"))
        return httpx2.Response(status, content=body, headers={"Content-Type": "text/plain"})


def register(**sites: dict[str, Any]) -> SiteRegister:
    base: dict[str, Any] = {
        "publisher": "Example",
        "terms_url": "https://example.test/terms",
        "terms_checked_on": "2026-09-29",
        "terms_note": "automated access permitted",
    }
    return SiteRegister.model_validate(
        {"version": 1, "sites": {name: base | site for name, site in sites.items()}}
    )


ALLOWED_SITES = register(
    ir={"hosts": ["ir.zj-innolight.com"], "automation": "allowed"},
    www={"hosts": ["www.zj-innolight.com"], "automation": "allowed"},
    rules={"hosts": ["rules.example.test"], "automation": "allowed"},
)


def robots(name: str) -> Route:
    return 200, (ROBOTS / name).read_bytes()


def gated(
    routes: dict[str, Route], sites: SiteRegister = ALLOWED_SITES, token: str | None = None
) -> tuple[Callable[[str], Any], Site]:
    """A `get(url)` through the gate: the blocking decision, or REQUESTED once the request
    was made (whatever the fake answered)."""
    site = Site(routes)

    async def no_sleep(_: float) -> None:
        return None

    async def get(url: str) -> Any:
        async with SecHttpClient(
            UA,
            transport=httpx2.MockTransport(site.handle),
            limiter=TokenBucket(rate_per_s=math.inf),
            sleep=no_sleep,
            max_attempts=2,
        ) as client:
            kwargs: dict[str, Any] = {} if token is None else {"token": token}
            gate = FetchGate(sites, client, now=lambda: NOW, **kwargs)
            try:
                await GatedHttpClient(client, gate).get(url)
            except FetchBlocked as blocked:
                return blocked.decision
            except FetchError:
                pass  # allowed, requested, and the fake answered an error
            assert url in site.requests
            return REQUESTED

    return lambda url: asyncio.run(get(url)), site


# --- Innolight's own IR site: never fetched ---


def test_a_robots_file_disallowing_everything_blocks_every_page_and_only_robots_is_read() -> None:
    get, site = gated({"https://ir.zj-innolight.com/robots.txt": robots("ir-disallow-all.txt")})

    for url in (
        "https://ir.zj-innolight.com/",
        "https://ir.zj-innolight.com/en/investor/announcements",
        "https://ir.zj-innolight.com/uploads/2026/interim.pdf",
    ):
        decision = get(url)
        assert isinstance(decision, GateDecision)
        assert decision.status == "blocked"
        assert decision.blocked_by == "robots"
        assert decision.robots is not None
        assert decision.robots.rule == "Disallow: / (line 3)"
        assert decision.robots.status == 200

    assert set(site.requests) == {"https://ir.zj-innolight.com/robots.txt"}


def test_a_disallowed_directory_blocks_only_its_paths() -> None:
    get, site = gated(
        {"https://www.zj-innolight.com/robots.txt": robots("www-disallow-uploads.txt")}
    )

    pdf = get("https://www.zj-innolight.com/uploads/ir/annual-report-2025.pdf")
    page = get("https://www.zj-innolight.com/en/about")

    assert isinstance(pdf, GateDecision) and pdf.blocked_by == "robots"
    assert page == REQUESTED
    assert "https://www.zj-innolight.com/uploads/ir/annual-report-2025.pdf" not in site.requests


def test_the_real_register_blocks_innolights_ir_site_and_hkexnews_without_any_request() -> None:
    sites = load_site_register(REPO / "configs" / "sources" / "sites.yaml")
    get, site = gated({}, sites)

    ir = get("https://ir.zj-innolight.com/")
    search = get("https://www1.hkexnews.hk/search/titleSearchServlet.do?stockId=1000311764")

    assert isinstance(ir, GateDecision) and ir.blocked_by == "terms"
    assert ir.reason == "zj-innolight's terms have not been checked"
    assert isinstance(search, GateDecision) and search.blocked_by == "terms"
    assert search.reason == (
        "blocked: HKEX Terms of Use prohibit automated access"
        " (IIS licence or written consent required)"
    )
    assert search.terms is not None and search.terms.automation == "forbidden"
    assert site.requests == []


# --- RFC 9309 matching ---


@pytest.mark.parametrize(
    ("path", "allowed", "rule"),
    [
        ("/reports/q2.pdf", False, "Disallow: /reports/ (line 9)"),
        ("/reports/annual/2026.pdf", True, "Allow: /reports/annual/ (line 10)"),  # longest wins
        ("/tie", True, "Allow: /tie (line 12)"),  # equal length: allow wins
        ("/data/sheet.xls", False, "Disallow: /*.xls$ (line 13)"),
        ("/data/sheet.xlsx", True, None),  # `$` anchors the end
        ("/search?lang=en&q=laser", False, "Disallow: /search?*q= (line 14)"),
        ("/search?lang=en", True, None),
        ("/caf%c3%a9/menu", False, "Disallow: /caf%C3%A9/ (line 15)"),  # encoding normalized
        ("/private/notes", False, "Disallow: /private (line 20)"),  # groups for us merge
        ("/privateer", False, "Disallow: /private (line 20)"),  # a prefix, not a directory
        ("/news", True, None),  # our group has no rule: `*`'s Disallow: / doesn't apply
        ("/before-any-group", True, None),
        ("/robots.txt", True, None),
    ],
)
def test_rules_are_matched_as_rfc_9309_says(path: str, allowed: bool, rule: str | None) -> None:
    get, _ = gated({"https://rules.example.test/robots.txt": robots("rules.txt")})

    result = get(f"https://rules.example.test{path}")

    if allowed:
        assert result == REQUESTED
    else:
        assert isinstance(result, GateDecision) and result.blocked_by == "robots"
        assert result.robots is not None and result.robots.rule == rule
        assert result.robots.group == "atlasresearch"


def test_another_user_agent_falls_back_to_the_star_group() -> None:
    get, _ = gated({"https://rules.example.test/robots.txt": robots("rules.txt")}, token="SomeBot")

    decision = get("https://rules.example.test/news")

    assert isinstance(decision, GateDecision)
    assert decision.robots is not None and decision.robots.group == "*"
    assert decision.robots.rule == "Disallow: / (line 5)"


def test_the_allowed_decision_records_the_robots_file_it_relied_on() -> None:
    body = (ROBOTS / "www-disallow-uploads.txt").read_bytes()
    site = Site({"https://www.zj-innolight.com/robots.txt": (200, body)})

    async def decide() -> GateDecision:
        async with SecHttpClient(
            UA, transport=httpx2.MockTransport(site.handle), limiter=TokenBucket(math.inf)
        ) as client:
            gate = FetchGate(ALLOWED_SITES, client, now=lambda: NOW)
            first = await gate.check("https://www.zj-innolight.com/en/about")
            await gate.check("https://www.zj-innolight.com/en/news")
            return first

    decision = asyncio.run(decide())

    assert decision.status == "allowed"
    assert decision.blocked_by is None
    assert decision.robots is not None
    assert decision.robots.url == "https://www.zj-innolight.com/robots.txt"
    assert decision.robots.sha256 == hashlib.sha256(body).hexdigest()
    assert decision.robots.status == 200
    assert decision.terms is not None and decision.terms.automation == "allowed"
    assert decision.decided_at == NOW
    assert site.requests == ["https://www.zj-innolight.com/robots.txt"]  # read once


# --- robots.txt fetch status ---


def test_a_missing_robots_file_restricts_nothing() -> None:
    get, _ = gated({})  # robots.txt is a 404 page

    assert get("https://rules.example.test/anything") == REQUESTED


def test_an_html_page_served_as_robots_txt_restricts_nothing() -> None:
    page = b"<html><body><h1>Error</h1><p>Disallow nothing here</p></body></html>"
    get, _ = gated(
        {"https://rules.example.test/robots.txt": (200, page)},
    )

    assert get("https://rules.example.test/anything") == REQUESTED


def test_an_unreachable_robots_file_disallows_everything() -> None:
    get, site = gated({"https://rules.example.test/robots.txt": (503, b"down")})

    decision = get("https://rules.example.test/anything")

    assert isinstance(decision, GateDecision) and decision.blocked_by == "robots"
    assert "robots.txt unreachable (503)" in decision.reason
    assert "https://rules.example.test/anything" not in site.requests


# --- the register and the terms ---


def test_an_unregistered_host_is_blocked_without_any_request() -> None:
    get, site = gated({})

    decision = get("https://unknown.example.test/page")

    assert isinstance(decision, GateDecision)
    assert decision.blocked_by == "register"
    assert decision.reason == "unknown.example.test is not onboarded in the site register"
    assert site.requests == []


def test_recorded_consent_lifts_a_terms_prohibition() -> None:
    sites = register(
        feed={
            "hosts": ["feed.example.test"],
            "automation": "forbidden",
            "consent": {
                "reference": "letter 2026-10-01",
                "granted_on": "2026-10-01",
                "scope": "daily retrieval of one issuer's announcements",
            },
        }
    )
    get, site = gated({}, sites)

    assert get("https://feed.example.test/doc.pdf") == REQUESTED
    assert site.requests == [
        "https://feed.example.test/robots.txt",
        "https://feed.example.test/doc.pdf",
    ]


def test_the_register_refuses_an_allowed_site_without_terms() -> None:
    with pytest.raises(ValueError, match="needs terms_url and terms_checked_on"):
        SiteRegister.model_validate(
            {
                "version": 1,
                "sites": {
                    "x": {
                        "publisher": "X",
                        "hosts": ["x.test"],
                        "automation": "allowed",
                        "terms_note": "n",
                    }
                },
            }
        )


def test_the_register_refuses_a_host_listed_twice(tmp_path: Path) -> None:
    path = tmp_path / "sites.yaml"
    path.write_text(
        "version: 1\nsites:\n"
        "  a: {publisher: A, hosts: [x.test], automation: unchecked, terms_note: n}\n"
        "  b: {publisher: B, hosts: [x.test], automation: unchecked, terms_note: n}\n"
    )

    with pytest.raises(SiteRegisterError, match=r"host x\.test is in both 'a' and 'b'"):
        load_site_register(path)
