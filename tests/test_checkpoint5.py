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
    for text in ("件名", "計算条件", "必要部材一覧", "在庫情報", "ダッシュボード概要", "パターン一覧", "母材一覧", "切断手順", "残材・廃棄材・使い切り", "未使用在庫と理由"):
        assert text in html
    assert "使い切り" in html and "左端を捨て切り" in html
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
