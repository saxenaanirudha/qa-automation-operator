"""
Step 10 — Chart Generator Tests

Tests Matplotlib chart image creation and missing/empty data handling.
Uses temporary output directories.
"""

import os
from pathlib import Path
import pytest

from src.reporter.chart_generator import (
    generate_pass_rate_chart,
    generate_failure_trend_chart,
    generate_module_failure_chart,
    generate_risk_chart,
)


@pytest.fixture
def tmp_chart_dir(tmp_path):
    d = tmp_path / "chart_assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_pass_rate_chart_created(tmp_chart_dir):
    """Test 25: Pass-rate chart PNG is generated for valid build history."""
    out = str(tmp_chart_dir / "pass_rate.png")
    result = generate_pass_rate_chart([80.0, 90.0, 95.0], [100, 101, 102], out)
    assert result == out
    assert os.path.exists(out)
    assert os.path.getsize(out) > 0


def test_failure_chart_created(tmp_chart_dir):
    """Test 26: Failure trend chart PNG is generated."""
    out = str(tmp_chart_dir / "failure_trend.png")
    result = generate_failure_trend_chart([5, 3, 1], [100, 101, 102], out)
    assert result == out
    assert os.path.exists(out)


def test_module_failure_chart_created(tmp_chart_dir):
    """Test 27: Module failure bar chart PNG is generated for non-zero failures."""
    out = str(tmp_chart_dir / "mod_failures.png")
    result = generate_module_failure_chart({"Payment": 5, "Checkout": 2}, out)
    assert result == out
    assert os.path.exists(out)


def test_risk_chart_created(tmp_chart_dir):
    """Test 28: Risk scores bar chart PNG is generated."""
    out = str(tmp_chart_dir / "risk_scores.png")
    report = {
        "Payment": {"score": 85, "level": "HIGH"},
        "Checkout": {"score": 50, "level": "MEDIUM"},
        "Login": {"score": 10, "level": "LOW"},
    }
    result = generate_risk_chart(report, out)
    assert result == out
    assert os.path.exists(out)


def test_missing_chart_data_does_not_crash(tmp_chart_dir):
    """Test 29: Insufficient or empty chart data returns None without crashing."""
    out = str(tmp_chart_dir / "empty.png")
    assert generate_pass_rate_chart([], [], out) is None
    assert generate_pass_rate_chart([100.0], [100], out) is None
    assert generate_failure_trend_chart([], [], out) is None
    assert generate_module_failure_chart({}, out) is None
    assert generate_module_failure_chart({"Login": 0}, out) is None
    assert generate_risk_chart({}, out) is None
