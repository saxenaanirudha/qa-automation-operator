import pytest
from fastapi.testclient import TestClient
from src.api.app import app

client = TestClient(app)


def test_get_historical_trends():
    response = client.get("/analysis/trends?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data or "pass_rate_trend" in data


def test_get_flaky_test_analysis():
    response = client.get("/analysis/flaky-tests?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "flaky_tests" in data
    assert "possibly_flaky_tests" in data
