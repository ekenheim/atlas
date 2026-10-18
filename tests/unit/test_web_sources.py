"""The pure parts of fetching a company's own page (W3): the publication date and title a page
carries, a web page's identity, the site register's `own_site_of` and the retention context of
a web page. The fetch itself is `tests/integration/test_web_sources.py`.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from atlas.ledger.service import web_canonical_url
from atlas.retention.context import SectionSource, section_context
from atlas.sources.gate import SiteRegisterError, load_site_register
from atlas.sources.web_dates import page_date, page_title, parse_moment
from tests.fakes.web import WEB_SITES

REPO = Path(__file__).parents[2]


def head(*lines: str) -> str:
    return "<html><head><title>T</title>" + "".join(lines) + "</head><body>x</body></html>"


META = '<meta property="article:published_time" content="2026-08-11T20:05:00+00:00">'
JSON_LD = (
    '<script type="application/ld+json">'
    '{"@graph": [{"@type": "Organization", "datePublished": "2020-01-01"},'
    ' {"@type": "NewsArticle", "datePublished": "2026-09-02T09:30:00-04:00"}]}'
    "</script>"
)
TIME = '<time datetime="2026-09-03T10:00:00+01:00">3 Sep</time>'


def test_the_meta_tag_wins_over_json_ld() -> None:
    found = page_date(head(TIME, JSON_LD, META))

    assert found is not None
    assert found.source == "article_published_time"
    assert found.moment == datetime(2026, 8, 11, 20, 5, tzinfo=UTC)
    assert found.written == "2026-08-11T20:05:00+00:00"


def test_json_ld_is_read_from_an_article_node_inside_a_graph_and_from_nowhere_else() -> None:
    found = page_date(head(TIME, JSON_LD))

    assert found is not None
    assert found.source == "json_ld"
    assert found.moment == datetime(2026, 9, 2, 13, 30, tzinfo=UTC)  # not the Organization's 2020


@pytest.mark.parametrize(
    "document",
    [
        '{"@type": "Organization", "datePublished": "2026-09-02"}',
        '{"@type": "WebPage", "datePublished": "2026-09-02"}',
        '{"@type": "Event", "startDate": "2026-09-02", "datePublished": "2026-09-02"}',
        '{"datePublished": "2026-09-02"}',
        '[{"@type": "Product", "datePublished": "2026-09-02"}]',
    ],
)
def test_json_ld_of_another_type_or_none_is_not_the_pages_date(document: str) -> None:
    ld = f'<script type="application/ld+json">{document}</script>'

    assert page_date(head(ld)) is None


@pytest.mark.parametrize("kind", ["Article", "NewsArticle", "PressRelease", '["Thing", "Article"]'])
def test_an_article_news_article_or_press_release_dates_the_page(kind: str) -> None:
    type_ = kind if kind.startswith("[") else f'"{kind}"'
    node = f'{{"@type": {type_}, "datePublished": "2026-09-02T00:00:00Z"}}'
    ld = f'<script type="application/ld+json">{node}</script>'

    found = page_date(head(ld))

    assert found is not None and found.source == "json_ld"


def test_a_time_element_is_never_the_pages_date() -> None:
    marked = '<time itemprop="datePublished" datetime="2026-09-03T10:00:00+01:00">new</time>'

    assert page_date(head(TIME, marked)) is None


def test_an_unparseable_source_falls_through_to_the_next() -> None:
    broken_meta = '<meta property="article:published_time" content="last Tuesday">'

    found = page_date(head(broken_meta, '<script type="application/ld+json">{not json</script>'))
    assert found is None
    found = page_date(head(broken_meta, JSON_LD))
    assert found is not None and found.source == "json_ld"


def test_a_page_with_no_date_has_none_and_a_pdf_is_not_read_for_one() -> None:
    assert page_date(head()) is None
    assert page_date(b"%PDF-1.4 article:published_time") is None


def test_a_date_without_an_offset_is_read_in_the_latest_zone_so_it_is_never_early() -> None:
    # 14:30 local, wherever the page is from: no earlier than 14:30 at UTC-12, i.e. 02:30Z next day.
    assert parse_moment("2026-08-21T14:30:00") == datetime(2026, 8, 22, 2, 30, tzinfo=UTC)


def test_a_date_alone_is_the_end_of_that_day_in_the_latest_zone() -> None:
    assert parse_moment("2026-08-21") == datetime(2026, 8, 22, 11, 59, 59, tzinfo=UTC)
    assert parse_moment("20260821") == datetime(2026, 8, 22, 11, 59, 59, tzinfo=UTC)


def test_an_offset_is_taken_as_written_and_so_is_rfc_2822() -> None:
    assert parse_moment("2026-08-21T22:30:00+08:00") == datetime(2026, 8, 21, 14, 30, tzinfo=UTC)
    assert parse_moment("2026-08-21T14:30:00Z") == datetime(2026, 8, 21, 14, 30, tzinfo=UTC)
    assert parse_moment("Fri, 21 Aug 2026 14:30:00 GMT") == datetime(
        2026, 8, 21, 14, 30, tzinfo=UTC
    )
    assert parse_moment("") is None and parse_moment("soon") is None


def test_the_title_is_og_title_else_the_title_element_with_spaces_collapsed() -> None:
    assert page_title(head('<meta property="og:title" content="Open Graph title">')) == (
        "Open Graph title"
    )
    assert page_title("<title>\n  A   spaced\ttitle </title>") == "A spaced title"
    assert page_title("<p>no title</p>") is None


def test_a_web_page_keeps_its_query_but_not_tracking_parameters_or_the_fragment() -> None:
    assert web_canonical_url("HTTPS://IR.Example.test:443/News/?id=3&utm_source=x#top") == (
        "https://ir.example.test/News?id=3"
    )
    assert web_canonical_url("https://ir.example.test/a?b=2&a=1") == (
        "https://ir.example.test/a?a=1&b=2"
    )
    assert web_canonical_url("http://www.example.test:8080") == "http://www.example.test:8080/"


def test_the_test_register_names_the_own_site_and_the_production_register_has_no_example() -> None:
    register = load_site_register(WEB_SITES)

    issuer = register.sites["example-issuer"]
    assert issuer.own_site_of == ("lumentum",) and issuer.automation == "allowed"
    assert register.sites["example-trade-press"].own_site_of == ()
    assert register.sites["example-licensed-press"].license_class == "public_regulatory"
    assert register.sites["example-forbidden"].automation == "forbidden"
    production = load_site_register(REPO / "configs" / "sources" / "sites.yaml")
    assert not [
        host for site in production.sites.values() for host in site.hosts if host.endswith(".test")
    ]
    assert production.version >= 4


def test_own_site_of_names_company_slugs(tmp_path: Path) -> None:
    path = tmp_path / "sites.yaml"
    path.write_text(
        "version: 1\nsites:\n  s:\n    publisher: P\n    hosts: [a.test]\n    terms_url: u\n"
        "    terms_checked_on: 2026-10-18\n    automation: allowed\n    terms_note: n\n"
        "    own_site_of: ['Not A Slug']\n",
        encoding="utf-8",
    )

    with pytest.raises(SiteRegisterError, match="own_site_of"):
        load_site_register(path)


def source(own_site: bool) -> SectionSource:
    return SectionSource(
        source_type="web_page",
        form_type=None,
        document_type=None,
        title="Capacity update",
        publisher="Example Publisher",
        available_at=datetime(2026, 8, 11, tzinfo=UTC),
        company_id=None,
        company_name="Lumentum",
        company_legal_name="Lumentum Holdings Inc.",
        metadata={"web": {"own_site": own_site}},
    )


def test_a_companys_own_page_is_its_own_statement() -> None:
    context = section_context(source(True), heading=None, anchor="cover")

    assert "Lumentum's web page" in context
    assert "Lumentum is speaking: this is its own page." in context


def test_another_sites_page_is_the_publishers_statement_not_the_companys() -> None:
    context = section_context(source(False), heading=None, anchor="cover")

    assert 'a web page "Capacity update" published by Example Publisher' in context
    assert "Example Publisher published it and is taken as the speaker." in context
    assert "Lumentum is speaking" not in context


@pytest.mark.parametrize(
    ("as_of", "filing_day", "published_day"),
    [
        # EDGAR files by Eastern day, over by 05:00Z next day; a date alone can last to 12:00Z.
        ("2026-09-30T00:00:00Z", "2026-09-28", "2026-09-28"),
        ("2026-09-30T04:59:59Z", "2026-09-28", "2026-09-28"),
        ("2026-09-30T05:00:00Z", "2026-09-29", "2026-09-28"),
        ("2026-09-30T11:59:59Z", "2026-09-29", "2026-09-28"),
        ("2026-09-30T12:00:00Z", "2026-09-29", "2026-09-29"),
        ("2026-09-30T12:00:00+02:00", "2026-09-29", "2026-09-28"),
    ],
)
def test_the_search_bounds_are_the_last_day_certainly_over_at_the_as_of_instant(
    as_of: str, filing_day: str, published_day: str
) -> None:
    from atlas.mcp.watch_sources import filing_bound, published_bound

    moment = datetime.fromisoformat(as_of)

    assert filing_bound(moment).isoformat() == filing_day
    assert published_bound(moment).isoformat() == published_day
