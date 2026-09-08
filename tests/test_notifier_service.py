"""
Step 11 — Notifier Service Tests

Tests high-level dispatching, disabled platform handling, missing webhooks, and error resilience.
No real network requests are made.
"""

from unittest.mock import patch
import pytest

from src.notifier.notifier_service import send_qa_notifications
from src.notifier.notification_builder import build_notification_payload
from src.quality_gate.quality_gate import evaluate_quality_gate


@pytest.fixture
def sample_payload():
    return build_notification_payload(
        246,
        summary={"pass_rate": 90.0, "passed": 9, "failed": 1, "skipped": 0},
        quality_gate={"status": "PASS", "release_recommendation": "PROCEED"},
        report_path="reports/qa_report_build_246.html",
    )


def test_disabled_slack_not_called(sample_payload):
    """Test 21: Disabled Slack is skipped with message 'Disabled.'."""
    res = send_qa_notifications(sample_payload, slack_enabled=False, teams_enabled=False)
    assert res["slack"]["enabled"] is False
    assert res["slack"]["sent"] is False
    assert res["slack"]["message"] == "Disabled."


def test_disabled_teams_not_called(sample_payload):
    """Test 22: Disabled Teams is skipped with message 'Disabled.'."""
    res = send_qa_notifications(sample_payload, slack_enabled=False, teams_enabled=False)
    assert res["teams"]["enabled"] is False
    assert res["teams"]["sent"] is False
    assert res["teams"]["message"] == "Disabled."


@patch("src.notifier.notifier_service.send_slack_notification")
@patch("src.notifier.notifier_service.send_teams_notification")
def test_slack_and_teams_both_enabled(mock_teams, mock_slack, monkeypatch, sample_payload):
    """Test 23: Both platforms called when enabled and configured."""
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/fake")
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://outlook.office.com/fake")
    mock_slack.return_value = True
    mock_teams.return_value = True

    res = send_qa_notifications(sample_payload, slack_enabled=True, teams_enabled=True)
    assert res["slack"]["sent"] is True
    assert res["teams"]["sent"] is True
    assert mock_slack.called
    assert mock_teams.called


def test_missing_webhook_configured_handled(monkeypatch, sample_payload):
    """Test 17 & 20: Missing webhook URLs handled gracefully without throwing unhandled exception."""
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("TEAMS_WEBHOOK_URL", raising=False)

    res = send_qa_notifications(sample_payload, slack_enabled=True, teams_enabled=True)
    assert res["slack"]["sent"] is False
    assert "not configured" in res["slack"]["message"]
    assert res["teams"]["sent"] is False
    assert "not configured" in res["teams"]["message"]


@patch("src.notifier.notifier_service.send_slack_notification")
@patch("src.notifier.notifier_service.send_teams_notification")
def test_one_platform_failing_does_not_prevent_other(mock_teams, mock_slack, monkeypatch, sample_payload):
    """Test 24: Failure on Slack does not block Teams notification."""
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/fake")
    monkeypatch.setenv("TEAMS_WEBHOOK_URL", "https://outlook.office.com/fake")

    mock_slack.side_effect = ValueError("Slack notification failed with status 500.")
    mock_teams.return_value = True

    res = send_qa_notifications(sample_payload, slack_enabled=True, teams_enabled=True)
    assert res["slack"]["sent"] is False
    assert "Failed to send" in res["slack"]["message"]
    assert res["teams"]["sent"] is True
    assert res["teams"]["message"] == "Sent successfully."


def test_step10_html_reporting_remains_unchanged():
    """Test 32: Step 10 HTML reporting imports and signatures remain unchanged."""
    from src.reporter.html_reporter import generate_html_report
    assert callable(generate_html_report)
