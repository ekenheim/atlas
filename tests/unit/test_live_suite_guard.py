"""The live suites stay out of CI and refuse to run without their explicit opt-in.

Each check runs pytest itself in a subprocess, as CI and the owner would, with the opt-in
variables removed from the environment. Only the Phase 2 file, the extraction smoke test and
the live verification are ever selected, so the live SEC smoke test can't run from here.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parents[2]
SUITE = "tests/live/test_phase2_gate_live.py"
SCENARIOS = 8
SMOKE = "tests/live/test_extraction_smoke_live.py"


def pytest_run(*args: str, **env: str) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_LIVE_")}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        cwd=REPO,
        env=clean | env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_the_default_run_that_ci_makes_deselects_the_live_suite() -> None:
    collected = pytest_run(SUITE, "--collect-only", "-q")
    assert f"no tests collected ({SCENARIOS} deselected)" in collected.stdout, collected.stdout


def test_selecting_the_live_marker_without_the_opt_in_skips_every_scenario() -> None:
    ran = pytest_run("-m", "live", SUITE, "-q", "-rs")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert f"{SCENARIOS} skipped" in ran.stdout
    assert "live Phase 2 suite not enabled: set ATLAS_LIVE_TESTS=1" in ran.stdout


def test_an_opted_in_live_run_under_ci_is_refused_before_any_call() -> None:
    ran = pytest_run(
        "-m",
        "live",
        SUITE,
        "-q",
        ATLAS_LIVE_TESTS="1",
        CI="true",
        ATLAS_LITELLM_URL="http://127.0.0.1:9",
        ATLAS_LITELLM_API_KEY="not-a-key",
    )
    assert ran.returncode == 4, ran.stdout + ran.stderr
    assert "live suite refused: CI is set" in ran.stdout + ran.stderr


def test_the_extraction_smoke_test_is_deselected_and_skipped_without_its_opt_in() -> None:
    collected = pytest_run(SMOKE, "--collect-only", "-q")
    assert "no tests collected (1 deselected)" in collected.stdout, collected.stdout
    ran = pytest_run("-m", "live", SMOKE, "-q", "-rs")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "1 skipped" in ran.stdout
    assert "live extraction smoke test not enabled" in ran.stdout


def test_an_opted_in_extraction_smoke_run_under_ci_is_refused_before_any_call() -> None:
    ran = pytest_run(
        "-m",
        "live",
        SMOKE,
        "-q",
        ATLAS_LIVE_TESTS="1",
        CI="true",
        ATLAS_LITELLM_URL="http://127.0.0.1:9",
        ATLAS_LITELLM_API_KEY="not-a-key",
    )
    assert ran.returncode == 4, ran.stdout + ran.stderr
    assert "live extraction smoke test refused: CI is set" in ran.stdout + ran.stderr


VERIFY = "tests/live/test_live_verify.py"
VERIFY_PARTS = 7


def test_the_live_verification_is_deselected_and_skipped_without_its_opt_in() -> None:
    collected = pytest_run(VERIFY, "--collect-only", "-q")
    assert f"no tests collected ({VERIFY_PARTS} deselected)" in collected.stdout, collected.stdout
    ran = pytest_run("-m", "live", VERIFY, "-q", "-rs")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert f"{VERIFY_PARTS} skipped" in ran.stdout
    assert "live verification not enabled" in ran.stdout


def test_an_opted_in_live_verification_under_ci_is_refused_before_any_call() -> None:
    ran = pytest_run(
        "-m",
        "live",
        VERIFY,
        "-q",
        ATLAS_LIVE_TESTS="1",
        CI="true",
        ATLAS_LITELLM_URL="http://127.0.0.1:9",
        ATLAS_LITELLM_API_KEY="not-a-key",
        ATLAS_LIVE_HINDSIGHT_URL="http://127.0.0.1:9",
    )
    assert ran.returncode == 4, ran.stdout + ran.stderr
    assert "live verification refused: CI is set" in ran.stdout + ran.stderr
