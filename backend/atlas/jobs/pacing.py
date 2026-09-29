"""Pacing: the queue-level pause on quota or outage failures, and the nightly backfill window.

**Failure classes.** A job attempt that fails because Hindsight or LiteLLM is out of quota
(`quota`: HTTP 429, a rate-limit or insufficient-quota message) or out of service
(`unavailable`: HTTP 502/503/504, a connection failure) says nothing about the job itself, so
the job is requeued without using up an attempt and the queue **pauses**: the pausable job
kinds (those that depend on Hindsight or LiteLLM) aren't claimed until the backoff has passed.
Each pause entered since the last success doubles the backoff (60 s, 120 s, ... capped at
1 h); the next success of a pausable job clears it. Any other failure is an ordinary failed
attempt. There is no fallback model: pausing is the only response (docs/decisions.md).

**The backfill window.** A job enqueued as `backfill` class is claimed only while the local
time in the configured timezone is inside the window (for example `01:00-07:00`; a window may
wrap past midnight). Interactive jobs run at any time.

Pacing reads the application clock (injectable, so tests can control it); leases keep using
the database clock.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx2

from atlas.hindsight.errors import HindsightHTTPError, HindsightUnavailable

if TYPE_CHECKING:
    from atlas.settings import Settings

FailureClass = Literal["quota", "unavailable"]
JobClass = Literal["interactive", "backfill"]
JOB_CLASSES: tuple[JobClass, ...] = ("interactive", "backfill")
Clock = Callable[[], datetime]

MAX_BACKOFF = timedelta(hours=1)


def utc_now() -> datetime:
    return datetime.now(UTC)


class TransientFailure(Exception):
    """Raised by a handler whose work can't proceed for a quota or availability reason.

    The worker pauses the queue (for a pausable kind) and requeues the job; e.g. a retain
    operation that Hindsight reports failed with a 429 from the model.
    """

    def __init__(self, failure_class: FailureClass, message: str) -> None:
        super().__init__(message)
        self.failure_class: FailureClass = failure_class


# Error text that marks a quota failure: the MiniMax cap-out reaches Hindsight as a 429 from
# LiteLLM (an OpenAI-style `RateLimitError: Error code: 429 ...`).
_QUOTA = re.compile(
    r"\b429\b|rate[ _-]?limit|too many requests|insufficient[ _-]?(?:quota|balance)"
    r"|quota[ _-]?exceeded|exceeded your current quota",
    re.IGNORECASE,
)
# Error text that marks an outage of the model provider, LiteLLM or Hindsight.
_UNAVAILABLE = re.compile(
    r"\b50[234]\b|service[ _-]?unavailable|bad gateway|gateway[ _-]?time-?out"
    r"|connection (?:refused|reset|error|aborted)|APIConnectionError|\boverloaded\b",
    re.IGNORECASE,
)


def classify_error_text(text: str | None) -> FailureClass | None:
    """`quota` or `unavailable` when an error message says so, else None."""
    if not text:
        return None
    if _QUOTA.search(text):
        return "quota"
    if _UNAVAILABLE.search(text):
        return "unavailable"
    return None


def classify_status(status_code: int) -> FailureClass | None:
    if status_code == 429:
        return "quota"
    if status_code in (502, 503, 504):
        return "unavailable"
    return None


def classify_failure(error: BaseException) -> FailureClass | None:
    """The failure class of a job attempt's exception (or its causes), or None if ordinary.

    Only failures of the dependencies are classified: an explicit `TransientFailure`, a
    Hindsight HTTP 429/5xx or unreachable server, an HTTP error or transport failure talking
    to LiteLLM (httpx2), and a 5xx whose body names a quota or outage. Arbitrary exception
    text is never matched, so an unrelated error that mentions "429" doesn't pause the queue.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        found = _classify_one(current)
        if found is not None:
            return found
        current = current.__cause__ or current.__context__
    return None


def _classify_one(error: BaseException) -> FailureClass | None:
    if isinstance(error, TransientFailure):
        return error.failure_class
    if isinstance(error, HindsightUnavailable | httpx2.TransportError):
        return "unavailable"
    if isinstance(error, HindsightHTTPError):
        by_status = classify_status(error.status_code)
        if by_status is None and error.status_code >= 500:
            return classify_error_text(error.body)
        return by_status
    if isinstance(error, httpx2.HTTPStatusError):
        return classify_status(error.response.status_code)
    return None


class InvalidWindow(ValueError):
    pass


_WINDOW = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


@dataclass(frozen=True)
class BackfillWindow:
    """A daily local-time window `[start, end)`; `end` before `start` wraps past midnight."""

    start: time
    end: time
    timezone: ZoneInfo

    @classmethod
    def parse(cls, spec: str, timezone: str) -> "BackfillWindow":
        match = _WINDOW.match(spec.strip())
        if match is None:
            raise InvalidWindow(f"expected HH:MM-HH:MM, e.g. 01:00-07:00 (got {spec!r})")
        sh, sm, eh, em = (int(part) for part in match.groups())
        if sh > 23 or eh > 23 or sm > 59 or em > 59:
            raise InvalidWindow(f"not a time of day in {spec!r}")
        if (sh, sm) == (eh, em):
            raise InvalidWindow(f"the window {spec!r} is empty")
        return cls(time(sh, sm), time(eh, em), parse_timezone(timezone))

    @property
    def spec(self) -> str:
        return f"{self.start:%H:%M}-{self.end:%H:%M}"

    def contains(self, moment: datetime) -> bool:
        local = moment.astimezone(self.timezone).time().replace(tzinfo=None)
        if self.start < self.end:
            return self.start <= local < self.end
        return local >= self.start or local < self.end

    def next_open(self, moment: datetime) -> datetime:
        """When the window next opens after `moment` (its start today or tomorrow, local)."""
        local = moment.astimezone(self.timezone)
        candidate = datetime.combine(local.date(), self.start, tzinfo=self.timezone)
        if candidate <= local:
            candidate = datetime.combine(
                local.date() + timedelta(days=1), self.start, tzinfo=self.timezone
            )
        return candidate.astimezone(UTC)


def parse_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise InvalidWindow(f"unknown timezone {name!r}") from error


@dataclass(frozen=True)
class Pacing:
    """The backfill window (None: backfill jobs run at any time) and the pause backoff."""

    backfill_window: BackfillWindow | None = None
    pause_base: timedelta = timedelta(seconds=60)
    pause_cap: timedelta = MAX_BACKOFF

    def __post_init__(self) -> None:
        if not timedelta(0) < self.pause_base <= self.pause_cap <= MAX_BACKOFF:
            raise ValueError("pause backoff must satisfy 0 < base <= cap <= 1 h")

    @classmethod
    def from_settings(cls, settings: "Settings") -> "Pacing":
        window = (
            BackfillWindow.parse(settings.backfill_window, settings.backfill_timezone)
            if settings.backfill_window
            else None
        )
        return cls(
            backfill_window=window,
            pause_base=timedelta(seconds=settings.queue_pause_base_seconds),
            pause_cap=timedelta(seconds=settings.queue_pause_max_seconds),
        )

    def backoff(self, level: int) -> timedelta:
        """The pause length for the `level`-th consecutive pause (1-based), capped."""
        doubling = min(max(level, 1) - 1, 32)
        return min(self.pause_base * (2**doubling), self.pause_cap)

    def window_open(self, moment: datetime) -> bool:
        return self.backfill_window is None or self.backfill_window.contains(moment)
