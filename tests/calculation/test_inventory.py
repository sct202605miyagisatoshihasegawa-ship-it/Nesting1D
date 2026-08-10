# Nesting1D - 在庫活用計算テスト
# 役割: 在庫残材・在庫新品材・追加購入新品材を使う計算結果を検証する。
# 更新日: 2026-08-10

from app.calculation import CalculationInput, calculate

def inventory(remnants, held, parts):
    return CalculationInput.model_validate({"mode":"inventory","cutting_conditions":{"new_stock_length_mm":1000,"kerf_mm":0,"left_trim_mm":0},"required_parts":parts,"inventory":{"new_stock_quantity":held,"remnants":remnants}})

def test_held_stock_is_selected_when_it_has_less_total_remnant():
    result=calculate(inventory([{"length_mm":600,"quantity":1}],1,[{"length_mm":600,"quantity":1},{"length_mm":400,"quantity":1}]))
    assert result.existing_remnant_used == 0
    assert result.inventory_new_stock_used == 1
    assert result.additional_new_stock_required == 0
    assert result.stock_usage[0]["cuts"] == [600,400]
    assert result.stock_usage[0]["remaining_length_mm"] == 0
    assert result.stock_usage[0]["remainder_class"] == "used_up"
    assert result.unused_inventory[0]["reason_code"] == "NOT_SELECTED_BY_CANDIDATE_SELECTION"

def test_same_purchase_count_prefers_less_total_remnant():
    result=calculate(inventory([{"length_mm":600,"quantity":1}],0,[{"length_mm":600,"quantity":1},{"length_mm":400,"quantity":1}]))
    assert result.existing_remnant_used == 0
    assert result.additional_new_stock_required == 1
    assert result.stock_usage[0]["cuts"] == [600,400]
    assert result.stock_usage[0]["remainder_class"] == "used_up"
    assert result.stock_usage[0]["remaining_length_mm"] == 0
    assert result.unused_inventory[0]["reason_code"] == "NOT_SELECTED_BY_CANDIDATE_SELECTION"

def test_unusable_remnant_is_not_error():
    data=CalculationInput.model_validate({"mode":"inventory","cutting_conditions":{"new_stock_length_mm":1000,"kerf_mm":5,"left_trim_mm":10},"required_parts":[{"length_mm":100,"quantity":1}],"inventory":{"new_stock_quantity":0,"remnants":[{"length_mm":100,"quantity":1}]}})
    result=calculate(data)
    assert result.existing_remnant_used == 0
    assert result.unused_inventory[0]["reason_code"] == "NO_REQUIRED_PART_FITS_AFTER_TRIM"
    assert result.additional_new_stock_required == 1
    assert result.unused_inventory[0]["source_type"] == "existing_remnant"


def test_zero_remainder_is_used_up():
    result=calculate(inventory([{"length_mm":600,"quantity":1}],0,[{"length_mm":600,"quantity":1}]))
    assert result.stock_usage[0]["remainder_class"] == "used_up"

def test_remaining_remnant_after_fulfillment_is_not_needed():
    result=calculate(inventory([{"length_mm":600,"quantity":2}],0,[{"length_mm":600,"quantity":1}]))
    assert result.existing_remnant_used == 1
    assert result.additional_new_stock_required == 0
    assert result.fulfillment[0]["completed_total_quantity"] == 1
    assert result.unused_inventory == [{
        "source_type":"existing_remnant",
        "length_mm":600,
        "quantity":1,
        "reason_code":"NOT_NEEDED",
    }]

def test_remaining_held_new_stock_after_fulfillment_is_not_needed():
    result=calculate(inventory([],2,[{"length_mm":600,"quantity":1}]))
    assert result.inventory_new_stock_used == 1
    assert result.additional_new_stock_required == 0
    assert result.fulfillment[0]["completed_total_quantity"] == 1
    assert result.unused_inventory == [{
        "source_type":"held_new_stock",
        "length_mm":1000,
        "quantity":1,
        "reason_code":"NOT_NEEDED",
    }]

def test_example_6_7_counts_follow_candidate_selection():
    result=calculate(inventory([{"length_mm":600,"quantity":1}],1,[{"length_mm":600,"quantity":1},{"length_mm":400,"quantity":1}]))
    assert (result.existing_remnant_used,result.inventory_new_stock_used,result.additional_new_stock_required)==(0,1,0)
    assert [(x["length_mm"],x["completed_total_quantity"],x["shortage_after_purchase_quantity"]) for x in result.fulfillment]==[(600,1,0),(400,1,0)]
