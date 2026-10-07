"""The known answers recall as investigations do (pilot fix 40), at a chosen results budget.

Seams: `atlas.conformance.run_known_answers` against an HTTP client that records the requests
it is sent, and the report a run writes. Pure: no service is reached.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from atlas.companies import load_universe
from atlas.conformance import (
    AtlasApi,
    ConformanceReport,
    KnownAnswerSet,
    KnownAnswersReport,
    load_known_answers,
    run_known_answers,
)
from atlas.research.probes import ProbeSet, load_probes
from atlas.settings import Settings

REPO = Path(__file__).parents[2]
KNOWN_ANSWERS = REPO / "configs" / "memory" / "known-answers.yaml"
PROBES = REPO / "configs" / "memory" / "probes.yaml"
THEMES = REPO / "configs" / "themes" / "ai-infrastructure.yaml"


class _Answered:
    status_code = 200
    text = "{}"

    def json(self) -> Any:
        return {"memories": []}


class RecordingClient:
    """Answers every recall with no memories and keeps what it was sent."""

    def __init__(self) -> None:
        self.recalls: list[dict[str, Any]] = []

    def get(self, url: str, *, params: Any = None) -> Any:
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url: str, *, json: Any = None) -> Any:
        self.recalls.append(json)
        return _Answered()


@pytest.fixture
def frame(monkeypatch: pytest.MonkeyPatch) -> tuple[KnownAnswerSet, ProbeSet]:
    # Resolving the answers needs the live bank's documents; the recalls do not.
    def nothing_to_resolve(api: AtlasApi, answers: object) -> tuple[list[Any], list[Any]]:
        return [], []

    monkeypatch.setattr("atlas.conformance.known_answers.resolve_answers", nothing_to_resolve)
    universe = load_universe(THEMES)
    probes = load_probes(PROBES, universe)
    return load_known_answers(KNOWN_ANSWERS, universe, probes), probes


def test_known_answers_recall_as_investigations_do_at_the_given_budget(
    frame: tuple[KnownAnswerSet, ProbeSet],
) -> None:
    answers, probes = frame
    client = RecordingClient()
    as_of = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)

    report = run_known_answers(AtlasApi(client), answers, probes, max_tokens=16000, as_of=as_of)

    assert client.recalls
    assert report.max_tokens == 16000
    for body in client.recalls:
        assert body["budget"] == "high"
        assert body["max_tokens"] == 16000
        assert body["prefer_observations"] is True
        assert body["include_source_facts"] is True
        assert body["include_chunks"] is True
        assert body["query_timestamp"].startswith("2026-10-07T12:00:00")
        assert body["scope"]["theme_ids"]


def test_known_answers_default_to_the_investigations_recall_budget(
    frame: tuple[KnownAnswerSet, ProbeSet],
) -> None:
    answers, probes = frame
    client = RecordingClient()

    run_known_answers(AtlasApi(client), answers, probes)

    assert {body["max_tokens"] for body in client.recalls} == {8192}
    assert Settings.model_fields["pointer_recall_max_tokens"].default == 8192


def _known(max_tokens: int, at_10: float, at_50: float) -> KnownAnswersReport:
    return KnownAnswersReport.model_validate(
        {
            "max_tokens": max_tokens,
            "verdict": "passed",
            "reason": None,
            "thresholds": {"recall_at_10": 0.0, "recall_at_50": 0.0},
            "answers": 17,
            "errors": [],
            "overall": {
                "answers": 17,
                "found_at_10": 1,
                "found_at_50": 2,
                "at_10": at_10,
                "at_50": at_50,
            },
            "by_question": {},
            "by_hop": {},
            "by_test_part": {},
            "outcomes": [],
            "recalls": [],
            "anchors_found": {},
        }
    )


def test_the_summary_compares_the_recall_budgets() -> None:
    report = ConformanceReport(
        mode="rehearse",
        strict=False,
        known_answers=_known(8192, 0.08, 0.12),
        known_answers_sweep=[_known(16000, 0.3, 0.5)],
    )

    summary = report.summary()

    assert "| 8192 | 17 | 0.08 | 0.12 |" in summary
    assert "| 16000 | 17 | 0.30 | 0.50 |" in summary
