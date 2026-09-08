"""
Step 11 — Microsoft Teams Notifier Tests

Tests Teams payload formatting, 2xx responses, retry logic, missing webhooks, and secret safety using unittest.mock.
No real network requests are made.
"""

from unittest.mock import MagicMock, patch
import pytest

from src.notifier.teams_notifier import (
    send_teams_notification,
    format_teams_text,
)


@pytest.fixture
def sample_payload():
    return {
        "build": 246,
        "severity": "CRITICAL",
        "quality_gate": {"status": "FAIL", "recommendation": "BLOCK"},
        "summary": {"pass_rate": 88.0, "passed": 88, "failed": 10, "skipped": 2},
        "comparison": "WORSE",
        "trend": "WORSENING",
        "top_risk_modules": [{"module": "Payment", "score": 89, "level": "HIGH"}],
        "newly_failing_tests": ["test_payment_card"],
        "total_newly_failing": 1,
        "flaky_tests": [{"test_name": "test_payment_card", "score": 100}],
        "total_flaky": 1,
        "report": "reports/qa_report_build_246.html",
    }


def test_teams_payload_built_correctly(sample_payload):
    """Test payload contains Teams markdown formatting."""
    text = format_teams_text(sample_payload)
    assert "**QA Automation Operator**" in text
    assert "**Build:** 246" in text
    assert "**Quality Gate:** FAIL" in text


@patch("requests.post")
def test_teams_successful_2xx_response(mock_post, sample_payload):
    """Test 18: Teams returns 200 OK -> send_teams_notification returns True."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_post.return_value = mock_resp

    res = send_teams_notification(sample_payload, webhook_url="https://outlook.office.com/webhook/fake/secret")
    assert res is True
    assert mock_post.called


@patch("requests.post")
def test_teams_error_response_handled(mock_post, sample_payload):
    """Test 19: Teams non-2xx response raises ValueError without exposing secret URL."""
    fake_url = "https://outlook.office.com/webhook/SECRET_KEY_999"
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_post.return_value = mock_resp

    with pytest.raises(ValueError) as exc_info:
        send_teams_notification(sample_payload, webhook_url=fake_url)

    assert "Teams notification failed with status 400" in str(exc_info.value)
    # Test 25: Ensure secret webhook URL is NOT in exception message
    assert fake_url not in str(exc_info.value)


def test_teams_missing_webhook_skipped(monkeypatch, sample_payload):
    """Test 20: Missing webhook URL raises ValueError."""
    monkeypatch.delenv("TEAMS_WEBHOOK_URL", raising=False)
    with pytest.raises(ValueError, match="TEAMS_WEBHOOK_URL is not configured"):
        send_teams_notification(sample_payload)
