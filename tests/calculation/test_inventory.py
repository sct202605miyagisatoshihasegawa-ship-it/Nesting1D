from app.calculation import CalculationInput, calculate

def inventory(remnants, held, parts):
    return CalculationInput.model_validate({"mode":"inventory","cutting_conditions":{"new_stock_length_mm":1000,"kerf_mm":0,"left_trim_mm":0},"required_parts":parts,"inventory":{"new_stock_quantity":held,"remnants":remnants}})

def test_remnant_then_held_stock():
    result=calculate(inventory([{"length_mm":600,"quantity":1}],1,[{"length_mm":600,"quantity":1},{"length_mm":400,"quantity":1}]))
    assert result.existing_remnant_used == 1
    assert result.inventory_new_stock_used == 1
    assert result.additional_new_stock_required == 0
    assert result.stock_usage[0]["cuts"] == [600]
    assert result.stock_usage[0]["remaining_length_mm"] == 0
    assert result.stock_usage[0]["remainder_class"] == "used_up"
    assert result.stock_usage[1]["remaining_length_mm"] == 600

def test_same_purchase_count_prefers_remnant():
    result=calculate(inventory([{"length_mm":600,"quantity":1}],0,[{"length_mm":600,"quantity":1},{"length_mm":400,"quantity":1}]))
    assert result.existing_remnant_used == 1
    assert result.additional_new_stock_required == 1
    assert result.stock_usage[0]["cuts"] == [600]
    assert result.stock_usage[0]["remainder_class"] == "used_up"
    assert result.stock_usage[1]["remaining_length_mm"] == 600

def test_unusable_remnant_is_not_error():
    data=CalculationInput.model_validate({"mode":"inventory","cutting_conditions":{"new_stock_length_mm":1000,"kerf_mm":5,"left_trim_mm":10},"required_parts":[{"length_mm":100,"quantity":1}],"inventory":{"new_stock_quantity":0,"remnants":[{"length_mm":100,"quantity":1}]}})
    result=calculate(data)
    assert result.existing_remnant_used == 0
    assert result.unused_inventory[0]["reason_code"] == "NO_REQUIRED_PART_FITS_AFTER_TRIM"
    assert result.additional_new_stock_required == 1


def test_zero_remainder_is_used_up():
    result=calculate(inventory([{"length_mm":600,"quantity":1}],0,[{"length_mm":600,"quantity":1}]))
    assert result.stock_usage[0]["remainder_class"] == "used_up"
