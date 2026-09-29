"""SEC identity data: the `company_tickers_exchange.json` bulk file and the submissions JSON.

- `https://www.sec.gov/files/company_tickers_exchange.json`: `{"fields": ["cik", "name",
  "ticker", "exchange"], "data": [[...], ...]}`; the same rows as `company_tickers.json`
  plus a coarse exchange label (`Nasdaq`, `NYSE`, `OTC`, `CBOE` or null). No accuracy
  guarantee; no ticker history. Read once per client.
- `https://data.sec.gov/submissions/CIK##########.json`: name, former names with dates,
  tickers, exchange labels, state of incorporation, `lei` (null for every company checked)
  and the recent forms (an unsponsored-ADR shell has only depositary F-6 forms).

All SEC traffic shares `SEC_RATE_LIMITER` (10 requests/s) and declares the User-Agent.
"""

import time
from dataclasses import dataclass
from datetime import date, datetime

import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from atlas.identity.http import IdentitySourceError, JsonHttp, Sleep
from atlas.identity.normalize import canonical_ticker, normalize_name
from atlas.sources.sec_http import SEC_RATE_LIMITER, TokenBucket

SEC_FILES_URL = "https://www.sec.gov/files"
SEC_DATA_URL = "https://data.sec.gov"

# Forms a depositary files for an ADR programme; a CIK with nothing else is an ADR shell.
_DEPOSITARY_FORMS = frozenset({"F-6", "F-6EF", "F-6/A", "F-6 POS"})


@dataclass(frozen=True)
class SecTicker:
    cik: str
    name: str
    ticker: str
    exchange: str | None


@dataclass(frozen=True)
class FormerName:
    name: str
    valid_from: date | None
    valid_to: date | None


@dataclass(frozen=True)
class SecEntity:
    cik: str
    name: str
    tickers: tuple[str, ...]
    exchanges: tuple[str | None, ...]
    former_names: tuple[FormerName, ...]
    state_of_incorporation: str | None
    lei: str | None
    forms: frozenset[str]
    url: str

    @property
    def adr_shell(self) -> bool:
        """Only depositary F-6 registrations: not the issuer's own filings (seed-list 3)."""
        return bool(self.forms) and self.forms <= _DEPOSITARY_FORMS


def _day(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Tickers(_Body):
    fields: list[str]
    data: list[list[str | int | None]]


class _FormerName(_Body):
    name: str
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None


class _Recent(_Body):
    form: list[str] = []


class _Filings(_Body):
    recent: _Recent = _Recent()


class _Submissions(_Body):
    cik: str | int
    name: str
    tickers: list[str] | None = None
    exchanges: list[str | None] | None = None
    formerNames: list[_FormerName] | None = None
    stateOfIncorporation: str | None = None
    lei: str | None = None
    filings: _Filings = _Filings()


def _parse[T: BaseModel](model: type[T], content: bytes, url: str) -> T:
    try:
        return model.model_validate_json(content)
    except ValidationError as error:
        raise IdentitySourceError("SEC", f"{url}: unexpected response: {error}") from None


class SecIdentityClient:
    def __init__(
        self,
        user_agent: str,
        *,
        files_url: str = SEC_FILES_URL,
        data_url: str = SEC_DATA_URL,
        transport: httpx2.BaseTransport | None = None,
        limiter: TokenBucket = SEC_RATE_LIMITER,
        sleep: Sleep = time.sleep,
    ) -> None:
        self._files_url = files_url.rstrip("/")
        self._data_url = data_url.rstrip("/")
        self._http = JsonHttp(
            "SEC",
            limiter=limiter,
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            transport=transport,
            sleep=sleep,
        )
        self._tickers: list[SecTicker] | None = None

    def close(self) -> None:
        self._http.close()

    @property
    def tickers_url(self) -> str:
        return f"{self._files_url}/company_tickers_exchange.json"

    def tickers(self) -> list[SecTicker]:
        if self._tickers is None:
            content = self._http.request("GET", self.tickers_url) or b"{}"
            body = _parse(_Tickers, content, self.tickers_url)
            self._tickers = []
            for row in body.data:
                record = dict(zip(body.fields, row, strict=True))
                exchange = record.get("exchange")
                self._tickers.append(
                    SecTicker(
                        cik=str(record["cik"]).zfill(10),
                        name=str(record["name"]),
                        ticker=canonical_ticker(str(record["ticker"])),
                        exchange=None if exchange is None else str(exchange),
                    )
                )
        return self._tickers

    def by_ticker(self, ticker: str) -> list[SecTicker]:
        wanted = canonical_ticker(ticker)
        return [row for row in self.tickers() if row.ticker == wanted]

    def by_cik(self, cik: str) -> list[SecTicker]:
        return [row for row in self.tickers() if row.cik == cik]

    def by_name(self, name: str) -> list[SecTicker]:
        """Rows whose title equals `name` after normalisation (never a similarity match)."""
        wanted = normalize_name(name)
        return [row for row in self.tickers() if normalize_name(row.name) == wanted]

    def submissions_url(self, cik: str) -> str:
        return f"{self._data_url}/submissions/CIK{cik}.json"

    def submissions(self, cik: str) -> SecEntity | None:
        url = self.submissions_url(cik)
        content = self._http.request("GET", url, missing_ok=True)
        if content is None:
            return None
        body = _parse(_Submissions, content, url)
        return SecEntity(
            cik=str(body.cik).zfill(10),
            name=body.name,
            tickers=tuple(canonical_ticker(t) for t in body.tickers or []),
            exchanges=tuple(body.exchanges or []),
            former_names=tuple(
                FormerName(f.name, _day(f.from_), _day(f.to)) for f in body.formerNames or []
            ),
            state_of_incorporation=body.stateOfIncorporation or None,
            lei=body.lei or None,
            forms=frozenset(body.filings.recent.form),
            url=url,
        )
