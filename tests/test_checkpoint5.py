from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.calculation import CalculationInput, calculate
from app.exporting import make_record, render_report
from app.records import (
    APP_VERSION,
    FORMAT_VERSION,
    MANAGEMENT_NUMBER_ALPHABET,
    RecordError,
    generate_management_number,
    validate_record,
)

TOKYO = ZoneInfo("Asia/Tokyo")
FIXED_TIME = datetime(2026, 7, 26, 10, 20, 30, tzinfo=TOKYO)


def test_public_v1_patch_version_is_consistent():
    assert APP_VERSION == "1.0.1"
    assert main_module.app.version == APP_VERSION


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


def direct_export_request(**updates):
    request = {
        "input": saved_input(),
        "management_number": "NEST-20260805-103645-A7K2",
        "created_at": "2026-08-05T10:36:45+09:00",
        "updated_at": "2026-08-05T10:36:45+09:00",
    }
    request.update(updates)
    return request


def test_new_management_number_uses_tokyo_time_and_unambiguous_secure_alphabet(monkeypatch):
    choices = iter("A7K2")
    monkeypatch.setattr("app.records.secrets.choice", lambda alphabet: next(choices))
    utc_time = datetime(2026, 8, 5, 1, 36, 45, tzinfo=ZoneInfo("UTC"))
    number = generate_management_number(utc_time)
    assert number == "NEST-20260805-103645-A7K2"
    assert set(number.rsplit("-", 1)[1]) <= set(MANAGEMENT_NUMBER_ALPHABET)
    assert not set("IO01") & set(MANAGEMENT_NUMBER_ALPHABET)


@pytest.mark.parametrize(
    "number",
    ["NEST-20260805-103645-A7K2", "NEST-20260726-001"],
)
def test_record_validation_accepts_current_and_legacy_management_numbers(number):
    assert validate_record(bare_record(number))["management_number"] == number


@pytest.mark.parametrize(
    "number",
    [
        "NEST-20260805-103645-A7I2",
        "NEST-20260805-103645-A7O2",
        "NEST-20260805-103645-A702",
        "NEST-20260805-103645-A712",
        "NEST-20260805-103645-a7k2",
        "NEST-20260805-103645-A7K",
        "NEST-20260805-103645-A7K22",
        "NEST-20260805-103645-Ａ7K2",
    ],
)
def test_record_validation_rejects_invalid_current_management_numbers(number):
    with pytest.raises(RecordError, match="管理番号"):
        validate_record(bare_record(number))


@pytest.mark.parametrize("field", ["created_at", "updated_at"])
def test_record_validation_rejects_invalid_tokyo_timestamps(field):
    record = bare_record()
    record[field] = "2026-07-26T10:20:30+00:00"
    with pytest.raises(RecordError, match="日時"):
        validate_record(record)


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


def test_direct_json_export_returns_memory_response_without_server_files():
    client = TestClient(main_module.app)
    number = "NEST-20260805-103645-A7K2"
    response = client.post(
        "/api/export/json",
        json=direct_export_request(management_number=number),
    )
    assert response.status_code == 200
    assert response.headers["content-disposition"] == f'attachment; filename="{number}.json"'
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["management_number"] == number
    _, expected_result, _ = main_module._saved_input(saved_input())
    assert response.json()["calculation_result"] == expected_result.model_dump()


def test_direct_json_export_rejects_invalid_number_without_server_files():
    client = TestClient(main_module.app)
    response = client.post(
        "/api/export/json",
        json=direct_export_request(management_number="../../private"),
    )
    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "message": "処理できませんでした。入力内容を確認してください。",
    }


def test_direct_html_export_is_independent_and_writes_no_server_files():
    client = TestClient(main_module.app)
    response = client.post("/api/export/html", json=direct_export_request())
    number = "NEST-20260805-103645-A7K2"
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html; charset=utf-8")
    assert response.headers["content-disposition"] == f'attachment; filename="{number}.html"'
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert number in response.text
    assert "使用材料一覧" in response.text


def test_json_and_html_direct_exports_share_the_complete_record(monkeypatch):
    client = TestClient(main_module.app)
    captured = {}
    original_render = main_module.render_report

    def capture_record(templates, record, view):
        captured["record"] = record
        return original_render(templates, record, view)

    monkeypatch.setattr(main_module, "render_report", capture_record)
    request = direct_export_request(input=saved_input(notes='<script>秘密</script>'))
    json_response = client.post("/api/export/json", json=request)
    html_response = client.post("/api/export/html", json=request)
    assert json_response.status_code == html_response.status_code == 200
    assert captured["record"] == json_response.json()
    assert captured["record"]["management_number"] == request["management_number"]
    assert captured["record"]["created_at"] == request["created_at"]
    assert captured["record"]["updated_at"] == request["updated_at"]
    assert captured["record"]["input"] == json_response.json()["input"]
    assert captured["record"]["calculation_result"] == json_response.json()["calculation_result"]
    assert "&lt;script&gt;秘密&lt;/script&gt;" in html_response.text
    assert "<script>秘密</script>" not in html_response.text


def test_direct_html_export_error_hides_input_and_internal_details():
    client = TestClient(main_module.app)
    response = client.post(
        "/api/export/html",
        json=direct_export_request(input=saved_input(notes="DO_NOT_EXPOSE"), created_at="not-a-timestamp"),
    )
    assert response.status_code == 400
    assert "DO_NOT_EXPOSE" not in response.text
    assert "Traceback" not in response.text


def test_javascript_and_css_checkpoint5_contracts():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    css = Path("app/static/css/style.css").read_text(encoding="utf-8")
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    assert '/api/save' not in javascript
    assert "beforeunload" in javascript
    for choice in ('choice === "cancel"', 'value="discard"'):
        assert choice in javascript or choice in template
    assert "download-json" in javascript
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


def test_json_export_state_changes_only_after_success_and_invalid_results_are_blocked():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    download_start = javascript.index("async function downloadJson")
    download_end = javascript.index('jsonButton.addEventListener("click", downloadJson)', download_start)
    download_handler = javascript[download_start:download_end]
    success_check = download_handler.index("if (!response.ok)")
    success_state = download_handler.index("jsonExported = true")
    failure_state = download_handler.index("jsonExported = false")
    assert success_check < success_state < failure_state
    assert "!hasValidResult" in download_handler
    assert "requiresManagementNumberReissue" in download_handler
    assert "return false" in download_handler


def test_html_export_is_independent_and_changes_state_only_after_success():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    start = javascript.index("async function downloadHtml")
    end = javascript.index('htmlButton.addEventListener("click", downloadHtml)', start)
    handler = javascript[start:end]
    assert 'fetch("/api/export/html"' in handler
    assert "!hasValidResult" in handler
    assert "requiresManagementNumberReissue" in handler
    assert "const blob = await response.blob()" in handler
    assert "URL.createObjectURL(blob)" in handler
    assert "URL.revokeObjectURL(objectUrl)" in handler
    assert handler.index("if (!response.ok)") < handler.index("htmlExported = true")
    assert handler.index("htmlExported = true") < handler.index("htmlExported = false")
    assert "jsonExported" not in handler
    assert "return false" in handler


def test_combined_output_status_and_shared_identity_state_are_present():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    assert "JSON・HTML出力済み" in javascript
    assert "hasValidResult && jsonExported && htmlExported" in javascript
    assert "const hasAnyExport = jsonExported || htmlExported" in javascript
    for state_name in ("managementNumber", "createdAt", "updatedAt"):
        assert f"let {state_name} =" in javascript
    for input_id in ("result-management-number", "result-created-at", "result-updated-at"):
        assert f'id="{input_id}"' in template


def test_input_change_invalidates_result_and_requests_new_management_number():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    start = javascript.index("function invalidateCalculationResult")
    end = javascript.index("function formInput", start)
    handler = javascript[start:end]
    for contract in (
        "hasValidResult = false",
        "jsonExported = false",
        "htmlExported = false",
        "requiresManagementNumberReissue = true",
        'managementNumberStateInput.value = "reissue"',
        'createdAtInput.value = ""',
        'updatedAtInput.value = ""',
        "jsonButton.disabled = true",
        "htmlButton.disabled = true",
    ):
        assert contract in handler
    assert 'form.addEventListener("input"' in javascript
    assert 'document.querySelector(".common-information").addEventListener("input"' in javascript


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


def test_local_json_file_api_ui_and_no_upload_contract():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    for contract in (
        'type="file" id="local-json-file" accept=".json,application/json"',
        'id="load-local-json"',
        'id="local-json-filename"',
        'id="local-json-error" role="alert"',
        "端末のJSONを読み込む",
    ):
        assert contract in template
    start = javascript.index("async function loadLocalJson")
    end = javascript.index("function protectedAction", start)
    handler = javascript[start:end]
    assert "await file.text()" in handler
    assert "JSON.parse(text)" in handler
    assert "fetch(" not in handler
    assert "FormData" not in handler
    assert "file.textContent" not in handler
    assert 'localJsonFileInput.value = ""' in handler
    assert 'localJsonFilename.textContent = file.name' in handler


def test_local_json_file_metadata_and_size_contract():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    assert "const LOCAL_JSON_MAX_BYTES = 5 * 1024 * 1024" in javascript
    start = javascript.index("async function loadLocalJson")
    end = javascript.index("function protectedAction", start)
    handler = javascript[start:end]
    assert "localJsonFileInput.files.length !== 1" in handler
    assert 'file.name.toLowerCase().endsWith(".json")' in handler
    assert "const mimeType = file.type.toLowerCase()" in handler
    assert "if (mimeType &&" in handler
    assert 'mimeType !== "application/json"' in handler
    assert 'mimeType !== "text/json"' in handler
    assert 'mimeType.endsWith("+json")' in handler
    assert "file.size > LOCAL_JSON_MAX_BYTES" in handler
    for message in (
        "JSONファイルを選択してください",
        "読み込めるJSONファイルではありません",
        "JSONファイルが大きすぎます",
    ):
        assert message in handler


def test_local_json_structure_validation_contract():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    start = javascript.index("function validateLocalRecord")
    end = javascript.index("function captureCurrentState", start)
    validator = javascript[start:end]
    assert "isPlainObject(record)" in validator
    assert "exceedsJsonDepth(record)" in validator
    assert 'record.format_version !== "1.0"' in validator
    for key in (
        "format_version", "app_version", "management_number", "created_at",
        "updated_at", "input", "calculation_result",
    ):
        assert f'"{key}"' in validator
    assert "LEGACY_MANAGEMENT_NUMBER.test" in validator
    assert "CURRENT_MANAGEMENT_NUMBER.test" in validator
    assert "TOKYO_TIMESTAMP.test(record.created_at)" in validator
    assert "TOKYO_TIMESTAMP.test(record.updated_at)" in validator
    assert '!["required_stock", "inventory"].includes(input.mode)' in validator
    assert "Array.isArray(rows)" in javascript
    assert "Number.isSafeInteger(value)" in javascript
    assert "LOCAL_JSON_MAX_PART_ROWS = 20" in javascript
    assert "LOCAL_JSON_MAX_REMNANT_ROWS = 10" in javascript
    assert "normalizeRows(input.required_parts, 1, LOCAL_JSON_MAX_PART_ROWS, 500)" in javascript
    assert "normalizeRows(input.inventory.remnants, 0, LOCAL_JSON_MAX_REMNANT_ROWS, 500)" in javascript
    assert "requireSafeInteger(row.length_mm, 1, 6100)" in javascript
    assert "requireSafeInteger(input.cutting_conditions.new_stock_length_mm, 1, 6100)" in javascript
    assert "requireSafeInteger(input.cutting_conditions.kerf_mm, 0, 100)" in javascript
    assert "requireSafeInteger(input.cutting_conditions.left_trim_mm, 0, 100)" in javascript
    assert "requireSafeInteger(input.inventory.new_stock_quantity, 0, 500)" in javascript
    assert "1000000" not in validator
    assert "LOCAL_JSON_MAX_DEPTH = 8" in javascript
    assert "value.length > LOCAL_JSON_MAX_BYTES" in javascript


def test_html_instruction_uses_saved_numeric_trim_and_kerf():
    data = saved_input()
    data["cutting_conditions"] = {
        "new_stock_length_mm": 1_000,
        "kerf_mm": 3,
        "left_trim_mm": 17,
    }
    data["required_parts"] = [{"length_mm": 100, "quantity": 1}]
    _, result, view = main_module._saved_input(data)
    record = make_record("NEST-20260726-001", FIXED_TIME, data, result.model_dump())
    html = render_report(main_module.templates, record, view)
    assert "左端を17mm捨て切り" in html
    assert "鋸刃厚3mm" in html


def test_dynamic_row_limits_and_reenable_contract():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    assert 'INPUT_ROW_LIMITS = {"part-rows": 20, "remnant-rows": 10}' in javascript
    assert 'target.querySelectorAll(".input-row").length >= INPUT_ROW_LIMITS[button.dataset.add]' in javascript
    assert javascript.count("updateAddRowButton(button)") >= 3
    assert 'updateAddRowButton(document.querySelector(`[data-add="${rowContainer.id}"]`))' in javascript
    assert 'updateAddRowButton(document.querySelector(`[data-add="${containerId}"]`))' in javascript


def test_local_json_accepts_legacy_and_current_number_patterns_contract():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    assert r"/^NEST-\d{8}-\d{3}$/" in javascript
    assert r"/^NEST-\d{8}-\d{6}-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}$/" in javascript
    assert "管理番号の形式が正しくありません" in javascript
    assert "日時の形式が正しくありません" in javascript


def test_local_json_normalizes_before_atomic_application_and_ignores_result_contract():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    load_start = javascript.index("async function loadLocalJson")
    load_end = javascript.index("function protectedAction", load_start)
    handler = javascript[load_start:load_end]
    assert handler.index("const record = validateLocalRecord(parsed)") < handler.index("applyRecord(record")
    assert "const previousState = captureCurrentState()" in handler
    assert "restoreCurrentState(previousState)" in handler
    validator_start = javascript.index("function validateLocalRecord")
    validator_end = javascript.index("function captureCurrentState", validator_start)
    validator = javascript[validator_start:validator_end]
    assert "calculation_result: {}" in validator
    assert "record.calculation_result" not in validator.replace("isPlainObject(record.calculation_result)", "")
    assert ".innerHTML" not in javascript


def test_local_json_state_preserves_identity_until_recalculation_contract():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    start = javascript.index("function applyRecord")
    end = javascript.index("function isPlainObject", start)
    apply_handler = javascript[start:end]
    for contract in (
        "managementNumber = record.management_number",
        "createdAt = record.created_at",
        "updatedAt = record.updated_at",
        "requiresManagementNumberReissue = false",
        "hasValidResult = false",
        "jsonExported = false",
        "htmlExported = false",
        "jsonLoadedPendingCalculation = true",
        'managementNumberStateInput.value = "maintain"',
        "jsonButton.disabled = true",
        "htmlButton.disabled = true",
    ):
        assert contract in apply_handler
    assert "JSON読込済み・再計算前" in javascript
    invalidate_start = javascript.index("function invalidateCalculationResult")
    invalidate_end = javascript.index("function formInput", invalidate_start)
    assert "jsonLoadedPendingCalculation = false" in javascript[invalidate_start:invalidate_end]


def test_public_v1_has_no_server_storage_routes_or_data_references():
    client = TestClient(main_module.app)
    main_source = Path("app/main.py").read_text(encoding="utf-8")
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    assert not Path("app/storage.py").exists()
    for forbidden in ("RecordStorage", "DATA_DIR", 'Path(__file__).resolve().parent.parent / "data"'):
        assert forbidden not in main_source
    for path in ("/api/save", "/api/records/NEST-20260726-001", "/download/NEST-20260726-001.json", "/download/NEST-20260726-001.html"):
        assert client.get(path).status_code in (404, 405)
        assert client.post(path).status_code in (404, 405)
    for forbidden in ("/api/save", "/api/records/", "/download/", "saveRecord", "loadSelected"):
        assert forbidden not in javascript
    for forbidden in ('id="save-record"', 'id="record-select"', 'id="load-record"', "保存済み", "旧サーバー"):
        assert forbidden not in template


def test_public_v1_buttons_reach_only_direct_memory_exports():
    javascript = Path("app/static/js/input.js").read_text(encoding="utf-8")
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    assert template.count('id="download-json"') == 1
    assert template.count('id="download-html"') == 1
    assert template.count('id="load-local-json"') == 1
    assert javascript.count('jsonButton.addEventListener("click", downloadJson)') == 1
    assert javascript.count('htmlButton.addEventListener("click", downloadHtml)') == 1
    assert javascript.count('localJsonLoadButton.addEventListener("click", () => protectedAction(loadLocalJson))') == 1
    json_handler = javascript[javascript.index("async function downloadJson"):javascript.index('jsonButton.addEventListener("click", downloadJson)')]
    html_handler = javascript[javascript.index("async function downloadHtml"):javascript.index('htmlButton.addEventListener("click", downloadHtml)')]
    assert 'fetch("/api/export/json"' in json_handler
    assert 'fetch("/api/export/html"' in html_handler
    assert "/api/export/html" not in json_handler
    assert "/api/export/json" not in html_handler
    assert "downloadJson()" not in html_handler
    assert 'type="button"' in template
    assert "?v=20260810-v1" in template


def test_direct_exports_create_no_files_in_isolated_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(main_module.app)
    assert client.post("/api/export/json", json=direct_export_request()).status_code == 200
    assert client.post("/api/export/html", json=direct_export_request()).status_code == 200
    assert list(tmp_path.rglob("*")) == []


def test_public_v1_does_not_persist_calculation_state_or_log_user_payloads():
    javascript = Path(__file__).parents[1].joinpath("app/static/js/input.js").read_text(encoding="utf-8")
    application = Path(__file__).parents[1].joinpath("app/main.py").read_text(encoding="utf-8")
    for forbidden in ("localStorage", "indexedDB", "document.cookie"):
        assert forbidden not in javascript
    session_lines = [line for line in javascript.splitlines() if "sessionStorage" in line]
    assert session_lines
    assert all("calculationScrollKey" in line for line in session_lines)
    assert not any(name in line for line in session_lines for name in ("managementNumber", "createdAt", "updatedAt", "jsonExported", "htmlExported"))
    for forbidden in ("print(", "console.log", "console.debug", "console.info", "logging.", "logger."):
        assert forbidden not in application
        assert forbidden not in javascript
