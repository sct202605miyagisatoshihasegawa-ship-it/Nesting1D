from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def normal(**updates):
    data={"mode":"required_stock","title":"案件<script>","material_type":"角材","author":"担当者","notes":"備考","new_stock_length_mm":"1030","kerf_mm":"5","left_trim_mm":"10","new_stock_quantity":"0","part_length":"500","part_quantity":"2","remnant_length":"","remnant_quantity":""}
    data.update(updates); return data

def test_get_form_and_existing_status():
    response=client.get("/")
    assert response.status_code==200
    assert "正常に稼働しています" in response.text
    assert "必要母材算出" in response.text
    assert "在庫母材・残材活用" in response.text

def test_required_stock_calculation_and_escape():
    response=client.post("/",data=normal())
    assert response.status_code==200
    assert "計算結果" in response.text
    assert "使用母材数" in response.text and ">1<" in response.text
    assert "案件&lt;script&gt;" in response.text
    assert "案件<script>" not in response.text

def test_inventory_calculation():
    response=client.post("/",data=normal(mode="inventory",new_stock_length_mm="1000",kerf_mm="0",left_trim_mm="0",new_stock_quantity="1",part_length=["600","400"],part_quantity=["1","1"],remnant_length="600",remnant_quantity="1"))
    assert response.status_code==200
    assert "追加購入新品母材" in response.text
    assert "600mm" in response.text and "400mm" in response.text

def test_hidden_inventory_values_are_ignored_in_required_mode():
    response=client.post("/",data=normal(new_stock_quantity="bad",remnant_length="bad",remnant_quantity="bad"))
    assert "計算結果" in response.text
    assert "保有新品母材本数は" not in response.text

def test_partial_part_row_is_error_and_value_is_kept():
    response=client.post("/",data=normal(part_length="777",part_quantity=""))
    assert "必要部材1行目は寸法と本数の両方" in response.text
    assert 'value="777"' in response.text

def test_no_part_row_is_error():
    response=client.post("/",data=normal(part_length="",part_quantity=""))
    assert "必要部材を最低1行" in response.text

def test_invalid_integer_and_range_errors():
    for value in ("0","-1","1.5","abc","1000001"):
        response=client.post("/",data=normal(new_stock_length_mm=value))
        assert "新品母材長は" in response.text
        assert "計算結果" not in response.text

def test_impossible_part_is_user_error():
    response=client.post("/",data=normal(new_stock_length_mm="100",part_length="100",part_quantity="1"))
    assert "新品母材から切り出せない部材" in response.text
    assert "Traceback" not in response.text

def test_inventory_partial_remnant_is_error():
    response=client.post("/",data=normal(mode="inventory",remnant_length="500",remnant_quantity=""))
    assert "既存残材1行目は寸法と本数の両方" in response.text
