"""Live SEC smoke test: a handful of real requests to EDGAR for Lumentum.

Opt-in only: `ATLAS_SEC_USER_AGENT="<name> <email>" uv run pytest -m live tests/live`.
It makes four requests through the process-wide 10 req/s limiter.
"""

import os
from datetime import UTC, datetime

import pytest

from atlas.sources import SearchQuery, live_edgar_adapter

pytestmark = pytest.mark.anyio

LUMENTUM = "0001633978"


async def test_lumentum_latest_8k_is_discovered_fetched_and_rechecked_conditionally() -> None:
    user_agent = os.environ.get("ATLAS_SEC_USER_AGENT")
    if not user_agent:
        pytest.skip("set ATLAS_SEC_USER_AGENT to run the live SEC smoke test")
    source = live_edgar_adapter(user_agent, ciks=[LUMENTUM])

    # Requests 1-2: the submissions index, then the newest 8-K's index headers.
    candidates = await source.discover(SearchQuery(cik=LUMENTUM, forms=("8-K",), limit=1))

    primary = next(c for c in candidates if c.document_type in {"8-K", "8-K/A"})
    assert primary.filing is not None
    assert primary.filing.cik == LUMENTUM
    # Public at acceptance, or, if EDGAR held it after hours, at the next opening.
    assert primary.available_at_basis in {"sec_acceptance", "sec_dissemination"}
    assert primary.filing.acceptance_datetime <= primary.available_at < datetime.now(UTC)

    # Request 3: the document itself; request 4: the same, conditionally.
    document = await source.fetch(primary)
    assert document.content
    assert document.validators.last_modified or document.validators.etag
    again = await source.fetch(primary.model_copy(update={"validators": document.validators}))
    assert again.not_modified is True
