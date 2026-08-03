import json
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import app.main as main_module
from app.calculation import CalculationInput, calculate
from app.calculation import engine
from app.calculation.engine import _plan
from app.exporting import make_record, render_report


NEW_REASON_CODE = "NOT_SELECTED_BY_CANDIDATE_SELECTION"
NEW_REASON_LABEL = "候補選別の結果、使用しない計画が選ばれたため未使用"


def _inventory_input(*, remnants, held, parts) -> CalculationInput:
    return CalculationInput.model_validate(
        {
            "mode": "inventory",
            "cutting_conditions": {
                "new_stock_length_mm": 1000,
                "kerf_mm": 0,
                "left_trim_mm": 0,
            },
            "required_parts": parts,
            "inventory": {
                "new_stock_quantity": held,
                "remnants": remnants,
            },
        }
    )


def _candidate_selection_input() -> CalculationInput:
    return _inventory_input(
        remnants=[{"length_mm": 600, "quantity": 1}],
        held=1,
        parts=[
            {"length_mm": 600, "quantity": 1},
            {"length_mm": 400, "quantity": 1},
        ],
    )


def test_plan_without_remnants_uses_candidate_selection_reason() -> None:
    data = _candidate_selection_input()

    _, unused, _ = _plan(data, (600, 400), False)

    assert unused[0]["reason_code"] == NEW_REASON_CODE


def test_calculation_outputs_only_new_reason_and_keeps_plan_result() -> None:
    result = calculate(_candidate_selection_input())

    assert result.unused_inventory == [
        {
            "source_type": "existing_remnant",
            "length_mm": 600,
            "quantity": 1,
            "reason_code": NEW_REASON_CODE,
        }
    ]
    assert result.existing_remnant_used == 0
    assert result.inventory_new_stock_used == 1
    assert result.additional_new_stock_required == 0
    assert result.stock_usage[0]["cuts"] == [600, 400]
    assert result.stock_usage[0]["remaining_length_mm"] == 0


def test_other_unused_reason_codes_are_unchanged() -> None:
    not_needed = calculate(
        _inventory_input(
            remnants=[{"length_mm": 600, "quantity": 2}],
            held=0,
            parts=[{"length_mm": 600, "quantity": 1}],
        )
    )
    no_fit = calculate(
        _inventory_input(
            remnants=[{"length_mm": 100, "quantity": 1}],
            held=0,
            parts=[{"length_mm": 600, "quantity": 1}],
        )
    )

    assert not_needed.unused_inventory[0]["reason_code"] == "NOT_NEEDED"
    assert no_fit.unused_inventory[0]["reason_code"] == "NO_REQUIRED_PART_FITS_AFTER_TRIM"


def test_physically_identical_candidates_keep_reason_when_order_is_reversed(
    monkeypatch,
) -> None:
    data = _inventory_input(
        remnants=[{"length_mm": 100, "quantity": 1}],
        held=0,
        parts=[{"length_mm": 600, "quantity": 1}],
    )
    candidates = engine._build_selection_candidates(data)

    assert len({candidate.stable_tie_break_key for candidate in candidates}) == 1
    assert {
        candidate.unused[0]["reason_code"] for candidate in candidates
    } == {"NO_REQUIRED_PART_FITS_AFTER_TRIM"}

    monkeypatch.setattr(engine, "_build_selection_candidates", lambda _: candidates)
    forward = engine.calculate(data).model_dump()
    monkeypatch.setattr(
        engine, "_build_selection_candidates", lambda _: tuple(reversed(candidates))
    )
    reversed_result = engine.calculate(data).model_dump()

    assert reversed_result == forward
    assert forward["unused_inventory"][0]["reason_code"] == "NO_REQUIRED_PART_FITS_AFTER_TRIM"
    assert forward["additional_new_stock_required"] == 1
    assert forward["stock_usage"][0]["cuts"] == [600]


def test_json_keeps_code_without_japanese_reason_label() -> None:
    result = calculate(_candidate_selection_input())
    dumped = json.dumps(result.model_dump(), ensure_ascii=False)

    assert NEW_REASON_CODE in dumped
    assert NEW_REASON_LABEL not in dumped
    assert set(result.unused_inventory[0]) == {
        "source_type",
        "length_mm",
        "quantity",
        "reason_code",
    }


def test_web_and_html_show_new_reason_label() -> None:
    client = TestClient(main_module.app)
    response = client.post(
        "/",
        data={
            "mode": "inventory",
            "title": "",
            "material_type": "",
            "author": "",
            "notes": "",
            "new_stock_length_mm": "1000",
            "kerf_mm": "0",
            "left_trim_mm": "0",
            "new_stock_quantity": "1",
            "part_length": ["600", "400"],
            "part_quantity": ["1", "1"],
            "remnant_length": "600",
            "remnant_quantity": "1",
        },
    )
    data = {
        "mode": "inventory",
        "metadata": {"title": "", "material_type": "", "author": "", "notes": ""},
        "cutting_conditions": {
            "new_stock_length_mm": 1000,
            "kerf_mm": 0,
            "left_trim_mm": 0,
        },
        "required_parts": [
            {"length_mm": 600, "quantity": 1},
            {"length_mm": 400, "quantity": 1},
        ],
        "inventory": {
            "new_stock_quantity": 1,
            "remnants": [{"length_mm": 600, "quantity": 1}],
        },
    }
    calculation_input, result, view = main_module._saved_input(data)
    record = make_record(
        "NEST-20260801-001",
        datetime(2026, 8, 1, tzinfo=ZoneInfo("Asia/Tokyo")),
        data,
        result.model_dump(),
    )
    html = render_report(main_module.templates, record, view)
    saved_json = json.dumps(record, ensure_ascii=False)

    assert calculation_input == _candidate_selection_input()
    assert NEW_REASON_CODE in saved_json
    assert NEW_REASON_LABEL not in saved_json
    assert NEW_REASON_LABEL in response.text
    assert NEW_REASON_LABEL in html


def test_unknown_reason_code_keeps_existing_fallback() -> None:
    result = calculate(_candidate_selection_input())
    result.unused_inventory[0]["reason_code"] = "UNKNOWN_REASON"

    view = main_module._display_result(
        result, {"left_trim_mm": 0, "kerf_mm": 0}
    )

    assert view["unused_inventory"][0]["reason"] == "使用条件に合わないため未使用です"
