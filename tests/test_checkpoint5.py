import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.calculation import CalculationInput, calculate
from app.exporting import make_record, render_report
from app.storage import APP_VERSION, FORMAT_VERSION, RecordStorage, StorageError, UnsupportedFormatError

TOKYO = ZoneInfo("Asia/Tokyo")
FIXED_TIME = datetime(2026, 7, 26, 10, 20, 30, tzinfo=TOKYO)


def saved_input(**metadata):
    return {
        "mode": "required_stock",
        "metadata": {"title": "日本語案件", "material_type": "角材", "author": "担当者", "notes": "備考"} | metadata,
        "cutting_conditions": {"new_stock_length_mm": 1030, "kerf_mm": 5, "left_trim_mm": 10},
        "required_parts": [{"length_mm": 500, "quantity": 2}],
    }


def inventory_input(**metadata):
    data = saved_input(**metadata)
    data.update({
        "mode": "inventory",
        "cutting_conditions": {"new_stock_length_mm": 1000, "kerf_mm": 0, "left_trim_mm": 0},
        "required_parts": [{"length_mm": 600, "quantity": 1}],
        "inventory": {"new_stock_quantity": 1, "remnants": [{"length_mm": 100, "quantity": 1}, {"length_mm": 600, "quantity": 1}]},
    })
    return data


def bare_record(number="NEST-20260726-001", title="日本語案件"):
    return {
        "format_version": FORMAT_VERSION,
        "app_version": APP_VERSION,
        "management_number": number,
        "created_at": FIXED_TIME.isoformat(),
        "updated_at": FIXED_TIME.isoformat(),
        "input": saved_input(title=title),
        "calculation_result": {"status": "saved"},
    }


@pytest.fixture
def web_storage(tmp_path, monkeypatch):
    storage = RecordStorage(tmp_path / "data", clock=lambda: FIXED_TIME)
    monkeypatch.setattr(main_module, "storage", storage)
    return TestClient(main_module.app), storage


def test_management_number_tokyo_format_and_maximum_with_gap(tmp_path):
    storage = RecordStorage(tmp_path / "data", clock=lambda: FIXED_TIME)
    storage.data_dir.mkdir()
    (storage.data_dir / "NEST-20260726-001.json").write_text("{}", encoding="utf-8")
    (storage.data_dir / "NEST-20260726-004.json").write_text("{}", encoding="utf-8")
    assert storage.next_number() == "NEST-20260726-005"
    utc_time = datetime(2026, 7, 25, 15, 30, tzinfo=ZoneInfo("UTC"))
    assert storage.next_number(utc_time).startswith("NEST-20260726-")


def test_new_save_writes_utf8_json_and_html_only_under_data(tmp_path):
    storage = RecordStorage(tmp_path / "data", clock=lambda: FIXED_TIME)
    record = storage.save_new(lambda number, now: (bare_record(number), f"<html>{number} 日本語</html>"))
    number = record["management_number"]
    json_path = storage.data_dir / f"{number}.json"
    html_path = storage.data_dir / f"{number}.html"
    assert number == "NEST-20260726-001"
    assert json_path.exists() and html_path.exists()
    assert "日本語案件" in json_path.read_text(encoding="utf-8")
    assert number in html_path.read_text(encoding="utf-8")
    assert list(tmp_path.glob("NEST-*")) == []
    assert not list(storage.data_dir.glob("*.tmp"))


def test_path_traversal_and_invalid_number_are_rejected(tmp_path):
    storage = RecordStorage(tmp_path / "data")
    for value in ("../outside", "NEST-20260726-001/../../x", "NEST-20260726-0001"):
        with pytest.raises(StorageError):
            storage.load(value)


def test_existing_name_is_not_changed_without_overwrite(tmp_path):
    storage = RecordStorage(tmp_path / "data", clock=lambda: FIXED_TIME)
    storage.data_dir.mkdir()
    existing = storage.data_dir / "NEST-20260726-001.json"
    existing.write_text("original", encoding="utf-8")
    record = storage.save_new(lambda number, now: (bare_record(number), "html"))
    assert record["management_number"] == "NEST-20260726-002"
    assert existing.read_text(encoding="utf-8") == "original"


def test_overwrite_keeps_number_and_created_at(tmp_path):
    storage = RecordStorage(tmp_path / "data", clock=lambda: FIXED_TIME)
    original = storage.save_new(lambda number, now: (bare_record(number), "old html"))
    updated = deepcopy(original)
    updated["updated_at"] = "2026-07-26T11:00:00+09:00"
    updated["input"]["metadata"]["title"] = "更新後"
    storage.overwrite(updated, "new html")
    loaded = storage.load(original["management_number"])
    assert loaded["management_number"] == original["management_number"]
    assert loaded["created_at"] == original["created_at"]
    assert loaded["input"]["metadata"]["title"] == "更新後"


def test_save_failure_restores_existing_files_and_removes_temps(tmp_path, monkeypatch):
    storage = RecordStorage(tmp_path / "data", clock=lambda: FIXED_TIME)
    original = storage.save_new(lambda number, now: (bare_record(number), "old html"))
    number = original["management_number"]
    json_path = storage.data_dir / f"{number}.json"
    html_path = storage.data_dir / f"{number}.html"
    before = (json_path.read_bytes(), html_path.read_bytes())
    real_replace = __import__("os").replace
    calls = 0
    def fail_second(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated")
        return real_replace(source, destination)
    monkeypatch.setattr("app.storage.os.replace", fail_second)
    changed = deepcopy(original)
    changed["input"]["metadata"]["title"] = "壊してはいけない"
    with pytest.raises(StorageError):
        storage.overwrite(changed, "new html")
    assert (json_path.read_bytes(), html_path.read_bytes()) == before
    assert not list(storage.data_dir.glob("*.tmp"))


def test_json_validation_invalid_and_unsupported(tmp_path):
    storage = RecordStorage(tmp_path / "data")
    storage.data_dir.mkdir()
    invalid = storage.data_dir / "NEST-20260726-001.json"
    invalid.write_text("{broken", encoding="utf-8")
    with pytest.raises(StorageError):
        storage.load(invalid.stem)
    invalid.write_text(json.dumps(bare_record() | {"format_version": "9.9"}), encoding="utf-8")
    with pytest.raises(UnsupportedFormatError, match="対応していません"):
        storage.load(invalid.stem)


def test_record_fields_and_recalculation_are_stable():
    data = saved_input(notes='<script>alert("x")</script>')
    calculation_input = CalculationInput.model_validate({key: data[key] for key in ("mode", "cutting_conditions", "required_parts")})
    result = calculate(calculation_input)
    record = make_record("NEST-20260726-001", FIXED_TIME, data, result.model_dump())
    assert set(("format_version", "app_version", "management_number", "created_at", "updated_at", "input", "calculation_result")) <= record.keys()
    assert record["format_version"] == FORMAT_VERSION and record["app_version"] == APP_VERSION
    assert record["input"]["metadata"]["notes"] == '<script>alert("x")</script>'
    recalculated = calculate(CalculationInput.model_validate({key: record["input"][key] for key in ("mode", "cutting_conditions", "required_parts")}))
    assert recalculated.model_dump() == record["calculation_result"]


def test_html_contains_required_sections_escapes_and_does_not_mutate():
    data = inventory_input(title='<script>alert("x")</script>')
    calculation_input, result, view = main_module._saved_input(data)
    record = make_record("NEST-20260726-001", FIXED_TIME, data, result.model_dump())
    before = deepcopy(record)
    html = render_report(main_module.templates, record, view)
    assert '<meta charset="UTF-8">' in html and "<style>" in html
    assert "cdn" not in html.lower() and "http://" not in html and "https://" not in html
    for text in ("件名", "計算条件", "必要部材一覧", "在庫情報", "ダッシュボード概要", "パターン一覧", "使用材料一覧", "切断手順", "残材・廃棄材・使い切り", "未使用在庫と理由"):
        assert text in html
    assert "使い切り" in html and "左端を捨て切り" in html
    for text in ("在庫新品材", "在庫残材", "使用材料数", "使用材料一覧", "切出し部材"):
        assert text in html
    assert "廃棄判定基準 固定50mm（鋸刃厚に依存しない）" in html
    assert "50mm＋鋸刃厚" not in html
    assert "在庫残材600mmを1本用意" in html
    assert "切断時に鋸刃厚0mmを1回消費" in html
    assert "&lt;script&gt;" in html and '<script>alert("x")</script>' not in html
    assert record == before


def test_web_save_load_download_and_template_lists(web_storage):
    client, storage = web_storage
    response = client.post("/api/save", json={"input": saved_input()})
    assert response.status_code == 200
    number = response.json()["management_number"]
    assert number == "NEST-20260726-001"
    assert (storage.data_dir / f"{number}.json").exists()
    assert (storage.data_dir / f"{number}.html").exists()
    loaded = client.get(f"/api/records/{number}")
    assert loaded.json()["record"]["input"]["metadata"]["title"] == "日本語案件"
    assert loaded.json()["record"]["management_number"] == number
    json_download = client.get(f"/download/{number}.json")
    html_download = client.get(f"/download/{number}.html")
    assert json_download.status_code == html_download.status_code == 200
    assert "attachment" in json_download.headers["content-disposition"]
    assert number in html_download.text
    assert number in client.get("/").text
    form = {"mode":"required_stock","title":"","material_type":"","author":"","notes":"","new_stock_length_mm":"1030","kerf_mm":"5","left_trim_mm":"10","new_stock_quantity":"0","part_length":"500","part_quantity":"2","remnant_length":"","remnant_quantity":""}
    assert number in client.post("/", data=form).text


def test_json_and_html_downloads_match_saved_record(web_storage):
    client, _ = web_storage
    saved = client.post("/api/save", json={"input": saved_input()})
    number = saved.json()["management_number"]
    json_download = client.get(f"/download/{number}.json")
    html_download = client.get(f"/download/{number}.html")
    assert json_download.status_code == html_download.status_code == 200
    assert json_download.headers["content-disposition"] == f'attachment; filename="{number}.json"'
    assert html_download.headers["content-disposition"] == f'attachment; filename="{number}.html"'
    record = json_download.json()
    assert record["management_number"] == number
    assert set(("mode", "metadata", "cutting_conditions", "required_parts")) <= record["input"].keys()
    assert "使用材料一覧" in html_download.text
    assert "廃棄判定基準 固定50mm（鋸刃厚に依存しない）" in html_download.text


def test_web_overwrite_confirmation_and_number_stability(web_storage):
    client, storage = web_storage
    first = client.post("/api/save", json={"input": saved_input()}).json()
    number = first["management_number"]
    before = (storage.data_dir / f"{number}.json").read_bytes()
    conflict = client.post("/api/save", json={"input": saved_input(title="変更"), "management_number": number})
    assert conflict.status_code == 409 and conflict.json()["confirm_overwrite"]
    assert (storage.data_dir / f"{number}.json").read_bytes() == before
    overwritten = client.post("/api/save", json={"input": saved_input(title="変更"), "management_number": number, "overwrite": True})
    assert overwritten.json()["management_number"] == number


@pytest.mark.parametrize("number", ["NEST-20260726-999", "../secret", "bad"])
def test_web_missing_or_invalid_number_has_no_internal_path(web_storage, number):
    client, storage = web_storage
    response = client.get(f"/api/records/{number}")
    assert response.status_code in (400, 404)
    assert str(storage.data_dir) not in response.text
    assert "Traceback" not in response.text


def test_web_save_error_is_handled_and_does_not_claim_success(web_storage, monkeypatch):
    client, storage = web_storage
    monkeypatch.setattr(storage, "save_new", lambda builder: (_ for _ in ()).throw(StorageError("/private/path")))
    response = client.post("/api/save", json={"input": saved_input()})
    assert response.status_code == 400
    assert response.json()["ok"] is False
    assert "/private/path" not in response.text


def test_javascript_and_css_checkpoint5_contracts():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    css = Path("app/static/css/style.css").read_text(encoding="utf-8")
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    assert 'fetch("/api/save"' in javascript
    assert javascript.index("if (!response.ok") < javascript.index("setDirty(false)")
    assert "beforeunload" in javascript
    for choice in ('choice === "save"', 'choice === "cancel"', 'value="discard"'):
        assert choice in javascript or choice in template
    assert "download-json" in javascript and "setDirty(false)" not in javascript[javascript.index("jsonButton.addEventListener"):]
    for existing in ("[data-add]", ".remove", "updateMode"):
        assert existing in javascript
    assert "@media (max-width: 600px)" in css and ".file-toolbar" in css
    assert "calculation-management-number" in template and "displayCalculationIdentity" in javascript


def test_five_tabs_and_initial_selection_contract():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    for label in ("入力条件・計算条件", "ダッシュボード", "パターン一覧", "使用材料一覧", "切断手順"):
        assert label in template
    assert template.count('data-result-view=') == 5
    assert "data-has-result=\"{{ 'true' if result else 'false' }}\"" in template
    assert 'showResultView(hasResult ? "dashboard-view" : "conditions-view")' in javascript
    assert 'form.hidden = targetId' not in javascript
    assert 'data-result-view="conditions-view"' in template
    assert 'class="tab-content"' in template
    assert 'form="calculation-form" name="title"' in template
    assert 'document.querySelector(".common-information").addEventListener("input"' in javascript
    assert "let dirty = hasResult" in javascript
    for panel_id in ("dashboard-view", "patterns-view", "stocks-view", "instructions-view"):
        assert f'id="{panel_id}"' in template


def test_successful_save_downloads_json_only_after_api_success():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    save_start = javascript.index("async function saveRecord")
    save_end = javascript.index("function replaceRows", save_start)
    save_handler = javascript[save_start:save_end]
    success_check = save_handler.index("if (!response.ok || !data.ok)")
    assign_number = save_handler.index("managementNumber = data.management_number")
    download = save_handler.index("downloadJson()")
    assert success_check < assign_number < download
    assert 'body: JSON.stringify({input: formInput(), management_number: managementNumber, overwrite})' in save_handler
    assert 'if (data.confirm_overwrite && window.confirm(data.message))' in save_handler
    assert 'return await saveRecord(true)' in save_handler
    assert 'window.location.assign(`/download/${managementNumber}.json`)' in javascript
    assert 'jsonButton.addEventListener("click", downloadJson)' in javascript


def test_stage5_dirty_save_load_and_reset_contract():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    assert "● 未保存の変更があります" in javascript
    assert javascript.count("let dirty =") == 1
    save_start = javascript.index("async function saveRecord")
    save_end = javascript.index("function replaceRows", save_start)
    assert "setDirty(false)" in javascript[save_start:save_end]
    populate_start = javascript.index("function populate")
    populate_end = javascript.index("async function loadSelected", populate_start)
    assert "setDirty(false)" in javascript[populate_start:populate_end]
    assert 'resetButton.addEventListener("click", () => protectedAction' in javascript
    assert 'choice === "cancel"' in javascript
    assert 'window.location.assign("/")' in javascript
    assert 'const newButton' not in javascript and 'id="new-record"' not in template
    assert '<details class="other-actions">' in template
    assert 'id="load-record"' in template
    management_start = template.index('id="management-actions-heading"')
    management_end = template.index('class="card common-information"')
    management_panel = template[management_start:management_end]
    for control_id in ("download-json", "download-html"):
        assert f'id="{control_id}"' in management_panel


def test_management_download_buttons_have_responsive_single_line_layout():
    css = Path("app/static/css/style.css").read_text(encoding="utf-8")
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css
    assert ".file-actions button { min-width: 0; white-space: nowrap; }" in css
    assert ".file-actions { grid-template-columns: 1fr; }" in css


def test_add_row_buttons_follow_their_dynamic_rows_and_mobile_text_contract():
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    css = Path("app/static/css/style.css").read_text(encoding="utf-8")
    part_rows = template.index('id="part-rows"')
    part_button = template.index('data-add="part-rows"')
    remnant_rows = template.index('id="remnant-rows"')
    remnant_button = template.index('data-add="remnant-rows"')
    assert part_rows < part_button < remnant_rows < remnant_button
    assert template.count('class="row-actions"') == template.count('data-add=') == 2
    assert ".row-actions .secondary{width:100%}" in css
    assert ".measurement{white-space:nowrap}" in css
    assert "overflow-wrap:anywhere" in css
    assert "body{font-size:16px}" in css


def test_inventory_mode_reorders_only_input_sections():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    assert 'const requiredPartsFields = document.querySelector("#part-rows").closest(".card")' in javascript
    assert "form.insertBefore(inventoryFields, inventoryMode ? requiredPartsFields : calculateButton)" in javascript
    assert "inventoryFields.hidden = !inventoryMode" in javascript


def test_successful_calculation_scroll_contract():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    css = Path("app/static/css/style.css").read_text(encoding="utf-8")
    submit_start = javascript.index('form.addEventListener("submit"')
    submit_end = javascript.index("});", submit_start) + 3
    submit_handler = javascript[submit_start:submit_end]
    assert "sessionStorage.setItem(calculationScrollKey" in submit_handler
    assert "sessionStorage.removeItem(calculationScrollKey)" in javascript
    assert "if (resultTabs)" in javascript
    assert "if (shouldScrollToResults && hasResult)" in javascript
    assert javascript.index('showResultView("dashboard-view")') < javascript.index("scrollIntoView")
    assert 'scrollIntoView({behavior: "smooth", block: "start"})' in javascript
    assert "scroll-margin-top:16px" in css


def test_inline_error_scroll_and_clear_contract():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    css = Path("app/static/css/style.css").read_text(encoding="utf-8")
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    assert 'document.querySelector(".field-error-input")' in javascript
    assert 'firstFieldError.focus({preventScroll: true})' in javascript
    assert 'firstFieldError.scrollIntoView({behavior: "smooth", block: "center"})' in javascript
    assert 'input.classList.remove("field-error-input")' in javascript
    assert 'input.removeAttribute("aria-invalid")' in javascript
    assert 'document.querySelector(`#${messageId}`)?.remove()' in javascript
    assert "label .field-error-input" in css and ".field-error-message" in css
    assert 'aria-invalid="true"' in template and "field_errors" in template


def test_calculation_submit_suppresses_only_intended_unload():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    submit_start = javascript.index('form.addEventListener("submit"')
    submit_end = javascript.index("});", submit_start) + 3
    submit_handler = javascript[submit_start:submit_end]
    assert "calculationSubmitting = true" in submit_handler
    assert "suppressBeforeUnload = true" in submit_handler
    assert "setDirty(false)" not in submit_handler
    assert "let calculationSubmitting = false" in javascript
    assert "let suppressBeforeUnload = false" in javascript
    assert "dirty && !suppressBeforeUnload" in javascript
    assert "event.defaultPrevented" in javascript
    assert 'window.addEventListener("pageshow", resetCalculationSubmission)' in javascript
    reset_start = javascript.index("function resetCalculationSubmission")
    reset_end = javascript.index("}", reset_start)
    reset_handler = javascript[reset_start:reset_end]
    assert "calculationSubmitting = false" in reset_handler
    assert '.calculate-button").disabled = false' in reset_handler
