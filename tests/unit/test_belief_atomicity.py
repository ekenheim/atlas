"""A Belief is one proposition (atlas-beliefs ticket 23): the deterministic check on its words,
run before the judge is asked. Pure; the statements are the kinds the MCP session of 2026-10-15
proposed or the skill's rule names."""

import pytest

from atlas.beliefs.atomicity import compound_reasons


@pytest.mark.parametrize(
    "statement",
    [
        "AXT has no U.S. InP export permits as of its 10-Q.",
        "Lumentum calls indium phosphide substrates very significant to its laser supply.",
        "Coherent's fiscal 2026 net revenue was $6.2 billion.",
        "Dr. Lisa T. Su said AMD's capacity is sold out through 2027.",
        "Revenue grew from $1.0 billion in 2024 to $2.0 billion in 2025.",
        "AXT supplies Coherent with InP substrates under a long-term agreement.",
        "Q3 FY2026 net revenue was $1.01 billion.",
        "Lumentum expects constraints to ease in H2 of fiscal 2027",
        "Soitec plans 3.5 million wafers a year.",
    ],
)
def test_an_atomic_statement_has_no_reasons(statement: str) -> None:
    assert compound_reasons(statement) == []


def test_two_sentences_are_two_propositions() -> None:
    reasons = compound_reasons(
        "AXT has no U.S. InP permits. Lumentum calls substrates very significant."
    )
    assert reasons == ["it is more than one sentence"]


def test_a_semicolon_joins_clauses() -> None:
    reasons = compound_reasons("Lumentum is capacity constrained; AXT is waiting on permits")
    assert reasons == ["a semicolon joins its clauses"]


def test_respectively_pairs_subjects_with_figures() -> None:
    reasons = compound_reasons(
        "Casela and Coherent bought $22.3 million and $25.4 million respectively"
    )
    assert len(reasons) == 1 and "respectively" in reasons[0]


def test_several_periods_are_more_than_one() -> None:
    quarters = compound_reasons("Coherent's capacity was sold out in Q2 FY2026 and Q3 FY2026")
    assert quarters == ["it names several quarters or halves: Q2 FY2026, Q3 FY2026"]
    fiscal = compound_reasons("Lumentum's backlog doubled between FY2025 and FY2026")
    assert fiscal == ["it names several fiscal years: FY2025, FY2026"]
    years = compound_reasons("Supply was short in 2023, 2024 and 2025")
    assert years == ["it names several years: 2023, 2024, 2025"]


def test_a_quarter_and_its_own_fiscal_year_are_one_period() -> None:
    assert compound_reasons("Q3 FY2026 revenue rose; the quarter ended March 28") == [
        "a semicolon joins its clauses"
    ]
    assert compound_reasons("Q3 revenue in FY2026 rose") == []


def test_every_reason_is_given() -> None:
    reasons = compound_reasons("AXT shipped in Q1 and Q2; Coherent did not. It was short.")
    assert reasons == [
        "it is more than one sentence",
        "a semicolon joins its clauses",
        "it names several quarters or halves: Q1, Q2",
    ]
