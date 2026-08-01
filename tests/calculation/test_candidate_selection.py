from copy import deepcopy

import pytest

from app.calculation.selection import (
    DEFAULT_REMNANT_TOLERANCE_MM,
    DEFAULT_WASTE_TOLERANCE_MM,
    NoFullySatisfiedCandidateError,
    SelectionCandidate,
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
) -> SelectionCandidate:
    return SelectionCandidate(
        stocks=((name, 1000, (500,)),),
        unused=((name, "unused"),),
        inventory_completed=((500, 1),),
        fully_satisfied=fully_satisfied,
        additional_new_stock_count=purchases,
        waste_length_mm=waste,
        remnant_length_mm=remnant,
        remnant_count=remnant_count,
        pattern_count=patterns,
        dimension_change_count=changes,
        stable_tie_break_key=(name,),
    )


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


def test_remnant_length_alone_does_not_decide_preference():
    more_remnant = candidate("b", remnant=900, patterns=1)
    less_remnant = candidate("a", remnant=100, patterns=1)
    assert select_candidate(
        [more_remnant, less_remnant], remnant_tolerance_mm=25
    ) is less_remnant


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


def test_default_zero_tolerances_use_strict_waste_comparison():
    less_waste = candidate("z", waste=0, patterns=2)
    more_waste = candidate("a", waste=1, patterns=1)
    assert DEFAULT_WASTE_TOLERANCE_MM == 0
    assert DEFAULT_REMNANT_TOLERANCE_MM == 0
    assert select_candidate([more_waste, less_waste]) is less_waste
