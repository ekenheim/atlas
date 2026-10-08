"""Discovery: the Scout turns a theme question and the Bottlenecks model's open gaps into at
most 10 SearXNG queries, whose results become Tier C leads, deduplicated by canonical URL
and never Evidence (spec "Discovery"; stories 10-12; ticket 08).

Seams: the `atlas` CLI enqueues the `discover` job, single worker passes run it, and
everything is observed through `/api/v1` (leads, discoveries, role calls, jobs, `/metrics`)
and the requests the fakes received. LiteLLM is the scripted chat fake (the Scout's answers
are written here), SearXNG the scripted fake over the hand-written fixtures in
`tests/fixtures/searxng/`, and Hindsight the recorded fake (the template import and the
Bottlenecks model's refresh are its documented derivations). Nothing live is called.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from atlas.roles import DIRECTIVES
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.searxng import FakeSearXNG, SearchReply
from tests.fakes.serve import Served, serve
from tests.harness import REPO, Atlas, at

QUESTION = (
    "Which inputs to indium phosphide lasers for AI data-center optics are capacity"
    " constrained, and who could second-source them?"
)
# What a refreshed Bottlenecks model names as missing (written here; the refresh is derived).
GAPS = (
    "Unconfirmed: InP substrate capacity. Demand evidence exists, but the second-source"
    " evidence is missing. Unconfirmed: EML lasers for 800G; pricing-power evidence is missing."
)
GAPS_REFRESHED_AT = "2026-09-28T06:00:00+00:00"
SUBSTRATE = "indium phosphide substrate capacity expansion 2026"
SECOND_SOURCE = "InP laser second source qualification hyperscaler"
NOTHING = "electro-absorption modulated laser shortage 800G transceivers"
QUERIES = [
    {"query": SUBSTRATE, "purpose": "InP substrate capacity: second sources"},
    {"query": SECOND_SOURCE, "purpose": "InP lasers: second sources"},
    {"query": NOTHING, "purpose": "EML lasers: pricing power"},
]
SCOUT_PROMPT = (REPO / "backend" / "atlas" / "roles" / "prompts" / "scout.v5.md").read_text(
    encoding="utf-8"
)
AXT = "https://photonics-news.test/2026/08/axt-expands-inp-substrate-capacity"
SUMITOMO = "https://optics-trade.test/articles/sumitomo-electric-inp-wafers"
BLOG = "https://blog.photonics.test/second-sources-for-inp-lasers?a=1&b=2"


class Discovery(Atlas):
    def __init__(
        self,
        database_url: str,
        tmp_path: Path,
        hindsight: str,
        litellm: FakeLiteLLM,
        litellm_url: str,
        searxng: FakeSearXNG,
        searxng_url: str | None,
    ) -> None:
        self.litellm = litellm
        self.searxng = searxng
        super().__init__(database_url, tmp_path, hindsight, litellm_url, searxng_url=searxng_url)

    def script_searches(self) -> None:
        self.searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))
        self.searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))
        self.searxng.script(NOTHING, SearchReply.of("no-results"))

    def discover(self, key: str, question: str = QUESTION, theme: str = "photonics") -> str:
        """Enqueue a `discover` job and return its ID (the worker isn't run)."""
        payload = json.dumps({"theme": theme, "question": question})
        return self.enqueue("jobs", "enqueue", "discover", "--key", key, "--payload", payload)

    def job(self, job_id: str) -> dict[str, Any]:
        return self.get(f"/api/v1/jobs/{job_id}")

    def run_discovery(self, key: str, **payload: Any) -> dict[str, Any]:
        """Discover, one worker pass, and the succeeded job's discovery record."""
        job = self.job(self.discover(key, **payload))
        self.worker_pass()
        job = self.job(job["id"])
        assert job["status"] == "succeeded", job["failures"]
        return self.get(f"/api/v1/discoveries/{job['artifacts']['discovery_id']}")

    def leads(self, **params: Any) -> dict[str, Any]:
        return self.get("/api/v1/leads", **params)

    def lead(self, canonical: str) -> dict[str, Any]:
        items = self.leads(limit=500)["items"]
        (found,) = [lead for lead in items if lead["canonical_url"] == canonical]
        return found

    def count(self, table: str) -> int:
        with self.engine.connect() as connection:
            return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def scout(*queries: dict[str, Any]) -> ChatReply:
    return ChatReply.json({"queries": list(queries)}, tokens=(900, 120))


@pytest.fixture
def served() -> Iterator[tuple[FakeLiteLLM, Served, FakeSearXNG, Served]]:
    litellm, searxng = FakeLiteLLM(), FakeSearXNG()
    with serve(litellm.handle) as litellm_served, serve(searxng.handle) as searxng_served:
        yield litellm, litellm_served, searxng, searxng_served
        litellm_served.raise_errors()
        searxng_served.raise_errors()


def harness(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    served: tuple[FakeLiteLLM, Served, FakeSearXNG, Served],
    *,
    with_searxng: bool = True,
) -> Discovery:
    litellm, litellm_served, searxng, searxng_served = served
    atlas = Discovery(
        database_url,
        tmp_path,
        hindsight[1].url,
        litellm,
        litellm_served.url,
        searxng,
        searxng_served.url if with_searxng else None,
    )
    atlas.apply_template()
    return atlas


@pytest.fixture
def atlas(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    served: tuple[FakeLiteLLM, Served, FakeSearXNG, Served],
) -> Iterator[Discovery]:
    """Atlas with the template applied and the Bottlenecks model refreshed with GAPS."""
    discovery = harness(database_url, tmp_path, hindsight, served)
    hindsight[0].apply_refresh("bottlenecks", GAPS, [], refreshed_at=at(GAPS_REFRESHED_AT))
    yield discovery
    discovery.engine.dispose()


# --- the Scout ---------------------------------------------------------------------------------


def test_the_scout_turns_the_question_and_the_bottleneck_gaps_into_queries(
    atlas: Discovery,
) -> None:
    atlas.litellm.script_chat(scout(*QUERIES))
    atlas.script_searches()

    discovery = atlas.run_discovery("photonics-1")

    [body] = atlas.litellm.chat_requests()
    assert body["metadata"] == {"run_id": discovery["run_id"], "role": "scout"}
    assert body["response_format"]["json_schema"]["name"] == "scout"
    assert body["response_format"]["json_schema"]["strict"] is True
    system, user = body["messages"]
    assert system["role"] == "system"
    assert system["content"].startswith(f"{DIRECTIVES}\n\n{SCOUT_PROMPT}\n\n## Answer format")
    sent = json.loads(user["content"])
    assert sent["request"] == {
        "theme_id": "photonics",
        "theme_title": "Photonics for AI data centers",
        "theme_description": sent["request"]["theme_description"],
        "research_question": QUESTION,
        "max_queries": 10,
    }
    assert sent["request"]["theme_description"].startswith("Optical transceivers, lasers")
    # The open gaps are the Bottlenecks model's content, passed as quoted low-trust data.
    assert sent["retrieved_data"] == [
        {"id": "bottlenecks", "source": "mental-model:bottlenecks", "text": GAPS, "trust": "low"}
    ]
    assert discovery["gaps_source"] == f"mental-model:bottlenecks@{GAPS_REFRESHED_AT}"
    assert (discovery["theme"], discovery["question"]) == ("photonics", QUESTION)
    assert discovery["status"] == "completed"
    assert [(q["position"], q["query"], q["purpose"]) for q in discovery["queries"]] == [
        (1, SUBSTRATE, "InP substrate capacity: second sources"),
        (2, SECOND_SOURCE, "InP lasers: second sources"),
        (3, NOTHING, "EML lasers: pricing power"),
    ]
    # Each query searched once, engines and language named explicitly, JSON asked for.
    assert atlas.searxng.searches() == [
        {"q": query["query"], "format": "json", "engines": "bing,brave", "language": "en"}
        for query in QUERIES
    ]
    assert discovery["engines"] == ["bing", "brave"]
    # The Scout's call is a role call of the discovery's run, with its tokens.
    calls = atlas.get(f"/api/v1/runs/{discovery['run_id']}/role-calls")
    assert (calls["tokens_in"], calls["tokens_out"]) == (900, 120)
    [call] = calls["role_calls"]
    assert (call["role"], call["prompt_name"], call["status"]) == ("scout", "scout", "accepted")


def test_before_the_bottlenecks_model_s_first_refresh_there_are_no_gaps_to_send(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    served: tuple[FakeLiteLLM, Served, FakeSearXNG, Served],
) -> None:
    atlas = harness(database_url, tmp_path, hindsight, served)
    atlas.litellm.script_chat(scout(QUERIES[0]))
    atlas.searxng.script(SUBSTRATE, SearchReply.of("inp-substrate-capacity"))

    discovery = atlas.run_discovery("photonics-1")

    [body] = atlas.litellm.chat_requests()
    assert json.loads(body["messages"][1]["content"])["retrieved_data"] == []
    assert discovery["gaps_source"] is None
    atlas.engine.dispose()


def test_at_most_ten_distinct_queries_are_searched(atlas: Discovery) -> None:
    texts = [f"inp query {n}" for n in range(1, 12)]
    proposed = [{"query": query, "purpose": None} for query in texts]
    duplicate = {"query": "  INP query 1 ", "purpose": "the same query again"}
    atlas.litellm.script_chat(scout(proposed[0], duplicate, *proposed[1:]))
    for query in texts[:10]:
        atlas.searxng.script(query, SearchReply.of("no-results"))

    discovery = atlas.run_discovery("photonics-1")

    assert discovery["max_queries"] == 10
    assert discovery["queries_proposed"] == 12
    assert [q["query"] for q in discovery["queries"]] == [f"inp query {n}" for n in range(1, 11)]
    assert len(atlas.searxng.searches()) == 10


def test_the_query_cap_is_config_but_never_above_ten(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    served: tuple[FakeLiteLLM, Served, FakeSearXNG, Served],
) -> None:
    atlas = harness(database_url, tmp_path, hindsight, served)
    atlas.overrides["discovery_max_queries"] = 2
    atlas.litellm.script_chat(scout(*QUERIES))
    atlas.script_searches()

    discovery = atlas.run_discovery("photonics-1")

    assert (
        json.loads(atlas.litellm.chat_requests()[0]["messages"][1]["content"])["request"][
            "max_queries"
        ]
        == 2
    )
    assert [q["query"] for q in discovery["queries"]] == [SUBSTRATE, SECOND_SOURCE]
    atlas.overrides["discovery_max_queries"] = 11
    with pytest.raises(ValueError, match="discovery_max_queries"):
        atlas.settings()
    atlas.engine.dispose()


# --- leads ---------------------------------------------------------------------------------------


def test_results_become_tier_c_leads_deduplicated_by_canonical_url(atlas: Discovery) -> None:
    atlas.litellm.script_chat(scout(*QUERIES))
    atlas.script_searches()

    discovery = atlas.run_discovery("photonics-1")

    leads = atlas.leads()
    # The AXT story came back from two queries (a tracking-parameter and a fragment variant):
    # one lead. The FTP result isn't a web page and makes no lead.
    assert leads["total"] == 3
    assert {lead["canonical_url"] for lead in leads["items"]} == {AXT, SUMITOMO, BLOG}
    axt = atlas.lead(AXT)
    assert axt["tier"] == "C"
    assert axt["url"] == (
        "https://www.photonics-news.test/2026/08/axt-expands-inp-substrate-capacity"
        "?utm_source=rss&utm_medium=feed"
    )
    assert axt["title"] == "AXT expands indium phosphide substrate capacity in Beijing"
    assert axt["snippet"].startswith("AXT said it would add InP substrate capacity")
    assert axt["published_date"] == "2026-08-12"
    assert axt["query"] == SUBSTRATE  # the query that found it first
    assert axt["engines"] == ["bing", "brave"]
    assert axt["theme"] == "photonics"
    assert axt["sightings"] == 2
    assert axt["first_seen_at"] <= axt["last_seen_at"]
    sumitomo = atlas.lead(SUMITOMO)
    assert (sumitomo["published_date"], sumitomo["engines"]) == (None, ["bing"])
    blog = atlas.lead(BLOG)
    assert (blog["query"], blog["sightings"]) == (SECOND_SOURCE, 1)
    substrate, second_source, nothing = discovery["queries"]
    assert (substrate["status"], substrate["result_count"], substrate["new_leads"]) == (
        "searched",
        3,
        2,
    )
    assert (second_source["result_count"], second_source["new_leads"]) == (2, 1)
    assert (nothing["result_count"], nothing["new_leads"]) == (0, 0)


def test_a_rerun_deduplicates(atlas: Discovery) -> None:
    atlas.litellm.script_chat(scout(*QUERIES))
    atlas.script_searches()
    atlas.run_discovery("photonics-1")
    first = atlas.lead(AXT)

    atlas.litellm.script_chat(scout(*QUERIES))
    atlas.script_searches()
    rerun = atlas.run_discovery("photonics-2")

    assert atlas.leads()["total"] == 3
    again = atlas.lead(AXT)
    assert (again["id"], again["first_seen_at"]) == (first["id"], first["first_seen_at"])
    assert again["last_seen_at"] > first["last_seen_at"]
    assert again["sightings"] == 4
    assert again["query"] == SUBSTRATE
    assert [q["new_leads"] for q in rerun["queries"]] == [0, 0, 0]
    assert len(atlas.get("/api/v1/discoveries")["items"]) == 2


def test_leads_are_filtered_by_theme_and_paged(atlas: Discovery) -> None:
    atlas.litellm.script_chat(scout(*QUERIES))
    atlas.script_searches()
    atlas.run_discovery("photonics-1")

    assert atlas.leads(theme="photonics")["total"] == 3
    assert atlas.leads(theme="memory")["total"] == 0
    page = atlas.leads(limit=2, offset=0)
    assert (len(page["items"]), page["total"], page["limit"]) == (2, 3, 2)
    assert len(atlas.leads(limit=2, offset=2)["items"]) == 1


def test_leads_never_create_retain_jobs_or_evidence(
    atlas: Discovery, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    atlas.litellm.script_chat(scout(*QUERIES))
    atlas.script_searches()

    atlas.run_discovery("photonics-1")
    atlas.worker_pass()  # anything the discovery might have enqueued would run now

    assert atlas.leads()["total"] == 3
    with atlas.engine.connect() as connection:
        kinds = connection.execute(text("SELECT DISTINCT kind FROM job")).scalars().all()
    assert kinds == ["discover"]
    for table in ("source_document", "source_version", "assertion", "memory_document"):
        assert atlas.count(table) == 0, table
    assert hindsight[0].retained() == []


# --- SearXNG failures ---------------------------------------------------------------------------


def test_unresponsive_engines_and_a_failed_search_are_recorded_and_the_rest_proceed(
    atlas: Discovery,
) -> None:
    atlas.litellm.script_chat(scout(*QUERIES))
    atlas.searxng.script(SUBSTRATE, SearchReply.error(429))
    atlas.searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))
    atlas.searxng.script(NOTHING, SearchReply.of("no-results"))

    discovery = atlas.run_discovery("photonics-1")

    failed, searched, nothing = discovery["queries"]
    assert failed["status"] == "failed"
    assert "HTTP 429" in failed["error"]
    assert (failed["result_count"], failed["new_leads"]) == (None, None)
    assert searched["status"] == "searched"
    assert searched["unresponsive_engines"] == [{"engine": "brave", "reason": "timeout"}]
    assert nothing["unresponsive_engines"] == [
        {"engine": "bing", "reason": "Suspended: access denied"},
        {"engine": "brave", "reason": "timeout"},
    ]
    assert {lead["canonical_url"] for lead in atlas.leads()["items"]} == {AXT, BLOG}
    assert atlas.get("/api/v1/queue")["pause"]["level"] == 0


def test_when_every_search_fails_the_attempt_fails_and_the_retry_reuses_the_scout_s_queries(
    atlas: Discovery,
) -> None:
    atlas.litellm.script_chat(scout(QUERIES[0], QUERIES[1]))
    atlas.searxng.script(SUBSTRATE, SearchReply.error(504), SearchReply.of("no-results"))
    atlas.searxng.script(SECOND_SOURCE, SearchReply.error(502), SearchReply.of("no-results"))
    job_id = atlas.discover("photonics-1")

    atlas.worker_pass()  # the failed attempt is retried in the same pass

    job = atlas.job(job_id)
    assert (job["status"], job["attempts"]) == ("succeeded", 2)
    [failure] = job["failures"]
    assert "every SearXNG search failed" in failure["error"]
    assert atlas.get("/api/v1/queue")["pause"]["level"] == 0  # SearXNG never pauses the queue
    assert len(atlas.litellm.chat_requests()) == 1  # the Scout isn't asked again
    discovery = atlas.get(f"/api/v1/discoveries/{job['artifacts']['discovery_id']}")
    assert [q["status"] for q in discovery["queries"]] == ["searched", "searched"]
    assert discovery["status"] == "completed"
    assert "every SearXNG search failed" in discovery["last_error"]
    run = atlas.get(f"/api/v1/runs/{discovery['run_id']}/role-calls")
    assert len(run["role_calls"]) == 1


def test_without_searxng_the_job_fails_before_any_llm_call(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    served: tuple[FakeLiteLLM, Served, FakeSearXNG, Served],
) -> None:
    atlas = harness(database_url, tmp_path, hindsight, served, with_searxng=False)
    job_id = atlas.discover("photonics-1")

    atlas.worker_pass()

    job = atlas.job(job_id)
    assert job["status"] == "failed"
    assert "ATLAS_SEARXNG_URL" in job["failures"][0]["error"]
    assert atlas.litellm.chat_requests() == []
    atlas.engine.dispose()


def test_an_unknown_theme_fails_the_job(atlas: Discovery) -> None:
    job_id = atlas.discover("memory-1", theme="memory")

    atlas.worker_pass()

    job = atlas.job(job_id)
    assert job["status"] == "failed"
    assert "'memory'" in job["failures"][0]["error"]
    assert atlas.litellm.chat_requests() == []


def test_a_scout_quota_failure_pauses_the_queue(atlas: Discovery) -> None:
    atlas.litellm.script_chat(ChatReply.error(429, "litellm.RateLimitError: rate limit"))
    job_id = atlas.discover("photonics-1")

    atlas.worker_pass()

    job = atlas.job(job_id)
    assert (job["status"], job["attempts"]) == ("queued", 0)
    pause = atlas.get("/api/v1/queue")["pause"]
    assert (pause["paused"], pause["error_class"]) == (True, "quota")
    assert atlas.searxng.searches() == []


def test_an_unknown_discovery_is_not_found(atlas: Discovery) -> None:
    response = atlas.api.get("/api/v1/discoveries/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- metrics -------------------------------------------------------------------------------------


def test_metrics_count_discovery_queries_leads_and_unresponsive_engines(atlas: Discovery) -> None:
    atlas.litellm.script_chat(scout(*QUERIES))
    atlas.searxng.script(SUBSTRATE, SearchReply.error(503))
    atlas.searxng.script(SECOND_SOURCE, SearchReply.of("inp-laser-second-source"))
    atlas.searxng.script(NOTHING, SearchReply.of("no-results"))

    atlas.run_discovery("photonics-1")

    metrics = atlas.metrics()
    queries = "atlas_discovery_queries_total"
    assert metrics[(queries, frozenset({("status", "searched")}))] == 2
    assert metrics[(queries, frozenset({("status", "failed")}))] == 1
    assert metrics[("atlas_leads_total", frozenset())] == 2
    unresponsive = "atlas_discovery_unresponsive_engines_total"
    assert metrics[(unresponsive, frozenset({("engine", "brave")}))] == 2
    assert metrics[(unresponsive, frozenset({("engine", "bing")}))] == 1
