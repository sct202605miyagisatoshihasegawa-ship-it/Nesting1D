# Nesting1D - 計算再現性テスト
# 役割: 同一入力と入力順差に対する計算結果およびパターン順の決定性を検証する。
# 更新日: 2026-08-10

from app.calculation import CalculationInput, calculate
from app.calculation.patterns import changes, key, order

def test_same_input_same_result():
    data=CalculationInput.model_validate({"mode":"required_stock","cutting_conditions":{"new_stock_length_mm":1000,"kerf_mm":0,"left_trim_mm":0},"required_parts":[{"length_mm":400,"quantity":2},{"length_mm":300,"quantity":2}]})
    assert calculate(data).model_dump() == calculate(data).model_dump()

def test_input_row_order_is_normalized():
    base={"mode":"required_stock","cutting_conditions":{"new_stock_length_mm":1000,"kerf_mm":0,"left_trim_mm":0}}
    a=CalculationInput.model_validate(base|{"required_parts":[{"length_mm":400,"quantity":2},{"length_mm":300,"quantity":2}]})
    b=CalculationInput.model_validate(base|{"required_parts":[{"length_mm":300,"quantity":2},{"length_mm":400,"quantity":2}]})
    assert calculate(a).model_dump() == calculate(b).model_dump()

def test_dimension_changes_ignore_usage_count_and_include_transition():
    p1=key([2300,2300,950]); p2=key([950,500])
    planned=order([p1,p2])
    assert changes(planned) == 2
