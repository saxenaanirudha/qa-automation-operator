"""
Notifier Service Module — High-Level Dispatcher.

Orchestrates notification dispatching to Slack and Microsoft Teams based on
configuration and environment variables. Handles missing configurations and network
failures gracefully without raising unhandled exceptions to main caller.
"""

import os
from typing import Any, Dict, Optional
from dotenv import load_dotenv

from config import get_notification_config
from src.notifier.slack_notifier import send_slack_notification
from src.notifier.teams_notifier import send_teams_notification

load_dotenv()


def send_qa_notifications(
    notification: Dict[str, Any],
    slack_enabled: Optional[bool] = None,
    teams_enabled: Optional[bool] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Dispatches QA notifications to enabled platforms (Slack, Teams).

    Args:
        notification: Structured notification payload.
        slack_enabled: Optional override to enable/disable Slack dispatch.
        teams_enabled: Optional override to enable/disable Teams dispatch.
        config: Optional notification configuration dict.

    Returns:
        Result dictionary containing delivery status for each platform.
    """
    cfg = config or get_notification_config()
    timeout = int(cfg.get("timeout_seconds", 10))

    # Determine enabled status for Slack
    if slack_enabled is not None:
        is_slack_enabled = slack_enabled
    else:
        is_slack_enabled = bool(cfg.get("slack", {}).get("enabled", False))

    # Determine enabled status for Teams
    if teams_enabled is not None:
        is_teams_enabled = teams_enabled
    else:
        is_teams_enabled = bool(cfg.get("teams", {}).get("enabled", False))

    slack_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    teams_url = os.getenv("TEAMS_WEBHOOK_URL", "").strip()

    results: Dict[str, Dict[str, Any]] = {
        "slack": {
            "enabled": is_slack_enabled,
            "configured": bool(slack_url),
            "sent": False,
            "message": "Disabled.",
        },
        "teams": {
            "enabled": is_teams_enabled,
            "configured": bool(teams_url),
            "sent": False,
            "message": "Disabled.",
        },
    }

    # Dispatch Slack
    if is_slack_enabled:
        if not slack_url:
            results["slack"]["message"] = "Skipped: SLACK_WEBHOOK_URL is not configured."
        else:
            try:
                sent = send_slack_notification(notification, webhook_url=slack_url, timeout=timeout)
                results["slack"]["sent"] = sent
                results["slack"]["message"] = "Sent successfully."
            except Exception as exc:
                results["slack"]["sent"] = False
                results["slack"]["message"] = f"Failed to send: {exc}"

    # Dispatch Teams
    if is_teams_enabled:
        if not teams_url:
            results["teams"]["message"] = "Skipped: TEAMS_WEBHOOK_URL is not configured."
        else:
            try:
                sent = send_teams_notification(notification, webhook_url=teams_url, timeout=timeout)
                results["teams"]["sent"] = sent
                results["teams"]["message"] = "Sent successfully."
            except Exception as exc:
                results["teams"]["sent"] = False
                results["teams"]["message"] = f"Failed to send: {exc}"

    return results
