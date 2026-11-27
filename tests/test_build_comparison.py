"""
Step 5 — Build Comparison Tests

All 24 tests use an isolated in-memory SQLite database.
No production database is touched.
"""
import pytest
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.database import Base
from src.database.repository import (
    save_build_result,
    BuildNotFoundError,
)
from src.analyzer.build_comparison import (
    compare_builds,
    compare_with_previous_build,
    NoPreviousBuildError,
)


# ---------------------------------------------------------------------------
# Shared fixture: isolated in-memory SQLite session
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    """Provides a fresh in-memory SQLite session for each test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Helper: quickly seed builds into the test DB
# ---------------------------------------------------------------------------

def _make_summary(build_num: int, total: int, passed: int, failed: int, skipped: int) -> dict:
    pass_rate    = round(passed / total * 100, 2) if total else 0.0
    failure_rate = round(failed / total * 100, 2) if total else 0.0
    return {
        "build":        build_num,
        "total":        total,
        "passed":       passed,
        "failed":       failed,
        "skipped":      skipped,
        "pass_rate":    pass_rate,
        "failure_rate": failure_rate,
    }


def _make_df(rows: list, build_num: int) -> pd.DataFrame:
    """
    rows: list of (test_name, module, status, error) tuples.
    """
    data = [
        {
            "test_name": r[0],
            "module":    r[1],
            "status":    r[2],
            "duration":  1.0,
            "error":     r[3],
            "build":     build_num,
        }
        for r in rows
    ]
    return pd.DataFrame(data)


def _seed_build(session, build_num, rows):
    """Seeds a build and its test rows. Returns the saved Build."""
    total   = len(rows)
    passed  = sum(1 for r in rows if r[2] == "PASS")
    failed  = sum(1 for r in rows if r[2] == "FAIL")
    skipped = sum(1 for r in rows if r[2] == "SKIP")
    summary = _make_summary(build_num, total, passed, failed, skipped)
    df      = _make_df(rows, build_num)
    return save_build_result(summary, df, session=session)


# ---------------------------------------------------------------------------
# Test 1: Pass rate improvement detected in summary
# ---------------------------------------------------------------------------

def test_pass_rate_improvement(db_session):
    _seed_build(db_session, 100, [
        ("t1", "M", "PASS", None), ("t2", "M", "FAIL", "Err"),  # 50%
    ])
    _seed_build(db_session, 101, [
        ("t1", "M", "PASS", None), ("t2", "M", "PASS", None),  # 100%
    ])
    report = compare_builds(100, 101, session=db_session)
    assert report["summary"]["pass_rate"]["difference"] > 0
    assert report["summary"]["pass_rate"]["current"] > report["summary"]["pass_rate"]["previous"]


# ---------------------------------------------------------------------------
# Test 2: Pass rate decrease detected in summary
# ---------------------------------------------------------------------------

def test_pass_rate_decrease(db_session):
    _seed_build(db_session, 100, [
        ("t1", "M", "PASS", None), ("t2", "M", "PASS", None),  # 100%
    ])
    _seed_build(db_session, 101, [
        ("t1", "M", "PASS", None), ("t2", "M", "FAIL", "Err"),  # 50%
    ])
    report = compare_builds(100, 101, session=db_session)
    assert report["summary"]["pass_rate"]["difference"] < 0


# ---------------------------------------------------------------------------
# Test 3: Failure count improvement
# ---------------------------------------------------------------------------

def test_failure_count_improvement(db_session):
    _seed_build(db_session, 100, [
        ("t1", "M", "FAIL", "Err"), ("t2", "M", "FAIL", "Err"), ("t3", "M", "PASS", None),
    ])
    _seed_build(db_session, 101, [
        ("t1", "M", "PASS", None), ("t2", "M", "PASS", None), ("t3", "M", "PASS", None),
    ])
    report = compare_builds(100, 101, session=db_session)
    assert report["summary"]["failed"]["difference"] < 0
    assert report["summary"]["failed"]["current"] < report["summary"]["failed"]["previous"]


# ---------------------------------------------------------------------------
# Test 4: Failure count worsening
# ---------------------------------------------------------------------------

def test_failure_count_worsening(db_session):
    _seed_build(db_session, 100, [
        ("t1", "M", "PASS", None), ("t2", "M", "PASS", None),
    ])
    _seed_build(db_session, 101, [
        ("t1", "M", "FAIL", "Err"), ("t2", "M", "FAIL", "Err"),
    ])
    report = compare_builds(100, 101, session=db_session)
    assert report["summary"]["failed"]["difference"] > 0


# ---------------------------------------------------------------------------
# Test 5: Overall BETTER
# ---------------------------------------------------------------------------

def test_overall_better(db_session):
    _seed_build(db_session, 200, [
        ("t1", "M", "PASS", None), ("t2", "M", "FAIL", "Err"),  # 50% pass, 1 fail
    ])
    _seed_build(db_session, 201, [
        ("t1", "M", "PASS", None), ("t2", "M", "PASS", None),  # 100% pass, 0 fail
    ])
    report = compare_builds(200, 201, session=db_session)
    assert report["overall_status"] == "BETTER"


# ---------------------------------------------------------------------------
# Test 6: Overall WORSE
# ---------------------------------------------------------------------------

def test_overall_worse(db_session):
    _seed_build(db_session, 200, [
        ("t1", "M", "PASS", None), ("t2", "M", "PASS", None),  # 100% pass, 0 fail
    ])
    _seed_build(db_session, 201, [
        ("t1", "M", "PASS", None), ("t2", "M", "FAIL", "Err"),  # 50% pass, 1 fail
    ])
    report = compare_builds(200, 201, session=db_session)
    assert report["overall_status"] == "WORSE"


# ---------------------------------------------------------------------------
# Test 7: Overall SAME
# ---------------------------------------------------------------------------

def test_overall_same(db_session):
    rows = [("t1", "M", "PASS", None), ("t2", "M", "FAIL", "Err")]
    _seed_build(db_session, 200, rows)
    _seed_build(db_session, 201, rows)
    report = compare_builds(200, 201, session=db_session)
    assert report["overall_status"] == "SAME"


# ---------------------------------------------------------------------------
# Test 8: Overall MIXED (pass rate up but failures also up)
# ---------------------------------------------------------------------------

def test_overall_mixed(db_session):
    # Build 200: 1/3 passed (33%), 2 failed
    _seed_build(db_session, 200, [
        ("t1", "M", "PASS", None),
        ("t2", "M", "FAIL", "Err"),
        ("t3", "M", "FAIL", "Err"),
    ])
    # Build 201: 2/4 passed (50% — rate up), 2 failed (same count)
    # Wait, MIXED needs pass_rate up AND failures not down (or vice versa).
    # Let's do: pass_rate improves but failure count also increases
    # prev: 2 pass / 4 total = 50%, 2 fail
    # curr: 3 pass / 5 total = 60%, 2 fail -> SAME on failures but MIXED? No — SAME needs both flat.
    # Best MIXED: pass_rate improves BUT failures also increase.
    _seed_build(db_session, 201, [
        ("t1", "M", "PASS", None),
        ("t2", "M", "PASS", None),   # t2 recovered
        ("t3", "M", "FAIL", "Err"),  # persistent
        ("t4", "M", "FAIL", "Err"),  # new failure — failures went UP
        ("t5", "M", "FAIL", "Err"),  # new failure — failures went UP
    ])
    # prev: 33.33% pass, 2 fail   curr: 40% pass, 3 fail → pass_rate up, failures up → MIXED
    report = compare_builds(200, 201, session=db_session)
    assert report["overall_status"] == "MIXED"


# ---------------------------------------------------------------------------
# Test 9: Module failure increase
# ---------------------------------------------------------------------------

def test_module_failure_increase(db_session):
    _seed_build(db_session, 300, [
        ("t1", "Payment", "FAIL", "Err"),
    ])
    _seed_build(db_session, 301, [
        ("t1", "Payment", "FAIL", "Err"),
        ("t2", "Payment", "FAIL", "Err"),
    ])
    report = compare_builds(300, 301, session=db_session)
    assert report["module_comparison"]["Payment"]["trend"] == "WORSE"
    assert report["module_comparison"]["Payment"]["difference"] > 0


# ---------------------------------------------------------------------------
# Test 10: Module failure decrease
# ---------------------------------------------------------------------------

def test_module_failure_decrease(db_session):
    _seed_build(db_session, 300, [
        ("t1", "Checkout", "FAIL", "Err"),
        ("t2", "Checkout", "FAIL", "Err"),
    ])
    _seed_build(db_session, 301, [
        ("t1", "Checkout", "PASS", None),
        ("t2", "Checkout", "FAIL", "Err"),
    ])
    report = compare_builds(300, 301, session=db_session)
    assert report["module_comparison"]["Checkout"]["trend"] == "BETTER"
    assert report["module_comparison"]["Checkout"]["difference"] < 0


# ---------------------------------------------------------------------------
# Test 11: Module failure unchanged
# ---------------------------------------------------------------------------

def test_module_failure_unchanged(db_session):
    _seed_build(db_session, 300, [("t1", "Login", "FAIL", "Err")])
    _seed_build(db_session, 301, [("t1", "Login", "FAIL", "Err")])
    report = compare_builds(300, 301, session=db_session)
    assert report["module_comparison"]["Login"]["trend"] == "SAME"
    assert report["module_comparison"]["Login"]["difference"] == 0


# ---------------------------------------------------------------------------
# Test 12: Module exists only in current build (previous value = 0)
# ---------------------------------------------------------------------------

def test_module_only_in_current_build(db_session):
    _seed_build(db_session, 300, [("t1", "Auth", "PASS", None)])
    _seed_build(db_session, 301, [
        ("t1", "Auth", "PASS", None),
        ("t2", "NewModule", "FAIL", "Err"),
    ])
    report = compare_builds(300, 301, session=db_session)
    assert "NewModule" in report["module_comparison"]
    assert report["module_comparison"]["NewModule"]["previous"] == 0
    assert report["module_comparison"]["NewModule"]["current"] == 1
    assert report["module_comparison"]["NewModule"]["trend"] == "WORSE"


# ---------------------------------------------------------------------------
# Test 13: Module exists only in previous build (current value = 0)
# ---------------------------------------------------------------------------

def test_module_only_in_previous_build(db_session):
    _seed_build(db_session, 300, [
        ("t1", "Auth", "PASS", None),
        ("t2", "OldModule", "FAIL", "Err"),
    ])
    _seed_build(db_session, 301, [("t1", "Auth", "PASS", None)])
    report = compare_builds(300, 301, session=db_session)
    assert "OldModule" in report["module_comparison"]
    assert report["module_comparison"]["OldModule"]["previous"] == 1
    assert report["module_comparison"]["OldModule"]["current"] == 0
    assert report["module_comparison"]["OldModule"]["trend"] == "BETTER"


# ---------------------------------------------------------------------------
# Test 14: Newly failing test detection
# ---------------------------------------------------------------------------

def test_newly_failing_test_detection(db_session):
    _seed_build(db_session, 400, [("t1", "M", "PASS", None), ("t2", "M", "PASS", None)])
    _seed_build(db_session, 401, [("t1", "M", "PASS", None), ("t2", "M", "FAIL", "Err")])
    report = compare_builds(400, 401, session=db_session)
    assert "t2" in report["newly_failing_tests"]
    assert "t1" not in report["newly_failing_tests"]


# ---------------------------------------------------------------------------
# Test 15: Recovered test detection
# ---------------------------------------------------------------------------

def test_recovered_test_detection(db_session):
    _seed_build(db_session, 400, [("t1", "M", "FAIL", "Err"), ("t2", "M", "PASS", None)])
    _seed_build(db_session, 401, [("t1", "M", "PASS", None), ("t2", "M", "PASS", None)])
    report = compare_builds(400, 401, session=db_session)
    assert "t1" in report["recovered_tests"]
    assert "t2" not in report["recovered_tests"]


# ---------------------------------------------------------------------------
# Test 16: Persistent failure detection
# ---------------------------------------------------------------------------

def test_persistent_failure_detection(db_session):
    _seed_build(db_session, 400, [("t1", "M", "FAIL", "Err"), ("t2", "M", "PASS", None)])
    _seed_build(db_session, 401, [("t1", "M", "FAIL", "Err"), ("t2", "M", "PASS", None)])
    report = compare_builds(400, 401, session=db_session)
    assert "t1" in report["persistent_failures"]
    assert "t2" not in report["persistent_failures"]


# ---------------------------------------------------------------------------
# Test 17: Added test detection (in current, not in previous)
# ---------------------------------------------------------------------------

def test_added_test_detection(db_session):
    _seed_build(db_session, 400, [("t1", "M", "PASS", None)])
    _seed_build(db_session, 401, [("t1", "M", "PASS", None), ("t_new", "M", "PASS", None)])
    report = compare_builds(400, 401, session=db_session)
    assert "t_new" in report["tests_added"]
    assert "t1" not in report["tests_added"]
    assert report["tests_removed"] == []


# ---------------------------------------------------------------------------
# Test 18: Removed test detection (in previous, not in current)
# ---------------------------------------------------------------------------

def test_removed_test_detection(db_session):
    _seed_build(db_session, 400, [("t1", "M", "PASS", None), ("t_old", "M", "PASS", None)])
    _seed_build(db_session, 401, [("t1", "M", "PASS", None)])
    report = compare_builds(400, 401, session=db_session)
    assert "t_old" in report["tests_removed"]
    assert "t1" not in report["tests_removed"]
    assert report["tests_added"] == []


# ---------------------------------------------------------------------------
# Test 19: Missing build raises BuildNotFoundError
# ---------------------------------------------------------------------------

def test_missing_build_raises_error(db_session):
    _seed_build(db_session, 400, [("t1", "M", "PASS", None)])
    with pytest.raises(BuildNotFoundError, match="Build 999 not found"):
        compare_builds(400, 999, session=db_session)

    with pytest.raises(BuildNotFoundError, match="Build 998 not found"):
        compare_builds(998, 400, session=db_session)


# ---------------------------------------------------------------------------
# Test 20: Automatic previous build selection
# ---------------------------------------------------------------------------

def test_automatic_previous_build_selection(db_session):
    _seed_build(db_session, 100, [("t1", "M", "FAIL", "Err")])
    _seed_build(db_session, 101, [("t1", "M", "PASS", None)])
    report = compare_with_previous_build(101, session=db_session)
    assert report["previous_build"] == 100
    assert report["current_build"] == 101


# ---------------------------------------------------------------------------
# Test 21: Automatic selection with non-sequential build numbers
# ---------------------------------------------------------------------------

def test_auto_selection_non_sequential_builds(db_session):
    # Stored: 243, 245, 250
    _seed_build(db_session, 243, [("t1", "M", "PASS", None)])
    _seed_build(db_session, 245, [("t1", "M", "PASS", None)])
    _seed_build(db_session, 250, [("t1", "M", "PASS", None)])
    # For build 250, previous should be 245, not 249
    report = compare_with_previous_build(250, session=db_session)
    assert report["previous_build"] == 245
    assert report["current_build"] == 250


# ---------------------------------------------------------------------------
# Test 22: First build has no previous build → NoPreviousBuildError
# ---------------------------------------------------------------------------

def test_first_build_no_previous(db_session):
    _seed_build(db_session, 500, [("t1", "M", "PASS", None)])
    with pytest.raises(NoPreviousBuildError, match="No previous build available"):
        compare_with_previous_build(500, session=db_session)


# ---------------------------------------------------------------------------
# Test 23: Deterministic alphabetical ordering
# ---------------------------------------------------------------------------

def test_alphabetical_ordering(db_session):
    _seed_build(db_session, 600, [
        ("test_z", "Zeta", "FAIL", "Err"),
        ("test_a", "Alpha", "FAIL", "Err"),
        ("test_m", "Mu", "FAIL", "Err"),
    ])
    _seed_build(db_session, 601, [
        ("test_z", "Zeta", "PASS", None),
        ("test_a", "Alpha", "FAIL", "Err"),
        ("test_m", "Mu", "FAIL", "Err"),
        ("test_new", "Zeta", "FAIL", "Err"),
    ])
    report = compare_builds(600, 601, session=db_session)
    # Module comparison keys should be alphabetically sorted
    module_keys = list(report["module_comparison"].keys())
    assert module_keys == sorted(module_keys)
    # Newly failing tests should be alphabetically sorted
    assert report["newly_failing_tests"] == sorted(report["newly_failing_tests"])
    # Recovered tests alphabetical
    assert report["recovered_tests"] == sorted(report["recovered_tests"])
    # Persistent failures alphabetical
    assert report["persistent_failures"] == sorted(report["persistent_failures"])
    # Added tests alphabetical
    assert report["tests_added"] == sorted(report["tests_added"])


# ---------------------------------------------------------------------------
# Test 24: Duplicate current build does not break comparison
# ---------------------------------------------------------------------------

def test_duplicate_current_build_does_not_break_comparison(db_session):
    """
    If the current build is already stored (DuplicateBuildError suppressed in main.py),
    compare_with_previous_build should still work using the stored data.
    """
    _seed_build(db_session, 700, [("t1", "M", "FAIL", "Err")])
    _seed_build(db_session, 701, [("t1", "M", "PASS", None)])
    # Build 701 is already stored; comparison should succeed
    report = compare_with_previous_build(701, session=db_session)
    assert report["previous_build"] == 700
    assert report["current_build"] == 701
    assert report["overall_status"] == "BETTER"


# ---------------------------------------------------------------------------
# Test 25: Build population comparability evaluation
# ---------------------------------------------------------------------------

def test_population_comparability_identical_vs_different(db_session):
    """
    Evaluates that builds with identical test identities report IDENTICAL population status,
    while builds with different populations report DIFFERENT and provide comparability notes.
    """
    # Identical populations (t1, t2 in both)
    _seed_build(db_session, 800, [("t1", "M", "FAIL", "Err"), ("t2", "M", "PASS", None)])
    _seed_build(db_session, 801, [("t1", "M", "PASS", None), ("t2", "M", "PASS", None)])

    rep_identical = compare_builds(800, 801, session=db_session)
    assert rep_identical["population_status"] == "IDENTICAL"
    assert rep_identical["is_comparable"] is True
    assert rep_identical["comparability_note"] is None

    # Different populations (t3 added, t1 removed)
    _seed_build(db_session, 802, [("t2", "M", "PASS", None), ("t3", "M", "PASS", None)])
    rep_different = compare_builds(801, 802, session=db_session)
    assert rep_different["population_status"] == "DIFFERENT"
    assert rep_different["is_comparable"] is False
    assert "Test populations differ" in rep_different["comparability_note"]
    assert "Aggregate pass-rate difference reflects test suite population changes" in rep_different["comparability_note"]
