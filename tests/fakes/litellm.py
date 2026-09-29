"""A transport-level fake LiteLLM proxy: `GET /model/info` and scripted `POST /chat/completions`.

`/model/info` serves `tests/fixtures/litellm/model-info.json`, hand-made in the shape LiteLLM
documents (see `atlas.llm_routes` for the shape and its sources). No real `/model/info`
response has been recorded yet; replace the fixture with a recording (keys and bases
redacted) once one is made against the cluster.

`/chat/completions` answers only with replies a test scripted (`script_chat`), in order:
schema-valid or malformed content (`ChatReply.json` / `ChatReply.text`), an HTTP error in
LiteLLM's error envelope (`ChatReply.error`), or a failed connection (`ChatReply.unreachable`).
The reply is OpenAI's chat completion object, which LiteLLM's proxy returns: `model` is the
requested alias and the deployment hash is the `x-litellm-model-id` header (both seen in the
2026-09-28 dev probe, `docs/research/litellm-dev-probe.md`); errors use LiteLLM's
OpenAI-style envelope `{"error": {"message", "type", "param", "code"}}`. These are
hand-written, not recordings. A chat request with nothing scripted, or any other endpoint,
fails loudly, so the code under test can't make an unplanned LLM call through it.
"""

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx2
from pydantic import JsonValue

MODEL_INFO_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "litellm" / "model-info.json"
)
API_KEY = "sk-atlas-test"  # not a real key
# The deployment hash a scripted chat reply reports in `x-litellm-model-id` (made up).
CHAT_MODEL_ID = "5d1e0c9b8a7f6e5d4c3b2a19081726354a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d"


class UnexpectedLiteLLMCall(AssertionError):
    """The code under test called something the fake doesn't serve, or wasn't scripted."""


def model_info_fixture() -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], json.loads(MODEL_INFO_FIXTURE.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class ChatReply:
    """One scripted answer to `POST /chat/completions`."""

    status: int = 200
    content: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    model_id: str | None = CHAT_MODEL_ID
    error_body: dict[str, JsonValue] | None = None
    drop_connection: bool = False

    @classmethod
    def text(cls, content: str, *, tokens: tuple[int, int] = (120, 40)) -> "ChatReply":
        """A completion whose message content is `content` (valid or not)."""
        return cls(content=content, tokens_in=tokens[0], tokens_out=tokens[1])

    @classmethod
    def json(cls, value: JsonValue, *, tokens: tuple[int, int] = (120, 40)) -> "ChatReply":
        """A completion whose content is `value` serialized as JSON."""
        return cls.text(json.dumps(value), tokens=tokens)

    @classmethod
    def error(cls, status: int, message: str, *, error_type: str | None = None) -> "ChatReply":
        """An HTTP error in LiteLLM's OpenAI-style error envelope."""
        body: dict[str, JsonValue] = {
            "error": {"message": message, "type": error_type, "param": None, "code": str(status)}
        }
        return cls(status=status, error_body=body)

    @classmethod
    def unreachable(cls) -> "ChatReply":
        """The connection fails before any response."""
        return cls(drop_connection=True)


@dataclass
class FakeLiteLLM:
    """Serves `model_info` and scripted chat replies to requests bearing `api_key`; 401 else."""

    model_info: dict[str, JsonValue] = field(default_factory=model_info_fixture)
    api_key: str = API_KEY
    calls: list[httpx2.Request] = field(default_factory=list[httpx2.Request])
    chat_replies: deque[ChatReply] = field(default_factory=deque[ChatReply])

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def without(self, model_name: str) -> "FakeLiteLLM":
        """A copy whose `/model/info` lacks every deployment of `model_name`."""
        data = cast(list[dict[str, JsonValue]], self.model_info["data"])
        kept: list[JsonValue] = [each for each in data if each["model_name"] != model_name]
        return FakeLiteLLM(model_info={"data": kept}, api_key=self.api_key)

    def script_chat(self, *replies: ChatReply) -> "FakeLiteLLM":
        """Queue replies for the next chat completions, answered in order."""
        self.chat_replies.extend(replies)
        return self

    def chat_requests(self) -> list[dict[str, Any]]:
        """The JSON bodies of the chat completions requested so far, oldest first."""
        return [
            cast(dict[str, Any], json.loads(call.content))
            for call in self.calls
            if call.url.path == "/chat/completions"
        ]

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        route = (request.method, request.url.path)
        if route not in {("GET", "/model/info"), ("POST", "/chat/completions")}:
            raise UnexpectedLiteLLMCall(f"{request.method} {request.url.path}")
        if request.headers.get("Authorization") != f"Bearer {self.api_key}":
            return httpx2.Response(401, json={"error": {"message": "Authentication Error"}})
        if route == ("GET", "/model/info"):
            return httpx2.Response(200, json=self.model_info)
        return self._chat(request)

    def _chat(self, request: httpx2.Request) -> httpx2.Response:
        if not self.chat_replies:
            raise UnexpectedLiteLLMCall("POST /chat/completions with no reply scripted")
        reply = self.chat_replies.popleft()
        if reply.drop_connection:
            raise httpx2.ConnectError("connection refused", request=request)
        if reply.status != 200:
            return httpx2.Response(reply.status, json=reply.error_body)
        body = cast(dict[str, Any], json.loads(request.content))
        headers = {"x-litellm-model-id": reply.model_id} if reply.model_id else {}
        completion = {
            "id": f"chatcmpl-fake-{len(self.calls)}",
            "object": "chat.completion",
            "created": 1790000000,
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply.content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": reply.tokens_in,
                "completion_tokens": reply.tokens_out,
                "total_tokens": reply.tokens_in + reply.tokens_out,
            },
        }
        return httpx2.Response(200, json=completion, headers=headers)
