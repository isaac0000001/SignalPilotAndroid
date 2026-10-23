from fastapi.testclient import TestClient

from app.main import app


def test_application_starts():
    assert app.title == "SignalPilot Pro"


def test_root_endpoint():
    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200

    data = response.json()

    assert data["application"] == "SignalPilot Pro"
    assert data["status"] == "running"
    assert data["live_trading_enabled"] is False


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "ok"
    assert data["live_trading_enabled"] is False
    assert data["live_market_data"] is False
