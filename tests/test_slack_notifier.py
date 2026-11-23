"""
Step 11 — Slack Notifier Tests

Tests Slack payload formatting, 200 OK responses, retry logic, missing webhooks, and secret safety using unittest.mock.
No real network requests are made.
"""

from unittest.mock import MagicMock, patch
import pytest

from src.notifier.slack_notifier import (
    send_slack_notification,
    format_slack_text,
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


def test_slack_payload_built_correctly(sample_payload):
    """Test 14: Slack payload contains formatted text message."""
    text = format_slack_text(sample_payload)
    assert "*QA Automation Operator*" in text
    assert "*Build:* 246" in text
    assert "*Quality Gate:* FAIL" in text
    assert "Payment - 89/100 HIGH" in text


@patch("requests.post")
def test_slack_successful_200_response(mock_post, sample_payload):
    """Test 15: Slack returns 200 OK -> send_slack_notification returns True."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_post.return_value = mock_resp

    res = send_slack_notification(sample_payload, webhook_url="https://hooks.slack.com/services/fake/secret")
    assert res is True
    assert mock_post.called
    assert mock_post.call_args[1]["timeout"] == 10


@patch("requests.post")
def test_slack_non_200_handled(mock_post, sample_payload):
    """Test 16: Slack non-200 response raises ValueError without exposing secret URL."""
    fake_url = "https://hooks.slack.com/services/SECRET_WEBHOOK_123"
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_post.return_value = mock_resp

    with pytest.raises(ValueError) as exc_info:
        send_slack_notification(sample_payload, webhook_url=fake_url)

    assert "Slack notification failed with status 403" in str(exc_info.value)
    # Test 25: Ensure secret webhook URL is NOT in exception message
    assert fake_url not in str(exc_info.value)


def test_slack_missing_webhook_skipped(monkeypatch, sample_payload):
    """Test 17: Missing webhook URL raises ValueError."""
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    with pytest.raises(ValueError, match="SLACK_WEBHOOK_URL is not configured"):
        send_slack_notification(sample_payload)


@patch("requests.post")
def test_slack_retries_on_5xx_error(mock_post, sample_payload):
    """Test retry on 500 error: retries once then fails if still 500."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_post.return_value = mock_resp

    with pytest.raises(ValueError, match="Slack notification failed with status 500"):
        send_slack_notification(sample_payload, webhook_url="https://fake.url")

    assert mock_post.call_count == 2
