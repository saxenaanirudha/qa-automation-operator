import io
import time
import pytest
from fastapi.testclient import TestClient
from src.api.app import app
from src.api.security import rate_limiter

client = TestClient(app)


def get_unique_build(offset: int = 0) -> int:
    """Generates a guaranteed unique build number based on current nanosecond timestamp."""
    return (int(time.time_ns()) % 100000000) + offset


@pytest.fixture(autouse=True)
def reset_security_env(monkeypatch):
    """Ensures clean environment state and resets rate limiter before each test."""
    rate_limiter.reset()
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("REQUIRE_API_KEY", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.delenv("RATE_LIMIT_REQUESTS", raising=False)
    monkeypatch.delenv("RATE_LIMIT_WINDOW", raising=False)


# ---------------------------------------------------------------------------
# 1. Permissive Local Development Tests
# ---------------------------------------------------------------------------
def test_unauthenticated_local_development_permitted_by_default():
    """By default in dev without API_KEY, endpoints function for local convenience."""
    res = client.get("/health")
    assert res.status_code == 200

    b_num = get_unique_build(100)
    csv_data = f"test_name,module,status,duration,error,build\nt1,M,PASS,0.1,,{b_num}\n".encode("utf-8")
    res_upload = client.post(
        "/analyze",
        files={"file": ("test.csv", io.BytesIO(csv_data), "text/csv")},
        data={"format": "csv"},
    )
    assert res_upload.status_code == 200


# ---------------------------------------------------------------------------
# 2. X-API-Key Authentication Tests
# ---------------------------------------------------------------------------
def test_missing_api_key_returns_401_when_configured(monkeypatch):
    """When API_KEY is set on the server, requests lacking X-API-Key return 401."""
    monkeypatch.setenv("API_KEY", "prod-secret-token-xyz")

    b_num = get_unique_build(200)
    csv_data = f"test_name,module,status,duration,error,build\nt1,M,PASS,0.1,,{b_num}\n".encode("utf-8")
    res = client.post(
        "/analyze",
        files={"file": ("test.csv", io.BytesIO(csv_data), "text/csv")},
        data={"format": "csv"},
    )
    assert res.status_code == 401
    assert "Missing required API key" in res.json()["detail"]


def test_invalid_api_key_returns_403(monkeypatch):
    """When an invalid X-API-Key is provided, returns 403 Forbidden."""
    monkeypatch.setenv("API_KEY", "correct-super-secret-token")

    b_num = get_unique_build(300)
    csv_data = f"test_name,module,status,duration,error,build\nt1,M,PASS,0.1,,{b_num}\n".encode("utf-8")
    res = client.post(
        "/analyze",
        files={"file": ("test.csv", io.BytesIO(csv_data), "text/csv")},
        data={"format": "csv"},
        headers={"X-API-Key": "wrong-token-abc"},
    )
    assert res.status_code == 403
    assert "Invalid API key" in res.json()["detail"]


def test_valid_api_key_succeeds(monkeypatch):
    """When a valid X-API-Key is provided, request succeeds."""
    token = "my-verified-qa-key-777"
    monkeypatch.setenv("API_KEY", token)

    b_num = get_unique_build(400)
    csv_data = f"test_name,module,status,duration,error,build\nt1,M,PASS,0.1,,{b_num}\n".encode("utf-8")
    res = client.post(
        "/analyze",
        files={"file": ("test.csv", io.BytesIO(csv_data), "text/csv")},
        data={"format": "csv"},
        headers={"X-API-Key": token},
    )
    assert res.status_code == 200
    assert res.json()["build"] == b_num


def test_production_fails_closed_when_api_key_is_missing(monkeypatch):
    """
    In production environment (ENVIRONMENT=production), missing API_KEY
    must fail closed (HTTP 500) rather than allowing unauthenticated access.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("API_KEY", raising=False)

    b_num = get_unique_build(500)
    csv_data = f"test_name,module,status,duration,error,build\nt1,M,PASS,0.1,,{b_num}\n".encode("utf-8")
    res = client.post(
        "/analyze",
        files={"file": ("test.csv", io.BytesIO(csv_data), "text/csv")},
        data={"format": "csv"},
    )
    assert res.status_code == 500
    assert "API_KEY must be set in production" in res.json()["detail"]


def test_report_and_notify_endpoints_are_protected(monkeypatch):
    """Protected report and notification endpoints also enforce X-API-Key."""
    monkeypatch.setenv("API_KEY", "secure-key-999")

    # Missing key on report trigger
    res_report = client.post("/builds/99999/report")
    assert res_report.status_code == 401

    # Missing key on notify trigger
    res_notify = client.post("/builds/99999/notify", json={"slack": True, "teams": True})
    assert res_notify.status_code == 401

    # Valid key passes auth check
    res_report_valid = client.post("/builds/99999/report", headers={"X-API-Key": "secure-key-999"})
    assert res_report_valid.status_code in (200, 404)  # 404 if build not in db, but passes auth!


# ---------------------------------------------------------------------------
# 3. Rate Limiting Tests
# ---------------------------------------------------------------------------
def test_rate_limiting_triggers_429(monkeypatch):
    """When requests exceed configured RATE_LIMIT_REQUESTS, HTTP 429 is returned."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "3")
    monkeypatch.setenv("RATE_LIMIT_WINDOW", "60")

    base_build = get_unique_build(600)

    # Make 3 allowed requests
    for i in range(3):
        b_num = base_build + i
        csv_data = f"test_name,module,status,duration,error,build\nt1,M,PASS,0.1,,{b_num}\n".encode("utf-8")
        res = client.post(
            "/analyze",
            files={"file": (f"test_{i}.csv", io.BytesIO(csv_data), "text/csv")},
            data={"format": "csv"},
        )
        assert res.status_code == 200

    # 4th request must be rejected with 429
    csv_blocked = f"test_name,module,status,duration,error,build\nt1,M,PASS,0.1,,{base_build + 99}\n".encode("utf-8")
    res_blocked = client.post(
        "/analyze",
        files={"file": ("test_blocked.csv", io.BytesIO(csv_blocked), "text/csv")},
        data={"format": "csv"},
    )
    assert res_blocked.status_code == 429
    assert "Rate limit exceeded" in res_blocked.json()["detail"]


def test_rate_limiting_tracks_proxied_ip(monkeypatch):
    """Rate limiter extracts and enforces per original client IP from X-Forwarded-For when TRUST_PROXIES is enabled."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("RATE_LIMIT_WINDOW", "60")
    monkeypatch.setenv("TRUST_PROXIES", "true")
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1,::1,testclient")

    headers_ip_a = {"X-Forwarded-For": "203.0.113.195, 10.0.0.1"}
    headers_ip_b = {"X-Forwarded-For": "198.51.100.44, 10.0.0.1"}

    base_build = get_unique_build(700)

    # 2 requests from IP A
    for i in range(2):
        b_num = base_build + i
        csv_data = f"test_name,module,status,duration,error,build\nt1,M,PASS,0.1,,{b_num}\n".encode("utf-8")
        res = client.post(
            "/analyze",
            files={"file": (f"test_a_{i}.csv", io.BytesIO(csv_data), "text/csv")},
            data={"format": "csv"},
            headers=headers_ip_a,
        )
        assert res.status_code == 200

    # 3rd request from IP A is rate limited
    csv_a_blocked = f"test_name,module,status,duration,error,build\nt1,M,PASS,0.1,,{base_build + 50}\n".encode("utf-8")
    res_a_blocked = client.post(
        "/analyze",
        files={"file": ("test_a_block.csv", io.BytesIO(csv_a_blocked), "text/csv")},
        data={"format": "csv"},
        headers=headers_ip_a,
    )
    assert res_a_blocked.status_code == 429

    # IP B is unaffected and can still make requests
    csv_b = f"test_name,module,status,duration,error,build\nt1,M,PASS,0.1,,{base_build + 90}\n".encode("utf-8")
    res_b = client.post(
        "/analyze",
        files={"file": ("test_b.csv", io.BytesIO(csv_b), "text/csv")},
        data={"format": "csv"},
        headers=headers_ip_b,
    )
    assert res_b.status_code == 200


def test_rate_limiting_cannot_be_bypassed_by_spoofed_headers(monkeypatch):
    """
    Security Gate: When TRUST_PROXIES is false (default), clients cannot bypass
    rate limiting by sending randomized/spoofed X-Forwarded-For headers.
    """
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("RATE_LIMIT_WINDOW", "60")
    monkeypatch.setenv("TRUST_PROXIES", "false")

    base_build = get_unique_build(800)

    # 2 requests using different spoofed IP headers
    for i in range(2):
        b_num = base_build + i
        csv_data = f"test_name,module,status,duration,error,build\nt1,M,PASS,0.1,,{b_num}\n".encode("utf-8")
        res = client.post(
            "/analyze",
            files={"file": (f"test_spoof_{i}.csv", io.BytesIO(csv_data), "text/csv")},
            data={"format": "csv"},
            headers={"X-Forwarded-For": f"10.99.{i}.1"},
        )
        assert res.status_code == 200

    # 3rd request from same client with yet another spoofed IP must still be BLOCKED
    csv_blocked = f"test_name,module,status,duration,error,build\nt1,M,PASS,0.1,,{base_build + 50}\n".encode("utf-8")
    res_blocked = client.post(
        "/analyze",
        files={"file": ("test_spoof_block.csv", io.BytesIO(csv_blocked), "text/csv")},
        data={"format": "csv"},
        headers={"X-Forwarded-For": "10.99.99.99"},
    )
    assert res_blocked.status_code == 429
    assert "Rate limit exceeded" in res_blocked.json()["detail"]


@pytest.mark.anyio
async def test_lifespan_refuses_to_start_in_production_without_api_key(monkeypatch):
    """
    Security Gate: The FastAPI lifespan manager must raise RuntimeError on startup
    in production mode if API_KEY is missing.
    """
    from src.api.app import lifespan

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Production mode requires API_KEY"):
        async with lifespan(app):
            pass

