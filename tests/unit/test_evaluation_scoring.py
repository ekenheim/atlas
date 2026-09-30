"""Scoring accounts for every verified edge Atlas produced, not only the ones the gold
foresaw (Codex review, 2026-09-30, item 1)."""

import json
from pathlib import Path
from typing import Any, cast

from pydantic import JsonValue

from atlas.evaluation.gold import Case
from atlas.evaluation.scoring import score

CASES = Path(__file__).resolve().parents[1] / "evaluation" / "gold" / "cases"


def load(case_id: str) -> Case:
    return Case.model_validate_json((CASES / f"{case_id}.json").read_bytes())


def edge(subject: str, predicate: str, obj: str, state: str = "machine_reviewed") -> dict[str, Any]:
    return {
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "object_text": None,
        "layer": "substrate",
        "review_state": state,
        "reasons": [],
        "evidence": [],
    }


def unexpected(case: Case, edges: list[dict[str, Any]]) -> Any:
    observed = cast(dict[str, JsonValue], {"relationships": edges})
    checks = [c for c in score(case, observed) if c.key == "relationships.unexpected"]
    assert len(checks) == 1
    return checks[0]


def test_an_expected_edge_alone_passes_and_the_check_feeds_precision() -> None:
    case = load("EV-SUP-001")  # gold: borealis supplies aurora, machine_reviewed
    check = unexpected(case, [edge("borealis", "supplies", "aurora")])
    assert check.passed
    assert check.metric == "relationship_precision"
    assert check.observed == {"verified": 1, "unexpected": []}


def test_a_verified_edge_the_gold_never_named_fails_the_check_and_is_listed() -> None:
    case = load("EV-SUP-001")
    extra = edge("aurora", "supplies", "borealis", state="approved")
    check = unexpected(case, [edge("borealis", "supplies", "aurora"), extra])
    assert not check.passed
    assert check.observed["verified"] == 2
    assert check.observed["unexpected"] == [
        {k: extra[k] for k in ("subject", "predicate", "object", "object_text", "layer")}
    ]


def test_an_unverified_extra_edge_is_the_reviewer_queue_s_and_does_not_fail() -> None:
    case = load("EV-SUP-001")
    extra = edge("aurora", "supplies", "borealis", state="needs_human_review")
    check = unexpected(case, [edge("borealis", "supplies", "aurora"), extra])
    assert check.passed
    assert check.observed == {"verified": 1, "unexpected": []}


def test_a_gold_claim_names_an_edge_as_well_as_a_gold_relationship() -> None:
    case = load("EV-INF-001")  # three claims and three relationships
    named = {(c.subject, c.predicate, c.object) for c in case.gold.claims}
    subject, predicate, obj = next(iter(named))
    assert obj is not None
    assert unexpected(case, [edge(subject, predicate, obj)]).passed


def test_cases_whose_pipeline_produces_no_edges_are_not_scored_for_it() -> None:
    for case_id in ("EV-RST-001", "EV-SYN-001"):
        case = load(case_id)
        assert not [c for c in score(case, {}) if c.key == "relationships.unexpected"]
        raw = json.loads((CASES / f"{case_id}.json").read_bytes())
        assert raw["pipeline"]["kind"] in ("financials", "families")
