"""Lead ranking (pilot fixes 02 and 08): a pure function of a search result, its query and
purpose, the universe's company names and sites, and the repo's ranking config.

The first results are those pilot investigation 1 kept for its query about Coherent's EML
capacity (`.scratch/pilot/results.md`): a dictionary entry, an encyclopedia page and
Swedish broker and translation pages, next to an on-topic industry article (hand-written,
with the titles and snippets such pages have).

The `rerun-*` fixtures are the real results the re-run (discovery
`e9565f0d-9e28-41b2-bb92-f9dbe0cdd4c5`) kept under ranking version 1: the seed companies'
own pages, LinkedIn, quote pages. The re-run found no industry article at all, so the
articles they are compared with here are hand-written for the same queries.
"""

import json
import uuid
from datetime import date
from typing import Any

import pytest

from atlas.companies import load_universe
from atlas.discovery.edgar_fts import FilingHit
from atlas.discovery.leads import filing_snippet
from atlas.discovery.ranking import (
    LeadScore,
    RankingConfig,
    Sighting,
    load_ranking_config,
    rank_leads,
    reads_as_english,
    score_lead,
    site_host,
)
from tests.harness import REPO

QUERY = "Coherent EML laser chip capacity 200G per lane 800G transceiver"
PURPOSE = "chip-laser: EML capacity"
COMPANIES = ["Coherent", "Coherent Corp.", "Lumentum", "Lumentum Holdings Inc."]

ARTICLE = (
    "https://photonics-news.test/2026/09/coherent-200g-eml-capacity",
    "Coherent adds 200G-per-lane EML laser capacity for 800G transceivers",
    "Coherent said it is expanding indium phosphide EML chip output in Sherman, Texas, as"
    " demand for 800G and 1.6T transceivers outstrips supply.",
)
DICTIONARY = (
    "https://www.merriam-webster.com/dictionary/coherent",
    "Coherent Definition & Meaning - Merriam-Webster",
    "The meaning of COHERENT is logically or aesthetically ordered or integrated: consistent."
    " How to use coherent in a sentence.",
)
CAMBRIDGE = (
    "https://dictionary.cambridge.org/dictionary/english/coherent",
    "COHERENT | English meaning - Cambridge Dictionary",
    "coherent definition: 1. If an argument, set of ideas, or a plan is coherent, it is clear"
    " and carefully considered.",
)
ENCYCLOPEDIA = (
    "https://en.wikipedia.org/wiki/Coherence_(physics)",
    "Coherence (physics) - Wikipedia",
    "In physics, coherence expresses the potential for two waves to interfere. Laser light is"
    " coherent.",
)
BROKER = (
    "https://www.avanza.se/aktier/om-aktien.html/1234/coherent-corp",
    "Coherent Corp (COHR) - Aktiekurs & information - Avanza",
    "Se Coherent Corp aktiekurs, köp och sälj aktier, läs nyheter och följ utvecklingen för"
    " bolaget på börsen.",
)
TRANSLATION = (
    "https://sv.bab.la/lexikon/engelsk-svensk/coherent",
    "COHERENT - Översättning på svenska - bab.la",
    "Översättning av 'coherent' - Engelsk-Svensk ordbok och många andra svenska översättningar.",
)


@pytest.fixture(scope="module")
def config() -> RankingConfig:
    return load_ranking_config(REPO / "configs" / "discovery" / "lead-ranking.yaml")


def score(result: tuple[str, str, str], config: RankingConfig) -> LeadScore:
    url, title, snippet = result
    return score_lead(
        url=url,
        title=title,
        snippet=snippet,
        query=QUERY,
        purpose=PURPOSE,
        companies=COMPANIES,
        config=config,
    )


def test_an_on_topic_industry_article_is_kept_with_its_reasons(config: RankingConfig) -> None:
    article = score(ARTICLE, config)

    assert article.kept
    assert article.score >= 60
    # The company the query names is not one of its topic terms.
    assert article.reasons[0] == (
        "query terms in the title: eml, laser, capacity, 200g, lane, 800g, transceiver"
    )
    assert "query terms in the snippet: chip" in article.reasons
    assert "names Coherent" in article.reasons


@pytest.mark.parametrize("junk", [DICTIONARY, CAMBRIDGE, ENCYCLOPEDIA, BROKER, TRANSLATION])
def test_dictionary_encyclopedia_and_quote_pages_rank_below_the_article(
    junk: tuple[str, str, str], config: RankingConfig
) -> None:
    article = score(ARTICLE, config)
    page = score(junk, config)

    assert page.score < article.score
    assert not page.kept


def test_dictionaries_are_denied_whatever_they_score(config: RankingConfig) -> None:
    assert "denied host merriam-webster.com" in score(DICTIONARY, config).reasons
    assert "denied host dictionary.cambridge.org" in score(CAMBRIDGE, config).reasons
    assert "denied host bab.la" in score(TRANSLATION, config).reasons


def test_encyclopedias_and_broker_pages_are_demoted(config: RankingConfig) -> None:
    assert "demoted host wikipedia.org (x0.25)" in score(ENCYCLOPEDIA, config).reasons
    assert "demoted host avanza.se (x0.25)" in score(BROKER, config).reasons


def test_a_non_english_result_ranks_below_the_same_result_in_english(
    config: RankingConfig,
) -> None:
    url = "https://photonics-news.test/2026/09/coherent-eml"
    english = score_lead(
        url=url,
        title="Coherent EML laser capacity for 800G transceivers",
        snippet="The company is adding capacity for its lasers in Texas and in Sweden.",
        query=QUERY,
        purpose=PURPOSE,
        companies=COMPANIES,
        config=config,
    )
    swedish = score_lead(
        url=url,
        title="Coherent EML laser capacity for 800G transceivers",
        snippet="Bolaget bygger ut kapaciteten för sina lasrar i Texas och i Sverige, enligt vd.",
        query=QUERY,
        purpose=PURPOSE,
        companies=COMPANIES,
        config=config,
    )

    assert "not English (x0.25)" in swedish.reasons
    assert "not English (x0.25)" not in english.reasons
    assert swedish.score < english.score


def test_what_reads_as_english() -> None:
    assert reads_as_english("Sumitomo Electric to double 6-inch InP wafer output")
    # A headline without a function word is English all the same.
    assert reads_as_english(
        "AXT expands InP substrate capacity (comments) Readers discuss AXT's substrate expansion."
    )
    assert reads_as_english("Société Générale lifts its target for the optics maker")
    assert not reads_as_english("Se Coherent Corp aktiekurs, köp och sälj aktier")
    assert not reads_as_english("光模块 800G 激光器 产能")
    assert not reads_as_english("Bolaget bygger ut kapaciteten kraftigt under hela nästa år")
    assert not reads_as_english("Coherent investit dans les lasers EML pour les centres")
    assert not reads_as_english("Coherent baut die Kapazität für EML-Laser aus und plant mehr")


def test_the_config_can_deny_a_host(config: RankingConfig) -> None:
    denied = config.model_copy(update={"denied_hosts": ("photonics-news.test",)})

    article = score(ARTICLE, denied)

    assert not article.kept
    assert "denied host photonics-news.test" in article.reasons


def test_a_result_without_query_terms_is_not_kept(config: RankingConfig) -> None:
    unrelated = score_lead(
        url="https://news.test/2026/09/weather",
        title="Sunny weekend ahead for the coast",
        snippet="Forecasters expect warm weather and light winds on Saturday.",
        query=QUERY,
        purpose=PURPOSE,
        companies=COMPANIES,
        config=config,
    )

    assert (unrelated.score, unrelated.kept) == (0.0, False)
    assert unrelated.reasons == ["no query term", "not kept without a query term"]


def test_ranking_takes_each_lead_once_by_its_best_sighting_best_first(
    config: RankingConfig,
) -> None:
    article, dictionary, encyclopedia = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    sightings = [
        Sighting(dictionary, *DICTIONARY[:3], query=QUERY, purpose=PURPOSE),
        Sighting(encyclopedia, *ENCYCLOPEDIA[:3], query=QUERY, purpose=PURPOSE),
        # The article, first seen by a query it hardly matches, then by the EML query.
        Sighting(article, *ARTICLE[:3], query="gallium export controls", purpose=None),
        Sighting(article, *ARTICLE[:3], query=QUERY, purpose=PURPOSE),
    ]

    ranked = rank_leads(sightings, companies=COMPANIES, config=config)

    assert [lead.lead_id for lead in ranked] == [article, encyclopedia, dictionary]
    assert ranked[0].query == QUERY
    assert [lead.score.kept for lead in ranked] == [True, False, False]


# --- ranking version 2: the companies' own pages (pilot fix 08) --------------------------------

RERUN_EML = "Lumentum 200G EML chip allocation qualified second source 2026"
RERUN_EML_PURPOSE = (
    "components: confirm whether 200G EML chip demand truly exceeds qualified supply and"
    " identify alternatives"
)
RERUN_INP = "Coherent six-inch InP wafer Sherman Texas yield ramp EML 2026"
RERUN_INP_PURPOSE = (
    "sub-components: device-level capacity, yields and timing on Coherent's six-inch InP line"
    " for datacom EML/CW"
)
# Hand-written trade-press articles for the re-run's queries (the re-run found none).
EML_ALLOCATION_ARTICLE = (
    "https://optics-trade.test/articles/200g-eml-allocation-second-sources",
    "200G EML chips stay on allocation as module makers qualify second sources",
    "Transceiver makers say 200G-per-lane EML supply from Lumentum remains on allocation, and"
    " several are qualifying second-source chips for 1.6T modules.",
)
SHERMAN_ARTICLE = (
    "https://compoundsemi.test/news/coherent-six-inch-inp-sherman-ramp",
    "Coherent ramps its six-inch InP wafer line in Sherman, Texas",
    "Coherent says yields on its six-inch indium phosphide line have reached those of its"
    " three-inch fabs, lifting EML and CW laser output.",
)


@pytest.fixture(scope="module")
def universe() -> tuple[list[str], list[str]]:
    """The photonics universe's company names and the hosts of their websites."""
    companies = load_universe(REPO / "configs" / "themes" / "ai-infrastructure.yaml").companies
    names = sorted({n for c in companies.values() for n in (c.display_name, c.legal_name)})
    sites = sorted({site_host(c.website) for c in companies.values() if c.website})
    return names, sites


def rerun_results(name: str) -> list[dict[str, Any]]:
    path = REPO / "tests" / "fixtures" / "searxng" / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))["results"]


@pytest.mark.parametrize(
    ("fixture", "query", "purpose", "article"),
    [
        ("rerun-lumentum-eml-allocation", RERUN_EML, RERUN_EML_PURPOSE, EML_ALLOCATION_ARTICLE),
        ("rerun-coherent-inp-wafer", RERUN_INP, RERUN_INP_PURPOSE, SHERMAN_ARTICLE),
    ],
)
def test_an_industry_article_ranks_above_the_companies_own_pages_for_the_same_query(
    fixture: str,
    query: str,
    purpose: str,
    article: tuple[str, str, str],
    config: RankingConfig,
    universe: tuple[list[str], list[str]],
) -> None:
    companies, sites = universe
    results = rerun_results(fixture)
    ids = [uuid.uuid4() for _ in results]
    article_id = uuid.uuid4()
    sightings = [
        Sighting(i, r["url"], r["title"], r["content"], query=query, purpose=purpose)
        for i, r in zip(ids, results, strict=True)
    ]
    # Found last, as the re-run's company pages were found first.
    sightings.append(Sighting(article_id, *article, query=query, purpose=purpose))

    ranked = rank_leads(sightings, companies=companies, config=config, company_sites=sites)

    assert ranked[0].lead_id == article_id
    assert ranked[0].score.kept
    # Version 1 kept these real results; none is kept now, and none outscores the article.
    assert [lead.score.kept for lead in ranked[1:]] == [False] * len(results)
    assert all(lead.score.score < ranked[0].score.score for lead in ranked[1:])


def test_the_companies_own_pages_say_why_they_are_not_kept(
    config: RankingConfig, universe: tuple[list[str], list[str]]
) -> None:
    companies, sites = universe
    by_url = {r["url"]: r for r in rerun_results("rerun-lumentum-eml-allocation")}

    def reasons(url: str) -> list[str]:
        r = by_url[url]
        return score_lead(
            url=url,
            title=r["title"],
            snippet=r["content"],
            query=RERUN_EML,
            purpose=RERUN_EML_PURPOSE,
            companies=companies,
            config=config,
            company_sites=sites,
        ).reasons

    investor = reasons("https://investor.lumentum.com/overview/default.aspx")
    assert "a company's own site lumentum.com (x0.25)" in investor
    assert 'generic title "investor relations" (x0.25)' in investor
    assert 'generic title "homepage" (x0.25)' in reasons("https://www.lumentum.com/en")
    assert 'generic title "company" (x0.25)' in reasons("https://www.lumentum.com/en/company")
    assert "demoted host linkedin.com (x0.25)" in reasons(
        "https://www.linkedin.com/company/lumentum"
    )
    # Naming Lumentum, whom the query names, is not matching the query.
    assert investor[0] == "no query term"
    assert investor[-1] == "not kept without a query term"


def test_a_company_name_alone_does_not_keep_a_lead(config: RankingConfig) -> None:
    profile = score_lead(
        url="https://markets-wire.test/companies/lumentum",
        title="Lumentum Holdings Inc. company profile and executives",
        snippet="Lumentum Holdings Inc. designs and makes optical and photonic products.",
        query=RERUN_EML,
        purpose=RERUN_EML_PURPOSE,
        companies=["Lumentum", "Lumentum Holdings Inc."],
        config=config,
    )

    assert not profile.kept
    assert "names Lumentum, Lumentum Holdings Inc." in profile.reasons
    assert profile.reasons[-1] == "not kept without a query term"


def test_regulator_and_standards_pages_are_not_demoted(
    config: RankingConfig, universe: tuple[list[str], list[str]]
) -> None:
    companies, sites = universe
    regulator = score_lead(
        url="https://www.federalregister.gov/documents/2026/01/15/export-controls-indium-phosphide",
        title="Export Controls on Indium Phosphide Substrates and Gallium",
        snippet="The Bureau of Industry and Security amends the Export Administration Regulations"
        " to add licence requirements for indium phosphide substrates shipped to China.",
        query="indium phosphide substrate export control China gallium germanium 2026",
        purpose="feedstock: export or licensing risks on InP substrates",
        companies=companies,
        config=config,
        company_sites=sites,
    )
    standard = score_lead(
        url="https://www.oiforum.com/technical-work/hot-topics/1-6t-co-packaged-optics",
        title="1.6T co-packaged optics: external laser source implementation agreement",
        snippet="The OIF external laser small form factor pluggable (ELSFP) agreement defines"
        " the CW laser source for co-packaged optics.",
        query="CW laser silicon photonics external laser source supplier Lumentum Coherent 2026",
        purpose="components: qualified second sources for CW/DFB lasers",
        companies=companies,
        config=config,
        company_sites=sites,
    )

    for page in (regulator, standard):
        assert page.kept
        assert not any("(x0.25)" in reason for reason in page.reasons)


def test_a_demoted_entry_with_a_path_demotes_only_the_pages_under_it(
    config: RankingConfig,
) -> None:
    def demoted(url: str) -> bool:
        return any(
            r.startswith("demoted host")
            for r in score_lead(
                url=url,
                title="Lumentum 200G EML allocation",
                snippet="",
                query=RERUN_EML,
                purpose=None,
                companies=[],
                config=config,
            ).reasons
        )

    assert demoted("https://www.bloomberg.com/profile/company/LITE:US")
    assert not demoted("https://www.bloomberg.com/news/articles/2026-09-01/eml-allocation")
    assert not demoted("https://www.bloomberg.com/profiles-of-the-week")


def test_an_edgar_filing_hit_is_ranked_against_its_phrase_and_not_demoted(
    config: RankingConfig, universe: tuple[list[str], list[str]]
) -> None:
    # Pilot fix 12: an EDGAR full-text search hit (as the recorded AXT hit), whose snippet
    # says which phrase EDGAR matched; its query is that phrase.
    companies, sites = universe
    hit = FilingHit(
        position=1,
        cik="0001051627",
        filer="AXT INC",
        ticker="AXTI",
        form="10-K",
        file_type="10-K",
        file_date=date(2026, 3, 17),
        period_ending=date(2025, 12, 31),
        accession="0001437749-26-008612",
        document="axti20251231_10k.htm",
        url="https://www.sec.gov/Archives/edgar/data/1051627/000143774926008612/axti20251231_10k.htm",
    )

    scored = score_lead(
        url=hit.url,
        title=hit.title,
        snippet=filing_snippet('"InP substrates"', hit),
        query='"InP substrates"',
        purpose="feedstock: InP substrate supply",
        companies=companies,
        config=config,
        company_sites=sites,
    )

    assert scored.kept
    assert scored.reasons[0] == "query terms in the snippet: inp, substrate"
    assert not any("own site" in reason or "demoted" in reason for reason in scored.reasons)


def test_the_config_is_version_2(config: RankingConfig) -> None:
    assert config.version == 2
