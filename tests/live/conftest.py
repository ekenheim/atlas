"""Live tests call real external services. They are excluded by default (`-m 'not live'`)
and never run in CI; run them explicitly, e.g. `uv run pytest -m live tests/live`.

The Phase 2 gate suite (`test_phase2_gate_live.py`), the extraction smoke test
(`test_extraction_smoke_live.py`) and the live verification (`test_live_verify.py`) need a
second opt-in, `ATLAS_LIVE_TESTS` (see
`tests/live/stack.py`); without it their tests are collected and skipped. Rehearsals
(`ATLAS_LIVE_TESTS=rehearse`) may reach localhost only. Run them with `scripts/live-tests.sh`,
`scripts/live-extraction-smoke.sh` and `scripts/live-verify.sh`.
"""

from collections.abc import Generator

import pytest

from tests.live.stack import OUTCOMES, live_mode

PHASE2_SUITE = "test_phase2_gate_live.py"
EXTRACTION_SMOKE = "test_extraction_smoke_live.py"
LIVE_VERIFY = "test_live_verify.py"
LOCAL_HOSTS = ["127.0.0.1", "localhost", "::1"]
NOT_ENABLED = (
    "live Phase 2 suite not enabled: set ATLAS_LIVE_TESTS=1 (spends MiniMax quota) or "
    "ATLAS_LIVE_TESTS=rehearse (recorded fakes), or use scripts/live-tests.sh"
)
# The opt-in suites, each with the reason its tests are skipped without ATLAS_LIVE_TESTS.
OPT_IN_SUITES = {
    PHASE2_SUITE: NOT_ENABLED,
    EXTRACTION_SMOKE: (
        "live extraction smoke test not enabled: set ATLAS_LIVE_TESTS=1 (spends MiniMax "
        "quota) or ATLAS_LIVE_TESTS=rehearse (scripted fake), or use "
        "scripts/live-extraction-smoke.sh"
    ),
    LIVE_VERIFY: (
        "live verification not enabled: set ATLAS_LIVE_TESTS=1 (spends MiniMax quota) or "
        "ATLAS_LIVE_TESTS=rehearse (every part against the fakes), or use scripts/live-verify.sh"
    ),
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    mode = live_mode()
    for item in items:
        if "tests/live/" in item.nodeid:
            item.add_marker(pytest.mark.live)
            item.add_marker(pytest.mark.enable_socket)
        if item.path.name in OPT_IN_SUITES:
            if mode is None:
                item.add_marker(pytest.mark.skip(reason=OPT_IN_SUITES[item.path.name]))
            elif mode == "rehearse":
                item.add_marker(pytest.mark.allow_hosts(LOCAL_HOSTS))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Keep each Phase 2 scenario's outcome for the run's report."""
    report = yield
    if item.path.name == PHASE2_SUITE and (report.when == "call" or not report.passed):
        outcome = report.outcome if report.when == "call" or report.skipped else "error"
        detail = ""
        if report.skipped and isinstance(report.longrepr, tuple):
            detail = str(report.longrepr[2]).removeprefix("Skipped: ")
        elif report.failed:
            detail = report.longreprtext.strip().splitlines()[-1][:300]
        OUTCOMES.setdefault(item.name, {"outcome": outcome, "detail": detail})
    return report
