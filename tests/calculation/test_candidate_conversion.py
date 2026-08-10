# Nesting1D - 候補変換テスト
# 役割: 計算計画から選別候補への評価値と安定キーの変換を検証する。
# 更新日: 2026-08-10

from collections import Counter
from copy import deepcopy

from app.calculation.engine import _build_selection_candidate, _plan
from app.calculation.models import CalculationInput
from app.calculation.selection import select_candidate


def _inventory_input() -> CalculationInput:
    return CalculationInput.model_validate(
        {
            "mode": "inventory",
            "cutting_conditions": {
                "new_stock_length_mm": 3000,
                "kerf_mm": 3,
                "left_trim_mm": 10,
            },
            "required_parts": [{"length_mm": 1000, "quantity": 1}],
            "inventory": {
                "new_stock_quantity": 1,
                "remnants": [{"length_mm": 1200, "quantity": 1}],
            },
        }
    )


def _required_stock_input() -> CalculationInput:
    return CalculationInput.model_validate(
        {
            "mode": "required_stock",
            "cutting_conditions": {
                "new_stock_length_mm": 1000,
                "kerf_mm": 0,
                "left_trim_mm": 0,
            },
            "required_parts": [{"length_mm": 400, "quantity": 2}],
        }
    )


def _metric_input() -> CalculationInput:
    return CalculationInput.model_validate(
        {
            "mode": "inventory",
            "cutting_conditions": {
                "new_stock_length_mm": 1000,
                "kerf_mm": 0,
                "left_trim_mm": 0,
            },
            "required_parts": [
                {"length_mm": 500, "quantity": 1},
                {"length_mm": 50, "quantity": 2},
            ],
            "inventory": {"new_stock_quantity": 1, "remnants": []},
        }
    )


def test_builds_candidate_from_plan_using_existing_remnant() -> None:
    data = _inventory_input()
    plan = _plan(data, (1000,), True)

    candidate = _build_selection_candidate(data, plan)

    assert candidate.stocks[0][0] == "existing_remnant"
    assert candidate.fully_satisfied is True


def test_builds_candidate_from_plan_without_using_existing_remnant() -> None:
    data = _inventory_input()
    plan = _plan(data, (1000,), False)

    candidate = _build_selection_candidate(data, plan)

    assert all(stock[0] != "existing_remnant" for stock in candidate.stocks)
    assert candidate.unused[0]["source_type"] == "existing_remnant"


def test_required_stock_plan_can_be_converted_without_inventory_data() -> None:
    data = _required_stock_input()
    plan = _plan(data, (400, 400), True)

    candidate = _build_selection_candidate(data, plan)

    assert candidate.fully_satisfied is True
    assert candidate.inventory_completed == ()
    assert candidate.unused == ()
    assert candidate.additional_new_stock_count == 1


def test_candidate_metrics_and_plan_data_are_built_from_existing_plan() -> None:
    data = _metric_input()
    plan = (
        [
            ("existing_remnant", 600, (500,)),
            ("inventory_new_stock", 100, (50,)),
            ("additional_new_stock", 100, (50,)),
        ],
        [
            {
                "source_type": "held_new_stock",
                "length_mm": 1000,
                "quantity": 1,
                "reason_code": "NOT_USED",
            }
        ],
        Counter({500: 1, 50: 1}),
    )

    candidate = _build_selection_candidate(data, plan)

    assert candidate.stocks == (
        ("existing_remnant", 600, (500,), 100),
        ("inventory_new_stock", 100, (50,), 50),
        ("additional_new_stock", 100, (50,), 50),
    )
    assert candidate.unused == tuple(plan[1])
    assert candidate.inventory_completed == ((500, 1), (50, 1))
    assert candidate.fully_satisfied is True
    assert candidate.additional_new_stock_count == 1
    assert candidate.waste_length_mm == 100
    assert candidate.remnant_length_mm == 100
    assert candidate.remnant_count == 1
    assert candidate.pattern_count == 2
    assert candidate.dimension_change_count == 1
    assert candidate.stable_tie_break_key


def test_incomplete_plan_is_not_fully_satisfied() -> None:
    data = _metric_input()
    plan = (
        [("additional_new_stock", 600, (500, 50))],
        [],
        Counter(),
    )

    candidate = _build_selection_candidate(data, plan)

    assert candidate.fully_satisfied is False


def test_only_additional_new_stock_is_counted_as_purchase() -> None:
    data = _metric_input()
    plan = (
        [
            ("existing_remnant", 500, (500,)),
            ("inventory_new_stock", 50, (50,)),
            ("additional_new_stock", 50, (50,)),
        ],
        [],
        Counter({500: 1, 50: 1}),
    )

    candidate = _build_selection_candidate(data, plan)

    assert candidate.additional_new_stock_count == 1


def test_remainder_metrics_use_fixed_50_51_boundary() -> None:
    data = CalculationInput.model_validate(
        {
            "mode": "required_stock",
            "cutting_conditions": {
                "new_stock_length_mm": 157,
                "kerf_mm": 3,
                "left_trim_mm": 0,
            },
            "required_parts": [{"length_mm": 100, "quantity": 2}],
        }
    )
    plan = (
        [
            ("additional_new_stock", 156, (100,)),
            ("additional_new_stock", 157, (100,)),
        ],
        [],
        Counter(),
    )

    candidate = _build_selection_candidate(data, plan)

    assert candidate.waste_length_mm == 50
    assert candidate.remnant_length_mm == 51
    assert candidate.remnant_count == 1


def test_fixed_boundary_is_reflected_in_candidate_selection() -> None:
    data = CalculationInput.model_validate(
        {
            "mode": "required_stock",
            "cutting_conditions": {
                "new_stock_length_mm": 157,
                "kerf_mm": 3,
                "left_trim_mm": 0,
            },
            "required_parts": [{"length_mm": 100, "quantity": 1}],
        }
    )
    scrap_candidate = _build_selection_candidate(
        data,
        ([("additional_new_stock", 156, (100,))], [], Counter()),
    )
    remnant_candidate = _build_selection_candidate(
        data,
        ([("additional_new_stock", 157, (100,))], [], Counter()),
    )

    selected = select_candidate([scrap_candidate, remnant_candidate])

    assert scrap_candidate.waste_length_mm == 50
    assert remnant_candidate.waste_length_mm == 0
    assert selected is remnant_candidate


def test_pattern_count_uses_existing_cut_pattern_definition() -> None:
    data = CalculationInput.model_validate(
        {
            "mode": "required_stock",
            "cutting_conditions": {
                "new_stock_length_mm": 500,
                "kerf_mm": 0,
                "left_trim_mm": 0,
            },
            "required_parts": [{"length_mm": 100, "quantity": 2}],
        }
    )
    plan = (
        [
            ("existing_remnant", 150, (100,)),
            ("additional_new_stock", 500, (100,)),
        ],
        [],
        Counter(),
    )

    candidate = _build_selection_candidate(data, plan)

    assert candidate.pattern_count == 1


def test_dimension_changes_use_existing_pattern_order_definition() -> None:
    data = CalculationInput.model_validate(
        {
            "mode": "required_stock",
            "cutting_conditions": {
                "new_stock_length_mm": 6000,
                "kerf_mm": 0,
                "left_trim_mm": 0,
            },
            "required_parts": [
                {"length_mm": 2300, "quantity": 2},
                {"length_mm": 950, "quantity": 2},
                {"length_mm": 500, "quantity": 1},
            ],
        }
    )
    plan = (
        [
            ("additional_new_stock", 6000, (2300, 2300, 950)),
            ("additional_new_stock", 6000, (950, 500)),
        ],
        [],
        Counter(),
    )

    candidate = _build_selection_candidate(data, plan)

    assert candidate.dimension_change_count == 2


def test_reason_code_does_not_change_metrics_or_tie_break_key() -> None:
    data = _metric_input()
    stocks = [("additional_new_stock", 600, (500, 50, 50))]
    first = _build_selection_candidate(
        data,
        (
            stocks,
            [{"source_type": "held_new_stock", "length_mm": 1000, "quantity": 1, "reason_code": "FIRST"}],
            Counter(),
        ),
    )
    second = _build_selection_candidate(
        data,
        (
            stocks,
            [{"source_type": "held_new_stock", "length_mm": 1000, "quantity": 1, "reason_code": "SECOND"}],
            Counter(),
        ),
    )

    assert (
        first.fully_satisfied,
        first.additional_new_stock_count,
        first.waste_length_mm,
        first.remnant_length_mm,
        first.remnant_count,
        first.pattern_count,
        first.dimension_change_count,
        first.stable_tie_break_key,
    ) == (
        second.fully_satisfied,
        second.additional_new_stock_count,
        second.waste_length_mm,
        second.remnant_length_mm,
        second.remnant_count,
        second.pattern_count,
        second.dimension_change_count,
        second.stable_tie_break_key,
    )


def test_candidate_copies_plan_data_and_does_not_modify_inputs() -> None:
    data = _metric_input()
    stocks = [["additional_new_stock", 600, [500, 50, 50]]]
    unused = [
        {
            "source_type": "held_new_stock",
            "length_mm": 1000,
            "quantity": 1,
            "reason_code": "NOT_USED",
        }
    ]
    inventory_completed = Counter({500: 1})
    plan = (stocks, unused, inventory_completed)
    original = deepcopy(plan)

    candidate = _build_selection_candidate(data, plan)
    original_key = candidate.stable_tie_break_key

    assert plan == original
    unused[0]["quantity"] = 9
    stocks[0][1] = 999
    stocks[0][2].append(25)
    inventory_completed[500] = 9
    assert candidate.unused[0]["quantity"] == 1
    assert candidate.stocks == (("additional_new_stock", 600, (500, 50, 50), 0),)
    assert candidate.inventory_completed == ((500, 1),)
    assert candidate.stable_tie_break_key == original_key
