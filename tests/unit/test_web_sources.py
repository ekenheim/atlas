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

REPO = Path(__file__).parents[2]


def head(*lines: str) -> str:
    return "<html><head><title>T</title>" + "".join(lines) + "</head><body>x</body></html>"


META = '<meta property="article:published_time" content="2026-08-11T20:05:00+00:00">'
JSON_LD = (
    '<script type="application/ld+json">'
    '{"@graph": [{"@type": "Organization"}, {"datePublished": "2026-09-02T09:30:00-04:00"}]}'
    "</script>"
)
TIME = '<time datetime="2026-09-03T10:00:00+01:00">3 Sep</time>'


def test_the_meta_tag_wins_over_json_ld_and_a_time_element() -> None:
    found = page_date(head(TIME, JSON_LD, META))

    assert found is not None
    assert found.source == "article_published_time"
    assert found.moment == datetime(2026, 8, 11, 20, 5, tzinfo=UTC)
    assert found.written == "2026-08-11T20:05:00+00:00"


def test_json_ld_wins_over_a_time_element_and_is_found_inside_a_graph() -> None:
    found = page_date(head(TIME, JSON_LD))

    assert found is not None
    assert found.source == "json_ld"
    assert found.moment == datetime(2026, 9, 2, 13, 30, tzinfo=UTC)


def test_a_time_element_is_the_last_resort_and_a_marked_one_comes_first() -> None:
    plain = '<time datetime="2026-01-01T00:00:00Z">old</time>'
    marked = '<time itemprop="datePublished" datetime="2026-09-03T10:00:00+01:00">new</time>'

    found = page_date(head(plain, marked))

    assert found is not None
    assert found.source == "time_element"
    assert found.moment == datetime(2026, 9, 3, 9, 0, tzinfo=UTC)
    assert page_date(head(plain)).moment == datetime(2026, 1, 1, tzinfo=UTC)  # type: ignore[union-attr]


def test_an_unparseable_source_falls_through_to_the_next() -> None:
    broken_meta = '<meta property="article:published_time" content="last Tuesday">'
    broken_ld = '<script type="application/ld+json">{not json</script>'

    found = page_date(head(broken_meta, broken_ld, TIME))

    assert found is not None and found.source == "time_element"


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


def test_the_committed_register_has_the_two_example_sites_and_names_the_own_site() -> None:
    register = load_site_register(REPO / "configs" / "sources" / "sites.yaml")

    issuer = register.sites["example-issuer"]
    assert issuer.own_site_of == ("lumentum",) and issuer.automation == "allowed"
    assert register.sites["example-trade-press"].own_site_of == ()
    assert register.site_for("https://ir.example-issuer.test/news/a.html") is not None
    assert register.version >= 4


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
