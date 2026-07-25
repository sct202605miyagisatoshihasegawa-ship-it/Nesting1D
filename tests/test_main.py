from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_root_page() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Nesting1D" in response.text
    assert "正常に稼働しています" in response.text


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
    }
