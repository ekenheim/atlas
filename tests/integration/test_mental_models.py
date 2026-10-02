"""Mental models: Theme status and Bottlenecks, refreshed daily and read with resolved
citations (spec Part B stories 26-29).

Seams: the `atlas` CLI applies the template and enqueues by hand, single worker passes (with
the daily refresh schedule, on a controllable clock) run the refresh jobs, and everything is
observed through `/api/v1` and the requests Hindsight received. Hindsight is the recorded
fake served on localhost with `derive_memories` on (see `tests/integration/test_research.py`);
the template import, the mental models and their refreshes are its documented derivations
(tests/fakes/hindsight.py). **Refreshed contents are written here**, so each quote in them is
chosen to match, or not match, the recorded Lumentum EDGAR fixture. No LLM is called.
"""

import hashlib
import json
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from atlas.api.app import create_app
from atlas.jobs import JobQueue, Pacing, Worker, builtin_registry, builtin_schedules, job_id_for
from atlas.mental_models import REFRESH_KIND, refresh_key
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import FakeLiteLLM, model_info_fixture
from tests.fakes.serve import Served, serve
from tests.harness import (
    BANK,
    ITEM_1,
    LITE_10K,
    LITE_APOSTROPHE,
    QUOTA_ERROR,
    TEMPLATE,
    Atlas,
    Clock,
    assert_source,
    at,
    make_settings,
)

TEMPLATE_FILE: dict[str, Any] = json.loads(TEMPLATE.read_text(encoding="utf-8"))
MODELS = ["theme-status", "bottlenecks"]
DAILY = {
    "refresh_after_consolidation": False,
    "refresh_cron": "0 6 * * *",
    "min_refresh_interval_seconds": 43200,
}
HINDSIGHT_VERSION = (
    RecordedHindsight().recording("monitoring/02-version").response_object()["api_version"]
)
ROUTED_REFLECT = [
    {"model": d["litellm_params"]["model"], "model_id": d["model_info"]["id"]}
    for d in cast(list[dict[str, Any]], model_info_fixture()["data"])
    if d["model_name"] == "atlas-reflect"
]
PLACEHOLDER = "Generating content...\n"  # what 0.10.1 showed before a model's first refresh
ITEM_1A = "part-i-item-1a"


def sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


class Models(Atlas):
    """The research harness, with scheduled worker passes and the API on a clock."""

    def __init__(self, database_url: str, tmp_path: Path, hindsight: str, litellm: str) -> None:
        self.clock = Clock(at("2026-10-01T05:00:00+00:00"))
        super().__init__(
            database_url,
            tmp_path,
            hindsight,
            litellm,
            mental_model_poll_timeout_seconds=0.3,
            mental_model_poll_interval_seconds=0.01,
            # The daily consolidation (ticket 19) stays out of these passes.
            consolidate_at="",
        )
        self.api = TestClient(create_app(self.settings(), clock=self.clock))

    def scheduled_pass(self) -> int:
        """One `atlas worker` pass: the schedules, then the jobs, on the clock."""
        settings = self.settings()
        queue = JobQueue(self.engine, pacing=Pacing.from_settings(settings), clock=self.clock)
        worker = Worker(
            queue,
            builtin_registry(settings, clock=self.clock),
            schedules=builtin_schedules(settings, self.engine),
        )
        return worker.run_once()

    def model(self, mental_model_id: str) -> dict[str, Any]:
        return self.get(f"/api/v1/mental-models/{mental_model_id}")

    def refreshes(self, mental_model_id: str) -> list[dict[str, Any]]:
        return self.model(mental_model_id)["refreshes"]

    def run(self, run_id: str) -> dict[str, Any]:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT * FROM run WHERE id = :id"), {"id": run_id}
            ).mappings()
            return dict(row.one())

    def scheduled_job(self, mental_model_id: str, day: date) -> dict[str, Any]:
        job_id = job_id_for(REFRESH_KIND, refresh_key(BANK, mental_model_id, day))
        return self.get(f"/api/v1/jobs/{job_id}")


@pytest.fixture
def hindsight_fake() -> RecordedHindsight:
    fake = RecordedHindsight()
    fake.derive_memories()
    return fake


@pytest.fixture
def models(
    database_url: str, tmp_path: Path, hindsight: tuple[RecordedHindsight, Served]
) -> Iterator[Models]:
    with serve(FakeLiteLLM().handle) as litellm:
        harness = Models(database_url, tmp_path, hindsight[1].url, litellm.url)
        harness.apply_template()
        harness.ingest_company("lumentum")
        yield harness
        harness.engine.dispose()
        litellm.raise_errors()


def fact_of(models: Models, fake: RecordedHindsight, anchor: str = ITEM_1) -> str:
    return fake.derived_fact(models.section(LITE_10K, "lumentum", anchor)["document_id"])


# --- the template -----------------------------------------------------------------------------


def test_the_template_defines_both_models_refreshed_daily_never_after_consolidation(
    models: Models, fake: RecordedHindsight
) -> None:
    manifest = TEMPLATE_FILE["manifest"]
    theme, bottlenecks = manifest["mental_models"]

    assert TEMPLATE_FILE["template_version"] == "1.4.0"
    assert [(m["id"], m["name"]) for m in (theme, bottlenecks)] == [
        ("theme-status", "Theme status"),
        ("bottlenecks", "Bottlenecks"),
    ]
    assert theme["trigger"] == bottlenecks["trigger"] == DAILY
    assert "supporting" in theme["source_query"] and "opposing" in theme["source_query"]
    # The glossary's Bottleneck test: no qualified second source or substitute in the
    # timeframe, pricing power, and never demand growth alone.
    for phrase in (
        "within the relevant timeframe",
        "no qualified second source or substitute",
        "pricing power",
        "Demand growth alone does not make a Bottleneck",
    ):
        assert phrase in bottlenecks["source_query"]
    # What Hindsight was sent, dry run then import, is the file's.
    imports = fake.requests("POST", "import")
    assert [body["mental_models"] for body in imports] == [manifest["mental_models"]] * 2
    # Each model is in the bank with the template's trigger, and nothing has refreshed it.
    listed = models.get("/api/v1/mental-models")
    assert (listed["bank_id"], listed["template_version"]) == (BANK, "1.4.0")
    assert [m["id"] for m in listed["mental_models"]] == MODELS
    for model in listed["mental_models"]:
        assert model["trigger"] == DAILY
        assert (model["in_bank"], model["content"], model["last_refreshed_at"]) == (
            True,
            PLACEHOLDER,
            None,
        )
        assert model["history"] == [] and model["refreshes"] == []


@pytest.mark.parametrize(
    "trigger",
    [
        {**DAILY, "refresh_after_consolidation": True},
        {k: v for k, v in DAILY.items() if k != "refresh_after_consolidation"},
        {k: v for k, v in DAILY.items() if k != "refresh_cron"},
        {**DAILY, "refresh_cron": "daily"},
        {**DAILY, "min_refresh_interval_seconds": 0},
    ],
    ids=["after-consolidation", "consolidation-unset", "no-cron", "bad-cron", "no-interval"],
)
def test_a_template_whose_models_could_run_away_is_refused_before_any_call(
    models: Models, fake: RecordedHindsight, tmp_path: Path, trigger: dict[str, Any]
) -> None:
    manifest = TEMPLATE_FILE["manifest"]
    theme = {**manifest["mental_models"][0], "trigger": trigger}
    edited = {**TEMPLATE_FILE, "manifest": {**manifest, "mental_models": [theme]}}
    path = tmp_path / "runaway-template.json"
    path.write_text(json.dumps(edited), encoding="utf-8")
    calls = len(fake.calls)

    result = models.cli("hindsight", "apply-template", "--template", str(path))

    assert result.returncode == 2
    assert "invalid bank template" in result.stderr
    assert len(fake.calls) == calls


# --- the daily refresh job --------------------------------------------------------------------


def test_refreshes_run_daily_and_never_inside_the_minimum_interval(
    models: Models, fake: RecordedHindsight
) -> None:
    fact = fact_of(models, fake)
    day_1 = at("2026-10-01T06:30:00+00:00")

    # Before 06:30 UTC nothing is scheduled.
    models.clock.now = day_1 - timedelta(seconds=1)
    assert models.scheduled_pass() == 0
    # At 06:30 each model's refresh is enqueued once and run.
    models.clock.now = day_1
    fake.script_refresh("theme-status", "Theme, day 1.", [fact], refreshed_at=day_1)
    fake.script_refresh("bottlenecks", "Bottlenecks, day 1.", [fact], refreshed_at=day_1)
    assert models.scheduled_pass() == 2
    assert sorted(fake.refreshes_requested()) == sorted(MODELS)
    for mental_model_id, content in [
        ("theme-status", "Theme, day 1."),
        ("bottlenecks", "Bottlenecks, day 1."),
    ]:
        [refresh] = models.refreshes(mental_model_id)
        ignored = ("id", "job_id", "operation_id", "run_id")
        assert {k: refresh[k] for k in refresh if k not in ignored} == {
            "scheduled_for": "2026-10-01",
            "template_version": "1.4.0",
            "min_refresh_interval_seconds": 43200,
            "status": "completed",
            "skip_reason": None,
            "operation_status": "completed",
            "error": None,
            "error_class": None,
            "previous_refreshed_at": None,
            "refreshed_at": "2026-10-01T06:30:00Z",
            "content_sha256": sha256(content),
            "requested_at": "2026-10-01T06:30:00Z",
            "completed_at": "2026-10-01T06:30:00Z",
        }
        job = models.scheduled_job(mental_model_id, date(2026, 10, 1))
        assert (job["status"], job["artifacts"]["outcome"]) == ("succeeded", "completed")
        assert refresh["job_id"] == job["id"]
        assert models.model(mental_model_id)["content"] == content
        # A submitted refresh is an LLM run: it records its run (stories 15 and 32).
        run = models.run(refresh["run_id"])
        assert (run["kind"], run["template_version"]) == (REFRESH_KIND, "1.4.0")
        assert run["hindsight_version"] == HINDSIGHT_VERSION
        assert run["routed_models"]["atlas-reflect"] == ROUTED_REFLECT
        assert run["finished_at"] is not None

    # Later the same day the schedule enqueues nothing more.
    models.clock.advance(hours=3)
    assert models.scheduled_pass() == 0
    # A refresh asked for by hand inside the minimum interval is skipped: no Hindsight call.
    models.enqueue(
        "jobs",
        "enqueue",
        REFRESH_KIND,
        "--key",
        "by-hand",
        "--payload",
        json.dumps({"mental_model_id": "theme-status"}),
    )
    assert models.scheduled_pass() == 1
    assert len(fake.refreshes_requested()) == 2
    skipped, _ = models.refreshes("theme-status")
    assert (skipped["status"], skipped["skip_reason"], skipped["scheduled_for"]) == (
        "skipped",
        "min_interval",
        None,
    )
    assert (skipped["operation_id"], skipped["content_sha256"]) == (None, sha256("Theme, day 1."))
    assert skipped["run_id"] is None  # a skip calls no model

    # Day 2, 06:00: Hindsight's own cron refreshes Theme status after Coherent is retained.
    models.clock.now = at("2026-10-02T06:00:00+00:00")
    models.ingest_company("coherent")
    fake.apply_refresh("theme-status", "Theme, day 2.", [fact], refreshed_at=models.clock.now)
    # 06:30: Atlas finds that refresh inside the interval and records it; Bottlenecks has
    # new memory in scope, so it is refreshed.
    models.clock.now = at("2026-10-02T06:30:00+00:00")
    fake.script_refresh("bottlenecks", "Bottlenecks, day 2.", [fact], refreshed_at=models.clock.now)
    assert models.scheduled_pass() == 2
    assert fake.refreshes_requested()[2:] == ["bottlenecks"]
    found = models.refreshes("theme-status")[0]
    assert (found["status"], found["skip_reason"], found["scheduled_for"]) == (
        "skipped",
        "min_interval",
        "2026-10-02",
    )
    assert (found["refreshed_at"], found["content_sha256"]) == (
        "2026-10-02T06:00:00Z",
        sha256("Theme, day 2."),
    )
    assert models.refreshes("bottlenecks")[0]["status"] == "completed"
    assert models.scheduled_job("theme-status", date(2026, 10, 2))["artifacts"] == {
        "mental_model_id": "theme-status",
        "outcome": "skipped",
        "reason": "min_interval",
        "refresh_id": found["id"],
        "last_refreshed_at": "2026-10-02T06:00:00+00:00",
    }

    # Day 3: nothing new in either model's scope, so neither is refreshed.
    models.clock.now = at("2026-10-03T06:30:00+00:00")
    assert models.scheduled_pass() == 2
    assert len(fake.refreshes_requested()) == 3
    for mental_model_id in MODELS:
        latest = models.refreshes(mental_model_id)[0]
        assert (latest["status"], latest["skip_reason"]) == ("skipped", "not_stale")
    # Each completed refresh is audited, and the chain holds.
    with models.engine.connect() as connection:
        audited = connection.exec_driver_sql(
            "SELECT entity_id FROM audit_event WHERE action = 'mental_model.refreshed'"
        ).scalars()
        assert sorted(audited) == [f"{BANK}:bottlenecks"] * 2 + [f"{BANK}:theme-status"]
    verified = models.cli("audit", "verify")
    assert verified.returncode == 0, verified.stdout + verified.stderr


def test_a_quota_failure_pauses_refreshes_and_the_pause_holds_them_back(
    models: Models, fake: RecordedHindsight
) -> None:
    fact = fact_of(models, fake)
    models.clock.now = at("2026-10-01T06:30:00+00:00")
    fake.script_refresh("theme-status", "Never.", [fact], hold="failed", error_message=QUOTA_ERROR)
    fake.script_refresh("theme-status", "Theme.", [fact], refreshed_at=models.clock.now)
    fake.script_refresh("bottlenecks", "Bottlenecks.", [fact], refreshed_at=models.clock.now)

    models.scheduled_pass()

    pause = models.get("/api/v1/queue")["pause"]
    assert (pause["paused"], pause["error_class"], pause["backoff_seconds"]) == (True, "quota", 60)
    assert REFRESH_KIND in pause["kinds"]
    assert fake.refreshes_requested() == ["theme-status"]
    theme_job = models.scheduled_job("theme-status", date(2026, 10, 1))
    assert (theme_job["status"], theme_job["attempts"]) == ("queued", 0)
    assert theme_job["failures"][-1]["classification"] == "quota"
    [failed] = models.refreshes("theme-status")
    assert (failed["status"], failed["error_class"], failed["error"]) == (
        "failed",
        "quota",
        QUOTA_ERROR,
    )
    # Bottlenecks' job was never claimed: the pause holds refreshes back.
    bottlenecks_job = models.scheduled_job("bottlenecks", date(2026, 10, 1))
    assert (bottlenecks_job["status"], bottlenecks_job["attempts"]) == ("queued", 0)
    models.clock.advance(seconds=59)
    assert models.scheduled_pass() == 0
    assert fake.refreshes_requested() == ["theme-status"]

    models.clock.advance(seconds=1)
    assert models.scheduled_pass() == 2

    assert fake.refreshes_requested() == ["theme-status", "theme-status", "bottlenecks"]
    assert [r["status"] for r in models.refreshes("theme-status")] == ["completed", "failed"]
    assert models.refreshes("bottlenecks")[0]["status"] == "completed"
    pause = models.get("/api/v1/queue")["pause"]
    assert (pause["paused"], pause["level"]) == (False, 0)


# --- reading the models -----------------------------------------------------------------------


def test_the_api_returns_content_history_and_resolved_citations(
    models: Models, fake: RecordedHindsight
) -> None:
    section = models.section(LITE_10K, "lumentum")
    parsed = models.parsed(section["version"]["id"])
    fact = fact_of(models, fake)
    gone = fact_of(models, fake, ITEM_1A)
    paraphrase = "Components are the foundational parts of a system"
    day_1, day_2 = at("2026-10-01T06:30:00+00:00"), at("2026-10-02T06:30:00+00:00")
    first = f'Day 1: Lumentum says "{LITE_APOSTROPHE}".'
    models.clock.now = day_1
    fake.script_refresh("theme-status", first, [fact], refreshed_at=day_1)
    fake.script_refresh("bottlenecks", "No Bottleneck is evidenced yet.", [], refreshed_at=day_1)
    models.scheduled_pass()
    observation = fake.derive_observation([section["document_id"]])
    second = f'Day 2: "{LITE_APOSTROPHE}", and "{paraphrase}".'
    models.clock.now = day_2
    fake.script_refresh("theme-status", second, [observation, fact, gone], refreshed_at=day_2)
    fake.script_refresh("bottlenecks", "Still none.", [], refreshed_at=day_2)
    fake.derive_observation([section["document_id"], section["document_id"]])  # stale again
    models.scheduled_pass()
    fake.forget(gone)

    model = models.model("theme-status")

    assert (model["content"], model["last_refreshed_at"], model["in_bank"]) == (
        second,
        "2026-10-02T06:30:00Z",
        True,
    )
    memories = {c["memory_id"]: c for c in model["citations"] if c["kind"] == "memory"}
    assert (memories[observation]["state"], memories[observation]["memory_type"]) == (
        "resolved",
        "observation",
    )
    assert memories[fact]["state"] == "resolved"
    assert (memories[gone]["state"], memories[gone]["reason"]) == ("broken", "memory_not_found")
    for resolved in (memories[observation], memories[fact]):
        [source] = resolved["sources"]
        assert_source(source, section, models.company("lumentum"))
    quotes = {c["text"]: c for c in model["citations"] if c["kind"] == "quote"}
    span = quotes[LITE_APOSTROPHE]["quote"]
    assert quotes[LITE_APOSTROPHE]["state"] == "resolved"
    assert parsed[span["char_start"] : span["char_end"]] == span["archived_text"] == LITE_APOSTROPHE
    assert (quotes[paraphrase]["state"], quotes[paraphrase]["reason"]) == (
        "unverified",
        "quote_mismatch",
    )
    assert model["counts"] == {"resolved": 3, "unverified": 1, "broken": 1}
    [evidence] = model["evidence"]
    assert (evidence["source_version_id"], evidence["section_anchor"]) == (
        section["version"]["id"],
        ITEM_1,
    )
    assert set(evidence["memory_ids"]) == {observation, fact}
    assert [q["quoted"] for q in evidence["quotes"]] == [LITE_APOSTROPHE]
    assert model["evidence_missing"] is False
    assert model["quote_rule"] == "whitespace-and-typographic-quotes-v1"
    # History, newest first: what each refresh replaced, with its own citations resolved.
    newest, oldest = model["history"]
    assert (newest["changed_at"], newest["previous_content"]) == ("2026-10-02T06:30:00Z", first)
    assert [(c["kind"], c["state"]) for c in newest["citations"]] == [
        ("memory", "resolved"),
        ("quote", "resolved"),
    ]
    assert newest["counts"] == {"resolved": 2, "unverified": 0, "broken": 0}
    assert (oldest["changed_at"], oldest["previous_content"], oldest["citations"]) == (
        "2026-10-01T06:30:00Z",
        PLACEHOLDER,
        [],
    )
    assert [r["status"] for r in model["refreshes"]] == ["completed", "completed"]

    listed = models.get("/api/v1/mental-models")["mental_models"]
    assert [m["id"] for m in listed] == MODELS
    assert listed[0] == model
    bottlenecks = listed[1]
    assert (bottlenecks["content"], bottlenecks["citations"]) == ("Still none.", [])
    assert (bottlenecks["evidence"], bottlenecks["evidence_missing"]) == ([], True)


def test_an_unknown_model_is_404_without_asking_hindsight(
    models: Models, fake: RecordedHindsight
) -> None:
    calls = len(fake.calls)

    response = models.api.get("/api/v1/mental-models/supply-chain")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert len(fake.calls) == calls


def test_mental_models_need_hindsight(database_url: str, tmp_path: Path) -> None:
    settings = make_settings(tmp_path, database_url=database_url)
    api = TestClient(create_app(settings))

    for path in ("/api/v1/mental-models", "/api/v1/mental-models/theme-status"):
        response = api.get(path)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "hindsight_not_configured"
