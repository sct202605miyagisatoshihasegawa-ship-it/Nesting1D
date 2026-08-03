from copy import deepcopy

import pytest

from app.calculation.selection import (
    DEFAULT_REMNANT_TOLERANCE_MM,
    DEFAULT_WASTE_TOLERANCE_MM,
    NoFullySatisfiedCandidateError,
    SelectionCandidate,
    build_stable_tie_break_key,
    select_candidate,
)


def candidate(
    name: str,
    *,
    fully_satisfied: bool = True,
    purchases: int = 0,
    waste: int = 0,
    remnant: int = 0,
    remnant_count: int = 0,
    patterns: int = 1,
    changes: int = 0,
    stocks=None,
    unused=None,
) -> SelectionCandidate:
    return SelectionCandidate(
        stocks=stocks or ((name, 1000, (500,), 500),),
        unused=unused or (
            {
                "source_type": "existing_remnant",
                "length_mm": 600,
                "quantity": 1,
                "reason_code": "NOT_NEEDED",
            },
        ),
        inventory_completed=((500, 1),),
        fully_satisfied=fully_satisfied,
        additional_new_stock_count=purchases,
        waste_length_mm=waste,
        remnant_length_mm=remnant,
        remnant_count=remnant_count,
        pattern_count=patterns,
        dimension_change_count=changes,
    )


def test_same_candidate_content_always_builds_same_stable_key():
    assert candidate("a").stable_tie_break_key == candidate("a").stable_tie_break_key


def test_unused_dictionary_key_order_does_not_change_stable_key():
    first = {"source_type": "existing_remnant", "length_mm": 600, "quantity": 2, "reason_code": "NOT_NEEDED"}
    second = {"reason_code": "NOT_NEEDED", "quantity": 2, "length_mm": 600, "source_type": "existing_remnant"}
    assert candidate("a", unused=(first,)).stable_tie_break_key == candidate("a", unused=(second,)).stable_tie_break_key


def test_unused_registration_order_does_not_change_stable_key():
    first = {"source_type": "existing_remnant", "length_mm": 600, "quantity": 1}
    second = {"source_type": "held_new_stock", "length_mm": 1000, "quantity": 2}
    assert candidate("a", unused=(first, second)).stable_tie_break_key == candidate("a", unused=(second, first)).stable_tie_break_key


def test_unused_reason_code_is_excluded_from_stable_key():
    first = {"source_type": "existing_remnant", "length_mm": 600, "quantity": 1, "reason_code": "NOT_NEEDED"}
    second = first | {"reason_code": "NOT_SELECTED_BY_CANDIDATE_SELECTION"}
    assert candidate("a", unused=(first,)).stable_tie_break_key == candidate("a", unused=(second,)).stable_tie_break_key


@pytest.mark.parametrize(
    ("first_stock", "second_stock"),
    [
        (("existing_remnant", 600, (500,), 100), ("existing_remnant", 700, (500,), 200)),
        (("existing_remnant", 600, (500,), 100), ("existing_remnant", 600, (400,), 200)),
        (("existing_remnant", 600, (400, 200), 0), ("existing_remnant", 600, (200, 400), 0)),
        (("existing_remnant", 600, (500,), 100), ("existing_remnant", 600, (500,), 99)),
    ],
)
def test_used_stock_content_changes_stable_key(first_stock, second_stock):
    assert candidate("a", stocks=(first_stock,)).stable_tie_break_key != candidate("a", stocks=(second_stock,)).stable_tie_break_key


def test_used_stock_order_is_preserved_in_stable_key():
    first = ("existing_remnant", 600, (500,), 100)
    second = ("inventory_new_stock", 1000, (500,), 500)
    assert candidate("a", stocks=(first, second)).stable_tie_break_key != candidate("a", stocks=(second, first)).stable_tie_break_key


@pytest.mark.parametrize(
    ("first_unused", "second_unused"),
    [
        ({"source_type": "existing_remnant", "length_mm": 600, "quantity": 1}, {"source_type": "existing_remnant", "length_mm": 700, "quantity": 1}),
        ({"source_type": "existing_remnant", "length_mm": 600, "quantity": 1}, {"source_type": "existing_remnant", "length_mm": 600, "quantity": 2}),
    ],
)
def test_unused_material_content_changes_stable_key(first_unused, second_unused):
    assert candidate("a", unused=(first_unused,)).stable_tie_break_key != candidate("a", unused=(second_unused,)).stable_tie_break_key


def test_building_stable_key_does_not_mutate_source_data():
    stocks = [["existing_remnant", 600, [400, 200], 0]]
    unused = [{"quantity": 1, "length_mm": 600, "source_type": "existing_remnant", "reason_code": "NOT_NEEDED"}]
    before_stocks = deepcopy(stocks)
    before_unused = deepcopy(unused)
    key = build_stable_tie_break_key(stocks, unused)
    assert key == candidate("a", stocks=stocks, unused=unused).stable_tie_break_key
    assert stocks == before_stocks
    assert unused == before_unused


def test_stable_key_snapshot_does_not_change_after_source_mutation():
    stocks = [["existing_remnant", 600, [500], 100]]
    unused = [{"source_type": "existing_remnant", "length_mm": 600, "quantity": 1}]
    planned = candidate("a", stocks=stocks, unused=unused)
    original_key = planned.stable_tie_break_key
    stocks[0][2].append(50)
    unused[0]["quantity"] = 2
    assert planned.stable_tie_break_key == original_key


def test_real_stable_key_selects_same_candidate_regardless_of_input_order():
    first = candidate("existing_remnant")
    second = candidate("inventory_new_stock")
    assert select_candidate([second, first]) is first
    assert select_candidate([first, second]) is first


def test_reason_code_does_not_override_plan_content_in_selection():
    preferred_unused = {"source_type": "existing_remnant", "length_mm": 600, "quantity": 1, "reason_code": "ZZZ"}
    other_unused = preferred_unused | {"reason_code": "AAA"}
    preferred = candidate("a", unused=(preferred_unused,))
    other = candidate("b", unused=(other_unused,))
    assert select_candidate([other, preferred]) is preferred
    assert select_candidate([preferred, other]) is preferred


def test_unsatisfied_candidate_is_excluded():
    unsatisfied = candidate("a", fully_satisfied=False, purchases=0)
    satisfied = candidate("b", purchases=1)
    assert select_candidate([unsatisfied, satisfied]) is satisfied


def test_no_fully_satisfied_candidate_raises_explicit_error():
    with pytest.raises(NoFullySatisfiedCandidateError):
        select_candidate([candidate("a", fully_satisfied=False)])


def test_fewer_additional_new_stocks_always_wins():
    fewer = candidate("z", purchases=1, waste=100, patterns=10, changes=10)
    more = candidate("a", purchases=2, waste=0, patterns=1, changes=0)
    assert select_candidate([more, fewer]) is fewer


@pytest.mark.parametrize("waste_difference", [9, 10])
def test_waste_difference_within_tolerance_is_not_significant(waste_difference):
    less_waste_but_more_work = candidate("b", waste=0, patterns=2)
    more_waste_but_less_work = candidate("a", waste=waste_difference, patterns=1)
    assert select_candidate(
        [less_waste_but_more_work, more_waste_but_less_work],
        waste_tolerance_mm=10,
    ) is more_waste_but_less_work


def test_waste_difference_above_tolerance_prefers_less_waste():
    less_waste = candidate("b", waste=0, patterns=2)
    more_waste = candidate("a", waste=11, patterns=1)
    assert select_candidate(
        [more_waste, less_waste], waste_tolerance_mm=10
    ) is less_waste


def test_remnant_above_tolerance_prefers_less_remnant():
    less_remnant = candidate("z", remnant=100, patterns=2)
    more_remnant = candidate("a", remnant=126, patterns=1)
    assert select_candidate(
        [more_remnant, less_remnant], remnant_tolerance_mm=25
    ) is less_remnant


@pytest.mark.parametrize("remnant_difference", [9, 10])
def test_remnant_within_tolerance_proceeds_to_workability(remnant_difference):
    less_remnant_but_more_work = candidate("b", remnant=0, patterns=2)
    more_remnant_but_less_work = candidate(
        "a", remnant=remnant_difference, patterns=1
    )
    assert select_candidate(
        [less_remnant_but_more_work, more_remnant_but_less_work],
        remnant_tolerance_mm=10,
    ) is more_remnant_but_less_work


def test_remnant_count_wins_when_remnant_length_is_within_tolerance():
    fewer_remnants = candidate("z", remnant=10, remnant_count=1, patterns=2)
    more_remnants = candidate("a", remnant=0, remnant_count=2, patterns=1)
    assert select_candidate(
        [more_remnants, fewer_remnants], remnant_tolerance_mm=10
    ) is fewer_remnants


def test_waste_comparison_precedes_remnant_length_comparison():
    less_waste = candidate("z", waste=0, remnant=100, patterns=2)
    less_remnant = candidate("a", waste=11, remnant=0, patterns=1)
    assert select_candidate(
        [less_remnant, less_waste],
        waste_tolerance_mm=10,
        remnant_tolerance_mm=0,
    ) is less_waste


def test_remnant_length_comparison_precedes_remnant_count_comparison():
    less_remnant = candidate("z", remnant=0, remnant_count=2, patterns=2)
    fewer_remnants = candidate("a", remnant=11, remnant_count=1, patterns=1)
    assert select_candidate(
        [fewer_remnants, less_remnant], remnant_tolerance_mm=10
    ) is less_remnant


def test_pattern_count_wins_when_remnant_count_matches():
    fewer_patterns = candidate("z", remnant_count=1, patterns=1, changes=2)
    more_patterns = candidate("a", remnant_count=1, patterns=2, changes=0)
    assert select_candidate([more_patterns, fewer_patterns]) is fewer_patterns


def test_waste_and_remnant_tolerances_act_independently():
    less_waste = candidate("z", waste=0, remnant=20, patterns=2)
    less_remnant = candidate("a", waste=10, remnant=0, patterns=1)
    assert select_candidate(
        [less_waste, less_remnant],
        waste_tolerance_mm=10,
        remnant_tolerance_mm=5,
    ) is less_remnant
    assert select_candidate(
        [less_waste, less_remnant],
        waste_tolerance_mm=5,
        remnant_tolerance_mm=20,
    ) is less_waste


def test_candidate_clearly_worse_in_waste_is_removed():
    better = candidate("z", waste=20, patterns=3)
    outside_waste_tolerance = candidate("a", waste=31, patterns=1)
    assert select_candidate(
        [outside_waste_tolerance, better], waste_tolerance_mm=10
    ) is better


def test_fewer_patterns_wins_when_materially_equivalent():
    fewer = candidate("z", waste=10, patterns=1, changes=5)
    more = candidate("a", waste=0, patterns=2, changes=0)
    assert select_candidate([more, fewer], waste_tolerance_mm=10) is fewer


def test_fewer_dimension_changes_wins_when_pattern_count_matches():
    fewer = candidate("z", patterns=2, changes=1)
    more = candidate("a", patterns=2, changes=2)
    assert select_candidate([more, fewer]) is fewer


def test_stable_key_decides_when_all_other_metrics_match():
    first = candidate("a")
    second = candidate("b")
    assert first.stable_tie_break_key < second.stable_tie_break_key
    assert select_candidate([second, first]) is first


def test_reversing_candidate_input_order_does_not_change_result():
    candidates = [
        candidate("c", waste=10, patterns=1),
        candidate("a", waste=0, patterns=1),
        candidate("b", waste=5, patterns=1),
    ]
    assert select_candidate(candidates, waste_tolerance_mm=10) is candidates[1]
    assert select_candidate(list(reversed(candidates)), waste_tolerance_mm=10) is candidates[1]


def test_reversing_input_order_with_remnant_metrics_does_not_change_result():
    candidates = [
        candidate("c", remnant=10, remnant_count=2),
        candidate("a", remnant=0, remnant_count=1),
        candidate("b", remnant=5, remnant_count=1),
    ]
    selected = select_candidate(candidates, remnant_tolerance_mm=10)
    reversed_selected = select_candidate(
        list(reversed(candidates)), remnant_tolerance_mm=10
    )
    assert selected is candidates[1]
    assert reversed_selected is candidates[1]


def test_selection_does_not_mutate_candidates_or_source_list():
    candidates = [candidate("b"), candidate("a")]
    before = deepcopy(candidates)
    selected = select_candidate(candidates)
    assert selected is candidates[1]
    assert candidates == before


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("waste_tolerance_mm", -1),
        ("remnant_tolerance_mm", -1),
        ("waste_tolerance_mm", True),
        ("remnant_tolerance_mm", False),
    ],
)
def test_invalid_tolerance_is_rejected(keyword, value):
    with pytest.raises(ValueError, match=keyword):
        select_candidate([candidate("a")], **{keyword: value})


def test_default_zero_tolerances_use_strict_waste_and_remnant_comparison():
    less_waste = candidate("z", waste=0, remnant=100, patterns=2)
    more_waste = candidate("a", waste=1, remnant=0, patterns=1)
    less_remnant = candidate("z", waste=0, remnant=0, patterns=2)
    more_remnant = candidate("a", waste=0, remnant=1, patterns=1)
    assert DEFAULT_WASTE_TOLERANCE_MM == 0
    assert DEFAULT_REMNANT_TOLERANCE_MM == 0
    assert select_candidate([more_waste, less_waste]) is less_waste
    assert select_candidate([more_remnant, less_remnant]) is less_remnant
