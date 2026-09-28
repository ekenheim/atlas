"""Everything the Hindsight gateway raises; callers catch `HindsightError` and its subclasses."""


class HindsightError(Exception):
    """Base class for gateway errors."""


class HindsightRuleViolation(HindsightError, ValueError):
    """A request broke a pinned-version (0.10.1) rule; it was rejected before any call."""


class HindsightUnavailable(HindsightError):
    """Hindsight could not be reached, or the request timed out in transit."""


class HindsightHTTPError(HindsightError):
    """Hindsight answered with a non-success HTTP status."""

    def __init__(self, method: str, path: str, status_code: int, body: str) -> None:
        super().__init__(f"{method} {path} returned HTTP {status_code}: {body[:500]}")
        self.method = method
        self.path = path
        self.status_code = status_code
        self.body = body


class HindsightNotFound(HindsightHTTPError):
    """HTTP 404: e.g. a memory that no longer exists."""


class HindsightProtocolError(HindsightError):
    """Hindsight answered 2xx with a body that doesn't match the 0.10.1 contract."""


class OperationTimeout(HindsightError):
    """An operation didn't reach a terminal status before the polling timeout."""

    def __init__(self, operation_id: str, last_status: str, timeout: float) -> None:
        super().__init__(
            f"operation {operation_id} still {last_status!r} after {timeout:g} s of polling"
        )
        self.operation_id = operation_id
        self.last_status = last_status
        self.timeout = timeout
