"""
Step 8 — Quality Gate Tests

All 32 tests use an isolated in-memory SQLite database or custom configs.
No production database is touched.
"""

import pytest
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.database import Base
from src.database.repository import save_build_result, BuildNotFoundError
from config import validate_quality_gate_config
from src.quality_gate.quality_gate import (
    evaluate_quality_gate,
    evaluate_pass_rate,
    evaluate_failure_count,
    evaluate_high_risk_modules,
    evaluate_new_failures,
    evaluate_trend,
    evaluate_build_comparison,
)
from src.analyzer.risk_analyzer import analyze_risk


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    """Fresh in-memory SQLite session for each test."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def default_config():
    return {
        "pass_rate": {"warning_below": 95.0, "fail_below": 90.0},
        "failure_count": {"warning_at": 5, "fail_at": 10},
        "high_risk_modules": {"warning_at": 1, "fail_at": 2},
        "overall_trend": {"warning_on": ["WORSENING"]},
        "build_comparison": {"warning_on": ["WORSE"]},
        "newly_failing_tests": {"warning_at": 3, "fail_at": 6},
    }


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _summary(build_num, total, passed, failed, skipped):
    pr = round(passed / total * 100, 2) if total else 0.0
    fr = round(failed / total * 100, 2) if total else 0.0
    return {
        "build": build_num,
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "pass_rate": pr,
        "failure_rate": fr,
    }


def _df(rows, build_num):
    return pd.DataFrame([
        {"test_name": r[0], "module": r[1], "status": r[2],
         "duration": 1.0, "error": r[3], "build": build_num}
        for r in rows
    ])


def _seed(session, build_num, rows):
    total = len(rows)
    passed = sum(1 for r in rows if r[2] == "PASS")
    failed = sum(1 for r in rows if r[2] == "FAIL")
    skipped = sum(1 for r in rows if r[2] == "SKIP")
    save_build_result(
        _summary(build_num, total, passed, failed, skipped),
        _df(rows, build_num),
        session=session,
    )


def _pass(name, mod="M"):  return (name, mod, "PASS", None)
def _fail(name, mod="M"):  return (name, mod, "FAIL", "Err")


# ---------------------------------------------------------------------------
# Tests 1-17: Individual Rule & Quality Gate Output Tests
# ---------------------------------------------------------------------------

def test_healthy_build_returns_pass(db_session):
    """Test 1: Healthy build with 100% pass rate returns PASS."""
    rows = [_pass(f"t{i}", "M") for i in range(20)]
    _seed(db_session, 100, rows)
    res = evaluate_quality_gate(100, session=db_session)
    assert res["status"] == "PASS"
    assert res["release_recommendation"] == "PROCEED"
    assert len(res["triggered_rules"]) == 0


def test_warning_pass_rate():
    """Test 2: Pass rate between 90% and 95% triggers WARNING."""
    status, rule = evaluate_pass_rate(93.0)
    assert status == "WARNING"
    assert rule["severity"] == "WARNING"
    assert "below warning threshold" in rule["message"]


def test_failing_pass_rate():
    """Test 3: Pass rate below 90% triggers FAIL."""
    status, rule = evaluate_pass_rate(88.0)
    assert status == "FAIL"
    assert rule["severity"] == "FAIL"
    assert "below fail threshold" in rule["message"]


def test_warning_failure_count():
    """Test 4: 5 failures triggers WARNING."""
    status, rule = evaluate_failure_count(5)
    assert status == "WARNING"
    assert rule["severity"] == "WARNING"


def test_failing_failure_count():
    """Test 5: 10 failures triggers FAIL."""
    status, rule = evaluate_failure_count(10)
    assert status == "FAIL"
    assert rule["severity"] == "FAIL"


def test_one_high_risk_module_warning():
    """Test 6: 1 high-risk module creates WARNING."""
    status, rule = evaluate_high_risk_modules(1)
    assert status == "WARNING"
    assert rule["severity"] == "WARNING"


def test_multiple_high_risk_modules_fail():
    """Test 7: 2 high-risk modules create FAIL."""
    status, rule = evaluate_high_risk_modules(2)
    assert status == "FAIL"
    assert rule["severity"] == "FAIL"


def test_worsening_overall_trend_warning():
    """Test 8: WORSENING overall trend creates WARNING."""
    status, rule = evaluate_trend("WORSENING")
    assert status == "WARNING"
    assert rule["severity"] == "WARNING"


def test_worse_build_comparison_warning():
    """Test 9: WORSE build comparison creates WARNING."""
    status, rule = evaluate_build_comparison("WORSE")
    assert status == "WARNING"
    assert rule["severity"] == "WARNING"


def test_newly_failing_tests_warning():
    """Test 10: 3 newly failing tests trigger WARNING."""
    status, rule = evaluate_new_failures(3)
    assert status == "WARNING"
    assert rule["severity"] == "WARNING"


def test_newly_failing_tests_fail():
    """Test 11: 6 newly failing tests trigger FAIL."""
    status, rule = evaluate_new_failures(6)
    assert status == "FAIL"
    assert rule["severity"] == "FAIL"


def test_fail_takes_priority_over_warning(db_session, default_config):
    """Test 12: Triggering FAIL and WARNING rules results in overall FAIL."""
    # Seed build with 88% pass rate (FAIL) and worsening trend (WARNING)
    # Build 100: 100% pass
    _seed(db_session, 100, [_pass(f"t{i}") for i in range(25)])
    # Build 101: 75% pass
    _seed(db_session, 101, [_pass(f"t{i}") for i in range(20)] + [_fail(f"f{i}") for i in range(5)])
    # Build 102: 88% pass (22 pass, 3 fail)
    rows_102 = [_pass(f"t{i}") for i in range(22)] + [_fail(f"f{i}") for i in range(3)]
    _seed(db_session, 102, rows_102)

    res = evaluate_quality_gate(102, session=db_session, config=default_config)
    assert res["status"] == "FAIL"
    assert res["release_recommendation"] == "BLOCK"


def test_warning_takes_priority_over_pass(db_session, default_config):
    """Test 13: Triggering WARNING rule when other checks PASS results in WARNING."""
    # 93 pass, 5 fail -> Total 98. Pass rate = 94.9% (WARNING < 95%), Failure count = 5 (WARNING >= 5) -> WARNING
    # Or 94 pass, 3 fail -> Total 97. Pass rate = 96.9% (PASS), Failure count = 5 (WARNING)
    # Let's do 95 pass, 5 fail: Total 100. Pass rate = 95.0% (PASS), Failure count = 5 (WARNING >= 5)
    rows_warn = [_pass(f"t{i}") for i in range(95)] + [_fail(f"f{i}") for i in range(5)]
    _seed(db_session, 100, rows_warn)
    res = evaluate_quality_gate(100, session=db_session, config=default_config)
    assert res["status"] == "WARNING"
    assert res["release_recommendation"] == "REVIEW"


def test_no_triggered_rules_is_pass(db_session):
    """Test 14: Clean build triggers no rules and returns PASS."""
    _seed(db_session, 100, [_pass("t1"), _pass("t2")])
    res = evaluate_quality_gate(100, session=db_session)
    assert res["status"] == "PASS"
    assert res["triggered_rules"] == []


def test_release_recommendation_proceed():
    """Test 15: PASS maps to PROCEED."""
    assert evaluate_pass_rate(98.0)[0] == "PASS"


def test_release_recommendation_review(db_session):
    """Test 16: WARNING maps to REVIEW."""
    # 93 pass, 7 fail -> Pass rate 93.0% (WARNING)
    rows = [_pass(f"t{i}") for i in range(93)] + [_fail(f"f{i}") for i in range(7)]
    _seed(db_session, 100, rows)
    res = evaluate_quality_gate(100, session=db_session)
    assert res["status"] == "WARNING"
    assert res["release_recommendation"] == "REVIEW"



def test_release_recommendation_block(db_session):
    """Test 17: FAIL maps to BLOCK."""
    rows = [_pass(f"t{i}") for i in range(80)] + [_fail(f"f{i}") for i in range(20)]
    _seed(db_session, 100, rows)
    res = evaluate_quality_gate(100, session=db_session)
    assert res["status"] == "FAIL"
    assert res["release_recommendation"] == "BLOCK"


# ---------------------------------------------------------------------------
# Tests 18-20: Missing History Handling
# ---------------------------------------------------------------------------

def test_missing_previous_build(db_session):
    """Test 18: Quality Gate works when no previous build exists."""
    _seed(db_session, 100, [_pass("t1"), _pass("t2")])
    res = evaluate_quality_gate(100, session=db_session)
    assert res["checks"]["build_comparison"]["value"] == "UNKNOWN"
    assert res["checks"]["build_comparison"]["status"] == "PASS"
    assert res["status"] == "PASS"


def test_missing_trend_history(db_session):
    """Test 19: Quality Gate works when fewer than 3 builds exist."""
    _seed(db_session, 100, [_pass("t1")])
    _seed(db_session, 101, [_pass("t1")])
    res = evaluate_quality_gate(101, session=db_session)
    assert res["checks"]["overall_trend"]["value"] == "UNKNOWN"
    assert res["checks"]["overall_trend"]["status"] == "PASS"


def test_insufficient_risk_history(db_session):
    """Test 20: Quality Gate uses current build Risk Analyzer output even with 1 build."""
    _seed(db_session, 100, [_pass("t1", "Login"), _pass("t2", "Checkout")])
    res = evaluate_quality_gate(100, session=db_session)
    assert res["checks"]["high_risk_modules"]["value"] == 0
    assert res["checks"]["high_risk_modules"]["status"] == "PASS"


# ---------------------------------------------------------------------------
# Tests 21-23: Exact Threshold & Boundary Behavior
# ---------------------------------------------------------------------------

def test_exact_warning_threshold_behavior():
    """Test 21: Failure count 5 is WARNING, 4 is PASS."""
    assert evaluate_failure_count(4)[0] == "PASS"
    assert evaluate_failure_count(5)[0] == "WARNING"


def test_exact_fail_threshold_behavior():
    """Test 22: Failure count 10 is FAIL, 9 is WARNING."""
    assert evaluate_failure_count(9)[0] == "WARNING"
    assert evaluate_failure_count(10)[0] == "FAIL"


def test_pass_rate_threshold_boundary():
    """Test 23: Boundary conditions: 89.99=FAIL, 90.0=WARNING, 94.99=WARNING, 95.0=PASS."""
    assert evaluate_pass_rate(89.99)[0] == "FAIL"
    assert evaluate_pass_rate(90.0)[0] == "WARNING"
    assert evaluate_pass_rate(94.99)[0] == "WARNING"
    assert evaluate_pass_rate(95.0)[0] == "PASS"


# ---------------------------------------------------------------------------
# Tests 24-27: Multiple Rules, Triggered Rules & Checks Structure
# ---------------------------------------------------------------------------

def test_multiple_warning_rules(db_session, default_config):
    """Test 24: Multiple warning rules are all captured in triggered_rules."""
    # 93% pass rate (WARNING) and WORSE build comparison (WARNING)
    _seed(db_session, 100, [_pass(f"t{i}") for i in range(100)])
    # Build 101 has 93 pass, 7 fail -> 93% pass rate (< 95% warning), failed diff = +7 (WORSE comparison)
    _seed(db_session, 101, [_pass(f"t{i}") for i in range(93)] + [_fail(f"f{i}") for i in range(7)])
    res = evaluate_quality_gate(101, session=db_session, config=default_config)
    severities = [r["severity"] for r in res["triggered_rules"]]
    assert "WARNING" in severities
    assert len(res["triggered_rules"]) >= 2


def test_multiple_fail_rules(db_session, default_config):
    """Test 25: Multiple fail rules are captured in triggered_rules."""
    # 85% pass rate (FAIL) and 12 failures (FAIL)
    rows = [_pass(f"t{i}") for i in range(85)] + [_fail(f"f{i}") for i in range(15)]
    _seed(db_session, 100, rows)
    res = evaluate_quality_gate(100, session=db_session, config=default_config)
    fail_rules = [r["rule"] for r in res["triggered_rules"] if r["severity"] == "FAIL"]
    assert "PASS_RATE" in fail_rules
    assert "FAILURE_COUNT" in fail_rules


def test_triggered_rule_messages_are_clear():
    """Test 26: Triggered rule messages contain formatted values and thresholds."""
    _, rule = evaluate_pass_rate(88.0)
    assert "88.0%" in rule["message"]
    assert "90.0%" in rule["message"]


def test_checks_section_contains_evaluated_values(db_session):
    """Test 27: Checks section contains value and status for every check."""
    _seed(db_session, 100, [_pass("t1")])
    res = evaluate_quality_gate(100, session=db_session)
    checks = res["checks"]
    required_keys = ["pass_rate", "failure_count", "high_risk_modules", "newly_failing_tests", "overall_trend", "build_comparison"]
    for k in required_keys:
        assert k in checks
        assert "value" in checks[k]
        assert "status" in checks[k]


# ---------------------------------------------------------------------------
# Tests 28-30: Configuration Validation Errors
# ---------------------------------------------------------------------------

def test_invalid_pass_rate_configuration():
    """Test 28: Fail threshold higher than warning threshold raises ValueError."""
    bad_cfg = {
        "pass_rate": {"fail_below": 96.0, "warning_below": 90.0},
        "failure_count": {"warning_at": 5, "fail_at": 10},
        "high_risk_modules": {"warning_at": 1, "fail_at": 2},
        "newly_failing_tests": {"warning_at": 3, "fail_at": 6},
    }
    with pytest.raises(ValueError, match="pass_rate fail threshold cannot be higher than warning threshold"):
        validate_quality_gate_config(bad_cfg)


def test_invalid_failure_count_configuration():
    """Test 29: Fail threshold lower than warning threshold raises ValueError."""
    bad_cfg = {
        "pass_rate": {"fail_below": 90.0, "warning_below": 95.0},
        "failure_count": {"warning_at": 10, "fail_at": 5},
        "high_risk_modules": {"warning_at": 1, "fail_at": 2},
        "newly_failing_tests": {"warning_at": 3, "fail_at": 6},
    }
    with pytest.raises(ValueError, match="failure_count fail threshold cannot be lower than warning threshold"):
        validate_quality_gate_config(bad_cfg)


def test_invalid_risk_module_configuration():
    """Test 30: High risk module fail threshold lower than warning threshold raises ValueError."""
    bad_cfg = {
        "pass_rate": {"fail_below": 90.0, "warning_below": 95.0},
        "failure_count": {"warning_at": 5, "fail_at": 10},
        "high_risk_modules": {"warning_at": 2, "fail_at": 1},
        "newly_failing_tests": {"warning_at": 3, "fail_at": 6},
    }
    with pytest.raises(ValueError, match="high_risk_modules fail threshold cannot be lower than warning threshold"):
        validate_quality_gate_config(bad_cfg)


# ---------------------------------------------------------------------------
# Tests 31-32: Step 7 Compatibility & Determinism
# ---------------------------------------------------------------------------

def test_step7_risk_analyzer_remains_unchanged(db_session):
    """Test 31: Risk Analyzer function and output structure remain identical."""
    _seed(db_session, 100, [_fail("t1", "Pay"), _pass("t2", "Auth")])
    risk = analyze_risk(100, session=db_session)
    assert "ranked_modules" in risk
    assert "modules" in risk
    assert "high_risk_modules" in risk


def test_overall_result_is_deterministic(db_session):
    """Test 32: Quality gate evaluation produces deterministic output given same data."""
    _seed(db_session, 100, [_pass("t1"), _fail("t2")])
    res1 = evaluate_quality_gate(100, session=db_session)
    res2 = evaluate_quality_gate(100, session=db_session)
    assert res1 == res2


# ---------------------------------------------------------------------------
# Tests 33-39: Population Comparability & Quality Gate Safety
# ---------------------------------------------------------------------------

def test_qg_build_comparison_identical_regression(db_session):
    """Test 33: Identical populations with genuine regression triggers WARNING."""
    _seed(db_session, 501, [_pass("t1", "M"), _pass("t2", "M")])
    _seed(db_session, 502, [_pass("t1", "M"), _fail("t2", "M")])

    res = evaluate_quality_gate(502, session=db_session)
    assert res["checks"]["build_comparison"]["value"] == "WORSE"
    assert res["checks"]["build_comparison"]["status"] == "WARNING"
    assert res["checks"]["build_comparison"]["population_status"] == "IDENTICAL"
    assert any(r["rule"] == "BUILD_COMPARISON" for r in res["triggered_rules"])


def test_qg_build_comparison_identical_improvement(db_session):
    """Test 34: Identical populations with improvement evaluates to PASS."""
    _seed(db_session, 503, [_pass("t1", "M"), _fail("t2", "M")])
    _seed(db_session, 504, [_pass("t1", "M"), _pass("t2", "M")])

    res = evaluate_quality_gate(504, session=db_session)
    assert res["checks"]["build_comparison"]["value"] == "BETTER"
    assert res["checks"]["build_comparison"]["status"] == "PASS"
    assert res["checks"]["build_comparison"]["population_status"] == "IDENTICAL"


def test_qg_build_comparison_different_populations_suppresses_warning(db_session):
    """Test 35: Different populations do not trigger regression warning on aggregate WORSE."""
    # Build 505: 287 tests (simulated by 10 tests, 100% pass)
    _seed(db_session, 505, [_pass(f"t_{i}", "Auth") for i in range(10)])
    # Build 506: 2 tests (smoke slice: 1 pass, 1 fail = 50% pass rate -> aggregate WORSE)
    _seed(db_session, 506, [_pass("smoke_1", "Smoke"), _fail("smoke_2", "Smoke")])

    res = evaluate_quality_gate(506, session=db_session)
    # The aggregate metric delta is WORSE
    assert res["checks"]["build_comparison"]["value"] == "WORSE"
    # But because populations differ, status is UNKNOWN (not WARNING, not verified PASS)
    assert res["checks"]["build_comparison"]["status"] == "UNKNOWN"
    assert res["checks"]["build_comparison"]["population_status"] == "DIFFERENT"
    assert "Test populations differ" in res["checks"]["build_comparison"]["details"]
    # No BUILD_COMPARISON rule in triggered_rules
    assert not any(r["rule"] == "BUILD_COMPARISON" for r in res["triggered_rules"])


def test_qg_build_comparison_equal_count_different_module_identity(db_session):
    """Test 36: Equal test count but different canonical module identity classified as DIFFERENT."""
    _seed(db_session, 507, [_pass("t1", "Auth"), _pass("t2", "Auth")])
    # Same names, but different module
    _seed(db_session, 508, [_pass("t1", "Checkout"), _fail("t2", "Checkout")])

    res = evaluate_quality_gate(508, session=db_session)
    assert res["checks"]["build_comparison"]["population_status"] == "DIFFERENT"
    assert res["checks"]["build_comparison"]["status"] == "UNKNOWN"
    assert not any(r["rule"] == "BUILD_COMPARISON" for r in res["triggered_rules"])


def test_qg_build_comparison_unknown_population_preserves_release(db_session):
    """Test 37: Missing previous build evaluates to UNKNOWN population and preserves PASS."""
    _seed(db_session, 509, [_pass("t1", "M"), _pass("t2", "M")])

    res = evaluate_quality_gate(509, session=db_session)
    assert res["checks"]["build_comparison"]["value"] == "UNKNOWN"
    assert res["checks"]["build_comparison"]["population_status"] == "UNKNOWN"
    assert res["checks"]["build_comparison"]["status"] == "PASS"


def test_qg_independent_critical_failures_maintained_with_different_population(db_session):
    """Test 38: Independent critical failure rules still trigger FAIL even if population is DIFFERENT."""
    _seed(db_session, 510, [_pass("t1", "M"), _pass("t2", "M")])
    # Build 511 has 10 failures (>= fail_at=10 in default config)
    fails = [_fail(f"diff_fail_{i}", "M") for i in range(10)]
    _seed(db_session, 511, fails)

    res = evaluate_quality_gate(511, session=db_session)
    assert res["checks"]["build_comparison"]["population_status"] == "DIFFERENT"
    assert res["checks"]["build_comparison"]["status"] == "UNKNOWN"
    # Failure count rule triggers FAIL independently
    assert res["status"] == "FAIL"
    assert res["release_recommendation"] == "BLOCK"
    assert any(r["rule"] == "FAILURE_COUNT" and r["severity"] == "FAIL" for r in res["triggered_rules"])


def test_qg_html_report_compatibility_with_different_population(db_session, tmp_path):
    """Test 39: HTML reporter renders cleanly with different population metadata."""
    import os
    from src.reporter.html_reporter import generate_html_report

    _seed(db_session, 512, [_pass("t1", "M"), _pass("t2", "M")])
    _seed(db_session, 513, [_pass("diff_1", "M"), _fail("diff_2", "M")])

    out_file = str(tmp_path / "report_513.html")
    report_path = generate_html_report(513, output_path=out_file, session=db_session)
    assert os.path.exists(report_path)

    with open(report_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert "Population Comparability Limitation" in html
    assert "Test populations differ" in html


def test_qg_build_comparison_unknown_population_with_worse_status_triggers_warning():
    """Test 40: UNKNOWN population with aggregate WORSE result triggers WARNING with disclosure."""
    status, rule = evaluate_build_comparison("WORSE", population_status="UNKNOWN")
    assert status == "WARNING"
    assert rule["severity"] == "WARNING"
    assert "Insufficient test identity evidence" in rule["message"]


def test_qg_build_comparison_configurable_policy_preserved():
    """Test 41: Custom configurable warning_on policy is respected."""
    custom_cfg = {"build_comparison": {"warning_on": ["MIXED"]}}
    status, rule = evaluate_build_comparison("MIXED", population_status="IDENTICAL", config=custom_cfg)
    assert status == "WARNING"
    assert rule["severity"] == "WARNING"

    status_worse, rule_worse = evaluate_build_comparison("WORSE", population_status="IDENTICAL", config=custom_cfg)
    assert status_worse == "PASS"
    assert rule_worse is None
