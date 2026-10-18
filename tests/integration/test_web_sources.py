"""A company's own page into the archive, through the fetch gate (W3: `atlas sources fetch`,
`POST /api/v1/sources/fetch`).

Seams: the HTTP API (the TestClient), the `atlas` CLI and, in `test_mcp_watch_sources.py`, the
MCP tool. The pages are the hand-written fixtures in `tests/fixtures/web/lumentum/` on the
register's two synthetic example sites (`ir.example-issuer.test`, the company's own, and
`news.example-trade.test`, a third party's), replayed in process through
`ATLAS_EXCHANGE_FIXTURES_DIR`; nothing is requested from the network. Expected values are read off
the fixtures by hand.
"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from atlas.cli import run_sources_fetch
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.serve import Served
from tests.harness import REPO, SITES, THEMES, Atlas

WEB = REPO / "tests" / "fixtures" / "web"
IR = "https://ir.example-issuer.test"
NEWS = "https://news.example-trade.test"
Q4 = f"{IR}/news/q4-results.html"
SENTENCE = "Demand for our indium phosphide lasers exceeded our capacity in the quarter"


@pytest.fixture
def atlas(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> Iterator[Atlas]:
    harness = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        exchange_fixtures_dir=WEB,
        source_sites_config=SITES,
    )
    harness.apply_template()
    yield harness
    harness.engine.dispose()


def fetch(atlas: Atlas, url: str, company: str = "lumentum", **extra: Any) -> Any:
    return atlas.api.post("/api/v1/sources/fetch", json={"company": company, "url": url, **extra})


def fetched(atlas: Atlas, url: str, **extra: Any) -> dict[str, Any]:
    response = fetch(atlas, url, **extra)
    assert response.status_code == 200, response.text
    return response.json()


def documents(atlas: Atlas, company: str = "lumentum") -> list[dict[str, Any]]:
    path = f"/api/v1/companies/{atlas.company(company)['id']}/sources"
    return atlas.get(path, limit=100)["items"]


def recorded(atlas: Atlas) -> int:
    """How many Source Documents there are, whatever the company."""
    with atlas.engine.connect() as connection:
        return connection.execute(text("SELECT count(*) FROM source_document")).scalar_one()


def decisions(atlas: Atlas, **params: Any) -> list[dict[str, Any]]:
    path = f"/api/v1/companies/{atlas.company('lumentum')['id']}/fetch-gate-decisions"
    return atlas.get(path, limit=100, **params)["items"]


def at(value: str) -> datetime:
    return datetime.fromisoformat(value)


# --- an own page, its tier, its date, its place in the ledger ---------------------------------


def test_a_companys_own_page_is_a_tier_a_source_dated_by_its_own_meta_tag(atlas: Atlas) -> None:
    page = fetched(atlas, Q4)

    assert page["outcome"] == "new_version"
    assert (page["company"], page["tier"], page["site"]) == ("lumentum", "A", "example-issuer")
    assert page["canonical_url"] == Q4
    assert page["title"] == "Example Issuer announces fourth-quarter results"
    assert page["media_type"] == "text/html"
    assert at(page["available_at"]) == datetime(2026, 8, 11, 20, 5, tzinfo=UTC)
    assert page["available_at_basis"] == "page_published_date"
    assert page["date_source"] == "article_published_time"

    (document,) = documents(atlas)
    assert document["provider"] == "web"
    assert document["source_type"] == "web_page"
    assert document["source_tier"] == "A"
    assert document["license_class"] == "public_issuer"
    assert document["publisher"] == "Example Issuer plc (investor relations; synthetic)"
    version = atlas.get(f"/api/v1/source-versions/{page['source_version_id']}")
    assert version["parse_status"] == "parsed" and version["language"] == "en"
    assert at(version["published_at"]) == datetime(2026, 8, 11, 20, 5, tzinfo=UTC)
    assert version["evidence_family"] is not None
    assert SENTENCE in atlas.parsed(page["source_version_id"])
    assert version["metadata"]["web"]["date_as_written"] == "2026-08-11T20:05:00+00:00"


def test_the_fetch_records_the_gate_decision_it_was_allowed_by(atlas: Atlas) -> None:
    page = fetched(atlas, Q4)

    (allowed,) = decisions(atlas, status="allowed")
    assert allowed["id"] == page["gate_decision_id"]
    assert (allowed["provider"], allowed["purpose"], allowed["url"]) == ("web", "document", Q4)
    assert allowed["site"] == "example-issuer"
    assert allowed["terms"]["automation"] == "allowed"
    assert allowed["robots"]["url"] == f"{IR}/robots.txt"
    version = atlas.get(f"/api/v1/source-versions/{page['source_version_id']}")
    assert version["fetches"][0]["gate_decision_id"] == allowed["id"]


def test_a_third_partys_page_is_tier_b(atlas: Atlas) -> None:
    page = fetched(atlas, f"{NEWS}/2026/lumentum-capacity.html")

    assert (page["tier"], page["site"]) == ("B", "example-trade-press")
    assert at(page["available_at"]) == datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    (document,) = documents(atlas)
    assert document["source_tier"] == "B" and document["license_class"] == "public_issuer"
    assert document["publisher"] == "Example Trade Press (synthetic)"


def test_another_companys_page_on_the_issuers_site_is_tier_b(atlas: Atlas) -> None:
    # The register says the site is Lumentum's own; Coherent fetching a page of it is a third
    # party's statement about Coherent, not Coherent's own.
    page = fetched(atlas, f"{IR}/news/explicit.html", company="coherent")

    assert page["tier"] == "B"


# --- available_at, from each source ------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "available_at", "basis", "source"),
    [
        (
            "q4-results.html",
            "2026-08-11T20:05:00+00:00",
            "page_published_date",
            "article_published_time",
        ),
        ("json-ld.html", "2026-09-02T13:30:00+00:00", "page_published_date", "json_ld"),
        # `<time datetime="2026-09-03">` is a date alone: the end of that day at UTC-12.
        ("time-element.html", "2026-09-04T11:59:59+00:00", "page_published_date", "time_element"),
    ],
)
def test_available_at_is_the_date_the_page_carries(
    atlas: Atlas, path: str, available_at: str, basis: str, source: str
) -> None:
    page = fetched(atlas, f"{IR}/news/{path}")

    assert at(page["available_at"]) == at(available_at)
    assert (page["available_at_basis"], page["date_source"]) == (basis, source)


def test_a_page_with_no_date_is_available_when_it_was_fetched(atlas: Atlas) -> None:
    before = datetime.now(UTC)
    page = fetched(atlas, f"{IR}/news/no-date.html")
    after = datetime.now(UTC)

    assert before <= at(page["available_at"]) <= after
    assert (page["available_at_basis"], page["date_source"]) == ("observed_discovery", "fetch_time")
    version = atlas.get(f"/api/v1/source-versions/{page['source_version_id']}")
    assert version["published_at"] is None  # the publisher said nothing


def test_a_pdf_deck_carries_no_date_so_it_is_available_when_fetched(atlas: Atlas) -> None:
    before = datetime.now(UTC)
    page = fetched(atlas, f"{IR}/decks/investor-deck.pdf")

    assert page["media_type"] == "application/pdf" and page["title"] == "investor-deck.pdf"
    assert at(page["available_at"]) >= before
    assert page["available_at_basis"] == "observed_discovery"
    version = atlas.get(f"/api/v1/source-versions/{page['source_version_id']}")
    assert version["parse_status"] == "parsed" and version["page_anchors"]
    assert "Annual Report and Accounts 2026" in atlas.parsed(page["source_version_id"])


def test_a_date_after_the_fetch_is_not_believed(atlas: Atlas) -> None:
    now = datetime.now(UTC)
    page = fetched(atlas, f"{IR}/news/future-date.html")

    assert at(page["available_at"]) <= datetime.now(UTC)
    assert at(page["available_at"]) >= now
    assert page["date_source"] == "article_published_time"


def test_a_publication_time_the_caller_gives_wins_over_the_pages(atlas: Atlas) -> None:
    page = fetched(atlas, f"{IR}/news/explicit.html", published_at="2026-06-01T00:00:00+02:00")

    assert at(page["available_at"]) == datetime(2026, 5, 31, 22, 0, tzinfo=UTC)
    assert (page["available_at_basis"], page["date_source"]) == ("publisher_timestamp", "argument")
    version = atlas.get(f"/api/v1/source-versions/{page['source_version_id']}")
    assert at(version["published_at"]) == datetime(2026, 5, 31, 22, 0, tzinfo=UTC)


def test_a_publication_time_needs_its_offset_and_cannot_be_in_the_future(atlas: Atlas) -> None:
    naive = fetch(atlas, Q4, published_at="2026-06-01T00:00:00")
    future = fetch(atlas, Q4, published_at="2999-01-01T00:00:00+00:00")

    assert naive.status_code == 422
    assert future.status_code == 422
    assert future.json()["error"]["code"] == "invalid_published_at"
    assert recorded(atlas) == 0


# --- idempotency and revisions -----------------------------------------------------------------


def test_the_same_bytes_again_change_nothing(atlas: Atlas) -> None:
    first = fetched(atlas, Q4)
    again = fetched(atlas, Q4)

    assert again["outcome"] == "unchanged"
    assert again["source_version_id"] == first["source_version_id"]
    assert again["source_document_id"] == first["source_document_id"]
    assert again["available_at"] == first["available_at"]
    assert again["retain_jobs"] == []  # nothing new to retain
    assert len(atlas.versions(Q4)) == 1
    assert len(documents(atlas)) == 1
    versions = atlas.get(f"/api/v1/source-versions/{first['source_version_id']}")
    assert [o["outcome"] for o in versions["fetches"]].count("unchanged") == 1


def test_a_page_the_server_says_is_unmodified_is_not_downloaded_again(atlas: Atlas) -> None:
    url = f"{IR}/news/etag.html"
    first = fetched(atlas, url)
    again = fetched(atlas, url)

    assert (first["outcome"], again["outcome"]) == ("new_version", "not_modified")
    assert again["source_version_id"] == first["source_version_id"]
    assert len(atlas.versions(url)) == 1


def test_changed_bytes_are_a_new_version_available_from_the_fetch(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    web = tmp_path / "web"  # a copy, whose page the site revises between the two fetches
    shutil.copytree(WEB, web)
    atlas = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        exchange_fixtures_dir=web,
        source_sites_config=SITES,
    )
    try:
        url = f"{IR}/news/revised.html"
        first = fetched(atlas, url)
        revised = web / "lumentum" / "ir" / "news" / "revised.html"
        revised.write_text(
            revised.read_text(encoding="utf-8").replace("fiscal 2027", "fiscal 2028"),
            encoding="utf-8",
        )
        second = fetched(atlas, url)

        assert second["outcome"] == "new_version"
        assert second["source_version_id"] != first["source_version_id"]
        assert second["available_at_basis"] == "observed_revision"  # not public before seen
        assert at(second["available_at"]) >= at(first["available_at"])
        assert [v["version_number"] for v in atlas.versions(url)] == [1, 2]
        assert "double by fiscal 2028" in atlas.parsed(second["source_version_id"])
        assert "double by fiscal 2027" in atlas.parsed(first["source_version_id"])
    finally:
        atlas.engine.dispose()


def test_a_new_version_is_retained_when_memory_is_configured(atlas: Atlas) -> None:
    page = fetched(atlas, Q4)

    assert len(page["retain_jobs"]) == 1
    atlas.worker_pass()
    sections = atlas.memory(page["source_version_id"])["documents"]
    assert sections  # the page's sections went to the research bank


# --- redirects ---------------------------------------------------------------------------------


def test_a_redirect_within_the_site_is_followed_and_the_target_is_the_document(
    atlas: Atlas,
) -> None:
    page = fetched(atlas, f"{IR}/news/old-path.html")

    assert page["url"] == f"{IR}/news/old-path.html" and page["final_url"] == Q4
    assert page["canonical_url"] == Q4
    allowed = decisions(atlas, status="allowed")
    assert sorted(each["url"] for each in allowed) == sorted([f"{IR}/news/old-path.html", Q4])


def test_a_redirect_to_a_site_nobody_onboarded_is_blocked_before_it_is_requested(
    atlas: Atlas,
) -> None:
    response = fetch(atlas, f"{IR}/news/offsite.html")

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "fetch_blocked"
    assert error["detail"]["blocked_by"] == "register"
    assert error["detail"]["url"] == "https://elsewhere.example-offsite.test/page.html"
    assert documents(atlas) == []
    blocked = decisions(atlas, status="blocked")
    assert [d["id"] for d in blocked] == [error["detail"]["gate_decision_id"]]


# --- the gate ----------------------------------------------------------------------------------


def test_a_site_nobody_onboarded_is_blocked_and_nothing_is_fetched(atlas: Atlas) -> None:
    url = "https://unknown.example-offsite.test/ir/news.html"

    response = fetch(atlas, url)

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "fetch_blocked"
    assert error["detail"]["blocked_by"] == "register"
    assert "not onboarded" in error["detail"]["reason"]
    assert documents(atlas) == []
    (blocked,) = decisions(atlas, status="blocked")
    assert (blocked["url"], blocked["blocked_by"], blocked["provider"]) == (url, "register", "web")
    assert blocked["id"] == error["detail"]["gate_decision_id"]
    assert decisions(atlas, status="allowed") == []


def test_a_site_whose_terms_forbid_automation_is_blocked_by_its_terms(atlas: Atlas) -> None:
    response = fetch(atlas, "https://www.soitec.com/en/investors/news.html")

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["detail"]["blocked_by"] == "terms"
    assert error["detail"]["site"] == "soitec"
    assert documents(atlas) == []
    (blocked,) = decisions(atlas, status="blocked")
    assert blocked["terms"]["automation"] == "forbidden" and blocked["robots"] is None


def test_a_path_robots_txt_disallows_is_blocked_by_robots(atlas: Atlas) -> None:
    response = fetch(atlas, f"{IR}/private/roadmap.html")

    assert response.status_code == 403
    assert response.json()["error"]["detail"]["blocked_by"] == "robots"
    assert documents(atlas) == []
    (blocked,) = decisions(atlas, status="blocked")
    assert blocked["robots"]["rule"] == "Disallow: /private/ (line 2)"
    # A path it allows on the same site is fetched.
    assert fetched(atlas, Q4)["outcome"] == "new_version"


def test_a_site_the_register_allows_is_not_fetched_when_atlas_cannot_request_it(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    (tmp_path / "off").mkdir()
    off = Atlas(database_url, tmp_path / "off", hindsight[1].url, source_sites_config=SITES)
    try:
        response = fetch(off, Q4)

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "web_fetch_off"
        assert documents(off) == []
    finally:
        off.engine.dispose()


# --- what is refused, and what fails ------------------------------------------------------------


def test_only_html_and_pdf_are_archived(atlas: Atlas) -> None:
    response = fetch(atlas, f"{IR}/media/chart.png")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert documents(atlas) == []


def test_a_page_the_site_does_not_have_is_a_failed_fetch(atlas: Atlas) -> None:
    response = fetch(atlas, f"{IR}/news/missing.html")

    assert response.status_code == 502
    error = response.json()["error"]
    assert (error["code"], error["detail"]["status"]) == ("fetch_failed", 404)
    assert documents(atlas) == []


def test_the_arguments_are_checked(atlas: Atlas) -> None:
    assert fetch(atlas, "ftp://ir.example-issuer.test/a").json()["error"]["code"] == "invalid_url"
    assert fetch(atlas, "not a url").status_code == 422
    unknown = fetch(atlas, Q4, company="no-such-company")
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "unknown_company"
    assert atlas.api.post("/api/v1/sources/fetch", json={"url": Q4}).status_code == 422


def test_a_source_version_of_a_page_is_in_the_audit_chain(atlas: Atlas) -> None:
    page = fetched(atlas, Q4)

    with atlas.engine.connect() as connection:
        actions = {
            row.action
            for row in connection.execute(
                text("SELECT action FROM audit_event WHERE entity_id = ANY(:ids)"),
                {
                    "ids": [
                        page["source_version_id"],
                        page["source_document_id"],
                        page["gate_decision_id"],
                    ]
                },
            )
        }
    assert {"source_document.created", "source_version.created", "fetch_gate.allowed"} <= actions


# --- the CLI -----------------------------------------------------------------------------------


def test_the_cli_function_prints_the_recorded_page(
    atlas: Atlas, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_sources_fetch(atlas.settings(), "lumentum", Q4, None)

    assert code == 0
    page = json.loads(capsys.readouterr().out)
    assert (page["outcome"], page["tier"], page["date_source"]) == (
        "new_version",
        "A",
        "article_published_time",
    )
    assert len(atlas.versions(Q4)) == 1


def test_the_cli_function_reports_a_block_and_a_bad_time(
    atlas: Atlas, capsys: pytest.CaptureFixture[str]
) -> None:
    blocked = run_sources_fetch(atlas.settings(), "lumentum", "https://unknown.test/a", None)
    out = json.loads(capsys.readouterr().out)
    bad = run_sources_fetch(atlas.settings(), "lumentum", Q4, "yesterday")

    assert blocked == 1 and out["outcome"] == "blocked" and out["blocked_by"] == "register"
    assert bad == 2
    assert documents(atlas) == []


def test_atlas_sources_fetch_runs_as_a_command(atlas: Atlas, tmp_path: Path) -> None:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        **({"SYSTEMROOT": os.environ["SYSTEMROOT"]} if "SYSTEMROOT" in os.environ else {}),
        "ATLAS_DATABASE_URL": atlas.database_url,
        "ATLAS_ACTOR": "local-researcher",
        "ATLAS_ARCHIVE_ROOT": str(atlas.archive),
        "ATLAS_THEMES_CONFIG": str(THEMES),
        "ATLAS_SOURCE_SITES_CONFIG": str(SITES),
        "ATLAS_EXCHANGE_FIXTURES_DIR": str(WEB),
    }

    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "atlas",
            "sources",
            "fetch",
            "--company",
            "lumentum",
            "--url",
            f"{IR}/news/json-ld.html",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert done.returncode == 0, done.stderr
    page = json.loads(done.stdout)
    assert (page["tier"], page["date_source"]) == ("A", "json_ld")
    assert len(atlas.versions(f"{IR}/news/json-ld.html")) == 1
