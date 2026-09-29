"""The minimal run record: provenance read at run start, token totals at the finish.

Hindsight is the recorded fake and LiteLLM the `/model/info` fake, both at the transport.
"""

import uuid
from pathlib import Path
from typing import Any, cast

import httpx2
import pytest
from pydantic import JsonValue
from sqlalchemy import Engine, text

from atlas import __version__
from atlas.audit import Actor
from atlas.bank_template import BankTemplate, apply_template
from atlas.hindsight import HindsightGateway
from atlas.llm_routes import AliasNotRouted
from atlas.runs import RunNotFound, RunNotStartable, RunRecorder
from atlas.settings import Settings
from tests.fakes.hindsight import RecordedHindsight
from tests.fakes.litellm import API_KEY, FakeLiteLLM, model_info_fixture
from tests.harness import BANK, TEMPLATE, make_settings

BANK_TEMPLATE = BankTemplate.load(TEMPLATE)


def settings(database_url: str, tmp_path: Path, **values: object) -> Settings:
    providers: dict[str, object] = {
        "hindsight_url": "http://hindsight.test",
        "hindsight_bank_id": BANK,
        "litellm_url": "http://litellm.test",
        "litellm_api_key": API_KEY,
    }
    return make_settings(tmp_path, database_url=database_url, **(providers | values))


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
    gateway = HindsightGateway("http://hindsight.test", BANK, transport=hindsight.transport)
    apply_template(engine, gateway, BANK_TEMPLATE, Actor("local-researcher"))


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
    assert stored["template_version"] == BANK_TEMPLATE.template_version
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
            {"id": uuid.uuid4(), "bank": BANK, "sha": "c" * 64},
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


def behind_a_v1_only_route(hindsight: RecordedHindsight) -> httpx2.MockTransport:
    """The home cluster's HTTPRoute: only /v1 reaches the API; /version gets the UI's 404 page."""

    def handle(request: httpx2.Request) -> httpx2.Response:
        if not request.url.path.startswith("/v1/"):
            return httpx2.Response(404, text="<html>control plane</html>")
        return hindsight.transport.handle_request(request)

    return httpx2.MockTransport(handle)


def v1_only_recorder(
    engine: Engine, tmp_path: Path, hindsight: RecordedHindsight, **values: object
) -> RunRecorder:
    configured = settings(str(engine.url.render_as_string(hide_password=False)), tmp_path, **values)
    run_recorder = RunRecorder.from_settings(
        configured,
        engine,
        hindsight_transport=behind_a_v1_only_route(hindsight),
        litellm_transport=FakeLiteLLM().transport,
    )
    assert run_recorder is not None
    return run_recorder


def test_behind_a_v1_only_route_a_run_records_the_declared_hindsight_version(
    engine: Engine, tmp_path: Path
) -> None:
    hindsight = RecordedHindsight()
    apply_research_template(engine, hindsight)
    runs = v1_only_recorder(engine, tmp_path, hindsight, hindsight_version="0.10.1")

    runs.start("reflect")

    [stored] = stored_runs(engine)
    assert stored["hindsight_version"] == "0.10.1 (declared)"


def test_behind_a_v1_only_route_no_run_starts_without_a_declared_version(
    engine: Engine, tmp_path: Path
) -> None:
    hindsight = RecordedHindsight()
    apply_research_template(engine, hindsight)
    runs = v1_only_recorder(engine, tmp_path, hindsight)

    with pytest.raises(RunNotStartable, match="ATLAS_HINDSIGHT_VERSION"):
        runs.start("reflect")

    assert stored_runs(engine) == []
