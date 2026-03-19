from fastapi.testclient import TestClient

from app.main import app


def test_config_endpoint_returns_defaults():
    client = TestClient(app)
    client.post("/auth/login", json={"username": "admin", "password": "admin123456"})
    response = client.get("/api/config")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schedule_interval_minutes"] == 10
    assert payload["log_retention_days"] == 3
    assert payload["run_retention_days"] == 3
    assert "new_api_base_url" not in payload
    assert "new_api_username" not in payload


def test_index_page_renders():
    client = TestClient(app)
    client.post("/auth/login", json={"username": "admin", "password": "admin123456"})
    response = client.get("/")
    assert response.status_code == 200
    assert "巡检与自动恢复管理台" in response.text


def test_unauthenticated_is_redirected_or_blocked():
    client = TestClient(app)
    page_response = client.get("/", follow_redirects=False)
    api_response = client.get("/api/config")
    assert page_response.status_code == 303
    assert api_response.status_code == 401
