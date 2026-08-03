from copy import deepcopy
from inspect import getsource

import pytest

from app.calculation import CalculationInput
from app.calculation import engine
from app.calculation.selection import SelectionCandidate


def _required_input() -> CalculationInput:
    return CalculationInput.model_validate(
        {
            "mode": "required_stock",
            "cutting_conditions": {
                "new_stock_length_mm": 1000,
                "kerf_mm": 0,
                "left_trim_mm": 0,
            },
            "required_parts": [
                {"length_mm": 400, "quantity": 1},
                {"length_mm": 200, "quantity": 1},
            ],
        }
    )


def _inventory_input() -> CalculationInput:
    return CalculationInput.model_validate(
        {
            "mode": "inventory",
            "cutting_conditions": {
                "new_stock_length_mm": 1000,
                "kerf_mm": 0,
                "left_trim_mm": 0,
            },
            "required_parts": [{"length_mm": 600, "quantity": 1}],
            "inventory": {
                "new_stock_quantity": 1,
                "remnants": [{"length_mm": 600, "quantity": 1}],
            },
        }
    )


def _candidate(
    *,
    stocks,
    unused=(),
    inventory_completed=(),
    additional=1,
    waste=0,
    remnant=0,
    remnant_count=0,
    patterns=1,
    changes=1,
) -> SelectionCandidate:
    return SelectionCandidate(
        stocks=tuple(stocks),
        unused=tuple(unused),
        inventory_completed=tuple(inventory_completed),
        fully_satisfied=True,
        additional_new_stock_count=additional,
        waste_length_mm=waste,
        remnant_length_mm=remnant,
        remnant_count=remnant_count,
        pattern_count=patterns,
        dimension_change_count=changes,
    )


@pytest.mark.parametrize(
    ("data", "expected_count"),
    [(_required_input(), 2), (_inventory_input(), 4)],
)
def test_builds_every_existing_plan_as_selection_candidate(
    data: CalculationInput, expected_count: int
) -> None:
    candidates = engine._build_selection_candidates(data)

    assert len(candidates) == expected_count
    assert all(isinstance(candidate, SelectionCandidate) for candidate in candidates)


def test_required_stock_uses_selected_candidate_and_preserves_cut_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _required_input()
    not_selected = _candidate(
        stocks=(("additional_new_stock", 1000, (400, 200), 400),),
        remnant=400,
    )
    selected = _candidate(
        stocks=(("additional_new_stock", 600, (200, 400), 0),),
        remnant=0,
    )
    monkeypatch.setattr(
        engine, "_build_selection_candidates", lambda _: (not_selected, selected)
    )

    result = engine.calculate(data)

    assert result.stock_usage[0]["original_length_mm"] == 600
    assert result.stock_usage[0]["cuts"] == [200, 400]
    assert result.stock_usage[0]["remaining_length_mm"] == 0


def test_candidate_generation_order_does_not_change_selected_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _required_input()
    first = _candidate(
        stocks=(("additional_new_stock", 1000, (400, 200), 400),),
        remnant=400,
    )
    second = _candidate(
        stocks=(("additional_new_stock", 600, (200, 400), 0),),
        remnant=0,
    )
    monkeypatch.setattr(engine, "_build_selection_candidates", lambda _: (first, second))
    forward = engine.calculate(data).model_dump()
    monkeypatch.setattr(engine, "_build_selection_candidates", lambda _: (second, first))

    assert engine.calculate(data).model_dump() == forward


def test_inventory_result_uses_one_selected_candidate_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _inventory_input()
    selected = _candidate(
        stocks=(("existing_remnant", 600, (600,), 0),),
        unused=(
            {
                "source_type": "held_new_stock",
                "length_mm": 1000,
                "quantity": 1,
                "reason_code": "NOT_NEEDED",
            },
        ),
        inventory_completed=((600, 1),),
        additional=0,
        changes=0,
    )
    rejected = _candidate(
        stocks=(("additional_new_stock", 1000, (600,), 400),),
        unused=(
            {
                "source_type": "existing_remnant",
                "length_mm": 600,
                "quantity": 1,
                "reason_code": "NOT_SELECTED_BY_CANDIDATE_SELECTION",
            },
        ),
        inventory_completed=(),
        additional=1,
        remnant=400,
        remnant_count=1,
        changes=0,
    )
    monkeypatch.setattr(
        engine, "_build_selection_candidates", lambda _: (rejected, selected)
    )

    result = engine.calculate(data)

    assert result.existing_remnant_used == 1
    assert result.additional_new_stock_required == 0
    assert result.unused_inventory == list(selected.unused)
    assert result.unused_inventory != list(rejected.unused)
    assert result.fulfillment[0]["completed_from_inventory_quantity"] == 1
    assert result.fulfillment[0]["shortage_before_purchase_quantity"] == 0


def test_calculate_keeps_result_schema_and_does_not_modify_input() -> None:
    data = _required_input()
    before = deepcopy(data)

    result = engine.calculate(data)

    assert data == before
    assert set(result.model_dump()) == {
        "mode",
        "required_stock_quantity",
        "additional_new_stock_required",
        "existing_remnant_used",
        "inventory_new_stock_used",
        "patterns",
        "stock_usage",
        "unused_inventory",
        "dimension_change_count",
        "initial_setup_count",
        "machine_setting_count",
        "fulfillment",
    }


def test_calculate_delegates_candidate_comparison_to_select_candidate() -> None:
    source = getsource(engine.calculate)

    assert "select_candidate(" in source
    assert "score=" not in source
    assert "min(candidates" not in source
