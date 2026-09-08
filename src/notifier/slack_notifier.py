"""
Slack Notifier Module.

Sends concise QA build summary notifications to a Slack channel via Incoming Webhook.

Rules:
    - Reads SLACK_WEBHOOK_URL from environment if not explicitly provided.
    - Webhook URLs/secrets must NEVER be printed or included in log messages/exceptions.
    - Uses requests.post with explicit timeout.
    - Retries once on 5xx server errors.
    - Raises exception on non-200 response code.
"""

import os
from typing import Any, Dict, Optional
import requests
from dotenv import load_dotenv

load_dotenv()


def format_slack_text(notification: Dict[str, Any]) -> str:
    """Formats a structured notification payload into a concise Slack markdown text message."""
    build = notification.get("build", "N/A")
    qg = notification.get("quality_gate", {})
    qg_status = qg.get("status", "UNKNOWN")
    qg_rec = qg.get("recommendation", "UNKNOWN")

    summary = notification.get("summary", {})
    pass_rate = summary.get("pass_rate", 0.0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    skipped = summary.get("skipped", 0)

    comparison = notification.get("comparison", "N/A")
    trend = notification.get("trend", "N/A")
    report = notification.get("report", "N/A")

    lines = [
        "*QA Automation Operator*",
        "",
        f"*Build:* {build}",
        "",
        f"*Quality Gate:* {qg_status}",
        f"*Release Recommendation:* {qg_rec}",
        "",
        f"*Pass Rate:* {pass_rate}%",
        f"*Passed:* {passed} | *Failed:* {failed} | *Skipped:* {skipped}",
        "",
        f"*Build Comparison:* {comparison}",
        f"*QA Trend:* {trend}",
        "",
    ]

    # Top Risk Modules
    risk_mods = notification.get("top_risk_modules", [])
    if risk_mods:
        lines.append("*Top Risk Modules:*")
        for i, rm in enumerate(risk_mods, start=1):
            lines.append(f"{i}. {rm['module']} - {rm['score']}/100 {rm['level']}")
        lines.append("")
    else:
        lines.append("*Top Risk Modules:* None")
        lines.append("")

    # Newly Failing Tests
    new_fail_count = notification.get("total_newly_failing", 0)
    lines.append(f"*Newly Failing Tests:* {new_fail_count}")
    new_fails = notification.get("newly_failing_tests", [])
    if new_fails:
        for t in new_fails:
            lines.append(f"• `{t}`")
        overflow = notification.get("newly_failing_overflow", 0)
        if overflow > 0:
            lines.append(f"• ...and {overflow} more")
    lines.append("")

    # Flaky Tests
    flaky_count = notification.get("total_flaky", 0)
    lines.append(f"*Flaky Tests:* {flaky_count}")
    flaky_list = notification.get("flaky_tests", [])
    if flaky_list:
        for ft in flaky_list:
            lines.append(f"• `{ft['test_name']}` ({ft['score']}/100)")
    lines.append("")

    lines.append("*Report:*")
    lines.append(report)

    return "\n".join(lines)


def send_slack_notification(
    notification: Dict[str, Any],
    webhook_url: Optional[str] = None,
    timeout: int = 10,
) -> bool:
    """
    Sends a Slack notification for the given payload using Incoming Webhooks.

    Args:
        notification: Structured notification payload.
        webhook_url: Optional webhook URL override (defaults to SLACK_WEBHOOK_URL env var).
        timeout: HTTP request timeout in seconds (default 10).

    Returns:
        True if sent successfully.

    Raises:
        ValueError: If HTTP response is not 200 OK.
    """
    url = webhook_url or os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        raise ValueError("Slack notification skipped: SLACK_WEBHOOK_URL is not configured.")

    text_body = format_slack_text(notification)
    payload = {"text": text_body}

    # Attempt request with 1 retry on 5xx errors
    response = None
    for attempt in range(2):
        try:
            response = requests.post(url, json=payload, timeout=timeout)
            if response.status_code == 200:
                return True
            if response.status_code < 500:
                # Client error (400, 401, 403, etc.) — do not retry
                break
        except requests.RequestException as exc:
            if attempt == 1:
                raise ValueError("Slack notification failed due to network error.") from None

    status_code = response.status_code if response else "Unknown"
    raise ValueError(f"Slack notification failed with status {status_code}.")
