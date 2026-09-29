"""OpenFIGI mapping, keyless (https://www.openfigi.com/api/documentation).

`POST /v3/mapping` takes a JSON array of jobs (`idType`, `idValue` and at most one of
`exchCode` and `micCode`) and answers an array aligned by index: `{"data": [...]}`,
`{"warning": "No identifier found."}` or `{"error": "..."}`. Keyless: 25 requests per
minute and at most 10 jobs per request, so larger job lists go in batches of 10. A 429
carries `ratelimit-reset`, which the retry honours.

- `micCode` must be the **segment** MIC: LITE matches on `XNGS`, not on the operating MIC
  `XNAS` (identity research §3).
- Tickers go out with OpenFIGI's class separator (`BRK/B`) and come back in SEC's (`BRK-B`).
- A data row has no ISIN, LEI, MIC or currency. FIGIs are public domain.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import httpx2
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from atlas.identity.http import IdentitySourceError, JsonHttp, Sleep
from atlas.identity.normalize import canonical_ticker, openfigi_ticker
from atlas.sources.sec_http import TokenBucket

OPENFIGI_URL = "https://api.openfigi.com"
MAX_JOBS_PER_REQUEST = 10  # keyless
# The one limiter for all OpenFIGI mapping traffic in this process (25 requests per minute).
OPENFIGI_RATE_LIMITER = TokenBucket(rate_per_s=25 / 60)

type IdType = Literal["TICKER", "ID_ISIN", "ID_CUSIP", "COMPOSITE_ID_BB_GLOBAL", "ID_BB_GLOBAL"]


@dataclass(frozen=True)
class MappingJob:
    id_type: IdType | str
    id_value: str
    exch_code: str | None = None
    mic_code: str | None = None

    def __post_init__(self) -> None:
        if self.exch_code is not None and self.mic_code is not None:
            raise ValueError("an OpenFIGI job takes exchCode or micCode, not both")

    def body(self) -> dict[str, str]:
        value = openfigi_ticker(self.id_value) if self.id_type == "TICKER" else self.id_value
        job = {"idType": self.id_type, "idValue": value}
        if self.exch_code is not None:
            job["exchCode"] = self.exch_code
        if self.mic_code is not None:
            job["micCode"] = self.mic_code
        return job


@dataclass(frozen=True)
class Figi:
    figi: str
    name: str
    ticker: str
    exch_code: str | None
    composite_figi: str | None
    share_class_figi: str | None
    security_type: str | None
    security_type2: str | None
    market_sector: str | None

    @property
    def depositary_receipt(self) -> bool:
        return self.security_type2 == "Depositary Receipt" or self.security_type == "ADR"


@dataclass(frozen=True)
class MappingResult:
    job: MappingJob
    figis: tuple[Figi, ...] = ()
    warning: str | None = None
    error: str | None = None


class _Row(BaseModel):
    model_config = ConfigDict(extra="ignore")

    figi: str
    name: str | None = None
    ticker: str | None = None
    exchCode: str | None = None
    compositeFIGI: str | None = None
    shareClassFIGI: str | None = None
    securityType: str | None = None
    securityType2: str | None = None
    marketSector: str | None = None


class _Answer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: list[_Row] = []
    warning: str | None = None
    error: str | None = None


_Answers = TypeAdapter(list[_Answer])


def _figi(row: _Row) -> Figi:
    return Figi(
        figi=row.figi,
        name=row.name or "",
        ticker=canonical_ticker(row.ticker or ""),
        exch_code=row.exchCode,
        composite_figi=row.compositeFIGI,
        share_class_figi=row.shareClassFIGI,
        security_type=row.securityType,
        security_type2=row.securityType2,
        market_sector=row.marketSector,
    )


class OpenFigiClient:
    def __init__(
        self,
        base_url: str = OPENFIGI_URL,
        *,
        transport: httpx2.BaseTransport | None = None,
        limiter: TokenBucket = OPENFIGI_RATE_LIMITER,
        sleep: Sleep = time.sleep,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._http = JsonHttp(
            "OpenFIGI",
            limiter=limiter,
            headers={"Content-Type": "application/json"},
            transport=transport,
            sleep=sleep,
        )

    @property
    def mapping_url(self) -> str:
        return f"{self._base}/v3/mapping"

    def close(self) -> None:
        self._http.close()

    def map(self, jobs: Sequence[MappingJob]) -> list[MappingResult]:
        """One result per job, in order; requests carry at most 10 jobs each."""
        results: list[MappingResult] = []
        for start in range(0, len(jobs), MAX_JOBS_PER_REQUEST):
            batch = list(jobs[start : start + MAX_JOBS_PER_REQUEST])
            content = self._http.request(
                "POST", self.mapping_url, json=[job.body() for job in batch]
            )
            try:
                answers = _Answers.validate_json(content or b"")
            except ValidationError as error:
                raise IdentitySourceError("OpenFIGI", f"unexpected response: {error}") from None
            if len(answers) != len(batch):
                raise IdentitySourceError("OpenFIGI", "the mapping answer isn't one item per job")
            for job, answer in zip(batch, answers, strict=True):
                results.append(
                    MappingResult(
                        job=job,
                        figis=tuple(_figi(row) for row in answer.data),
                        warning=answer.warning,
                        error=answer.error,
                    )
                )
        return results
