"""Lead ranking (pilot fix 02): a pure function of a search result, its query and purpose,
the universe's company names and the repo's ranking config.

The results are those pilot investigation 1 kept for its query about Coherent's EML
capacity (`.scratch/pilot/results.md`): a dictionary entry, an encyclopedia page and
Swedish broker and translation pages, next to an on-topic industry article (hand-written,
with the titles and snippets such pages have).
"""

import uuid

import pytest

from atlas.discovery.ranking import (
    LeadScore,
    RankingConfig,
    Sighting,
    load_ranking_config,
    rank_leads,
    reads_as_english,
    score_lead,
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
    assert article.reasons[0] == (
        "query terms in the title: coherent, eml, laser, capacity, 200g, lane, 800g, transceiver"
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
    assert unrelated.reasons == ["no query term", "below the minimum score 15"]


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
