import pytest
from pydantic import ValidationError
from app.calculation import CalculationInput, calculate
from app.calculation.rules import remainder_class, used_length

def request(**overrides):
    data={"mode":"required_stock","cutting_conditions":{"new_stock_length_mm":1030,"kerf_mm":5,"left_trim_mm":10},"required_parts":[{"length_mm":500,"quantity":2}]}; data.update(overrides); return CalculationInput.model_validate(data)

def test_basic_cut_and_kerf():
    result=calculate(request())
    assert result.required_stock_quantity == 1
    assert result.stock_usage[0]["used_length_mm"] == 1025
    assert result.stock_usage[0]["remaining_length_mm"] == 5
    assert result.stock_usage[0]["remainder_class"] == "scrap"

def test_exact_fit_and_too_short():
    exact=request(cutting_conditions={"new_stock_length_mm":120,"kerf_mm":5,"left_trim_mm":10},required_parts=[{"length_mm":100,"quantity":1}])
    assert calculate(exact).stock_usage[0]["remaining_length_mm"] == 0
    short=request(cutting_conditions={"new_stock_length_mm":119,"kerf_mm":5,"left_trim_mm":10},required_parts=[{"length_mm":100,"quantity":1}])
    with pytest.raises(ValueError): calculate(short)

@pytest.mark.parametrize(
    ("remaining", "expected"),
    [(0, "used_up"), (1, "scrap"), (50, "scrap"), (51, "remnant")],
)
def test_remainder_boundary(remaining, expected):
    assert remainder_class(remaining) == expected


@pytest.mark.parametrize("kerf", [0, 3, 5])
@pytest.mark.parametrize(
    ("remaining", "expected"), [(50, "scrap"), (51, "remnant")]
)
def test_calculation_result_remainder_boundary_does_not_depend_on_kerf(
    kerf, remaining, expected
):
    used = kerf + 100 + kerf
    data = request(
        cutting_conditions={
            "new_stock_length_mm": used + remaining,
            "kerf_mm": kerf,
            "left_trim_mm": 0,
        },
        required_parts=[{"length_mm": 100, "quantity": 1}],
    )
    usage = calculate(data).stock_usage[0]

    assert usage["remaining_length_mm"] == remaining
    assert usage["remainder_class"] == expected
    assert used_length([400,400],20,3) == 829

@pytest.mark.parametrize("value", [0,-1,1.5,"10",1_000_001])
def test_invalid_lengths(value):
    with pytest.raises(ValidationError):
        request(cutting_conditions={"new_stock_length_mm":value,"kerf_mm":0,"left_trim_mm":0})

def test_duplicate_dimensions_are_aggregated():
    data=request(cutting_conditions={"new_stock_length_mm":1000,"kerf_mm":0,"left_trim_mm":0},required_parts=[{"length_mm":400,"quantity":1},{"length_mm":300,"quantity":2},{"length_mm":400,"quantity":1}])
    result=calculate(data)
    assert result.required_stock_quantity == 2
    assert len(result.patterns) == 1
    assert result.patterns[0]["usage_count"] == 2
