"""The fetch gate: whether Atlas may fetch a URL, decided before any request is made to it.

Every request an exchange adapter makes (its feed's search as well as each document) goes
through `GatedHttpClient`, which asks the `FetchGate` first and records the decision. The
gates, in order (build plan §4.2; docs/source-licenses.md §5; docs/decisions.md):

1. **Register.** The URL's host must belong to a site in the site register
   (`configs/sources/sites.yaml`). An unknown host is blocked: a site is onboarded before
   its first fetch.
2. **Terms.** The site's recorded terms decision: `allowed` passes; `forbidden` (the terms
   forbid automated access) passes only with a recorded consent from the site's owner;
   `unchecked` (nobody has read the terms yet) is blocked. A site blocked here gets no
   request at all, not even for its robots.txt.
3. **robots.txt.** Read once per origin per gate (so once per ingest), before any other
   request to that origin, and obeyed as RFC 9309 says (`atlas.sources.robots`). Its bytes
   are archived and their hash recorded with each decision that relied on them.

A blocked URL raises `FetchBlocked` carrying the decision; the ingest records it as a
`blocked` fetch gate decision (visible in the API) instead of fetching.
"""

import hashlib
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, Protocol, Self
from urllib.parse import urlsplit, urlunsplit

import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from atlas.archive import Archive, Namespace
from atlas.sources.adapter import FetchError, HttpValidators
from atlas.sources.robots import ROBOTS_PRODUCT_TOKEN, RobotsTxt
from atlas.sources.sec_http import HttpResult

Automation = Literal["allowed", "forbidden", "unchecked"]
GateStatus = Literal["allowed", "blocked"]
GateName = Literal["register", "terms", "robots"]


class SiteRegisterError(ValueError):
    """The site register is missing or invalid; the message says where."""


class _Config(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Consent(_Config):
    """Written permission from a site's owner that lifts a terms prohibition."""

    reference: str = Field(min_length=1)  # where the consent is kept, e.g. an email's subject
    granted_on: date
    scope: str = Field(min_length=1)  # what it permits


class SiteConfig(_Config):
    publisher: str = Field(min_length=1)
    hosts: tuple[str, ...] = Field(min_length=1)
    terms_url: str | None = None
    terms_checked_on: date | None = None
    automation: Automation
    terms_note: str = Field(min_length=1)  # what the terms say about automated access
    # The reason a terms block records, e.g. "blocked: <why> (<what would lift it>)";
    # without one, a generic reason is recorded.
    block_reason: str | None = Field(default=None, min_length=1)
    consent: Consent | None = None
    rate_per_s: float = Field(default=1.0, gt=0)

    @model_validator(mode="after")
    def _terms(self) -> Self:
        if self.automation != "unchecked" and (not self.terms_url or not self.terms_checked_on):
            raise ValueError(f"automation {self.automation!r} needs terms_url and terms_checked_on")
        if self.consent is not None and self.automation != "forbidden":
            raise ValueError("consent only applies to a site whose terms forbid automation")
        if any(host != host.lower() or "/" in host for host in self.hosts):
            raise ValueError("hosts are lowercase host names")
        return self


class SiteRegister(_Config):
    version: int = Field(ge=1)
    sites: dict[str, SiteConfig]

    @model_validator(mode="after")
    def _unique_hosts(self) -> Self:
        seen: dict[str, str] = {}
        for name, site in self.sites.items():
            for host in site.hosts:
                if host in seen:
                    raise ValueError(f"host {host} is in both {seen[host]!r} and {name!r}")
                seen[host] = name
        return self

    def site_for(self, url: str) -> tuple[str, SiteConfig] | None:
        host = (urlsplit(url).hostname or "").lower()
        return next(((n, s) for n, s in self.sites.items() if host in s.hosts), None)


def load_site_register(path: Path) -> SiteRegister:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise SiteRegisterError(f"cannot read site register {path}: {error.strerror}") from None
    except yaml.YAMLError as error:
        raise SiteRegisterError(f"site register {path} is not valid YAML: {error}") from None
    try:
        return SiteRegister.model_validate(document)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc']) or '<root>'}: {issue['msg']}"
            for issue in error.errors()
        )
        raise SiteRegisterError(f"site register {path} is invalid: {problems}") from None


class TermsRecord(BaseModel):
    """The terms decision a gate decision relied on, as the register recorded it."""

    url: str | None
    checked_on: date | None
    automation: Automation
    note: str
    consent: Consent | None


class RobotsRecord(BaseModel):
    """The robots.txt a gate decision relied on."""

    url: str
    status: int | None  # HTTP status; None when no response arrived
    sha256: str | None  # of the body, when there was one
    object_uri: str | None  # the archived body
    fetched_at: AwareDatetime
    group: str | None  # the user-agent group obeyed
    rule: str | None  # the deciding rule, e.g. "Disallow: / (line 2)"


class GateDecision(BaseModel):
    """Whether one URL may be fetched, and why."""

    model_config = ConfigDict(frozen=True)

    url: str
    status: GateStatus
    blocked_by: GateName | None  # None when allowed
    reason: str
    site: str | None  # the register's name for the site
    terms: TermsRecord | None
    robots: RobotsRecord | None
    user_agent_token: str
    decided_at: AwareDatetime


class FetchBlocked(Exception):
    """The gate blocked this URL; nothing was requested from it."""

    def __init__(self, decision: GateDecision) -> None:
        super().__init__(f"{decision.url} blocked by {decision.blocked_by}: {decision.reason}")
        self.decision = decision


class HttpGetter(Protocol):
    """What the gate and the exchange adapters need of an HTTP client (`SecHttpClient`)."""

    async def get(self, url: str, validators: HttpValidators | None = None) -> HttpResult: ...


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), "", "", ""))


class FetchGate:
    def __init__(
        self,
        register: SiteRegister,
        client: HttpGetter,
        *,
        archive: Archive | None = None,
        token: str = ROBOTS_PRODUCT_TOKEN,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._register = register
        self._client = client
        self._archive = archive
        self._token = token
        self._now = now
        self._robots: dict[str, tuple[RobotsTxt, RobotsRecord]] = {}

    async def check(self, url: str) -> GateDecision:
        def decide(
            status: GateStatus,
            blocked_by: GateName | None,
            reason: str,
            site: str | None = None,
            terms: TermsRecord | None = None,
            robots: RobotsRecord | None = None,
        ) -> GateDecision:
            return GateDecision(
                url=url,
                status=status,
                blocked_by=blocked_by,
                reason=reason,
                site=site,
                terms=terms,
                robots=robots,
                user_agent_token=self._token,
                decided_at=self._now(),
            )

        found = self._register.site_for(url)
        if found is None:
            host = urlsplit(url).hostname
            return decide("blocked", "register", f"{host} is not onboarded in the site register")
        name, site = found
        terms = TermsRecord(
            url=site.terms_url,
            checked_on=site.terms_checked_on,
            automation=site.automation,
            note=site.terms_note,
            consent=site.consent,
        )
        if site.automation == "unchecked":
            return decide("blocked", "terms", f"{name}'s terms have not been checked", name, terms)
        if site.automation == "forbidden" and site.consent is None:
            reason = (
                site.block_reason
                or f"{name}'s terms forbid automated access and no consent is recorded"
            )
            return decide("blocked", "terms", reason, name, terms)
        robots, record = await self._robots_for(url)
        verdict = robots.check(url, self._token)
        record = record.model_copy(
            update={
                "group": verdict.group,
                "rule": verdict.rule.describe() if verdict.rule else None,
            }
        )
        terms_basis = "consent" if site.consent is not None else "terms allow automation"
        if not verdict.allowed:
            return decide("blocked", "robots", f"robots.txt: {verdict.reason}", name, terms, record)
        reason = f"{terms_basis}; robots.txt: {verdict.reason}"
        return decide("allowed", None, reason, name, terms, record)

    async def _robots_for(self, url: str) -> tuple[RobotsTxt, RobotsRecord]:
        origin = _origin(url)
        if origin not in self._robots:
            robots_url = f"{origin}/robots.txt"
            fetched_at = self._now()
            status: int | None
            body: bytes | None = None
            try:
                result = await self._client.get(robots_url)
            except FetchError as error:
                status = error.status
                if status is not None and 400 <= status < 500:
                    robots = RobotsTxt.unrestricted()
                else:
                    robots = RobotsTxt.unreachable(
                        f"robots.txt unreachable ({status or error}): everything is disallowed"
                    )
            else:
                status, body = result.status, result.content
                robots = RobotsTxt.parse(body)
            record = RobotsRecord(
                url=robots_url,
                status=status,
                sha256=hashlib.sha256(body).hexdigest() if body is not None else None,
                object_uri=(
                    self._archive.put(Namespace.RAW, body)
                    if body is not None and self._archive is not None
                    else None
                ),
                fetched_at=fetched_at,
                group=None,
                rule=None,
            )
            self._robots[origin] = (robots, record)
        return self._robots[origin]


class GatedHttpClient:
    """An `HttpGetter` that asks the gate before every request and keeps each decision
    until the caller takes them (to record them)."""

    def __init__(self, client: HttpGetter, gate: FetchGate) -> None:
        self._client = client
        self._gate = gate
        self._pending: list[GateDecision] = []

    async def get(self, url: str, validators: HttpValidators | None = None) -> HttpResult:
        decision = await self._gate.check(url)
        self._pending.append(decision)
        if decision.status == "blocked":
            raise FetchBlocked(decision)
        return await self._client.get(url, validators)

    def take_decisions(self) -> list[GateDecision]:
        """The decisions made since the last call, in request order."""
        taken, self._pending = self._pending, []
        return taken
