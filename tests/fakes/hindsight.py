"""A transport-level fake Hindsight 0.10.1, replaying the spike's recorded interactions.

Every response it serves is a real recording from `spikes/hindsight/recordings/`. A request is
answered only when its method, path, query and JSON body match a recording exactly; anything
else raises `UnrecordedRequest`, so a gateway request that drifts from what the real server was
sent fails loudly instead of being answered by a guess. Extend the fake by recording new real
interactions, never by hand-writing responses.

The one derived behaviour is `hold_operation`: the spike recorded only the terminal state of each
operation, so to exercise polling it serves a recorded operation-status response with nothing
changed but its `status` field.
"""

import copy
import functools
import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import httpx2
from pydantic import JsonValue

RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "spikes" / "hindsight" / "recordings"

type QueryKey = tuple[tuple[str, str], ...]
type RequestKey = tuple[str, str, QueryKey, str]


class UnrecordedRequest(AssertionError):
    """The gateway sent a request no recording matches."""


@dataclass(frozen=True)
class Recording:
    name: str  # "<feature>/<NN-name>", e.g. "retain/04-batch"
    method: str
    path: str
    query: dict[str, JsonValue] | None
    body: JsonValue
    status: int
    response_body: JsonValue

    @property
    def bank_id(self) -> str:
        """The bank in the recorded path (`/v1/default/banks/<bank>/...`)."""
        parts = self.path.split("/")
        return parts[4] if len(parts) > 4 and parts[3] == "banks" else ""

    def response_object(self) -> dict[str, JsonValue]:
        assert isinstance(self.response_body, dict), self.name
        return self.response_body

    def request_object(self) -> dict[str, JsonValue]:
        assert isinstance(self.body, dict), self.name
        return self.body


def load_recordings(directory: Path = RECORDINGS_DIR) -> dict[str, Recording]:
    """All recordings by name. Read once per process; treat the bodies as read-only."""
    return dict(_load(directory))


@functools.cache
def _load(directory: Path) -> dict[str, Recording]:
    recordings: dict[str, Recording] = {}
    for file in sorted(directory.glob("*/*.json")):
        raw = cast(dict[str, dict[str, JsonValue]], json.loads(file.read_text(encoding="utf-8")))
        request, response = raw["request"], raw["response"]
        name = f"{file.parent.name}/{file.stem}"
        recordings[name] = Recording(
            name=name,
            method=str(request["method"]),
            path=str(request["path"]),
            query=cast(dict[str, JsonValue] | None, request.get("query")),
            body=request.get("body"),
            status=cast(int, response["status"]),
            response_body=response.get("body"),
        )
    return recordings


def _query_key(pairs: list[tuple[str, str]]) -> QueryKey:
    return tuple(sorted(pairs))


def _recorded_query(query: dict[str, JsonValue] | None) -> QueryKey:
    pairs: list[tuple[str, str]] = []
    for key, value in (query or {}).items():
        values = value if isinstance(value, list) else [value]
        pairs.extend((key, _query_value(v)) for v in values)
    return _query_key(pairs)


def _query_value(value: JsonValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _body_key(body: JsonValue) -> str:
    return json.dumps(body, sort_keys=True)


@dataclass
class _Hold:
    status: str
    polls: int | None  # None: hold forever


@dataclass
class RecordedHindsight:
    """Serves the recordings through an `httpx2.MockTransport`; inspect `calls` and `served`."""

    recordings: dict[str, Recording] = field(default_factory=load_recordings)
    calls: list[httpx2.Request] = field(default_factory=list[httpx2.Request])
    served: list[str] = field(default_factory=list[str])
    _replies: dict[RequestKey, deque[Recording]] = field(init=False)
    _holds: dict[str, _Hold] = field(init=False, default_factory=dict[str, _Hold])

    def __post_init__(self) -> None:
        self._replies = defaultdict(deque)
        for recording in self.recordings.values():
            key = (
                recording.method,
                recording.path,
                _recorded_query(recording.query),
                _body_key(recording.body),
            )
            self._replies[key].append(recording)

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def recording(self, name: str) -> Recording:
        return self.recordings[name]

    def hold_operation(self, operation_id: str, status: str, polls: int | None = None) -> None:
        """Report `status` for the next `polls` reads of a recorded operation (None: forever)."""
        self._holds[operation_id] = _Hold(status, polls)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        content = request.content
        body: JsonValue = json.loads(content) if content else None
        key = (
            request.method,
            request.url.path,
            _query_key(list(request.url.params.multi_items())),
            _body_key(body),
        )
        queue = self._replies.get(key)
        if not queue:
            raise UnrecordedRequest(
                f"no recording for {request.method} {request.url.path} "
                f"query={dict(request.url.params)} body={body!r}"
            )
        recording = queue[0]
        if len(queue) > 1:  # replay identical requests in recorded order, then repeat the last
            queue.popleft()
        self.served.append(recording.name)
        return self._respond(recording)

    def _respond(self, recording: Recording) -> httpx2.Response:
        body = recording.response_body
        if isinstance(body, dict) and "_binary_bytes" in body:
            raise UnrecordedRequest(f"{recording.name}: the binary body was not recorded")
        if (
            isinstance(body, dict)
            and recording.method == "GET"
            and "/operations/" in recording.path
        ):
            body = self._apply_hold(body)
        if isinstance(body, str):
            return httpx2.Response(recording.status, text=body)
        return httpx2.Response(recording.status, json=body)

    def _apply_hold(self, body: dict[str, JsonValue]) -> dict[str, JsonValue]:
        hold = self._holds.get(str(body.get("operation_id")))
        if hold is None or hold.polls == 0:
            return body
        if hold.polls is not None:
            hold.polls -= 1
        derived = copy.deepcopy(body)
        derived["status"] = hold.status
        return derived
