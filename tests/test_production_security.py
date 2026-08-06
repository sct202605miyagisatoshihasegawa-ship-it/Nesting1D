import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from tests.test_checkpoint5 import direct_export_request
from tests.test_web_calculation import normal


SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}


def assert_security_headers(response) -> None:
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


def test_development_documentation_urls_are_available(monkeypatch) -> None:
    try:
        with monkeypatch.context() as patch:
            patch.delenv("APP_ENV", raising=False)
            development_module = importlib.reload(main_module)
            client = TestClient(development_module.app)

            assert client.get("/docs").status_code == 200
            assert client.get("/redoc").status_code == 200
            assert client.get("/openapi.json").status_code == 200
    finally:
        importlib.reload(main_module)


@pytest.mark.parametrize("app_env", ["production", "PRODUCTION", "PrOdUcTiOn"])
def test_production_value_is_case_insensitive(app_env: str) -> None:
    assert main_module.is_production(app_env)


@pytest.mark.parametrize("app_env", [None, "", "development", "prod"])
def test_non_production_values_remain_development(app_env: str | None) -> None:
    assert not main_module.is_production(app_env)


def test_production_disables_documentation_urls(monkeypatch) -> None:
    with monkeypatch.context() as patch:
        patch.setenv("APP_ENV", "PrOdUcTiOn")
        production_module = importlib.reload(main_module)
        client = TestClient(production_module.app)

        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404

    importlib.reload(main_module)


def test_common_security_headers_cover_pages_health_404_and_json_export() -> None:
    client = TestClient(main_module.app)
    responses = (
        client.get("/"),
        client.get("/health"),
        client.get("/this-route-does-not-exist"),
        client.post("/api/export/json", json=direct_export_request()),
    )

    assert [response.status_code for response in responses] == [200, 200, 404, 200]
    for response in responses:
        assert_security_headers(response)


def test_html_no_store_does_not_apply_to_static_css() -> None:
    client = TestClient(main_module.app)

    assert client.get("/").headers["cache-control"] == "no-store"
    assert client.post("/", data=normal()).headers["cache-control"] == "no-store"
    css_response = client.get("/static/css/style.css")
    assert css_response.status_code == 200
    assert css_response.headers.get("cache-control") != "no-store"


def test_export_headers_are_preserved_without_duplicate_cache_values() -> None:
    client = TestClient(main_module.app)
    request = direct_export_request()
    json_response = client.post("/api/export/json", json=request)
    html_response = client.post("/api/export/html", json=request)

    assert json_response.headers["content-disposition"].endswith('.json"')
    assert json_response.headers["cache-control"] == "no-store"
    assert html_response.headers["content-disposition"].endswith('.html"')
    assert html_response.headers["cache-control"] == "no-store"
    assert html_response.headers["pragma"] == "no-cache"
    assert_security_headers(json_response)
    assert_security_headers(html_response)


def test_robots_txt_is_crawl_guidance_not_access_control() -> None:
    response = TestClient(main_module.app).get("/robots.txt")

    assert response.status_code == 200
    assert response.text == "User-agent: *\nDisallow: /\n"
    assert response.headers["content-type"].startswith("text/plain")
    assert_security_headers(response)


def test_html_templates_include_noindex_metadata() -> None:
    meta = '<meta name="robots" content="noindex, nofollow, noarchive">'

    assert meta in Path("app/templates/index.html").read_text(encoding="utf-8")
    assert meta in Path("app/templates/report.html").read_text(encoding="utf-8")
