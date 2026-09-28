"""The minimal run record: provenance read at run start, token totals at the finish.

Hindsight is the recorded fake and LiteLLM the `/model/info` fake, both at the transport.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import JsonValue
from sqlalchemy import Engine, create_engine, text

from atlas import __version__
from atlas.audit import Actor
from atlas.bank_template import BankTemplate, apply_template
from atlas.db.migrate import upgrade
from atlas.hindsight import HindsightGateway
from atlas.llm_routes import AliasNotRouted
from atlas.runs import RunNotFound, RunNotStartable, RunRecorder
from atlas.settings import Settings
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import API_KEY, FakeLiteLLM, model_info_fixture

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = BankTemplate.load(REPO_ROOT / "configs" / "hindsight" / "bank-template.json")
BANK_ID = RecordedHindsight().recording("research_template/01-import-dry-run").bank_id


@pytest.fixture
def engine(empty_database_url: str) -> Iterator[Engine]:
    upgrade(empty_database_url)
    engine = create_engine(empty_database_url)
    yield engine
    engine.dispose()


def settings(database_url: str, tmp_path: Path, **values: object) -> Settings:
    return Settings.model_validate(
        {
            "database_url": database_url,
            "actor": "local-researcher",
            "archive_root": tmp_path,
            "hindsight_url": "http://hindsight.test",
            "hindsight_bank_id": BANK_ID,
            "litellm_url": "http://litellm.test",
            "litellm_api_key": API_KEY,
            **values,
        }
    )


def recorder(
    engine: Engine,
    tmp_path: Path,
    hindsight: RecordedHindsight,
    litellm: FakeLiteLLM,
    **values: object,
) -> RunRecorder:
    configured = settings(str(engine.url.render_as_string(hide_password=False)), tmp_path, **values)
    run_recorder = RunRecorder.from_settings(
        configured,
        engine,
        hindsight_transport=hindsight.transport,
        litellm_transport=litellm.transport,
    )
    assert run_recorder is not None
    return run_recorder


def apply_research_template(engine: Engine, hindsight: RecordedHindsight) -> None:
    gateway = HindsightGateway("http://hindsight.test", BANK_ID, transport=hindsight.transport)
    apply_template(engine, gateway, TEMPLATE, Actor("local-researcher"))


def fixture_routes(alias: str) -> list[dict[str, JsonValue]]:
    data = cast(list[dict[str, Any]], model_info_fixture()["data"])
    return [
        {"model": d["litellm_params"]["model"], "model_id": d["model_info"]["id"]}
        for d in data
        if d["model_name"] == alias
    ]


def stored_runs(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text("SELECT * FROM run")).mappings()]


def test_a_run_records_code_hindsight_template_and_routed_models_at_start(
    engine: Engine, tmp_path: Path
) -> None:
    hindsight, litellm = RecordedHindsight(), FakeLiteLLM()
    apply_research_template(engine, hindsight)
    runs = recorder(engine, tmp_path, hindsight, litellm, code_version="0123abc")

    run = runs.start("ingest")

    expected_routes = {alias: fixture_routes(alias) for alias in ("atlas-extract", "atlas-reflect")}
    recorded_version = hindsight.recording("monitoring/02-version").response_object()
    [stored] = stored_runs(engine)
    assert stored["id"] == run.id
    assert stored["kind"] == "ingest"
    assert stored["code_version"] == "0123abc"
    assert stored["hindsight_version"] == recorded_version["api_version"]
    assert stored["template_version"] == TEMPLATE.template_version
    assert stored["routed_models"] == expected_routes
    assert (stored["tokens_in"], stored["tokens_out"], stored["finished_at"]) == (0, 0, None)
    assert (
        run.routed_models["atlas-reflect"][0].model_id
        == expected_routes["atlas-reflect"][0]["model_id"]
    )
    assert [(c.method, c.url.path) for c in litellm.calls] == [("GET", "/model/info")]


def test_finishing_a_run_records_its_token_totals(engine: Engine, tmp_path: Path) -> None:
    hindsight = RecordedHindsight()
    apply_research_template(engine, hindsight)
    runs = recorder(engine, tmp_path, hindsight, FakeLiteLLM())
    started = runs.start("reflect")

    finished = runs.finish(started.id, tokens_in=12_345, tokens_out=678)

    assert (finished.tokens_in, finished.tokens_out) == (12_345, 678)
    assert finished.finished_at is not None
    assert runs.get(started.id) == finished
    with pytest.raises(RunNotFound):
        runs.finish(started.id, tokens_in=1, tokens_out=1)
    with pytest.raises(RunNotFound):
        runs.finish(uuid.uuid4(), tokens_in=1, tokens_out=1)


def test_the_code_version_defaults_to_the_package_version(engine: Engine, tmp_path: Path) -> None:
    hindsight = RecordedHindsight()
    apply_research_template(engine, hindsight)

    run = recorder(engine, tmp_path, hindsight, FakeLiteLLM()).start("ingest")

    assert run.code_version == __version__


def test_a_run_takes_the_latest_applied_template_version(engine: Engine, tmp_path: Path) -> None:
    hindsight = RecordedHindsight()
    apply_research_template(engine, hindsight)
    with engine.begin() as connection:  # a later application of a newer version
        connection.execute(
            text(
                "INSERT INTO bank_template_application (id, bank_id, template_version,"
                " manifest_sha256, dry_run_result, import_result)"
                " VALUES (:id, :bank, '9.9.9', :sha, '{}'::jsonb, '{}'::jsonb)"
            ),
            {"id": uuid.uuid4(), "bank": BANK_ID, "sha": "c" * 64},
        )

    run = recorder(engine, tmp_path, hindsight, FakeLiteLLM()).start("ingest")

    assert run.template_version == "9.9.9"


def test_no_run_starts_before_the_template_is_applied(engine: Engine, tmp_path: Path) -> None:
    litellm = FakeLiteLLM()
    runs = recorder(engine, tmp_path, RecordedHindsight(), litellm)

    with pytest.raises(RunNotStartable, match="apply-template"):
        runs.start("ingest")

    assert stored_runs(engine) == []
    assert litellm.calls == []


def test_no_run_starts_when_an_alias_has_no_route(engine: Engine, tmp_path: Path) -> None:
    hindsight = RecordedHindsight()
    apply_research_template(engine, hindsight)
    runs = recorder(engine, tmp_path, hindsight, FakeLiteLLM().without("atlas-extract"))

    with pytest.raises(AliasNotRouted):
        runs.start("ingest")

    assert stored_runs(engine) == []


def test_aliases_are_read_from_config(engine: Engine, tmp_path: Path) -> None:
    hindsight = RecordedHindsight()
    apply_research_template(engine, hindsight)
    runs = recorder(
        engine, tmp_path, hindsight, FakeLiteLLM(), llm_extract_alias="qwen3-embedding-0.6b"
    )

    run = runs.start("ingest")

    assert set(run.routed_models) == {"qwen3-embedding-0.6b", "atlas-reflect"}


def test_no_recorder_without_both_hindsight_and_litellm(engine: Engine, tmp_path: Path) -> None:
    url = engine.url.render_as_string(hide_password=False)

    assert RunRecorder.from_settings(settings(url, tmp_path, hindsight_url=None), engine) is None
    assert RunRecorder.from_settings(settings(url, tmp_path, litellm_api_key=None), engine) is None
