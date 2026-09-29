"""The LLM route recorder at the LiteLLM transport boundary (`GET /model/info`)."""

from pathlib import Path
from typing import Any, cast

import httpx2
import pytest

from atlas.llm_routes import AliasNotRouted, LiteLLMRoutes, LiteLLMUnavailable, RoutedDeployment
from tests.fakes.litellm import API_KEY, FakeLiteLLM, model_info_fixture
from tests.harness import make_settings

ALIASES = ["atlas-extract", "atlas-reflect"]


def recorder(fake: FakeLiteLLM, api_key: str = API_KEY) -> LiteLLMRoutes:
    return LiteLLMRoutes("http://litellm.test/", api_key, transport=fake.transport)


def fixture_deployments(alias: str) -> list[RoutedDeployment]:
    data = cast(list[dict[str, Any]], model_info_fixture()["data"])
    return [
        RoutedDeployment(
            model=str(d["litellm_params"]["model"]), model_id=str(d["model_info"]["id"])
        )
        for d in data
        if d["model_name"] == alias
    ]


def test_each_alias_maps_to_the_deployment_litellm_routes_it_to() -> None:
    fake = FakeLiteLLM()

    routes = recorder(fake).routes(ALIASES)

    assert routes == {alias: fixture_deployments(alias) for alias in ALIASES}
    assert routes["atlas-extract"][0].model == "minimax/MiniMax-M3"
    assert [(c.method, c.url.path) for c in fake.calls] == [("GET", "/model/info")]
    assert fake.calls[0].headers["Authorization"] == f"Bearer {API_KEY}"


def test_an_alias_without_a_deployment_is_named() -> None:
    fake = FakeLiteLLM().without("atlas-reflect")

    with pytest.raises(AliasNotRouted) as raised:
        recorder(fake).routes(ALIASES)

    assert raised.value.aliases == ["atlas-reflect"]


def test_a_rejected_key_is_unavailable_and_the_key_is_not_echoed() -> None:
    with pytest.raises(LiteLLMUnavailable) as raised:
        recorder(FakeLiteLLM(), api_key="sk-wrong-key").routes(ALIASES)

    assert "401" in str(raised.value)
    assert "sk-wrong-key" not in str(raised.value)


def test_an_unreachable_litellm_is_unavailable() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    routes = LiteLLMRoutes("http://litellm.test", API_KEY, transport=httpx2.MockTransport(refuse))

    with pytest.raises(LiteLLMUnavailable):
        routes.routes(ALIASES)


def test_an_unexpected_response_shape_is_unavailable() -> None:
    fake = FakeLiteLLM(model_info={"models": []})

    with pytest.raises(LiteLLMUnavailable):
        recorder(fake).routes(ALIASES)


def test_litellm_needs_both_its_url_and_key(tmp_path: Path) -> None:
    url = {"litellm_url": "http://litellm.test"}
    key = {"litellm_api_key": API_KEY}

    assert LiteLLMRoutes.from_settings(make_settings(tmp_path)) is None
    assert LiteLLMRoutes.from_settings(make_settings(tmp_path, **url)) is None
    assert LiteLLMRoutes.from_settings(make_settings(tmp_path, **key)) is None
    assert LiteLLMRoutes.from_settings(make_settings(tmp_path, **url, **key)) is not None


def test_the_aliases_come_from_config(tmp_path: Path) -> None:
    custom = make_settings(tmp_path, llm_extract_alias="x-extract", llm_reflect_alias="x-reflect")

    assert make_settings(tmp_path).llm_aliases() == ALIASES
    assert custom.llm_aliases() == ["x-extract", "x-reflect"]
