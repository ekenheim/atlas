"""Which companies a round reads beyond its seeds (memory-directed reading ticket 06): the
ranking of companies by their reading pointers and the allotment of Investigators within the
company budget. Pure functions (`atlas.investigations.companies`); the expected orders follow
from the documented weight, a pointer at rank r weighing 1/r."""

from atlas.investigations.companies import PointerWeight, allot, rank_companies


def ranked(ranks: dict[str, list[int]]) -> list[str]:
    return [slug for slug, _ in rank_companies(ranks)]


def test_a_company_s_weight_is_its_pointers_each_counted_by_its_rank() -> None:
    [(slug, weight)] = rank_companies({"axt": [1, 2, 4]})

    assert slug == "axt"
    assert weight == PointerWeight(pointers=3, score=1.75, best_rank=1)  # 1 + 1/2 + 1/4


def test_companies_are_ranked_by_weight_best_first() -> None:
    # AXT: 1 + 1 = 2; Coherent: 1/2 + 1/3 + 1/4 = 1.0833; Lumentum: 1.
    ranks = {"lumentum": [1], "coherent": [2, 3, 4], "axt": [1, 1]}

    assert ranked(ranks) == ["axt", "coherent", "lumentum"]
    assert dict(rank_companies(ranks))["coherent"] == PointerWeight(3, 1.0833, 2)


def test_one_top_ranked_pointer_outweighs_many_far_down_the_recall() -> None:
    # Five pointers at rank 10 weigh 0.5 together; one at rank 1 weighs 1.
    assert ranked({"many-low": [10, 10, 10, 10, 10], "one-top": [1]}) == ["one-top", "many-low"]


def test_several_good_pointers_outweigh_one_better_one() -> None:
    # Three at rank 2 weigh 1.5; one at rank 1 weighs 1.
    assert ranked({"one": [1], "three": [2, 2, 2]}) == ["three", "one"]


def test_equal_weights_are_ordered_by_best_rank_then_slug() -> None:
    # 1 = 1/2 + 1/2: the company with the rank-1 pointer first.
    assert ranked({"two-halves": [2, 2], "one-whole": [1]}) == ["one-whole", "two-halves"]
    assert ranked({"macom": [3], "axt": [3], "iqe": [3]}) == ["axt", "iqe", "macom"]


def test_a_company_with_no_pointer_is_not_ranked() -> None:
    assert rank_companies({"axt": [], "iqe": [2]}) == [("iqe", PointerWeight(1, 0.5, 2))]
    assert rank_companies({}) == []


def test_an_entity_pointer_weighs_half_a_top_recall_pointer_over_its_rank_by_default() -> None:
    # Memory-quality ticket 09: AXT reached only by the entity hop, two pointers (1/2 + 1/4);
    # IQE by one recall pointer at rank 2 (1/2) and one entity pointer at rank 1 (1/2).
    weights = dict(rank_companies({"iqe": [2]}, {"axt": [1, 2], "iqe": [1]}))

    assert weights["axt"] == PointerWeight(0, 0.75, None, entity_pointers=2)
    assert weights["iqe"] == PointerWeight(1, 1.0, 2, entity_pointers=1)
    assert weights["axt"].as_json() == {
        "pointers": 0,
        "entity_pointers": 2,
        "score": 0.75,
        "best_rank": None,
    }


def test_the_entity_pointer_weight_is_a_setting_and_ties_go_to_a_recall_rank() -> None:
    # At weight 1 an entity pointer at rank 2 weighs what a recall pointer at rank 2 does; the
    # company with a recall rank comes first.
    assert [
        slug for slug, _ in rank_companies({"macom": [2]}, {"axt": [2]}, entity_weight=1.0)
    ] == ["macom", "axt"]
    assert [slug for slug, _ in rank_companies({"macom": [3]}, {"axt": [1]})] == ["axt", "macom"]


def test_seeds_are_read_whatever_their_rank_and_the_others_in_rank_order_while_there_is_room() -> (
    None
):
    outcomes = allot(
        ["axt", "coherent", "macom", "iqe", "lumentum"],
        reading={"coherent", "lumentum"},
        disproven=set(),
        max_companies=4,
    )

    assert outcomes == {
        "axt": "added",
        "coherent": "seed",
        "macom": "added",
        "iqe": "no_room",
        "lumentum": "seed",
    }


def test_the_seeds_count_against_the_company_budget_even_without_a_pointer() -> None:
    # Three seeds (one of them unpointed) fill a budget of three.
    outcomes = allot(
        ["axt", "coherent"],
        reading={"coherent", "lumentum", "ciena"},
        disproven=set(),
        max_companies=3,
    )

    assert outcomes == {"axt": "no_room", "coherent": "seed"}


def test_a_budget_below_the_number_of_seeds_adds_nobody_and_drops_no_seed() -> None:
    outcomes = allot(
        ["coherent", "axt", "lumentum"],
        reading={"coherent", "lumentum"},
        disproven=set(),
        max_companies=1,
    )

    assert outcomes == {"coherent": "seed", "axt": "no_room", "lumentum": "seed"}


def test_a_company_whose_premise_was_disproven_gets_no_investigator_and_takes_no_room() -> None:
    outcomes = allot(
        ["axt", "macom", "iqe"],
        reading={"coherent"},
        disproven={"axt"},
        max_companies=2,
    )

    assert outcomes == {"axt": "premise_disproven", "macom": "added", "iqe": "no_room"}
