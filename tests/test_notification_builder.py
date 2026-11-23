"""
Step 11 — Notification Builder Tests

Tests payload construction, severity mapping, risk/flaky limiters, and REPORT_BASE_URL resolution.
"""

import os
import pytest

from src.notifier.notification_builder import (
    build_notification_payload,
    SEVERITY_MAP,
)


def test_notification_payload_contains_build_number():
    """Test 1: Notification payload contains build number."""
    payload = build_notification_payload(246)
    assert payload["build"] == 246


def test_quality_gate_and_recommendation_appear():
    """Test 2 & 3: Quality Gate status and release recommendation appear."""
    qg = {"status": "FAIL", "release_recommendation": "BLOCK"}
    payload = build_notification_payload(246, quality_gate=qg)
    assert payload["quality_gate"]["status"] == "FAIL"
    assert payload["quality_gate"]["recommendation"] == "BLOCK"


def test_pass_rate_and_summary_appear():
    """Test 4 & 5: Pass rate and execution summary appear."""
    sum_data = {"pass_rate": 88.5, "passed": 88, "failed": 10, "skipped": 2}
    payload = build_notification_payload(246, summary=sum_data)
    assert payload["summary"]["pass_rate"] == 88.5
    assert payload["summary"]["failed"] == 10


def test_severity_mapping_pass_warning_fail():
    """Test 29, 30, 31: Severity maps PASS -> INFO, WARNING -> WARNING, FAIL -> CRITICAL."""
    assert SEVERITY_MAP["PASS"] == "INFO"
    assert SEVERITY_MAP["WARNING"] == "WARNING"
    assert SEVERITY_MAP["FAIL"] == "CRITICAL"

    payload_pass = build_notification_payload(100, quality_gate={"status": "PASS", "release_recommendation": "PROCEED"})
    assert payload_pass["severity"] == "INFO"

    payload_warn = build_notification_payload(100, quality_gate={"status": "WARNING", "release_recommendation": "REVIEW"})
    assert payload_warn["severity"] == "WARNING"

    payload_fail = build_notification_payload(100, quality_gate={"status": "FAIL", "release_recommendation": "BLOCK"})
    assert payload_fail["severity"] == "CRITICAL"


def test_top_risk_modules_limited_correctly():
    """Test 6 & 7: Top risk modules are limited (default 3) and sorted correctly."""
    risk = {
        "ranked_modules": ["ModA", "ModB", "ModC", "ModD"],
        "modules": {
            "ModA": {"score": 90, "level": "HIGH"},
            "ModB": {"score": 75, "level": "HIGH"},
            "ModC": {"score": 50, "level": "MEDIUM"},
            "ModD": {"score": 20, "level": "LOW"},
        },
    }
    payload = build_notification_payload(100, risk_analysis=risk)
    top_mods = payload["top_risk_modules"]
    assert len(top_mods) == 3
    assert top_mods[0]["module"] == "ModA"
    assert top_mods[2]["module"] == "ModC"


def test_newly_failing_tests_limited_correctly():
    """Test 8 & 27: Newly failing tests are limited (max 5) with overflow count."""
    comp = {"newly_failing_tests": [f"t{i}" for i in range(8)]}
    payload = build_notification_payload(100, comparison=comp)
    assert len(payload["newly_failing_tests"]) == 5
    assert payload["total_newly_failing"] == 8
    assert payload["newly_failing_overflow"] == 3


def test_flaky_tests_limited_correctly():
    """Test 9 & 28: Flaky tests are limited (max 3) with top scores."""
    flaky = {
        "flaky_tests": ["t1", "t2", "t3", "t4"],
        "ranked_flaky_tests": ["t1", "t2", "t3", "t4"],
        "possibly_flaky_tests": ["t5"],
        "tests": {f"t{i}": {"flaky_score": 100 - i * 10, "module": "Mod"} for i in range(1, 6)},
    }
    payload = build_notification_payload(100, flaky_analysis=flaky)
    assert len(payload["flaky_tests"]) == 3
    assert payload["total_flaky"] == 4
    assert payload["total_possibly_flaky"] == 1


def test_comparison_and_trend_missing_handled():
    """Test 10 & 11: Missing comparison and trend fall back to N/A."""
    payload = build_notification_payload(100, comparison=None, trend_analysis=None)
    assert payload["comparison"] == "N/A"
    assert payload["trend"] == "N/A"


def test_report_path_included():
    """Test 12: Report filepath is included when REPORT_BASE_URL is not set."""
    payload = build_notification_payload(100, report_path="reports/qa_report_100.html")
    assert "qa_report_100.html" in payload["report"]


def test_report_base_url_generates_url(monkeypatch):
    """Test 13: REPORT_BASE_URL env var generates full HTTP URL."""
    monkeypatch.setenv("REPORT_BASE_URL", "https://qa.example.com/reports")
    payload = build_notification_payload(100, report_path="reports/qa_report_100.html")
    assert payload["report"] == "https://qa.example.com/reports/qa_report_100.html"


def test_empty_high_risk_modules_handled():
    """Test 26: Empty high-risk modules handled cleanly."""
    payload = build_notification_payload(100, risk_analysis={"ranked_modules": [], "modules": {}})
    assert payload["top_risk_modules"] == []
