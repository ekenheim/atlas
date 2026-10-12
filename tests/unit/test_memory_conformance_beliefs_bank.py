"""The conclusions bank as a known answer (beliefs ticket 12): it exists and its template
version is the repository's. Pure: an HTTP client that answers `GET /memory/health`."""

from pathlib import Path
from typing import Any

import pytest

from atlas.conformance import AtlasApi, ConformanceReport, check_beliefs_bank

REPO = Path(__file__).parents[2]
BELIEFS_TEMPLATE = REPO / "configs" / "hindsight" / "bank-template-beliefs.json"


class Health:
    def __init__(self, beliefs: dict[str, Any] | None, status: int = 200) -> None:
        self._beliefs = beliefs
        self.status_code = status
        self.text = "unavailable"

    def json(self) -> Any:
        return {"bank_id": "atlas-ai-infrastructure", "beliefs": self._beliefs}


class Client:
    def __init__(self, health: Health) -> None:
        self._health = health
        self.paths: list[str] = []

    def get(self, url: str, *, params: Any = None) -> Any:
        self.paths.append(url)
        return self._health

    def post(self, url: str, *, json: Any = None) -> Any:
        raise AssertionError("the check is read-only")


def check(beliefs: dict[str, Any] | None, status: int = 200):
    client = Client(Health(beliefs, status))
    report = check_beliefs_bank(AtlasApi(client), BELIEFS_TEMPLATE)
    assert client.paths == ["/api/v1/memory/health"]
    return report


def test_the_bank_exists_with_the_repositorys_template_version() -> None:
    report = check({"bank": "atlas-beliefs", "template_version": "1.0.0"})

    assert report.verdict == "passed"
    assert (report.bank, report.expected_template_version) == ("atlas-beliefs", "1.0.0")


@pytest.mark.parametrize(
    ("beliefs", "status", "reason"),
    [
        ({"bank": "atlas-beliefs", "template_version": None}, 200, "no template was applied"),
        ({"bank": "atlas-beliefs", "template_version": "0.9.0"}, 200, "has template 0.9.0"),
        ({"template_version": "1.0.0"}, 200, "names no conclusions bank"),
        (None, 200, "names no conclusions bank"),
        (None, 503, "memory health unavailable"),
    ],
)
def test_a_missing_or_stale_bank_fails_the_known_answer(
    beliefs: dict[str, Any] | None, status: int, reason: str
) -> None:
    report = check(beliefs, status)

    assert report.verdict == "failed"
    assert reason in (report.reason or "")


def test_a_failed_beliefs_bank_fails_the_run_and_shows_in_the_summary() -> None:
    failed = check({"bank": "atlas-beliefs", "template_version": None})
    run = ConformanceReport.model_validate(
        {"mode": "live", "strict": False, "beliefs_bank": failed.model_dump()}
    )

    assert run.exit_code() == 1
    assert any(each.startswith("beliefs bank:") for each in run.failures())
    assert "## The conclusions bank" in run.summary()
    passed = check({"bank": "atlas-beliefs", "template_version": "1.0.0"})
    assert (
        ConformanceReport.model_validate(
            {"mode": "live", "strict": False, "beliefs_bank": passed.model_dump()}
        ).exit_code()
        == 0
    )
