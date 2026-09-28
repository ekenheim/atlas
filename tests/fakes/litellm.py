"""A transport-level fake LiteLLM proxy that serves only `GET /model/info`.

The response is `tests/fixtures/litellm/model-info.json`, hand-made in the shape LiteLLM
documents (see `atlas.llm_routes` for the shape and its sources). No real `/model/info`
response has been recorded yet; replace the fixture with a recording (keys and bases
redacted) once one is made against the cluster. Anything but `/model/info` fails loudly, so
the code under test can't make an LLM call through it.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import httpx2
from pydantic import JsonValue

MODEL_INFO_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "litellm" / "model-info.json"
)
API_KEY = "sk-atlas-test"  # not a real key


class UnexpectedLiteLLMCall(AssertionError):
    """The code under test called something other than `GET /model/info`."""


def model_info_fixture() -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], json.loads(MODEL_INFO_FIXTURE.read_text(encoding="utf-8")))


@dataclass
class FakeLiteLLM:
    """Serves `model_info` to requests bearing `api_key`; 401 to any other key."""

    model_info: dict[str, JsonValue] = field(default_factory=model_info_fixture)
    api_key: str = API_KEY
    calls: list[httpx2.Request] = field(default_factory=list[httpx2.Request])

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def without(self, model_name: str) -> "FakeLiteLLM":
        """A copy whose `/model/info` lacks every deployment of `model_name`."""
        data = cast(list[dict[str, JsonValue]], self.model_info["data"])
        kept: list[JsonValue] = [each for each in data if each["model_name"] != model_name]
        return FakeLiteLLM(model_info={"data": kept}, api_key=self.api_key)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        if (request.method, request.url.path) != ("GET", "/model/info"):
            raise UnexpectedLiteLLMCall(f"{request.method} {request.url.path}")
        if request.headers.get("Authorization") != f"Bearer {self.api_key}":
            return httpx2.Response(401, json={"error": {"message": "Authentication Error"}})
        return httpx2.Response(200, json=self.model_info)
