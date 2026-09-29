"""A transport-level fake of the identity sources: SEC's ticker file and submissions, the GLEIF
API and OpenFIGI `/v3/mapping`, answered from `tests/fixtures/identity/` (see its manifest:
hand-written from the identity research's trimmed live responses) plus the recorded EDGAR
submissions of Lumentum and Coherent.

Requests are routed by path only, so the same fake serves the real hosts through an
`httpx2.MockTransport` and a localhost URL through `tests/fakes/serve.py`:

- `GET …/company_tickers_exchange.json`, `GET …/submissions/CIK##########.json`
- `GET …/lei-records/{lei}`, `GET …/lei-records?filter[...]=…`
- `POST …/v3/mapping`, answered job by job

Anything else, an unrecorded submission, GLEIF filter or OpenFIGI job fails loudly
(`UnexpectedRequest`), so the code under test can't reach an unplanned endpoint (including
GLEIF's `fuzzycompletions`). `rate_limit_openfigi` scripts 429s with `ratelimit-reset`.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx2

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
IDENTITY = FIXTURES / "identity"
_EDGAR = FIXTURES / "edgar"


class UnexpectedRequest(AssertionError):
    """The code under test asked for something no fixture answers."""


def _json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def _canonical(job: dict[str, Any]) -> str:
    return json.dumps(job, sort_keys=True)


@dataclass
class FakeIdentitySources:
    calls: list[httpx2.Request] = field(default_factory=list[httpx2.Request])
    openfigi_batches: list[list[dict[str, Any]]] = field(default_factory=list[list[dict[str, Any]]])
    openfigi_429s: int = 0
    openfigi_reset_s: int = 7
    missing_submissions: set[str] = field(default_factory=set[str])

    def __post_init__(self) -> None:
        mapping = cast(list[dict[str, Any]], _json(IDENTITY / "openfigi" / "mapping.json"))
        self._jobs = {_canonical(item["job"]): item["answer"] for item in mapping}
        self._queries = cast(dict[str, list[str]], _json(IDENTITY / "gleif" / "queries.json"))

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def rate_limit_openfigi(self, times: int = 1, reset_s: int = 7) -> None:
        self.openfigi_429s = times
        self.openfigi_reset_s = reset_s

    def paths(self) -> list[str]:
        return [call.url.path for call in self.calls]

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        path = request.url.path
        if request.method == "GET" and path.endswith("/company_tickers_exchange.json"):
            return self._ok(_json(IDENTITY / "sec" / "company_tickers_exchange.json"))
        if request.method == "GET" and "/submissions/" in path:
            return self._submissions(path.rsplit("/", 1)[1])
        if request.method == "GET" and path.endswith("/lei-records"):
            return self._gleif_filter(request)
        if request.method == "GET" and "/lei-records/" in path:
            return self._gleif_record(path.rsplit("/", 1)[1])
        if request.method == "POST" and path.endswith("/v3/mapping"):
            return self._openfigi(request)
        raise UnexpectedRequest(f"{request.method} {request.url}")

    @staticmethod
    def _ok(body: Any, headers: dict[str, str] | None = None) -> httpx2.Response:
        return httpx2.Response(200, json=body, headers=headers)

    def _submissions(self, name: str) -> httpx2.Response:
        if name in self.missing_submissions:
            return httpx2.Response(404, text="Not Found")
        for candidate in [
            IDENTITY / "sec" / "submissions" / name,
            *_EDGAR.glob(f"*/data.sec.gov/submissions/{name}"),
        ]:
            if candidate.is_file():
                return self._ok(_json(candidate))
        raise UnexpectedRequest(f"no submissions fixture {name}")

    def _gleif_record(self, lei: str) -> httpx2.Response:
        path = IDENTITY / "gleif" / "records" / f"{lei}.json"
        if not path.is_file():
            return httpx2.Response(404, json={"errors": [{"status": "404", "title": "Not Found"}]})
        return self._ok({"data": _json(path)})

    def _gleif_filter(self, request: httpx2.Request) -> httpx2.Response:
        filters = [(k, v) for k, v in request.url.params.items() if k.startswith("filter[")]
        if len(filters) != 1:
            raise UnexpectedRequest(f"GLEIF filters {filters}")
        [(key, value)] = filters
        query = f"{key.removeprefix('filter[').removesuffix(']')}={value}"
        if query not in self._queries:
            raise UnexpectedRequest(f"no GLEIF fixture for {query}")
        records = [
            _json(IDENTITY / "gleif" / "records" / f"{lei}.json") for lei in self._queries[query]
        ]
        return self._ok(
            {
                "meta": {"pagination": {"currentPage": 1, "total": len(records)}},
                "data": records,
            }
        )

    def _openfigi(self, request: httpx2.Request) -> httpx2.Response:
        jobs = cast(list[dict[str, Any]], json.loads(request.content))
        if self.openfigi_429s > 0:
            self.openfigi_429s -= 1
            return httpx2.Response(
                429,
                text="Too Many Requests",
                headers={
                    "ratelimit-limit": "25",
                    "ratelimit-remaining": "0",
                    "ratelimit-reset": str(self.openfigi_reset_s),
                },
            )
        self.openfigi_batches.append(jobs)
        if len(jobs) > 10:
            return httpx2.Response(413, text="Too many mapping jobs")
        answers: list[Any] = []
        for job in jobs:
            key = _canonical(job)
            if key not in self._jobs:
                raise UnexpectedRequest(f"no OpenFIGI fixture for job {job}")
            answers.append(self._jobs[key])
        return self._ok(answers, headers={"ratelimit-policy": "25;w=60"})
