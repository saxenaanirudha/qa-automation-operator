import pytest
import pandas as pd
from fastapi.testclient import TestClient
from src.api.app import app
from src.database.database import init_db, get_session
from src.database.repository import save_build_result

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_test_build_data():
    """Seeds test build data into SQLite before each test."""
    init_db()
    session = get_session()

    # Seed build 801
    summary1 = {
        "build": 801,
        "total": 2,
        "passed": 1,
        "failed": 1,
        "skipped": 0,
        "pass_rate": 50.0,
        "failure_rate": 50.0,
    }
    df1 = pd.DataFrame(
        [
            {"test_name": "test_card", "module": "Payment", "status": "FAIL", "duration": 1.5, "error": "Timeout", "build": 801},
            {"test_name": "test_login", "module": "Auth", "status": "PASS", "duration": 0.8, "error": None, "build": 801},
        ]
    )
    try:
        save_build_result(summary1, df1, session=session)
    except Exception:
        pass

    # Seed build 802
    summary2 = {
        "build": 802,
        "total": 2,
        "passed": 2,
        "failed": 0,
        "skipped": 0,
        "pass_rate": 100.0,
        "failure_rate": 0.0,
    }
    df2 = pd.DataFrame(
        [
            {"test_name": "test_card", "module": "Payment", "status": "PASS", "duration": 1.0, "error": None, "build": 802},
            {"test_name": "test_login", "module": "Auth", "status": "PASS", "duration": 0.7, "error": None, "build": 802},
        ]
    )
    try:
        save_build_result(summary2, df2, session=session)
    except Exception:
        pass

    session.close()


def test_list_builds():
    response = client.get("/builds?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 2
    assert data[0]["build_number"] >= data[1]["build_number"]


def test_get_build_success():
    response = client.get("/builds/801")
    assert response.status_code == 200
    data = response.json()
    assert data["build_number"] == 801
    assert data["total_tests"] == 2
    assert data["failed"] == 1


def test_get_build_not_found():
    response = client.get("/builds/999999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_get_build_tests_and_filters():
    response = client.get("/builds/801/tests")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    # Status filter
    res_fail = client.get("/builds/801/tests?status=FAIL")
    assert res_fail.status_code == 200
    assert len(res_fail.json()) == 1
    assert res_fail.json()[0]["module"] == "Payment"

    # Module filter
    res_auth = client.get("/builds/801/tests?module=Auth")
    assert res_auth.status_code == 200
    assert len(res_auth.json()) == 1
    assert res_auth.json()[0]["test_name"] == "test_login"


def test_get_build_failures():
    response = client.get("/builds/801/failures")
    assert response.status_code == 200
    data = response.json()
    assert data["build"] == 801
    assert data["total_failures"] == 1
    assert "Payment" in data["failures_by_module"]


def test_get_build_comparison():
    response = client.get("/builds/802/comparison")
    assert response.status_code == 200
    data = response.json()
    assert data["previous_build"] == 801
    assert data["current_build"] == 802
    assert data["overall_status"] == "BETTER"


def test_get_build_risk():
    response = client.get("/builds/801/risk")
    assert response.status_code == 200
    data = response.json()
    assert data["build"] == 801
    assert "ranked_modules" in data


def test_get_build_quality_gate():
    response = client.get("/builds/801/quality-gate")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "release_recommendation" in data


def test_post_build_report():
    response = client.post("/builds/801/report")
    assert response.status_code == 200
    data = response.json()
    assert data["build"] == 801
    assert data["status"] == "generated"
    assert "report_path" in data


def test_post_build_notify():
    response = client.post("/builds/801/notify", json={"slack": True, "teams": True})
    assert response.status_code == 200
    data = response.json()
    assert data["build"] == 801
    assert "slack" in data
    assert "teams" in data
