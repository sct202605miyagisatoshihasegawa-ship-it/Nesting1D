from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def normal(**updates):
    data={"mode":"required_stock","title":"案件<script>","material_type":"角材","author":"担当者","notes":"備考","new_stock_length_mm":"1030","kerf_mm":"5","left_trim_mm":"10","new_stock_quantity":"0","part_length":"500","part_quantity":"2","remnant_length":"","remnant_quantity":""}
    data.update(updates); return data

def test_get_form_and_calculation_identity():
    response=client.get("/")
    assert response.status_code==200
    assert "開発環境" not in response.text
    assert "計算結果識別情報" in response.text
    assert "未発行" in response.text and "未計算" in response.text
    assert "必要母材算出" in response.text
    assert "在庫母材・残材活用" in response.text


def test_calculation_identity_and_fixed_rules():
    response=client.post("/",data=normal(mode="inventory"))
    assert response.status_code==200
    assert "未計算" not in response.text
    assert "計算日時" in response.text and "在庫母材・残材活用" in response.text
    for text in ("固定ルール（編集不可）", "右端捨て切り", "なし", "残材50mm以下", "廃棄", "左から順に切断"):
        assert text in response.text
    assert response.text.count('name="new_stock_length_mm"') == 1
    assert response.text.count('name="kerf_mm"') == 1
    assert response.text.count('name="left_trim_mm"') == 1

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
        assert "計算結果ダッシュボード" not in response.text

def test_impossible_part_is_user_error():
    response=client.post("/",data=normal(new_stock_length_mm="100",part_length="100",part_quantity="1"))
    assert "新品母材から切り出せない部材" in response.text
    assert "Traceback" not in response.text

def test_inventory_partial_remnant_is_error():
    response=client.post("/",data=normal(mode="inventory",remnant_length="500",remnant_quantity=""))
    assert "既存残材1行目は寸法と本数の両方" in response.text

def test_dashboard_and_normal_mode_details():
    response=client.post("/",data=normal())
    assert "計算結果ダッシュボード" in response.text
    assert "合計廃棄材" in response.text
    assert "寸法変更回数" in response.text
    assert "機械設定回数" in response.text
    assert "P01" in response.text and "500mm × 2本" in response.text

def test_pattern_aggregation_and_stock_list():
    response=client.post("/",data=normal(part_quantity="4"))
    assert "P01" in response.text
    assert "2回使用" in response.text
    assert "No.1" in response.text and "No.2" in response.text
    assert "追加購入新品母材" in response.text

def test_field_mode_cutting_instructions():
    response=client.post("/",data=normal(part_quantity="4"))
    assert "切断手順（現場モード）" in response.text
    assert "P01を2回加工" in response.text
    assert "左端を10mm捨て切り" in response.text
    assert "ストッパーを500mmに設定" in response.text
    assert "合計4本切断" in response.text

def test_inventory_used_up_remnant_and_unused_reason():
    response=client.post("/",data=normal(mode="inventory",new_stock_length_mm="1000",kerf_mm="0",left_trim_mm="0",new_stock_quantity="0",part_length="600",part_quantity="1",remnant_length=["100","600"],remnant_quantity=["1","1"]))
    assert "使用した既存残材" in response.text
    assert "使い切り" in response.text
    assert "既存残材：100mm × 1本" in response.text
    assert "未使用在庫" in response.text
    assert "左端を捨て切りした後の長さでは、必要な部材を1本も切り出せないため未使用" in response.text


def test_unused_inventory_after_fulfillment_has_source_and_reason():
    response=client.post("/",data=normal(mode="inventory",new_stock_length_mm="1000",kerf_mm="0",left_trim_mm="0",new_stock_quantity="2",part_length="600",part_quantity="1",remnant_length=["600","600"],remnant_quantity=["1","1"]))
    assert response.status_code==200
    assert "既存残材：600mm × 1本" in response.text
    assert "保有新品母材：1000mm × 2本" in response.text
    assert response.text.count("必要部材をすべて確保できたため未使用") == 2
    assert "左端を捨て切りした後の長さでは" not in response.text

def test_result_navigation_and_html_escape():
    response=client.post("/",data=normal(title='<img src=x onerror="alert(1)">',notes="<script>alert(1)</script>"))
    assert 'data-result-view="dashboard-view"' in response.text
    assert 'data-result-view="instructions-view"' in response.text
    assert "&lt;img src=x onerror=&#34;alert(1)&#34;&gt;" in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert '<script>alert(1)</script>' not in response.text
