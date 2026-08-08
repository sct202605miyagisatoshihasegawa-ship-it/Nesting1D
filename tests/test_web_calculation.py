import re
import pytest

from fastapi.testclient import TestClient
import app.main as main_module
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

def test_tabs_before_calculation_and_on_input_error():
    initial=client.get("/")
    assert initial.text.count('data-result-view=') == 5
    assert 'data-has-result="false"' in initial.text
    input_button=re.search(r'<button[^>]*data-result-view="conditions-view"[^>]*>',initial.text).group()
    assert 'class="active"' in input_button
    assert initial.text.count("計算後に") == 5
    error=client.post("/",data=normal(part_length="",part_quantity=""))
    assert 'data-has-result="false"' in error.text
    error_input_button=re.search(r'<button[^>]*data-result-view="conditions-view"[^>]*>',error.text).group()
    assert 'class="active"' in error_input_button
    assert "計算結果ダッシュボード" not in error.text


def test_corrected_tab_window_and_following_section_order():
    response=client.get("/")
    html=response.text
    calculate_position=html.index('class="calculate-button"')
    tabs_position=html.index('class="result-tabs"')
    window_position=html.index('class="tab-content"')
    management_position=html.index('id="management-actions-heading"')
    common_position=html.index('class="card common-information"')
    assert calculate_position < tabs_position < window_position < management_position < common_position
    shared_window=html[window_position:management_position]
    assert shared_window.count('class="card result-panel') == 5
    for panel_id in ("conditions-view", "dashboard-view", "patterns-view", "stocks-view", "instructions-view"):
        assert f'id="{panel_id}"' in shared_window
    assert 'form="calculation-form" name="title"' in html
    assert 'form="calculation-form" name="notes"' in html


def test_stage5_management_actions_and_auxiliary_placement():
    html = client.get("/").text
    conditions_start = html.index('id="conditions-view"')
    dashboard_start = html.index('id="dashboard-view"')
    management_start = html.index('id="management-actions-heading"')
    common_start = html.index('class="card common-information"')
    conditions_panel = html[conditions_start:dashboard_start]
    management_panel = html[management_start:common_start]
    assert conditions_start < dashboard_start < management_start < common_start
    assert '<summary>その他の操作</summary>' in conditions_panel
    for control_id in ("local-json-file", "load-local-json"):
        assert f'id="{control_id}"' in conditions_panel
        assert f'id="{control_id}"' not in management_panel
    for removed_id in ("record-select", "load-record", "save-record"):
        assert f'id="{removed_id}"' not in html
    for control_id in ("download-json", "download-html"):
        assert f'id="{control_id}"' not in conditions_panel
        assert f'id="{control_id}"' in management_panel
    assert management_panel.count("<button") == 3
    expected_actions = (
        'id="download-json" disabled>JSONを端末へ出力</button>',
        'id="download-html" disabled>HTMLを端末へ出力</button>',
        'id="reset-input">リセット</button>',
    )
    assert all(action in management_panel for action in expected_actions)
    positions = [management_panel.index(action) for action in expected_actions]
    assert positions == sorted(positions)
    assert "新規作成" not in management_panel
    assert 'id="save-status" class="saved">未計算</span>' in management_panel


def test_calculation_issues_maintains_and_reissues_explicit_result_id(monkeypatch):
    numbers = iter(("NEST-20260805-103645-A7K2", "NEST-20260805-103646-B8L3"))
    monkeypatch.setattr(main_module, "generate_management_number", lambda now: next(numbers))

    first = client.post("/", data=normal())
    assert 'name="result_management_number" value="NEST-20260805-103645-A7K2"' in first.text
    assert 'name="management_number_state" value="maintain"' in first.text
    assert "計算済み・未出力" in first.text
    created_at = re.search(r'name="result_created_at" value="([^"]+)"', first.text).group(1)
    updated_at = re.search(r'name="result_updated_at" value="([^"]+)"', first.text).group(1)
    assert created_at == updated_at and created_at.endswith("+09:00")

    maintained = client.post("/", data=normal(
        result_management_number="NEST-20260805-103645-A7K2",
        management_number_state="maintain",
        result_created_at=created_at,
        result_updated_at=updated_at,
    ))
    assert 'name="result_management_number" value="NEST-20260805-103645-A7K2"' in maintained.text
    assert f'name="result_created_at" value="{created_at}"' in maintained.text
    assert f'name="result_updated_at" value="{updated_at}"' in maintained.text

    reissued = client.post("/", data=normal(
        result_management_number="NEST-20260805-103645-A7K2",
        management_number_state="reissue",
    ))
    assert 'name="result_management_number" value="NEST-20260805-103646-B8L3"' in reissued.text


def test_success_selects_dashboard_and_snapshot_totals_are_stable():
    response=client.post("/",data=normal(new_stock_length_mm="2000",part_length=["500","200","500"],part_quantity=["2","3","1"]))
    assert response.status_code==200
    assert 'data-has-result="true"' in response.text
    dashboard_button=re.search(r'<button[^>]*data-result-view="dashboard-view"[^>]*>',response.text).group()
    assert 'class="active"' in dashboard_button
    for text in ("計算時の入力条件", "必要部材の種類数", "3種類", "必要部材の合計本数", "6本", "必要部材の合計長さ", "2100mm"):
        assert text in response.text
    assert "500mm × 3本" in response.text
    assert "200mm × 3本" in response.text
    assert "前回計算時点" in response.text
    assert "右端捨て切り：なし" in response.text
    assert "残材50mm以下：廃棄" in response.text
    assert "左から順に切断" in response.text


def test_required_stock_calculation_and_escape():
    response=client.post("/",data=normal())
    assert response.status_code==200
    assert "計算結果" in response.text
    assert "使用材料数" in response.text and ">1<" in response.text
    assert "案件&lt;script&gt;" in response.text
    assert "案件<script>" not in response.text

def test_inventory_calculation():
    response=client.post("/",data=normal(mode="inventory",new_stock_length_mm="1000",kerf_mm="0",left_trim_mm="0",new_stock_quantity="1",part_length=["600","400"],part_quantity=["1","1"],remnant_length="600",remnant_quantity="1"))
    assert response.status_code==200
    assert "購入新品材" in response.text
    assert "600mm" in response.text and "400mm" in response.text

def test_hidden_inventory_values_are_ignored_in_required_mode():
    response=client.post("/",data=normal(new_stock_quantity="bad",remnant_length="bad",remnant_quantity="bad"))
    assert "計算結果" in response.text
    assert "在庫新品材本数は" not in response.text

def test_partial_part_row_is_error_and_value_is_kept():
    response=client.post("/",data=normal(part_length="777",part_quantity=""))
    assert "必要部材1行目は寸法と本数の両方" in response.text
    assert 'value="777"' in response.text

def test_no_part_row_is_error():
    response=client.post("/",data=normal(part_length="",part_quantity=""))
    assert "必要部材を最低1行" in response.text
    assert "寸法を入力してください。" in response.text
    assert "必要本数を入力してください。" in response.text
    assert 'id="error-part-length-0"' in response.text
    assert 'id="error-part-quantity-0"' in response.text


def test_inline_errors_mark_only_invalid_fields_and_keep_row_indexes():
    response=client.post("/",data=normal(part_length=["500","abc"],part_quantity=["2","0"]))
    assert response.status_code==200
    valid_input=re.search(r'<input name="part_length"[^>]*value="500"[^>]*>',response.text).group()
    invalid_length=re.search(r'<input name="part_length"[^>]*value="abc"[^>]*>',response.text).group()
    invalid_quantity=re.search(r'<input name="part_quantity"[^>]*value="0"[^>]*>',response.text).group()
    assert "field-error-input" not in valid_input
    assert 'class="field-error-input"' in invalid_length and 'aria-invalid="true"' in invalid_length
    assert 'class="field-error-input"' in invalid_quantity
    assert 'id="error-part-length-1"' in response.text
    assert 'id="error-part-quantity-1"' in response.text
    assert "1以上1000000以下の整数を入力してください。" in response.text
    assert "1以上500以下の整数を入力してください。" in response.text
    assert "計算結果ダッシュボード" not in response.text


def test_impossible_part_has_inline_error_using_engine_length_rule():
    response=client.post("/",data=normal(new_stock_length_mm="119",kerf_mm="5",left_trim_mm="10",part_length="100",part_quantity="1"))
    part_input=re.search(r'<input name="part_length"[^>]*value="100"[^>]*>',response.text).group()
    assert "field-error-input" in part_input
    assert "捨て切りと鋸刃厚を含めて新品母材から切り出せる寸法を入力してください。" in response.text
    assert "新品母材から切り出せない部材があります。" in response.text
    assert "計算結果ダッシュボード" not in response.text


def test_inventory_inline_errors_stay_with_their_fields():
    response=client.post("/",data=normal(mode="inventory",new_stock_quantity="bad",remnant_length=["600","700"],remnant_quantity=["1",""]))
    assert 'id="error-new-stock-quantity"' in response.text
    assert "0以上100000以下の整数を入力してください。" in response.text
    assert 'id="error-remnant-quantity-1"' in response.text
    assert "保有本数を入力してください。" in response.text
    assert 'id="error-remnant-quantity-0"' not in response.text

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
    assert "在庫残材1行目は寸法と本数の両方" in response.text

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
    assert "購入新品材" in response.text


def test_stock_cards_keep_source_header_and_omit_duplicate_source_row():
    responses = (
        (client.post("/", data=normal(mode="inventory", new_stock_length_mm="1000", kerf_mm="3", left_trim_mm="10", new_stock_quantity="0", part_length="590", part_quantity="1", remnant_length="606", remnant_quantity="1")), "在庫残材"),
        (client.post("/", data=normal(mode="inventory", new_stock_length_mm="1000", kerf_mm="3", left_trim_mm="10", new_stock_quantity="1", part_length="590", part_quantity="1", remnant_length="", remnant_quantity="")), "在庫新品材"),
        (client.post("/", data=normal(new_stock_length_mm="1000", kerf_mm="3", left_trim_mm="10", part_length="590", part_quantity="1")), "購入新品材"),
    )
    for response, source_label in responses:
        card = re.search(r'<article class="stock-card">.*?</article>', response.text, re.S).group()
        assert f"<strong>{source_label}</strong>" in card
        assert re.findall(r"<dt>(.*?)</dt>", card) == ["元の長さ", "パターン", "切出し部材", "使用後"]
        assert "在庫区分" not in card

def test_field_mode_cutting_instructions():
    response=client.post("/",data=normal(part_quantity="4"))
    assert "切断手順（現場モード）" in response.text
    assert "P01を2回加工" in response.text
    assert '購入新品材<span class="measurement">1030mm</span>' in response.text
    assert '左端を<span class="measurement">10mm</span>捨て切り' in response.text
    assert 'ストッパーを<span class="measurement">500mm</span>に設定' in response.text
    assert "合計4本切断" in response.text
    assert '鋸刃厚<span class="measurement">5mm</span>を4回消費' in response.text
    assert "母材を" not in response.text


def test_field_mode_names_each_actual_material_type():
    existing=client.post("/",data=normal(mode="inventory",new_stock_length_mm="1000",kerf_mm="3",left_trim_mm="10",new_stock_quantity="0",part_length="590",part_quantity="1",remnant_length="606",remnant_quantity="1"))
    held=client.post("/",data=normal(mode="inventory",new_stock_length_mm="1000",kerf_mm="3",left_trim_mm="10",new_stock_quantity="1",part_length="590",part_quantity="1",remnant_length="",remnant_quantity=""))
    purchased=client.post("/",data=normal(new_stock_length_mm="1000",kerf_mm="3",left_trim_mm="10",part_length="590",part_quantity="1"))
    assert '在庫残材<span class="measurement">606mm</span>' in existing.text
    assert '在庫新品材<span class="measurement">1000mm</span>' in held.text
    assert '購入新品材<span class="measurement">1000mm</span>' in purchased.text
    for response in (existing,held,purchased):
        assert '切断時に鋸刃厚<span class="measurement">3mm</span>を1回消費' in response.text

def test_inventory_used_up_remnant_and_unused_reason():
    response=client.post("/",data=normal(mode="inventory",new_stock_length_mm="1000",kerf_mm="0",left_trim_mm="0",new_stock_quantity="0",part_length="600",part_quantity="1",remnant_length=["100","600"],remnant_quantity=["1","1"]))
    assert "使用した在庫残材" in response.text
    assert "使い切り" in response.text
    assert "在庫残材：100mm × 1本" in response.text
    assert "未使用在庫" in response.text
    assert "左端を捨て切りした後の長さでは、必要な部材を1本も切り出せないため未使用" in response.text


def test_unused_inventory_after_fulfillment_has_source_and_reason():
    response=client.post("/",data=normal(mode="inventory",new_stock_length_mm="1000",kerf_mm="0",left_trim_mm="0",new_stock_quantity="2",part_length="600",part_quantity="1",remnant_length=["600","600"],remnant_quantity=["1","1"]))
    assert response.status_code==200
    assert "在庫残材：600mm × 1本" in response.text
    assert "在庫新品材：1000mm × 2本" in response.text
    assert response.text.count("必要部材がすべて確保され、この在庫材料を使用する必要がないため") == 2
    assert "左端を捨て切りした後の長さでは" not in response.text

def test_result_navigation_and_html_escape():
    response=client.post("/",data=normal(title='<img src=x onerror="alert(1)">',notes="<script>alert(1)</script>"))
    assert 'data-result-view="dashboard-view"' in response.text
    assert 'data-result-view="instructions-view"' in response.text
    assert "&lt;img src=x onerror=&#34;alert(1)&#34;&gt;" in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert '<script>alert(1)</script>' not in response.text


@pytest.mark.parametrize("quantity", ["1", "500"])
def test_part_quantity_boundaries_are_calculated(quantity):
    response = client.post("/", data=normal(part_quantity=quantity))
    assert response.status_code == 200
    assert "計算結果ダッシュボード" in response.text
    assert f"<dd>{quantity}本</dd>" in response.text


def test_part_quantity_501_is_rejected_without_calculation(monkeypatch):
    called = False

    def unexpected_calculate(_data):
        nonlocal called
        called = True
        raise AssertionError("calculate must not be called")

    monkeypatch.setattr(main_module, "calculate", unexpected_calculate)
    response = client.post("/", data=normal(part_quantity="501"))

    assert response.status_code == 200
    assert not called
    assert "必要部材1行目の本数は1以上500以下" in response.text
    assert "1以上500以下の整数を入力してください。" in response.text
    assert "計算結果ダッシュボード" not in response.text


def test_required_part_row_limit_accepts_20_and_rejects_21():
    accepted = client.post("/", data=normal(part_length=["500"] * 20, part_quantity=["1"] * 20))
    rejected = client.post("/", data=normal(part_length=["500"] * 21, part_quantity=["1"] * 21))

    assert "計算結果ダッシュボード" in accepted.text
    assert "入力件数または合計本数が上限を超えています。" in rejected.text
    assert "計算結果ダッシュボード" not in rejected.text


def test_inventory_remnant_row_and_quantity_limits():
    accepted = client.post("/", data=normal(
        mode="inventory", remnant_length=["1"] * 10, remnant_quantity=["100000"] * 10,
    ))
    too_many_rows = client.post("/", data=normal(
        mode="inventory", remnant_length=["1"] * 11, remnant_quantity=["1"] * 11,
    ))
    too_many_items = client.post("/", data=normal(
        mode="inventory", remnant_length="1", remnant_quantity="100001",
    ))

    assert "計算結果ダッシュボード" in accepted.text
    assert "入力件数または合計本数が上限を超えています。" in too_many_rows.text
    assert "計算結果ダッシュボード" not in too_many_rows.text
    assert "在庫残材1行目の本数は1以上100000以下" in too_many_items.text
    assert "計算結果ダッシュボード" not in too_many_items.text


def test_form_declares_part_quantity_and_text_limits():
    html = client.get("/").text
    assert html.count('name="part_quantity" type="number" inputmode="numeric" min="1" max="500" step="1"') == 2
    for name, maximum in (("title", 20), ("material_type", 30), ("author", 30), ("notes", 400)):
        assert f'name="{name}" maxlength="{maximum}"' in html


@pytest.mark.parametrize(
    ("field", "maximum", "label"),
    (("title", 20, "件名"), ("material_type", 30, "材料種類"), ("author", 30, "データ製作者"), ("notes", 400, "備考")),
)
def test_text_fields_accept_exact_limit_and_reject_one_over(field, maximum, label):
    accepted = client.post("/", data=normal(**{field: "日" * maximum}))
    rejected = client.post("/", data=normal(**{field: "日" * (maximum + 1)}))

    assert "計算結果ダッシュボード" in accepted.text
    assert f"{label}は{maximum}文字以下で入力してください。" in rejected.text
    assert "計算結果ダッシュボード" not in rejected.text


def test_text_length_counts_python_characters_and_keeps_html_escaping():
    value = "<>&\"'" + "日" * 15
    response = client.post("/", data=normal(title=value))

    assert len(value) == 20
    assert "計算結果ダッシュボード" in response.text
    assert "&lt;&gt;&amp;&#34;&#39;" in response.text or "&lt;&gt;&amp;&#34;'" in response.text
    assert value not in response.text
