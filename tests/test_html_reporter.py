"""
Step 10 — HTML Reporter Tests

All tests use temporary output directories and in-memory SQLite database sessions.
No production reports directory or production database is touched.
"""

import os
from pathlib import Path
import pytest
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.database import Base
from src.database.repository import save_build_result
from src.reporter.html_reporter import generate_html_report
from src.analyzer.flaky_detector import detect_flaky_tests


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
def tmp_report_file(tmp_path):
    d = tmp_path / "reports"
    return str(d / "qa_report_test.html")


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
# Tests 1-12: Basic Content & Section Presence
# ---------------------------------------------------------------------------

def test_html_report_file_created(db_session, tmp_report_file):
    """Test 1 & 22: HTML report file and parent directory are created automatically."""
    _seed(db_session, 100, [_pass("t1"), _pass("t2")])
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    assert os.path.exists(path)
    assert os.path.getsize(path) > 0


def test_correct_build_number_appears(db_session, tmp_report_file):
    """Test 2: Correct build number appears in HTML content."""
    _seed(db_session, 246, [_pass("t1")])
    path = generate_html_report(246, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "Build 246" in html


def test_summary_values_appear(db_session, tmp_report_file):
    """Test 3: Summary metrics (total, pass_rate) appear in HTML."""
    _seed(db_session, 100, [_pass("t1"), _pass("t2"), _fail("t3")])
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "Total Tests" in html
    assert "Pass Rate" in html


def test_quality_gate_status_appears(db_session, tmp_report_file):
    """Test 4: Quality Gate status and Release Recommendation appear in HTML."""
    _seed(db_session, 100, [_pass("t1")])
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "Quality Gate" in html
    assert "Release Recommendation" in html


def test_failure_analysis_appears(db_session, tmp_report_file):
    """Test 5: Failure analysis section appears in HTML."""
    _seed(db_session, 100, [_fail("t1", "Pay")])
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "Failure Analysis" in html
    assert "Pay" in html


def test_build_comparison_appears(db_session, tmp_report_file):
    """Test 6: Build comparison section appears when previous build exists."""
    _seed(db_session, 99, [_pass("t1")])
    _seed(db_session, 100, [_pass("t1")])
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "Build Comparison" in html
    assert "Build 99" in html


def test_trend_analysis_appears(db_session, tmp_report_file):
    """Test 7: Trend analysis section appears when 3+ builds exist."""
    for b in range(100, 103):
        _seed(db_session, b, [_pass("t1")])
    path = generate_html_report(102, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "Trend Analysis" in html
    assert "Builds Analyzed" in html


test_risk_analysis_appears = None  # placeholder for index mapping


def test_risk_analysis_section_appears(db_session, tmp_report_file):
    """Test 8: Risk analysis section appears in HTML."""
    _seed(db_session, 100, [_pass("t1", "Auth")])
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "Module Risk Analysis" in html
    assert "Auth" in html


def test_flaky_test_section_appears(db_session, tmp_report_file):
    """Test 9: Flaky test section appears in HTML."""
    _seed(db_session, 100, [_pass("t1")])
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "Flaky Test Analysis" in html


def test_newly_failing_and_recovered_tests_appear(db_session, tmp_report_file):
    """Test 10 & 11: Newly failing and recovered test names appear in comparison section."""
    _seed(db_session, 99, [_pass("t_new_fail"), _fail("t_rec")])
    _seed(db_session, 100, [_fail("t_new_fail"), _pass("t_rec")])
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "t_new_fail" in html
    assert "t_rec" in html


def test_qa_attention_section_appears(db_session, tmp_report_file):
    """Test 12: QA Attention Required section appears."""
    _seed(db_session, 100, [_pass("t1")])
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "QA Attention Required" in html


# ---------------------------------------------------------------------------
# Tests 13-15: Quality Gate Badges & Display
# ---------------------------------------------------------------------------

def test_pass_gate_display(db_session, tmp_report_file):
    """Test 13: Clean build renders PASS badge and PROCEED recommendation."""
    _seed(db_session, 100, [_pass("t1"), _pass("t2")])
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "PASS" in html
    assert "PROCEED" in html


def test_warning_gate_display(db_session, tmp_report_file):
    """Test 14: Build with 93% pass rate renders WARNING and REVIEW."""
    rows = [_pass(f"t{i}") for i in range(93)] + [_fail(f"f{i}") for i in range(7)]
    _seed(db_session, 100, rows)
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "WARNING" in html
    assert "REVIEW" in html


def test_fail_gate_display(db_session, tmp_report_file):
    """Test 15: Build with 80% pass rate renders FAIL and BLOCK."""
    rows = [_pass(f"t{i}") for i in range(80)] + [_fail(f"f{i}") for i in range(20)]
    _seed(db_session, 100, rows)
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "FAIL" in html
    assert "BLOCK" in html


# ---------------------------------------------------------------------------
# Tests 16-20: Missing Data / Empty State Handling
# ---------------------------------------------------------------------------

def test_no_previous_build_handled(db_session, tmp_report_file):
    """Test 16: First build displays friendly message for missing comparison."""
    _seed(db_session, 100, [_pass("t1")])
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "No previous build available for comparison." in html


def test_insufficient_trend_data_handled(db_session, tmp_report_file):
    """Test 17: Fewer than 3 builds displays friendly message for missing trend data."""
    _seed(db_session, 100, [_pass("t1")])
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "Not enough historical data to display trend analysis." in html


def test_no_failures_handled(db_session, tmp_report_file):
    """Test 18: Build with 0 failures displays friendly empty message."""
    _seed(db_session, 100, [_pass("t1"), _pass("t2")])
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "No failing tests in current build." in html


def test_no_flaky_tests_handled(db_session, tmp_report_file):
    """Test 19: No flaky tests displays friendly empty message."""
    for b in range(100, 103):
        _seed(db_session, b, [_pass("t1")])
    path = generate_html_report(102, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "No flaky tests detected." in html


# ---------------------------------------------------------------------------
# Tests 21-24: Escaping, Path & Naming Verification
# ---------------------------------------------------------------------------

def test_special_html_characters_are_escaped(db_session, tmp_report_file):
    """Test 21: Special HTML characters (<, >, &) in test names are properly escaped."""
    rows = [(_pass("<script>alert('xss')</script>")[0], "Mod&Test", "PASS", None)]
    _seed(db_session, 100, rows)
    path = generate_html_report(100, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "<script>alert('xss')</script>" not in html
    assert "&lt;script&gt;" in html or "&amp;" in html


def test_custom_output_path_works(db_session, tmp_path):
    """Test 23: Passing custom output filepath generates report at that location."""
    custom_path = str(tmp_path / "custom_folder" / "my_custom_report.html")
    _seed(db_session, 100, [_pass("t1")])
    res = generate_html_report(100, output_path=custom_path, session=db_session)
    assert res == str(Path(custom_path).resolve())
    assert os.path.exists(res)


def test_step9_flaky_detector_unchanged(db_session):
    """Test 30: Flaky test detector output structure remains identical."""
    _seed(db_session, 100, [_pass("t1")])
    _seed(db_session, 101, [_fail("t1")])
    _seed(db_session, 102, [_pass("t1")])
    flaky = detect_flaky_tests(limit=3, session=db_session)
    assert "flaky_tests" in flaky
    assert "ranked_flaky_tests" in flaky
    assert "t1" in flaky["flaky_tests"]


def test_failed_test_details_rendering(db_session, tmp_report_file):
    """Test 31: Failed test details including test name, module, and error trace render correctly."""
    rows = [
        ("test_checkout_flow", "Checkout", "FAIL", "AssertionError: Expected 200 OK but got 500 Internal Error"),
        ("test_login_auth", "Auth", "PASS", None),
    ]
    _seed(db_session, 105, rows)
    path = generate_html_report(105, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "test_checkout_flow" in html
    assert "Checkout" in html
    assert "AssertionError: Expected 200 OK but got 500 Internal Error" in html


def test_top_kpi_cards_and_badges_render(db_session, tmp_report_file):
    """Test 32: Top KPI cards render Total Tests, Passed, Failed, Skipped, Pass Rate, Quality Gate, Release."""
    _seed(db_session, 106, [_pass("t1"), _fail("t2", "Mod"), _pass("t3")])
    path = generate_html_report(106, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "Total Tests" in html
    assert "Passed" in html
    assert "Failed" in html
    assert "Skipped" in html
    assert "Pass Rate" in html
    assert "Quality Gate" in html
    assert "Release" in html


def test_highest_risk_module_spotlight_renders(db_session, tmp_report_file):
    """Test 33: Highest Risk Module spotlight is rendered in Risky Modules section."""
    rows = [_fail("t_pay", "Payment"), _fail("t_pay2", "Payment"), _pass("t_auth", "Auth")]
    _seed(db_session, 107, rows)
    path = generate_html_report(107, output_path=tmp_report_file, session=db_session)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    assert "Highest Risk Module" in html
    assert "Payment" in html


def test_remediation_presentation_fixes(db_session, tmp_report_file):
    """Test 34: Verifies Unicode arrows, pp terminology, heuristic subtitle, and tie display."""
    # Seed build 108 with tied errors and build 109 with differing population
    rows_108 = [
        ("t1", "Payment", "FAIL", "Payment API Error"),
        ("t2", "Payment", "FAIL", "TimeoutException"),
        ("t3", "Auth", "PASS", None),
    ]
    _seed(db_session, 108, rows_108)

    rows_109 = [
        ("t1", "Payment", "PASS", None),
        ("t2", "Payment", "PASS", None),
        ("t3", "Auth", "PASS", None),
        ("t4_new", "Auth", "PASS", None),
    ]
    _seed(db_session, 109, rows_109)

    # Generate report for build 108
    path_108 = generate_html_report(108, output_path=tmp_report_file, session=db_session)
    with open(path_108, "r", encoding="utf-8") as f:
        html_108 = f.read()

    # 1. Heuristic module risk scoring subtitle
    assert "heuristic module risk scoring (0-100 scale)" in html_108
    assert "defect probability modeling" not in html_108

    # 2. Tied errors display
    assert "Payment API Error, TimeoutException (Tie)" in html_108

    # Generate report for build 109 (comparing against 108)
    tmp_path_109 = tmp_report_file.replace(".html", "_109.html")
    path_109 = generate_html_report(109, output_path=tmp_path_109, session=db_session)
    with open(path_109, "r", encoding="utf-8") as f:
        html_109 = f.read()

    # 3. Unicode arrow rendering - NO literal &amp;rarr;
    assert "&amp;rarr;" not in html_109
    assert "→" in html_109

    # 4. Percentage points (pp) terminology
    assert "pp" in html_109

    # 5. Population Comparability Limitation notice
    assert "Population Comparability Limitation" in html_109
