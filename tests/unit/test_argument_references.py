"""A statement never shows the Editor's Fact references (bottleneck-argument ticket 08).

Seam: `without_references`, which the argument Editor's task applies to each statement before
the grounding check. Pilot question 3 on 0.5.3 (2026-10-07) printed "c1" where Coherent was
meant.
"""

from atlas.investigations.argument import without_references

REFS = {
    "c1": {"id": "f-1", "subject_name": "Coherent"},
    "c2": {"id": "f-2", "subject_name": "Fabrinet"},
    "c12": {"id": "f-12", "subject_name": "Applied Optoelectronics"},
}


def test_a_cited_reference_becomes_its_fact_s_company() -> None:
    said = "c1 says its data center grew about 4% sequentially."
    assert without_references(said, ["c1"], REFS) == (
        "Coherent says its data center grew about 4% sequentially."
    )


def test_each_reference_by_its_own_fact() -> None:
    said = "c12 is adding capacity while c2 is short of one component."
    assert without_references(said, ["c2", "c12"], REFS) == (
        "Applied Optoelectronics is adding capacity while Fabrinet is short of one component."
    )


def test_a_reference_it_does_not_cite_drops_the_statement() -> None:
    assert without_references("Unlike c2, c1 is not constrained.", ["c1"], REFS) is None


def test_words_only_shaped_like_a_reference_are_left() -> None:
    said = "Coherent's C3 band lasers and its c99 roadmap"  # c99 is no reference it was given
    assert without_references(said, ["c1"], REFS) == said
    assert without_references("Coherent abc1 test", ["c1"], REFS) == "Coherent abc1 test"
