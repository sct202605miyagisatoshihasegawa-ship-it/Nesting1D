# Nesting1D - 基本Webエンドポイントテスト
# 役割: 初期画面とヘルスチェックの基本応答を検証する。
# 更新日: 2026-08-10

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_page() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Nesting1D" in response.text
    assert "計算結果識別情報" in response.text
    assert "未発行" in response.text and "未計算" in response.text


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
    }
