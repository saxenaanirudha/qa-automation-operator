"""Reporter module."""

from src.reporter.html_reporter import generate_html_report
from src.reporter.chart_generator import (
    generate_pass_rate_chart,
    generate_failure_trend_chart,
    generate_module_failure_chart,
    generate_risk_chart,
)

__all__ = [
    "generate_html_report",
    "generate_pass_rate_chart",
    "generate_failure_trend_chart",
    "generate_module_failure_chart",
    "generate_risk_chart",
]
