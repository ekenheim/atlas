"""Quota-window pacing: each provider's rolling-window budget holds its job kinds, backfill
never uses the interactive reserve, and a first backfill ingest records its plan and honours
its retain cap (ticket 27).

Seams: the `atlas` CLI enqueues, single worker passes run the jobs with a controllable
pacing clock and the settings under test, and everything is observed through
`/api/v1/queue`, `/api/v1/jobs`, `/api/v1/ingest-plans`, `/metrics` and the requests the
fakes received. Hindsight is the recorded fake with `derive_retains` on (each retain job
submits one operation); LiteLLM and SearXNG are the scripted fakes (the Scout's replies and
their token counts are written here). Nothing live is called.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from atlas.api.app import create_app
from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import ChatReply, FakeLiteLLM
from tests.fakes.searxng import FakeSearXNG, SearchReply
from tests.fakes.serve import Served, serve
from tests.harness import LITE_10K, QUOTA_ERROR, Atlas, Clock, Metrics, at, scrape_metrics

FIVE_HOURS = timedelta(hours=5)
# `consolidate` has a budget of its own, counted by rounds (memory-quality ticket 20).
CODEX_KINDS = ["reflect", "refresh_mental_model", "replay", "reprocess", "retain"]
# With ATLAS_RETAIN_EXTRACTOR set, retains leave the Codex budget for their own.
CODEX_KINDS_WITHOUT_RETAINS = ["reflect", "refresh_mental_model", "replay"]
ROUTED_RETAIN_KINDS = ["reprocess", "retain"]
MINIMAX_KINDS = [
    "discover",
    "extract_claims",
    "investigation_task",
    "review_relationships",
    "triage",
    "triage_audit",
]
LUMENTUM = "https://www.sec.gov/Archives/edgar/data/1633978"
LUMENTUM_DOCUMENTS = {
    f"{LUMENTUM}/000162828026055726/lite-20260811.htm",  # 8-K, filed 2026-08-11
    f"{LUMENTUM}/000162828026055726/lite_ex991xq4fy26.htm",  # its EX-99.1
    f"{LUMENTUM}/000162828026057358/lite-20260627.htm",  # 10-K
    f"{LUMENTUM}/000162828026030777/lite-20260328.htm",  # 10-Q
    "https://data.sec.gov/api/xbrl/companyfacts/CIK0001633978.json",
}
QUERY = "indium phosphide substrate capacity expansion 2026"


class Paced:
    """The Atlas harness, with worker passes and the API on a controllable pacing clock."""

    def __init__(self, atlas: Atlas, clock: Clock) -> None:
        self.atlas = atlas
        self.clock = clock
        self.api = TestClient(create_app(atlas.settings(), clock=clock))

    def worker_pass(self) -> int:
        settings = self.atlas.settings()
        queue = JobQueue(self.atlas.engine, pacing=Pacing.from_settings(settings), clock=self.clock)
        return Worker(queue, builtin_registry(settings)).run_once()

    def get(self, path: str, **params: Any) -> Any:
        response = self.api.get(path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def job(self, job_id: str) -> dict[str, Any]:
        return self.get(f"/api/v1/jobs/{job_id}")

    def budget(self, provider: str) -> dict[str, Any]:
        (found,) = [b for b in self.get("/api/v1/queue")["budgets"] if b["provider"] == provider]
        return found

    def providers(self) -> list[str]:
        return [b["provider"] for b in self.get("/api/v1/queue")["budgets"]]

    def pending(self, kind: str) -> dict[str, Any]:
        (found,) = [p for p in self.get("/api/v1/queue")["pending"] if p["kind"] == kind]
        return found

    def statuses(self, job_ids: list[str]) -> list[str]:
        return sorted(self.job(i)["status"] for i in job_ids)

    def metrics(self) -> Metrics:
        return scrape_metrics(self.api)


def audit_actions(paced: Paced) -> list[str]:
    """Every audit event's action, oldest first."""
    with paced.atlas.engine.connect() as connection:
        rows = connection.exec_driver_sql("SELECT action FROM audit_event ORDER BY id").all()
    return [row[0] for row in rows]


def labels(**pairs: str) -> frozenset[tuple[str, str]]:
    return frozenset(pairs.items())


@pytest.fixture
def clock() -> Clock:
    # Real time, so the database's lease clock and the pacing clock start together.
    return Clock(datetime.now(UTC).replace(microsecond=0))


def codex_paced(
    database_url: str, tmp_path: Path, hindsight_url: str, clock: Clock, **budgets: Any
) -> Paced:
    atlas = Atlas(database_url, tmp_path, hindsight_url, **budgets)
    atlas.apply_template()
    return Paced(atlas, clock)


# --- Codex: retain operations per window ------------------------------------------------------


def test_a_backfill_over_the_codex_budget_spreads_over_two_windows_behind_interactive_work(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    fake = hindsight[0]
    # 4 operations per window; backfill stops at 3, keeping one for interactive work.
    paced = codex_paced(
        database_url,
        tmp_path,
        hindsight[1].url,
        clock,
        codex_budget_operations=4,
        budget_interactive_reserve=0.25,
    )
    backfill = paced.atlas.enqueue("ingest", "--company", "lumentum", "--key", "lite", "--backfill")
    start = clock.now

    paced.worker_pass()

    # The backfill ingest's four retains: three submitted their operation, one is held.
    retains = paced.job(backfill)["artifacts"]["retain_jobs"]
    assert len(retains) == 4
    assert paced.statuses(retains) == ["queued", "succeeded", "succeeded", "succeeded"]
    assert len(fake.retained()) == 3
    codex = paced.budget("codex")
    assert codex == {
        "provider": "codex",
        "unit": "operations",
        "window_seconds": 5 * 3600,
        "used": 3,
        "budget": 4,
        "backfill_limit": 3,
        "interactive_held": False,
        "backfill_held": True,
        "interactive_resumes_at": None,
        "backfill_resumes_at": codex["backfill_resumes_at"],
        "kinds": CODEX_KINDS,
    }
    assert at(codex["backfill_resumes_at"]) == start + FIVE_HOURS
    assert paced.pending("retain") == {
        "kind": "retain",
        "queued": 1,
        "running": 0,
        "backfill_queued": 1,
        "paused": False,
        "budget_held": 1,
    }
    metrics = paced.metrics()
    assert metrics[("atlas_budget_used", labels(provider="codex", unit="operations"))] == 3
    assert metrics[("atlas_budget_limit", labels(provider="codex", job_class="backfill"))] == 3
    assert metrics[("atlas_budget_limit", labels(provider="codex", job_class="interactive"))] == 4
    assert metrics[("atlas_budget_window_seconds", labels())] == 5 * 3600
    assert metrics[("atlas_budget_usage_total", labels(provider="codex"))] == 3
    held = labels(provider="codex", kind="retain", job_class="backfill")
    assert metrics[("atlas_queue_jobs_held_by_budget", held)] == 1

    # The owner's interactive ingest runs in the reserve, while the backfill waits.
    interactive = paced.atlas.enqueue(
        "ingest", "--company", "coherent", "--key", "cohr", "--forms", "10-K"
    )
    paced.worker_pass()

    (own,) = paced.job(interactive)["artifacts"]["retain_jobs"]
    assert paced.job(own)["status"] == "succeeded"
    assert paced.statuses(retains).count("queued") == 1
    codex = paced.budget("codex")
    assert (codex["used"], codex["interactive_held"]) == (4, True)
    assert at(codex["interactive_resumes_at"]) == start + FIVE_HOURS

    # Just before the window rolls nothing more is submitted; once it has, the rest is.
    clock.now = start + FIVE_HOURS - timedelta(seconds=1)
    paced.worker_pass()
    assert paced.statuses(retains).count("queued") == 1
    assert len(fake.retained()) == 4

    clock.now = start + FIVE_HOURS
    paced.worker_pass()

    assert paced.statuses(retains) == ["succeeded"] * 4
    assert len(fake.retained()) == 5
    codex = paced.budget("codex")
    assert (codex["used"], codex["backfill_held"], codex["backfill_resumes_at"]) == (1, False, None)
    assert paced.metrics()[("atlas_budget_usage_total", labels(provider="codex"))] == 5


def test_each_reflect_and_each_refresh_atlas_submits_spends_one_codex_operation(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    fake = hindsight[0]
    fake.derive_memories()  # reflect answers are scripted (tests/fakes/hindsight.py)
    paced = codex_paced(database_url, tmp_path, hindsight[1].url, clock, codex_budget_operations=3)
    model = json.dumps({"mental_model_id": "theme-status"})
    start = clock.now

    def reflect(key: str) -> str:
        response = paced.api.post(
            "/api/v1/memory/reflect",
            json={
                "question": f"What constrains optics? ({key})",
                "scope": {"theme_ids": ["photonics"]},
            },
        )
        assert response.status_code == 202, response.text
        return response.json()["job_id"]

    fake.script_reflect("An answer.", [])
    first = reflect("first")
    paced.worker_pass()
    assert paced.job(first)["status"] == "succeeded"
    assert paced.budget("codex")["used"] == 1

    fake.script_refresh("theme-status", "Theme.", [], refreshed_at=start)
    refresh = paced.atlas.enqueue(
        "jobs", "enqueue", "refresh_mental_model", "--key", "one", "--payload", model
    )
    paced.worker_pass()
    assert paced.job(refresh)["artifacts"]["outcome"] == "completed"
    assert paced.budget("codex")["used"] == 2

    # A refresh skipped inside the model's interval asks Hindsight for nothing and spends
    # nothing.
    skipped = paced.atlas.enqueue(
        "jobs", "enqueue", "refresh_mental_model", "--key", "two", "--payload", model
    )
    paced.worker_pass()
    assert paced.job(skipped)["artifacts"]["outcome"] == "skipped"
    assert paced.budget("codex")["used"] == 2

    fake.script_reflect("Another answer.", [])
    second = reflect("second")
    paced.worker_pass()
    assert paced.job(second)["status"] == "succeeded"
    codex = paced.budget("codex")
    assert (codex["used"], codex["interactive_held"]) == (3, True)
    assert at(codex["interactive_resumes_at"]) == start + FIVE_HOURS
    assert paced.metrics()[("atlas_budget_usage_total", labels(provider="codex"))] == 3

    # The spent window holds the next reflect and the next refresh, as it holds a retain.
    held = reflect("held")
    held_refresh = paced.atlas.enqueue(
        "jobs", "enqueue", "refresh_mental_model", "--key", "three", "--payload", model
    )
    paced.worker_pass()
    assert paced.statuses([held, held_refresh]) == ["queued", "queued"]
    assert paced.pending("reflect")["budget_held"] == 1
    assert paced.pending("refresh_mental_model")["budget_held"] == 1
    assert len(fake.requests("POST", "reflect")) == 2
    assert fake.refreshes_requested() == ["theme-status"]
    paced.atlas.engine.dispose()


def test_a_429_still_pauses_the_queue_under_the_budgets(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    fake = hindsight[0]
    fake.hold_retains("failed", where=lambda _: True, error_message=QUOTA_ERROR, times=1)
    paced = codex_paced(database_url, tmp_path, hindsight[1].url, clock)
    paced.atlas.enqueue("ingest", "--company", "coherent", "--key", "cohr", "--forms", "10-K")

    paced.worker_pass()

    pause = paced.get("/api/v1/queue")["pause"]
    assert (pause["paused"], pause["error_class"], pause["backoff_seconds"]) == (True, "quota", 60)
    # The failed operation was submitted, so it counts against the window.
    assert paced.budget("codex")["used"] == 1
    assert paced.budget("codex")["backfill_held"] is False

    clock.advance(seconds=60)
    paced.worker_pass()

    assert paced.get("/api/v1/queue")["pause"]["level"] == 0
    assert paced.budget("codex")["used"] == 2  # the resubmission


# --- retains routed to MiniMax: their own operations budget -----------------------------------


def test_with_the_extractor_set_retains_spend_their_own_budget_and_reflect_stays_on_codex(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    fake = hindsight[0]
    # Before the switch, a retain spends the window's one Codex operation.
    atlas = Atlas(database_url, tmp_path, hindsight[1].url, codex_budget_operations=1)
    atlas.apply_template()
    before = Paced(atlas, clock)
    atlas.enqueue("ingest", "--company", "coherent", "--key", "cohr", "--forms", "10-K")
    before.worker_pass()
    # As before the setting (the consolidation rounds' budget is always there: ticket 20).
    assert before.providers() == ["codex", "hindsight_consolidation", "minimax", "tradingview"]
    codex = before.budget("codex")
    assert (codex["used"], codex["interactive_held"], codex["kinds"]) == (1, True, CODEX_KINDS)

    # The owner switches the extractor on: two routed operations per window, backfill one.
    atlas.overrides |= {
        "retain_extractor": "minimax",
        "retain_budget_operations": 2,
        "budget_interactive_reserve": 0.5,
    }
    paced = Paced(atlas, clock)
    reflect = atlas.enqueue("jobs", "enqueue", "reflect", "--key", "held", "--payload", "{}")
    ingest = atlas.enqueue("ingest", "--company", "lumentum", "--key", "lite")
    start = clock.now

    paced.worker_pass()

    # The spent Codex window doesn't hold the retains: two are submitted, and then their own
    # budget holds the other two. The reflect waits for Codex.
    retains = paced.job(ingest)["artifacts"]["retain_jobs"]
    assert paced.statuses(retains) == ["queued", "queued", "succeeded", "succeeded"]
    assert len(fake.retained()) == 3
    assert paced.job(reflect)["status"] == "queued"
    assert paced.providers() == [
        "codex",
        "hindsight_consolidation",
        "hindsight_minimax",
        "minimax",
        "tradingview",
    ]
    routed = paced.budget("hindsight_minimax")
    assert routed == {
        "provider": "hindsight_minimax",
        "unit": "operations",
        "window_seconds": 5 * 3600,
        "used": 2,
        "budget": 2,
        "backfill_limit": 1,
        "interactive_held": True,
        "backfill_held": True,
        "interactive_resumes_at": routed["interactive_resumes_at"],
        "backfill_resumes_at": routed["backfill_resumes_at"],
        "kinds": ROUTED_RETAIN_KINDS,
    }
    assert at(routed["interactive_resumes_at"]) == start + FIVE_HOURS
    assert at(routed["backfill_resumes_at"]) == start + FIVE_HOURS
    codex = paced.budget("codex")
    assert (codex["used"], codex["budget"], codex["interactive_held"]) == (1, 1, True)
    assert codex["kinds"] == CODEX_KINDS_WITHOUT_RETAINS
    assert paced.pending("retain")["budget_held"] == 2
    assert paced.pending("reflect")["budget_held"] == 1
    metrics = paced.metrics()
    used = labels(provider="hindsight_minimax", unit="operations")
    assert metrics[("atlas_budget_used", used)] == 2
    limit = ("atlas_budget_limit", labels(provider="hindsight_minimax", job_class="interactive"))
    assert metrics[limit] == 2
    limit = ("atlas_budget_limit", labels(provider="hindsight_minimax", job_class="backfill"))
    assert metrics[limit] == 1
    assert metrics[("atlas_budget_usage_total", labels(provider="hindsight_minimax"))] == 2
    assert metrics[("atlas_budget_usage_total", labels(provider="codex"))] == 1
    held = labels(provider="hindsight_minimax", kind="retain", job_class="interactive")
    assert metrics[("atlas_queue_jobs_held_by_budget", held)] == 2
    held = labels(provider="codex", kind="reflect", job_class="interactive")
    assert metrics[("atlas_queue_jobs_held_by_budget", held)] == 1

    # Just before the window rolls nothing more is submitted.
    clock.now = start + FIVE_HOURS - timedelta(seconds=1)
    paced.worker_pass()
    assert len(fake.retained()) == 3
    assert paced.job(reflect)["status"] == "queued"
    atlas.engine.dispose()


def test_a_routed_backfill_keeps_the_interactive_reserve_of_the_retain_budget(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    fake = hindsight[0]
    # 4 routed operations per window; backfill stops at 3. Codex has room for one only.
    paced = codex_paced(
        database_url,
        tmp_path,
        hindsight[1].url,
        clock,
        retain_extractor="minimax",
        retain_budget_operations=4,
        codex_budget_operations=1,
        budget_interactive_reserve=0.25,
    )
    backfill = paced.atlas.enqueue("ingest", "--company", "lumentum", "--key", "lite", "--backfill")
    start = clock.now

    paced.worker_pass()

    retains = paced.job(backfill)["artifacts"]["retain_jobs"]
    assert paced.statuses(retains) == ["queued", "succeeded", "succeeded", "succeeded"]
    routed = paced.budget("hindsight_minimax")
    assert (routed["used"], routed["budget"], routed["backfill_limit"]) == (3, 4, 3)
    assert (routed["interactive_held"], routed["backfill_held"]) == (False, True)
    assert at(routed["backfill_resumes_at"]) == start + FIVE_HOURS
    assert paced.budget("codex")["used"] == 0  # routed retains spend no Codex operation
    assert paced.pending("retain")["budget_held"] == 1

    # The owner's own ingest runs in the reserve while the backfill waits.
    interactive = paced.atlas.enqueue(
        "ingest", "--company", "coherent", "--key", "cohr", "--forms", "10-K"
    )
    paced.worker_pass()

    (own,) = paced.job(interactive)["artifacts"]["retain_jobs"]
    assert paced.job(own)["status"] == "succeeded"
    assert paced.statuses(retains).count("queued") == 1
    routed = paced.budget("hindsight_minimax")
    assert (routed["used"], routed["interactive_held"]) == (4, True)

    clock.now = start + FIVE_HOURS
    paced.worker_pass()

    assert paced.statuses(retains) == ["succeeded"] * 4
    assert len(fake.retained()) == 5
    assert paced.budget("hindsight_minimax")["used"] == 1
    assert paced.budget("codex")["used"] == 0


def test_switched_back_a_reprocess_runs_on_codex_and_records_no_extractor(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    fake = hindsight[0]
    fake.report_zero_facts(lambda document_id: document_id.endswith(":part-i-item-1b"))
    # One routed operation per window: the 10-K's retain spends it, so its zero-fact
    # section's reprocess waits.
    atlas = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        retain_extractor="minimax",
        retain_budget_operations=1,
    )
    atlas.apply_template()
    routed = Paced(atlas, clock)
    atlas.enqueue("ingest", "--company", "lumentum", "--key", "lite", "--forms", "10-K")

    routed.worker_pass()

    assert routed.pending("reprocess")["budget_held"] == 1
    ten_k = atlas.version(LITE_10K)["id"]
    memory = atlas.memory(ten_k)
    assert {d["extractor"] for d in memory["documents"]} == {"minimax"}
    assert memory["counts"]["pending"] == 1  # the zero-fact section, awaiting its reprocess

    # The owner unsets ATLAS_RETAIN_EXTRACTOR: the reprocess is a Codex kind again.
    atlas.overrides["retain_extractor"] = None
    unrouted = Paced(atlas, clock)
    unrouted.worker_pass()

    memory = atlas.memory(ten_k)
    sections = {d["section_anchor"]: d for d in memory["documents"]}
    reprocessed = sections.pop("part-i-item-1b")
    # The section records the extractor of its last attempt: none, the primary.
    assert (reprocessed["retain_state"], reprocessed["extractor"]) == ("zero_fact", None)
    assert {d["extractor"] for d in sections.values()} == {"minimax"}
    assert [(o["kind"], o["extractor"]) for o in memory["operations"]] == [
        ("retain", "minimax"),
        ("reprocess", None),
    ]
    first, again = [i for b in fake.retained() for i in b if i["document_id"].endswith("-1b")]
    assert first["metadata"]["extractor"] == "minimax"
    assert "extractor" not in again["metadata"]
    # Each operation counts once, against the budget of the extractor it asked for.
    assert unrouted.providers() == ["codex", "hindsight_consolidation", "minimax", "tradingview"]
    codex = unrouted.budget("codex")
    assert (codex["used"], codex["kinds"]) == (1, CODEX_KINDS)
    metrics = unrouted.metrics()
    assert metrics[("atlas_budget_usage_total", labels(provider="codex"))] == 1
    atlas.engine.dispose()


# --- MiniMax: recorded tokens per window ------------------------------------------------------


@pytest.fixture
def role_fakes() -> Iterator[tuple[FakeLiteLLM, Served, FakeSearXNG, Served]]:
    litellm, searxng = FakeLiteLLM(), FakeSearXNG()
    with serve(litellm.handle) as litellm_served, serve(searxng.handle) as searxng_served:
        yield litellm, litellm_served, searxng, searxng_served
        litellm_served.raise_errors()
        searxng_served.raise_errors()


def test_role_calls_are_held_by_their_recorded_minimax_tokens(
    database_url: str,
    tmp_path: Path,
    hindsight: tuple[RecordedHindsight, Served],
    role_fakes: tuple[FakeLiteLLM, Served, FakeSearXNG, Served],
    clock: Clock,
) -> None:
    litellm, litellm_served, searxng, searxng_served = role_fakes
    # 2,000 tokens per window; backfill stops at 1,000. Each Scout call spends 1,020.
    atlas = Atlas(
        database_url,
        tmp_path,
        hindsight[1].url,
        litellm_served.url,
        searxng_url=searxng_served.url,
        minimax_budget_tokens=2000,
        budget_interactive_reserve=0.5,
    )
    atlas.apply_template()
    paced = Paced(atlas, clock)
    scout = ChatReply.json({"queries": [{"query": QUERY, "purpose": None}]}, tokens=(900, 120))
    litellm.script_chat(scout, scout, scout)
    searxng.script(QUERY, *[SearchReply.of("no-results")] * 3)

    def discover(key: str, *backfill: str) -> str:
        payload = json.dumps({"theme": "photonics", "question": "Who makes InP substrates?"})
        return atlas.enqueue(
            "jobs", "enqueue", "discover", "--key", key, "--payload", payload, *backfill
        )

    first = discover("backfill-1", "--backfill")
    second = discover("backfill-2", "--backfill")
    start = clock.now

    paced.worker_pass()

    # The first backfill discovery spent past the backfill limit, so the second waits.
    assert [paced.job(i)["status"] for i in (first, second)] == ["succeeded", "queued"]

    # The owner's own discovery runs in the reserve (interactive work is claimed before
    # backfill anyway) and uses up the window.
    own = discover("interactive")
    paced.worker_pass()
    assert [paced.job(i)["status"] for i in (first, second, own)] == [
        "succeeded",
        "queued",
        "succeeded",
    ]
    assert len(litellm.chat_requests()) == 2
    minimax = paced.budget("minimax")
    assert {k: minimax[k] for k in ("unit", "used", "budget", "backfill_limit", "kinds")} == {
        "unit": "tokens",
        "used": 2040,
        "budget": 2000,
        "backfill_limit": 1000,
        "kinds": MINIMAX_KINDS,
    }
    assert (minimax["interactive_held"], minimax["backfill_held"]) == (True, True)
    assert at(minimax["backfill_resumes_at"]) == start + FIVE_HOURS
    assert paced.pending("discover")["budget_held"] == 1
    assert paced.budget("codex")["used"] == 0  # role calls spend no Codex
    metrics = paced.metrics()
    assert metrics[("atlas_budget_used", labels(provider="minimax", unit="tokens"))] == 2040
    held = labels(provider="minimax", kind="discover", job_class="backfill")
    assert metrics[("atlas_queue_jobs_held_by_budget", held)] == 1

    clock.now = start + FIVE_HOURS
    paced.worker_pass()

    assert paced.job(second)["status"] == "succeeded"
    assert paced.budget("minimax")["used"] == 1020
    atlas.engine.dispose()


# --- the staged rollout: ingest plans and the retain cap --------------------------------------


def test_a_first_backfill_ingest_records_its_plan_and_retains_up_to_its_cap(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    paced = codex_paced(database_url, tmp_path, hindsight[1].url, clock)
    first = paced.atlas.enqueue(
        "ingest", "--company", "lumentum", "--key", "first", "--backfill", "--max-retains", "3"
    )

    paced.worker_pass()

    (plan,) = paced.get("/api/v1/ingest-plans", company="lumentum")["items"]
    job = paced.job(first)
    assert plan["id"] == job["artifacts"]["ingest_plan_id"]
    assert (plan["job_id"], plan["company"]) == (first, "lumentum")
    assert plan["company_id"] == job["artifacts"]["company_id"]
    # Every discovered document (after the lookback and 8-K selection), and one retain
    # operation per parsed filing document; companyfacts is normalized, not retained.
    assert {d["url"] for d in plan["documents"]} == LUMENTUM_DOCUMENTS
    assert (plan["document_count"], plan["estimated_retain_operations"]) == (5, 4)
    assert plan["max_retains"] == 3
    assert at(plan["since"]) < clock.now - timedelta(days=700)  # the default lookback
    assert plan["forms"] is None
    # The cap: the three newest versions (the 10-K of 2026-08-17, then the 8-K of 2026-08-11
    # and its exhibit) are retained; the 10-Q of 2026-05-05 is deferred.
    retained = [
        paced.job(i)["payload"]["source_version_id"] for i in job["artifacts"]["retain_jobs"]
    ]
    assert job["artifacts"]["retains_deferred"] == 1
    urls = {
        paced.get(f"/api/v1/source-versions/{v}")["source_document"]["canonical_url"]
        for v in retained
    }
    assert urls == {
        f"{LUMENTUM}/000162828026057358/lite-20260627.htm",
        f"{LUMENTUM}/000162828026055726/lite-20260811.htm",
        f"{LUMENTUM}/000162828026055726/lite_ex991xq4fy26.htm",
    }
    # The plan was recorded before anything was fetched or retained.
    actions = audit_actions(paced)
    planned = actions.index("ingest_plan.recorded")
    assert planned < actions.index("source_version.created")
    assert planned < actions.index("hindsight_operation.submitted")

    # A later capped ingest records no new plan and retains the deferred 10-Q.
    second = paced.atlas.enqueue(
        "ingest", "--company", "lumentum", "--key", "second", "--backfill", "--max-retains", "2"
    )
    paced.worker_pass()

    artifacts = paced.job(second)["artifacts"]
    assert "ingest_plan_id" not in artifacts
    (retain,) = artifacts["retain_jobs"]
    assert artifacts["retains_deferred"] == 0
    version = paced.get(
        f"/api/v1/source-versions/{paced.job(retain)['payload']['source_version_id']}"
    )
    assert (
        version["source_document"]["canonical_url"]
        == f"{LUMENTUM}/000162828026030777/lite-20260328.htm"
    )
    assert len(paced.get("/api/v1/ingest-plans")["items"]) == 1
    assert paced.budget("codex")["used"] == 4


def test_only_a_first_backfill_ingest_records_a_plan(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served], clock: Clock
) -> None:
    paced = codex_paced(database_url, tmp_path, hindsight[1].url, clock)
    interactive = paced.atlas.enqueue("ingest", "--company", "coherent", "--key", "cohr")
    paced.worker_pass()
    later = paced.atlas.enqueue("ingest", "--company", "coherent", "--key", "again", "--backfill")
    paced.worker_pass()

    assert paced.get("/api/v1/ingest-plans")["items"] == []
    assert "ingest_plan_id" not in paced.job(interactive)["artifacts"]
    assert "retains_deferred" not in paced.job(later)["artifacts"]


def test_the_retain_cap_is_refused_for_a_company_the_sec_ingest_does_not_fetch(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> None:
    atlas = Atlas(database_url, tmp_path, hindsight[1].url)

    refused = atlas.cli("ingest", "--company", "innolight", "--backfill", "--max-retains", "3")

    assert refused.returncode == 2
    assert "--max-retains applies to SEC filers only" in refused.stderr
